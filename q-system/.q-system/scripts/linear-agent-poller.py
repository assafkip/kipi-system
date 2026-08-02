#!/usr/bin/env python3
"""Mac side of the relay: drain the queue, verify independently, run, ack.

WHY THIS VERIFIES AGAIN
-----------------------
The relay already checked the signature at the edge. This checks it a SECOND time,
over the raw bytes the relay stored, because the relay is a different machine on a
different vendor and "the relay said it was fine" is not evidence. If the relay were
ever compromised or misconfigured, edge-only verification would mean anything it
chose to enqueue gets executed locally with this fleet's full permissions. The raw
body is carried byte-exact through the queue precisely so this check is possible.

ACK ORDERING IS THE WHOLE DURABILITY STORY
------------------------------------------
Ack happens AFTER the run completes, never before. At-least-once, deliberately:
  - ack-first  -> a crash mid-run loses the delegation forever. Silent. The exact
                  failure the queue was built to prevent.
  - ack-after  -> a crash mid-run replays the delegation on the next poll. Recoverable,
                  visible, and the receiver's dedupe key collapses the repeat.
A duplicated run is recoverable; a dropped delegation is not. That asymmetry decides
the ordering.

Usage:
  linear-agent-poller.py once      # one drain cycle, then exit (launchd-friendly)
  linear-agent-poller.py loop      # poll forever at KIPI_RELAY_POLL_INTERVAL
"""
import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

RELAY_URL = os.environ.get("KIPI_RELAY_URL", "")
RELAY_TOKEN = os.environ.get("KIPI_RELAY_TOKEN", "")
WEBHOOK_SECRET = os.environ.get("KIPI_LINEAR_WEBHOOK_SECRET", "")
NOTIFY = os.environ.get("KIPI_NOTIFY", str(SCRIPT_DIR / "slack-notify.sh"))
POLL_INTERVAL = int(os.environ.get("KIPI_RELAY_POLL_INTERVAL", "60"))
# One cycle must not run the box out of the day. The queue keeps the rest; the next
# cycle picks them up. An unbounded drain would serialise a backlog into one run.
MAX_PER_CYCLE = int(os.environ.get("KIPI_RELAY_MAX_PER_CYCLE", "5"))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def page(msg: str) -> None:
    try:
        subprocess.run([NOTIFY, msg], timeout=20, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass
    print(f"PAGE: {msg}", file=sys.stderr)


def _request(path: str, payload: dict = None, transport=None):
    """One HTTP shape for the relay. Injectable so the suite needs no relay."""
    if transport:
        return transport(path, payload)
    req = urllib.request.Request(
        f"{RELAY_URL.rstrip('/')}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {RELAY_TOKEN}",
                 "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def poll_once(receiver=None, transport=None, secret=None) -> dict:
    """Drain up to MAX_PER_CYCLE events. Returns a summary dict."""
    receiver = receiver or _load("linear_agent_receiver", "linear-agent-receiver.py")
    secret = secret if secret is not None else WEBHOOK_SECRET

    try:
        data = _request("/api/poll", transport=transport)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        page(f"Linear relay unreachable ({exc}). Delegations are queueing but not running.")
        return {"ok": False, "reason": "relay unreachable", "ran": 0}

    events = (data or {}).get("events", [])[:MAX_PER_CYCLE]
    ran, rejected = 0, 0

    for ev in events:
        raw = ev.get("raw", "").encode("latin-1")
        sig = ev.get("signature", "")

        # INDEPENDENT verification. See the module docstring.
        ok, why = receiver.verify_signature(raw, sig, secret)
        if not ok:
            # Do NOT ack. An event this box refuses is evidence about the relay, and
            # deleting it would destroy that evidence.
            rejected += 1
            page(f"Linear relay delivered an event that FAILED local signature "
                 f"verification ({why}). Not running it, not acking it.")
            continue

        try:
            receiver.handle_event(json.loads(raw))
            ran += 1
        except Exception as exc:  # noqa: BLE001
            # Not acked -> replays next cycle. Surfaced rather than swallowed.
            page(f"Linear delegation run failed ({type(exc).__name__}: {exc}). "
                 f"It stays queued and will retry.")
            continue

        # Ack LAST, and only for this event.
        try:
            _request("/api/ack", {"key": ev["key"]}, transport=transport)
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            page("Linear delegation ran but could NOT be acked. It will replay; "
                 "expect one duplicate run.")

    return {"ok": True, "ran": ran, "rejected": rejected, "queued": len(events)}


def main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else "once"
    if not RELAY_URL:
        print("KIPI_RELAY_URL is not set", file=sys.stderr)
        return 1

    if cmd == "once":
        print(json.dumps(poll_once(), indent=2))
        return 0
    if cmd == "loop":
        while True:
            try:
                print(json.dumps(poll_once()), flush=True)
            except Exception as exc:  # noqa: BLE001
                page(f"Linear poller crashed: {exc}")
            time.sleep(POLL_INTERVAL)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
