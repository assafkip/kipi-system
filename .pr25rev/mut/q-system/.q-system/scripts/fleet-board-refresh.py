#!/usr/bin/env python3
"""SessionStart surfacer: keep the Fleet Loop Board fresh, event-driven.

Pairs with fleet-loop-board.py (the generator) and .claude/rules/loop-exits.md.
Detects when the board's inputs changed since the last publish (git HEAD moved
OR open-loops.json changed) and nudges to regenerate + republish. Detection is
deterministic and free; the actual Artifact publish is session-bound (a bash or
cron step cannot reach the Artifact tool), so this surfaces the need at the next
session instead of trying to publish itself. That is the honest shape of
"event-driven refresh" given the publish wall.

Two modes:
  - default (SessionStart hook): inputs changed since published_sig -> emit an
    additionalContext nudge. Never blocks; always exit 0.
  - --mark-published: record the current inputs as the published baseline. Run
    right after republishing the artifact, so the nudge stops until the next
    real change.

Self-disabling: no state file (or no `url` in it) -> exit 0, silent. So this
ships fleet-wide harmlessly; it only speaks on an instance that has set up a
board and recorded its URL.

State: q-system/output/.fleet-board-state.json  {"url": str, "published_sig": str}
stdlib only; fail-closed on every source (a broken source emits nothing, never
a stack trace into session start).
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent          # q-system/.q-system/scripts/
QROOT = SCRIPT_DIR.parent.parent                       # q-system/
REPO = QROOT.parent                                    # repo root
STATE = QROOT / "output" / ".fleet-board-state.json"
OPEN_LOOPS_JSON = QROOT / "memory" / "open-loops.json"


def current_sig():
    """A 16-char signature of the board's inputs: HEAD + open-loops.json bytes.
    Change-driven, not clock-driven (a fixed daily beat was explicitly rejected)."""
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=5).stdout.strip()
    loops = OPEN_LOOPS_JSON.read_bytes() if OPEN_LOOPS_JSON.is_file() else b""
    return hashlib.sha256(head.encode() + b"|" + loops).hexdigest()[:16]


def load_state():
    if not STATE.is_file():
        return None
    try:
        return json.loads(STATE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def mark_published():
    state = load_state() or {}
    try:
        state["published_sig"] = current_sig()
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=2))
        print(f"[fleet-board] published baseline = {state['published_sig']}")
    except (OSError, subprocess.SubprocessError):
        pass


def surface():
    state = load_state()
    if not state or not state.get("url"):
        return  # self-disabled: no board configured on this instance
    try:
        sig = current_sig()
    except (subprocess.SubprocessError, OSError):
        return
    if sig == state.get("published_sig"):
        return  # board is current
    body = (
        "Fleet loop board is STALE: the repo or open-loops changed since it was "
        "last published. Regenerate + republish so the comprehension board stays "
        "current:\n"
        "  1. python3 q-system/.q-system/scripts/fleet-loop-board.py\n"
        f"  2. republish q-system/output/fleet-loop-board.html to {state['url']} "
        "(Artifact tool, pass url=)\n"
        "  3. python3 q-system/.q-system/scripts/fleet-board-refresh.py --mark-published"
    )
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": body}}))


def main():
    if "--mark-published" in sys.argv:
        mark_published()
    else:
        surface()
    sys.exit(0)


if __name__ == "__main__":
    main()
