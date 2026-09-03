#!/usr/bin/env python3
"""Tests for fleet-replica-divergence.py.

EVERY CASE BUILDS ITS OWN FAKE FLEET IN A TMPDIR. None of these read the real
instance-registry.json or any real instance. A test that pointed at the live
registry would pass or fail based on whatever the fleet happens to hold today,
which is a test that cannot be trusted in either direction (and the
fable-discipline lint blocks tests that touch a live data path).

The exit codes are deliberately distinct so a control cannot pass by accident:
  0 = agreement, 1 = divergence/unenforced found, 2 = refused (empty
  population), 3 = refused (the run was asked for something it cannot evaluate).
An earlier draft treated "nonzero" as the assertion, which would have accepted
the empty-population refusal as a successful divergence detection.

3 is separate from 2 for the same reason: "I could not evaluate your spec" and
"your fleet is empty" are different repairs, and the kipi-update preflight needs
"the gate ran and refused" to be distinguishable from "the gate did not run".
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fleet-replica-divergence.py"
REL = "plugins/prd-os/scripts/prd_runner.py"
VERDICT = "fleet replica divergence: "


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


def test_malformed_claim_spec_refuses_rather_than_reporting_green(tmp_path):
    """The defect this suite previously failed to pin.

    The original case asserted only that stderr MENTIONED the usage line. It
    passed against code that printed the message, reported "claims checked: 0"
    and exited 0 -- so a one-character typo in the kipi-update wiring would have
    made this gate permanently green while announcing it had run. The assertion
    that matters is the exit code, not the text.
    """
    reg = build_claim_fleet(tmp_path, {"a": (True, True)})
    res = run(reg, "--claim", "only::two")
    assert res.returncode == 3, res.stdout + res.stderr
    assert "must be 'claim::enforcer::needle'" in res.stderr
    assert "claims checked: 1" not in res.stdout


@pytest.mark.parametrize("spec", [
    "only::two",
    "a::b::c::d",
    "::{code}::{needle}",
    "{lesson}::::{needle}",
    "{lesson}::{code}::",
])
def test_every_unevaluable_claim_shape_refuses(tmp_path, spec):
    """One assertion over the CLASS, not one test per shape it occurred in."""
    reg = build_claim_fleet(tmp_path, {"a": (True, True)})
    res = run(reg, "--claim", spec.format(lesson=LESSON, code=CODE, needle=NEEDLE))
    assert res.returncode == 3, f"{spec}: {res.stdout}{res.stderr}"


def test_claim_naming_a_path_in_no_root_refuses(tmp_path):
    """A claim file that exists nowhere scores a meaningless permanent green."""
    reg = build_claim_fleet(tmp_path, {"a": (True, True), "b": (True, True)})
    res = run(reg, "--claim", f"q-system/lessons/typo.md::{CODE}::{NEEDLE}")
    assert res.returncode == 3, res.stdout + res.stderr
    assert "0 of 2 roots" in res.stderr


def test_replicated_path_in_no_root_refuses(tmp_path):
    """The same defect in the replica half, which is where it was LIVE.

    `plugins/kipi-core/scripts/rca-lint.py` was in DEFAULT_REPLICATED from the
    first commit and resolved to 0 of 29 real roots (the real path is under
    skills/rca/). scan() dropped it silently, so the tool printed "checked: 3"
    and checked two.
    """
    reg = build_fleet(tmp_path, {"a": "same\n", "b": "same\n"})
    # Paired with a path that DOES resolve. A dead path on its own means "this
    # population has no replicated content", which disarms by design; the error
    # is a dead path sitting alongside live ones, claiming coverage it lacks.
    res = run(reg, "--path", REL, "--path", "plugins/nope/does-not-exist.py")
    assert res.returncode == 3, res.stdout + res.stderr
    assert "0 of 2 roots" in res.stderr


def test_population_with_no_replicated_content_disarms_out_loud(tmp_path):
    """Every kipi-update fixture builds exactly this population.

    Refusing here would red the gate on 11 existing tests for a reason unrelated
    to divergence, and a gate unsatisfiable for its own population gets switched
    off. It disarms -- but says so, and still prints a verdict, so the preflight
    can still tell "ran and disarmed" from "did not run".
    """
    reg = build_fleet(tmp_path, {"a": "same\n", "b": "same\n"})
    res = run(reg, "--path", "plugins/nope/a.py", "--path", "plugins/nope/b.py")
    assert res.returncode == 0, res.stdout + res.stderr
    assert f"{VERDICT}DISARMED" in res.stdout


def test_disarm_does_not_swallow_a_real_divergence(tmp_path):
    """The disarm branch must not be reachable while a live path is diverging."""
    reg = build_fleet(tmp_path, {"a": "same\n", "b": "different\n"})
    res = run(reg, "--path", REL, "--path", "plugins/nope/a.py")
    assert res.returncode == 3, res.stdout + res.stderr
    assert "DISARMED" not in res.stdout


def test_a_dead_path_does_not_hide_behind_a_live_one(tmp_path):
    """Mixed set: the live path is green, so only the dead one can make it red."""
    reg = build_fleet(tmp_path, {"a": "same\n", "b": "same\n"})
    ok = run(reg, "--path", REL)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    res = run(reg, "--path", REL, "--path", "plugins/nope/does-not-exist.py")
    assert res.returncode == 3, res.stdout + res.stderr


@pytest.mark.parametrize("expected_rc,args_fn", [
    (0, lambda: ("--path", REL)),
    (3, lambda: ("--path", REL, "--path", "plugins/nope/does-not-exist.py")),
])
def test_verdict_line_is_printed_on_every_outcome(tmp_path, expected_rc, args_fn):
    """The kipi-update preflight aborts when this line is absent.

    It is proof of EXECUTION: a truncated copy of the script is a valid program
    that exits 0 silently, and `[ -f ]` cannot tell it from a working gate. So
    the line has to appear on refusals too, or a refusal reads as a dead gate.
    """
    reg = build_fleet(tmp_path, {"a": "same\n", "b": "same\n"})
    res = run(reg, *args_fn())
    assert res.returncode == expected_rc, res.stdout + res.stderr
    assert any(l.startswith(VERDICT) for l in res.stdout.splitlines()), res.stdout


def test_verdict_line_is_printed_when_diverged(tmp_path):
    reg = build_fleet(tmp_path, {"a": "same\n", "b": "different\n"})
    res = run(reg, "--path", REL)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"{VERDICT}DIVERGED" in res.stdout


def test_verdict_line_is_printed_on_empty_population(tmp_path):
    reg = tmp_path / "instance-registry.json"
    reg.write_text(json.dumps({"instances": []}))
    res = run(reg, "--path", REL)
    assert res.returncode == 2, res.stdout + res.stderr
    assert f"{VERDICT}REFUSED" in res.stdout


def test_default_replicated_paths_all_resolve_in_the_real_fleet():
    """Every DECLARED path must resolve somewhere, or its green is decoration.

    Reads the real registry deliberately: the claim under test is about the
    REAL fleet, and a tmpdir cannot make it. Read-only -- it hashes nothing and
    writes nothing (the fable-discipline lint exempts assertion lines).
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("frd", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    registry = SCRIPT.resolve().parents[3] / "instance-registry.json"
    if not registry.is_file():
        pytest.skip("no real registry here")
    roots = mod.registry_roots(registry)
    if not roots:
        pytest.skip("registry resolved no roots")
    dead = [rel for rel in mod.DEFAULT_REPLICATED
            if not any((Path(r) / rel).is_file() for r in roots)]
    assert not dead, f"declared but present in 0/{len(roots)} roots: {dead}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
