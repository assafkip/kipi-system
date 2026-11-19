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
import socket
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


@pytest.fixture
def venv(tmp_path):
    # Function scope: one venv per test. A shared one made the negative control depend
    # on test order (an install-first order, or --ff -x after one failed install,
    # turned it red; review of PR 856, r1).
    r = _run([sys.executable, "-m", "venv", str(tmp_path / "v")])
    assert r.returncode == 0, r.stderr
    return tmp_path / "v" / "bin" / "python"


def _pypi_reachable():
    try:
        socket.create_connection(("pypi.org", 443), timeout=3).close()
        return True
    except OSError:
        return False


def test_import_fails_without_the_install(venv, tmp_path):
    # Negative control: the probe must be able to fail in this venv.
    r = _run([str(venv), "-I", "-c", PROBE], cwd=tmp_path)
    assert r.returncode != 0
    assert "No module named 'voiceloop'" in r.stderr


def test_editable_install_provides_voiceloop(venv, tmp_path):
    # Build isolation fetches setuptools from the index. Offline is a skip WITH its
    # reason, not a red on an unrelated change; CI always has the index.
    if not _pypi_reachable():
        pytest.skip("pypi.org unreachable: pip cannot fetch the build backend")
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


def test_install_does_not_dirty_the_checkout(venv, tmp_path):
    # The install runs on a copy, so assert the rule that keeps a real one clean:
    # setuptools' egg-info dir is ignored (an unignored one is auto-committable).
    r = _run(["git", "-C", str(ROOT), "check-ignore", "-q",
              "plugins/kipi-core/kipi_voiceloop.egg-info/PKG-INFO"])
    assert r.returncode == 0, "plugins/*/*.egg-info/ is not gitignored"
