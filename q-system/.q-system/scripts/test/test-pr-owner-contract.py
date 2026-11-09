#!/usr/bin/env python3
"""test-pr-owner-contract.py -- every promise pr-owner.py makes, one assertion each (ASK-3962).

WHY THIS FILE. Rounds 4 to 6 of PR #659 each found a sentence pr-owner.py says that
its code did not do. "Reopen this PR to undo" was false from the first commit: the
state it needed was written and never read. The tests followed the code paths each
finding named, so a promise no finding named had no test. This file follows the
WORDS: PROMISES lists every claim in pr-owner.py's docstrings, comments, posted PR
comments, ticket notes and log lines, and each claim has assertions that run the
real decide(), act() and main() on a faked fleet. RCA:
q-system/output/rca/rca-pr-owner-three-rounds-2026-11-08.md, "Rounds 4 to 6".

THE COVERAGE RULE, so a new claim cannot ship untested. Every line of pr-owner.py
that reads like a promise (never, only, at most, once, always, undo, refuse,
nothing else, exit N) must contain the anchor of a PROMISES row, or of an EXEMPT row
that says why it is not one. Every anchor must still be in the file, and every row
must run at least one assertion.

WHAT IS REAL: decide(), act(), main(); read_ticket() with linear-sync.py's
live_claim() and STARTED_STALE_HOURS; ci-redrive.py's provenance and slot rules;
pr-verdict-lib.sh rework_gate; the archive hook's allow path (a copy of the
founder's ps-archive-deny.sh when this machine has it); slack-notify.sh and
alert-to-linear.py main() with only the Linear transport faked; cap-ladder.py
ladder_owns() when PR #662 is reachable; the dispatcher's fleet_candidates();
install-plist.sh's render.
WHAT IS FAKE: every gh call, linear-sync.py's GraphQL transport and its requeue and
progress commands, the reviewer run (except one stub run through the real
run_logged()), and the archive hook's DENY path. The archived engagement's folder
name may not appear in any file a tool writes (ps-archive-deny.sh refuses that
write, on purpose), so scenario D denies a fixture marker with the hook's own deny
output shape instead.

NEVER LIVE DATA. The state file, the worker state dir and HOME (the archive hook and
the plist render read it) are under a temp dir, asserted before anything runs, and
urlopen is blocked in this process and in the sink.

Run: python3 q-system/.q-system/scripts/test/test-pr-owner-contract.py   (exit 0 = pass)
"""

from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
REPO = SCRIPTS.parents[2]
SUBJECT = Path(os.environ.get("KIPI_PR_OWNER_PATH") or SCRIPTS / "pr-owner.py")
VERBOSE = os.environ.get("PR_OWNER_CONTRACT_VERBOSE") == "1"

print("test-pr-owner-contract.py")
if not SUBJECT.is_file():
    print(f"RED: no {SUBJECT}")
    sys.exit(1)
SRC = SUBJECT.read_text()

# ================================================================ the promises

PROMISES: dict = {}
FAILS: list = []


def promise(pid, says, *anchors):
    PROMISES[pid] = {"says": says, "anchors": anchors, "ran": 0}


def holds(pid, name, got, want):
    PROMISES[pid]["ran"] += 1  # an unknown id is a KeyError: a test bug, loud
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} [{pid}] {name}" + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(f"[{pid}] {name}")


promise("P01", "dry by default: it prints and writes nothing, not even its state file; --apply acts",
        "writes nothing, not even its state", "--apply acts")
promise("P02", "hourly, from its own pinned checkout; the job never sets the clock",
        "Hourly as com.kipi.pr-owner", "the job never does")
promise("P03", "a .kipi-no-dispatch file skips the repo", "`.kipi-no-dispatch` file skips it", "(kill switch)")
promise("P04", "the archive guard is asked before anything reads the repo",
        "before anything reads the repo", "the archive guard refuses it")
promise("P05", "a missing archive hook refuses the run", "A missing hook refuses the", "REFUSED: the archive guard")
promise("P06", "a guard that cannot answer is never read as an allow",
        "A GUARD THAT CANNOT ANSWER IS NOT AN ALLOW", "so any other exit is no answer",
        "read and closed PRs in what may be the archive", "Now every non-answer raises")
promise("P07", "a PR younger than 48h belongs to whatever opened it",
        "A PR younger than 48 hours belongs to")
promise("P08", "12h of quiet gates every write", "So it gates every write")
promise("P09", "a lessons PR is superseded by its content, not its branch name", "Decided by content")
promise("P10", "a merge is the fleet's one shape, gh pr merge --auto --squash <n>, from the repo's own checkout",
        "`gh pr merge --auto --squash <n>`, run from the")
promise("P11", "UNSTABLE merges only when our CI read is green",
        "UNSTABLE is allowed ONLY because", "whose only non-green status was the advisory")
promise("P12", "at most one review per run, and one per head per 48h; a review that crashed or never landed is asked "
        "again after 48h, never closed for it; the reviewer's exit 9 is asked again next run",
        "`kipi review <n> --repo <path> --post`, at most one", "per run, at most one per head per 48 hours",
        "this run's one review is spent", "a review that crashes must not be", "EXIT 9 IS THE MACHINE, NOT THE PR",
        "and no verdict landed; asked again")
promise("P13", "a rework leaves the PR open once; still red at that head 48h after its ticket note landed, it closes",
        "open once. Still red at the same head one age", "It stays open once",
        "THE 48 HOURS START WHEN THE NOTE LANDS", "so the note is asked again", "only the note is asked again")
promise("P14", "the rework comment says the ticket goes back to Backlog only when it is requeued",
        "so the worker reworks it on", "THE COMMENT SAYS WHAT ticket_note() DOES")
promise("P15", "an open ticket on another branch: close, then a resume note",
        "open ticket on any other branch: close, then the same resume note")
promise("P16", "no ticket, or a closed one: close with a comment", "no ticket, or a closed one: close with a comment")
promise("P17", "checks running, or mergeability not computed: wait",
        "checks still running, or GitHub has not computed mergeability: wait")
promise("P18", "no write ever deletes a branch", "A close never deletes the branch", "the only copy of the work",
        "pr-owner never deletes a branch", "Nothing was deleted")
promise("P19", "a reopen is the undo: no write of any kind until a new push",
        "Reopening the PR undoes it", "A REOPEN IS THE UNDO", "was written and never read",
        "a reopen is the undo, so pr-owner leaves it until a new push", "reopen the PR within 30 days to undo",
        "reopen the PR within {KEEP_DAYS} days to undo")
promise("P20", "a fork is never acted on: no Linear read, no ladder read, no comment, no close",
        "A FORK IS NEVER ACTED ON", "pr-owner never acts on it")
promise("P21", "a fork waits behind the 48h age and the 12h quiet", "It waits behind the same 48h age and 12h quiet")
promise("P22", "one alert per fork PR, each on its own ticket, never a second", "and never a second", "(once per PR)")
promise("P23", "an alert is recorded only when the sink's line names a ticket",
        "The alert is recorded only when the sink's own line names a ticket", "for why exit 0 is not that proof",
        "EXIT 0 IS NOT A RECORD", "Only the first two name a ticket")
promise("P24", "only the alert's own first sink line is read", "is never read as this one")
promise("P25", "the dedup ref is letters only, distinct per PR, the same every run", "letters only, never hex")
promise("P26", "a PR cap-ladder.py owns gets no write and no Linear read",
        "gets `ladder`, nothing else", "cap-ladder.py takes it, pr-owner writes nothing")
promise("P27", "once cap-ladder.py is in the tree, ladder_owns() answers and the fallback is unused",
        "Once cap-ladder.py is in the pinned tree this path is")
promise("P28", "a cap-ladder.py that cannot answer holds the PR", '"could not ask" is not "the ladder does not own it"')
promise("P29", "a live lane is never closed or reworked", "A LIVE LANE IS NEVER CLOSED")
promise("P30", "one writer: the state file is written under a lock, as a temp file plus rename",
        "is written only here, under a lock", "another pr-owner run holds the lock")
promise("P31", "Linear writes go through linear-sync.py requeue and progress, and the fork alert's sink",
        "Linear writes go through linear-sync.py requeue and progress")
promise("P32", "exit 0 clean, 2 a repo unread or an action failed, 3 refused, 64 usage",
        "Exit: 0 clean, 2 a repo could not be read", "EXIT 3 FOR EVERY REFUSAL", 'refuse with SystemExit("REFUSED: ...")',
        "REFUSED: no FLOOR_DESC", "REFUSED: fleet_candidates returned no repo", "not running on a blank memory",
        "REFUSED: the dispatch set could not be read", "no kipi-dispatch.sh at", "kipi-dispatch.sh has no $fn()",
        "every red PR holds, and exit 0 told", "Same exit 2 as a GitHub read that failed")
promise("P33", "the floor description comes from reviewer-floor.sh, so never-reviewed is not rejected",
        'alone cannot tell "never reviewed"', "description is the only difference",
        "would close never-reviewed PRs as rejected")
promise("P34", "commits and files are read per aged PR, never in the list",
        "Read per aged PR, never in the list", "traverses the authors connection")
promise("P35", "a pending kipi/reviewer-approved means the round cap", "posts pending for one thing only: its round cap")
promise("P36", "a lane branch is never reworked: the worker commits only onto sana/<id>",
        "the worker commits only onto sana/<id>")
promise("P37", "a rework_gate that cannot answer holds the PR", "|| exit 99")
promise("P38", "approved and green but BLOCKED waits, never reworked or closed for it",
        "so it is never reworked or closed for it")
promise("P39", "review findings are read only, and land in the close comment", "Read only. The worker's review record")
promise("P40", "a failed requeue still posts the resume note and exits 2",
        "so the resume line lands, and the run counts a failure and exits 2")
promise("P41", "an aged fork's commits are its only per-PR read", "A fork's commits and nothing else")
promise("P42", "the review runs to a file, never a pipe", "A FILE, NEVER A PIPE")
promise("P43", "only ASK-n names a ticket", "The board's only team")
promise("P44", "kipi-dispatch.sh is read, never edited", "this reads those files and never edits them")
promise("P45", "--skip leaves one PR alone for this run only", "leave one PR alone this run")
promise("P46", "client repos are in: the dispatcher's overlay rows are owned", "Client repos are in")
# ASK-4099: the three round-7 minors of PR #659 and the two follow-ups the round-7 contract test found.
promise("P47", "a ticket linear-worker.sh does not pick (Triage) gets no rework round and no 'worker reworks it'",
        "A REWORK IS PROMISED ONLY TO A TICKET THE WORKER PICKS", "which linear-worker.sh does not pick",
        "no QUEUE_STATES in linear-worker.sh")
promise("P48", "the state file stays bounded: a PR gone from a fully listed repo for 30 days loses its entries",
        "THE STATE FILE STAYS BOUNDED", "never pruned", "Reopen this PR within 30 days to undo")
promise("P49", "no check reported is not CI green: no workflow merges on the review and says so, workflows is red, unread holds",
        "NO CHECK IS NOT GREEN", "logged as that and never as CI green", "could not tell whether")
promise("P50", "an approved, green, conflict-free PR that is only BEHIND is updated, never closed for it: a call that "
        "fails, or that GitHub accepts and the head does not move, is held, asked again next run, and exits 2",
        "BEHIND IS UPDATED, NOT CLOSED", "update-branch was asked at", "A FAILED CALL IS NOT A FAILED REBASE",
        "so the PR holds and the run exits 2, as every red PR does", "and the head did not move",
        "update-branch failed {fails} time(s) at this head", "until GitHub moves the head")
promise("P52", "a write of pr-owner's own that fails or does not take never closes the PR: the run exits 2, and one "
        "alert per PR, head and failed write goes through the sink, recorded only when the sink names a ticket",
        "THE RED TABLE READS THE PR, NEVER OUR OWN WRITES", "never pr-owner's record of its own writes",
        "never closes a PR because its own write failed",
        "one alert per PR, head and failed write", "HELD IS NOT RED", "the run exits 2, and main() files the PR's one alert",
        "it is recorded only when the sink's line names a ticket", "ONE ALERT PER FAILED WRITE")
promise("P53", "a rework's requeue and its note are two results: the 48h start once the note lands, and a requeue "
        "that failed while its note landed is surfaced once by the alert and never asked again",
        "TWO WRITES, TWO RESULTS", "each ask would post the note again")
promise("P54", "the note after a close is never asked again, since a closed PR leaves the open list; its alert names "
        "the ticket, carries the resume line, and names the write that did not take",
        "a closed PR leaves the open list", "carries the resume line")
promise("P51", "the merge is asked of merge-bypass-gate.py first, re-read as the same PR at the same head, and read back",
        "ASKED OF THE GATE, NOT HIDDEN FROM IT", "a deny or no answer is no merge", "neither merged nor armed",
        "merge-bypass-gate.py refused it",
        "GH_REPO and GH_HOST never reach")

