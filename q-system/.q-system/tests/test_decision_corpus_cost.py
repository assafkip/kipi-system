#!/usr/bin/env python3
"""RED FIRST. Issue mbl-two-measurements (plan 2h, Codex finding-16). The cost
script prints bytes and tokens = ceil(bytes / 4) with the formula in its
output, and exits 3 when KIPI_VOICE_DIR is unset or a corpus file is missing.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent / "scripts" / "decision-corpus-cost.py"


def _voice(tmp_path, sizes=(1054, 1850, 13221)):
    d = tmp_path / "voice"
    d.mkdir()
    for name, size in zip(("pov.md", "identity.md", "scars.md"), sizes):
        (d / name).write_bytes(b"x" * size)
    return d


def _run(env_extra, *args):
    env = {k: v for k, v in os.environ.items() if k != "KIPI_VOICE_DIR"}
    env.update(env_extra)
    return subprocess.run([sys.executable, str(MODULE), *args], capture_output=True, text=True, env=env)


def test_prints_bytes_tokens_and_the_formula(tmp_path):
    d = _voice(tmp_path)
    r = _run({"KIPI_VOICE_DIR": str(d)}, "--json")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["total_bytes"] == 1054 + 1850 + 13221
    assert out["total_tokens"] == math.ceil(out["total_bytes"] / 4)
    assert out["formula"] == "tokens = ceil(bytes / 4)"
    text = _run({"KIPI_VOICE_DIR": str(d)}).stdout
    assert "tokens = ceil(bytes / 4)" in text and "per turn" in text


def test_two_runs_agree_by_construction(tmp_path):
    d = _voice(tmp_path)
    a = _run({"KIPI_VOICE_DIR": str(d)}, "--json").stdout
    b = _run({"KIPI_VOICE_DIR": str(d)}, "--json").stdout
    assert a == b


def test_unset_env_exits_3(tmp_path):
    r = _run({})
    assert r.returncode == 3 and "KIPI_VOICE_DIR" in r.stderr


def test_missing_file_exits_3_not_a_partial_cost(tmp_path):
    d = _voice(tmp_path)
    (d / "scars.md").unlink()
    r = _run({"KIPI_VOICE_DIR": str(d)})
    assert r.returncode == 3 and "scars.md" in r.stderr


def test_this_file_runs_its_own_tests_under_python3():
    if os.environ.get("KIPI_SELFTEST_INNER"):
        pytest.skip("inner run")
    env = dict(os.environ, KIPI_SELFTEST_INNER="1")
    ok = subprocess.run([sys.executable, __file__], capture_output=True, text=True, env=env)
    assert ok.returncode == 0 and "passed" in ok.stdout, ok.stdout[-600:]
    none = subprocess.run([sys.executable, __file__, "-k", "no_such_test_zzz"], capture_output=True, text=True, env=env)
    assert none.returncode != 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
