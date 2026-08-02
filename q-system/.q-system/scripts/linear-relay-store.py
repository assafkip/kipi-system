#!/usr/bin/env python3
"""Durable store for the relay queue. Redis-over-HTTP, same interface as MemoryStore.

WHICH PRODUCT THIS ACTUALLY IS, verified 2026-08-01
---------------------------------------------------
"Vercel KV" is GONE. It was deprecated and every existing store was migrated to
Upstash Redis in Dec 2024; `vercel.com/docs/storage` now lists only Blob, Global
Config, and Marketplace. Writing against the name from memory would have produced code
for a product that no longer exists.

What replaces it is Upstash Redis provisioned THROUGH Vercel Marketplace
(`vercel install upstash`). That still satisfies the one-vendor requirement in the way
that matters: the founder never creates an Upstash account, never copies a credential,
and never sees a second invoice. Vercel auto-provisions the account, injects the
credentials as project env vars, and bills it on the Vercel invoice. Upstash is the
backing provider, not a surface he touches.

Blob was the other first-party candidate and was rejected: it is a file store with no
atomic operations, so building queue semantics on it means hand-rolling the exact
races Redis already solves. Global Config is explicitly read-optimised with writes
measured in SECONDS, which is the wrong primitive for an inbound queue.

THE ENV VAR NAMES ARE A MIGRATION HAZARD
----------------------------------------
The Dec 2024 migration means a project can carry EITHER naming: the legacy
`KV_REST_API_*` pair from the Vercel KV era, or `UPSTASH_REDIS_REST_*` from a fresh
marketplace install. Both are read here, legacy first, because a project migrated from
KV keeps the old names and reading only the new ones would fail on exactly the
projects that have been around longest.
"""
import json
import os
import urllib.error
import urllib.request

KEY_PREFIX = os.environ.get("KIPI_RELAY_PREFIX", "linear:q:")


def _credentials() -> tuple:
    """Return (url, token). Legacy names first -- see the migration note above."""
    url = (os.environ.get("KV_REST_API_URL")
           or os.environ.get("UPSTASH_REDIS_REST_URL") or "")
    token = (os.environ.get("KV_REST_API_TOKEN")
             or os.environ.get("UPSTASH_REDIS_REST_TOKEN") or "")
    return url.rstrip("/"), token


class RedisRestStore:
    """Upstash's HTTP Redis API behind the MemoryStore interface.

    The transport is injectable for the same reason every other outbound edge in this
    fleet is: a suite that needed a live Redis would either not run or would write to
    the founder's real queue, and neither is acceptable. Default is the real thing.
    """

    def __init__(self, url: str = None, token: str = None, transport=None):
        cred_url, cred_token = _credentials()
        self.url = (url or cred_url).rstrip("/")
        self.token = token or cred_token
        self._transport = transport or self._http

    def _http(self, command: list):
        req = urllib.request.Request(
            self.url,
            data=json.dumps(command).encode(),
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    def _cmd(self, *args):
        """Every Redis call goes through here. Returns the `result` field or None.

        Errors are returned as None rather than raised. A store that throws would take
        down the webhook handler, and Linear would retry into a 5xx loop -- but the
        CALLERS must therefore treat None as failure, not as 'key absent'. `has()` is
        the one place that distinction is load-bearing, so it is documented there.
        """
        try:
            out = self._transport([str(a) for a in args])
        except (urllib.error.URLError, OSError, ValueError):
            return None
        if isinstance(out, dict) and "error" in out:
            return None
        return out.get("result") if isinstance(out, dict) else out

    def put(self, key, value):
        return self._cmd("SET", KEY_PREFIX + key, value) is not None

    def get(self, key):
        return self._cmd("GET", KEY_PREFIX + key)

    def has(self, key):
        # A transport failure returns None -> falsy -> reads as "not present", which
        # would let a duplicate through. That is the SAFE direction: a duplicated run
        # is recoverable, a dropped delegation is not. Stated so the next reader does
        # not "fix" it into failing closed.
        return bool(self._cmd("EXISTS", KEY_PREFIX + key))

    def delete(self, key):
        return self._cmd("DEL", KEY_PREFIX + key)

    def keys(self):
        raw = self._cmd("KEYS", KEY_PREFIX + "*") or []
        # Strip the prefix so callers deal in logical keys and never learn the
        # namespace. KEYS is O(N) and unsafe on a big Redis; it is fine here only
        # because MAX_QUEUE_DEPTH caps N at 200 and this store holds nothing else.
        return [k[len(KEY_PREFIX):] if k.startswith(KEY_PREFIX) else k for k in raw]

    def count(self):
        return len(self.keys())
