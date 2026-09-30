#!/usr/bin/env python3
"""RED FIRST. This test pins the nightly gates workflow that moves the Mac's
02:15 Gates run into GitHub Actions (automation cleanup, Phase 7).

What a fresh clone can run: the capability gate's full suite,
validate-separation phase 1, and the prd-os tests.
What needs the Mac stays there: the launchd health check, `kipi check`'s
remote-coverage scan plus separation phases 2-4, which read instance dirs.

The spillover census (`prd_runner.py gates run`) is NOT here. Its ledgers are
untracked, so a fresh clone runs it over an empty population and prints an
all-clear (PR #478 review, reproduced with a depth-1 clone: "0 open total",
exit 0). This test requires that no step reads it, and requires the suites
green on main to be the ones whose failure fails the job.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "gates.yml"

# Words that mean a model is being called or a model credential is in reach.
MODEL_SURFACE = re.compile(r"\b(claude|anthropic|codex|openai|gemini)\b", re.I)


def _text() -> str:
    assert WORKFLOW.is_file(), f"missing {WORKFLOW.relative_to(ROOT)}"
    return WORKFLOW.read_text()


def _steps(text: str) -> list[str]:
    """Split the workflow into step blocks: each starts at a `- name:` line."""
    blocks = re.split(r"(?m)^\s*- name:", text)
    return blocks[1:]


def _step(text: str, needle: str) -> str:
    hits = [b for b in _steps(text) if needle in b]
    assert len(hits) == 1, f"expected exactly one step running {needle!r}, found {len(hits)}"
    return hits[0]


def _code_lines(text: str) -> str:
    """The workflow minus comment lines: a why-comment may name what the job
    refuses to do without the job doing it."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def test_runs_nightly_and_by_hand_only():
    text = _text()
    on = text.split("\njobs:", 1)[0]
    assert re.search(r"(?m)^\s*schedule:\s*$", on), "no schedule trigger"
    assert re.search(r"cron:\s*['\"][0-9]+ [0-9]+ \* \* \*['\"]", on), "cron is not a daily fixed time"
    assert "workflow_dispatch" in on, "cannot be run by hand"
    assert "pull_request" not in on and "push:" not in on, "must not run on PRs or pushes"


def test_makes_no_model_call_and_reads_no_secret():
    code = _code_lines(_text())
    hit = MODEL_SURFACE.search(code)
    assert hit is None, f"model surface in a non-comment line: {hit.group(0)!r}"
    assert "secrets." not in code, "the nightly gates read no secret"


def test_failing_suites_are_the_full_push_suites():
    text = _text()
    cap = _step(text, "capability-gate.py")
    assert "--diff-base" not in cap, "the nightly capability gate must run the FULL suite"
    assert "continue-on-error" not in cap
    sep = _step(text, "validate-separation.py")
    assert re.search(r"validate-separation\.py 1\b", sep)
    assert "continue-on-error" not in sep
    prd = _step(text, "pytest plugins/prd-os/tests")
    assert "continue-on-error" not in prd


def test_no_step_reads_an_untracked_ledger():
    code = _code_lines(_text())
    assert "gates run" not in code, "the census ledgers are untracked: it would report an empty population"
    assert "spillover" not in code


def test_design_chain_tests_cannot_skip_to_green():
    # dc-25: without a browser every design-chain test skips and the gate reads green.
    text = _text()
    assert "playwright install" in text, "no browser for the design-chain producers"
    cap = _step(text, "capability-gate.py")
    assert re.search(r'DC_REQUIRE_REAL_PRODUCERS:\s*"1"', cap), "a skip would read as green"


