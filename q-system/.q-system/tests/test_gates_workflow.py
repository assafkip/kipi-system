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


def test_names_no_machine_path():
    text = _text()
    for bad in ("/Users/", "/home/", "~/projects", "$HOME/projects"):
        assert bad not in text, f"machine path {bad!r} in a public workflow"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
