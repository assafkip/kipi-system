#!/usr/bin/env python3
"""Orchestrator lane watchdog: exit the moment an active lane goes quiet (ASK-3932).

WHY THIS EXISTS. 2026-11-06: a supervised multi-lane run lost 11.5 hours. A lane
agent ended its turn waiting on its own background CI watcher. CI finished red at
23:00 PST, the watcher never woke the agent, and the orchestrator session only
wakes on agent notifications, so nothing moved until 10:11 the next morning. The
Mac did not sleep. Founder, verbatim: "make sure this doesnt happen again" and
"ensure this fix is actually in code, not prose - it must be in code".

The fix is a waker that depends on no agent: this script, run in the background
by the orchestrator (its EXIT is the notification) and on a cron heartbeat.

A lane is ACTIVE when something is in flight for it: a required check is pending,
or an OS process names its worktree, its PR's review tree, its reviewer run or a
`gh pr checks <n>` watch. A lane is STALLED when nothing is in flight AND no
signal moved for --stall-min minutes. Signals: newest file mtime in the worktree,
the PR's updatedAt, the newest required-check completedAt, the newest review file
for the PR. An in-process subagent is not an OS process, so an idle-but-alive
agent reads as nothing in flight: that is the stall, and that is the 11.5 hours.

STATE FILE: one lane per line, `label pr worktree` (pr may be `-`). Lines
starting with # are ignored. lane-mark.py is its single writer -- it derives
`<lanes dir>/lanes.state` from the live lane markers on every start/touch/end, so
a lane that marks itself (which the fleet already requires: stall-sweep.py,
ci-redrive.py and linear-worker.sh all read those markers) is watched without a
second step anyone can forget.

FIRST-SEEN FLOOR: a lane's quiet clock never starts before the watchdog first saw
that lane. Found 2026-11-07: three lanes (#609, #621, #543) read STALL zero
minutes after launch, because a lane re-added on an existing worktree and PR
carries day-old signals. The floor is kept PER LANE in a sidecar JSON
(--seen / WATCHDOG_SEEN, default `<state>.seen`), never from the state file's
mtime: one shared mtime means adding lane B resets lane A's clock and masks
exactly the stall this script exists to catch.

Exit codes: 0 all lanes active or recently moving (heartbeat or --once ok),
3 at least one lane stalled, 2 bad usage or an unreadable state file.
"""
import argparse
import datetime as dt
import glob
import json
import os
import subprocess
import sys
import time

REPO = os.environ.get("WATCHDOG_REPO", "assafkip/kipi-system")
REVIEWS = os.environ.get("WATCHDOG_REVIEWS") or os.path.expanduser("~/.config/kipi/pr-reviews")
SKIP_DIRS = {"node_modules", "__pycache__", ".venv", ".pytest_cache", ".git"}


def run(args, timeout=60):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except Exception:
        return 99, ""


def ts(iso):
    if not iso:
        return 0.0
    try:
        return dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def newest_mtime(path):
    newest = 0.0
    if not path or path == "-" or not os.path.isdir(path):
        return newest
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            try:
                newest = max(newest, os.lstat(os.path.join(root, f)).st_mtime)
            except OSError:
                continue
    return newest


def split_pr(pr):
    """'owner/repo#123' -> ('owner/repo', '123'); a bare number uses REPO."""
    if "#" in pr:
        repo, num = pr.rsplit("#", 1)
        return repo, num
    return REPO, pr


def in_flight_procs(pr, wt):
    num = split_pr(pr)[1] if pr != "-" else pr
    rc, out = run(["ps", "-Ao", "command"])
    if rc != 0:
        return ["ps-unreadable"]  # fail toward ACTIVE: never page on a blind read
    hits = []
    for line in out.splitlines()[1:]:
        if "lane-watchdog.py" in line:
            continue
        if wt and wt != "-" and wt in line:
            hits.append("worktree-proc")
        if num != "-" and (
            f"__pr-{num}" in line
            or f"pr-review-agent.sh {num}" in line
            or f"gh pr checks {num}" in line
        ):
            hits.append("review-or-watch-proc")
    return sorted(set(hits))