EXEMPT = [
    ("select `sana` branches only", "history: what the 2026-11-08 audit found in other scripts"),
    ("counts only `sana/` heads", "history: the audit"),
    ("human-shaped PR was never selected", "history: the audit"),
    ("wip_release moves a PR only when", "history: the audit"),
    ("in front of closes only", "history: the first design, replaced by 'it gates every write' (P08)"),
]

# ================================================================ never live data

TMP = Path(tempfile.mkdtemp(prefix="pr-owner-contract-"))
REAL_HOME = Path(os.environ.get("HOME") or str(Path.home()))
FAKE_HOME = TMP / "home"
FAKE_HOME.mkdir()
os.environ.update({"KIPI_PR_OWNER_STATE": str(TMP / "state" / "state.json"), "KIPI_STATE_DIR": str(TMP / "worker"),
                   "HOME": str(FAKE_HOME), "KIPI_TEST": "1", "KIPI_INSTANCE_NAME": "kipi-system"})
for k in ("KIPI_PR_OWNER_NOW", "KIPI_DISPATCH_REGISTRY", "KIPI_DISPATCH_TARGETS", "KIPI_NOTIFY", "KIPI_ALERT_CAPTURE",
          "KIPI_LINEAR_API_URL", "KIPI_LINEAR_API_KEY", "KIPI_LINEAR_QUEUE", "PYTEST_CURRENT_TEST", "ALLOW_PS_ARCHIVE",
          "KIPI_REPO"):
    os.environ.pop(k, None)


def _no_network(*a, **k):
    raise RuntimeError("test: network blocked")


urllib.request.urlopen = _no_network

spec = importlib.util.spec_from_file_location("pr_owner_contract", SUBJECT)
po = importlib.util.module_from_spec(spec)
spec.loader.exec_module(po)

REAL_RUN, REAL_RUN_LOGGED, REAL_FLEET_REPOS = po.run, po.run_logged, po.fleet_repos
BLOCKED: list = []


def blocked_run(argv, timeout=120, env=None, cwd=None):
    BLOCKED.append([str(a) for a in argv])
    return 1, "", "test: real subprocess blocked"


po.run = blocked_run  # nothing reaches a real gh before the fake is in

live = [str(p) for p in (po.state_path(), po.worker_state_dir(), Path.home(), po.archive_guard())
        if not str(p).startswith(str(TMP))]
if live:
    print(f"REFUSED: these paths are live, not under {TMP}: {live}")
    sys.exit(1)

# ================================================================ the faked fleet

H = 3600
NOW = po.iso_s("2026-11-08T21:00:00Z")
OLD = "2026-10-01T00:00:00Z"
FRESH = po.iso(NOW - H)
FLOOR = po.floor_desc()
LEDGER = po.LEDGER
GREEN = [{"__typename": "CheckRun", "name": "validate", "status": "COMPLETED", "conclusion": "SUCCESS"}]
RED = [{"__typename": "CheckRun", "name": "validate", "status": "COMPLETED", "conclusion": "FAILURE"}]
RUNNING = [{"__typename": "CheckRun", "name": "validate", "status": "IN_PROGRESS", "conclusion": None}]
CODEX_RED = GREEN + [{"__typename": "StatusContext", "context": "kipi/codex-approved", "state": "FAILURE"}]
APPROVE = ("success", "APPROVE")
CHANGES = ("failure", "delta x..y: REQUEST CHANGES")

REPOS: dict = {}
LEDGERS: dict = {}
SENT: list = []
WRITE_RC: dict = {}
LS_RC: dict = {}
REVIEW_RC = [0]
ALLOW_BASH_C = [False]
SLUG_ASKED: list = []
# ASK-4099 knobs. WORKFLOWS: slug -> workflow file names on its base (absent = a 404,
# no CI configured). VIEW_HEAD / VIEW_URL: what the pre-merge re-read from the repo's
# checkout answers instead of the truth. ARMED / NEITHER: what a merge leaves behind.
WORKFLOWS: dict = {}
WORKFLOWS_FAIL: set = set()
VIEW_HEAD: dict = {}
VIEW_URL: dict = {}
ARMED: set = set()
NEITHER: set = set()
MERGED_DONE: set = set()
CWD_ENVS: list = []
WRITE_ENVS: list = []
CWD_MARK = "(cwd "


def repo(slug, name, path=None, **kw):
    p = Path(path) if path else TMP / "repos" / name
    p.mkdir(parents=True, exist_ok=True)
    REPOS[slug] = {"name": name, "path": str(p), "prs": {}, "pushed": {}, "files": {}, "verdict": {},
                   "list_fails": False, **kw}
    return slug


def head_of(slug, n, gen=0):
    return hashlib.sha1(f"{slug}#{n}@{gen}".encode()).hexdigest()


def add(slug, n, branch, title="t", verdict=None, pushed=OLD, files=("x.py",), **kw):
    r = {"number": n, "title": title, "url": f"https://github.com/{slug}/pull/{n}", "headRefName": branch,
         "headRefOid": head_of(slug, n), "baseRefName": "main", "createdAt": OLD, "isDraft": False,
         "isCrossRepository": False, "mergeable": "MERGEABLE", "mergeStateStatus": "BLOCKED",
         "statusCheckRollup": GREEN}
    r.update(kw)
    R = REPOS[slug]
    R["prs"][n], R["pushed"][n], R["files"][n] = r, pushed, list(files)
    R["verdict"][n] = verdict or ("failure", FLOOR)
    if LEDGER in files:
        LEDGERS[(slug, r["headRefOid"])] = {"k1": {"status": "published"}, "k2": {"status": "published"}}
        LEDGERS[(slug, "mergebase")] = {}
        LEDGERS[(slug, "main")] = {"k0": {}, "k1": {}, "k2": {}}
    return r


def slug_in(a):
    """The repo a recorded gh argv acts on: its -R, else the checkout it ran from."""
    if "-R" in a:
        return a[a.index("-R") + 1]
    if a and a[-1].startswith(CWD_MARK):
        path = a[-1][len(CWD_MARK):-1]
        return next((s for s, R in REPOS.items() if R["path"] == path), "?cwd " + path)
    return "?"


def fake_run(argv, timeout=120, env=None, cwd=None):
    argv = [str(a) for a in argv]
    # A call made from a checkout records which one: without -R, the checkout IS the repo.
    SENT.append(argv + ([f"{CWD_MARK}{cwd})"] if cwd is not None else []))
    if cwd is not None:
        CWD_ENVS.append(env)
    if argv[:2] == ["gh", "pr"] and len(argv) > 2 and argv[2] in WRITE_VERBS:
        WRITE_ENVS.append(env)
    ok = lambda obj: (0, json.dumps(obj), "")  # noqa: E731
    slug = slug_in(SENT[-1])
    if argv[:3] == ["gh", "pr", "list"]:
        R = REPOS[argv[argv.index("-R") + 1]]
        return (1, "", "HTTP 502: bad gateway") if R["list_fails"] else ok(list(R["prs"].values()))
    if argv[:3] == ["gh", "pr", "view"]:
        n, R = int(argv[3]), REPOS[slug]
        r = R["prs"][n]
        done = (slug, n) in MERGED_DONE
        full = {"commits": [{"committedDate": R["pushed"][n]}], "files": [{"path": p} for p in R["files"][n]],
                "mergeable": r["mergeable"], "mergeStateStatus": r["mergeStateStatus"],
                "url": VIEW_URL.get((slug, n), r["url"]), "headRefOid": VIEW_HEAD.get((slug, n), r["headRefOid"]),
                "state": "MERGED" if done and (slug, n) not in ARMED | NEITHER else "OPEN",
                "autoMergeRequest": {"enabledAt": FRESH} if done and (slug, n) in ARMED else None}
        return ok({f: full[f] for f in argv[argv.index("--json") + 1].split(",")})
    if argv[:2] == ["gh", "api"]:
        path = argv[2]
        m = re.match(r"repos/(.+)/contents/\.github/workflows\?ref=(.+)$", path)
        if m:
            if m.group(1) in WORKFLOWS_FAIL:
                return 1, "", "HTTP 502: bad gateway"
            if m.group(1) not in WORKFLOWS:
                return 1, "", "gh: Not Found (HTTP 404)"
            return ok([{"name": w, "type": "file"} for w in WORKFLOWS[m.group(1)]])
        m = re.match(r"repos/(.+)/commits/([0-9a-f]+)/status$", path)
        if m:
            R = REPOS[m.group(1)]
            n = next(k for k, v in R["prs"].items() if v["headRefOid"] == m.group(2))
            st, desc = R["verdict"][n]
            return ok({"statuses": [{"context": po.REVIEWER_CONTEXT, "state": st, "description": desc}]})
        if "/compare/" in path:
            return ok({"merge_base_commit": {"sha": "mergebase"}})
        m = re.match(r"repos/(.+)/contents/.+\?ref=(.+)$", path)
        if m:
            led = LEDGERS.get((m.group(1), m.group(2)))
            if led is None:
                return 1, "", "HTTP 404: Not Found"
            return ok({"content": base64.b64encode(json.dumps(led).encode()).decode()})
    if argv[:2] == ["gh", "pr"] and argv[2] in WRITE_VERBS:
        n = int(next(a for a in argv[3:] if a.isdigit()))
        rc, err = WRITE_RC.get((argv[2], slug, n), (0, ""))
        if rc == 0 and argv[2] == "merge":
            MERGED_DONE.add((slug, n))
        return rc, "", err
    if len(argv) > 3 and argv[1].endswith("linear-sync.py"):
        default = (0, f"{argv[3]}: In Progress -> Backlog (exit: pr-owner)" if argv[2] == "requeue" else "", "")
        return LS_RC.get(argv[2], default)
    if len(argv) > 1 and argv[1] == str(SINK_NOTIFY):
        return REAL_RUN(argv, timeout=60)
    if len(argv) > 1 and argv[1].endswith("slack-notify.sh"):
        return 1, "", "test: only the temp copy of slack-notify.sh may run"
    if argv[:2] == ["bash", "-c"] and ALLOW_BASH_C[0]:
        return REAL_RUN(argv, timeout, env, cwd)
    return 1, "", "unfaked: " + " ".join(argv)


def fake_run_logged(argv, log, timeout=2700):
    SENT.append([str(a) for a in argv])
    return REVIEW_RC[0], "" if REVIEW_RC[0] == 0 else "reviewer crashed"


def slug_lookup(root, path, targets):
    SLUG_ASKED.append(path)
    return next((s for s, R in REPOS.items() if R["path"] == path), "")


po.run, po.run_logged, po.slug_for = fake_run, fake_run_logged, slug_lookup
po.fleet_repos = lambda root=None: ([(R["name"], R["path"], "") for R in REPOS.values()], "")


WRITE_VERBS = ("close", "merge", "comment", "update-branch")


def gh_writes(sent, slug=None, n=None, verb=None):
    out = []
    for a in sent:
        if a[:2] == ["gh", "pr"] and len(a) > 3 and a[2] in WRITE_VERBS:
            num = next((x for x in a[3:] if x.isdigit()), "")
            if ((slug is None or slug_in(a) == slug) and (n is None or num == str(n))
                    and (verb is None or a[2] == verb)):
                out.append(a)
    return out


def ls_calls(sent, verb=None, ident=None):
    return [a for a in sent if len(a) > 3 and a[1].endswith("linear-sync.py")
            and (verb is None or a[2] == verb) and (ident is None or a[3] == ident)]


def reviews(sent, n=None):
    return [a for a in sent if len(a) > 3 and a[2] == "review" and (n is None or a[3] == str(n))]


def sink_calls(sent, n=None):
    return [a for a in sent if len(a) > 2 and a[1].endswith("slack-notify.sh") and (n is None or f"PR #{n} (" in a[2])]


def all_writes(sent):
    return gh_writes(sent) + ls_calls(sent) + reviews(sent) + sink_calls(sent)


def writes_for(sent, slug, n, ident=None):
    return gh_writes(sent, slug, n) + reviews(sent, n) + sink_calls(sent, n) + (ls_calls(sent, ident=ident) if ident else [])


def body_of(a):
    for flag in ("--body", "--comment"):
        if flag in a:
            return a[a.index(flag) + 1]
    return ""


OUT: dict = {}


def run_main(tag, argv, now):
    os.environ["KIPI_PR_OWNER_NOW"] = str(now)
    start = len(SENT)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            rc = po.main(argv)
        except SystemExit as exc:
            rc = f"SystemExit({exc.code!r})"
    OUT[tag] = buf.getvalue()
    if VERBOSE:
        print(f"---- {tag}\n{OUT[tag]}")
    return rc, SENT[start:]


