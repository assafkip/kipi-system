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
check("provenance comes from ci-redrive's head_provenance",
      [po.normalize("o/r", "r", "/p", {"number": 1, "isCrossRepository": v})["provenance"] for v in (False, True, None)],
      ["same-repo", "fork", "unstated"])

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

# ---------------------------------------------------------------- apply and dry, end to end
print("-- --apply and the dry run, end to end on a faked fleet")
SLUG = "o/fx"
SHA = {n: f"{n:02d}" + "ab" * 19 for n in range(1, 10)}
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
       raw(8, "sana/ask-142"), raw(9, "sana/ask-3036", title="fork (ASK-2540)", isCrossRepository=True)]
PUSHED = {n: (FRESH if n == 6 else OLD) for n in SHA}
REVIEWER = {1: ("failure", "delta x..y: REQUEST CHANGES"), 2: ("failure", "unstated: no verdict parsed from the review"),
            3: ("success", "APPROVE"), 4: ("failure", FLOOR), 5: ("failure", FLOOR), 6: ("failure", FLOOR),
            7: ("failure", FLOOR), 8: ("failure", "delta x..y: REQUEST CHANGES"),
            9: ("failure", "delta x..y: REQUEST CHANGES")}
LEDGERS = {SHA[7]: {"k1": {"status": "published"}, "k2": {"status": "published"}}, "mb7": {}, "main": {"k1": {}, "k2": {}, "k0": {}}}
TICKETS = {"ASK-2540": ticket("ASK-2540", "backlog"), "ASK-3036": ticket("ASK-3036", "started", started_h=400),
           "ASK-142": ticket("ASK-142", "started", started_h=200)}
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
    if len(argv) > 1 and argv[1].endswith("slack-notify.sh"):
        return 0, "", ""
    return 1, "", "unfaked: " + " ".join(argv)


guard = TMP / "guard.sh"
guard.write_text("#!/bin/bash\necho '{}'\n")
po.run = fake_run
po.fleet_repos = lambda root=None: ([("fx", str(TMP / "fx"), "")], "")
po.slug_for = lambda root, path, targets: SLUG
po.archived = lambda path, label: False
po.archive_guard = lambda: guard
po.read_ticket = loader(TICKETS)
(TMP / "fx").mkdir()


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
check("#9 (a fork on sana/ask-3036) gets no close, comment, merge, review or Linear write, and no read of its head",
      [a for a in SENT if "9" in a[3:4] or any(SHA[9] in x for x in a)], [])
pages = [a for a in writes() if a[1].endswith("slack-notify.sh")]
check("#9 gets exactly one alert, naming it, for the alert lane",
      [("PR #9" in a[2], "outside the fleet" in a[2]) for a in pages], [(True, True)])
check("the alert is recorded", "o/fx#9" in json.loads(po.state_path().read_text()).get("outside", {}), True)
st = json.loads(po.state_path().read_text())
check("the strike on #2 is recorded at its head", st["strikes"]["o/fx#2"]["head"], SHA[2])
check("the review on #4 is recorded at its head", st["reviews"]["o/fx#4"]["head"], SHA[4])

SENT.clear()
PRS[:] = [p for p in PRS if p["number"] in (2, 4, 9)]
os.environ["KIPI_PR_OWNER_NOW"] = str(NOW + 49 * H)
po.main(["--apply"])
check("49h later, #2 still red at the same head is closed", len(sent_for(2, "close")), 1)
check("49h later, #9's alert is not filed a second time", [a for a in writes() if a[1].endswith("slack-notify.sh")], [])
check("... and its ticket gets the resume note", any(a[3] == "ASK-3036" for a in writes() if a[1].endswith("linear-sync.py")), True)
check("49h later, #4 reviewed at this head with no verdict is closed, not reviewed again",
      (len(sent_for(4, "close")), len([a for a in writes() if len(a) > 2 and a[2] == "review"])), (1, 0))

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