def _jobs(text: str) -> dict[str, str]:
    """Each job's block, keyed by its id: the 2-space keys under `jobs:`."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  ([A-Za-z0-9_-]+):\s*$", body)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}


def _job_keys(block: str) -> dict[str, str]:
    """A job's own keys (4-space indent), never its steps' keys."""
    return {m.group(1): m.group(2).strip()
            for m in re.finditer(r"(?m)^    ([A-Za-z_-]+):(.*)$", block)}


# ASK-2262 (#478 reviewer): per-step checks miss the job-level ways to silence the
# nightly. Each of these keeps every step "running" in the text while the job can
# no longer fail, or never starts.
def test_the_gates_job_cannot_be_silenced_at_job_level():
    gates = _jobs(_code_lines(_text()))["gates"]
    keys = _job_keys(gates)
    assert "continue-on-error" not in keys, "job-level continue-on-error: red reads green"
    assert "if" not in keys, "job-level if: the job can be skipped, and skipped is not red"
    assert "continue-on-error" not in gates, "no step in the gates job may swallow a failure"
    assert not re.search(r"(?m)^\s+if:", gates), "a step-level if: can skip a gate"
    # #484 review: the cheapest silencers live INSIDE a run: line, not in a key.
    for pat, why in RUN_LINE_SILENCERS:
        assert not re.search(pat, gates), why


# Kept as data so the table below can prove each pattern fires on its spelling.
RUN_LINE_SILENCERS = (
    (r"\|\|\s*(true\b|:(?=\s|;|\)|$))", "`|| true` / `|| :` swallows a gate's exit"),
    (r"\bexit\s+0\b", "`exit 0` overrides a gate's exit"),
    (r"\bset\s+\+e\b", "`set +e` stops a failing line failing the step"),
)


@pytest.mark.parametrize("line,silenced", [
    ("        run: pytest plugins/prd-os/tests/ -q || true", True),
    # #484 round 2: `\b` after `:` cannot match at end of line, so this passed.
    ("        run: pytest plugins/prd-os/tests/ -q || :", True),
    ("        run: pytest plugins/prd-os/tests/ -q || : ; echo done", True),
    ("        run: pytest plugins/prd-os/tests/ -q; exit 0", True),
    ("        run: set +e; pytest plugins/prd-os/tests/ -q", True),
    ("        run: pytest plugins/prd-os/tests/ -q", False),
    ("        run: pytest plugins/prd-os/tests/ -q || exit 1", False),
    ("        run: echo 'a: b' || exit 2", False),
])
def test_silencer_patterns_fire_on_every_spelling(line, silenced):
    """A pattern table with no fixture of its own is a check nobody has seen fail."""
    hit = any(re.search(pat, line, re.M) for pat, _ in RUN_LINE_SILENCERS)
    assert hit is silenced, line


def test_a_red_run_opens_or_updates_one_issue():
    """The route out of a red run: no secret, one deduped issue, a named consumer."""
    text = _text()
    jobs = _jobs(_code_lines(text))
    reporters = sorted(j for j in jobs if j != "gates")
    assert reporters == ["report-green", "report-red"], f"unexpected reporter jobs {reporters}"
    rep = jobs["report-red"]
    keys = _job_keys(rep)
    assert keys.get("needs") == "gates", "the reporter must follow the gates job"
    assert keys.get("if") == "failure()", "the reporter runs only when gates failed"
    assert re.search(r"(?m)^\s+issues:\s*write\s*$", rep), "needs issues: write"
    assert "github.token" in rep, "the built-in token, never a stored secret"
    assert "gates-red" in rep and "--label gates-red" in rep
    assert "gates-red: nightly gates failed" in rep, "the title is the dedup key"
    assert "gh issue comment" in rep and "gh issue create" in rep, "update or open"
    # The consumer this route depends on. Without it the issue is an output nobody reads.
    fh = (ROOT / "q-system/.q-system/scripts/fleet-health-daily.py").read_text()
    assert '"id": "gates-red"' in fh and "--label" in fh


def test_a_green_run_closes_the_issue():
    """#484 review: without a closer the open issue outlives the fix, and the
    detector refiles (reopens) a Linear issue every morning over a green nightly."""
    grn = _jobs(_code_lines(_text()))["report-green"]
    keys = _job_keys(grn)
    assert keys.get("needs") == "gates"
    assert keys.get("if") == "success()", "the closer runs only on a green gates job"
    assert re.search(r"(?m)^\s+issues:\s*write\s*$", grn)
    assert "github.token" in grn and "gh issue close" in grn and "--label gates-red" in grn
    # #484 round 2: `for n in $(gh ...)` hides gh's exit from set -e, so a failed
    # list closed nothing, exited 0, and the detector reopened Linear next morning.
    assert not re.search(r"\bfor\s+\w+\s+in\s+\$\(", grn), \
        "list the issues in an assignment, where set -e sees gh fail"


def test_two_runs_cannot_race_to_two_issues():
    """#484 review: read-then-create is a window; serialize the workflow."""
    top = _text().split("\njobs:", 1)[0]
    assert re.search(r"(?m)^concurrency:", top), "no workflow concurrency group"
    assert re.search(r"(?m)^  cancel-in-progress:\s*false\s*$", top), \
        "queue a second run, never cancel a running gate"


def test_names_no_machine_path():
    text = _text()
    for bad in ("/Users/", "/home/", "~/projects", "$HOME/projects"):
        assert bad not in text, f"machine path {bad!r} in a public workflow"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