def fresh_state(tag):
    os.environ["KIPI_PR_OWNER_STATE"] = str(TMP / f"state-{tag}" / "state.json")
    return po.state_path()


# ---------------------------------------------------------------- Linear: the real reader, a fake transport
ls = po.linear_sync()
TICKETS: dict = {}
GRAPHQL: list = []


def fake_graphql(query, variables=None):
    GRAPHQL.append((query, dict(variables or {})))
    v = TICKETS.get((variables or {}).get("id"))
    if isinstance(v, Exception):
        raise v
    return {"issue": v}


ls.graphql = fake_graphql


def tk(ident, type_, name=None, started_h=None):
    started = po.iso(NOW - int(started_h * H)).replace("Z", ".000Z") if started_h is not None else None
    return {"id": "uuid-" + ident, "identifier": ident, "startedAt": started,
            "state": {"name": name or type_.title(), "type": type_}}


WT = TMP / "worker" / "worktrees"


def claim(ident, pid):
    d = WT / ident.lower()
    d.mkdir(parents=True, exist_ok=True)
    (d / ".linear-claims.json").write_text(json.dumps({"agent": "w1", "session": "s1", "holder_pid": pid}))


_gone = subprocess.Popen(["true"])
_gone.wait()
DEAD_PID = _gone.pid

# ---------------------------------------------------------------- the cap ladder: real when reachable
(TMP / "worker").mkdir(exist_ok=True)
(TMP / "worker" / "linear-worker-attempts.json").write_text(json.dumps({
    "ASK-777": {"capout": True, "capout_at": "2026-11-01T00:00:00Z", "count": 1},
    "ASK-5009": {"capout": True, "capout_at": "2026-11-01T00:00:00Z", "count": 1}}))
LADDER = SCRIPTS / "cap-ladder.py"
LADDER_KIND = "this tree's"
if not LADDER.is_file():
    got = subprocess.run(["git", "-C", str(REPO), "show",
                          "origin/sana/ask-3824-ladder:q-system/.q-system/scripts/cap-ladder.py"],
                         capture_output=True, text=True)
    if got.returncode == 0 and "def ladder_owns(" in got.stdout:
        LADDER, LADDER_KIND = TMP / "ladder" / "cap-ladder.py", "PR #662's branch"
        LADDER.parent.mkdir()
        LADDER.write_text(got.stdout)
    else:
        LADDER, LADDER_KIND = TMP / "no-ladder" / "cap-ladder.py", "absent, so the superset fallback"
po.CAP_LADDER = LADDER
print(f"  note: cap-ladder.py is {LADDER_KIND}")
REAL_LADDER_CHECK = po.ladder_check
LADDER_ASKED: list = []


def recording_ladder_check(pr, state_dir=None):
    LADDER_ASKED.append(f"{pr['slug']}#{pr['number']}")
    return REAL_LADDER_CHECK(pr, state_dir)


po.ladder_check = recording_ladder_check

# ---------------------------------------------------------------- the archive hook under the temp HOME
# The allow path is the real hook when this machine has it. The deny path is a
# stand-in that prints the hook's own deny shape for a fixture marker: the real
# deny is keyed to a folder name no tool may write into a file.
HOOK = FAKE_HOME / ".claude" / "hooks" / "ps-archive-deny.sh"
HOOK.parent.mkdir(parents=True)
ARCHIVED_MARKER = "archived-fixture"
DENY_STAND_IN = ('#!/bin/bash\nINPUT="$(cat)"\ncase "$INPUT" in *' + ARCHIVED_MARKER + "*)\n"
                 "  printf '%s\\n' '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\","
                 "\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"stand-in\"}}' ;;\nesac\nexit 0\n")
_real_hook = REAL_HOME / ".claude" / "hooks" / "ps-archive-deny.sh"
if _real_hook.is_file():
    shutil.copy(_real_hook, HOOK)  # read once; under the temp HOME it logs nothing live
    print("  note: the archive hook's allow path is a copy of the founder's ps-archive-deny.sh")
else:
    HOOK.write_text(DENY_STAND_IN)
    print("  note: no ps-archive-deny.sh on this machine; the stand-in answers both paths")
HOOK_TEXT = HOOK.read_text()

# ---------------------------------------------------------------- the real alert sink, fake transport
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
                   "PR_OWNER_TEST_FAKE_LINEAR": str(FAKE_LINEAR), "PR_OWNER_TEST_ALERT_STATE": str(TMP / "alert-state")})


def sink_issues():
    return json.loads(FAKE_LINEAR.read_text())["issues"]


# ================================================================ scenario A: every shape, dry then --apply
print("-- scenario A: one fleet holding every shape of PR, dry and then --apply")
FX = repo("o/fx", "fx")
add(FX, 1, "fix/thing-ask-2540", verdict=CHANGES)
add(FX, 2, "sana/ask-3036", verdict=("failure", "unstated: no verdict parsed from the review"))
add(FX, 3, "feat/ok", verdict=APPROVE, mergeStateStatus="CLEAN")
add(FX, 4, "feat/a")
add(FX, 5, "feat/b")
add(FX, 7, "feat/ledger-sync", files=(LEDGER,))
add(FX, 8, "lessons/weekly-2026-10-26")
add(FX, 9, "sana/ask-5009", title="looks like ours (ASK-5010)", isCrossRepository=True)
add(FX, 10, "sana/ask-777", verdict=CHANGES, statusCheckRollup=RED)
add(FX, 11, "feat/other-fork", isCrossRepository=True)
add(FX, 12, "feat/new-fork", isCrossRepository=True, createdAt=FRESH)
add(FX, 14, "feat/busy-fork", isCrossRepository=True, pushed=FRESH)
add(FX, 16, "feat/red", statusCheckRollup=RED)
add(FX, 17, "feat/running", statusCheckRollup=RUNNING)
add(FX, 18, "feat/unknown", mergeable="UNKNOWN", mergeStateStatus="UNKNOWN")
add(FX, 19, "feat/approved-blocked", verdict=APPROVE, mergeStateStatus="BLOCKED")
add(FX, 20, "feat/unstable-red", verdict=APPROVE, mergeStateStatus="UNSTABLE", statusCheckRollup=RED)
add(FX, 21, "sana/ask-901-slug", verdict=CHANGES, statusCheckRollup=RED)
add(FX, 22, "sana/ask-4100", verdict=CHANGES, statusCheckRollup=RED)
add(FX, 23, "sana/ask-4101", verdict=CHANGES, statusCheckRollup=RED)
add(FX, 24, "sana/ask-4102", verdict=CHANGES, statusCheckRollup=RED)
add(FX, 25, "sana/ask-4103", verdict=CHANGES, statusCheckRollup=RED)
add(FX, 26, "feat/unstable-codex", verdict=APPROVE, mergeStateStatus="UNSTABLE", statusCheckRollup=CODEX_RED)
QUIET = {31: 3, 32: 7, 33: 16, 34: 2}  # pushed an hour ago -> their aged, quiet twin
add(FX, 31, "feat/ok-busy", verdict=APPROVE, mergeStateStatus="CLEAN", pushed=FRESH)
add(FX, 32, "feat/ledger-busy", files=(LEDGER,), pushed=FRESH)
add(FX, 33, "feat/red-busy", statusCheckRollup=RED, pushed=FRESH)
add(FX, 34, "sana/ask-3037", verdict=CHANGES, statusCheckRollup=RED, pushed=FRESH)
# 44 is the one only the age gate holds: open 30h, so the 12h quiet gate (which
# reads the open time for a PR this young) lets it through. A mutant with no age
# gate lived until 44 was added, because 41 to 43 are also under the quiet gate.
YOUNG = (41, 42, 43, 44)
add(FX, 41, "feat/ok-young", verdict=APPROVE, mergeStateStatus="CLEAN", createdAt=FRESH, pushed=FRESH)
add(FX, 42, "feat/red-young", statusCheckRollup=RED, createdAt=FRESH, pushed=FRESH)
add(FX, 43, "feat/ledger-young", files=(LEDGER,), createdAt=FRESH, pushed=FRESH)
add(FX, 44, "feat/red-30h", statusCheckRollup=RED, createdAt=po.iso(NOW - 30 * H))
add(FX, 45, "feat/red-skip", statusCheckRollup=RED)
TICKETS.update({
    "ASK-2540": tk("ASK-2540", "backlog"), "ASK-3036": tk("ASK-3036", "started", "In Progress", 400),
    "ASK-901": tk("ASK-901", "backlog"), "ASK-4100": tk("ASK-4100", "started", "In Progress", 2),
    "ASK-4101": tk("ASK-4101", "started", "In Progress", 400), "ASK-4102": tk("ASK-4102", "started", "In Progress", 400),
    "ASK-4103": tk("ASK-4103", "unstarted", "Todo"), "ASK-777": tk("ASK-777", "backlog"),
    "ASK-3037": tk("ASK-3037", "started", "In Progress", 400),
    "ASK-5009": tk("ASK-5009", "started", "In Progress", 400), "ASK-5010": tk("ASK-5010", "started", "In Progress", 400)})
claim("ASK-4101", os.getpid())
claim("ASK-4102", DEAD_PID)
REVIEWS_DIR = TMP / "worker" / "pr-reviews"
REVIEWS_DIR.mkdir(parents=True)
(REVIEWS_DIR / "o_fx__pr-16-20261101T000000Z.md").write_text("verdict\nFINDINGS:\nmajor|red for a reason|x.py:1\nEND FINDINGS\n")


def snapshot(d: Path):
    return sorted((str(p.relative_to(d)), p.read_bytes()) for p in d.rglob("*") if p.is_file())


REVIEWS_BEFORE = snapshot(REVIEWS_DIR)

spath = fresh_state("A")
rc, dry = run_main("A-dry", ["--skip", "fx#45"], NOW)
holds("P01", "a dry run exits 0", rc, 0)
holds("P01", "a dry run sends no close, merge, comment, review, alert or Linear write", all_writes(dry), [])
holds("P01", "a dry run leaves no state file, no lock and no review log",
      snapshot(spath.parent) if spath.parent.exists() else [], [])

rc, A = run_main("A", ["--apply", "--skip", "fx#45"], NOW)
holds("P01", "the same fleet under --apply does write (so the dry check can fail)", len(all_writes(A)) > 10, True)
holds("P32", "a clean --apply exits 0", rc, 0)

holds("P10", "#3 is `gh pr merge --auto --squash 3` from fx's own checkout, and nothing more",
      gh_writes(A, FX, 3), [["gh", "pr", "merge", "--auto", "--squash", "3", f"{CWD_MARK}{REPOS[FX]['path']})"]])
holds("P11", "approved and UNSTABLE with our CI read red -> no merge", gh_writes(A, FX, 20, "merge"), [])
holds("P11", "approved and UNSTABLE only from the advisory codex slot -> merged",
      len(gh_writes(A, FX, 26, "merge")), 1)
holds("P12", "one review this run, on the first never-reviewed PR, shaped `kipi review <n> --repo <path> --post`",
      reviews(A), [["bash", str(po.ROOT / "kipi"), "review", "4", "--repo", REPOS[FX]["path"], "--post"]])
holds("P33", "the never-reviewed #4 (floor status) is reviewed, not closed as rejected",
      (len(reviews(A, 4)), gh_writes(A, FX, 4, "close")), (1, []))
holds("P13", "#2 (worker branch, red) gets one rework comment and stays open",
      (len(gh_writes(A, FX, 2, "comment")), gh_writes(A, FX, 2, "close")), (1, []))
for n, ident in ((2, "ASK-3036"), (24, "ASK-4102"), (25, "ASK-4103")):
    c = gh_writes(A, FX, n, "comment")
    requeued = bool(ls_calls(A, "requeue", ident))
    holds("P14", f"#{n}: the comment says 'goes back to Backlog' exactly when {ident} is requeued",
          ("goes back to Backlog" in body_of(c[0]) if c else None), requeued)
note1 = ls_calls(A, ident="ASK-2540")
holds("P15", "#1 (fix/ branch, ticket in Backlog) is closed, and its ticket gets one resume note",
      (len(gh_writes(A, FX, 1, "close")), [a[2] for a in note1],
       bool(note1) and note1[0][4].startswith(f"Resume from branch fix/thing-ask-2540 at {head_of(FX, 1)[:8]}")),
      (1, ["progress"], True))
c16 = gh_writes(A, FX, 16, "close")
holds("P19", "#1's resume note says how long a reopen undoes the close",
      bool(note1) and "reopen the PR within 30 days to undo" in note1[0][4], True)
holds("P16", "#16 (red, no ticket) is closed with a comment that says so",
      [("--comment" in a, "no ticket named in the branch or title" in body_of(a)) for a in c16], [(True, True)])
