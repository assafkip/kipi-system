#!/usr/bin/env python3
"""test-heartbeat.py -- the outside heartbeat fires on a starved or a missing consumer (ASK-3947).

RED FIRST. On a tree with no heartbeat.py (main at c6734f01) this prints RED and
exits 1: the 16 real nightly "0 written, 8 failed" alert-triage passes
(fixtures/heartbeat/alert-triage-zero-written.txt, 2026-10-23 to 2026-11-07, queue
701 to 1269) replay into nothing, because nothing off the Mac reads them.

GREEN means:
  * starved fires on the 2nd starved run in a row, and not on the 1st;
  * a row older than 2 periods fires missing, and one younger does not;
  * a listed job that never reported fires missing 2 periods after `since`;
  * a healthy series fires nothing, and a good run resets the streak;
  * every listed producer calls heartbeat, the plist passes --heartbeat, and the
    drafter's real main() emits only when asked;
  * an alert-triage night whose model half writes 0 is starved, whatever the
    no-model pre-pass closed (PR #642 round 2), through the real emit and evaluate;
  * fleet-health mirrors heartbeat-red issues, and a blind gh is a finding.
MUTANTS: the same invariant cases run against a copy of heartbeat.py with the
starved rule removed, the missing rule removed, and the queue term of
is_starved removed (PR #631 R1). Each must go red. A
test that stays green on a mutant could not have failed.

NEVER A LIVE PATH. Every emit gets a scratch state dir and a scratch repo root,
every gh call goes through an injected fake, and KIPI_HEARTBEAT_DIR and
KIPI_HEARTBEAT_GH are pointed at scratch before anything loads, so a call this file
forgot to inject still cannot write ~/.config/kipi or reach GitHub.

Run: python3 q-system/.q-system/scripts/test/test-heartbeat.py   (exit 0 = pass)
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import plistlib
import re
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
REPO = SCRIPTS.parents[2]
UNDER_TEST = Path(os.environ.get("KIPI_HEARTBEAT_UNDER_TEST") or SCRIPTS / "heartbeat.py")
FIXTURE = HERE / "fixtures" / "heartbeat" / "alert-triage-zero-written.txt"
LINE_RE = re.compile(r"^alert-triage (\S+): triage pass: (\d+) written, (\d+) skipped, "
                     r"(\d+) failed; (\d+) still queued")

SANDBOX = Path(tempfile.mkdtemp(prefix="test-heartbeat-"))
os.environ["KIPI_HEARTBEAT_DIR"] = str(SANDBOX / "default-state")
os.environ["KIPI_HEARTBEAT_GH"] = str(SANDBOX / "no-such-gh")
os.environ["KIPI_STATE_DIR"] = str(SANDBOX / "kipi-state")

FAILS: list[str] = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(name)


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Proc:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


class FakeGh:
    """Records every argv. `list_out` answers `gh issue list`."""

    def __init__(self, rc=0, list_out="[]", raise_exc=None):
        self.calls, self.rc, self.list_out, self.raise_exc = [], rc, list_out, raise_exc

    def __call__(self, argv, **_kw):
        self.calls.append(list(argv))
        if self.raise_exc:
            raise self.raise_exc
        if argv[1:3] == ["issue", "list"]:
            return Proc(self.rc, self.list_out)
        return Proc(self.rc)


def at(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def scratch_root() -> Path:
    root = Path(tempfile.mkdtemp(dir=SANDBOX, prefix="repo-"))
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "heartbeat.yml").write_text("name: Heartbeat\n")
    return root


def fixture_runs() -> list[tuple]:
    runs = []
    for line in FIXTURE.read_text().splitlines():
        m = LINE_RE.match(line)
        if m:
            when, written, _skipped, failed, queue = m.groups()
            runs.append((at(when), int(written) + int(failed), int(written), int(queue)))
    return runs


def core_cases(hb) -> list[str]:
    """The invariant. Returns the names of the cases that failed (empty = all hold)."""
    bad: list[str] = []

    def expect(name, cond):
        if not cond:
            bad.append(name)

    table = {"jobs": {"linear-alert-triage": {"period_hours": 24, "since": "2026-10-22"},
                      "linear-dor": {"period_hours": 24, "since": "2026-11-01"}}}
    runs = fixture_runs()
    expect("the fixture holds the 16 real nightly passes", len(runs) == 16)

    # The 16 real zero-written passes.
    state, root, gh = SANDBOX / f"s-{id(hb)}", scratch_root(), FakeGh()
    rows = [hb.emit("linear-alert-triage", n_in, done, queue=q, state_dir=state,
                    repo_root=root, run=gh, now=when)["row"] for when, n_in, done, q in runs]
    expect("every replayed run wrote a row", all(rows))
    if not all(rows):
        return bad
    expect("the streak counts each starved night", [r["starved_streak"] for r in rows]
           == list(range(1, 17)))
    first = hb.evaluate({"linear-alert-triage": rows[0]}, table, runs[0][0] + timedelta(hours=1))
    expect("one starved night does not fire", not [v for v in first if v["kind"] == "starved"])
    second = hb.evaluate({"linear-alert-triage": rows[1]}, table, runs[1][0] + timedelta(hours=1))
    expect("the second starved night fires starved",
           [v["kind"] for v in second if v["job"] == "linear-alert-triage"] == ["starved"])
    last = hb.evaluate({"linear-alert-triage": rows[-1]}, table, runs[-1][0] + timedelta(hours=1))
    expect("the full replay fires starved and names 16 runs",
           any(v["kind"] == "starved" and "16 runs" in v["detail"] for v in last))

    # The drafter's 2026-11-07 run: in 1, done 0. Once is not an alarm; twice is.
    state = SANDBOX / f"d-{id(hb)}"
    t0 = at("2026-11-07T11:00:20Z")
    r1 = hb.emit("linear-dor", 1, 0, queue=1, state_dir=state, publish=False, now=t0)["row"]
    def dor_kinds(rows_, when):
        return [v["kind"] for v in hb.evaluate(rows_, table, when) if v["job"] == "linear-dor"]

    expect("the drafter's one failed night does not fire",
           dor_kinds({"linear-dor": r1}, t0 + timedelta(hours=1)) == [])
    r2 = hb.emit("linear-dor", 1, 0, queue=1, state_dir=state, publish=False,
                 now=t0 + timedelta(days=1))["row"]
    expect("a second failed night fires starved",
           dor_kinds({"linear-dor": r2}, t0 + timedelta(days=1, hours=1)) == ["starved"])
    r3 = hb.emit("linear-dor", 2, 2, queue=0, state_dir=state, publish=False,
                 now=t0 + timedelta(days=2))["row"]
    expect("a good run resets the streak", r3["starved_streak"] == 0)
    expect("a healthy row fires nothing",
           dor_kinds({"linear-dor": r3}, t0 + timedelta(days=2, hours=1)) == [])

    # An errored run did no work either.
    state = SANDBOX / f"e-{id(hb)}"
    e1 = hb.emit("linear-dor", 0, 0, error="linear-unreachable", state_dir=state,
                 publish=False, now=t0)["row"]
    e2 = hb.emit("linear-dor", 0, 0, error="linear-unreachable", state_dir=state,
                 publish=False, now=t0 + timedelta(days=1))["row"]
    expect("an errored run counts as starved", (e1["starved_streak"], e2["starved_streak"]) == (1, 2))
    idle = hb.emit("linear-dor", 0, 0, state_dir=SANDBOX / f"i-{id(hb)}", publish=False, now=t0)["row"]
    expect("an empty queue with no error is not starved", idle["starved_streak"] == 0)
    # PR #631 R1 major: nothing taken on, 32 still queued, twice. That is starved.
    state = SANDBOX / f"q-{id(hb)}"
    hb.emit("linear-dor", 0, 0, queue=32, state_dir=state, publish=False, now=t0)
    q2 = hb.emit("linear-dor", 0, 0, queue=32, state_dir=state, publish=False,
                 now=t0 + timedelta(days=1))["row"]
    expect("a night that did nothing while 32 waited is starved, twice fires",
           (q2["starved_streak"], dor_kinds({"linear-dor": q2}, t0 + timedelta(days=1, hours=1)))
           == (2, ["starved"]))

    # Missing: 2 periods is the line.
    now = at("2026-11-10T12:00:00Z")
    old = dict(r3, at=hb._iso(now - timedelta(hours=49)), starved_streak=0)
    young = dict(r3, at=hb._iso(now - timedelta(hours=47)), starved_streak=0)
    expect("a row 49h old on a 24h job fires missing",
           [v["kind"] for v in hb.evaluate({"linear-dor": old, "linear-alert-triage": young}, table, now)
            if v["job"] == "linear-dor"] == ["missing"])
    expect("a row 47h old does not",
           not [v for v in hb.evaluate({"linear-dor": young, "linear-alert-triage": young}, table, now)
                if v["job"] == "linear-dor"])
    never = hb.evaluate({}, table, now)
    expect("a listed job that never reported fires missing after 2 periods",
           sorted(v["job"] for v in never if v["kind"] == "missing")
           == ["linear-alert-triage", "linear-dor"])
    fresh = {"jobs": {"linear-dor": {"period_hours": 24, "since": "2026-11-10"}}}
    expect("a job listed today is not missing yet", not hb.evaluate({}, fresh, now))
    return bad


print("test-heartbeat.py")
if not UNDER_TEST.is_file():
    print(f"RED: {UNDER_TEST} does not exist on this tree. Replaying the "
          f"{len(fixture_runs())} real starved nights fires nothing; no reader exists.")
    sys.exit(1)

hb = load(UNDER_TEST, "heartbeat")

print("-- the invariant")
core = core_cases(hb)
for name in core:
    FAILS.append(name)
    print(f"  FAIL {name}")
check("every invariant case holds", core, [])

print("-- the published row")
gh = FakeGh()
root = scratch_root()
res = hb.emit("linear-dor", 3, 1, queue=7, state_dir=SANDBOX / "pub", repo_root=root, run=gh,
              now=at("2026-11-08T11:00:00Z"))
check("emit publishes", res["published"], "published")
check("one gh call", len(gh.calls), 1)
call = gh.calls[0] if gh.calls else ["", "", "", "", "", "{}"]
check("it sets the job's own variable", call[1:4], ["variable", "set", "KIPI_HB_LINEAR_DOR"])
body = json.loads(call[call.index("--body") + 1]) if "--body" in call else {}
check("the body is the row", (body.get("job"), body.get("in"), body.get("done"), body.get("queue")),
      ("linear-dor", 3, 1, 7))
check("the local ledger has the same row",
      json.loads((SANDBOX / "pub" / "linear-dor.jsonl").read_text().splitlines()[-1]), body)
rows, bad = hb.rows_from_vars({"KIPI_HB_LINEAR_DOR": call[call.index("--body") + 1]
                               if "--body" in call else "", "OTHER": "x"})
check("the reader reads back what emit published", (list(rows), bad), (["linear-dor"], []))

print("-- emit never kills its consumer")
for label, fake, want in (("gh exits 1", FakeGh(rc=1), "failed: exit 1"),
                          ("gh raises", FakeGh(raise_exc=OSError("boom")), "failed: OSError")):
    res = hb.emit("linear-dor", 1, 1, state_dir=SANDBOX / "robust", repo_root=root, run=fake)
    check(f"{label}: emit returns {want}", res["published"], want)
check("the rows are still in the local ledger",
      len((SANDBOX / "robust" / "linear-dor.jsonl").read_text().splitlines()), 2)
bare = Path(tempfile.mkdtemp(dir=SANDBOX))
gh = FakeGh()
res = hb.emit("linear-dor", 1, 1, state_dir=SANDBOX / "bare", repo_root=bare, run=gh)
check("a repo without the workflow does not publish", (res["published"].startswith("skipped"),
      gh.calls), (True, []))
check("a bad job name returns, never raises", hb.emit("Bad Name!", 1, 1, publish=False)["row"], None)
row = hb.emit("linear-dor", 0, 0, error="Linear <b>down</b>: token=abc", state_dir=SANDBOX / "err",
              publish=False)["row"]
check("caller text becomes the class 'other', never published", row["error"], "other")
row = hb.emit("linear-dor", 0, 0, error="linear-unreachable", state_dir=SANDBOX / "err",
              publish=False)["row"]
check("a known class is kept", row["error"], "linear-unreachable")

print("-- the reader on GitHub")
rows, bad = hb.rows_from_vars({"KIPI_HB_JUNK": "not json", "SECRET_THING": "topsecret"})
check("a junk KIPI_HB_ value is unreadable", [v["kind"] for v in bad], ["unreadable"])
check("a row for an unlisted job is unlisted",
      [v["kind"] for v in hb.evaluate({"stray": {"job": "stray", "at": "2026-11-08T00:00:00Z"}},
                                       {"jobs": {}}, at("2026-11-08T01:00:00Z"))], ["unlisted"])
jobs_file = SANDBOX / "jobs.json"
jobs_file.write_text(json.dumps({"jobs": {"linear-dor": {"period_hours": 24, "since": "2026-11-08"}}}))
os.environ["KIPI_HB_VARS_T"] = json.dumps({"SECRET_THING": "topsecret",
                                           "KIPI_HB_LINEAR_DOR": json.dumps(body)})
out = io.StringIO()
with redirect_stdout(out):
    rc = hb.main(["check", "--vars-env", "KIPI_HB_VARS_T", "--jobs", str(jobs_file),
                  "--now", "2026-11-08T12:00:00Z"])
check("check exits 0", rc, 0)
check("check never prints a variable that is not a heartbeat", "topsecret" in out.getvalue(), False)

print("-- issues: one per (job, kind), closed when green")
listed = json.dumps([{"number": 5, "title": "heartbeat-red: linear-dor starved"},
                     {"number": 6, "title": "heartbeat-red: linear-dor missing"},
                     {"number": 7, "title": "something else"}])
gh = FakeGh(list_out=listed)
viol = [{"job": "linear-dor", "kind": "starved", "detail": "d"},
        {"job": "other-job", "kind": "missing", "detail": "d"}]
check("filing exits 0", hb.file_issues(viol, {"jobs": {}}, run=gh), 0)
creates = [c for c in gh.calls if c[1:3] == ["issue", "create"]]
closes = [c for c in gh.calls if c[1:3] == ["issue", "close"]]
check("one new issue, for the new violation", [c[c.index("--title") + 1] for c in creates],
      ["heartbeat-red: other-job missing"])
check("it carries the label", all("heartbeat-red" in c for c in creates), True)
check("the green one closes, the unrelated one is untouched", [c[3] for c in closes], ["6"])
gh = FakeGh(rc=1)
check("a gh that cannot list makes the run red", hb.file_issues(viol, {"jobs": {}}, run=gh), 1)
# PR #643 round 1, major 1: install-plist.sh --missing (what the skeleton sync calls)
# never rewrites an installed job, so a job whose installed plist predates --heartbeat
# runs green on the Mac and reads missing off it. The Action named only launchctl and
# the .out log, both of which show a healthy job. It has to name the stale plist and
# the reinstall.
real_table = hb.load_table(REPO / "q-system" / ".q-system" / "heartbeat-jobs.json")
miss = hb.issue_body({"job": "linear-alert-triage", "kind": "missing", "detail": "d"}, real_table)
check("a missing issue names the stale installed plist and its reinstall",
      ("~/Library/LaunchAgents/com.kipi.linear-alert-triage.plist" in miss,
       "install-plist.sh com.kipi.linear-alert-triage" in miss, "--heartbeat" in miss),
      (True, True, True))
# ASK-3987 (PR #643 round 2, minor 2). Diffing the installed plist against the RAW
# template drowns the one fact that matters: a healthy pinned install differs from
# it on 13 lines (4 placeholders filled, the kipi-job-pinned.sh pair added). The
# Action must compare against a --render-only copy, as fleet-health plist drift does.
check("the missing Action diffs against a --render-only copy, not the raw template",
      ("install-plist.sh com.kipi.linear-alert-triage --render-only" in miss,
       "the template in" in miss),
      (True, False))
# PR #652 round 1: render from the primary checkout, and compare the argv, not
# the raw files (where --heartbeat lives, without the comment noise).
check("...from the primary checkout, comparing ProgramArguments",
      ("~/projects/kipi-system" in miss, "plutil -extract ProgramArguments" in miss),
      (True, True))
check("...and opens nothing", [c for c in gh.calls if c[1:3] == ["issue", "create"]], [])

print("-- wiring: every listed producer emits, and the reader is scheduled")
table = json.loads((REPO / "q-system" / ".q-system" / "heartbeat-jobs.json").read_text())
for job, spec in sorted(table["jobs"].items()):
    src = (REPO / spec["producer"]).read_text() if (REPO / spec["producer"]).is_file() else ""
    check(f"{job}: the producer exists and calls heartbeat",
          bool(src) and "heartbeat" in src and f'"{job}"' in src, True)
wf = (REPO / ".github" / "workflows" / "heartbeat.yml").read_text()
for needle in ("schedule:", "cron:", "issues: write", "toJSON(vars)",
               "heartbeat.py check --file-issues"):
    check(f"the workflow carries {needle!r}", needle in wf, True)
# EVERY listed job's plist passes --heartbeat (ASK-3965): a producer that emits only
# when asked, run by a plist that never asks, is the silent job this table exists for.
for job, spec in sorted(table["jobs"].items()):
    tmpl_path = SCRIPTS / f"{spec.get('launchd', '')}.plist"
    tmpl = tmpl_path.read_text() if tmpl_path.is_file() else ""
    rendered = tmpl.replace("__KIPI_REPO__", "/r").replace("__HOME__", "/h").encode()
    try:
        args = plistlib.loads(rendered)["ProgramArguments"]
    except Exception as exc:  # noqa: BLE001 - a parse failure IS the finding
        args = [f"unparseable: {type(exc).__name__}"]
    check(f"{job}: its plist parses strictly and passes --heartbeat",
          "--heartbeat" in (args[-1] if args else "").split(), True)

print("-- wiring: the alert-triage pass emits only when asked, and only when it writes")
tri = load(SCRIPTS / "linear-alert-triage.py", "triage_under_test")
tbeats: list = []
tri.heartbeat = lambda n_in, n_done, queue=None, error=None: tbeats.append((n_in, n_done, queue, error))
tri.lane_pool = lambda _ls: ([{"identifier": f"ASK-{n}"} for n in range(5)], [])
tri.run_prepass = lambda _ls, pool, _apply, _pr=None: (pool, __import__("collections").Counter())
tri._prepass_part = lambda _pre, _apply: ""
tri.write_run_evidence = lambda _line: None
tri._triage_one = lambda _ls, issue, _d, _apply: "written" if issue["identifier"] == "ASK-0" else "skipped"
with redirect_stdout(io.StringIO()):
    tri.run_triage(None, 2, True)
check("alert-triage without the flag emits nothing", tbeats, [])
with redirect_stdout(io.StringIO()):
    tri.run_triage(None, 2, False, beat=True)
check("alert-triage dry run emits nothing, flag or not", tbeats, [])
with redirect_stdout(io.StringIO()):
    tri.run_triage(None, 2, True, beat=True)
check("alert-triage with --heartbeat emits in 2, done 1, queue 3", tbeats, [(2, 1, 3, None)])
# The no-model pre-pass's closes are NOT model work (PR #642 round 2): 3 examined and
# 2 closed beside 1 written still reports in 2, done 1. Counting them in done kept
# done above 0 on a model-silent night, and done is is_starved's only input.
tbeats.clear()
tri.run_prepass = lambda _ls, pool, _apply, _pr=None: (pool, __import__("collections").Counter(attempted=3, closed=2))
with redirect_stdout(io.StringIO()):
    tri.run_triage(None, 2, True, beat=True)
check("pre-pass closes stay out of the row: in 2, done 1", tbeats, [(2, 1, 3, None)])
tbeats.clear()
with redirect_stdout(io.StringIO()):
    tri.run_triage(None, 2, True, beat=True, prepass_only=True)
check("a pre-pass-only drain never emits into the nightly job's ledger", tbeats, [])
def _down(_ls):
    raise RuntimeError("linear is down")
tri.lane_pool = _down
try:
    with redirect_stdout(io.StringIO()):
        tri.run_triage(None, 2, True, beat=True)
except RuntimeError:
    pass
check("an outage night emits an errored row, not silence", tbeats, [(0, 0, None, "linear-unreachable")])
check("the parser carries --heartbeat",
      tri.build_parser().parse_args(["run", "--apply", "--heartbeat"]).heartbeat, True)

print("-- the model half's silence fires starved, whatever the pre-pass closed (PR #642 round 2)")
# The 16-night scar, replayed through the real wrapper, emit and evaluate: the pool at
# 1269, the no-model pre-pass closing 12, every model decision failing, two nights.
# Round 1 summed the closes into done, so done read 12, the streak stayed 0 and the
# check stayed green on exactly the failure this heartbeat exists to catch.
from collections import Counter as _Counter
mh = load(SCRIPTS / "linear-alert-triage.py", "triage_model_half")
mh_state = SANDBOX / "model-half"


class _HbShim:
    """The real heartbeat.emit, forced onto a sandbox ledger and never published."""

    def __init__(self):
        self.now, self.state = None, mh_state

    def emit(self, job, n_in, n_done, **kw):
        kw.update(state_dir=self.state, publish=False, now=self.now)
        return hb.emit(job, n_in, n_done, **kw)


mh_shim = _HbShim()
mh_real_load = mh._load
mh._load = lambda name, filename: mh_shim if name == "heartbeat" else mh_real_load(name, filename)
mh.lane_pool = lambda _ls: ([{"identifier": f"ASK-{n}"} for n in range(1269)], [])
mh.run_prepass = lambda _ls, pool, _apply, _pr=None: (pool[12:], _Counter(attempted=12, closed=12))
mh.write_run_evidence = lambda _line: None  # the live ~/.config/kipi/*.out, never from a test
mh_table = hb.load_table(REPO / "q-system" / ".q-system" / "heartbeat-jobs.json")
mh_kinds = []
for night in (at("2026-11-09T10:30:00Z"), at("2026-11-10T10:30:00Z")):
    mh_shim.now = night
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        mh_rc = mh.run_triage(None, 8, True, decider=lambda _issue: None, beat=True)
    # No ledger is a FAIL line below, not a crash that skips every later check.
    mh_ledger = mh_state / "linear-alert-triage.jsonl"
    mh_rows = ([json.loads(x) for x in mh_ledger.read_text().splitlines()]
               if mh_ledger.is_file() else [])
    mh_kinds.append([v["kind"] for v in hb.evaluate(
        {"linear-alert-triage": mh_rows[-1]} if mh_rows else {}, mh_table, night + timedelta(hours=1))
        if v["job"] == "linear-alert-triage"])
check("a model-silent pass exits red", mh_rc, 1)
check("night 2's row is the model half: in 8, done 0, queue 1249, streak 2",
      [(r.get("in"), r.get("done"), r.get("queue"), r.get("starved_streak")) for r in mh_rows],
      [(8, 0, 1249, 1), (8, 0, 1249, 2)])
check("the check fires nothing on night 1 and starved on night 2", mh_kinds, [[], ["starved"]])

# PR #643 round 1, major 2: run_prepass drops an alert from the pool BEFORE its close,
# so when it takes the whole pool and every close fails the model batch is empty. The
# row read in 0, done 0, queue 0, a quiet night, while the pass exited 1. A failed
# close stays open for tomorrow, so it is work that waits: queue counts it.
mh_shim.state = SANDBOX / "prepass-failed"
mh.lane_pool = lambda _ls: ([{"identifier": f"ASK-{n}"} for n in range(5)], [])
mh.run_prepass = lambda _ls, pool, _apply, _pr=None: ([], _Counter(attempted=5, failed=5))
pf_rows, pf_kinds, pf_rcs = [], [], []
for night in (at("2026-11-20T10:30:00Z"), at("2026-11-21T10:30:00Z")):
    mh_shim.now = night
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        pf_rcs.append(mh.run_triage(None, 8, True, decider=lambda _issue: None, beat=True))
    pf_ledger = mh_shim.state / "linear-alert-triage.jsonl"
    pf_rows = ([json.loads(x) for x in pf_ledger.read_text().splitlines()]
               if pf_ledger.is_file() else [])
    pf_kinds.append([v["kind"] for v in hb.evaluate(
        {"linear-alert-triage": pf_rows[-1]} if pf_rows else {}, mh_table, night + timedelta(hours=1))
        if v["job"] == "linear-alert-triage"])
check("failed pre-pass closes are queued: in 0, done 0, queue 5, streak 1 then 2",
      [(r.get("in"), r.get("done"), r.get("queue"), r.get("starved_streak")) for r in pf_rows],
      [(0, 0, 5, 1), (0, 0, 5, 2)])
check("...so two such nights fire starved, as the exit code already says", (pf_rcs, pf_kinds),
      ([1, 1], [[], ["starved"]]))

# ASK-3986 (PR #643 round 2, minor 1). A pre-pass close that SKIPS because the
# alert could not be re-read leaves it open for tomorrow, exactly like a failed
# close, so it is queued work. A skip because the ticket is not an alert (or was
# promoted mid-close) is terminal for this lane and is not. Before this, every
# skip read as done: a night whose every close skipped on a re-read read queue 0
# and exited 0, so both channels were green on a lane doing nothing.
#
# 1. The real do_close says which kind of skip it is.
class _FakeLs:
    def __init__(self, issue=None, fail=False):
        self.issue, self.fail = issue, fail

    def graphql(self, _q, _v):
        if self.fail:
            raise RuntimeError("linear timed out")
        return {"issue": self.issue}


_ALERT = {"identifier": "ASK-9", "description": "x\n<!-- kipi-alert-fingerprint: 0a1b2c3d4e5f -->"}
with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    _o_reread = tri.do_close(_FakeLs(fail=True), _ALERT, "r", True)
    _o_notalert = tri.do_close(_FakeLs(issue={"description": "a real spec"}), _ALERT, "r", True)
check("a close that could not re-read the alert skips and WAITS (it stays open)",
      (_o_reread.wrote, getattr(_o_reread, "waits", None)), (False, True))
check("a close of a ticket that is not an alert skips and does NOT wait (terminal here)",
      (_o_notalert.wrote, getattr(_o_notalert, "waits", None)), (False, False))

# 2. The real run_prepass counts the waiting skips apart. Only its inputs are faked:
# every alert has a subject that ended, so every one is a close attempt.
pp = load(SCRIPTS / "linear-alert-triage.py", "triage_prepass_split")
pp.alert_subject = lambda _issue: {"shape": "fixture"}
pp.duplicates_by_kept = lambda _pool: {}
pp._why_subjects_ended = lambda *_a, **_k: ("the subject ended.", "ended")
pp.read_cursor = lambda: None
pp.write_cursor = lambda _i: None
_pool5 = [dict(_ALERT, identifier=f"ASK-{n}", createdAt="2026-11-01T00:00:00Z") for n in range(5)]
with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    _left, _tally = pp.run_prepass(_FakeLs(fail=True), _pool5, True, pr_state=lambda *_a: None)
check("run_prepass counts every re-read skip as waiting: 5 skipped, 5 waiting",
      (_tally["skipped"], _tally["skipped_waits"]), (5, 5))

# 3. Through the real emit and evaluate, two nights of re-read skips fire starved;
# two nights of not-an-alert skips stay green.
_saved = (mh_shim.state, mh.lane_pool, mh.run_prepass)


def _two_nights(state, counter):
    mh_shim.state = state
    mh.lane_pool = lambda _ls: ([{"identifier": f"ASK-{n}"} for n in range(5)], [])
    mh.run_prepass = lambda _ls, pool, _apply, _pr=None: ([], counter)
    rows, kinds = [], []
    for night in (at("2026-11-24T10:30:00Z"), at("2026-11-25T10:30:00Z")):
        mh_shim.now = night
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            mh.run_triage(None, 8, True, decider=lambda _issue: None, beat=True)
        led = state / "linear-alert-triage.jsonl"
        rows = [json.loads(x) for x in led.read_text().splitlines()] if led.is_file() else []
        kinds.append([v["kind"] for v in hb.evaluate(
            {"linear-alert-triage": rows[-1]} if rows else {}, mh_table, night + timedelta(hours=1))
            if v["job"] == "linear-alert-triage"])
    return [(r.get("queue"), r.get("starved_streak")) for r in rows], kinds


check("two nights of re-read skips are queued and fire starved on night 2",
      _two_nights(SANDBOX / "prepass-reread", _Counter(attempted=5, skipped=5, skipped_waits=5)),
      ([(5, 1), (5, 2)], [[], ["starved"]]))
check("two nights of not-an-alert skips stay green: nothing waits",
      _two_nights(SANDBOX / "prepass-notalert", _Counter(attempted=5, skipped=5))[1],
      [[], []])
# The checks below read the failed-close setup above, so it goes back as it was.
mh_shim.state, mh.lane_pool, mh.run_prepass = _saved

# PR #643 round 1, minor: the wrapper's own _load was unguarded. An unloadable
# heartbeat.py killed the pass after its Linear writes (the exit code never ran), and
# on an outage night it replaced the Linear error in the launchd log with its own.
def _no_heartbeat(name, filename):
    if name == "heartbeat":
        raise FileNotFoundError("heartbeat.py unreadable")
    return mh_real_load(name, filename)


mh._load = _no_heartbeat
try:
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        nb_rc = mh.run_triage(None, 8, True, decider=lambda _issue: None, beat=True)
except Exception as exc:  # noqa: BLE001 - the raise IS the finding
    nb_rc = type(exc).__name__
check("an unloadable heartbeat.py does not cost the pass: it still exits 1", nb_rc, 1)


def _linear_down(_ls):
    raise RuntimeError("linear is down")


mh.lane_pool = _linear_down
try:
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        mh.run_triage(None, 8, True, decider=lambda _issue: None, beat=True)
    nb_raised = None
except Exception as exc:  # noqa: BLE001 - which exception surfaces IS the check
    nb_raised = type(exc).__name__
check("...and an outage still surfaces the Linear error, not the heartbeat's", nb_raised,
      "RuntimeError")

print("-- emit coerces queue before it decides (PR #631 round 2, minor 1)")
cq, tc = SANDBOX / "coerce", datetime(2026, 11, 8, 10, 30, tzinfo=timezone.utc)
hb.emit("linear-dor", 0, 0, queue="32", state_dir=cq, publish=False, now=tc)
# Read through .get, so a regression is a FAIL line here, not a crash that skips
# every check after it (PR #642 round 1).
rq = (hb.emit("linear-dor", 0, 0, queue="32", state_dir=cq, publish=False,
              now=tc + timedelta(hours=24)) or {}).get("row") or {}
check("a string queue twice is a starved streak of 2, and the row says 32",
      (rq.get("starved_streak"), rq.get("queue")), (2, 32))

print("-- wiring: the drafter's real main() emits only when asked")
sys.path.insert(0, str(SCRIPTS))
dor = load(SCRIPTS / "linear-dor-drafter.py", "dor_under_test")
beats: list = []


class TinyLinear:
    def __init__(self, down=False):
        self.down = down

    def graphql(self, _q, _v):
        if self.down:
            raise RuntimeError("down")
        return {"teams": {"nodes": [{"id": "t"}]}}


dor.STATE = SANDBOX / "dor-state.json"
dor.notify = lambda *_a, **_k: None
dor.report_failures = lambda *_a, **_k: "none"
dor.draft_one = lambda issue, timeout, *_a: (None, "claude exited rc=1 with 63 chars of output")
dor.fetch_draftable = lambda _ls, _tid: [{"id": "x", "identifier": "ASK-1", "title": "t",
                                          "description": "", "project": None,
                                          "state": {"name": "Backlog", "type": "backlog"}}]
dor.heartbeat = lambda n_in, n_done, queue=None, error=None: beats.append((n_in, n_done, error))
real_argv = sys.argv
try:
    dor._linear = lambda: TinyLinear()
    sys.argv = ["linear-dor-drafter.py", "--limit", "1", "--apply"]
    with redirect_stdout(io.StringIO()):
        dor.main()
    check("without --heartbeat nothing is emitted", beats, [])
    sys.argv = ["linear-dor-drafter.py", "--limit", "1", "--apply", "--heartbeat"]
    with redirect_stdout(io.StringIO()):
        dor.main()
    check("with --heartbeat a failed night emits in 1, done 0", beats, [(1, 0, None)])
    beats.clear()
    dor._linear = lambda: TinyLinear(down=True)
    with redirect_stdout(io.StringIO()):
        dor.main()
    check("Linear down at start emits an errored run", beats, [(0, 0, "linear-unreachable")])
finally:
    sys.argv = real_argv

print("-- fleet-health mirrors heartbeat-red into Linear")
fh = load(SCRIPTS / "fleet-health-daily.py", "fh_under_test")
ids = {d["id"]: d for d in fh.DETECTORS}
check("the heartbeat-red detector is registered to file", ids.get("heartbeat-red", {}).get("action"),
      "file_issue")
two = json.dumps([{"number": 11, "title": "heartbeat-red: linear-dor starved", "url": "u",
                   "updatedAt": "t"}, {"number": 12, "title": "heartbeat-red: x missing",
                                       "url": "u", "updatedAt": "t"}])
# gh_dirs is a scratch dir holding a stub `gh`, so _find_gh resolves without a
# real gh on the runner; the injected `run` means the stub is never executed.
stub_dir = SANDBOX / "gh-bin"
stub_dir.mkdir()
(stub_dir / "gh").write_text("#!/bin/sh\nexit 99\n")
(stub_dir / "gh").chmod(0o755)
fake = FakeGh(list_out=two)
found = fh.heartbeat_red_findings(repo_root=root, run=fake, gh_dirs=[str(stub_dir)])
check("one finding per open issue", [f["subject"] for f in found],
      ["heartbeat-red-11", "heartbeat-red-12"])
check("the finding title names the job and kind", found[0]["title"].startswith(
      "heartbeat-red: linear-dor starved") if found else False, True)
check("a gh that fails is a blind finding, never zero",
      [f["subject"] for f in fh.heartbeat_red_findings(repo_root=root, run=FakeGh(rc=1),
                                                       gh_dirs=[str(stub_dir)])],
      ["heartbeat-red-blind"])
check("a repo without the workflow is not asked", fh.heartbeat_red_findings(repo_root=bare, run=fake), [])

print("-- a copy at a shallow path still imports (validate on PR #631: /tmp/x on Linux)")
shallow = Path(tempfile.mkdtemp(dir=SANDBOX)) / "heartbeat.py"
shallow.write_text(UNDER_TEST.read_text().replace(
    "REPO_ROOT = HERE.parents[2] if len(HERE.parents) > 2 else HERE",
    "REPO_ROOT = HERE.parents[2] if len(HERE.parents) > 99 else HERE"))
check("the root falls back instead of raising when parents run out",
      str(load(shallow, "heartbeat_shallow").REPO_ROOT), str(shallow.parent.resolve()))

print("-- mutants: the invariant must go red without each rule")
src = UNDER_TEST.read_text()
for label, needle, swap in (
        ("starved rule removed", "        if streak >= STARVED_RUNS:\n", "        if False:\n"),
        ("missing rule removed", "        if age > limit:\n", "        if False:\n"),
        ("queue term removed", "(queue or 0) > 0 or ", "")):
    check(f"mutant anchor present once: {label}", src.count(needle), 1)
    mutant = SANDBOX / f"mutant-{label.split()[0]}.py"
    mutant.write_text(src.replace(needle, swap, 1))
    broken = core_cases(load(mutant, f"mutant_{label.split()[0]}"))
    check(f"the invariant goes red with the {label}", bool(broken), True)

print()
if FAILS:
    print(f"FAIL: {len(FAILS)} check(s): " + "; ".join(FAILS))
    sys.exit(1)
print("PASS")
