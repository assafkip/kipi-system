#!/usr/bin/env python3
"""Dispatch stall checker (ASK-3064): the dispatcher is ALIVE and dispatching NOTHING.

THE SCAR (2026-10-24). com.kipi.dispatch ran every 15 minutes for 8.5 hours and
every kipi-system turn logged the same two lines:

    reviewer redrive: ASK-2058 PR #554 needs rework (ASK-3058 waits)
    skip ASK-2058: its open PR #554 is on sana/ask-2058-guard, but converge
    would commit onto sana/ask-2058 ...

Nothing dispatched and new issues waited behind it. Every liveness signal said
healthy: launchd-health reads LastExitStatus (0), test-dispatch-liveness.sh
tests that a dispatch which DIED is not reported as success. This is the other
shape: a dispatcher that exits 0 every time having decided to do nothing. The
branch-guard page was deduped for 24h (page_once) and it lands in Sana's queue,
and Sana IS the dispatcher, so the one alert went to the thing that was stuck.

WHY A SEPARATE LAUNCHD JOB AND NOT A STEP IN kipi-dispatch.sh. A step inside the
dispatcher shares every failure the dispatcher has: the stale-checkout refusal,
a lock held by a wedged turn, a bad edit to the script itself all stop the
step too. It would also restart itself from inside its own turn. This watcher
reads only the log, so it keeps working when the dispatcher does not.

WHAT IT DOES, per tick, never more than once per stall:
  1. Reads dispatch.log, splits it into turns (one per "dispatch: N of M ..."
     line), and attributes each turn to its repo ("entering X" or the home repo).
  2. A STALLED TURN names an issue (a `skip ASK-n:` line, or a redrive line with
     no outcome) and has NO `dispatching`/`dispatched`/`nothing ready`/
     `DAILY CAP` line. K such turns in a row for one (repo, issue) is a stall.
     A turn of another repo does not touch this repo's count: brag's
     `nothing ready` sat between kipi-system's stalled turns on 2026-10-24.
  3. Known class, branch-guard: the open PR is on sana/ask-n-suffix, converge
     commits onto sana/ask-n. Repair = push the PR head sha to the new name
     (create-only ref, never a force-push), open a replacement PR (GitHub CLOSES
     a PR whose head branch is renamed, so the rename itself is not an option),
     close the old PR without --delete-branch, comment on the Linear issue.
  4. Then kickstart com.kipi.dispatch. A restart ALONE clears nothing: the
     dispatcher was already restarting every 15 minutes and skipping the same issue.
  5. Next tick, if a turn AFTER the kickstart still stalls (or none came at all
     for 2 intervals), file ONE ticket for Sana through slack-notify.sh. Never the
     founder (founder-notifications.md).

WRITE ORDER (repair): create ref, then PR, then close the old PR. A crash between
steps leaves the old PR open and working, and a rerun finds the ref (same sha)
and an open PR on it and resumes, so no step is destructive and every step is
re-runnable.

DRY RUN IS THE DEFAULT. Nothing acts without --apply (the plist passes it).
--replay walks a whole log and prints when the checker WOULD have fired.

K = 3 turns (about 45 minutes). Measured on the real log 2026-10-24: the same
branch-guard skip ran 442 and 323 turns (ASK-1144, Aug/Sep) and 24 turns
(ASK-2058); a 3-turn run is already past anything a healthy rotation produces.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()
DISPATCH_LABEL = "com.kipi.dispatch"
K_TURNS = 3
INTERVAL_S = 900
# A stall is "now" when its last stalled turn is within 4 intervals. Older than
# that and the dispatcher either moved on or is dead, and a dead one is
# launchd-health's finding, not this file's.
ACTIVE_WINDOW_S = 4 * INTERVAL_S
# No turn at all for 2 intervals after our kickstart: the restart did not take.
NO_TURN_AFTER_KICK_S = 2 * INTERVAL_S

TS = r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)"
LINE_RE = re.compile(TS + r" (.*)")
TURN_RE = re.compile(r"dispatch: \d+ of \d+ registered repo")
ENTER_RE = re.compile(r"entering (\S+) \((.+?)\) --")
SKIP_RE = re.compile(r"skip (ASK-\d+): (.*)")
GUARD_RE = re.compile(
    r"its open PR #(\d+) is on (\S+), but converge would commit onto (\S+) --")
REDRIVE_RE = re.compile(r"reviewer redrive: (ASK-\d+) PR #(\d+)")
OUTCOME_PREFIXES = ("dispatching ", "dispatched ", "nothing ready", "DAILY CAP")
# Legitimate holds that are not a stall: concurrency cap, a live run, no repo.
HOLD_MARKERS = ("skip: ", "skip kipi-system: a converge run", "no free repo",
                "no dispatchable repo", "STALE:", "heartbeat:")


def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def parse_turns(lines):
    """Split log lines into turns: [{ts, repo, path, msgs}]. Untimestamped lines
    (review-redrive stderr) are dropped; they repeat a timestamped line."""
    turns = []
    cur = None
    for raw in lines:
        m = LINE_RE.match(raw)
        if not m:
            continue
        ts, msg = m.groups()
        if TURN_RE.match(msg):
            cur = {"ts": ts, "repo": "home", "path": None, "msgs": []}
            turns.append(cur)
            continue
        if cur is None:
            continue
        e = ENTER_RE.match(msg)
        if e:
            cur["repo"], cur["path"] = e.group(1), e.group(2)
        cur["msgs"].append((ts, msg))
    return turns


def turn_outcome(turn):
    return any(msg.startswith(OUTCOME_PREFIXES) for _, msg in turn["msgs"])


def turn_stalls(turn):
    """{issue: info} for the issues this turn skipped without any outcome."""
    if turn_outcome(turn):
        return {}
    found = {}
    redrives = {}
    held = any(msg.startswith(HOLD_MARKERS) for _, msg in turn["msgs"])
    for ts, msg in turn["msgs"]:
        r = REDRIVE_RE.match(msg)
        if r:
            redrives[r.group(1)] = int(r.group(2))
        s = SKIP_RE.match(msg)
        if s:
            issue, rest = s.groups()
            g = GUARD_RE.search(rest)
            if g:
                found[issue] = {"class": "branch-guard", "pr": int(g.group(1)),
                                "actual": g.group(2), "expect": g.group(3)}
            else:
                found[issue] = {"class": "unknown", "detail": rest[:160]}
    if not found and not held:
        for issue, pr in redrives.items():
            found[issue] = {"class": "unknown", "pr": pr,
                            "detail": "redrive selected, nothing dispatched"}
    return found


def scan(turns, k=K_TURNS):
    """-> (fires, counts). fires: one record each time a (repo, issue) REACHES k
    stalled turns in a row. counts: the state at the end of the log."""
    counts = {}
    fires = []
    for t in turns:
        repo = t["repo"]
        stalled = turn_stalls(t)
        for key in [x for x in counts if x[0] == repo and x[1] not in stalled]:
            del counts[key]
        for issue, info in stalled.items():
            c = counts.setdefault((repo, issue), {"n": 0, "first": t["ts"]})
            c["n"] += 1
            c["last"], c["info"], c["path"] = t["ts"], info, t["path"]
            if c["n"] == k:
                fires.append({"repo": repo, "issue": issue, "ts": t["ts"],
                              "first": c["first"], "info": info,
                              "path": t["path"]})
    return fires, counts


def active_stalls(turns, now, k=K_TURNS):
    _, counts = scan(turns, k)
    out = {}
    for (repo, issue), c in counts.items():
        if c["n"] >= k and (now - parse_ts(c["last"])).total_seconds() <= ACTIVE_WINDOW_S:
            out[(repo, issue)] = c
    return out


# ---- effects: every outside call goes through these, so tests replace them ----

def run(cmd, cwd=None):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def linear_comment(issue, body):
    """Comment on the Linear issue through linear-sync.py's graphql (the fleet's
    one Linear client). Returns (ok, detail); failure never blocks a repair."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "kipi_linear_sync", str(HERE / "linear-sync.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        q = 'query($id:String!){issue(id:$id){id}}'
        iid = mod.graphql(q, {"id": issue})["issue"]["id"]
        m = ('mutation($input:CommentCreateInput!)'
             '{commentCreate(input:$input){success}}')
        mod.graphql(m, {"input": {"issueId": iid, "body": body}})
        return True, "commented"
    except Exception as exc:  # noqa: BLE001  (a comment must not stop a repair)
        return False, "linear comment failed: %s" % exc


