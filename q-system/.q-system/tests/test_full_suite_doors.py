#!/usr/bin/env python3
"""Fixtures for full_suite_doors.py, the one detector behind test_ci_workflows.py
and fleet-full-suite-scan.py (RULE-2026-10-01-A).

A detector with no fixture of its own is a check nobody has seen fail, so every
door shape fires here and every near miss stays silent here. The three shapes
the PR #491 review named (an `if:`-first step, an `env:`-first step, a
reusable-workflow call) each have a row.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import full_suite_doors as fsd  # noqa: E402

ON_PR = "on:\n  pull_request:\n  push:\n    branches: [main]\n"


def wf(steps: str, on: str = ON_PR) -> str:
    return on + "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n" + steps + "\n"


@pytest.mark.parametrize("step,door", [
    ("      - run: bash q-system/.q-system/verify.sh --full", True),
    ("      - run: bash q-system/.q-system/verify.sh", True),
    ("      - run: q-system/.q-system/verify.sh", True),
    ("      - run: bash q-system/.q-system/verify.sh --changed --base \"$base\"", False),
    ("      - run: bash q-system/.q-system/verify.sh --staged", False),
    ("      - run: bash q-system/.q-system/test_verify_changed.sh q-system/.q-system/verify.sh", False),
    ("      - name: verify.sh --full\n        run: echo labelled only", False),
    ("      - run: python3 s/capability-gate.py --repo-root .", True),
    ("      - run: python3 s/capability-gate.py --repo-root . --diff-base x", False),
    ("      - run: pytest plugins/prd-os/tests/ -q", True),
    ("      - run: python3 -m pytest -q", True),
    ("      - run: python -m pytest tests -m \"not slow\"", True),
    ("      - run: pytest a/test_x.py -q", False),
    ("      - run: pytest a/test_x.py::test_one -m \"not slow\"", False),
    ("      - run: python3 -m pytest $TEST_TARGETS -q", False),
    ("      - run: pip install pytest", False),
    ("      - run: kipi check", True),
    ("      - name: v\n        run: python3 validate-separation.py 1", True),
    ("      - name: v\n        run: python3 validate-separation.py 1\n"
     "        env:\n          CAPABILITY_GATE_SKIP: \"1\"", False),
    ("      - run: |\n          FILES=(\n            \"validate-separation.py\"\n          )", False),
    ("      - run: npm test", True),
    ("      - run: npm run test", True),
    ("      - run: npm run test:tauri-assets", False),
    ("      - run: npx vitest run", True),
    ("      - run: npx vitest run src/a.test.ts", False),
    ("      - run: npx jest --findRelatedTests src/a.ts", False),
    ("      - run: make test", True),
    ("      - run: flutter test", True),
    ("      - run: flutter test test/widget_test.dart", False),
    ("      - run: go test ./...", True),
    ("      - run: cargo test", True),
    ("      # a comment naming verify.sh --full is not a door\n      - run: echo hi", False),
    # PR #491 review, the three silent shapes:
    ("      - if: github.event_name == 'push'\n        run: pytest tests/", True),
    ("      - env:\n          CI: true\n        run: npm test", True),
    ("      - uses: ./.github/workflows/full.yml", True),
    # A step that opens with env: is its OWN step. Split only on name/uses/run,
    # it merged into the step above and lent that step its skip flag.
    ("      - name: v\n        run: python3 validate-separation.py 1\n"
     "      - env:\n          CAPABILITY_GATE_SKIP: \"1\"\n        run: echo other", True),
])
def test_every_door_fires_and_only_there(step, door):
    hits = fsd.workflow_doors(wf(step))
    assert bool(hits) is door, (step, hits)


def test_a_job_level_reusable_call_is_a_door():
    text = ON_PR + "jobs:\n  t:\n    uses: org/repo/.github/workflows/tests.yml@main\n"
    assert any("reusable" in h for h in fsd.workflow_doors(text))


def test_a_local_reusable_call_is_judged_by_what_it_runs():
    caller = wf("      - uses: ./.github/workflows/inner.yml")
    full = "on:\n  workflow_call:\njobs:\n  i:\n    steps:\n      - run: pytest tests/\n"
    scoped = "on:\n  workflow_call:\njobs:\n  i:\n    steps:\n      - run: pytest t/test_a.py\n"
    hits = fsd.workflow_doors(caller)
    assert fsd.resolve_local(hits, lambda _: full)
    assert fsd.resolve_local(hits, lambda _: scoped) == []
    assert fsd.resolve_local(hits, lambda _: None) == hits, "unreadable stays a door"


@pytest.mark.parametrize("on,pr_or_push", [
    ("on:\n  schedule:\n    - cron: '0 9 * * *'\n  workflow_dispatch:\n", False),
    ("on: [push, pull_request]\n", True),
    ("on: push\n", True),
    ("on: workflow_dispatch\n", False),
    ("\"on\":\n  pull_request_target:\n", True),
    ("on:\n  push:\n    branches: ['feat/**']\n", True),
    ("on:\n  workflow_dispatch:\n    inputs:\n      push:\n        type: string\n", False),
])
def test_triggers(on, pr_or_push):
    assert fsd.runs_on_pr_or_push(on + "jobs:\n") is pr_or_push


def test_the_nightly_class_is_not_a_door():
    text = wf("      - run: pytest tests/", on="on:\n  schedule:\n    - cron: '0 9 * * *'\n")
    assert fsd.workflow_doors(text) == []


@pytest.mark.parametrize("line,exempt", [
    ("# full-suite-exempt: 23s measured on run 36800000001 (2026-10-01)", True),
    ("# full-suite-exempt: 59s measured on run 36800000001 (2026-10-01)", True),
    ("# full-suite-exempt: 60s measured on run 36800000001 (2026-10-01)", False),
    ("# full-suite-exempt: fast enough", False),           # a guess, not a measurement
    ("# full-suite-exempt: 23s measured", False),           # no run id to check it against
])
def test_an_exemption_needs_a_measurement_under_a_minute(line, exempt):
    text = line + "\n" + wf("      - run: pytest tests/")
    assert (fsd.workflow_doors(text) == []) is exempt


@pytest.mark.parametrize("hook,door", [
    ("#!/bin/sh\nbash q-system/.q-system/verify.sh --staged\n", False),
    ("#!/bin/sh\nexec python3 -m pytest\n", True),
    ("#!/bin/sh\nnpm test\n", True),
    ("pre-push:\n  commands:\n    tests:\n      run: pytest tests/\n", True),
    ("pre-commit:\n  commands:\n    verify:\n      run: bash q-system/.q-system/verify.sh --staged\n", False),
    ("#!/bin/sh\n# pytest tests/ used to run here\nexit 0\n", False),
    # a lefthook command NAMED pytest is a key, not an invocation (measured live)
    ("pre-commit:\n  commands:\n    pytest:\n      run: scripts/precommit-tests.sh {staged_files}\n", False),
    ("pre-commit:\n  commands:\n    pytest:\n      run: pytest tests/\n", True),
])
def test_hook_doors(hook, door):
    assert bool(fsd.hook_doors(hook)) is door, (hook, fsd.hook_doors(hook))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
