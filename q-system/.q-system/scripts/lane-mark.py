#!/usr/bin/env python3
"""lane-mark.py: an interactive lane says it is on a ticket (ASK-4095).

WHY. 2026-11-08 23:25:01Z: the red-CI redrive dispatched `converge --issue
ASK-4011` onto #666 while the rules-to-code agent was working that PR by hand.
That put two writers on one branch. The fleet cannot see an interactive session:
it holds no worker claim and writes no attempts-ledger row. This marker is how a
lane says "mine", and the redrives and the WIP release read it (linear-sync.py
lane_marker).

    lane-mark.py start ASK-4011 --agent rules-to-code [--hours 24]
    lane-mark.py touch ASK-4011            # push the expiry out again
    lane-mark.py end   ASK-4011            # the lane is done: the fleet may act

The marker is ~/.config/kipi/lanes/<ID>.json (KIPI_LANES_DIR overrides it):
{"issue", "agent", "since", "until"}. It expires by itself at "until", so a lane
that dies without `end` blocks the fleet for at most --hours. `end` sets "until"
to now and keeps the file, which is the record that the lane ran.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

ID_RX = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")


def lanes_dir() -> str:
    return os.environ.get("KIPI_LANES_DIR") or os.path.expanduser("~/.config/kipi/lanes")


def stamp(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("op", choices=("start", "touch", "end"))
    ap.add_argument("issue")
    ap.add_argument("--agent", default=os.environ.get("KIPI_AGENT", ""))
    ap.add_argument("--hours", type=float, default=24.0)
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
        cur = {"issue": a.issue, "agent": a.agent, "since": stamp(now)}
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
    print(f"lane-mark: {a.issue} {a.op}: {cur.get('agent')} until {cur['until']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