def pr_signals(pr):
    """(state, pending_count, newest_ts); state UNKNOWN when the read failed."""
    repo, num = split_pr(pr)
    rc, out = run(["gh", "pr", "view", num, "-R", repo, "--json", "state,updatedAt"])
    if rc != 0:
        return "UNKNOWN", 0, 0.0
    try:
        d = json.loads(out)
    except json.JSONDecodeError:
        return "UNKNOWN", 0, 0.0
    newest = ts(d.get("updatedAt"))
    rc, out = run(["gh", "pr", "checks", num, "-R", repo, "--required",
                   "--json", "bucket,completedAt"])
    pending = 0
    if out.strip():
        try:
            for c in json.loads(out):
                if c.get("bucket") == "pending":
                    pending += 1
                newest = max(newest, ts(c.get("completedAt")))
        except json.JSONDecodeError:
            pass
    for f in glob.glob(os.path.join(REVIEWS, f"*__pr-{num}-*")):
        try:
            newest = max(newest, os.stat(f).st_mtime)
        except OSError:
            pass
    return d.get("state", "UNKNOWN"), pending, newest


def assess(label, pr, wt, stall_s, now, floor=0.0):
    procs = in_flight_procs(pr, wt)
    state, pending, newest = ("NOPR", 0, 0.0) if pr == "-" else pr_signals(pr)
    newest = max(newest, newest_mtime(wt), floor)
    quiet_min = int((now - newest) / 60) if newest else -1
    if state == "UNKNOWN":
        verdict, why = "ACTIVE", "gh unreadable, not judging"
    elif pending or procs:
        verdict, why = "ACTIVE", f"pending={pending} procs={','.join(procs) or 0}"
    elif newest and now - newest < stall_s:
        verdict, why = "MOVING", f"last signal {quiet_min}m ago"
    else:
        verdict, why = "STALL", f"nothing in flight, quiet {quiet_min}m, pr_state={state}"
    return verdict, f"{verdict} {label} pr={pr} {why}"


def read_state(path):
    lanes = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 3:
                raise ValueError(f"bad state line: {line!r}")
            lanes.append(tuple(parts))
    return lanes


def read_seen(path):
    """{label: epoch first seen}. An unreadable sidecar reads as empty, which
    floors every lane at now and fails toward ACTIVE (never page on a blind
    read); main() prints WATCHDOG-WARN when it cannot be written back."""
    try:
        with open(path) as fh:
            d = json.load(fh)
        return {k: float(v) for k, v in d.items() if isinstance(v, (int, float))}
    except (OSError, ValueError, AttributeError):
        return {}


def write_seen(path, seen):
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(tmp, "w") as fh:
            json.dump(seen, fh)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def floors(seen_path, labels, now):
    """Per-lane first-seen floor; records new lanes, forgets gone ones."""
    seen = read_seen(seen_path)
    for label in labels:
        seen.setdefault(label, now)
    seen = {k: v for k, v in seen.items() if k in set(labels)}
    return seen, write_seen(seen_path, seen)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, help="lane state file (lane-mark.py writes it)")
    ap.add_argument("--seen", default=os.environ.get("WATCHDOG_SEEN"),
                    help="first-seen sidecar JSON (default: <state>.seen)")
    ap.add_argument("--stall-min", type=int, default=20)
    ap.add_argument("--heartbeat-min", type=int, default=40)
    ap.add_argument("--poll-s", type=int, default=120)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    seen_path = a.seen or (a.state + ".seen")
    deadline = time.time() + a.heartbeat_min * 60
    while True:
        try:
            lanes = read_state(a.state)
        except (OSError, ValueError) as e:
            print(f"WATCHDOG-ERROR {e}", flush=True)
            return 2
        now = time.time()
        seen, stored = floors(seen_path, [l for l, _, _ in lanes], now)
        results = [assess(l, p, w, a.stall_min * 60, now, seen.get(l, now))
                   for l, p, w in lanes]
        stalled = [line for v, line in results if v == "STALL"]
        if stalled or a.once or time.time() >= deadline:
            stamp = dt.datetime.now().strftime("%H:%M")
            for _, line in results:
                print(f"{stamp} {line}", flush=True)
            if not lanes:
                print(f"{stamp} NO-LANES state file is empty", flush=True)
            if not stored:
                print(f"{stamp} WATCHDOG-WARN cannot write {seen_path}; "
                      "every lane's clock restarts each poll", flush=True)
            if stalled:
                return 3
            if not a.once:
                print(f"{stamp} HEARTBEAT no stall; re-arm the watchdog", flush=True)
            return 0
        time.sleep(a.poll_s)


if __name__ == "__main__":
    sys.exit(main())
