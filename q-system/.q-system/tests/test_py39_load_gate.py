#!/usr/bin/env python3
"""Tests for py39_load_gate.py (ASK-4230).

The gate's whole job is to turn the PR #668 class red before it merges, so the
first test here is the fixture from the issue: an unquoted `-> str | None` in
linear-sync.py. The second is the negative self-test the DoR asks for: an empty
file list must FAIL, because an empty list is a broken collector and a gate that
checks nothing passes everything.
"""

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GATE = ROOT / "q-system" / ".q-system" / "scripts" / "py39_load_gate.py"


def _version_of(candidate):
    try:
        out = subprocess.run(
            [candidate, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def find_py39():
    """A real 3.9 interpreter, or fail loudly.

    NO skipTest here on purpose. dc-25's scar: a design-chain test with no
    browser called skipTest, the file exited 0, and the capability gate read
    green over tests that never ran. A 3.9 gate with no 3.9 interpreter is
    untested, not satisfied.
    """
    for cand in ("python3.9", "/usr/bin/python3", "python3", sys.executable):
        if _version_of(cand) == "3.9":
            return cand
    pytest.fail(
        "no Python 3.9 interpreter found (tried python3.9, /usr/bin/python3, "
        "python3, sys.executable). This gate cannot be tested without one; in "
        "CI it comes from actions/setup-python 3.9."
    )


@pytest.fixture(scope="module")
def gate():
    sys.path.insert(0, str(GATE.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("py39_load_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def collected(gate):
    files, plists, seeds = gate.collect(str(ROOT))
    return files, plists, seeds


# ---------------------------------------------------------------- the fixture

UNQUOTED = textwrap.dedent(
    """
    class Thing:
        def refusal(self) -> str | None:
            return None
    """
)

QUOTED = textwrap.dedent(
    """
    class Thing:
        def refusal(self) -> "str | None":
            return None
    """
)


def test_the_pr668_annotation_fails_the_load(gate, tmp_path):
    py39 = find_py39()
    target = tmp_path / "fixture.py"
    target.write_text(UNQUOTED)
    ok, detail = gate.load_one(py39, str(tmp_path), "fixture.py", 60)
    assert not ok, "an unquoted PEP 604 union loaded under 3.9; the gate is blind"
    assert "unsupported operand type" in detail
    assert gate.blame_line(detail, "fixture.py") == "fixture.py:3"


def test_the_quoted_annotation_loads(gate, tmp_path):
    py39 = find_py39()
    (tmp_path / "fixture.py").write_text(QUOTED)
    ok, detail = gate.load_one(py39, str(tmp_path), "fixture.py", 60)
    assert ok, detail


def test_py_compile_alone_would_not_have_caught_it(tmp_path):
    """Why this gate LOADS instead of compiling.

    If py_compile caught the class, the gate could be a syntax check and skip
    every side effect. It does not: `str | None` is legal 3.9 syntax and the
    TypeError comes from evaluating it. This test is the receipt for that
    design decision, so nobody simplifies the gate back into a compile.
    """
    py39 = find_py39()
    target = tmp_path / "fixture.py"
    target.write_text(UNQUOTED)
    compiled = subprocess.run(
        [py39, "-m", "py_compile", str(target)],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert compiled.returncode == 0, (
        "py_compile rejected the fixture; the premise of this gate changed"
    )


def test_main_exits_mid_import_is_not_run(gate, tmp_path):
    """A script's main() must not run during the probe."""
    py39 = find_py39()
    (tmp_path / "fixture.py").write_text(textwrap.dedent(
        """
        import sys
        def main():
            raise SystemExit(9)
        if __name__ == "__main__":
            main()
        """
    ))
    ok, detail = gate.load_one(py39, str(tmp_path), "fixture.py", 60)
    assert ok, detail


def test_a_dataclass_loads_under_the_probe(gate, tmp_path):
    """The sentinel module is registered in sys.modules.

    Measured 2026-11-09: without the registration, @dataclass on 3.9 resolves a
    field type through sys.modules.get(cls.__module__), gets None, and three
    healthy scripts failed with AttributeError. This pins the fix.
    """
    py39 = find_py39()
    (tmp_path / "fixture.py").write_text(textwrap.dedent(
        """
        from dataclasses import dataclass
        @dataclass
        class Row:
            name: str
            count: int = 0
        """
    ))
    ok, detail = gate.load_one(py39, str(tmp_path), "fixture.py", 60)
    assert ok, detail


# -------------------------------------------------------- the negative self-test

def test_an_empty_file_list_fails_the_gate(gate, monkeypatch, capsys):
    """The DoR's negative self-test: a broken list cannot read green."""
    monkeypatch.setattr(gate, "collect", lambda root: ([], [], []))
    rc = gate.main(["--repo-root", str(ROOT), "--python", "python3"])
    assert rc == 2, "an empty list passed; the gate would pass every PR"
    err = capsys.readouterr().err
    assert "collected 0 files" in err


# ------------------------------------------------------------------ collection

def test_the_list_is_not_empty_and_names_the_shared_module(collected):
    files, plists, seeds = collected
    assert plists, "no com.kipi.*.plist found; the collector lost its authority"
    assert files
    assert "q-system/.q-system/scripts/linear-sync.py" in files, (
        "linear-sync.py is the module PR #668 broke; the DoR names it explicitly"
    )


def test_every_plist_named_python_file_is_in_the_list(collected):
    """The seeds the plists name directly are all checked."""
    files, plists, seeds = collected
    direct = [s for s in seeds if s.endswith(".py")]
    assert direct, "no plist named a .py file; the placeholder stripping broke"
    missing = [s for s in direct
               if s not in files
               and not re.search(r"(^|/)(tests?)/|(^|/)test[_-]", s)]
    assert not missing, missing


def test_test_files_and_package_members_are_excluded(collected):
    files, _, _ = collected
    assert not [f for f in files if re.search(r"(^|/)test[_-]", os.path.basename(f))], (
        "a pytest file is in the list; launchd runs none, and they fail on "
        "import pytest under /usr/bin/python3"
    )
    assert not [f for f in files if f.startswith("plugins/kipi-core/voiceloop/")], (
        "a package member is in the list; exec'ing one standalone breaks its "
        "relative imports, which is a probe artifact, not a 3.9 defect"
    )


def test_the_whole_gate_is_green_on_this_tree():
    """The gate must pass on its own population.

    A gate that is red the day it lands is a gate someone switches off, and then
    it protects nothing. This is the pass half of the red/green pair; the red
    half is test_the_pr668_annotation_fails_the_load above.
    """
    py39 = find_py39()
    proc = subprocess.run(
        [sys.executable, str(GATE), "--repo-root", str(ROOT), "--python", py39],
        capture_output=True, text=True, cwd=str(ROOT), timeout=900,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
