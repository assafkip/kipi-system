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
    # A negation in an EARLIER clause must not fence a real request: the
    # fence is clause-scoped (PR #612 round 1 fix round).
    "negation-in-earlier-clause": "Do not merge yet, and open two PRs for "
                                  "the parser and the filter.",
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
    # PR #612 round 1 major: the count rule had no fence, so the brief that
    # OBEYS the rule, and one quoting PR history, were blocked.
    "forbids-split": "Fix the off-by-one in the parser. Keep it to one PR: "
                     "do not split this into two PRs.",
    "says-never": "One job only. Never open two PRs for this; the whole fix "
                  "is one commit.",
    "not-as-separate": "Ship it as one PR, not as two separate PRs.",
    "past-tense-history": "Context: the scratch-file leak happened in three "
                          "consecutive PRs, and the last fix landed in two "
                          "PRs. Fix it at push time, one PR.",
}


@pytest.mark.parametrize("case", sorted(SINGLE_JOB))
def test_single_job_brief_passes(case):
    r = _run(SINGLE_JOB[case])
    assert r.returncode == 0, (case, r.stderr)
    assert r.stderr == ""
    # the report-limit WARNING may speak on stdout; it must never be a block
    assert "BLOCKED" not in r.stdout


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


# ---- ASK-4649: brief length and report-limit WARNINGS (exit 0, never a block)
# Fixtures are real briefs from the control set, not invented. Measured on those
# 105 briefs: 3 over the length caps, 91 with no numeric report limit.
BRIEFS = json.loads((HERE / "fixtures" / "agent_briefs_control_1111.json").read_text())


def _warning(r: subprocess.CompletedProcess) -> str:
    assert r.returncode == 0, r.stderr
    assert r.stderr == "", "a warning on stderr never reaches the model"
    if not r.stdout.strip():
        return ""
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    return out["additionalContext"]


def test_short_brief_with_report_limit_passes_silently():
    r = _run(BRIEFS["short_with_report_limit"])
    assert r.stdout == "" and _warning(r) == ""


def test_long_brief_gets_the_length_message():
    msg = _warning(_run(BRIEFS["long_no_report_limit"]))
    assert "non-blank lines" in msg and "caps: 40 lines, 1000 words" in msg


def test_brief_without_report_limit_gets_that_message():
    msg = _warning(_run(BRIEFS["short_no_report_limit"]))
    assert "no limit on the final report" in msg
    assert "non-blank lines" not in msg, "a short brief must not get the length note"


def test_a_stated_limit_in_a_long_brief_drops_only_the_limit_message():
    msg = _warning(_run(BRIEFS["long_no_report_limit"] + "\nReport under 300 words."))
    assert "non-blank lines" in msg and "no limit on the final report" not in msg


def test_bypass_silences_both_warnings():
    marker = "\none-job-brief-skip: a long brief by design, one job"
    r = _run(BRIEFS["long_no_report_limit"] + marker)
    assert r.stdout == "" and _warning(r) == ""


def test_warnings_never_block_even_when_both_fire():
    r = _run(BRIEFS["long_no_report_limit"])
    assert r.returncode == 0


def test_malformed_input_still_exits_zero_without_output():
    r = subprocess.run([sys.executable, str(GUARD)], input="not json",
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


def test_each_length_cap_fires_alone():
    # boundary shapes, constructed: the real long brief trips both caps at once
    # and would hide a mutant that disables only one of them
    lines_only = "\n".join(["Report under 300 words. Step."] + ["step"] * 45)
    words_only = "Report under 300 words. " + "word " * 1100
    assert "non-blank lines" in _warning(_run(lines_only))
    assert "non-blank lines" in _warning(_run(words_only))
    # the description line counts too: 1 + 1 + 38 = exactly 40 lines
    at_cap = "Report under 300 words.\n" + "\n".join(["step"] * 38)
    assert _warning(_run(at_cap)) == ""


def test_warning_does_not_name_the_bypass_marker():
    # PR #769 review major: the marker also stands down the multi-PR block, so
    # advertising it in a warning that fires on most launches teaches the model
    # the string that turns the block off. The bypass still works (test above).
    msg = _warning(_run(BRIEFS["long_no_report_limit"]))
    assert msg and "one-job-brief-skip" not in msg
