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


def _need_index():
    """Build isolation fetches setuptools from the index. Offline FAILS, always: a skip
    printed nowhere under verify.sh (pytest without -rs), and the opt-out env var that
    first replaced it left the same hole (review of PR 856, r2 finding 2, r3 minor 4)."""
    try:
        socket.create_connection(("pypi.org", 443), timeout=3).close()
    except OSError:
        pytest.fail("pypi.org unreachable: pip cannot fetch setuptools for the build")


def test_import_fails_without_the_install(venv, tmp_path):
    # Negative control: the probe must be able to fail in this venv.
    r = _run([str(venv), "-I", "-c", PROBE], cwd=tmp_path)
    assert r.returncode != 0
    assert "No module named 'voiceloop'" in r.stderr


def test_editable_install_provides_voiceloop(venv, tmp_path):
    _need_index()
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


@pytest.mark.parametrize("editable", [True, False])
def test_install_leaves_a_checkout_clean(venv, tmp_path, editable):
    # A real install into a git checkout that carries THIS repo's .gitignore: egg-info
    # (editable) and build/ (wheel path) must both be ignored, or auto-commit sweeps
    # generated files (PR 856 r1 finding 2, r2 findings 3 and 4).
    _need_index()
    repo = tmp_path / "repo"
    shutil.copytree(CORE, repo / "plugins" / "kipi-core",
                    ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "build"))
    shutil.copy(ROOT / ".gitignore", repo / ".gitignore")
    g = ["git", "-C", str(repo)]
    assert _run(g + ["init", "-q"]).returncode == 0
    assert _run(g + ["add", "-A"]).returncode == 0
    assert _run(g + ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                     "-c", "core.hooksPath=/dev/null",  # a machine-wide hooksPath must not run in the fixture
                    
                     "commit", "-qm", "base"]).returncode == 0
    cmd = [str(venv), "-m", "pip", "install", "-q"] + (["-e"] if editable else []) + [str(repo / "plugins" / "kipi-core")]
    r = _run(cmd)
    assert r.returncode == 0, r.stdout + r.stderr
    st = _run(g + ["status", "--porcelain"]).stdout
    assert st == "", f"install dirtied the checkout:\n{st}"


def test_a_shadowing_voice_loop_wins_until_it_is_uninstalled(venv, tmp_path):
    """The migration trap (PR 856 r2 finding 1): chief's venvs already hold the retired
    `voice-loop` dist, which ships the SAME top-level `voiceloop`. A regular
    site-packages copy outranks an editable finder, so installing kipi-voiceloop on top
    exits 0 and the import still runs the mirror. Pinned so the cure is in the open:
    `pip uninstall -y voice-loop` first (chief's installer does it, ASK-5450)."""
    _need_index()
    shadow = tmp_path / "shadow"
    (shadow / "voiceloop").mkdir(parents=True)
    (shadow / "voiceloop" / "__init__.py").write_text("")
    (shadow / "voiceloop" / "usage_ledger.py").write_text("STALE_MIRROR = True\n")
    (shadow / "pyproject.toml").write_text(
        '[build-system]\nrequires=["setuptools>=68"]\nbuild-backend="setuptools.build_meta"\n'
        '[project]\nname="voice-loop"\nversion="0.2.0"\n[tool.setuptools]\npackages=["voiceloop"]\n')
    pip = [str(venv), "-m", "pip", "install", "-q"]
    assert _run(pip + [str(shadow)]).returncode == 0
    src = tmp_path / "kipi-core"
    shutil.copytree(CORE, src, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "build"))
    assert _run(pip + ["-e", str(src)]).returncode == 0
    r = _run([str(venv), "-I", "-c", PROBE], cwd=tmp_path)
    assert "site-packages" in r.stdout, f"expected the shadow to win, got {r.stdout}"
    # `voice-loop` is the mirror's real dist name (voice_loop-0.2.0.dist-info in chief's
    # venv, name in ~/projects/voice-loop/pyproject.toml). uninstall exits 0 when the
    # name matches nothing, so assert the dist was present before and gone after.
    show = [str(venv), "-m", "pip", "show", "voice-loop"]
    assert _run(show).returncode == 0
    assert _run([str(venv), "-m", "pip", "uninstall", "-q", "-y", "voice-loop"]).returncode == 0
    assert _run(show).returncode != 0
    r = _run([str(venv), "-I", "-c", PROBE], cwd=tmp_path)
    assert Path(r.stdout.strip()).is_relative_to(src), r.stdout + r.stderr