holds("P39", "#16's close comment carries the last review findings",
      bool(c16) and "Last review findings" in body_of(c16[0]) and "major|red for a reason" in body_of(c16[0]), True)
holds("P39", "the worker's review records are byte for byte as they were", snapshot(REVIEWS_DIR), REVIEWS_BEFORE)
holds("P17", "#17 (checks running) and #18 (mergeability not computed) get no write",
      writes_for(A, FX, 17) + writes_for(A, FX, 18), [])
holds("P38", "#19 (approved, green, BLOCKED) gets no write", writes_for(A, FX, 19), [])
holds("P36", "#21 (a lane branch, its ticket open) is closed, never given a rework comment",
      (len(gh_writes(A, FX, 21, "close")), gh_writes(A, FX, 21, "comment")), (1, []))
holds("P29", "#22 (ticket started 2h ago) and #23 (a live worker claim) get no write",
      writes_for(A, FX, 22, "ASK-4100") + writes_for(A, FX, 23, "ASK-4101"), [])
holds("P29", "#24, the same shape with a dead claim, is reworked (so the check can fail)",
      (len(gh_writes(A, FX, 24, "comment")), len(ls_calls(A, "requeue", "ASK-4102"))), (1, 1))
holds("P07", "a PR open under 48h (1h, and 30h past the quiet gate) gets no write, whatever its shape",
      [w for n in YOUNG for w in writes_for(A, FX, n)], [])
holds("P08", "a PR pushed an hour ago gets no write: merge-ready, superseded, red, worker branch",
      [w for n in QUIET for w in writes_for(A, FX, n, "ASK-3037" if n == 34 else None)], [])
holds("P08", "... while each one's aged, quiet twin did get its write (so the check can fail)",
      [n for n in QUIET.values() if not (gh_writes(A, FX, n) or reviews(A, n))], [])
c7 = gh_writes(A, FX, 7, "close")
holds("P09", "#7 (feat/ branch, its ledger batch all on main) is closed as superseded",
      ["already on main" in body_of(a) for a in c7], [True])
holds("P09", "#8 (a lessons/ name, no ledger change) is not closed", gh_writes(A, FX, 8, "close"), [])
holds("P45", "#45, named by --skip, gets no write", writes_for(A, FX, 45), [])
holds("P20", "fork #9 on sana/ask-5009 titled ASK-5010: no gh write, no review", gh_writes(A, FX, 9) + reviews(A, 9), [])
holds("P20", "... Linear is never asked about either ticket it names",
      [v.get("id") for _q, v in GRAPHQL if v.get("id") in ("ASK-5009", "ASK-5010")], [])
holds("P20", "... and the cap ladder is never asked about a fork",
      [k for k in LADDER_ASKED if k in ("o/fx#9", "o/fx#11", "o/fx#12", "o/fx#14")], [])
holds("P41", "aged fork #11's only per-PR read is its commits",
      ([a[-1] for a in A if a[:4] == ["gh", "pr", "view", "11"]],
       [a for a in A if a[:2] == ["gh", "api"] and head_of(FX, 11) in a[2]]), (["commits"], []))
by_pr = {re.findall(r"PR #(\d+) \(", i["description"])[0]: i["identifier"] for i in sink_issues()
         if re.findall(r"PR #(\d+) \(", i["description"])}
st = json.loads(spath.read_text())
holds("P22", "forks #9 and #11 each get their own ticket from the real sink, naming that PR",
      sorted(by_pr), ["11", "9"])
holds("P23", "pr-owner records, per fork, the ticket the sink named",
      {k: (st.get("outside") or {}).get(f"{FX}#{k}", {}).get("ticket") for k in ("9", "11")},
      {"9": by_pr.get("9"), "11": by_pr.get("11")})
holds("P21", "fork #12 (opened an hour ago) and fork #14 (pushed an hour ago) get no alert and no record",
      (sink_calls(A, 12) + sink_calls(A, 14), sorted(k for k in (st.get("outside") or {}) if k.endswith(("#12", "#14")))),
      ([], []))
holds("P26", "#10, owned by the cap ladder (ASK-777 capout), gets no write", writes_for(A, FX, 10, "ASK-777"), [])
holds("P31", "every Linear call pr-owner makes itself is a read", [q[:40] for q, _v in GRAPHQL if "mutation" in q], [])
holds("P31", "its Linear writes are linear-sync.py requeue and progress only",
      sorted({a[2] for a in ls_calls(A)}), ["progress", "requeue"])
lst = [a for a in A if a[:3] == ["gh", "pr", "list"]]
holds("P34", "the list asks for no commits and no files",
      [f for a in lst for f in a[a.index("--json") + 1].split(",") if f in ("commits", "files")], [])

# ================================================================ scenario B: time passes
print("-- scenario B: the same fleet 1h, 2h, 49h and 200h later")
for n in (3, 26, 20, 21):  # merged or closed, and not reopened
    del REPOS[FX]["prs"][n]
REOPENED = {1: "ASK-2540", 7: None, 16: None}  # closed by pr-owner in A, reopened at the same head
REVIEW_RC[0] = 1
rc, B1 = run_main("B1", ["--apply"], NOW + H)
REVIEW_RC[0] = 0
holds("P12", "an hour later the run's one review goes to #5, and the reviewer crashes", [a[3] for a in reviews(B1)], ["5"])
holds("P32", "a crashed review is a failed action: exit 2", rc, 2)
holds("P45", "#45, not skipped this run, is closed (--skip was for one run)", len(gh_writes(B1, FX, 45, "close")), 1)
rc, B2 = run_main("B2", ["--apply"], NOW + 2 * H)
holds("P12", "the next run does not ask the crashed review again; its one review goes to #8",
      [a[3] for a in reviews(B2)], ["8"])
holds("P13", "#2 is not commented on again while its strike is under 48h",
      gh_writes(B1, FX, 2) + gh_writes(B2, FX, 2), [])
rc, B49 = run_main("B49", ["--apply"], NOW + 49 * H)
c2 = gh_writes(B49, FX, 2, "close")
holds("P13", "49h after the rework, still red at the same head, #2 is closed", len(c2), 1)
# PR #693 round 4: #4's review in A exited 0 and no verdict ever landed. That is a
# write of ours that did not take, not a verdict on #4, so it is asked again.
holds("P12", "49h after #4's review, with no verdict landed: #4 is reviewed again, never closed for it, exit 2",
      ([a[3] for a in reviews(B49)], gh_writes(B49, FX, 4, "close"), rc), (["4"], [], 2))
holds("P19", "the close comment says the branch is kept and how to undo",
      bool(c2) and f"Branch sana/ask-3036 is kept at {head_of(FX, 2)[:8]}" in body_of(c2[0])
      and "Reopen this PR within 30 days to undo" in body_of(c2[0]), True)
holds("P22", "no fork alert is filed a second time", sink_calls(B1, 9) + sink_calls(B1, 11) + sink_calls(B2, 9)
      + sink_calls(B2, 11) + sink_calls(B49, 9) + sink_calls(B49, 11), [])
rc, B200 = run_main("B200", ["--apply"], NOW + 200 * H)
for n, ident in REOPENED.items():
    holds("P19", f"#{n}, reopened at the head pr-owner closed it at, gets no write in 200 hours",
          [w for run in (B1, B2, B49, B200) for w in writes_for(run, FX, n, ident)], [])
REPOS[FX]["prs"][16]["headRefOid"] = head_of(FX, 16, gen=1)
REPOS[FX]["pushed"][16] = po.iso(NOW + 190 * H)
rc, B210 = run_main("B210", ["--apply"], NOW + 210 * H)
holds("P19", "after a new push, the reopened #16 is decided again (so the check can fail)",
      len(gh_writes(B210, FX, 16, "close")), 1)
ALL_B = B1 + B2 + B49 + B200 + B210
holds("P12", "no run sent more than one review",
      [t for t, run in (("A", A), ("B1", B1), ("B2", B2), ("B49", B49), ("B200", B200), ("B210", B210))
       if len(reviews(run)) > 1], [])
B_AT = (("A", A, NOW), ("B1", B1, NOW + H), ("B2", B2, NOW + 2 * H), ("B49", B49, NOW + 49 * H),
        ("B200", B200, NOW + 200 * H), ("B210", B210, NOW + 210 * H))
asked = [(a[3], at) for _t, run, at in B_AT for a in reviews(run)]
holds("P12", "no PR was reviewed twice inside 48 hours (no reviewed PR's head moved in this fleet)",
      [(n, t1, t2) for i, (n, t1) in enumerate(asked) for m, t2 in asked[i + 1:] if n == m and t2 - t1 < po.AGE_S], [])
holds("P12", "... and a review that never landed was asked again after them (so the check can fail)",
      len(asked) > len({n for n, _at in asked}), True)
holds("P26", "the ladder-owned #10 gets no write in any run, and Linear is never asked about ASK-777",
      ([w for run in (B1, B2, B49, B200, B210) for w in writes_for(run, FX, 10, "ASK-777")],
       [v.get("id") for _q, v in GRAPHQL if v.get("id") == "ASK-777"]), ([], []))
holds("P20", "across every run, no fork gets a gh write",
      [w for n in (9, 11, 12, 14) for w in gh_writes(A + ALL_B, FX, n)], [])

# ================================================================ scenario C: the exit codes and refusals
print("-- scenario C: exit codes and refusals")
REPOS.clear()
fresh_state("C1")
repo("o/a", "a", list_fails=True)
OB = repo("o/b", "b")
add(OB, 1, "feat/red", statusCheckRollup=RED)
rc, C1 = run_main("C1", ["--apply"], NOW)
holds("P32", "a repo gh cannot list exits 2, and the next repo is still owned",
      (rc, len(gh_writes(C1, OB, 1, "close"))), (2, 1))
REPOS.clear()
fresh_state("C2")
OB = repo("o/b", "b")
add(OB, 1, "feat/red", statusCheckRollup=RED)
WRITE_RC[("close", OB, 1)] = (1, "HTTP 422")
rc, _ = run_main("C2", ["--apply"], NOW)
WRITE_RC.clear()
holds("P32", "a close GitHub refuses is a failed action: exit 2", rc, 2)
REPOS.clear()
fresh_state("C3")
OB = repo("o/b", "b")
add(OB, 2, "fix/x-ask-6000", statusCheckRollup=RED)
TICKETS["ASK-6000"] = RuntimeError("HTTP 503 from Linear")
rc, C3 = run_main("C3", ["--apply"], NOW)
holds("P32", "Linear down: the red PR is held, nothing is closed, exit 2", (rc, gh_writes(C3, OB)), (2, []))
TICKETS["ASK-6000"] = ls.LinearAPIError("Entity not found: Issue")
fresh_state("C3b")
rc, C3b = run_main("C3b", ["--apply"], NOW)
holds("P32", "Linear says the ticket does not exist: no ticket, closed, exit 0 (so the check can fail)",
      (rc, len(gh_writes(C3b, OB, 2, "close"))), (0, 1))

_scripts = po.SCRIPTS
nofloor = TMP / "nofloor"
nofloor.mkdir()
(nofloor / "reviewer-floor.sh").write_text("#!/bin/bash\necho no floor here\n")
po.SCRIPTS = nofloor
rc, C4 = run_main("C4", [], NOW)
po.SCRIPTS = _scripts
holds("P32", "no FLOOR_DESC in reviewer-floor.sh refuses: exit 3, nothing read", (rc, [a for a in C4 if a[0] == "gh"]), (3, []))

HOOK.rename(HOOK.with_name("away.sh"))
rc, C5 = run_main("C5", [], NOW)
HOOK.with_name("away.sh").rename(HOOK)
holds("P05", "a missing archive hook refuses: exit 3, nothing read", (rc, [a for a in C5 if a[0] == "gh"]), (3, []))

REPOS.clear()
fresh_state("C6")
OB = repo("o/b", "b")
add(OB, 1, "feat/red", statusCheckRollup=RED)
HOOK.write_text("#!/bin/bash\ncat >/dev/null\necho 'guard: jq: command not found' >&2\nexit 1\n")
rc, C6 = run_main("C6", ["--apply"], NOW)
HOOK.write_text(HOOK_TEXT)
holds("P06", "an archive hook that crashes is no answer: the repo is never read",
      [a[:3] for a in C6 if a[:2] == ["gh", "pr"]], [])
holds("P32", "... and the unread repo exits 2, not a healthy 0", rc, 2)
rc, C6b = run_main("C6b", ["--apply"], NOW)
holds("P06", "the same repo with the hook restored is read and owned (so the check can fail)",
      (rc, len(gh_writes(C6b, OB, 1, "close"))), (0, 1))

_fleet = po.fleet_repos
po.fleet_repos = lambda root=None: ([], "")
rc, _ = run_main("C7", [], NOW)
po.fleet_repos = _fleet
holds("P32", "fleet_candidates returning no repo refuses: exit 3", rc, 3)

