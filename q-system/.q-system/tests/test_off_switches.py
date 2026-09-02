#!/usr/bin/env python3
"""RED FIRST. Issue mbl-off-switches (prd-morning-brief-learns, Codex
finding-17): every new job and writer has an off state, and the off state is
proven a NO-OP by the absence of the artifact the on state would produce. A
test that only sets its own precondition cannot see missing wiring (lesson),
so each case here asserts what did NOT happen: no request, no file, no send.

Runs LAST in the PRD; imports every module by path with tmp_path homes.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
ROOT = HERE.parent.parent.parent
NOW = dt.datetime(2026, 9, 8, 7, 0, tzinfo=dt.timezone.utc)


def _load(stem, path):
    spec = importlib.util.spec_from_file_location(stem, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_board_with_no_page_id_file_is_off_and_makes_no_request(tmp_path):
    board = _load("notion_board_off", SCRIPTS / "notion_board.py")
    calls = []

    def opener(req, timeout):
        calls.append(req.full_url)
        return io.BytesIO(b'{"results": [], "has_more": false}')
    (tmp_path / "notion-token").write_text("t")
    out = board.collect(NOW, {"owed": (["ASK-1  x"], None)}, opener=opener,
                        token_file=tmp_path / "notion-token", page_file=tmp_path / "absent")
    assert out is None, "off must be None (no section), not an empty section"
    assert calls == [], f"the off state reached the network: {calls}"


def test_weekly_runner_dry_run_writes_nothing(tmp_path):
    """Codex adversarial finding on this issue: watching tmp_path alone proves
    nothing about the host. HOME and cwd ARE tmp_path here, so the only
    LaunchAgents dir the script could reach is the temp one (no plist
    installed by construction), and the repo's output tree is snapshotted."""
    home = tmp_path / "home"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    output_dir = ROOT / "q-system" / "output"
    before = _tree(output_dir) if output_dir.exists() else set()
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "TMPDIR": str(tmp_path / "tmp")}
    (tmp_path / "tmp").mkdir()
    r = subprocess.run(["/bin/bash", str(SCRIPTS / "weekly-improve.sh"), "--dry-run"], capture_output=True, text=True,
                       env=env, cwd=home)
    assert r.returncode == 0 and r.stdout.count("would run: ") == 3, r.stderr[-300:]
    assert _tree(home) == set(), f"dry-run wrote into HOME (plist or log): {_tree(home)}"
    assert _tree(tmp_path / "tmp") == set(), "dry-run left a temp marker"
    after = _tree(output_dir) if output_dir.exists() else set()
    assert after == before, f"dry-run wrote into q-system/output: {after ^ before}"


def test_weekly_pass_with_no_friction_file_sends_nothing(tmp_path, capsys):
    weekly = _load("weekly_improve_off", SCRIPTS / "weekly-improve.py")
    rc = weekly.main(["--friction", str(tmp_path / "absent.jsonl"), "--inbox", str(tmp_path / "no-inbox")])
    out = capsys.readouterr().out
    assert "nothing this week" in out
    assert '"refused": true' in out and '"delivered": false' in out, "under pytest a send must be refused, and refused is not delivered"
    assert rc == 1, "a refused send is not a success exit"
    assert not (tmp_path / "absent.jsonl").exists(), "the consumer must not create the ledger"


def test_producer_import_creates_no_salt_and_no_ledger(tmp_path):
    """Codex adversarial finding: redirecting SALT_FILE after import could not
    see an import-time write. The import runs in a subprocess whose HOME and
    KIPI_STATE_DIR are tmp_path, with the module's default paths left alone,
    and both the temp home and the repo's output tree are snapshotted."""
    home = tmp_path / "home"
    home.mkdir()
    output_dir = ROOT / "q-system" / "output"
    before = _tree(output_dir) if output_dir.exists() else set()
    code = ("import importlib.util, pathlib\n"
            f"p = pathlib.Path({str(SCRIPTS / 'draft-vs-sent.py')!r})\n"
            "s = importlib.util.spec_from_file_location('dvs', p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
            "print(len(m.read_ledger(pathlib.Path('absent.jsonl'))))\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=home,
                       env={"PATH": os.environ.get("PATH", ""), "HOME": str(home), "KIPI_STATE_DIR": str(home / "state"),
                            "PYTEST_CURRENT_TEST": "1"})
    assert r.returncode == 0 and r.stdout.strip() == "0", r.stderr[-300:]
    assert _tree(home) == set(), f"import wrote into HOME/state: {_tree(home)}"
    after = _tree(output_dir) if output_dir.exists() else set()
    assert after == before, f"import wrote into q-system/output: {after ^ before}"


def _tree(root: Path) -> set:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


