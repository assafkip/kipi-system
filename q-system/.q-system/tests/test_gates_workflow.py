#!/usr/bin/env python3
"""RED FIRST. This test pins the nightly gates workflow that moves the Mac's
02:15 Gates run into GitHub Actions (automation cleanup, Phase 7).

What a fresh clone can run: the capability gate's full suite,
validate-separation phase 1, the prd-os tests, and `prd_runner.py gates run`.
What needs the Mac stays there: the launchd health check, and `kipi check`'s
remote-coverage scan plus separation phases 2-4, which read instance dirs.

Measured 2026-09-30 for this test: the gates ledger holds 112 rows and ZERO carry
the `regression` lifecycle, so `gates run` executes no registered command here.
Its whole verdict is the spillover census, red on its entire population (95
inherited items, no active scope in CI). A job that fails on it fails every
night and says nothing new, so this test requires the census exit code to be
captured and written to the run summary, and requires the suites that are green
on main to be the ones whose failure fails the job.
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


def test_spillover_census_is_reported_only():
    step = _step(_text(), "gates run")
    assert "GITHUB_STEP_SUMMARY" in step, "census output never reaches the run summary"
    # Non-blocking by construction: the exit code is captured, not propagated.
    assert re.search(r"\|\|\s*rc=\$\?", step), "gates run exit code is not captured"
    assert not re.search(r"(?m)^\s*exit \"?\$rc", step), "the census must not fail the job"


def test_names_no_machine_path():
    text = _text()
    for bad in ("/Users/", "/home/", "~/projects", "$HOME/projects"):
        assert bad not in text, f"machine path {bad!r} in a public workflow"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
