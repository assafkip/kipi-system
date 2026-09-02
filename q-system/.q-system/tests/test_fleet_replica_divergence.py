#!/usr/bin/env python3
"""Tests for fleet-replica-divergence.py.

EVERY CASE BUILDS ITS OWN FAKE FLEET IN A TMPDIR. None of these read the real
instance-registry.json or any real instance. A test that pointed at the live
registry would pass or fail based on whatever the fleet happens to hold today,
which is a test that cannot be trusted in either direction (and the
fable-discipline lint blocks tests that touch a live data path).

The exit codes are deliberately distinct so a control cannot pass by accident:
  0 = agreement, 1 = divergence found, 2 = refused (empty population).
An earlier draft treated "nonzero" as the assertion, which would have accepted
the empty-population refusal as a successful divergence detection.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fleet-replica-divergence.py"
REL = "plugins/prd-os/scripts/prd_runner.py"


def build_fleet(tmp_path, contents: dict[str, str | None], *, extra: dict | None = None):
    """contents: root name -> file text, or None to omit the file entirely."""
    roots = []
    for name, text in contents.items():
        root = tmp_path / name
        if text is not None:
            target = root / REL
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        else:
            root.mkdir(parents=True, exist_ok=True)
        roots.append({"name": name, "path": str(root)})
    registry = tmp_path / "instance-registry.json"
    payload = {"instances": roots}
    if extra:
        payload.update(extra)
    registry.write_text(json.dumps(payload))
    return registry


def run(registry, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--registry", str(registry), *args],
        capture_output=True, text=True, timeout=120,
    )


def test_identical_copies_are_green(tmp_path):
    reg = build_fleet(tmp_path, {"a": "same\n", "b": "same\n", "c": "same\n"})
    res = run(reg, "--path", REL)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "DIVERGED" not in res.stdout


def test_one_diverged_copy_goes_red(tmp_path):
    """THE NEGATIVE SELF-TEST. This is the real P-3 shape: 2 agree, 1 is ahead."""
    reg = build_fleet(tmp_path, {"a": "same\n", "b": "same\n", "c": "same\nEXTRA\n"})
    res = run(reg, "--path", REL)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "DIVERGED" in res.stdout
    # Fails for the RIGHT reason: it must name the path and the odd copy out,
    # not merely exit nonzero.
    assert REL in res.stdout
    assert str(tmp_path / "c") in res.stdout
    assert "--delete" in res.stdout  # the data-loss warning fired


def test_green_flips_to_red_on_a_one_byte_change(tmp_path):
    """Mutation: same fleet, one byte apart, must change the verdict.

    Guards against a detector that is green because it measured nothing. If this
    passed in both states the check would be decoration.
    """
    reg = build_fleet(tmp_path, {"a": "x\n", "b": "x\n"})
    assert run(reg, "--path", REL).returncode == 0
    (tmp_path / "b" / REL).write_text("y\n")
    assert run(reg, "--path", REL).returncode == 1


def test_absent_copy_is_not_divergence(tmp_path):
    """Not every instance carries every plugin. Absence must not red the gate."""
    reg = build_fleet(tmp_path, {"a": "same\n", "b": None, "c": "same\n"})
    res = run(reg, "--path", REL)
    assert res.returncode == 0, res.stdout + res.stderr


def test_empty_population_refuses_rather_than_reporting_green(tmp_path):
    """A detector that resolved zero roots must not look like agreement.

    Distinct exit code (2) so this can never be mistaken for the divergence
    signal (1) by a caller that only checks truthiness.
    """
    registry = tmp_path / "instance-registry.json"
    registry.write_text(json.dumps({"instances": []}))
    res = run(registry, "--path", REL)
    assert res.returncode == 2, res.stdout + res.stderr
    assert "refusing to report green" in res.stderr


def test_unreadable_registry_refuses(tmp_path):
    res = run(tmp_path / "does-not-exist.json", "--path", REL)
    assert res.returncode == 2, res.stdout + res.stderr


# --- claim-vs-enforcer mode (P-4 / P-5 shape) ---------------------------------

LESSON = "q-system/lessons/gate-must-run.md"
CODE = "plugins/prd-os/scripts/prd_runner.py"
NEEDLE = "_reject_unrunnable_gate"


def build_claim_fleet(tmp_path, spec: dict[str, tuple[bool, bool]]):
    """root name -> (has_lesson, has_enforcer_symbol)."""
    roots = []
    for name, (lesson, enforcer) in spec.items():
        root = tmp_path / name
        if lesson:
            p = root / LESSON
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("a gate that cannot run must not pass\n")
        p = root / CODE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"def {NEEDLE}(): pass\n" if enforcer else "pass\n")
        roots.append({"name": name, "path": str(root)})
    registry = tmp_path / "instance-registry.json"
    registry.write_text(json.dumps({"instances": roots}))
    return registry


def test_claim_travelling_further_than_enforcer_goes_red(tmp_path):
    """P-4 exactly: lesson in 3 roots, enforcer in 1."""
    reg = build_claim_fleet(tmp_path, {
        "a": (True, True), "b": (True, False), "c": (True, False),
    })
    res = run(reg, "--claim", f"{LESSON}::{CODE}::{NEEDLE}")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "UNENFORCED" in res.stdout
    assert "claim reaches 3 root(s); enforcer" in res.stdout
    assert "reaches 1" in res.stdout
    assert str(tmp_path / "b") in res.stdout


def test_claim_matched_by_enforcer_is_green(tmp_path):
    reg = build_claim_fleet(tmp_path, {"a": (True, True), "b": (True, True)})
    res = run(reg, "--claim", f"{LESSON}::{CODE}::{NEEDLE}")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "UNENFORCED" not in res.stdout


def test_enforcer_ahead_of_claim_is_green(tmp_path):
    """Code may ship before the doc. Only claim-ahead-of-enforcer is the defect."""
    reg = build_claim_fleet(tmp_path, {"a": (True, True), "b": (False, True)})
    res = run(reg, "--claim", f"{LESSON}::{CODE}::{NEEDLE}")
    assert res.returncode == 0, res.stdout + res.stderr


def test_claim_mode_ignores_unrelated_replica_drift(tmp_path):
    """A --claim run must not red on hash drift it was not asked about.

    Both roots carry the lesson AND the enforcer, but their prd_runner.py bytes
    differ. If claim mode fell through to the replica scan this would be red, and
    a check whose failure does not name what you asked about reads as noise.
    """
    reg = build_claim_fleet(tmp_path, {"a": (True, True), "b": (True, True)})
    (tmp_path / "b" / CODE).write_text(f"def {NEEDLE}(): pass\n# drift\n")
    res = run(reg, "--claim", f"{LESSON}::{CODE}::{NEEDLE}")
    assert res.returncode == 0, res.stdout + res.stderr


def test_malformed_claim_spec_is_reported(tmp_path):
    reg = build_claim_fleet(tmp_path, {"a": (True, True)})
    res = run(reg, "--claim", "only::two")
    assert "must be 'claim::enforcer::needle'" in res.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