sp = fresh_state("C8")
sp.parent.mkdir(parents=True)
sp.write_text("{not json")
rc, _ = run_main("C8", ["--apply"], NOW)
holds("P32", "an unreadable state file refuses: exit 3, not running on a blank memory", rc, 3)

broken_root = TMP / "broken-root"
broken_root.mkdir()
(broken_root / "kipi-dispatch.sh").write_text("#!/bin/bash\nREPO=x\n")
_root = po.ROOT
po.fleet_repos, po.ROOT, ALLOW_BASH_C[0] = REAL_FLEET_REPOS, broken_root, True
rc, _ = run_main("C9", [], NOW)
po.fleet_repos, po.ROOT, ALLOW_BASH_C[0] = _fleet, _root, False
holds("P32", "a dispatcher with no fleet_candidates() refuses: exit 3", rc, 3)

rc, _ = run_main("C10", ["--no-such-flag"], NOW)
holds("P32", "a usage error exits 64", rc, 64)
rc, _ = run_main("C10b", ["-h"], NOW)
holds("P32", "-h exits 0", rc, 0)

sp = fresh_state("C11")
sp.parent.mkdir(parents=True)
held = open(sp.with_name("lock"), "w")
fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
rc, C11 = run_main("C11", ["--apply"], NOW)
held.close()
holds("P30", "a second --apply while the lock is held does nothing and exits 0",
      (rc, all_writes(C11), sp.exists()), (0, [], False))

REPOS.clear()
fresh_state("C12")
OB = repo("o/b", "b")
add(OB, 3, "sana/ask-6100", verdict=CHANGES, statusCheckRollup=RED)
TICKETS["ASK-6100"] = tk("ASK-6100", "started", "In Progress", 400)
LS_RC["requeue"] = (2, "", "BLOCK: HTTP 500 from Linear")
rc, C12 = run_main("C12", ["--apply"], NOW)
LS_RC.clear()
holds("P40", "a failed requeue still posts the resume note, and the run exits 2",
      ([a[2] for a in ls_calls(C12, ident="ASK-6100")], rc), (["requeue", "progress"], 2))

REPOS.clear()
fresh_state("C13")
OB = repo("o/b", "b")
add(OB, 4, "sana/ask-777", verdict=CHANGES, statusCheckRollup=RED)
broken_ladder = TMP / "broken-ladder" / "cap-ladder.py"
broken_ladder.parent.mkdir()
broken_ladder.write_text("X = 1\n")
po.CAP_LADDER = broken_ladder
rc, C13 = run_main("C13", ["--apply"], NOW)
po.CAP_LADDER = LADDER
holds("P28", "a cap-ladder.py with no ladder_owns() holds the PR: no write, exit 2",
      (all_writes(C13), rc, "hold o/b#4" in OUT["C13"]), ([], 2, True))

REPOS.clear()
fresh_state("C14")
OB = repo("o/b", "b")
add(OB, 5, "feat/approved-blocked", verdict=APPROVE, mergeStateStatus="BLOCKED")
_lib = po.VERDICT_LIB
po.VERDICT_LIB = TMP / "no-such-verdict-lib.sh"
rc, C14 = run_main("C14", ["--apply"], NOW)
po.VERDICT_LIB = _lib
holds("P37", "rework_gate that cannot answer holds the PR: no write, exit 2", (all_writes(C14), rc), ([], 2))

# ================================================================ scenario D: the archive and the kill switch
print("-- scenario D: the archive guard and the kill switch come before any read")
REPOS.clear()
fresh_state("D")
KS = repo("o/ks", "ks")
Path(REPOS[KS]["path"], ".kipi-no-dispatch").write_text("")
PS = repo("o/ps", "ps", path=TMP / "repos" / ARCHIVED_MARKER)
OK_ = repo("o/okr", "okr")
for s in (KS, PS, OK_):
    add(s, 1, "feat/red", statusCheckRollup=RED)
SLUG_ASKED.clear()
HOOK.write_text(DENY_STAND_IN)
rc, D = run_main("D", ["--apply"], NOW)
HOOK.write_text(HOOK_TEXT)
holds("P03", "the kill-switched repo: no gh call names it, its slug is never looked up, the log says why",
      ([a for a in D if KS in " ".join(a)], REPOS[KS]["path"] in SLUG_ASKED, "is present (kill switch)" in OUT["D"]),
      ([], False, True))
holds("P04", "the archived repo: no gh call names it, and the guard is asked before its slug is looked up",
      ([a for a in D if PS in " ".join(a)], REPOS[PS]["path"] in SLUG_ASKED), ([], False))
holds("P04", "the guard's refusal is in the log, and the third repo is still owned",
      ("the archive guard refuses it" in OUT["D"], len(gh_writes(D, OK_, 1, "close"))), (True, 1))
holds("P32", "excluded repos are not a failure: exit 0", rc, 0)

# ================================================================ scenario E: one function at a time
print("-- scenario E: the readers, the sink line, the ref, the render")
out = TMP / "render" / "com.kipi.pr-owner.plist"
rend = subprocess.run(["bash", str(SCRIPTS / "install-plist.sh"), "com.kipi.pr-owner", "--render-only", str(out)],
                      capture_output=True, text=True, timeout=60, env=dict(os.environ))
pl = plistlib.loads(out.read_bytes()) if out.is_file() else {}
args = pl.get("ProgramArguments") or []
pinned = FAKE_HOME / ".local/state/kipi/jobs/com.kipi.pr-owner/kipi-system"
holds("P02", "the rendered job runs kipi-job-pinned.sh from its own pinned tree",
      args[:2], ["/bin/bash", str(pinned / "q-system/.q-system/scripts/kipi-job-pinned.sh")])
holds("P02", "... which runs pr-owner.py --apply inside that tree, hourly",
      (any(f"cd {pinned} " in a and "pr-owner.py --apply" in a for a in args), pl.get("StartInterval")), (True, 3600))
holds("P02", "the job never sets the clock", "KIPI_PR_OWNER_NOW" in (pl.get("EnvironmentVariables") or {}), False)

stub = TMP / "stub-reviewer.sh"
stub.write_text('#!/bin/bash\necho "stub review $*"\n( sleep 8 ) &\nexit 0\n')
rlog = TMP / "rlog" / "review.log"
t0 = time.monotonic()
rc_l, _tail = REAL_RUN_LOGGED(["bash", str(stub), "77"], rlog, timeout=60)
holds("P42", "the reviewer returns while its background sleep still holds stdout (under 4s)",
      (rc_l, time.monotonic() - t0 < 4), (0, True))
holds("P42", "... and its output is in the log file", "stub review 77" in rlog.read_text(), True)

agent = (SCRIPTS / "pr-review-agent.sh").read_text()
posts = [ln for ln in agent.splitlines() if "state=pending" in ln and not ln.lstrip().startswith("#")]
msgs = re.findall(r'CAP_MSG="([^"]+)"', agent)
holds("P35", "every pending post in pr-review-agent.sh carries CAP_MSG, and that message reads as the cap",
      (len(posts) > 0, [ln for ln in posts if "$CAP_MSG" not in ln], len(msgs) > 0,
       [po.reviewer_state([{"context": po.REVIEWER_CONTEXT, "state": "pending",
                            "description": m.replace("$MAX_ROUNDS", "3")}], FLOOR)[0] for m in msgs]),
      (True, [], True, ["cap"] * len(msgs)))

bash_floor = subprocess.run(["bash", "-c", 'eval "$(grep -E "^FLOOR_DESC=" "$1")"; printf %s "$FLOOR_DESC"', "x",
                             str(SCRIPTS / "reviewer-floor.sh")], capture_output=True, text=True).stdout
holds("P33", "floor_desc() is the FLOOR_DESC reviewer-floor.sh posts, as bash reads it",
      (bool(FLOOR), FLOOR), (True, bash_floor))

holds("P43", "only ASK-n names a ticket",
      (po.ticket_candidates("lessons/weekly-2026-10-19", "weekly distill 2026-10-19"),
       po.ticket_candidates("fix/x-ask-12", "ENG-5 and WEEKLY-2026")), ([], ["ASK-12"]))

refs = [po.alert_ref(f"o/r{i % 7}#{i}") for i in range(300)]
holds("P25", "the ref is one word of g-v letters, distinct per PR, the same every call",
      (all(re.fullmatch(r"ref[g-v]{16}", r) for r in refs), len(set(refs)), po.alert_ref("o/r0#0")), (True, 300, refs[0]))
a2l_spec = importlib.util.spec_from_file_location("alert_sink_contract", SCRIPTS / "alert-to-linear.py")
a2l = importlib.util.module_from_spec(a2l_spec)
a2l_spec.loader.exec_module(a2l)
pr_ = lambda slug, n: {"slug": slug, "number": n, "url": f"https://github.com/{slug}/pull/{n}"}  # noqa: E731
fps = {a2l.fingerprint(po.outside_alert(pr_(s, n), "head provenance is fork"))
       for s, n in (("o/kipi-system", 526), ("o/brag", 2), ("o/kipi-system", 2), ("o/openwitness", 41))}
holds("P25", "four fork PRs, two of them #2 in different repos, are four fingerprints in the real sink", len(fps), 4)

holds("P24", "the alert's own line is the first sink line; a later 'filed' line is never read as its ticket",
      (po.filed_ticket("alert-to-linear: suppressed as noise\nalert-to-linear: filed ASK-77 https://x"),
       po.filed_ticket("alert-to-linear: filed ASK-77 https://x\nalert-to-linear: repeat #2 on ASK-5")),
      ("", "ASK-77"))

cap_file = TMP / "capture.txt"
os.environ["KIPI_ALERT_CAPTURE"] = str(cap_file)
fresh_state("E-capture")
lone = {"slug": "o/fx", "number": 13, "url": "https://github.com/o/fx/pull/13", "head": "13" * 20,
        "branch": "feat/x", "pushed": None}
lone_state: dict = {}
ok_, what, _write = po.act(lone, {"action": "outside", "reason": "head provenance is fork"}, lone_state, NOW)
os.environ.pop("KIPI_ALERT_CAPTURE", None)
holds("P23", "the sink exits 0 and names no ticket (its capture hatch): not ok, not recorded, but the sink took it",
      (ok_, "o/fx#13" in (lone_state.get("outside") or {}),
       "PR #13 (" in (cap_file.read_text() if cap_file.is_file() else "")), (False, False, True))

stand_in = TMP / "ladder-stand-in" / "cap-ladder.py"
stand_in.parent.mkdir()
stand_in.write_text("def ladder_owns(slug, number, branch, state_dir):\n    return ''\n")
po.CAP_LADDER = stand_in
lpr = {"slug": "o/fx", "number": 10, "branch": "sana/ask-777"}
holds("P27", "with a cap-ladder.py in the tree, its answer stands, even where the fallback would yield",
      (REAL_LADDER_CHECK(lpr, str(TMP / "worker")), bool(po._ladder_absent(lpr, str(TMP / "worker")))), ("", True))
po.CAP_LADDER = LADDER

fx_root = TMP / "dispatch-root"
fx_root.mkdir()
shutil.copy(REPO / "kipi-dispatch.sh", fx_root / "kipi-dispatch.sh")
disp_before = (fx_root / "kipi-dispatch.sh").read_bytes()
reg, overlay = TMP / "registry.json", TMP / "overlay.json"
reg.write_text(json.dumps({"instances": [
    {"name": "on", "path": "/fx/on", "dispatch": {"enabled": True}},
    {"name": "off", "path": "/fx/off", "dispatch": {"enabled": False}}]}))
overlay.write_text(json.dumps({"instances": [{"name": "client", "path": "/fx/client", "dispatch": {"enabled": True}}]}))
os.environ["KIPI_DISPATCH_REGISTRY"], os.environ["KIPI_DISPATCH_TARGETS"] = str(reg), str(overlay)
ALLOW_BASH_C[0] = True
rows, _targets = REAL_FLEET_REPOS(fx_root)
ALLOW_BASH_C[0] = False
for k in ("KIPI_DISPATCH_REGISTRY", "KIPI_DISPATCH_TARGETS"):
    os.environ.pop(k, None)
holds("P46", "the dispatcher's overlay row (a client repo) is in the set", "client" in [r[0] for r in rows], True)
holds("P44", "reading the dispatcher leaves kipi-dispatch.sh byte for byte as it was",
      (fx_root / "kipi-dispatch.sh").read_bytes() == disp_before, True)

# ================================================================ scenario F: ASK-4099
print("-- scenario F: ASK-4099 (a ticket the worker does not pick, the bound, no checks, BEHIND, the merge)")
DAY = 86400

