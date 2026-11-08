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
  * fleet-health mirrors heartbeat-red issues, and a blind gh is a finding.
MUTANTS: the same invariant cases run against a copy of heartbeat.py with the
starved rule removed, then with the missing rule removed. Each must go red. A
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
from contextlib import redirect_stdout
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
check("the error is a short class, not free text", re.fullmatch(r"[a-z0-9-]{1,40}", row["error"])
      is not None, True)

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
tmpl = (SCRIPTS / "com.kipi.linear-dor.plist").read_text()
rendered = tmpl.replace("__KIPI_REPO__", "/r").replace("__HOME__", "/h").encode()
try:
    args = plistlib.loads(rendered)["ProgramArguments"]
except Exception as exc:  # noqa: BLE001 - a parse failure IS the finding
    args = [f"unparseable: {type(exc).__name__}"]
check("the linear-dor plist parses strictly and passes --heartbeat",
      "--heartbeat" in (args[-1] if args else "").split(), True)

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

print("-- mutants: the invariant must go red without each rule")
src = UNDER_TEST.read_text()
for label, needle in (("starved rule removed", "        if streak >= STARVED_RUNS:\n"),
                      ("missing rule removed", "        if age > limit:\n")):
    check(f"mutant anchor present once: {label}", src.count(needle), 1)
    mutant = SANDBOX / f"mutant-{label.split()[0]}.py"
    mutant.write_text(src.replace(needle, needle.split("if ")[0] + "if False:\n", 1))
    broken = core_cases(load(mutant, f"mutant_{label.split()[0]}"))
    check(f"the invariant goes red with the {label}", bool(broken), True)

print()
if FAILS:
    print(f"FAIL: {len(FAILS)} check(s): " + "; ".join(FAILS))
    sys.exit(1)
print("PASS")
