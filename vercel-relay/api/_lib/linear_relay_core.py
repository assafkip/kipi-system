#!/usr/bin/env python3
"""Durable inbound queue for Linear agent delegations. The logic half of the relay.

WHY A QUEUE AND NOT A FORWARDER
-------------------------------
A tunnel forwards in real time, so a delegation arriving while the Mac is asleep is
LOST -- Linear retries a handful of times and gives up. A lost delegation looks
exactly like Sana ignoring the founder, which is the silent-success failure shape this
fleet keeps hitting (2026-07-30 budget day; the token expiry earlier tonight). So the
public endpoint accepts and PERSISTS; the Mac drains when it is awake.

THE PUBLIC-ENDPOINT OBLIGATIONS
-------------------------------
This is an unauthenticated inbound URL with storage behind it. Two things are
therefore not optional:

1. SIGNATURE VERIFICATION AT THE EDGE. Anything unsigned is refused before it can
   consume a byte of storage. Verification also happens again on the Mac, because the
   relay is a second machine and "the relay said it was fine" is not evidence. The raw
   body is stored BYTE-EXACT with its signature header for exactly this reason: Linear
   signs raw bytes, so re-serializing the JSON anywhere in the path destroys the
   digest and makes the Mac-side check impossible.

2. A BOUND ON GROWTH. An unbounded queue behind a public URL is its own outage.
   The bound here is deliberately NOT "drop the oldest": silently evicting a real
   delegation is the failure we are building this to prevent. Instead a full queue
   REFUSES new work with 503, which Linear treats as retryable, and pages. Normal
   depth is a handful (one per delegation while asleep); hitting the cap means
   something is wrong and a human should hear about it, not have it smoothed over.

Stale entries expire on drain rather than on write, because a delegation from
yesterday firing today is its own kind of wrong.

Storage is behind a seam so the suite never needs a live Redis and production never
needs a fake. Same convention as the rest of these scripts.
"""
import json
import os
import time

MAX_QUEUE_DEPTH = int(os.environ.get("KIPI_RELAY_MAX_DEPTH", "200"))
# A delegation older than this is not worth running. Linear's own session would be
# long dead, and firing a run for it would surprise whoever filed it.
MAX_AGE_SECONDS = int(os.environ.get("KIPI_RELAY_MAX_AGE", str(24 * 3600)))


class MemoryStore:
    """Reference implementation and the one the suite drives. Ordered by insertion."""

    def __init__(self):
        self._items = {}

    def put(self, key, value):
        self._items[key] = value

    def get(self, key):
        return self._items.get(key)

    def has(self, key):
        return key in self._items

    def delete(self, key):
        self._items.pop(key, None)

    def keys(self):
        return list(self._items.keys())

    def count(self):
        return len(self._items)


def dedupe_key(payload: dict) -> str:
    """Identity of a delegation for retry-collapsing purposes.

    Linear retries anything it thinks failed, so the SAME event can arrive several
    times. Without this, one delegation becomes several runs of the same issue against
    the same worktree -- the identical hazard the receiver's 5-second ack rule exists
    to prevent, arriving by a different road.

    Keyed on session + action rather than on a random id: a `created` and a later
    `prompted` on one session are genuinely different work and must both survive.
    """
    session = (payload.get("agentSession") or {}).get("id") or ""
    action = payload.get("action") or ""
    return f"{session}:{action}"


def admit(raw_body: bytes, signature: str, secret: str, store, verify_fn,
          now: float = None) -> tuple:
    """Edge admission. Returns (http_status, reason). Never raises.

    Order is deliberate and each step is cheaper than the next:
    verify -> parse -> dedupe -> bound -> persist. A forged payload must not reach
    the depth check, or an attacker can fill the queue with garbage and DoS the
    founder's real delegations by making them 503.
    """
    now = now if now is not None else time.time()

    ok, reason = verify_fn(raw_body, signature, secret, now_ms=int(now * 1000))
    if not ok:
        # 401, not 5xx. Linear retries 5xx, and retrying a forged event forever is
        # not a behaviour worth having.
        return 401, f"rejected: {reason}"

    try:
        payload = json.loads(raw_body)
    except ValueError:
        return 400, "body is not JSON"

    if payload.get("type") != "AgentSessionEvent":
        # Accepted and discarded on purpose. Returning non-200 would make Linear
        # retry an event we will never want.
        return 200, "ignored: not an AgentSessionEvent"

    key = dedupe_key(payload)
    if store.has(key):
        return 200, "duplicate: already queued"

    if store.count() >= MAX_QUEUE_DEPTH:
        # 503 so Linear retries, rather than 200-and-drop which loses the delegation
        # silently. The caller pages on this reason.
        return 503, f"queue full ({store.count()}/{MAX_QUEUE_DEPTH}) -- refusing, not dropping"

    store.put(key, json.dumps({
        # BYTE-EXACT body. Stored as latin-1 text so it survives a JSON round trip
        # without a single byte changing -- re-encoding would break the HMAC the Mac
        # is going to check independently.
        "raw": raw_body.decode("latin-1"),
        "signature": signature,
        "received_at": now,
    }))
    return 200, "queued"


def drain(store, now: float = None, max_age: int = None) -> tuple:
    """Return (fresh_events, expired_count). Expiry happens HERE, not on write.

    Each event carries its raw bytes and signature so the consumer verifies for
    itself. The relay's verdict is never the consumer's evidence.
    """
    now = now if now is not None else time.time()
    max_age = max_age if max_age is not None else MAX_AGE_SECONDS

    fresh, expired = [], 0
    for key in store.keys():
        try:
            item = json.loads(store.get(key))
        except (ValueError, TypeError):
            store.delete(key)          # unparseable is not recoverable; drop and move
            expired += 1
            continue

        if now - item.get("received_at", 0) > max_age:
            store.delete(key)
            expired += 1
            continue

        fresh.append({
            "key": key,
            "raw": item["raw"].encode("latin-1"),
            "signature": item.get("signature", ""),
            "received_at": item["received_at"],
        })

    fresh.sort(key=lambda e: e["received_at"])   # oldest first; delegation order matters
    return fresh, expired


def ack(store, key: str) -> None:
    """Remove ONLY after the consumer has finished with it.

    Deleting at read time would lose the event if the Mac died mid-run, which is the
    same lost-delegation outcome the queue exists to prevent.
    """
    store.delete(key)