# F1: a Triage ticket is never promised a worker rework.
REPOS.clear()
fresh_state("F1")
TR = repo("o/tri", "tri")
add(TR, 1, "sana/ask-7001", verdict=CHANGES, statusCheckRollup=RED)
add(TR, 2, "sana/ask-7002", verdict=CHANGES, statusCheckRollup=RED)
TICKETS.update({"ASK-7001": tk("ASK-7001", "triage", "Triage"), "ASK-7002": tk("ASK-7002", "backlog")})
rc, F1 = run_main("F1", ["--apply"], NOW)
c1 = gh_writes(F1, TR, 1)
holds("P47", "a red worker-branch PR whose ticket is in Triage: no 'worker reworks it' text in any write",
      [a for a in c1 if "worker reworks it" in body_of(a)], [])
holds("P47", "... it is closed (branch kept) saying why, and its ticket gets a resume note, not a requeue",
      ([a[2] for a in c1], [a[2] for a in ls_calls(F1, ident="ASK-7001")],
       bool(c1) and "which linear-worker.sh does not pick" in body_of(c1[0])), (["close"], ["progress"], True))
holds("P47", "the same PR with its ticket in Backlog does get 'so the worker reworks it' (so the check can fail)",
      ["so the worker reworks it" in body_of(a) for a in gh_writes(F1, TR, 2)], [True])
holds("P47", "the queue states are read from linear-worker.sh itself",
      tuple((getattr(po, "worker_queue_states", None) or (lambda: ("missing",)))()), ("backlog", "unstarted"))
fresh_state("F1b")
no_queue = TMP / "no-queue" / "linear-worker.sh"
no_queue.parent.mkdir()
no_queue.write_text("#!/bin/bash\necho no queue states here\n")
_wsh = getattr(po, "WORKER_SH", None)
po.WORKER_SH = no_queue
rc, F1b = run_main("F1b", ["--apply"], NOW)
po.WORKER_SH = _wsh
holds("P47", "a linear-worker.sh with no QUEUE_STATES holds each worker-branch red PR: no write, exit 2",
      (writes_for(F1b, TR, 1, "ASK-7001") + writes_for(F1b, TR, 2, "ASK-7002"), rc), ([], 2))

# F2: 1,000 old closed entries are pruned on the next run; nothing a reopen or an unread repo needs is.
REPOS.clear()
sp = fresh_state("F2")
PRN = repo("o/prune", "prune")
DOWN = repo("o/down", "down", list_fails=True)
BIG = repo("o/big", "big")
for n in range(1, 201):
    add(BIG, n, f"feat/b{n}", createdAt=FRESH, pushed=FRESH)
add(PRN, 3, "feat/reopened", statusCheckRollup=RED)
OLD_AT = NOW - 40 * DAY
old = lambda h="f" * 40: {"head": h, "at": OLD_AT, "action": "close-comment"}  # noqa: E731
st0 = {"closed": {f"{PRN}#{n}": old() for n in range(1000, 2000)}}
st0["closed"].update({f"{PRN}#3": old(head_of(PRN, 3)), f"{PRN}#4000": {**old(), "at": NOW - 5 * DAY},
                      f"{BIG}#9999": old(), **{f"{DOWN}#{n}": old() for n in range(1, 11)}})
st0.update({"strikes": {f"{PRN}#5001": old()}, "reviews": {f"{PRN}#5002": old()},
            "outside": {f"{PRN}#5003": {**old(), "ticket": "ASK-1"}}, "updates": {f"{PRN}#5004": old()},
            "held": {f"{PRN}#5005": {**old(), "ticket": "ASK-2"}}})
sp.parent.mkdir(parents=True)
sp.write_text(json.dumps(st0))
before = sp.read_bytes()
rc, _ = run_main("F2-dry", [], NOW)
holds("P48", "a dry run leaves the state file byte for byte and says what it would prune",
      (sp.read_bytes() == before, "would prune 1005 state entr" in OUT["F2-dry"]), (True, True))
rc, F2 = run_main("F2", ["--apply"], NOW)
st = json.loads(sp.read_text())
holds("P48", "1,000 closed entries 40 days old for PRs gone from a listed repo are pruned; the rest stay",
      sorted(st.get("closed") or {}),
      sorted([f"{PRN}#3", f"{PRN}#4000", f"{BIG}#9999"] + [f"{DOWN}#{n}" for n in range(1, 11)]))
holds("P48", "... and the same rule prunes strikes, reviews, fork alerts, updates and held alerts",
      [st.get(m) or {} for m in ("strikes", "reviews", "outside", "updates", "held")], [{}, {}, {}, {}, {}])
holds("P48", "#3, reopened at the head pr-owner closed it at 40 days ago, keeps its undo: no write",
      (writes_for(F2, PRN, 3), f"reopened {PRN}#3" in OUT["F2"]), ([], True))
holds("P48", "the run says how many it pruned", "pruned 1005 state entr" in OUT["F2"], True)

# F3: no check reported is not CI green.
REPOS.clear()
fresh_state("F3")
NC, WF, WFF = repo("o/nochecks", "nochecks"), repo("o/withwf", "withwf"), repo("o/wffail", "wffail")
SLOT_ONLY = [{"__typename": "StatusContext", "context": po.REVIEWER_CONTEXT, "state": "SUCCESS"}]
add(NC, 1, "feat/a", verdict=APPROVE, mergeStateStatus="CLEAN", statusCheckRollup=None)
add(NC, 2, "feat/b", verdict=APPROVE, mergeStateStatus="CLEAN", statusCheckRollup=SLOT_ONLY)
add(WF, 1, "feat/a", verdict=APPROVE, mergeStateStatus="CLEAN", statusCheckRollup=None)
add(WFF, 1, "feat/a", verdict=APPROVE, mergeStateStatus="CLEAN", statusCheckRollup=None)
WORKFLOWS[WF] = ["ci.yml"]
WORKFLOWS_FAIL.add(WFF)
holds("P49", "ci_state: null, empty and slot-only rollups are 'none'; one passing check is 'green'",
      [po.ci_state(r)[0] for r in (None, [], SLOT_ONLY, GREEN)], ["none", "none", "none", "green"])
rc, F3 = run_main("F3", ["--apply"], NOW)
mline = lambda tag, s, n: [ln for ln in OUT[tag].splitlines() if ln.startswith(f"MERGE {s}#{n} ")]  # noqa: E731
holds("P49", "in a repo with no workflow file, both are merged, and neither log line says 'CI green'",
      [(len(gh_writes(F3, NC, n, "merge")), [("CI green" in ln, "no workflow file" in ln) for ln in mline("F3", NC, n)])
       for n in (1, 2)], [(1, [(False, True)])] * 2)
holds("P49", "in a repo with workflows, no check at this head is red: no merge, a close that says so",
      (gh_writes(F3, WF, 1, "merge"), ["no CI check reported" in body_of(a) for a in gh_writes(F3, WF, 1, "close")]),
      ([], [True]))
holds("P49", "a workflow read that fails holds the PR: no write, exit 2",
      (writes_for(F3, WFF, 1), f"hold {WFF}#1" in OUT["F3"], rc), ([], True, 2))
WORKFLOWS.clear()
WORKFLOWS_FAIL.clear()

# F4: an approved PR that is only BEHIND is updated, once per head, never closed for it.
REPOS.clear()
fresh_state("F4")
BH = repo("o/behind", "behind")
add(BH, 1, "feat/behind", verdict=APPROVE, mergeStateStatus="BEHIND")
add(BH, 2, "sana/ask-7101", verdict=APPROVE, mergeStateStatus="BEHIND")
TICKETS["ASK-7101"] = tk("ASK-7101", "started", "In Progress", 2)
rc, F4 = run_main("F4", ["--apply"], NOW)
holds("P50", "approved, green, MERGEABLE, only BEHIND, no ticket: one update-branch, no close, no comment, exit 0",
      ([a[:4] for a in gh_writes(F4, BH, 1)], rc), ([["gh", "pr", "update-branch", "1"]], 0))
holds("P50", "the same shape with a live lane on its ticket gets no write", writes_for(F4, BH, 2, "ASK-7101"), [])
rc, F4b = run_main("F4b", ["--apply"], NOW + H)
c4 = gh_writes(F4b, BH, 1)
# PR #693 round 4 (item 2 of the round-3 RCA): GitHub said yes and did nothing.
# That is a write that did not take, not a verdict on the PR, so it holds.
holds("P50", "an hour later at the same head, GitHub accepted the call and the head did not move: asked again, "
             "never closed, exit 2",
      ([a[2] for a in c4], rc, "and the head did not move" in OUT["F4b"]), (["update-branch"], 2, True))
holds("P52", "... and that hold files one alert, naming the PR, through the real sink", len(sink_calls(F4b, 1)), 1)
rc, F4b2 = run_main("F4b2", ["--apply"], NOW + 2 * H)
holds("P52", "two hours later, still unmoved: asked again, exit 2, and no second alert at this head",
      ([a[2] for a in gh_writes(F4b2, BH, 1)], rc, sink_calls(F4b2, 1)), (["update-branch"], 2, []))
# PR #693 round 1, major: a 502 on the call must not read as a rebase that did not take.
REPOS.clear()
sp = fresh_state("F4c")
BH = repo("o/behind", "behind")
add(BH, 1, "feat/behind", verdict=APPROVE, mergeStateStatus="BEHIND")
WRITE_RC[("update-branch", BH, 1)] = (1, "HTTP 502: Bad Gateway")
WRITE_ENVS.clear()
os.environ["GH_HOST"] = "evil.example"
rc, F4c = run_main("F4c", ["--apply"], NOW)
os.environ.pop("GH_HOST", None)
WRITE_RC.clear()
holds("P50", "a 502 on update-branch: the run exits 2 and records one failed attempt, not an accepted call",
      (rc, {k: v.get("fails") for k, v in (json.loads(sp.read_text()).get("updates") or {}).items()}),
      (2, {f"{BH}#1": 1}))
holds("P51", "GH_HOST in the job's env does not reach the update-branch write either",
      (len(WRITE_ENVS), [e for e in WRITE_ENVS if e is None or {"GH_REPO", "GH_HOST"} & set(e)]), (1, []))
rc, F4d = run_main("F4d", ["--apply"], NOW + H)
holds("P50", "an hour later the update is asked again, not closed (a failed call is not a failed rebase)",
      ([a[2] for a in gh_writes(F4d, BH, 1)], rc), (["update-branch"], 0))
# PR #693 round 2, major: a call that fails every time gets an exit. Round 3, major:
# that exit was a close. Round 4 (the RCA's red-first check): a 403 for 24 hours is
# 24 asks, exit 2 every run, no close, and one alert, not 24.
sp = fresh_state("F4e")
WRITE_RC[("update-branch", BH, 1)] = (1, "HTTP 403: Resource not accessible by integration")
WRITE_ENVS.clear()
os.environ.update({"GH_REPO": "o/evil", "GH_HOST": "evil.example"})
tries = [run_main(f"F4e-{h}", ["--apply"], NOW + h * H) for h in range(24)]
for k in ("GH_REPO", "GH_HOST"):
    os.environ.pop(k, None)
WRITE_RC.clear()
holds("P50", "a 403 every hour for 24 hours: update-branch is asked every run, nothing else is sent, every run exits 2",
      ([[a[2] for a in gh_writes(run, BH, 1)] for _rc, run in tries], [r for r, _run in tries]),
      ([["update-branch"]] * 24, [2] * 24))
held4e = (json.loads(sp.read_text()).get("held") or {}).get(f"{BH}#1") or {}
alerts4e = [a for _rc, run in tries for a in sink_calls(run, 1)]
holds("P52", "... one alert in those 24 hours, carrying GitHub's error, and the state records the ticket the sink named",
      (len(alerts4e), bool(alerts4e) and "HTTP 403" in alerts4e[0][2],
       held4e.get("head") == head_of(BH, 1), bool(re.fullmatch(r"ASK-\d+", held4e.get("ticket") or ""))),
      (1, True, True, True))
holds("P51", "GH_REPO and GH_HOST reach no gh write",
      (sorted({a[2] for _rc, run in tries for a in gh_writes(run)}),
       [e for e in WRITE_ENVS if e is None or {"GH_REPO", "GH_HOST"} & set(e)]), (["update-branch"], []))
