#!/usr/bin/env python3
"""test-pr-owner.py -- every open fleet PR gets an owner, whatever its branch (ASK-3962).

RED FIRST. On main at bc9a9b82 there is no pr-owner.py, so this prints RED and exits
1: kipi-system #526 (fix/, open since 10-07), brag #2 (since 10-24) and ktlyst #8
(since 11-01) had no mover, because every PR selector read only `sana/` heads and
wip_release moved a PR only at 5 open sana/ PRs (dead-end audit 2026-11-08, rows 25,
46, 54).

What it proves, all on fixtures, never on live data (the state file, the fleet and
every gh and Linear call are faked; the state path is asserted to be under a temp
dir before anything runs):
  * decide() on the three real shapes and on every rule of the design on ASK-3962.
  * --apply sends a close with the branch kept, a merge pinned to the head, a review,
    a rework comment and the ticket writes through linear-sync.py; a dry run sends
    no write at all and leaves no state file; a reworked PR still red at the same
    head one age later closes.
  * a fork alert runs through the REAL slack-notify.sh and alert-to-linear.py main()
    (only the Linear transport is fake), so each fork PR must get its own ticket
    and pr-owner records the ticket the sink named, never a bare exit 0 (PR #659
    round 3; RCA q-system/output/rca/rca-pr-owner-three-rounds-2026-11-08.md).
  * a PR cap-ladder.py owns is yielded, asked of the REAL ladder_owns() (this tree's
    cap-ladder.py, else PR #662's pushed branch), and a superset when it is absent.
  * the repo set is the dispatcher's own fleet_candidates on a fixture registry, and
    a dispatcher without that function refuses the run.
  * the wiring: the terminal-states open-pr consumer row, the plist, the pinned
    checkout table.

Run: python3 q-system/.q-system/scripts/test/test-pr-owner.py   (exit 0 = pass)
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import plistlib
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
REPO = SCRIPTS.parents[2]
SUBJECT = Path(os.environ.get("KIPI_PR_OWNER_PATH") or SCRIPTS / "pr-owner.py")

FAILS: list[str] = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(name)


print("test-pr-owner.py")
if not SUBJECT.is_file():
    print(f"RED: no {SUBJECT.name}: kipi-system #526, brag #2 and ktlyst #8 have no mover "
          "(no fleet script owns a PR that is not on a sana/ head, under the 5-PR ceiling)")
    sys.exit(1)

TMP = Path(tempfile.mkdtemp(prefix="pr-owner-test-"))
os.environ["KIPI_PR_OWNER_STATE"] = str(TMP / "state" / "state.json")
os.environ["KIPI_STATE_DIR"] = str(TMP / "worker")
os.environ.pop("KIPI_PR_OWNER_NOW", None)

spec = importlib.util.spec_from_file_location("pr_owner", SUBJECT)
po = importlib.util.module_from_spec(spec)
spec.loader.exec_module(po)

# NO REAL SUBPROCESS BEFORE THE FAKE IS IN. Measured 2026-11-08 on the first
# mutation run: with the --delete-branch refusal mutated away, the refusal check
# below ran before po.run was faked, so the mutant sent a real
# `gh pr close 1 --delete-branch` from this checkout. It hit a fork PR closed since
# July and changed nothing, by luck. Every call now lands here until the fake is set.
BLOCKED: list[list[str]] = []
# The real run(), kept for ONE caller: the sink harness below, which runs a temp
# copy of slack-notify.sh. fake_run refuses any other path to it.
REAL_RUN = po.run


def blocked_run(argv, timeout=120, env=None, cwd=None):
    BLOCKED.append([str(a) for a in argv])
    return 1, "", "test: real subprocess blocked"


po.run = blocked_run

check("the state path is the temp dir, never the live one", str(po.state_path()).startswith(str(TMP)), True)
check("the worker state dir is the temp dir", str(po.worker_state_dir()).startswith(str(TMP)), True)

H = 3600
NOW = po.iso_s("2026-11-08T21:00:00Z")
FLOOR = po.floor_desc()
LANE_H = 24


def pr(**kw):
    base = {"slug": "assafkip/kipi-system", "repo": "kipi-system", "path": "/fx/kipi-system",
            "number": 526, "title": "fix(fleet-scan): scan launchd runner trees",
            "url": "https://github.com/assafkip/kipi-system/pull/526",
            "branch": "fix/fleet-scan-runner-trees-drain-ask-2540", "head": "a6de9861" + "0" * 32,
            "base": "main", "created": NOW - 32 * 24 * H, "pushed": NOW - 32 * 24 * H,
            "draft": False, "mergeable": "MERGEABLE", "merge_state": "BLOCKED",
            "ci": "green", "ci_names": [], "touches_ledger": False, "provenance": "same-repo",
            "reviewer": ("rejected", "delta fa5dab03..a6de9861: REQUEST CHANGES")}
    base.update(kw)
    return base


def ticket(ident, state_type="backlog", started_h=None, claim=""):
    return {"id": ident, "state_type": state_type, "state_name": state_type.title(),
            "started": (NOW - started_h * H) if started_h is not None else None,
            "claim": claim, "lane_hours": LANE_H}


def loader(table):
    def load(ident):
        v = table.get(ident)
        if isinstance(v, Exception):
            raise v
        return v
    return load


def act_of(p, tickets=None, state=None, review_left=1, skip=()):
    return po.decide(p, NOW, state or {}, loader(tickets or {}), review_left, set(skip))


# ---------------------------------------------------------------- the three real shapes
print("-- the three PRs the audit found with no mover")
d = act_of(pr(), {"ASK-2540": ticket("ASK-2540", "started", started_h=2.6)})
check("#526: REQUEST CHANGES, ticket started 2.6h ago -> wait (lane window)", d["action"], "wait")
check("#526: the reason names the lane window", "lane window" in d["reason"], True)
d = act_of(pr(), {"ASK-2540": ticket("ASK-2540", "backlog")})
check("#526: ticket back in Backlog, fix/ branch -> close-requeue", d["action"], "close-requeue")

brag = pr(slug="assafkip/brag", repo="brag", number=2, branch="sana/ask-3036", head="cef07083" + "0" * 32,
          created=NOW - 15 * 24 * H, pushed=NOW - 15 * 24 * H, title="brag: pace gates",
          reviewer=("rejected", "unstated: no verdict parsed from the review"))
t3036 = {"ASK-3036": ticket("ASK-3036", "started", started_h=15 * 24)}
check("brag #2: no verdict, worker branch, ticket started 15 days ago -> rework",
      act_of(brag, t3036)["action"], "rework")
k8 = pr(slug="assafkip/ktlyst-saas-product", repo="ktlyst", number=8, branch="sana/ask-142",
        created=NOW - 7 * 24 * H, pushed=NOW - 0.1 * H, reviewer=("unreviewed", FLOOR))
check("ktlyst #8: pushed 6 minutes ago -> wait, even with a review owed", act_of(k8, review_left=1)["action"], "wait")

# ---------------------------------------------------------------- the rework strike
print("-- rework once, then close at the same head one age later")
key = "assafkip/brag#2"
s_same = {"strikes": {key: {"head": brag["head"], "at": NOW - 10 * H}}}
check("strike 10h ago, same head -> wait", act_of(brag, t3036, s_same)["action"], "wait")
s_old = {"strikes": {key: {"head": brag["head"], "at": NOW - 49 * H}}}
check("strike 49h ago, same head -> close-requeue", act_of(brag, t3036, s_old)["action"], "close-requeue")
s_moved = {"strikes": {key: {"head": "f" * 40, "at": NOW - 49 * H}}}
check("strike on an older head (the worker pushed) -> rework again", act_of(brag, t3036, s_moved)["action"], "rework")

# ---------------------------------------------------------------- every other rule
print("-- the rest of the rules")
check("open 47h -> young", act_of(pr(created=NOW - 47 * H, pushed=NOW - 47 * H))["action"], "young")
check("--skip owner/repo#n -> skip", act_of(pr(), skip={"assafkip/kipi-system#526"})["action"], "skip")
check("--skip repo#n -> skip", act_of(pr(), skip={"kipi-system#526"})["action"], "skip")
check("mergeability not computed -> wait", act_of(pr(mergeable="UNKNOWN"))["action"], "wait")
check("approved, mergeable, CLEAN -> merge",
      act_of(pr(reviewer=("approved", "APPROVE"), merge_state="CLEAN"))["action"], "merge")
check("approved but a draft -> not a merge",
      act_of(pr(reviewer=("approved", "APPROVE"), merge_state="CLEAN", draft=True))["action"] != "merge", True)
check("checks running -> wait", act_of(pr(ci="running", ci_names=["validate"]))["action"], "wait")
unrev = pr(reviewer=("unreviewed", FLOOR), branch="feat/x", title="feat: x")
check("CI green, never reviewed -> review", act_of(unrev)["action"], "review")
check("CI green, never reviewed, run's review spent -> wait", act_of(unrev, review_left=0)["action"], "wait")
rv_key = "assafkip/kipi-system#526"
check("review asked at this head 3h ago -> wait",
      act_of(unrev, state={"reviews": {rv_key: {"head": unrev["head"], "at": NOW - 3 * H}}})["action"], "wait")
check("review asked at this head 49h ago, no verdict -> red, closes with no ticket",
      act_of(unrev, state={"reviews": {rv_key: {"head": unrev["head"], "at": NOW - 49 * H}}})["action"], "close-comment")
check("CI red, no ticket -> close-comment",
      act_of(pr(ci="red", ci_names=["validate=FAILURE"], branch="feat/x", title="x", reviewer=("unreviewed", FLOOR)))["action"],
      "close-comment")
check("conflict, ticket Done -> close-comment",
      act_of(pr(mergeable="CONFLICTING"), {"ASK-2540": ticket("ASK-2540", "completed")})["action"], "close-comment")
check("review cap -> red",
      act_of(pr(reviewer=("cap", "review cap reached (3); needs a human decision")),
             {"ASK-2540": ticket("ASK-2540", "backlog")})["action"], "close-requeue")
check("approved but BEHIND -> red, not a merge",
      act_of(pr(reviewer=("approved", "APPROVE"), merge_state="BEHIND"), {"ASK-2540": ticket("ASK-2540")})["action"],
      "close-requeue")
check("Linear cannot answer -> hold, never 'no ticket'",
      act_of(pr(), {"ASK-2540": RuntimeError("HTTP 500")})["action"], "hold")
check("started long ago but a live claim -> wait",
      act_of(brag, {"ASK-3036": ticket("ASK-3036", "started", started_h=400, claim="a live claim by w1")})["action"], "wait")
lane = pr(branch="sana/ask-901-slug", title="lane")
check("lane branch with an open ticket -> close-requeue, never rework (the worker cannot commit there)",
      act_of(lane, {"ASK-901": ticket("ASK-901")})["action"], "close-requeue")
sup = pr(branch="lessons/weekly-2026-10-19", title="chore(lessons): weekly distill", reviewer=("unreviewed", FLOOR),
         touches_ledger=True, lessons={"batch": 19, "on_base": 19})
check("lessons batch all on base -> close-superseded", act_of(sup)["action"], "close-superseded")
check("lessons batch with one entry not on base -> not superseded",
      act_of({**sup, "lessons": {"batch": 19, "on_base": 18}})["action"] != "close-superseded", True)

print("-- forks are never acted on (PR #659 round 1, major 1)")
LOOKED: list[str] = []


def watching(ident):
    LOOKED.append(ident)
    return ticket(ident, "started", started_h=400)


fork = pr(provenance="fork", branch="sana/ask-2540", title="looks like ours")
check("a fork on sana/ask-2540, its ticket started long ago -> outside",
      po.decide(fork, NOW, {}, watching, 1, set())["action"], "outside")
check("... and Linear is never read for it", LOOKED, [])
check("an unstated head -> outside", act_of(pr(provenance="unstated"))["action"], "outside")
check("a fork whose alert is filed -> outside-filed, no second alert",
      act_of(fork, state={"outside": {"assafkip/kipi-system#526": {"head": "x", "at": NOW - H}}})["action"], "outside-filed")
check("a fork opened 100 seconds ago -> young, not alerted (PR #659 round 3, minor)",
      act_of(pr(provenance="fork", created=NOW - 100, pushed=NOW - 100))["action"], "young")
check("an old fork pushed an hour ago -> wait (the 12h quiet gate holds forks too)",
      act_of(pr(provenance="fork", pushed=NOW - H))["action"], "wait")
check("provenance comes from ci-redrive's head_provenance",
      [po.normalize("o/r", "r", "/p", {"number": 1, "isCrossRepository": v})["provenance"] for v in (False, True, None)],
      ["same-repo", "fork", "unstated"])

print("-- a PR cap-ladder.py owns is yielded (ASK-3824, PR #662)")
owned = pr(reviewer=("approved", "APPROVE"), merge_state="CLEAN", ladder="cap-ladder owns it: ASK-2540 holds capout")
check("a ladder-owned PR -> ladder, even when it would merge", act_of(owned)["action"], "ladder")
check("a ladder-owned PR -> ladder, and Linear is never read",
      (po.decide(owned, NOW, {}, watching, 1, set())["action"], LOOKED), ("ladder", []))
check("a ladder-owned PR still young -> young (the gates come first)",
      act_of({**owned, "created": NOW - H, "pushed": NOW - H})["action"], "young")

print("-- merge needs our read of CI green; UNSTABLE alone is no veto (PR #659 rounds 1 and 2)")
ok_rv = ("approved", "APPROVE")
check("approved, UNSTABLE, CI red -> not a merge",
      act_of(pr(reviewer=ok_rv, merge_state="UNSTABLE", ci="red", ci_names=["lint=FAILURE"]),
             {"ASK-2540": ticket("ASK-2540")})["action"], "close-requeue")
check("approved, UNSTABLE only from the advisory codex slot, CI green -> merge (round 2 major)",
      act_of(pr(reviewer=ok_rv, merge_state="UNSTABLE"), {"ASK-2540": ticket("ASK-2540")})["action"], "merge")
check("approved, UNSTABLE, CI still running -> wait",
      act_of(pr(reviewer=ok_rv, merge_state="UNSTABLE", ci="running", ci_names=["validate"]))["action"], "wait")
check("normalize: codex-approved red is not CI, so an UNSTABLE PR reads CI green",
      po.normalize("o/r", "r", "/p", {"number": 1, "isCrossRepository": False, "mergeStateStatus": "UNSTABLE",
                                      "statusCheckRollup": [{"__typename": "StatusContext", "context": "kipi/codex-approved", "state": "FAILURE"},
                                                            {"__typename": "CheckRun", "name": "validate", "status": "COMPLETED", "conclusion": "SUCCESS"}]})["ci"],
      "green")
check("approved, CLEAN, CI still running -> wait",
      act_of(pr(reviewer=ok_rv, merge_state="CLEAN", ci="running", ci_names=["validate"]))["action"], "wait")
check("approved, CLEAN, but our read of CI is red -> not a merge (the two reads can disagree)",
      act_of(pr(reviewer=ok_rv, merge_state="CLEAN", ci="red", ci_names=["scan=ACTION_REQUIRED"]),
             {"ASK-2540": ticket("ASK-2540")})["action"], "close-requeue")
check("approved, HAS_HOOKS, CI green -> merge", act_of(pr(reviewer=ok_rv, merge_state="HAS_HOOKS"))["action"], "merge")

print("-- an approved PR GitHub will not merge is asked of pr-verdict-lib.sh rework_gate (PR #659 round 5)")
t2540 = {"ASK-2540": ticket("ASK-2540")}
check("approved, CI green, MERGEABLE, BLOCKED -> wait, never rework or close (rework_gate says terminal)",
      act_of(pr(reviewer=ok_rv, merge_state="BLOCKED"), t2540)["action"], "wait")
check("approved, CI green, MERGEABLE, merge state UNKNOWN -> wait",
      act_of(pr(reviewer=ok_rv, merge_state="UNKNOWN"), t2540)["action"], "wait")
no_field = po.normalize("o/r", "r", "/p", {"number": 1, "isCrossRepository": False, "mergeable": "MERGEABLE"})["merge_state"]
check("gh omitted mergeStateStatus on an approved green PR -> wait, not a rework (round 5 minor)",
      act_of(pr(reviewer=ok_rv, merge_state=no_field), t2540)["action"], "wait")
check("approved, BEHIND -> still red (rework_gate: a rebase round)",
      act_of(pr(reviewer=ok_rv, merge_state="BEHIND"), t2540)["action"], "close-requeue")
_lib = getattr(po, "VERDICT_LIB", None)
po.VERDICT_LIB = TMP / "no-such-lib.sh"
check("rework_gate cannot answer -> hold, never a guess",
      act_of(pr(reviewer=ok_rv, merge_state="BLOCKED"), t2540)["action"], "hold")
po.VERDICT_LIB = _lib

# ---------------------------------------------------------------- readers
print("-- readers")
check("the floor description is read from reviewer-floor.sh", FLOOR.startswith("no reviewer verdict at this head"), True)
check("reviewer-floor.sh posts exactly that variable",
      '-f "description=$FLOOR_DESC"' in (SCRIPTS / "reviewer-floor.sh").read_text(), True)
rs = lambda st, desc: po.reviewer_state([{"context": "kipi/reviewer-approved", "state": st, "description": desc}], FLOOR)
check("floor status -> unreviewed", rs("failure", FLOOR)[0], "unreviewed")
check("no status -> unreviewed", po.reviewer_state([], FLOOR)[0], "unreviewed")
check("REQUEST CHANGES -> rejected", rs("failure", "delta a..b: REQUEST CHANGES")[0], "rejected")
check("unstated -> rejected", rs("failure", "unstated: no verdict parsed from the review")[0], "rejected")
check("APPROVE -> approved", rs("success", "APPROVE")[0], "approved")
check("cap pending -> cap", rs("pending", "review cap reached (3); needs a human decision")[0], "cap")
check("CI: a running check run -> running",
      po.ci_state([{"__typename": "CheckRun", "name": "validate", "status": "IN_PROGRESS", "conclusion": ""}])[0], "running")
check("CI: a failed check run -> red",
      po.ci_state([{"__typename": "CheckRun", "name": "validate", "status": "COMPLETED", "conclusion": "FAILURE"}])[0], "red")
check("CI: the reviewer context is not CI",
      po.ci_state([{"__typename": "StatusContext", "context": "kipi/reviewer-approved", "state": "FAILURE"}])[0], "green")
check("CI: a third engine's slot is not CI either (PR #659 round 1, minor 1)",
      po.ci_state([{"__typename": "StatusContext", "context": "kipi/gemini-approved", "state": "FAILURE"}])[0], "green")
check("ticket from a fix/ branch", po.ticket_candidates("fix/fleet-scan-runner-trees-drain-ask-2540", ""), ["ASK-2540"])
check("ticket from a title", po.ticket_candidates("feature", "fix(ASK-142): stop-hook routing"), ["ASK-142"])
check("lessons/weekly-2026-10-19 names no ticket", po.ticket_candidates("lessons/weekly-2026-10-19", "weekly distill 2026-10-19"), [])
check("worker branch", po.worker_branch_issue("sana/ask-3036"), "ASK-3036")
check("lane branch is not a worker branch", po.worker_branch_issue("sana/ask-3036-slug"), "")

# ---------------------------------------------------------------- the cap-ladder yield
print("-- ladder_check drives the real cap-ladder.py ladder_owns() (ASK-3824, PR #662)")
import subprocess


def try_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as exc:  # an old pr-owner.py has no ladder_check at all
        return f"RAISED {type(exc).__name__}: {exc}"


LSTATE = TMP / "ladder-state"
(LSTATE / "pr-reviews" / "codex").mkdir(parents=True)
(LSTATE / "linear-worker-attempts.json").write_text(json.dumps({
    "ASK-777": {"capout": True, "capout_at": "2026-11-01T00:00:00Z", "count": 1},
    "ASK-778": {"rounds": 1}}))
(LSTATE / "pr-reviews" / ".round-cap-o_fx-pr-55").write_text("")
lpr = lambda branch, n=10: pr(slug="o/fx", number=n, branch=branch)

# The REAL ladder: this tree's copy once PR #662 is on main, else #662's pushed
# branch. Never a hand model of what the ladder owns (RCA 2026-11-08, root cause 2).
real_src = SCRIPTS / "cap-ladder.py"
if not real_src.is_file():
    got = subprocess.run(["git", "-C", str(REPO), "show",
                          "origin/sana/ask-3824-ladder:q-system/.q-system/scripts/cap-ladder.py"],
                         capture_output=True, text=True)
    if got.returncode == 0 and "def ladder_owns(" in got.stdout:
        real_src = TMP / "ladder-real" / "cap-ladder.py"
        real_src.parent.mkdir()
        real_src.write_text(got.stdout)
    else:
        real_src = None
REAL_CASES = [("sana/ask-777", 10), ("sana/ask-777-slug", 10), ("sana/ask-555", 55), ("sana/ask-778", 10),
              ("fix/x-ask-777", 10)]
if real_src:
    po.CAP_LADDER = real_src
    real_owns = {c: try_call(lambda *a: po.ladder_check(*a), lpr(*c), str(LSTATE)) for c in REAL_CASES}
    check("real ladder: sana/ask-777 with a capout -> owned",
          str(real_owns[("sana/ask-777", 10)]).startswith("cap-ladder owns it: ASK-777"), True)
    check("real ladder: a lane branch is never the ladder's", real_owns[("sana/ask-777-slug", 10)], "")
    check("real ladder: a round-cap marker for o/fx#55 -> owned",
          str(real_owns[("sana/ask-555", 55)]).startswith("cap-ladder owns it: ASK-555"), True)
    check("real ladder: an entry with no cap -> not owned", real_owns[("sana/ask-778", 10)], "")
    check("real ladder: a fix/ branch -> not owned", real_owns[("fix/x-ask-777", 10)], "")
else:
    real_owns = {}
    print("  note: cap-ladder.py is in neither this tree nor origin/sana/ask-3824-ladder; "
          "the real-ladder checks run once PR #662 is on main")

# PR #662 NOT IN THIS CHECKOUT: yield everything the ladder could own. A superset
# of ladder_owns, so the two jobs never both write one PR.
po.CAP_LADDER = TMP / "no-such-dir" / "cap-ladder.py"
fb = {c: try_call(lambda *a: po.ladder_check(*a), lpr(*c), str(LSTATE)) for c in REAL_CASES}
check("ladder absent: sana/ask-777 with a record -> yielded", "PR #662" in str(fb[("sana/ask-777", 10)]), True)
check("ladder absent: the lane branch with a record -> yielded too", "PR #662" in str(fb[("sana/ask-777-slug", 10)]), True)
check("ladder absent: the round-cap marker -> yielded", "PR #662" in str(fb[("sana/ask-555", 55)]), True)
check("ladder absent: a fix/ branch with no marker -> not yielded", fb[("fix/x-ask-777", 10)], "")
check("ladder absent: no record at all -> not yielded",
      try_call(lambda *a: po.ladder_check(*a), lpr("sana/ask-999"), str(LSTATE)), "")
if real_owns:
    check("ladder absent yields every PR the real ladder owns (never two writers)",
          [c for c in REAL_CASES if real_owns[c] and not str(fb[c]).startswith("cap-ladder")
           and "PR #662" not in str(fb[c])], [])
broken = TMP / "broken" / "cap-ladder.py"
broken.parent.mkdir()
broken.write_text("X = 1\n")
po.CAP_LADDER = broken
check("a cap-ladder.py with no ladder_owns() raises, so main holds the PR",
      str(try_call(lambda *a: po.ladder_check(*a), lpr("sana/ask-777"), str(LSTATE))).startswith("RAISED RuntimeError"), True)
po.CAP_LADDER = real_src or (TMP / "no-such-dir" / "cap-ladder.py")

print("-- the branch is never deleted")
for argv in (["pr", "close", "1", "--delete-branch"], ["pr", "merge", "1", "-d"]):
    try:
        po.gh_write(argv)
        check(f"gh_write refuses {' '.join(argv)}", "sent", "refused")
    except SystemExit:
        check(f"gh_write refuses {' '.join(argv)}", "refused", "refused")
check("a refused write never reached a subprocess, real or blocked", BLOCKED, [])
src = SUBJECT.read_text()
check("'--delete-branch' appears only in the refusal", src.count('"--delete-branch"'), 1)

# ---------------------------------------------------------------- the real alert sink
# THE SINK IS DRIVEN, NOT MODELLED (PR #659 round 3, major). A temp copy of the
# real slack-notify.sh runs as a real subprocess, and its alert-to-linear.py is a
# wrapper that runs the REAL alert-to-linear.py main(): fingerprint, lock, dedup,
# create. Only the Linear transport is fake, a JSON file, and urlopen is blocked.
# Round 3's fake returned (0, "", "") for every alert, so a second fork PR was
# never a case this suite could see.
SINK = TMP / "sink"
SINK.mkdir()
SINK_NOTIFY = SINK / "slack-notify.sh"
shutil.copy(SCRIPTS / "slack-notify.sh", SINK_NOTIFY)
FAKE_LINEAR = TMP / "fake-linear.json"
FAKE_LINEAR.write_text(json.dumps({"issues": [], "comments": []}))
(SINK / "alert-to-linear.py").write_text(r"""
import importlib.util, json, os, sys, urllib.request
def _blocked(*a, **k):
    raise RuntimeError("test: network blocked")
