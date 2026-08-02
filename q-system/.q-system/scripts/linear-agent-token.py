#!/usr/bin/env python3
"""OAuth token store + refresh for the Sana Linear agent. ONE writer, loud on failure.

WHY THIS EXISTS
---------------
Linear access tokens live 24 hours ("expires_in": 86399). With no rotation the agent
goes silent once a day, and a silent agent is the worst failure shape we have: the
board looks calm, delegations sit unanswered, and nothing pages. Same class as the
2026-07-30 budget day, where runs exited 0 having done nothing and read as success.

THE ROTATION HAZARD IS THE REASON FOR THE LOCK
----------------------------------------------
Linear ROTATES the refresh token: "a new valid access token and a new refresh token
will be returned." The moment a refresh succeeds, the refresh token we sent is DEAD.
If the new pair is not durably on disk before we act on it, we have destroyed the only
credential that can get another one, and recovery costs the founder a re-authorization
-- the precise cost this whole design is built to avoid spending twice.

So: one writer, one lock, atomic replace, and the write happens BEFORE the new access
token is handed to any caller. A crash between refresh and persist must lose the RUN,
never the CREDENTIAL.

FAILURE IS LOUD, NEVER SILENT
-----------------------------
Every terminal failure pages through the founder-notification channel. Note that
slack-notify.sh is a deliberate silent no-op when unconfigured and always exits 0 --
so "we called it" can never be proven by an exit code. The KIPI_NOTIFY seam exists so
the suite can assert WHAT was paged by reading a file.

Seams (unset in production; defaults are real):
  KIPI_LINEAR_OAUTH_URL     token endpoint   (default: real Linear)
  KIPI_LINEAR_AGENT_STATE   state dir        (default: ~/.config/kipi)
  KIPI_NOTIFY               pager            (default: real slack-notify.sh)

Usage:
  linear-agent-token.py get        # print a valid access token, refreshing if needed
  linear-agent-token.py status     # human-readable expiry, no refresh
  linear-agent-token.py store      # read a token-exchange JSON on stdin and save it
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

OAUTH_URL = os.environ.get("KIPI_LINEAR_OAUTH_URL", "https://api.linear.app/oauth/token")
STATE_DIR = Path(os.environ.get("KIPI_LINEAR_AGENT_STATE", os.path.expanduser("~/.config/kipi")))
NOTIFY = os.environ.get("KIPI_NOTIFY", str(SCRIPT_DIR / "slack-notify.sh"))

# Refresh an hour early. Not cosmetic: a token that expires mid-run would fail the
# closing `response` activity and strand the Linear thread in `active` forever, which
# looks to the founder exactly like the agent ignored him.
REFRESH_SKEW_SECONDS = 3600

_LOCK = threading.Lock()


class TokenError(Exception):
    """Terminal. The caller must stop, not retry."""


class ReauthRequired(TokenError):
    """The refresh token is dead. Only the founder can fix this, with clicks."""


def _token_file() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / "linear-agent-token.json"


def page(msg: str) -> None:
    """Loud channel. Never raises -- a pager that can crash the caller is a liability."""
    try:
        subprocess.run([NOTIFY, msg], timeout=20, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass
    print(f"PAGE: {msg}", file=sys.stderr)


def load() -> dict:
    try:
        return json.loads(_token_file().read_text())
    except FileNotFoundError:
        raise ReauthRequired(
            "no Linear agent token on disk -- the OAuth app has never been authorized")
    except ValueError:
        raise TokenError("token file is corrupt")


def save(tokens: dict) -> None:
    """THE only writer of the credential file. Atomic, 0600, lock-held.

    tmp-then-replace because a truncated credential file is indistinguishable from a
    revoked one, and the recovery for both is a founder re-authorization.
    """
    with _LOCK:
        path = _token_file()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tokens, indent=2))
        os.chmod(tmp, 0o600)          # a credential, not a log
        os.replace(tmp, path)         # atomic within a filesystem
        # fsync the DIRECTORY so the rename itself survives a power loss, not just
        # the bytes. Losing the rotated refresh token costs founder clicks.
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _exchange(body: dict) -> dict:
    data = urllib.parse.urlencode(body).encode()
    req = urllib.request.Request(OAUTH_URL, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode()[:300]
        except OSError:
            pass
        # 400 invalid_grant means the refresh token is gone for good. Retrying that
        # forever is how a dead agent stays quiet; it is a founder-action state.
        if exc.code in (400, 401):
            raise ReauthRequired(f"refresh rejected ({exc.code}): {detail}")
        raise TokenError(f"token endpoint HTTP {exc.code}: {detail}")
    except (urllib.error.URLError, OSError) as exc:
        # environmental-trigger, not latent-defect (self-healing-retry rule 5):
        # surface immediately, do not burn retries against a down network.
        raise TokenError(f"token endpoint unreachable: {exc}")
    except ValueError:
        raise TokenError("token endpoint returned non-JSON")


def _normalize(resp: dict, previous: dict) -> dict:
    if not resp.get("access_token"):
        raise TokenError(f"token response has no access_token: {list(resp)}")
    now = int(time.time())
    return {
        "access_token": resp["access_token"],
        # Linear rotates, but fall back to the old one if a response ever omits it --
        # dropping a still-valid refresh token to None would lock us out on the next
        # cycle for no reason.
        "refresh_token": resp.get("refresh_token") or previous.get("refresh_token"),
        "expires_at": now + int(resp.get("expires_in", 86399)),
        "obtained_at": now,
        "scope": resp.get("scope", previous.get("scope", "")),
    }


def store_exchange(resp: dict) -> dict:
    """Persist a first-time authorization-code exchange."""
    tokens = _normalize(resp, {})
    save(tokens)
    return tokens


def refresh(tokens: dict, client_id: str = None, client_secret: str = None) -> dict:
    """Rotate. Persists the new pair BEFORE returning it. Pages on terminal failure."""
    rt = tokens.get("refresh_token")
    if not rt:
        page("Linear agent: no refresh token stored. Sana cannot renew and is now "
             "offline until the OAuth app is re-authorized.")
        raise ReauthRequired("no refresh_token stored")

    body = {"grant_type": "refresh_token", "refresh_token": rt}
    cid = client_id or os.environ.get("KIPI_LINEAR_CLIENT_ID", "")
    sec = client_secret or os.environ.get("KIPI_LINEAR_CLIENT_SECRET", "")
    if cid:
        body["client_id"] = cid
    if sec:
        body["client_secret"] = sec

    try:
        resp = _exchange(body)
    except ReauthRequired as exc:
        page(f"Linear agent: token refresh REJECTED ({exc}). Sana is offline until you "
             f"re-authorize the OAuth app. Delegations will sit unanswered until then.")
        raise
    except TokenError as exc:
        page(f"Linear agent: token refresh failed ({exc}). Sana may go offline within "
             f"the hour if this does not clear.")
        raise

    new = _normalize(resp, tokens)
    # PERSIST BEFORE USE. The token we just spent is already dead server-side; if this
    # write does not land, the replacement is lost and only the founder can recover it.
    save(new)
    return new


def ensure_fresh(now: int = None) -> str:
    """The chokepoint every caller uses. Returns a valid access token."""
    now = now if now is not None else int(time.time())
    # A MISSING or corrupt token file must page, not just raise. This path shipped
    # silent: `load()` raised, main() printed to stderr, exit 3, and nobody was told --
    # the agent was simply offline and the board looked calm. The suite hid it too,
    # because the assertion was "paged OR stderr mentions it" and stderr always does.
    # Paging happens HERE rather than in load() so `status` stays a quiet read.
    try:
        tokens = load()
    except ReauthRequired as exc:
        page(f"Linear agent: {exc}. Sana is OFFLINE -- delegations will sit unanswered "
             f"until the OAuth app is authorized.")
        raise
    except TokenError as exc:
        page(f"Linear agent: {exc}. Sana is OFFLINE until the token store is repaired.")
        raise

    if not tokens.get("access_token"):
        page("Linear agent: token file has no access_token. Sana is offline.")
        raise ReauthRequired("no access_token stored")

    if tokens.get("expires_at", 0) - now > REFRESH_SKEW_SECONDS:
        return tokens["access_token"]

    return refresh(tokens)["access_token"]


def main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"
    try:
        if cmd == "get":
            print(ensure_fresh())
            return 0
        if cmd == "store":
            t = store_exchange(json.loads(sys.stdin.read()))
            print(f"stored; expires_at={t['expires_at']}")
            return 0
        if cmd == "status":
            t = load()
            left = t.get("expires_at", 0) - int(time.time())
            print(f"expires_in={left}s refresh_token={'yes' if t.get('refresh_token') else 'NO'}")
            return 0 if left > 0 else 1
    except ReauthRequired as exc:
        print(f"REAUTH REQUIRED: {exc}", file=sys.stderr)
        return 3
    except TokenError as exc:
        print(f"TOKEN ERROR: {exc}", file=sys.stderr)
        return 4
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
