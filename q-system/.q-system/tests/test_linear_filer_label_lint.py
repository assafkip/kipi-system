#!/usr/bin/env python3
"""Tests for linear-filer-label-lint.py (ASK-882).

The cases that matter are the two the brief names -- a compliant filer passes, a
new filer that skips the label fails -- plus the population check, because this
gate was nearly shipped in a form that would have been red on 7 of the 8 files
already in the repo.
"""
import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
# normpath, not a raw join. `tests/../scripts/x.py` still CONTAINS "/tests/", so
# the un-normalized path made is_test_path() true for every production filer and
# the population check below passed by skipping all of it. A test that passes
# because its input never reached the code is worse than no test.
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "scripts"))


def _load(filename: str, modname: str):
    path = os.path.join(SCRIPTS, filename)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lint = _load("linear-filer-label-lint.py", "linear_filer_label_lint")

FILER = 'MUT = """mutation($input: IssueCreateInput!) { issueCreate(input: $input) }"""'


def test_a_compliant_automated_filer_passes():
    """The positive case: it attaches the triage label, so it declares itself."""
    text = FILER + '\nTRIAGE_LABEL = "needs-triage"\npayload["labelIds"] = ids\n'
    assert lint.check_text("scripts/some-filer.py", text)[0] == lint.EXIT_PASS


def test_a_new_filer_that_skips_the_label_is_blocked():
    """The negative case, and the whole reason this gate exists.

    A future script that creates Linear issues and says nothing about who
    decided they should exist is exactly the drift the rule could not catch.
    """
    text = FILER + '\npayload = {"teamId": team, "title": t}\nln.graphql(MUT, payload)\n'
    assert lint.check_text("scripts/new-filer.py", text)[0] == lint.EXIT_BLOCK


def test_a_human_driven_filer_passes_by_declaring_it():
    """The judgment half is DECLARED, never inferred. A reason is required."""
    text = FILER + "\n# linear-filer: human-in-the-loop -- founder types each issue\n"
    assert lint.check_text("scripts/manual.py", text)[0] == lint.EXIT_PASS


def test_a_bare_posture_marker_without_a_reason_is_still_blocked():
    """A mute exemption defeats the point: the marker exists to say something.

    Pinned because the regex is the only thing standing between "declared" and
    "waved through", and a trailing-empty group is the easy way to get it wrong.
    """
    text = FILER + "\n# linear-filer: human-in-the-loop --\n"
    assert lint.check_text("scripts/mute.py", text)[0] == lint.EXIT_BLOCK


def test_a_file_that_never_files_issues_is_untouched():
    """Scope must match the rule, or the gate runs on every edit in the repo."""
    assert lint.check_text("scripts/whatever.py",
                           "def add(a, b):\n    return a + b\n")[0] == lint.EXIT_PASS


def test_tests_are_skipped_so_the_reference_suite_stays_writable():
    """A suite constructs issueCreate in order to assert on it."""
    assert lint.check_text("q-system/.q-system/tests/test_alert_to_linear.py",
                           FILER)[0] == lint.EXIT_PASS
    assert lint.check_text("scripts/test/test-linear-dor.py",
                           FILER)[0] == lint.EXIT_PASS


def test_non_source_files_are_ignored():
    """A markdown rule QUOTING the mutation must not be gated as a filer."""
    assert lint.check_text("docs/automated-filer-marking.md",
                           FILER)[0] == lint.EXIT_PASS


def test_the_bypass_marker_releases_one_file():
    text = FILER + "\n# linear-filer-lint-skip: migration, one-shot\n"
    assert lint.check_text("scripts/one-shot.py", text)[0] == lint.EXIT_PASS


def test_label_constant_matches_the_filer_and_the_health_script():
    """Three files, one vocabulary. A rename in one silently empties the queue.

    linear-triage-health.py already pins itself to alert-to-linear.py; this
    extends the same chain to the gate, so the gate cannot drift into checking
    for a label nothing writes.
    """
    health = _load("linear-triage-health.py", "lfl_health_for_labels")
    alerts = _load("alert-to-linear.py", "lfl_alerts_for_labels")
    assert lint.TRIAGE_LABEL == health.TRIAGE_LABEL == alerts.TRIAGE_LABEL


@pytest.mark.parametrize("name", [
    "linear-sync.py",
    "fleet-health-daily.py",
    "spillover-promote.py",
    "linear-job-migration.py",
    "linear-dor-drafter.py",
    "alert-to-linear.py",
])
def test_every_existing_filer_in_this_repo_passes(name):
    """The gate must be satisfiable by the population it runs on.

    Measured 2026-08-16: 8 files construct `issueCreate` and only ONE referenced
    `needs-triage`. A gate demanding the label outright would have been red on 7
    of them the day it landed, and a gate that cannot pass gets switched off.
    This is the check that would have caught that, so it runs against the real
    files rather than a fixture of them.
    """
    path = os.path.join(SCRIPTS, name)
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    code, note = lint.check_text(path, text)
    assert code == lint.EXIT_PASS, f"{name} would be blocked ({note})"