urllib.request.urlopen = _blocked
spec = importlib.util.spec_from_file_location("alert_to_linear_real", os.environ["PR_OWNER_TEST_SINK_REAL"])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
DB = os.environ["PR_OWNER_TEST_FAKE_LINEAR"]
mod._state_dir = lambda: os.environ["PR_OWNER_TEST_ALERT_STATE"]
class Fake:
    def linear_api_key(self):
        return "test-key"
    def graphql(self, q, v=None):
        db = json.load(open(DB))
        v = v or {}
        if "teams(filter" in q:
            out = {"teams": {"nodes": [{"id": "team-1", "key": "ASK"}]}}
        elif "labels(first" in q:
            out = {"team": {"labels": {"nodes": [{"id": "l1", "name": "owner:sana"}, {"id": "l2", "name": "needs-triage"}]}}}
        elif "projects(first" in q:
            out = {"team": {"projects": {"nodes": []}}}
        elif "issueCreate" in q:
            n = 9001 + len(db["issues"])
            i = {"id": f"uuid-{n}", "identifier": f"ASK-{n}", "url": f"https://linear.app/ASK-{n}",
                 "state": {"type": "backlog"}, "title": v["input"]["title"], "description": v["input"]["description"]}
            db["issues"].append(i)
            out = {"issueCreate": {"success": True, "issue": {k: i[k] for k in ("id", "identifier", "url")}}}
        elif "commentCreate" in q:
            db["comments"].append(v["input"])
            out = {"commentCreate": {"success": True}}
        elif "issue(id:" in q:
            hit = [i for i in db["issues"] if v.get("id") in (i["id"], i["identifier"])]
            out = {"issue": {k: hit[0][k] for k in ("id", "identifier", "url", "state")} if hit else None}
        else:
            raise RuntimeError("fake Linear: unexpected query " + q[:60])
        json.dump(db, open(DB, "w"))
        return out
