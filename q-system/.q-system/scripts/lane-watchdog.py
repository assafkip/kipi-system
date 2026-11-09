#!/usr/bin/env python3
"""Orchestrator lane watchdog: exit the moment an active lane goes quiet (ASK-3932).

WHY THIS EXISTS. 2026-11-06: a supervised multi-lane run lost 11.5 hours. A lane
agent ended its turn waiting on its own background CI watcher. CI finished red at
23:00 PST, the watcher never woke the agent, and the orchestrator session only
wakes on agent notifications, so nothing moved until 10:11 the next morning. The
Mac did not sleep. Founder, verbatim: "make sure this doesnt happen again" and
"ensure this fix is actually in code, not prose - it must be in code".

The fix is a waker that depends on no agent: this script, run in the background
by the orchestrator. Its EXIT is the notification.

WHO ARMS IT, exactly (corrected after the claude review of PR #706, round 1,
which caught this docstring claiming a cron heartbeat that does not exist):
`kipi lane watch` is the only armer in this repo, and the orchestrator runs it in
the background at the start of a supervised run. There is NO launchd job yet, so
nothing arms it when no orchestrator session is running; that backstop is its own
issue, named on the PR, and this file no longer pretends otherwise. What needs no
arming step is the STATE FILE, not the watchdog.

A lane is ACTIVE when something is in flight for it: a required check is pending,
or an OS process names its worktree, its PR's review tree, its reviewer run or a
`gh pr checks <n>` watch. A lane is STALLED when nothing is in flight AND no
signal moved for --stall-min minutes. Signals: newest file mtime in the worktree,
the PR's updatedAt, the newest required-check completedAt, the newest review file
for the PR. An in-process subagent is not an OS process, so an idle-but-alive
agent reads as nothing in flight: that is the stall, and that is the 11.5 hours.

A SHARED PATH TELLS US NOTHING ABOUT ONE LANE. The worktree signals (both the
process probe and the file mtime) are used only when the path identifies exactly
one lane: named by one line in the state file, and a linked git worktree rather
than a main checkout (`.git` a pointer file, not a directory -- the same split
open-loops.py:78 makes with `git rev-parse --git-common-dir`). A main checkout is
shared with the founder and with the 14 launchd jobs that run from it
(separate-worktrees.md), so before this a lane sitting in one read ACTIVE forever
and the detector was silently off. Such a lane is now judged on its PR and its
checks alone, and the verdict line carries `wt=<reason>` so the narrowing is
loud rather than silent. That is deliberately noisier: a false wake-up costs one
poll, a missed stall cost 11.5 hours.

STATE FILE: one lane per line, `label pr worktree` (pr may be `-`). Lines
starting with # are ignored. lane-mark.py is its single writer -- it derives
`<lanes dir>/lanes.state` from the live lane markers on every start/touch/end, so
a lane that marks itself (which the fleet already requires: stall-sweep.py,
ci-redrive.py and linear-worker.sh all read those markers) is watched without a
second step anyone can forget. Before reading a file actually named `lanes.state`
this script shells `lane-mark.py sync` to have that one writer re-derive it:
an expired or dead marker otherwise kept its line until the next start/touch/end
-- never, for a lane that died -- and the watchdog paged STALL on the ghost in
0.1s on every arm, for ever. Parsing the markers here instead would have put a
second reader on one format, which is the worse defect.

COOLDOWN. A real stall that the orchestrator cannot clear used to exit 3 in 0.1s
on every re-arm, which is a hot loop, not a signal. The first stall pages at
once; a repeat within --cooldown-min (default: --stall-min) prints
`STALL-COOLDOWN <lane>` and exits 0 so the caller can sleep. A lane that recovers
forgets its cooldown, so its next stall pages immediately.

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
LANE_MARK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lane-mark.py")
STATE_BASENAME = "lanes.state"
# Commands that name a lane's worktree BY CONSTRUCTION. Counting them as work in
# flight would make the watchdog hold a lane active on the strength of its own
# arming command.
SELF_CMDS = ("lane-watchdog.py", "lane-mark.py", "kipi lane")
# Token boundaries. A worktree path counts only when it ends at one of these, so
# `/tmp/wt-old` no longer matches a process working in `/tmp/wt-old-sibling`.
TOK_BEFORE = " \t\"'=:(,"
TOK_AFTER = " \t\"'/:;),&|"


def run(args, timeout=60, env=None):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, p.stdout
    except Exception:
        return 99, ""


def resync(state):
    """Have lane-mark re-derive the state file, so a dead lane leaves it.

    Only for a file actually named lanes.state: that is the derived file, and a
    hand-written fixture must not be overwritten by a sync. Best-effort -- a
    failure leaves the existing file, which is the pre-fix behaviour, and is
    reported by the caller rather than swallowed.
    """
    if os.path.basename(state) != STATE_BASENAME:
        return None
    env = dict(os.environ)
    env["KIPI_LANES_DIR"] = os.path.dirname(os.path.abspath(state))
    rc, _ = run([sys.executable, LANE_MARK, "sync"], timeout=30, env=env)
    return rc == 0


def path_in_cmdline(path, line):
    """True when `line` names `path` as a path token, not as a bare substring."""
    i = line.find(path)
    while i != -1:
        before = line[i - 1] if i else " "
        after = line[i + len(path):i + len(path) + 1] or " "
        if before in TOK_BEFORE and after in TOK_AFTER:
            return True
        i = line.find(path, i + 1)
    return False


def worktree_signal_ok(wt, all_worktrees):
    """(usable, reason): may this path's processes and mtime speak for ONE lane?

    A shared path answers "someone touched this place", never "this lane moved".
    Two lanes on one path cannot be told apart, and a main checkout is shared
    with the founder and with the launchd jobs that run from it, which is how a
    lane in one read ACTIVE for ever with the detector silently off.
    """
    if not wt or wt == "-":
        return False, "no-worktree"
    if all_worktrees.count(wt) > 1:
        return False, "worktree-shared-by-lanes"
    if os.path.isdir(os.path.join(wt, ".git")):
        return False, "worktree-is-main-checkout"
    return True, ""


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
        if any(c in line for c in SELF_CMDS):
            continue
        if wt and wt != "-" and path_in_cmdline(wt, line):
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


def assess(label, pr, wt, stall_s, now, floor=0.0, all_worktrees=()):
    wt_ok, wt_why = worktree_signal_ok(wt, list(all_worktrees))
    # Both worktree signals stand or fall together. Keeping the mtime of a
    # shared path while dropping its processes would leave the same hole: a
    # launchd job writing the main checkout would read as the lane moving.
    procs = in_flight_procs(pr, wt if wt_ok else "-")
    state, pending, newest = ("NOPR", 0, 0.0) if pr == "-" else pr_signals(pr)
    newest = max(newest, newest_mtime(wt) if wt_ok else 0.0, floor)
    quiet_min = int((now - newest) / 60) if newest else -1
    if state == "UNKNOWN":
        verdict, why = "ACTIVE", "gh unreadable, not judging"
    elif pending or procs:
        verdict, why = "ACTIVE", f"pending={pending} procs={','.join(procs) or 0}"
    elif newest and now - newest < stall_s:
        verdict, why = "MOVING", f"last signal {quiet_min}m ago"
    else:
        verdict, why = "STALL", f"nothing in flight, quiet {quiet_min}m, pr_state={state}"
    note = f" wt={wt_why}" if wt_why and wt_why != "no-worktree" else ""
    return verdict, f"{verdict} {label} pr={pr} {why}{note}"


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


def _epochs(d):
    if not isinstance(d, dict):
        return {}
    return {k: float(v) for k, v in d.items() if isinstance(v, (int, float))}


def read_seen(path):
    """({label: first seen}, {label: last paged}) from the sidecar.

    An unreadable sidecar reads as empty, which floors every lane at now and
    fails toward ACTIVE (never page on a blind read); main() prints
    WATCHDOG-WARN when it cannot be written back. A flat {label: epoch} file is
    the pre-cooldown format and still reads as the first-seen half.
    """
    try:
        with open(path) as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return {}, {}
    if isinstance(d, dict) and ("seen" in d or "paged" in d):
        return _epochs(d.get("seen")), _epochs(d.get("paged"))
    return _epochs(d), {}


def write_seen(path, seen, paged):
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(tmp, "w") as fh:
            json.dump({"seen": seen, "paged": paged}, fh)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def floors(seen_path, labels, now):
    """Per-lane first-seen floor and last-paged stamp; forgets lanes that left."""
    seen, paged = read_seen(seen_path)
    live = set(labels)
    for label in labels:
        seen.setdefault(label, now)
    seen = {k: v for k, v in seen.items() if k in live}
    paged = {k: v for k, v in paged.items() if k in live}
    return seen, paged


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, help="lane state file (lane-mark.py writes it)")
    ap.add_argument("--seen", default=os.environ.get("WATCHDOG_SEEN"),
                    help="first-seen sidecar JSON (default: <state>.seen)")
    ap.add_argument("--stall-min", type=int, default=20)
    ap.add_argument("--cooldown-min", type=int, default=None,
                    help="do not re-page the same stalled lane for this long "
                         "(default: --stall-min; 0 pages on every poll)")
    ap.add_argument("--heartbeat-min", type=int, default=40)
    ap.add_argument("--poll-s", type=int, default=120)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    seen_path = a.seen or (a.state + ".seen")
    cooldown_s = (a.stall_min if a.cooldown_min is None else a.cooldown_min) * 60
    deadline = time.time() + a.heartbeat_min * 60
    while True:
        synced = resync(a.state)
        try:
            lanes = read_state(a.state)
        except (OSError, ValueError) as e:
            print(f"WATCHDOG-ERROR {e}", flush=True)
            return 2
        now = time.time()
        labels = [l for l, _, _ in lanes]
        worktrees = [w for _, _, w in lanes]
        seen, paged = floors(seen_path, labels, now)
        results = [assess(l, p, w, a.stall_min * 60, now, seen.get(l, now), worktrees)
                   for l, p, w in lanes]
        # A stall the caller already heard about, inside the cooldown, is not a
        # new event: exiting 3 in 0.1s on every re-arm is a hot loop, not a
        # signal. A lane that is not stalling forgets its stamp, so its next
        # stall pages at once.
        pages, cooled, shown = [], [], []
        for (verdict, line), label in zip(results, labels):
            if verdict != "STALL":
                paged.pop(label, None)
                shown.append(line)
                continue
            last = paged.get(label, 0.0)
            if last and now - last < cooldown_s:
                cooled.append(label)
                shown.append(line.replace("STALL ", "STALL-COOLDOWN ", 1))
            else:
                paged[label] = now
                pages.append(label)
                shown.append(line)
        stored = write_seen(seen_path, seen, paged)
        # A cooled stall does not end a LOOP: staying armed is the point, and
        # the lane pages again the moment its cooldown lapses. In --once mode
        # the caller gets the cooldown line and exit 0.
        if pages or a.once or time.time() >= deadline:
            stamp = dt.datetime.now().strftime("%H:%M")
            for line in shown:
                print(f"{stamp} {line}", flush=True)
            if not lanes:
                print(f"{stamp} NO-LANES state file is empty", flush=True)
            if synced is False:
                print(f"{stamp} WATCHDOG-WARN lane-mark sync failed; the state "
                      "file may still name a lane that has ended", flush=True)
            if not stored:
                print(f"{stamp} WATCHDOG-WARN cannot write {seen_path}; "
                      "every lane's clock restarts each poll", flush=True)
            if pages:
                return 3
            if cooled:
                print(f"{stamp} COOLDOWN {len(cooled)} stalled lane(s) already "
                      f"reported within {cooldown_s // 60}m; not paging again", flush=True)
            elif not a.once:
                print(f"{stamp} HEARTBEAT no stall; re-arm the watchdog", flush=True)
            return 0
        time.sleep(a.poll_s)


if __name__ == "__main__":
    sys.exit(main())
