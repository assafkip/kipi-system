#!/usr/bin/env python3
"""lane-mark.py writes the lane marker that linear-sync.lane_marker reads (ASK-4095).
Scar: 2026-11-08 23:25Z, a redrive put a second writer on #666 because nothing told
the fleet an interactive lane was on it."""
import fcntl
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
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

    def bare_env():
        env = dict(os.environ)
        env.pop("KIPI_AGENT", None)
        return env

    def start_async(issue):
        return subprocess.Popen(
            [sys.executable, str(SCRIPTS / "lane-mark.py"), "start", issue, "--agent", "x"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=bare_env())

    def mark(*args):
        # KIPI_AGENT is lane-mark's fallback for --agent, and the fleet worker
        # exports it (KIPI_AGENT=sana), so an inherited env made "start needs an
        # agent" pass an agent and read exit 0. Measured 2026-11-09 on
        # origin/main: rc 0 in the worker's shell, rc 64 in a bare one. The test
        # runs in a shell of its own choosing, so it states the variable.
        return subprocess.run([sys.executable, str(SCRIPTS / "lane-mark.py"), *args],
                              capture_output=True, text=True, env=bare_env()).returncode

    print("== lane-mark")
    check("no marker: no lane", ls.lane_marker("ASK-1"), "")
    check("start needs an agent", mark("start", "ASK-1"), 64)
    check("start with an agent writes the marker", mark("start", "ASK-1", "--agent", "rules-to-code"), 0)
    check("a started lane is live and names its agent",
          ls.lane_marker("ASK-1").startswith("lane marker: rules-to-code holds ASK-1 until "), True)
    rec = json.load(open(Path(d) / "ASK-1.json"))
    # pr and worktree joined the marker with the lane watchdog (ASK-3932):
    # lane-mark derives lanes.state from these fields, so they live on the
    # marker rather than in a second file a lane could forget to write. Read
    # linear-sync.lane_marker before changing this: it pulls "until" and "agent"
    # by key and ignores the rest, which is why adding fields is safe there.
    check("the marker records issue, agent, since, until, pr and worktree",
          sorted(rec), ["agent", "issue", "pr", "since", "until", "worktree"])
    check("pr defaults to - when the lane names none", rec["pr"], "-")
    check("the state file skips lanes.state, which is not a marker",
          ls.lane_marker("lanes.state"), "")
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

    # --- the derived state file is written under a lock (ASK-3932, PR #706 r1) --
    # FINDING: two lanes starting at once interleaved as "A lists the markers ->
    # B lists them -> B replaces lanes.state -> A replaces it with its OLDER
    # list", so lane B vanished from the derived file and the watchdog never
    # watched it until the next lane-mark op, which for a lane that dies without
    # `end` never comes. The read of the markers and the write of the derived
    # file are now ONE critical section, held with flock on <state>.lock.
    # The lock file is not a marker: linear-sync.lane_marker:739 opens
    # <id>.json by exact name, so neither it nor lanes.state is ever read as one.
    print("== lane-mark: the derived state file is written under a lock")
    lock = Path(d) / "lanes.state.lock"
    with open(lock, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        held = start_async("ASK-30")
        time.sleep(1.0)
        waiting = held.poll() is None     # must still be blocked on the lock
        fcntl.flock(fh, fcntl.LOCK_UN)
    check("the state writer waits for a held lock", (waiting, held.wait(timeout=20)), (True, 0))

    # 12 starts fired at once: every one of them has to be in the derived file.
    # This is the race itself rather than the lock, so it can pass by luck on a
    # broken build; the lock check above is the deterministic half.
    ids = [f"ASK-{40 + i}" for i in range(12)]
    procs = [start_async(i) for i in ids]
    for p in procs:
        p.wait(timeout=30)
    state_text = (Path(d) / "lanes.state").read_text()
    check("no lane is dropped when 12 start at once",
          [i for i in ids if f"{i} " not in state_text], [])

    # --- sync: the one writer can re-derive without touching a marker ---------
    # FINDING: an expired or dead marker kept its line in lanes.state until the
    # next start/touch/end, and the watchdog paged STALL on it in 0.1s on every
    # arm, forever. `sync` is how the watchdog gets a fresh file without
    # becoming a second parser of the markers.
    print("== lane-mark: sync re-derives the state file, markers untouched")
    before = json.load(open(Path(d) / "ASK-40.json"))
    expired = Path(d) / "ASK-41.json"
    rec41 = json.load(open(expired))
    rec41["until"] = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    json.dump(rec41, open(expired, "w"))
    check("sync needs no issue id", mark("sync"), 0)
    state_text = (Path(d) / "lanes.state").read_text()
    check("sync drops the expired lane", "ASK-41 " in state_text, False)
    check("sync keeps the live lane", "ASK-40 " in state_text, True)
    check("sync does not rewrite a marker", json.load(open(Path(d) / "ASK-40.json")), before)
    check("sync still refuses a bad id", mark("sync", "not-an-id"), 64)

print()
if FAILS:
    print(f"FAILED: {len(FAILS)}")
    sys.exit(1)
print("all lane-mark checks passed")
