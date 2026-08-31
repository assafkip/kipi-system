"""Tests for plugin-parity-check.py (ASK-721).

The check's whole job is to go RED when the marketplace clone lags the skeleton.
A check that cannot go GREEN is useless, and a check that cannot go RED is a lie,
so both directions are pinned here against built fixtures -- never against the
live tree, which changes under the suite.

The mutation cases at the bottom are the point: each one makes ONE change to an
otherwise-green fixture and asserts the verdict flips. If any of them stays green,
the check is not measuring what its name says.
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
CHECK = os.path.join(REPO, "q-system", ".q-system", "scripts", "plugin-parity-check.py")


def write_plugin(root, name, version, files=None):
    """Build a minimal plugin tree: a manifest plus optional content files."""
    plugin_dir = os.path.join(root, "plugins", name)
    os.makedirs(os.path.join(plugin_dir, ".claude-plugin"), exist_ok=True)
    manifest = os.path.join(plugin_dir, ".claude-plugin", "plugin.json")
    with open(manifest, "w", encoding="utf-8") as handle:
        json.dump({"name": name, "version": version}, handle)
    for rel, body in (files or {}).items():
        target = os.path.join(plugin_dir, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(body)
    return plugin_dir


def run_check(skeleton, marketplace):
    proc = subprocess.run(
        [
            sys.executable,
            CHECK,
            "--skeleton",
            skeleton,
            "--marketplace",
            marketplace,
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    return proc.returncode, payload, proc.stderr


@pytest.fixture
def in_parity(tmp_path):
    """Two trees that agree on every plugin version AND every byte."""
    skeleton = tmp_path / "skeleton"
    clone = tmp_path / "clone"
    for root in (skeleton, clone):
        write_plugin(str(root), "prd-os", "0.27.0", {"scripts/runner.py": "ok\n"})
        write_plugin(str(root), "kipi-core", "1.6.0", {"skills/a/SKILL.md": "a\n"})
    return str(skeleton), str(clone)


def test_green_when_versions_agree(in_parity):
    """The control. Without this passing, every RED below proves nothing."""
    skeleton, clone = in_parity
    code, payload, _ = run_check(skeleton, clone)
    assert code == 0
    assert [r["status"] for r in payload["plugins"]] == ["MATCH", "MATCH"]


def test_green_fixture_has_no_advisory_drift(in_parity):
    """Guards the control itself: a fixture that already drifts would make the
    advisory numbers meaningless in every other case."""
    skeleton, clone = in_parity
    _, payload, _ = run_check(skeleton, clone)
    for row in payload["plugins"]:
        assert row["advisory_content"] == {
            "differing": 0,
            "missing": 0,
            "clone_only": 0,
        }


# --- mutation cases: one change each, verdict must flip ----------------------


def test_red_when_clone_version_lags(in_parity):
    """The ASK-721 shape itself: clone behind the skeleton."""
    skeleton, clone = in_parity
    write_plugin(clone, "prd-os", "0.25.1", {"scripts/runner.py": "ok\n"})
    code, payload, _ = run_check(skeleton, clone)
    assert code == 1
    row = next(r for r in payload["plugins"] if r["plugin"] == "prd-os")
    assert row["status"] == "MISMATCH"
    assert row["skeleton_version"] == "0.27.0"
    assert row["marketplace_version"] == "0.25.1"


def test_red_when_clone_version_leads(in_parity):
    """Parity is equality, not "clone >= skeleton". A clone AHEAD is also drift:
    it means the runtime carries code this repo never shipped."""
    skeleton, clone = in_parity
    write_plugin(clone, "prd-os", "9.9.9", {"scripts/runner.py": "ok\n"})
    code, payload, _ = run_check(skeleton, clone)
    assert code == 1
    row = next(r for r in payload["plugins"] if r["plugin"] == "prd-os")
    assert row["status"] == "MISMATCH"


def test_red_when_plugin_absent_from_clone(tmp_path):
    """A plugin the runtime has never seen at all. Reported as MISSING, not
    silently skipped -- skipping is how a never-deployed plugin reads as fine."""
    skeleton = tmp_path / "skeleton"
    clone = tmp_path / "clone"
    write_plugin(str(skeleton), "prd-os", "0.27.0")
    write_plugin(str(clone), "kipi-core", "1.6.0")
    code, payload, _ = run_check(str(skeleton), str(clone))
    assert code == 1
    row = next(r for r in payload["plugins"] if r["plugin"] == "prd-os")
    assert row["status"] == "MISSING"
    assert row["marketplace_version"] is None


def test_every_plugin_is_compared_not_just_the_first(tmp_path):
    """The defect was found in prd-os; kipi-core was stale too and nobody looked.
    A check that stops at the first mismatch would have repeated that."""
    skeleton = tmp_path / "skeleton"
    clone = tmp_path / "clone"
    write_plugin(str(skeleton), "prd-os", "0.27.0")
    write_plugin(str(skeleton), "kipi-core", "1.6.0")
    write_plugin(str(skeleton), "kipi-ops", "1.2.0")
    write_plugin(str(clone), "prd-os", "0.25.1")
    write_plugin(str(clone), "kipi-core", "1.5.26")
    write_plugin(str(clone), "kipi-ops", "1.2.0")
    code, payload, _ = run_check(str(skeleton), str(clone))
    assert code == 1
    statuses = {r["plugin"]: r["status"] for r in payload["plugins"]}
    assert statuses == {
        "prd-os": "MISMATCH",
        "kipi-core": "MISMATCH",
        "kipi-ops": "MATCH",
    }


# --- the deliberate non-gate, pinned so nobody "fixes" it by accident --------


def test_content_drift_is_advisory_and_does_not_fail(in_parity):
    """Byte drift with matching versions stays GREEN, and the count is reported.

    This is the trade documented in the module docstring: nothing in this repo can
    delete a file inside .claude/, so gating on byte-equality would make green
    unreachable and the check would get switched off. The advisory count is the
    only signal for a version bumped without its content."""
    skeleton, clone = in_parity
    target = os.path.join(clone, "plugins", "prd-os", "scripts", "runner.py")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("DRIFTED\n")
    with open(os.path.join(clone, "plugins", "prd-os", "stray.bak"), "w") as handle:
        handle.write("x\n")

    code, payload, _ = run_check(skeleton, clone)
    assert code == 0, "content drift must not fail the gate"
    row = next(r for r in payload["plugins"] if r["plugin"] == "prd-os")
    assert row["status"] == "MATCH"
    assert row["advisory_content"]["differing"] == 1
    assert row["advisory_content"]["clone_only"] == 1


def test_pycache_is_not_counted_as_drift(in_parity):
    """A working checkout always has __pycache__. Counting it would bury the real
    advisory numbers in noise."""
    skeleton, clone = in_parity
    cache = os.path.join(clone, "plugins", "prd-os", "scripts", "__pycache__")
    os.makedirs(cache, exist_ok=True)
    with open(os.path.join(cache, "runner.cpython-311.pyc"), "wb") as handle:
        handle.write(b"\x00\x01")
    code, payload, _ = run_check(skeleton, clone)
    assert code == 0
    row = next(r for r in payload["plugins"] if r["plugin"] == "prd-os")
    assert row["advisory_content"]["clone_only"] == 0


def test_non_plugin_directory_is_skipped(tmp_path):
    """A directory under plugins/ with no manifest is not a plugin. Treating it
    as MISSING would make the check permanently red on stray scratch dirs."""
    skeleton = tmp_path / "skeleton"
    clone = tmp_path / "clone"
    write_plugin(str(skeleton), "prd-os", "0.27.0")
    write_plugin(str(clone), "prd-os", "0.27.0")
    os.makedirs(os.path.join(str(skeleton), "plugins", "scratch"), exist_ok=True)
    code, payload, _ = run_check(str(skeleton), str(clone))
    assert code == 0
    assert [r["plugin"] for r in payload["plugins"]] == ["prd-os"]


def test_missing_plugins_dir_exits_2_not_0(tmp_path):
    """"Nothing to compare" must never read as "everything is in parity"."""
    skeleton = tmp_path / "empty"
    skeleton.mkdir()
    clone = tmp_path / "clone"
    write_plugin(str(clone), "prd-os", "0.27.0")
    proc = subprocess.run(
        [sys.executable, CHECK, "--skeleton", str(skeleton), "--marketplace", str(clone)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "CHECK FAILED TO RUN" in proc.stderr