mod._load_linear = lambda: Fake()
sys.exit(mod.main(sys.argv))
""")
os.environ.update({"KIPI_NOTIFY": str(SINK_NOTIFY), "PR_OWNER_TEST_SINK_REAL": str(SCRIPTS / "alert-to-linear.py"),
                   "PR_OWNER_TEST_FAKE_LINEAR": str(FAKE_LINEAR), "PR_OWNER_TEST_ALERT_STATE": str(TMP / "alert-state"),
                   "KIPI_INSTANCE_NAME": "kipi-system"})
for k in ("KIPI_LINEAR_API_URL", "KIPI_ALERT_CAPTURE", "PYTEST_CURRENT_TEST", "KIPI_LINEAR_QUEUE"):
    os.environ.pop(k, None)


def linear_db():
    return json.loads(FAKE_LINEAR.read_text())


# ---------------------------------------------------------------- the review runner
print("-- the review's output goes to a log file, never a pipe")
# pr-review-agent.sh starts a watchdog `( sleep "$secs"; ... ) &` (line 334) that
# inherits stdout. A caller reading the reviewer through a pipe waits for that
# sleep, up to 40 minutes after the review is done. This stub does the same with
# a 20s sleep, and runs as a real subprocess.
stub_root = TMP / "stubroot"
stub_root.mkdir()
(stub_root / "kipi").write_text('#!/bin/bash\necho "stub $*"\n( sleep 20 ) &\nexit 0\n')
saved = (po.ROOT, po.run, po.read_ticket)
po.ROOT = stub_root
po.run = lambda argv, timeout=120, env=None, cwd=None: (
    REAL_RUN(argv, timeout, env, cwd) if len(argv) > 1 and argv[1] == str(stub_root / "kipi") else blocked_run(argv))
po.read_ticket = loader({})
rv_pr = pr(slug="o/fx", number=77, branch="feat/x", title="feat: x", path=str(TMP))
t0 = time.monotonic()
got = try_call(po.act, rv_pr, {"action": "review", "reason": "CI green, no reviewer verdict"}, {}, NOW)
took = time.monotonic() - t0
po.ROOT, po.run, po.read_ticket = saved
check("the review returns while the reviewer's background sleep still holds its output (under 10s)",
      (took < 10, f"{took:.1f}s" if took >= 10 else "fast"), (True, "fast"))
check("... and reports the review posted", got[0] if isinstance(got, tuple) else got, True)
rlog = po.state_path().parent / "reviews" / "o_fx-pr-77.log"
check("... and the reviewer's output is in pr-owner's review log",
      "stub review 77 --repo" in (rlog.read_text() if rlog.is_file() else ""), True)
po.state_path().unlink(missing_ok=True)  # the dry run below asserts it leaves none

# ---------------------------------------------------------------- apply and dry, end to end
print("-- --apply and the dry run, end to end on a faked fleet")
SLUG = "o/fx"
SHA = {n: f"{n:02d}" + "ab" * 19 for n in range(1, 15)}
OLD, FRESH = "2026-10-01T00:00:00Z", "2026-11-08T20:00:00Z"
ROLL_OK = [{"__typename": "CheckRun", "name": "validate", "status": "COMPLETED", "conclusion": "SUCCESS"}]


def raw(n, branch, title="t", **kw):
    r = {"number": n, "title": title, "url": f"https://github.com/{SLUG}/pull/{n}", "headRefName": branch,
         "headRefOid": SHA[n], "baseRefName": "main", "createdAt": OLD, "isDraft": False, "isCrossRepository": False,
         "mergeable": "MERGEABLE", "mergeStateStatus": "BLOCKED", "statusCheckRollup": ROLL_OK}
    r.update(kw)
    return r


PRS = [raw(1, "fix/thing-ask-2540"), raw(2, "sana/ask-3036"), raw(3, "feat/ok", mergeStateStatus="CLEAN"),
       raw(4, "feat/a"), raw(5, "feat/b"), raw(6, "feat/fresh"), raw(7, "lessons/weekly-2026-10-19"),
       raw(8, "sana/ask-142"), raw(9, "sana/ask-3036", title="fork (ASK-2540)", isCrossRepository=True),
       raw(10, "sana/ask-777"), raw(11, "feat/other-fork", isCrossRepository=True),
       raw(12, "feat/new-fork", isCrossRepository=True, createdAt=FRESH),
       raw(14, "feat/busy-fork", isCrossRepository=True)]
PUSHED = {n: (FRESH if n in (6, 14) else OLD) for n in SHA}
REVIEWER = {1: ("failure", "delta x..y: REQUEST CHANGES"), 2: ("failure", "unstated: no verdict parsed from the review"),
            3: ("success", "APPROVE"), 4: ("failure", FLOOR), 5: ("failure", FLOOR), 6: ("failure", FLOOR),
            7: ("failure", FLOOR), 8: ("failure", "delta x..y: REQUEST CHANGES"),
            9: ("failure", "delta x..y: REQUEST CHANGES"), 10: ("failure", "delta x..y: REQUEST CHANGES"),
            11: ("failure", FLOOR), 12: ("failure", FLOOR), 14: ("failure", FLOOR)}
LEDGERS = {SHA[7]: {"k1": {"status": "published"}, "k2": {"status": "published"}}, "mb7": {}, "main": {"k1": {}, "k2": {}, "k0": {}}}
TICKETS = {"ASK-2540": ticket("ASK-2540", "backlog"), "ASK-3036": ticket("ASK-3036", "started", started_h=400),
           "ASK-142": ticket("ASK-142", "started", started_h=200), "ASK-777": ticket("ASK-777", "backlog")}
SENT: list[list[str]] = []


def fake_run(argv, timeout=120, env=None, cwd=None):
    argv = [str(a) for a in argv]
    SENT.append(argv)
    ok = lambda obj: (0, json.dumps(obj), "")
    if argv[:3] == ["gh", "pr", "list"]:
        return ok(PRS)
    if argv[:3] == ["gh", "pr", "view"]:
        n = int(argv[3])
        files = [{"path": "lesson-candidates/.processed.json"}] if n == 7 else [{"path": "x.py"}]
        return ok({"commits": [{"committedDate": PUSHED[n]}], "files": files})
    if argv[:2] == ["gh", "api"]:
        path = argv[2]
        if "/status" in path:
            n = next(k for k, v in SHA.items() if v in path)
            st, desc = REVIEWER[n]
            return ok({"statuses": [{"context": "kipi/reviewer-approved", "state": st, "description": desc}]})
        if "/compare/" in path:
            return ok({"merge_base_commit": {"sha": "mb7"}})
        if "/contents/" in path:
            ref = path.split("ref=")[1]
            return ok({"content": base64.b64encode(json.dumps(LEDGERS.get(ref, {})).encode()).decode()})
    if argv[:3] in (["gh", "pr", "close"], ["gh", "pr", "merge"], ["gh", "pr", "comment"]):
        return 0, "", ""
    if len(argv) > 2 and argv[1].endswith("linear-sync.py"):
        return 0, f"{argv[3]}: In Progress -> Backlog (exit: pr-owner)" if argv[2] == "requeue" else "", ""
    if len(argv) > 2 and argv[2] == "review":
        return 0, "", ""
    if len(argv) > 1 and argv[1] == str(SINK_NOTIFY):
        return REAL_RUN(argv, timeout=60)
    if len(argv) > 1 and argv[1].endswith("slack-notify.sh"):
        return 1, "", "test: refused, only the temp copy of slack-notify.sh may run"
    return 1, "", "unfaked: " + " ".join(argv)


guard = TMP / "guard.sh"
guard.write_text("#!/bin/bash\necho '{}'\n")
po.run = fake_run
po.fleet_repos = lambda root=None: ([("fx", str(TMP / "fx"), "")], "")
po.slug_for = lambda root, path, targets: SLUG
po.archived = lambda path, label: False
po.archive_guard = lambda: guard
po.read_ticket = loader(TICKETS)


def fake_run_logged(argv, log, timeout=2700):
    SENT.append([str(a) for a in argv])
    return 0, ""


po.run_logged = fake_run_logged
(TMP / "fx").mkdir()
(TMP / "worker").mkdir(exist_ok=True)
(TMP / "worker" / "linear-worker-attempts.json").write_text(json.dumps({"ASK-777": {"capout": True, "count": 1}}))


def writes():
    out = []
    for a in SENT:
        if a[:3] in (["gh", "pr", "close"], ["gh", "pr", "merge"], ["gh", "pr", "comment"]):
            out.append(a)
        elif len(a) > 2 and (a[1].endswith("linear-sync.py") or a[1].endswith("slack-notify.sh") or a[2] == "review"):
            out.append(a)
    return out


def sent_for(n, verb):
    return [a for a in writes() if verb in a[:3] and str(n) in a[3:4]]


os.environ["KIPI_PR_OWNER_NOW"] = str(NOW)
SENT.clear()
rc = po.main(["--skip", "fx#8"])
check("dry run exits 0", rc, 0)
check("dry run sends no write", writes(), [])
check("dry run leaves no state file", po.state_path().exists(), False)

SENT.clear()
rc = po.main(["--apply", "--skip", "o/fx#8"])
check("--apply exits 0", rc, 0)
close1 = sent_for(1, "close")
check("#1 (fix/, ticket in Backlog) is closed", len(close1), 1)
check("#1's close keeps the branch", "--delete-branch" in (close1[0] if close1 else []), False)
check("#1's ticket gets a progress note, not a requeue (it is in Backlog)",
      [a[2] for a in writes() if a[1].endswith("linear-sync.py") and a[3] == "ASK-2540"], ["progress"])
check("#2 (worker branch) gets a rework comment, not a close",
      (len(sent_for(2, "comment")), len(sent_for(2, "close"))), (1, 0))
req = [a for a in writes() if a[1].endswith("linear-sync.py") and a[3] == "ASK-3036"]
check("#2's started ticket is requeued with the pr-owner exit and a resume line",
      bool(req) and req[0][2] == "requeue" and req[0][5] == "pr-owner" and req[0][7].startswith("Resume from branch sana/ask-3036 at"),
      True)
merge3 = sent_for(3, "merge")
check("#3 is merged pinned to its head", bool(merge3) and merge3[0][-2:] == ["--match-head-commit", SHA[3]], True)
rev = [a for a in writes() if len(a) > 2 and a[2] == "review"]
check("one review this run, on #4", [a[3] for a in rev], ["4"])
check("#5 waits: the run's one review is spent", sent_for(5, "close") + sent_for(5, "comment"), [])
check("#6 (pushed an hour ago) gets nothing", sent_for(6, "close") + sent_for(6, "comment"), [])
check("#7 (lessons batch on main) is closed as superseded", len(sent_for(7, "close")), 1)
check("#8 (--skip) gets nothing", [a for a in writes() if "8" in a[3:4] or "ASK-142" in a], [])
check("#9 (a fork on sana/ask-3036) gets no close, comment, merge, review or Linear write; the only read is its commits",
      [a for a in SENT if ("9" in a[3:4] or any(SHA[9] in x for x in a)) and a[:3] != ["gh", "pr", "view"]], [])
check("... and that read asks for commits only", [a[-1] for a in SENT if a[:4] == ["gh", "pr", "view", "9"]], ["commits"])
st = json.loads(po.state_path().read_text())
issues = linear_db()["issues"]
import re as _re
names = lambda i: _re.findall(r"PR #(\d+) \(", i["description"])
check("each old fork gets its own Linear ticket from the real sink, naming it (round 3 major)",
      sorted(names(i)[0] for i in issues if names(i)), ["11", "9"])
by_pr = {names(i)[0]: i["identifier"] for i in issues if names(i)}
check("pr-owner records the ticket the sink named, per PR",
      {k: (st.get("outside") or {}).get(f"o/fx#{k}", {}).get("ticket") for k in ("9", "11")},
      {"9": by_pr.get("9", "none"), "11": by_pr.get("11", "none")})
check("#12, a fork opened an hour ago, gets no alert and no record (round 3 minor)",
      ("o/fx#12" in (st.get("outside") or {}), [i for i in issues if "PR #12 (" in i["description"]]), (False, []))
check("#14, an old fork pushed an hour ago, gets no alert (the quiet gate reads its commits)",
      ("o/fx#14" in (st.get("outside") or {}), [i for i in issues if "PR #14 (" in i["description"]]), (False, []))
check("#10 (cap-ladder owns ASK-777) gets no write at all",
      [a for a in writes() if "10" in a[3:4] or "ASK-777" in a], [])
check("the strike on #2 is recorded at its head", st["strikes"]["o/fx#2"]["head"], SHA[2])
check("the review on #4 is recorded at its head", st["reviews"]["o/fx#4"]["head"], SHA[4])

SENT.clear()
PRS[:] = [p for p in PRS if p["number"] in (2, 4, 9, 11)]
os.environ["KIPI_PR_OWNER_NOW"] = str(NOW + 49 * H)
po.main(["--apply"])
check("49h later, #2 still red at the same head is closed", len(sent_for(2, "close")), 1)
check("49h later, neither fork's alert is filed a second time",
      ([a for a in writes() if a[1].endswith("slack-notify.sh")], len(linear_db()["issues"]), linear_db()["comments"]),
      ([], 2, []))
check("... and its ticket gets the resume note", any(a[3] == "ASK-3036" for a in writes() if a[1].endswith("linear-sync.py")), True)
check("49h later, #4 reviewed at this head with no verdict is closed, not reviewed again",
      (len(sent_for(4, "close")), len([a for a in writes() if len(a) > 2 and a[2] == "review"])), (1, 0))

print("-- a failed requeue and a refusal are loud (PR #659 round 4, minors)")
# linear-sync.py's own failure shape: "BLOCK: ..." on stderr and its EXIT_USAGE.
LS_FAIL = po.linear_sync().EXIT_USAGE


def requeue_fails(argv, timeout=120, env=None, cwd=None):
    argv = [str(a) for a in argv]
    if len(argv) > 2 and argv[1].endswith("linear-sync.py") and argv[2] == "requeue":
        SENT.append(argv)
        return LS_FAIL, "", "BLOCK: HTTP 500 from Linear"
    return fake_run(argv, timeout, env, cwd)


po.run = requeue_fails
rq_state: dict = {}
rq_pr = pr(slug="o/fx", number=2, branch="sana/ask-3036", head=SHA[2])
got = try_call(po.act, rq_pr, {"action": "rework", "ticket": TICKETS["ASK-3036"], "reason": "CI red"}, rq_state, NOW)
check("rework whose requeue fails -> not ok, and the failure is named",
      (got[0], "requeue failed" in got[1]) if isinstance(got, tuple) else got, (False, True))
got = try_call(po.act, rq_pr, {"action": "close-requeue", "ticket": TICKETS["ASK-3036"], "reason": "CI red"}, rq_state, NOW)
check("close-requeue whose requeue fails -> not ok, and the failure is named",
      (got[0], "requeue failed" in got[1]) if isinstance(got, tuple) else got, (False, True))
po.run = fake_run
import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    try:
        rc_help = po.main(["-h"])
    except SystemExit as exc:
        rc_help = f"SystemExit({exc.code!r})"
check("-h exits 0, not the usage-error 64 (round 5 nit)", rc_help, 0)
keep = (PRS[:], po.read_ticket)
PRS[:] = [raw(1, "fix/thing-ask-2540")]
po.read_ticket = loader({"ASK-2540": RuntimeError("HTTP 503 from Linear")})
with contextlib.redirect_stdout(io.StringIO()) as buf:
    rc_down = po.main([])
PRS[:], po.read_ticket = keep
check("Linear down, every red PR held -> exit 2, not a healthy 0 (round 5 minor)",
      (rc_down, "hold o/fx#1" in buf.getvalue()), (2, True))
po.state_path().write_text("{not json")
try:
    rc_refused = po.main(["--apply"])
except SystemExit as exc:
    rc_refused = f"SystemExit({exc.code!r})"
check("an unreadable state file refuses with exit 3, as the docstring says", rc_refused, 3)
po.state_path().unlink()

print("-- the sink's exit 0 is not a record; the ticket it names is")
real_sink = importlib.util.spec_from_file_location("alert_sink_real", SCRIPTS / "alert-to-linear.py")
a2l = importlib.util.module_from_spec(real_sink)
real_sink.loader.exec_module(a2l)
three = [pr(slug=sl, number=n, url=f"https://github.com/{sl}/pull/{n}", provenance="fork")
         for sl, n in (("assafkip/kipi-system", 526), ("assafkip/brag", 2), ("assafkip/openwitness", 41),
                       ("assafkip/kipi-system", 2))]
fps = [try_call(lambda x: a2l.fingerprint(po.outside_alert(x, "head provenance is fork")), x) for x in three]
check("four fork PRs, two sharing #2 in different repos -> four fingerprints in the real normalizer",
      len(set(fps)), 4)
check("one PR said twice -> one fingerprint (a retry repeats on its own ticket)",
      try_call(lambda: a2l.fingerprint(po.outside_alert(three[1], "head provenance is fork"))), fps[1])
cap_file = TMP / "capture.txt"
os.environ["KIPI_ALERT_CAPTURE"] = str(cap_file)
lone = pr(slug="o/fx", number=13, url="https://github.com/o/fx/pull/13", provenance="fork", head="13" * 20)
lone_state: dict = {}
got = try_call(po.act, lone, {"action": "outside", "reason": "head provenance is fork"}, lone_state, NOW)
os.environ.pop("KIPI_ALERT_CAPTURE", None)
check("a sink exit 0 that names no ticket (the real capture hatch) -> not ok", (got[0] if isinstance(got, tuple) else got), False)
check("... and not recorded, so the next hourly run retries", "o/fx#13" in (lone_state.get("outside") or {}), False)
check("... and the real sink did take the message", "PR #13 (" in (cap_file.read_text() if cap_file.is_file() else ""), True)

# ---------------------------------------------------------------- the repo set
print("-- the repo set is the dispatcher's fleet_candidates")
spec2 = importlib.util.spec_from_file_location("pr_owner_real", SUBJECT)
real = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(real)
fx = TMP / "home"
fx.mkdir()
shutil.copy(REPO / "kipi-dispatch.sh", fx / "kipi-dispatch.sh")
reg, overlay = TMP / "registry.json", TMP / "overlay.json"
reg.write_text(json.dumps({"instances": [
    {"name": "on", "path": "/fx/on", "dispatch": {"enabled": True, "expected_remote": "https://github.com/o/on.git"}},
    {"name": "off", "path": "/fx/off", "dispatch": {"enabled": False}},
    {"name": "strtrue", "path": "/fx/strtrue", "dispatch": {"enabled": "true"}},
    {"name": "nokey", "path": "/fx/nokey"}]}))
overlay.write_text(json.dumps({"instances": [
    {"name": "client", "path": "/fx/client", "dispatch": {"enabled": True}},
    {"name": "off", "path": "/fx/off", "dispatch": {"enabled": True}}]}))
os.environ["KIPI_DISPATCH_REGISTRY"], os.environ["KIPI_DISPATCH_TARGETS"] = str(reg), str(overlay)
rows, targets = real.fleet_repos(fx)
check("home, the opted-in row and the overlay row; a recorded OFF stays off",
      [r[0] for r in rows], ["home", "on", "client"])
check("the overlay path reaches the slug reader", targets, str(overlay))
(fx / "kipi-dispatch.sh").write_text("#!/bin/bash\nREPO=x\n")
try:
    real.fleet_repos(fx)
    check("a dispatcher with no fleet_candidates refuses the run", "ran", "refused")
except SystemExit:
    check("a dispatcher with no fleet_candidates refuses the run", "refused", "refused")
for k in ("KIPI_DISPATCH_REGISTRY", "KIPI_DISPATCH_TARGETS"):
    os.environ.pop(k, None)

# ---------------------------------------------------------------- wiring
print("-- wiring")
table = json.loads((REPO / "q-system/.q-system/terminal-states.json").read_text())
exits = table["ticket_states"]["rows"]["open-pr"]["exits"]
mine = [e for e in exits if e.get("path") == "q-system/.q-system/scripts/pr-owner.py"]
check("open-pr has a by-age consumer row for pr-owner.py",
      [(e.get("kind"), e.get("fires"), e.get("marker")) for e in mine], [("consumer", "by-age", "def decide(")])
check("that row names this test", [e.get("test") for e in mine], ["q-system/.q-system/scripts/test/test-pr-owner.py"])
check("the ASK-3962 debt is gone", [e for e in exits if e.get("ticket") == "ASK-3962"], [])
plist_path = SCRIPTS / "com.kipi.pr-owner.plist"
pl = plistlib.loads(plist_path.read_bytes()) if plist_path.is_file() else {}
check("the plist's label", pl.get("Label"), "com.kipi.pr-owner")
check("it runs pr-owner.py --apply", any("pr-owner.py --apply" in a for a in pl.get("ProgramArguments") or []), True)
check("hourly", pl.get("StartInterval"), 3600)
jobs = json.loads((REPO / "q-system/.q-system/job-checkouts.json").read_text())
check("it runs from its own pinned checkout", "com.kipi.pr-owner" in jobs.get("pinned", []), True)
frag = REPO / "q-system/.q-system/capability/expected_tests/q-system__.q-system__scripts__test__test-pr-owner.py.json"
check("CI runs this test", json.loads(frag.read_text()).get("path") if frag.is_file() else None,
      "q-system/.q-system/scripts/test/test-pr-owner.py")

shutil.rmtree(TMP, ignore_errors=True)
print()
if FAILS:
    print(f"FAIL: {len(FAILS)} check(s): " + "; ".join(FAILS))
    sys.exit(1)
print("PASS")
