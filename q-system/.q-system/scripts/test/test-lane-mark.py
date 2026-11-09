#!/usr/bin/env python3
"""lane-mark.py writes the lane marker that linear-sync.lane_marker reads (ASK-4095).
Scar: 2026-11-08 23:25Z, a redrive put a second writer on #666 because nothing told
the fleet an interactive lane was on it."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
FAILS = []


def check(name, got, want):
    if got == want:
        print(f"  ok: {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL: {name}\n     got  {got!r}\n     want {want!r}")


with tempfile.TemporaryDirectory() as d:
    os.environ["KIPI_LANES_DIR"] = d
    spec = importlib.util.spec_from_file_location("ls_lane", SCRIPTS / "linear-sync.py")
    ls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ls)

    def mark(*args):
        return subprocess.run([sys.executable, str(SCRIPTS / "lane-mark.py"), *args],
                              capture_output=True, text=True, env=dict(os.environ)).returncode

    print("== lane-mark")
    check("no marker: no lane", ls.lane_marker("ASK-1"), "")
    check("start needs an agent", mark("start", "ASK-1"), 64)
    check("start with an agent writes the marker", mark("start", "ASK-1", "--agent", "rules-to-code"), 0)
    check("a started lane is live and names its agent",
          ls.lane_marker("ASK-1").startswith("lane marker: rules-to-code holds ASK-1 until "), True)
    rec = json.load(open(Path(d) / "ASK-1.json"))
    check("the marker records issue, agent, since and until",
          sorted(rec), ["agent", "issue", "since", "until"])
    check("end ends it", mark("end", "ASK-1"), 0)
    check("an ended lane is not live", ls.lane_marker("ASK-1"), "")
    check("touch with no marker is refused", mark("touch", "ASK-2"), 1)
    check("a bad id is refused", mark("start", "not-an-id", "--agent", "x"), 64)
    check("more than 72 hours is refused", mark("start", "ASK-3", "--agent", "x", "--hours", "100"), 64)
    later = datetime.now(timezone.utc) + timedelta(hours=30)
    check("a lane is judged against the clock: 30h on, a 24h marker has expired",
          (mark("start", "ASK-4", "--agent", "x"), ls.lane_marker("ASK-4", now=later)), (0, ""))
    (Path(d) / "ASK-5.json").write_text("{not json")
    check("an unreadable marker is respected (fail closed)",
          ls.lane_marker("ASK-5").startswith("its lane marker"), True)
    (Path(d) / "ASK-6.json").write_text('{"issue": "ASK-6", "agent": "x"}')
    check("a marker with no expiry is respected", "names no expiry" in ls.lane_marker("ASK-6"), True)

print()
if FAILS:
    print(f"FAILED: {len(FAILS)}")
    sys.exit(1)
print("all lane-mark checks passed")
