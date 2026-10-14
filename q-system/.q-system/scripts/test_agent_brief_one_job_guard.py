"""agent-brief-one-job-guard.py: one Agent brief = one job = one PR (ASK-2541).

Drives the hook the way the harness does: a PreToolUse JSON payload on stdin,
exit code and stderr read back. The multi-PR cases are red before the guard
exists (no script, nothing blocks). The single-job controls pin that it blocks
on PR count, not on the word "PR". Fixtures are generic on purpose: this repo
is public.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GUARD = HERE / "agent-brief-one-job-guard.py"
REPO = HERE.parents[2]


def _run(brief_text: str, *, tool: str = "Agent", description: str = "do a thing",
         guard: Path = GUARD) -> subprocess.CompletedProcess:
    payload = {
        "session_id": "s",
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {"description": description, "prompt": brief_text,
                       "subagent_type": "general-purpose"},
    }
    return subprocess.run(
        [sys.executable, str(guard)], input=json.dumps(payload),
        capture_output=True, text=True, timeout=30,
    )


MULTI_JOB = {
    # the RCA's own shape: an orchestrator brief that asks for the split
    "orchestrator-split": "Read the plan. Build every action item. Split into "
                          "small PRs, one job each. Review each when ready.",
    "numbered-pr-list": "Your jobs:\n1. PR 1: add the ledger row.\n"
                        "2. PR 2: add the channel filter.\n3. Dry run.\n",
    "per-item": "Two fixes for the widget, one PR each. Test first.",
    "counted": "Land the work as two separate PRs and arm auto-merge.",
    "lettered": "Ship PR-A (the checker) then PR-B (the filter).",
}


@pytest.mark.parametrize("case", sorted(MULTI_JOB))
def test_multi_pr_brief_is_blocked(case):
    r = _run(MULTI_JOB[case])
    assert r.returncode == 2, (case, r.stderr)
    assert "more than one PR" in r.stderr
    assert "one agent per PR" in r.stderr, "the block must say how to split"


def test_task_tool_name_is_covered_too():
    assert _run(MULTI_JOB["per-item"], tool="Task").returncode == 2


def test_description_field_is_read():
    r = _run("Do it.", description="PR-C then PR-D: renderer fixes")
    assert r.returncode == 2, r.stderr


SINGLE_JOB = {
    "plain": "Fix the off-by-one in the parser. Test first. Open one PR.",
    "real-pr-numbers": "Fix the review findings on PR #233 and land it. "
                       "PR 241 is unrelated.",
    "fenced-sibling": "Build exactly PR-B of the plan, nothing from PR-C..F. "
                      "PR-A is merged (#82).",
    "descriptive-count": "Context: three PRs merged green today and still "
                         "broke the mirror. Fix the mirror check, one PR.",
    "no-pr-at-all": "Research the vendor's API limits and report back.",
}


@pytest.mark.parametrize("case", sorted(SINGLE_JOB))
def test_single_job_brief_passes(case):
    r = _run(SINGLE_JOB[case])
    assert r.returncode == 0, (case, r.stderr)
    assert r.stderr == ""


def test_bypass_needs_a_reason():
    quoted = "Scar: a brief once asked for three PRs, split into two PRs. " \
             "Fix the detector, one PR."
    assert _run(quoted).returncode == 2
    assert _run(quoted + "\none-job-brief-skip:").returncode == 2, \
        "a bare marker must not stand the gate down"
    ok = _run(quoted + "\none-job-brief-skip: quotes the old scar, one job")
    assert ok.returncode == 0, ok.stderr


def test_non_agent_tools_and_bad_input_pass():
    assert _run(MULTI_JOB["per-item"], tool="Bash").returncode == 0
    r = subprocess.run([sys.executable, str(GUARD)], input="not json",
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0


def test_missing_detector_is_loud_not_silent(tmp_path):
    # a copy of the guard with no plugins/ beside it: it must say INERT
    q = tmp_path / "q-system" / ".q-system" / "scripts"
    q.mkdir(parents=True)
    lone = q / GUARD.name
    lone.write_text(GUARD.read_text())
    r = _run(MULTI_JOB["per-item"], guard=lone)
    assert r.returncode == 0
    assert "INERT" in r.stderr


def test_detector_resolves_from_this_repo():
    # load-path: the guard's computed detector dir is a real file in this tree
    assert (REPO / "plugins" / "prd-os" / "scripts" / "one_job.py").is_file()


@pytest.mark.parametrize("settings", [".claude/settings.json", "settings-template.json"])
def test_wired_in_both_settings_files(settings):
    data = json.loads((REPO / settings).read_text())
    hits = [
        h["command"]
        for block in data["hooks"]["PreToolUse"]
        if "Agent" in block.get("matcher", "").split("|")
        and "Task" in block.get("matcher", "").split("|")
        for h in block["hooks"]
        if GUARD.name in h["command"]
    ]
    assert len(hits) == 1, f"{settings}: guard wired {len(hits)} times"