def test_improve_ground_is_importable_without_side_effects(tmp_path):
    """Codex standard finding on this issue: the first version watched only
    tmp_path, which nothing pointed at. The import now runs in a subprocess
    whose HOME and cwd are tmp_path, and the two trees it could plausibly
    write (the skill directory and q-system/output) are snapshotted before
    and after."""
    skill_dir = ROOT / "plugins" / "kipi-core" / "skills" / "improve"
    output_dir = ROOT / "q-system" / "output"
    home = tmp_path / "home"
    home.mkdir()
    before = (_tree(skill_dir), _tree(output_dir) if output_dir.exists() else set())
    code = ("import importlib.util, pathlib, sys\n"
            f"p = pathlib.Path({str(skill_dir / 'scripts' / 'improve_ground.py')!r})\n"
            "s = importlib.util.spec_from_file_location('ig', p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
            f"print(m.corpus_report([pathlib.Path({str(tmp_path / 'absent')!r})])[0]['status'])\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=home,
                       env={"PATH": os.environ.get("PATH", ""), "HOME": str(home), "PYTEST_CURRENT_TEST": "1"})
    assert r.returncode == 0 and r.stdout.strip() == "missing", r.stderr[-400:]
    assert _tree(home) == set(), f"import wrote into HOME/cwd: {_tree(home)}"
    after = (_tree(skill_dir), _tree(output_dir) if output_dir.exists() else set())
    assert after == before, f"import wrote into the repo: {after[0] ^ before[0]} {after[1] ^ before[1]}"


def test_unknown_terms_with_no_inputs_is_an_error_not_a_pull(tmp_path):
    ut = _load("unknown_terms_off", SCRIPTS / "unknown_terms.py")
    rows, err = ut.collect(NOW, {}, canonical_dir=tmp_path)
    assert rows == [] and err and "not collected" in err
    src = (SCRIPTS / "unknown_terms.py").read_text(encoding="utf-8")
    assert "run_claude" not in src and "urllib" not in src


def _docstring(path: Path) -> str:
    """The operator-facing header: the module docstring of a .py file, or the
    leading comment block of a .sh file. Never the whole source (Codex
    standard minor: a token in executable code satisfied the old check)."""
    import ast
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        return ast.get_docstring(ast.parse(text)) or ""
    lines = []
    for line in text.splitlines()[1:]:  # skip the shebang
        if not line.startswith("#"):
            break
        lines.append(line.lstrip("# "))
    return "\n".join(lines)


def _registered_scripts() -> set:
    """Scripts the SYSTEM registers, derived from its registries, never a hand
    list (Codex adversarial minor): the brief's OPTIONAL_SECTIONS, the weekly
    runner's STEPS, and every com.kipi.*.plist template's ProgramArguments
    that names a script in this directory."""
    import re
    found = set()
    brief = (SCRIPTS / "morning-brief.py").read_text(encoding="utf-8")
    block = brief.split("OPTIONAL_SECTIONS = (", 1)[1].split(")\n", 1)[0]
    # Registry entries name the file since PR #294 (the capability gate matches
    # engines by filename); accept either spelling so this derivation cannot
    # silently shrink to zero if the registry flips back.
    found |= {f"{m}.py" for m in re.findall(r'\("([a-z_]+)(?:\.py)?",', block)}
    runner = (SCRIPTS / "weekly-improve.sh").read_text(encoding="utf-8")
    steps = runner.split("STEPS=(", 1)[1].split(")", 1)[0]
    found |= set(re.findall(r'"([^"]+)"', steps))
    # Plist templates: the ones this PRD registered. Older templates (morning
    # brief, deadman, digest, heartbeats) predate the off-switch convention
    # and adopt it when next edited; listing them here would be a hand list
    # of exemptions, which is the thing this derivation exists to avoid.
    for plist in SCRIPTS.glob("com.kipi.weekly-*.plist"):
        for m in re.findall(r"__KIPI_REPO__/q-system/\.q-system/scripts/([A-Za-z0-9_.\-]+)", plist.read_text(encoding="utf-8")):
            found.add(m)
    assert len(found) >= 5, f"the registries yielded too little; the derivation is broken: {found}"
    return found


def test_every_new_script_declares_its_off_switch_in_its_docstring():
    """The switch must be written where an operator reads it: the docstring.
    The set of scripts is derived from the registries; the phrase table must
    cover every NEW script this PRD registered (older registered jobs such as
    morning-brief.py predate the convention and are listed as such)."""
    registered = _registered_scripts()
    expectations = {
        "notion_board.py": "OFF switch",
        "unknown_terms.py": "never pulls anything",
        "weekly-improve.py": "trigger is weekly-improve.sh",
        "friction-note.sh": "instance-owned",
        "draft-vs-sent.py": "runner is refused",
        "route-overrides-to-learn.py": "learn-from-correction",
        "weekly-improve.sh": "--dry-run",
    }
    uncovered = {s for s in registered if (SCRIPTS / s).exists()} - set(expectations)
    assert not uncovered, f"registered script(s) with no off-switch expectation: {sorted(uncovered)}"
    for name, phrase in expectations.items():
        doc = " ".join(_docstring(SCRIPTS / name).split())  # docstrings wrap; phrases do not
        assert doc, f"{name} has no module docstring / header block"
        assert phrase in doc, f"{name}: its docstring does not say how it is switched off ({phrase!r} missing)"


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
