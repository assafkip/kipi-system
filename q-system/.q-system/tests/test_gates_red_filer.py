#!/usr/bin/env python3
"""gates-red-filer.py files ONE issue per (check, breaking commit) (ASK-3828).

The DoR check, end to end with nothing real filed: a main branch whose third
commit injects an undeclared test, a red nightly whose log says so, and the
filer run twice against a fixture GitHub (a directory of JSON). Night one must
open exactly one issue naming that commit, found by bisecting with the real
capability gate in throwaway worktrees. Night two, same red, must open nothing
and comment once. Before this file the nightly kept one issue per red streak
that named no check and no commit (gates.yml report-red, ASK-2262).

Every repo here is built in tmp_path; the live repo is only read for the two
gate files copied into the fixture (fable-discipline: no test on a live path).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "q-system" / ".q-system" / "scripts"
_spec = importlib.util.spec_from_file_location("gates_red_filer", SCRIPTS / "gates-red-filer.py")
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)
sys.path.insert(0, str(SCRIPTS))
import capability_manifest  # noqa: E402

CAP = F.CAPABILITY_STEP
INJECTED = "q-system/.q-system/scripts/test_injected.py"


# ---------------------------------------------------------------- parsing
@pytest.mark.parametrize("line,key", [
    ("test-failed rc=1: q/s/test-a.sh", "test-failed: q/s/test-a.sh"),
    ("test-failed rc=2: q/s/test-a.sh", "test-failed: q/s/test-a.sh"),
    ("test-timeout (60s): q/s/test_b.py", "test-timeout: q/s/test_b.py"),
    (f"present-but-undeclared: {INJECTED} — declare it by creating x.json containing {{}}",
     f"present-but-undeclared: {INJECTED}"),
    ("declared-but-missing (outside scan root): q/t/test_c.py",
     "declared-but-missing (outside scan root): q/t/test_c.py"),
    ("inert-engine: q/s/dead.py has no reference on any wiring surface", "inert-engine: q/s/dead.py"),
    ("zero tests executed: this gate ran no test artifact at all",
     "zero tests executed: this gate ran no test artifact at all"),
])
def test_one_failure_keeps_one_key_across_runs(line, key):
    assert F.normalize(line)[2] == key


def test_only_this_runs_top_level_red_lines_are_findings():
    log = "\n".join([
        "2026-11-06T09:19:30.0Z ##[group]Run python3 q-system/.q-system/scripts/covers-lint.py",
        "2026-11-06T09:19:30.1Z   RED: printed by an earlier step",
        "2026-11-06T09:19:31.0Z ##[group]Run python3 q-system/.q-system/scripts/capability-gate.py --repo-root .",
        "2026-11-06T10:06:11.0Z   RED: test-failed rc=1: q/s/test-a.sh",
        "2026-11-06T10:06:11.1Z       |   RED: present-but-undeclared: a nested gate inside test-a's tail",
        "2026-11-06T10:06:11.2Z   RED: inert-engine: q/s/dead.py has no reference",
        "2026-11-06T10:06:11.3Z capability-gate: RED (2)",
    ])
    keys = [f["key"] for f in F.findings_for(CAP, log)]
    assert keys == ["test-failed: q/s/test-a.sh", "inert-engine: q/s/dead.py"]


def test_a_red_gate_with_no_red_line_is_still_one_finding():
    assert [f["key"] for f in F.findings_for(CAP, "Traceback: boom")] == ["exited red with no RED line"]
    assert [f["key"] for f in F.findings_for("prd-os tests", "")] == ["step failed"]


# ---------------------------------------------------------------- bisect
class FakeProber:
    def __init__(self, red, broken=()):
        self.red_at, self.broken, self.count = set(red), set(broken), 0

    def red(self, finding, sha):
        self.count += 1
        if sha in self.broken:
            raise F.ProbeError(f"cannot run at {sha}")
        return sha in self.red_at


COMMITS = [f"c{i}" for i in range(1, 9)]          # c1 oldest .. c8 head; base is c0
FIND = {"step": CAP, "kind": "test-failed", "path": "p", "key": "test-failed: p"}


@pytest.mark.parametrize("culprit", COMMITS)
def test_bisect_names_the_first_red_commit(culprit):
    pr = FakeProber(COMMITS[COMMITS.index(culprit):])
    a = F.attribute(pr, FIND, COMMITS, "c0", "c8")
    assert a == {"sha": culprit, "found": True, "why": "bisected"}
    assert pr.count <= 2 + 3, "head, base, then log2(8) probes, never one per commit"


def test_one_commit_in_range_is_that_commit():
    a = F.attribute(FakeProber(["c1"]), FIND, ["c1"], "c0", "c1")
    assert a["sha"] == "c1" and a["found"] and "only commit" in a["why"]


@pytest.mark.parametrize("red,broken,sha,why", [
    ([], (), "c8", "not reproduced"),                            # flaky: green when re-run
    (["c0", *COMMITS], (), "c0", "no commit in range caused it"),  # time or runner, not code
    (COMMITS, ("c4",), "c8", "not bisected: cannot run at c4"),
])
def test_an_unpinned_cause_says_why_and_names_no_culprit(red, broken, sha, why):
    a = F.attribute(FakeProber(red, broken), FIND, COMMITS, "c0", "c8")
    assert a["sha"] == sha and a["found"] is False and why in a["why"], a


def test_no_green_baseline_is_said_not_guessed():
    a = F.attribute(FakeProber(COMMITS), FIND, None, None, "c8")
    assert a["found"] is False and "no usable green nightly" in a["why"]


# ---------------------------------------------------------------- end to end
def _git(r, *a):
    env = {"PATH": os.environ["PATH"], "HOME": str(r.parent), "LC_ALL": "C"}
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", *a],
                          cwd=r, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def main_branch(tmp_path):
    """A (green) -> B -> C (injects an undeclared test) -> D (head). Instance
    mode (no registry), so the copied gate scripts need no wiring surface."""
    r = tmp_path / "repo"
    s = r / "q-system/.q-system/scripts"
    s.mkdir(parents=True)
    for name in ("capability-gate.py", "capability_manifest.py"):
        shutil.copy2(SCRIPTS / name, s / name)
    capability_manifest.explode(r, {"schema_version": 1, "expected_tests": [], "required_data": [],
                                    "skeleton_only": [], "declared_inert": [], "uncovered_known": []})
    _git(r, "init", "-q", "-b", "main")
    shas = {}
    for name, path, body in (("A", "a.txt", "a\n"), ("B", "b.txt", "b\n"),
                             ("C", INJECTED, "import sys; sys.exit(0)\n"), ("D", "d.txt", "d\n")):
        (r / path).write_text(body)
        _git(r, "add", "-A")
        _git(r, "commit", "-q", "-m", f"commit {name}")
        shas[name] = _git(r, "rev-parse", "HEAD")
    return r, shas


def _night(tmp_path, r, run_id, steps, log):
    d = tmp_path / "gh"
    d.mkdir(exist_ok=True)
    (d / "jobs.json").write_text(json.dumps({"jobs": [
        {"id": 7, "name": "gates", "conclusion": "failure",
         "steps": [{"name": n, "conclusion": c} for n, c in steps]}]}))
    (d / "log-7.txt").write_text(log)
    gh = F.FixtureGitHub(d)
    return F.run(gh, r, run_id, f"https://ci/run/{run_id}", "gates.yml"), json.loads((d / "issues.json").read_text())


RED_LOG = ("2026-11-07T09:19:31.0Z ##[group]Run python3 q-system/.q-system/scripts/capability-gate.py --repo-root .\n"
           f"2026-11-07T10:06:11.0Z   RED: present-but-undeclared: {INJECTED} — declare it by creating x.json\n"
           "2026-11-07T10:06:11.1Z capability-gate: RED (1)\n")
CAP_RED = [("Coverage declarations are real", "success"), (CAP, "failure"),
           ("Skeleton separation, phase 1", "skipped"), ("prd-os tests", "skipped")]


def _per_check(issues, state="open"):
    return [i for i in issues if i["state"] == state and F.GROUP_RE.search(i["body"])]


def test_an_injected_undeclared_test_files_one_issue_naming_its_commit(tmp_path, main_branch):
    r, sha = main_branch
    d = tmp_path / "gh"
    d.mkdir()
    (d / "green_sha.txt").write_text(sha["A"])
    (d / "issues.json").write_text(json.dumps([{"number": 1, "title": "gates-red: nightly gates failed",
                                                "body": "old shape", "state": "open", "comments": []}]))

    acts, issues = _night(tmp_path, r, "101", CAP_RED, RED_LOG)
    filed = _per_check(issues)
    assert len(filed) == 1, f"night one must file exactly one issue: {acts}"
    assert sha["C"][:7] in filed[0]["title"] and "commit C" in filed[0]["title"], filed[0]["title"]
    assert f"gates-red-group: {CAP}@{sha['C']}" in filed[0]["body"]
    assert f"present-but-undeclared: {INJECTED}" in filed[0]["body"]
    assert "bisected" in filed[0]["body"]
    legacy = next(i for i in issues if i["number"] == 1)
    assert legacy["state"] == "closed" and "ASK-3828" in legacy["comments"][0]
    assert _git(r, "worktree", "list").count("\n") == 0, "a probe worktree outlived the run"

    acts, issues = _night(tmp_path, r, "102", CAP_RED, RED_LOG)
    assert len(_per_check(issues)) == 1, f"night two filed again: {acts}"
    assert _per_check(issues)[0]["comments"] == ["Still red: https://ci/run/102"]
    assert acts == [f"still-red #{filed[0]['number']}"]

    # A night where the gate never ran (an earlier step failed) proves nothing
    # about its findings, so the issue stays open.
    acts, issues = _night(tmp_path, r, "103", [("Install test dependencies", "failure"), (CAP, "skipped")], "")
    assert len([i for i in _per_check(issues) if CAP in i["title"]]) == 1, acts

    # The gate ran and its finding is gone: closed, with the run that showed it.
    acts, issues = _night(tmp_path, r, "104", [(CAP, "success"), ("prd-os tests", "failure")], "")
    closed = [i for i in _per_check(issues, "closed") if CAP in i["title"]]
    assert len(closed) == 1 and closed[0]["comments"][-1] == "Green for this check in https://ci/run/104"


def test_an_issue_extended_tonight_is_not_closed_for_what_it_lost(tmp_path, main_branch):
    """One open issue for (gate, C) whose old finding is gone tonight, while a new
    finding bisects to the same C: it is extended, and it stays open."""
    r, sha = main_branch
    d = tmp_path / "gh"
    d.mkdir()
    (d / "green_sha.txt").write_text(sha["A"])
    gone = "test-failed: q/s/test-fixed-since.sh"
    body = (f"<!-- gates-red-group: {CAP}@{sha['C']} -->\nx\n\nFindings:\n"
            f"- `{gone}` <!-- gates-red-finding: {F.finding_id(CAP, gone)} -->\n")
    (d / "issues.json").write_text(json.dumps([{"number": 5, "title": "gates-red: old", "body": body,
                                                "state": "open", "comments": []}]))
    acts, issues = _night(tmp_path, r, "301", CAP_RED, RED_LOG)
    five = next(i for i in issues if i["number"] == 5)
    assert acts == ["extended #5 +1"] and five["state"] == "open", acts
    assert f"present-but-undeclared: {INJECTED}" in five["body"] and gone in five["body"]


TWO_RED_LOG = RED_LOG.replace(
    "2026-11-07T10:06:11.1Z capability-gate: RED (1)\n",
    "2026-11-07T10:06:11.1Z   RED: test-failed rc=1: q/s/test-slow.sh\n"
    "2026-11-07T10:06:11.2Z capability-gate: RED (2)\n")


def test_a_cancelled_bisect_keeps_what_was_already_attributed(tmp_path, main_branch, monkeypatch):
    """#608 review, major: every create ran after every bisect, so a job cancelled
    at its cap during finding two filed nothing, finding one included."""
    r, sha = main_branch
    d = tmp_path / "gh"
    d.mkdir()
    (d / "green_sha.txt").write_text(sha["A"])
    calls = []

    def attribute(prober, f, commits, base, head):
        calls.append(f["key"])
        if len(calls) == 2:
            raise KeyboardInterrupt("job cancelled at its cap")
        return {"sha": sha["C"], "found": True, "why": "bisected"}
    monkeypatch.setattr(F, "attribute", attribute)
    with pytest.raises(KeyboardInterrupt):
        _night(tmp_path, r, "401", CAP_RED, TWO_RED_LOG)
    issues = json.loads((d / "issues.json").read_text())
    assert len(_per_check(issues)) == 1 and sha["C"][:7] in issues[0]["title"], issues
    assert _git(r, "worktree", "list").count("\n") == 0, "the cancelled run leaked a probe worktree"


def test_a_commit_that_cannot_be_checked_out_is_not_a_crash(tmp_path, main_branch):
    r, sha = main_branch
    pr = F.Prober(r)
    try:
        a = F.attribute(pr, FIND, ["0" * 40], sha["A"], "0" * 40)   # head probed first
    finally:
        pr.close()
    assert a["found"] is False and "not bisected" in a["why"], a


def test_a_spent_probe_budget_files_against_head_unbisected(tmp_path, main_branch):
    r, sha = main_branch
    pr = F.Prober(r, budget_s=0)
    try:
        a = F.attribute(pr, {"step": CAP, "kind": "present-but-undeclared", "path": INJECTED,
                             "key": f"present-but-undeclared: {INJECTED}"},
                        [sha["B"], sha["C"], sha["D"]], sha["A"], sha["D"])
    finally:
        pr.close()
    assert a == {"sha": sha["D"], "found": False,
                 "why": f"not bisected: this run's {F.PROBE_BUDGET_S // 60}-minute probe budget is spent"}


def test_the_one_issue_count_can_fail(tmp_path, main_branch):
    """Negative self-test: with the dedup markers stripped between nights, the
    same red files a second issue, and the count above would catch it."""
    r, sha = main_branch
    d = tmp_path / "gh"
    d.mkdir()
    (d / "green_sha.txt").write_text(sha["A"])
    _night(tmp_path, r, "201", CAP_RED, RED_LOG)
    issues = json.loads((d / "issues.json").read_text())
    for i in issues:
        i["body"] = F.FIND_RE.sub("", F.GROUP_RE.sub("<!-- gates-red-group: x@0000000 -->", i["body"]))
    (d / "issues.json").write_text(json.dumps(issues))
    _, issues = _night(tmp_path, r, "202", CAP_RED, RED_LOG)
    assert len([i for i in _per_check(issues) if sha["C"][:7] in i["title"]]) == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