# Round 3's other two reproducers: a 502 outage that outlasts the old cap, and the
# recovery after it. Four failed hours, then GitHub answers: the fifth ask lands.
REPOS.clear()
fresh_state("F4f")
OUT4 = repo("o/outage", "outage")
add(OUT4, 1, "feat/behind", verdict=APPROVE, mergeStateStatus="BEHIND")
WRITE_RC[("update-branch", OUT4, 1)] = (1, "HTTP 502: Bad Gateway")
tries = [run_main(f"F4f-{h}", ["--apply"], NOW + h * H) for h in range(4)]
WRITE_RC.clear()
tries.append(run_main("F4f-4", ["--apply"], NOW + 4 * H))
holds("P50", "a 502 for 4 hours, then GitHub recovers: asked every hour, never closed, the 5th ask lands (exit 0)",
      ([[a[2] for a in gh_writes(run, OUT4, 1)] for _rc, run in tries], [r for r, _run in tries]),
      ([["update-branch"]] * 5, [2, 2, 2, 2, 0]))
holds("P52", "... with one alert across the outage", sum(len(sink_calls(run, 1)) for _rc, run in tries), 1)
REPOS[OUT4]["prs"][1]["headRefOid"] = head_of(OUT4, 1, gen=1)
REPOS[OUT4]["pushed"][1] = po.iso(NOW + 4 * H)
rc, F4f5 = run_main("F4f-5", ["--apply"], NOW + 5 * H)
holds("P50", "an hour after it lands, GitHub's new head waits out its quiet: no write (so the ask is not looped)",
      (writes_for(F4f5, OUT4, 1), rc), ([], 0))

# F5: the merge is the gate's one shape, asked of the gate, re-read, and read back.
REPOS.clear()
MG = repo("o/mg", "mg")
add(MG, 1, "feat/ok", verdict=APPROVE, mergeStateStatus="CLEAN")
MG_PATH = REPOS[MG]["path"]
gate_fn = getattr(po, "merge_gate_verdict", None)
REAL_GATE = SCRIPTS / "merge-bypass-gate.py"
holds("P51", "the real merge-bypass-gate.py allows the merge pr-owner sends, and denies its old shape (the check can fail)",
      ((gate_fn(["pr", "merge", "--auto", "--squash", "1"], MG_PATH) if gate_fn else "missing"),
       (bool(gate_fn(["pr", "merge", "1", "-R", MG, "--squash", "--match-head-commit", "a" * 40], MG_PATH))
        if gate_fn else "missing")), ("", True))
deny_gate, crash_gate = TMP / "gates" / "deny.py", TMP / "gates" / "crash.py"
deny_gate.parent.mkdir()
deny_gate.write_text("import json, sys\njson.load(sys.stdin)\nprint(json.dumps({'hookSpecificOutput': {'hookEventName': "
                     "'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': 'stand-in'}}))\n")
crash_gate.write_text("import sys\nsys.exit(1)\n")
for tag, gate in (("denies", deny_gate), ("cannot answer", crash_gate)):
    fresh_state("F5-" + tag.replace(" ", "-"))
    po.MERGE_GATE = gate
    rc, F5 = run_main("F5-" + tag, ["--apply"], NOW)
    po.MERGE_GATE = REAL_GATE
    holds("P51", f"a gate that {tag}: no merge is sent, exit 2", (gh_writes(F5, MG, 1, "merge"), rc), ([], 2))
for tag, knob, val in (("its head moved", VIEW_HEAD, "9" * 40),
                       ("the checkout resolves another repo", VIEW_URL, "https://github.com/o/other/pull/1")):
    fresh_state("F5-" + tag)
    knob[(MG, 1)] = val
    rc, F5 = run_main("F5-" + tag, ["--apply"], NOW)
    knob.clear()
    holds("P51", f"the re-read from the checkout says {tag}: no merge is sent, exit 2",
          (gh_writes(F5, MG, 1, "merge"), rc), ([], 2))
for tag, mark, word, want_rc in (("merged", None, "-> merged", 0), ("armed", ARMED, "-> auto-merge armed", 0),
                                 ("neither", NEITHER, "neither merged nor armed", 2)):
    fresh_state("F5-" + tag)
    MERGED_DONE.clear()
    CWD_ENVS.clear()
    if mark is not None:
        mark.add((MG, 1))
    os.environ.update({"GH_REPO": "o/evil", "GH_HOST": "evil.example"})
    rc, F5 = run_main("F5-" + tag, ["--apply"], NOW)
    for k in ("GH_REPO", "GH_HOST"):
        os.environ.pop(k, None)
    if mark is not None:
        mark.clear()
    holds("P51", f"read back as {tag}: the log says so and the run exits {want_rc}",
          (len(gh_writes(F5, MG, 1, "merge")), word in OUT["F5-" + tag], rc), (1, True, want_rc))
    holds("P51", f"({tag}) GH_REPO and GH_HOST in the job's env reach none of the checkout's gh calls",
          (len(CWD_ENVS) >= 3, [e for e in CWD_ENVS if e is None or {"GH_REPO", "GH_HOST"} & set(e)]), (True, []))

# ================================================================ scenario G: PR #693 round 4
# The round-3 RCA's root cause #2: tests were built from each finding's one input,
# not its class. So every write pr-owner makes gets the same three inputs here: a
# failure (transient or permanent), and the recovery after it. A failed write is
# environmental (self-healing-retry.md rule 5): held and surfaced, never escalated.
print("-- scenario G: every write of pr-owner's own that fails is held, never closed")

REPOS.clear()
fresh_state("G1")
MERGED_DONE.clear()
GM = repo("o/gmerge", "gmerge")
add(GM, 1, "feat/ok", verdict=APPROVE, mergeStateStatus="CLEAN")
WRITE_RC[("merge", GM, 1)] = (1, "HTTP 502: Bad Gateway")
tries = [run_main(f"G1-{h}", ["--apply"], NOW + h * H) for h in range(3)]
WRITE_RC.clear()
tries.append(run_main("G1-3", ["--apply"], NOW + 3 * H))
holds("P52", "a merge GitHub answers with a 502 for 3 hours: asked every hour, never closed, exit 2, then merged",
      ([[a[2] for a in gh_writes(run, GM, 1)] for _rc, run in tries], [r for r, _run in tries]),
      ([["merge"]] * 4, [2, 2, 2, 0]))
holds("P52", "... and one alert for the three failed hours", sum(len(sink_calls(run, 1)) for _rc, run in tries), 1)

REPOS.clear()
fresh_state("G2")
GC = repo("o/gclose", "gclose")
add(GC, 1, "feat/red", statusCheckRollup=RED)
WRITE_RC[("close", GC, 1)] = (1, "HTTP 422: Unprocessable Entity")
WRITE_ENVS.clear()
os.environ.update({"GH_REPO": "o/evil", "GH_HOST": "evil.example"})
tries = [run_main(f"G2-{h}", ["--apply"], NOW + h * H) for h in range(3)]
WRITE_RC.clear()
tries.append(run_main("G2-3", ["--apply"], NOW + 3 * H))
for k in ("GH_REPO", "GH_HOST"):
    os.environ.pop(k, None)
holds("P52", "a close GitHub refuses for 3 hours: asked again every hour, exit 2, the 4th lands, one alert",
      ([[a[2] for a in gh_writes(run, GC, 1)] for _rc, run in tries], [r for r, _run in tries],
       sum(len(sink_calls(run, 1)) for _rc, run in tries)), ([["close"]] * 4, [2, 2, 2, 0], 1))
holds("P51", "GH_REPO and GH_HOST reach no gh write, the close included",
      (sorted({a[2] for _rc, run in tries for a in gh_writes(run)}),
       [e for e in WRITE_ENVS if e is None or {"GH_REPO", "GH_HOST"} & set(e)]), (["close"], []))

REPOS.clear()
sp = fresh_state("G3")
GW = repo("o/grework", "grework")
add(GW, 1, "sana/ask-7201", verdict=CHANGES, statusCheckRollup=RED)
TICKETS["ASK-7201"] = tk("ASK-7201", "backlog")
WRITE_RC[("comment", GW, 1)] = (1, "HTTP 502: Bad Gateway")
rc0, G3a = run_main("G3a", ["--apply"], NOW)
strikes0 = dict(json.loads(sp.read_text()).get("strikes") or {})
WRITE_RC.clear()
rc1, G3b = run_main("G3b", ["--apply"], NOW + H)
strike3 = (json.loads(sp.read_text()).get("strikes") or {}).get(f"{GW}#1") or {}
holds("P52", "a rework comment GitHub refuses: no strike, no Linear write, exit 2; the next hour asks again, "
             "and the strike starts when it lands",
      ([a[2] for a in gh_writes(G3a, GW, 1)], ls_calls(G3a, ident="ASK-7201"), rc0, strikes0,
       [a[2] for a in gh_writes(G3b, GW, 1)], rc1, strike3.get("at")),
      (["comment"], [], 2, {}, ["comment"], 0, NOW + H))

REPOS.clear()
fresh_state("G4")
GN = repo("o/gnote", "gnote")
add(GN, 1, "sana/ask-7202", verdict=CHANGES, statusCheckRollup=RED)
TICKETS["ASK-7202"] = tk("ASK-7202", "started", "In Progress", 400)
LS_RC.update({"requeue": (2, "", "BLOCK: HTTP 500 from Linear"), "progress": (2, "", "BLOCK: HTTP 500 from Linear")})
tries = [run_main(f"G4-{h}", ["--apply"], NOW + h * H) for h in (0, 1, 2, 49)]
LS_RC.clear()
holds("P13", "a rework whose ticket note never lands: one PR comment, the note asked again every run, "
             "no close at hour 49, exit 2",
      (sum(len(gh_writes(run, GN, 1, "comment")) for _rc, run in tries),
       sum(len(gh_writes(run, GN, 1, "close")) for _rc, run in tries),
       [len(ls_calls(run, "requeue", "ASK-7202")) for _rc, run in tries], [r for r, _run in tries]),
      (1, 0, [1, 1, 1, 1], [2, 2, 2, 2]))
holds("P52", "... and one alert for it", sum(len(sink_calls(run, 1)) for _rc, run in tries), 1)
tries = [run_main(f"G4-{h}", ["--apply"], NOW + h * H) for h in (50, 97, 99)]
holds("P13", "once the note lands (hour 50) the 48 hours start there: no second comment, open at hour 97, "
             "closed at hour 99",
      ([[a[2] for a in gh_writes(run, GN, 1)] for _rc, run in tries], [r for r, _run in tries]),
      ([[], [], ["close"]], [0, 0, 0]))

REPOS.clear()
fresh_state("G5")
GL = repo("o/glost", "glost")
add(GL, 1, "fix/x-ask-7203", statusCheckRollup=RED)
TICKETS["ASK-7203"] = tk("ASK-7203", "started", "In Progress", 400)
LS_RC.update({"requeue": (2, "", "BLOCK: HTTP 500 from Linear"), "progress": (2, "", "BLOCK: HTTP 500 from Linear")})
rc, G5 = run_main("G5", ["--apply"], NOW)
LS_RC.clear()
holds("P52", "a close whose ticket note does not land: closed for its content, exit 2, and the alert names the ticket",
      ([a[2] for a in gh_writes(G5, GL, 1)], rc, ["ASK-7203" in a[2] for a in sink_calls(G5, 1)]),
      (["close"], 2, [True]))

REPOS.clear()
sp = fresh_state("G6")
GR = repo("o/greview", "greview")
add(GR, 1, "feat/a")
REVIEW_RC[0] = 9
rc0, G6a = run_main("G6a", ["--apply"], NOW)
rec6 = (json.loads(sp.read_text()).get("reviews") or {}).get(f"{GR}#1")
REVIEW_RC[0] = 0
rc1, G6b = run_main("G6b", ["--apply"], NOW + H)
holds("P12", "the reviewer's exit 9 (no review ran, a machine condition): exit 2, not recorded as asked, "
             "and the next run asks again",
      ([a[3] for a in reviews(G6a)], rc0, rec6, [a[3] for a in reviews(G6b)], rc1), (["1"], 2, None, ["1"], 0))
holds("P12", "... and 9 is the code pr-review-agent.sh itself names as the machine's, not the PR's",
      (po.REVIEW_ENV_RC, "A condition of the machine (exit 9), not of the PR" in (SCRIPTS / "pr-review-agent.sh").read_text()),
      (9, True))

REPOS.clear()
fresh_state("G7")
GK = repo("o/gcrash", "gcrash")
add(GK, 1, "feat/a")
REVIEW_RC[0] = 1
rc0, G7a = run_main("G7a", ["--apply"], NOW)
REVIEW_RC[0] = 0
tries = [run_main(f"G7-{h}", ["--apply"], NOW + h * H) for h in (1, 47, 49)]
holds("P12", "a crashed review: exit 2 and one alert; not asked again at hour 1 or 47; asked again at hour 49, "
             "never closed",
      (rc0, len(sink_calls(G7a, 1)), [[a[3] for a in reviews(run)] for _rc, run in tries],
       [a for _rc, run in tries for a in gh_writes(run, GK, 1)], sum(len(sink_calls(run, 1)) for _rc, run in tries)),
      (2, 1, [[], [], ["1"]], [], 0))

