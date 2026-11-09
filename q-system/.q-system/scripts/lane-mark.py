#!/usr/bin/env python3
"""lane-mark.py: an interactive lane says it is on a ticket (ASK-4095).

WHY. 2026-11-08 23:25:01Z: the red-CI redrive dispatched `converge --issue
ASK-4011` onto #666 while the rules-to-code agent was working that PR by hand.
That put two writers on one branch. The fleet cannot see an interactive session:
it holds no worker claim and writes no attempts-ledger row. This marker is how a
lane says "mine", and the redrives and the WIP release read it (linear-sync.py
lane_marker).

    lane-mark.py start ASK-4011 --agent rules-to-code [--hours 24] \
                 [--pr 621] [--worktree /path]      # worktree defaults to cwd
    lane-mark.py touch ASK-4011            # push the expiry out again
    lane-mark.py end   ASK-4011            # the lane is done: the fleet may act

The marker is ~/.config/kipi/lanes/<ID>.json (KIPI_LANES_DIR overrides it):
{"issue", "agent", "since", "until", "pr", "worktree"}. It expires by itself at
"until", so a lane that dies without `end` blocks the fleet for at most --hours.
`end` sets "until" to now and keeps the file, which is the record that the lane
ran.

ALSO THE ONE WRITER OF THE WATCHDOG STATE FILE (ASK-3932). Every op rewrites
<lanes dir>/lanes.state from the live markers, one `label pr worktree` line each,
which is what lane-watchdog.py reads. 2026-11-06 cost 11.5 hours because the
waker was session-local and died with the session; hanging the state file off the
marker every lane already writes means no separate arming step to forget.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

ID_RX = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")
STATE_NAME = "lanes.state"


def lanes_dir() -> str:
    return os.environ.get("KIPI_LANES_DIR") or os.path.expanduser("~/.config/kipi/lanes")


def state_path() -> str:
    return os.path.join(lanes_dir(), STATE_NAME)


def stamp(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_stamp(s):
    try:
        return datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def live_lanes(now: datetime) -> list:
    """(issue, pr, worktree) for every unexpired, unended marker, issue-sorted.

    A field is written as `-` when the lane never named one, because
    lane-watchdog.py reads exactly three whitespace-separated fields per line and
    exits 2 on anything else. Whitespace in a worktree path would split the line,
    so such a lane is written as `-` rather than corrupting the file.
    """
    out = []
    for name in sorted(os.listdir(lanes_dir())):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(lanes_dir(), name)) as fh:
                m = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict) or m.get("ended"):
            continue
        until = parse_stamp(m.get("until"))
        if not until or until <= now:
            continue
        issue = str(m.get("issue") or "").strip()
        if not ID_RX.match(issue):
            continue
        fields = []
        for key in ("pr", "worktree"):
            val = str(m.get(key) or "").strip()
            fields.append(val if val and len(val.split()) == 1 else "-")
        out.append((issue, fields[0], fields[1]))
    return out


def write_state(now: datetime) -> str:
    """Rewrite the watchdog state file from the markers. One writer, every op."""
    path = state_path()
    lines = [
        "# lane-watchdog.py state, written by lane-mark.py (ASK-3932). Do not hand-edit:",
        "# every lane-mark start/touch/end rewrites this file from the live markers.",
    ]
    lines += [f"{i} {pr} {wt}" for i, pr, wt in live_lanes(now)]
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, path)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("op", choices=("start", "touch", "end"))
    ap.add_argument("issue")
    ap.add_argument("--agent", default=os.environ.get("KIPI_AGENT", ""))
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--pr", default="", help="PR number or owner/repo#n the lane is driving")
    ap.add_argument("--worktree", default="", help="the lane's worktree (default: cwd on start)")
    a = ap.parse_args(argv)
    if not ID_RX.match(a.issue):
        print(f"lane-mark: {a.issue!r} is not an issue id like ASK-123", file=sys.stderr)
        return 64
    if not 0 < a.hours <= 72:
        print("lane-mark: --hours runs from more than 0 to 72", file=sys.stderr)
        return 64
    os.makedirs(lanes_dir(), exist_ok=True)
    path = os.path.join(lanes_dir(), a.issue + ".json")
    now = datetime.now(timezone.utc)
    try:
        cur = json.load(open(path))
    except (OSError, ValueError):
        cur = {}
    if a.op in ("touch", "end") and not cur:
        print(f"lane-mark: no lane marker for {a.issue} to {a.op}", file=sys.stderr)
        return 1
    if a.op == "start":
        if not a.agent:
            print("lane-mark: start needs --agent (or KIPI_AGENT)", file=sys.stderr)
            return 64
        cur = {"issue": a.issue, "agent": a.agent, "since": stamp(now),
               "pr": a.pr or "-", "worktree": a.worktree or os.getcwd()}
    else:
        # touch and end may correct the pr or worktree; they never erase one.
        if a.pr:
            cur["pr"] = a.pr
        if a.worktree:
            cur["worktree"] = a.worktree
    if a.op == "end":
        cur["until"] = stamp(now)
        cur["ended"] = stamp(now)
    else:
        cur["until"] = stamp(now + timedelta(hours=a.hours))
        cur.pop("ended", None)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(cur, fh, indent=1)
    os.replace(tmp, path)
    # The watchdog state file is DERIVED, so it is rewritten here and nowhere
    # else. A failure to write it is reported and does not fail the marker: the
    # marker is what the redrives read, and losing the lane's claim to save the
    # watchdog would trade a 11.5-hour stall for a two-writer branch.
    try:
        state = write_state(now)
        note = f"; watchdog state {state}"
    except OSError as e:
        note = f"; WARNING watchdog state not written ({e})"
    print(f"lane-mark: {a.issue} {a.op}: {cur.get('agent')} until {cur['until']}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