def repair_branch_guard(path, issue, info, apply, runner=None):
    """Move the open PR's work onto sana/ask-n. Returns (ok, detail)."""
    runner = runner or run
    pr, actual, expect = info["pr"], info["actual"], info["expect"]
    if not apply:
        return True, ("DRY: would push PR #%d head to refs/heads/%s (create-only), "
                      "open a replacement PR, close #%d (no branch delete), "
                      "comment on %s" % (pr, expect, pr, issue))
    rc, out = runner(["gh", "pr", "view", str(pr), "--json",
                      "state,headRefOid,headRefName,baseRefName,title,body,"
                      "isCrossRepository"], path)
    if rc != 0:
        return False, "gh pr view failed: %s" % out[:200]
    pv = json.loads(out)
    if pv.get("state") != "OPEN" or pv.get("isCrossRepository") \
            or pv.get("headRefName") != actual:
        return False, "PR #%d no longer matches the logged stall (%s)" % (pr, out[:160])
    oid = pv["headRefOid"]
    rc, slug = runner(["gh", "repo", "view", "--json", "nameWithOwner", "-q",
                       ".nameWithOwner"], path)
    slug = slug.strip()
    if rc != 0 or "/" not in slug:
        return False, "cannot resolve repo slug: %s" % slug[:120]
    rc, out = runner(["gh", "api", "repos/%s/git/ref/heads/%s" % (slug, expect)], path)
    if rc == 0:
        have = json.loads(out)["object"]["sha"]
        if have != oid:
            return False, ("%s already exists at %s, not the PR head %s; two live "
                           "branches is a guess, not a repair" % (expect, have[:8], oid[:8]))
    else:
        rc, out = runner(["gh", "api", "-X", "POST", "repos/%s/git/refs" % slug,
                          "-f", "ref=refs/heads/%s" % expect, "-f", "sha=%s" % oid], path)
        if rc != 0:
            return False, "create ref failed: %s" % out[:200]
    rc, out = runner(["gh", "pr", "list", "--head", expect, "--state", "open",
                      "--json", "number", "-q", ".[0].number"], path)
    new_pr = out.strip() if rc == 0 else ""
    if not new_pr:
        body = (pv.get("body") or "") + (
            "\n\nReplaces #%d. GitHub closes a PR when its head branch is renamed, so "
            "the same commit was pushed to %s and this PR opened on it "
            "(dispatch stall checker, ASK-3064)." % (pr, expect))
        rc, out = runner(["gh", "pr", "create", "--head", expect, "--base",
                          pv["baseRefName"], "--title", pv["title"], "--body", body], path)
        if rc != 0:
            return False, "create PR failed: %s" % out[:200]
        m = re.search(r"/pull/(\d+)", out)
        new_pr = m.group(1) if m else ""
    rc, out = runner(["gh", "pr", "close", str(pr), "--comment",
                      "Superseded by #%s: same commit on %s so dispatch can reach it. "
                      "The old branch %s is kept." % (new_pr, expect, actual)], path)
    if rc != 0:
        return False, "close old PR failed: %s" % out[:200]
    ok, why = linear_comment(
        issue, "Dispatch stall repaired (ASK-3064): PR #%d was on `%s`; pushed %s to "
        "`%s` and opened #%s. Old PR closed, old branch kept." % (pr, actual, oid[:8], expect, new_pr))
    return True, "moved #%d -> #%s on %s (%s)" % (pr, new_pr, expect, why)