REPOS.clear()
sp = fresh_state("G8")
GQ = repo("o/gcap", "gcap")
add(GQ, 1, "feat/behind", verdict=APPROVE, mergeStateStatus="BEHIND")
WRITE_RC[("update-branch", GQ, 1)] = (1, "HTTP 502: Bad Gateway")
cap8 = TMP / "capture-g8.txt"
os.environ["KIPI_ALERT_CAPTURE"] = str(cap8)
rc0, G8a = run_main("G8a", ["--apply"], NOW)
os.environ.pop("KIPI_ALERT_CAPTURE", None)
held8 = (json.loads(sp.read_text()).get("held") or {}).get(f"{GQ}#1")
rc1, G8b = run_main("G8b", ["--apply"], NOW + H)
WRITE_RC.clear()
held8b = (json.loads(sp.read_text()).get("held") or {}).get(f"{GQ}#1") or {}
holds("P52", "a sink that takes the alert and names no ticket (its capture hatch): not recorded, so the next "
             "failure asks the sink again, and that one is recorded",
      (len(sink_calls(G8a, 1)), "PR #1 (" in (cap8.read_text() if cap8.is_file() else ""), held8,
       len(sink_calls(G8b, 1)), bool(re.fullmatch(r"ASK-\d+", held8b.get("ticket") or ""))),
      (1, True, None, 1, True))

# ================================================================ scenario H: PR #693 round 5
# Round 4's tests failed the requeue and the note together (G4), so the case of one
# half failing was never run, and a requeue that failed while its note posted
# re-posted that note every hour (round 4, major). The input class here is every
# outcome of each Linear half, plus two different failed writes at one head.
print("-- scenario H: a rework's requeue and its note are two writes with two results")
REQ_FAIL = (2, "", "BLOCK: HTTP 422 from Linear")
NOTE_FAIL = (2, "", "BLOCK: HTTP 500 from Linear")


def per_hour(tries, fn):
    return [fn(run) for _rc, run in tries]


REPOS.clear()
sp = fresh_state("H1")
HA = repo("o/hreq", "hreq")
add(HA, 1, "sana/ask-7301", verdict=CHANGES, statusCheckRollup=RED)
TICKETS["ASK-7301"] = tk("ASK-7301", "started", "In Progress", 400)
LS_RC["requeue"] = REQ_FAIL
tries = [run_main(f"H1-{h}", ["--apply"], NOW + h * H) for h in range(6)]
strikeH1 = (json.loads(sp.read_text()).get("strikes") or {}).get(f"{HA}#1") or {}
holds("P53", "a requeue that fails while its note posts: one PR comment, one note, one requeue in 6 hours, "
             "exit 2 once, one alert, and the 48h start at that note",
      (sum(len(gh_writes(run, HA, 1, "comment")) for _rc, run in tries),
       sum(len(ls_calls(run, "progress", "ASK-7301")) for _rc, run in tries),
       sum(len(ls_calls(run, "requeue", "ASK-7301")) for _rc, run in tries),
       [r for r, _run in tries], sum(len(sink_calls(run, 1)) for _rc, run in tries),
       (strikeH1.get("noted"), strikeH1.get("at"))),
      (1, 1, 1, [2, 0, 0, 0, 0, 0], 1, (True, NOW)))
rc47, H1_47 = run_main("H1-47", ["--apply"], NOW + 47 * H)
rc49, H1_49 = run_main("H1-49", ["--apply"], NOW + 49 * H)
LS_RC.clear()
holds("P53", "... so the close ladder is reachable: open at hour 47, closed at hour 49",
      ([a[2] for a in gh_writes(H1_47, HA, 1)], [a[2] for a in gh_writes(H1_49, HA, 1)]), ([], ["close"]))

REPOS.clear()
sp = fresh_state("H2")
HB = repo("o/hboth", "hboth")
add(HB, 1, "sana/ask-7302", verdict=CHANGES, statusCheckRollup=RED)
TICKETS["ASK-7302"] = tk("ASK-7302", "started", "In Progress", 400)
LS_RC.update({"requeue": REQ_FAIL, "progress": NOTE_FAIL})
tries = [run_main("H2-0", ["--apply"], NOW)]
LS_RC.pop("progress")
tries += [run_main("H2-1", ["--apply"], NOW + H)]
LS_RC.clear()
tries += [run_main(f"H2-{h}", ["--apply"], NOW + h * H) for h in (2, 48, 49)]
# Every Linear write per hour, not only progress: a requeue that moves posts the
# resume line too, so a re-asked requeue is a re-posted note.
holds("P53", "both halves fail, then the note posts while the requeue still fails, then Linear recovers: the note "
             "is asked until it lands and never after, the 48h start at hour 1, closed at hour 49",
      (per_hour(tries, lambda run: [a[2] for a in ls_calls(run, ident="ASK-7302")]),
       per_hour(tries, lambda run: [a[2] for a in gh_writes(run, HB, 1)]), [r for r, _run in tries]),
      ([["requeue", "progress"], ["requeue", "progress"], [], [], ["requeue"]],
       [["comment"], [], [], [], ["close"]], [2, 2, 0, 0, 0]))
holds("P52", "... one alert per failed write: the two halves at hour 0, the requeue alone at hour 1",
      per_hour(tries, lambda run: len(sink_calls(run, 1))), [1, 1, 0, 0, 0])

REPOS.clear()
fresh_state("H3")
HC = repo("o/hnote", "hnote")
add(HC, 1, "sana/ask-7303", verdict=CHANGES, statusCheckRollup=RED)
TICKETS["ASK-7303"] = tk("ASK-7303", "backlog")
LS_RC["progress"] = NOTE_FAIL
tries = [run_main("H3-0", ["--apply"], NOW)]
LS_RC.clear()
tries += [run_main(f"H3-{h}", ["--apply"], NOW + h * H) for h in (1, 2)]
holds("P53", "a ticket in Backlog has no requeue: a note that fails is asked again next hour, and once it lands "
             "it is not asked again",
      (per_hour(tries, lambda run: len(ls_calls(run, "progress", "ASK-7303"))),
       sum(len(ls_calls(run, "requeue")) for _rc, run in tries), [r for r, _run in tries]),
      ([1, 1, 0], 0, [2, 0, 0]))

REPOS.clear()
fresh_state("H4")
HD = repo("o/hmoved", "hmoved")
add(HD, 1, "sana/ask-7304", verdict=CHANGES, statusCheckRollup=RED)
TICKETS["ASK-7304"] = tk("ASK-7304", "started", "In Progress", 400)
tries = [run_main(f"H4-{h}", ["--apply"], NOW + h * H) for h in (0, 1)]
holds("P53", "a requeue that moves the ticket posts the resume line itself: no second note, no alert, exit 0",
      (per_hour(tries, lambda run: [a[2] for a in ls_calls(run, ident="ASK-7304")]),
       sum(len(sink_calls(run, 1)) for _rc, run in tries), [r for r, _run in tries]),
      ([["requeue"], []], 0, [0, 0]))

# Round 4, minor: the held alert was keyed on PR and head only, so a second,
# different write failing at that head filed nothing.
REPOS.clear()
fresh_state("H5")
HE = repo("o/htwo", "htwo")
add(HE, 1, "sana/ask-7305")
TICKETS["ASK-7305"] = tk("ASK-7305", "backlog")
REVIEW_RC[0] = 1
tries = [run_main("H5-0", ["--apply"], NOW)]
REVIEW_RC[0] = 0
REPOS[HE]["verdict"][1] = CHANGES
WRITE_RC[("comment", HE, 1)] = (1, "HTTP 502: Bad Gateway")
tries += [run_main(f"H5-{h}", ["--apply"], NOW + h * H) for h in (1, 2)]
WRITE_RC.clear()
holds("P52", "a review that crashes, then a rework comment GitHub refuses, at one head: two alerts, "
             "and the comment's retry files no third",
      (per_hour(tries, lambda run: len(sink_calls(run, 1))), [r for r, _run in tries]), ([1, 1, 0], [2, 2, 2]))

REPOS.clear()
fresh_state("H6")
HF = repo("o/hsame", "hsame")
add(HF, 1, "sana/ask-7306", verdict=CHANGES, statusCheckRollup=RED)
TICKETS["ASK-7306"] = tk("ASK-7306", "started", "In Progress", 400)
WRITE_RC[("comment", HF, 1)] = (1, "HTTP 502: Bad Gateway")
tries = [run_main("H6-0", ["--apply"], NOW)]
WRITE_RC.clear()
LS_RC["requeue"] = REQ_FAIL
tries += [run_main(f"H6-{h}", ["--apply"], NOW + h * H) for h in (1, 2)]
LS_RC.clear()
holds("P52", "one rework at one head: the comment fails, then the requeue fails: an alert for each, none at hour 2",
      (per_hour(tries, lambda run: len(sink_calls(run, 1))), [r for r, _run in tries]), ([1, 1, 0], [2, 2, 0]))

# Round 4, minor: the docstring said a note Linear does not take is asked again;
# after a close it never is. Now it says so, and the alert carries what was lost.
REPOS.clear()
fresh_state("H7")
HG = repo("o/hclose", "hclose")
add(HG, 1, "fix/x-ask-7307", statusCheckRollup=RED)
TICKETS["ASK-7307"] = tk("ASK-7307", "started", "In Progress", 400)
LS_RC.update({"requeue": REQ_FAIL, "progress": NOTE_FAIL})
rc0, H7a = run_main("H7-0", ["--apply"], NOW)
del REPOS[HG]["prs"][1]  # GitHub took the close: the PR leaves the open list
rc1, H7b = run_main("H7-1", ["--apply"], NOW + H)
LS_RC.clear()
alert7 = " ".join(a[2] for a in sink_calls(H7a, 1))
holds("P54", "a close whose note does not land: closed, exit 2, one alert naming the ticket and carrying the "
             "resume line; the next run asks no note",
      ([a[2] for a in gh_writes(H7a, HG, 1)], rc0, len(sink_calls(H7a, 1)), "ASK-7307" in alert7,
       f"resume from branch fix/x-ask-7307 at {head_of(HG, 1)[:8]}" in alert7, ls_calls(H7b), rc1),
      (["close"], 2, 1, True, True, [], 0))
holds("P54", "... and the alert names the write that did not take (the note), not the close, which took",
      ("its close-requeue did not take" in alert7, "(requeue and note)" in alert7), (False, True))

# ================================================================ across every run
print("-- across every run")
holds("P18", "no argv sent in any run asks GitHub to delete a branch or a ref",
      [a for a in SENT if a[:1] == ["gh"] and ({"--delete-branch", "-d", "DELETE"} & set(a) or any("git/refs" in x for x in a))],
      [])
try:
    po.gh_write(["pr", "close", "1", "-R", "o/fx", "--delete-branch"])
    refused = "sent"
except SystemExit as exc:
    refused = "REFUSED" if str(exc.code).startswith("REFUSED") else str(exc.code)
holds("P18", "gh_write refuses a close that deletes the branch, before any subprocess", (refused, BLOCKED), ("REFUSED", []))
holds("P30", "no temp state file is left behind in any state dir", [str(p) for p in TMP.glob("state*/*.tmp.*")], [])
holds("P30", "the one state writer is save_state(): temp file plus rename",
      ("os.replace(tmp, path)" in SRC, len(re.findall(r"\.write_text\(json\.dumps\(state", SRC))), (True, 1))

# ================================================================ coverage
print("-- coverage: every promise-shaped line of pr-owner.py has a row")
KEY = re.compile(r"\bnever\b|at most|\bonly\b|undo|refuse|\bexits? [0-9]|no write|writes nothing|nothing else"
                 r"|\balways\b|\bonce\b", re.I)
anchors = [a for p in PROMISES.values() for a in p["anchors"]] + [a for a, _why in EXEMPT]
stale = [a for a in anchors if a not in SRC]
uncovered = [f"{i}: {ln.strip()[:90]}" for i, ln in enumerate(SRC.splitlines(), 1)
             if KEY.search(ln) and not any(a in ln for a in anchors)]
unrun = [pid for pid, p in PROMISES.items() if not p["ran"]]
for name, got in (("every anchor is still in pr-owner.py (a changed promise needs its row changed)", stale),
                  ("every promise-shaped line carries a row's anchor or an exemption", uncovered),
                  ("every promise row ran at least one assertion", unrun)):
    ok = got == []
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": {got}"))
    if not ok:
        FAILS.append(name)

shutil.rmtree(TMP, ignore_errors=True)
n_checks = sum(p["ran"] for p in PROMISES.values())
print()
print(f"{len(PROMISES)} promises, {n_checks} assertions")
if FAILS:
    print(f"FAIL: {len(FAILS)} check(s): " + "; ".join(FAILS))
    sys.exit(1)
print("PASS")
