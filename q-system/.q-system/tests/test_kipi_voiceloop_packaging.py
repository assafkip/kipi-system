"""ASK-5450: `pip install -e <kipi-system>/plugins/kipi-core` provides `voiceloop`.

Why this exists: founder, 2026-11-18, "We don't need the mirror". Chief used to
install the engine from github.com/assafkip/voice-loop (a third copy). Without a
pyproject in plugins/kipi-core there is nothing for chief to install from
kipi-system, so the mirror could not be retired (ASK-2181, ASK-4025).

Isolation: the venv lives in a pytest tmp dir. The editable install points at
THIS checkout's plugins/kipi-core, read-only (setuptools writes its egg-info
into the source dir, so it is installed from a copy of the package tree).
The interpreter runs with -I and a tmp cwd so a stray cwd or PYTHONPATH cannot
make the import succeed without the install (the negative test below proves it).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "plugins" / "kipi-core"
PROBE = "from voiceloop import usage_ledger; print(usage_ledger.__file__)"


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


@pytest.fixture(scope="module")
def venv(tmp_path_factory):
    d = tmp_path_factory.mktemp("venv")
    r = _run([sys.executable, "-m", "venv", str(d / "v")])
    assert r.returncode == 0, r.stderr
    return d / "v" / "bin" / "python"


def test_import_fails_without_the_install(venv, tmp_path):
    # Negative control: the probe must be able to fail in this venv.
    r = _run([str(venv), "-I", "-c", PROBE], cwd=tmp_path)
    assert r.returncode != 0
    assert "No module named 'voiceloop'" in r.stderr


def test_editable_install_provides_voiceloop(venv, tmp_path):
    # Whole plugin dir, copied: setuptools' egg-info stays out of the tracked
    # tree, and the sibling dirs (hooks/, scripts/, skills/) are present so a
    # packaging that relies on auto-discovery fails here as it would in chief.
    src = tmp_path / "kipi-core"
    shutil.copytree(CORE, src, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "node_modules"))
    assert (CORE / "pyproject.toml").is_file(), "plugins/kipi-core/pyproject.toml missing"
    r = _run([str(venv), "-m", "pip", "install", "-q", "-e", str(src)])
    assert r.returncode == 0, r.stdout + r.stderr
    r = _run([str(venv), "-I", "-c", PROBE], cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert Path(r.stdout.strip()).name == "usage_ledger.py"
    assert Path(r.stdout.strip()).is_relative_to(src)


def test_pyproject_shape():
    data = tomllib.loads((CORE / "pyproject.toml").read_text())
    assert data["project"]["name"] == "kipi-voiceloop"
    assert data["project"]["version"] == "0.3.0"
    # Explicit: plugins/kipi-core also holds hooks/, scripts/, skills/, kipi-mcp/,
    # so auto-discovery aborts on a flat layout with several top-level dirs.
    assert data["tool"]["setuptools"]["packages"] == ["voiceloop"]
    assert not data["project"].get("dependencies")