def kickstart():
    return run(["launchctl", "kickstart", "gui/%d/%s" % (os.getuid(), DISPATCH_LABEL)])


def notify(msg):
    return run(["bash", str(HERE / "slack-notify.sh"), msg])


# ---- the state machine ----

def load_state(p):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return {}


def save_state(p, st):
    tmp = "%s.tmp.%d" % (p, os.getpid())
    Path(tmp).write_text(json.dumps(st, indent=1, sort_keys=True))
    os.replace(tmp, p)


def tick(turns, now, state, apply, home_path, say):
    """One checker pass. Mutates `state`; every effect is announced through say()."""
    active = active_stalls(turns, now)
    for key in list(state):
        repo, issue = key.split("|", 1)
        if (repo, issue) not in active:
            kicked = parse_ts(state[key]["kicked_at"])
            disp = [mts for t in turns if t["repo"] == repo
                    for mts, m in t["msgs"]
                    if m.startswith("dispatched ") and parse_ts(mts) > kicked]
            say("recovered %s repo=%s: dispatched at %s" % (issue, repo, disp[0])
                if disp else "cleared %s repo=%s: stall no longer in the log tail" % (issue, repo))
            if apply:
                del state[key]
    if not active:
        last = turns[-1]["ts"] if turns else "none"
        say("ok: no stall (turns=%d, last turn %s)" % (len(turns), last))
        return
    for (repo, issue), c in sorted(active.items()):
        key = "%s|%s" % (repo, issue)
        info = c["info"]
        say("STALL %s repo=%s class=%s turns=%d since=%s last=%s" % (
            issue, repo, info["class"], c["n"], c["first"], c["last"]))
        st = state.get(key)
        if st is None:
            path = c.get("path") or home_path
            if info["class"] == "branch-guard":
                ok, why = repair_branch_guard(path, issue, info, apply)
                say("repair %s: %s" % ("ok" if ok else "FAILED", why))
            else:
                ok, why = False, "unknown class: %s" % info.get("detail", "")
                say("no repair known for this class (%s); kickstart only" % why)
            if apply:
                rc, out = kickstart()
                say("kickstart %s rc=%d" % (DISPATCH_LABEL, rc))
                state[key] = {"kicked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "repair": "ok" if ok else why, "ticketed": False}
            else:
                say("DRY: would kickstart %s" % DISPATCH_LABEL)
            continue
        if st.get("ticketed"):
            continue
        kicked = parse_ts(st["kicked_at"])
        after = parse_ts(c["last"]) > kicked
        silent = (now - kicked).total_seconds() > NO_TURN_AFTER_KICK_S and not after
        if after or silent:
            msg = ("dispatch stalled: %s (%s, repo %s) still skipped after repair+restart "
                   "at %s. repair=%s. Do: read ~/.config/kipi/dispatch.log tail and "
                   "dispatch-stall-check.log." % (issue, info["class"], repo,
                                                  st["kicked_at"], st["repair"]))
            if apply:
                rc, out = notify(msg)
                st["ticketed"] = True
                say("ticket filed for Sana rc=%d: %s" % (rc, msg))
            else:
                say("DRY: would file ONE ticket: %s" % msg)
        else:
            say("waiting for a turn after the kickstart at %s" % st["kicked_at"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", default=str(HOME / ".config/kipi/dispatch.log"))
    ap.add_argument("--state", default=str(HOME / ".config/kipi/dispatch-stall-state.json"))
    ap.add_argument("--out-log", default=str(HOME / ".config/kipi/dispatch-stall-check.log"))
    ap.add_argument("--home", default=os.environ.get("KIPI_REPO_MAIN", str(HERE.parents[2])))
    ap.add_argument("--now", help="ISO UTC; defaults to the clock")
    ap.add_argument("--apply", action="store_true", help="act; without it, dry run")
    ap.add_argument("--replay", action="store_true", help="list when it WOULD have fired")
    ap.add_argument("--since", default="", help="replay: only fires at or after this ISO ts")
    ap.add_argument("-k", type=int, default=K_TURNS)
    a = ap.parse_args(argv)
    now = parse_ts(a.now) if a.now else datetime.now(timezone.utc)
    try:
        lines = Path(a.log).read_text(errors="replace").splitlines()
    except OSError as exc:
        print("cannot read %s: %s" % (a.log, exc), file=sys.stderr)
        return 1
    turns = parse_turns(lines)
    if a.replay:
        fires, _ = scan(turns, a.k)
        fires = [f for f in fires if f["ts"] >= a.since]
        for f in fires:
            tick_at = parse_ts(f["ts"]) + timedelta(seconds=INTERVAL_S)
            print("%s would FIRE %s repo=%s class=%s: turn %d of the run at %s "
                  "(run began %s); acts on the first tick after, by %s at the latest" % (
                      f["ts"], f["issue"], f["repo"], f["info"]["class"], a.k, f["ts"],
                      f["first"], tick_at.strftime("%Y-%m-%dT%H:%M:%SZ")))
            if f["info"]["class"] == "branch-guard":
                i = f["info"]
                print("    repair: PR #%d %s -> %s, then kickstart %s" % (
                    i["pr"], i["actual"], i["expect"], DISPATCH_LABEL))
            else:
                print("    no known repair: kickstart once, then ONE ticket if it persists")
        print("replay: %d fire(s) over %d turns" % (len(fires), len(turns)))
        return 0

    def say(msg):
        line = "%s %s%s" % (now.strftime("%Y-%m-%dT%H:%M:%SZ"), "" if a.apply else "[dry] ", msg)
        print(line)
        if a.apply:
            with open(a.out_log, "a") as fh:
                fh.write(line + "\n")

    if not a.apply:
        tick(turns, now, load_state(a.state), False, a.home, say)
        return 0
    # ONE WRITER for the state file: a manual run while the job ticks would
    # otherwise kickstart twice and file two tickets.
    with open(a.state + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        st = load_state(a.state)
        tick(turns, now, st, True, a.home, say)
        save_state(a.state, st)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001  exit non-zero so launchd-health sees it
        traceback.print_exc()
        sys.exit(1)
