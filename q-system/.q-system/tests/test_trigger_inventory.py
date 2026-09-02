#!/usr/bin/env python3
"""RED FIRST. Issue lr-trigger-inventory (prd-lessons-rail-and-up-rail, plan 4d,
CAP-2). Three stages were found built, correct and never running in one
session; one script name returned 184 hits in dead worktree copies. The
inventory derives its candidates from the TREE (every script under
q-system/.q-system/scripts/ and every repo-root *.sh), never from a hand list,
reads every registered trigger surface, closes over scripts that triggered
scripts name, and prints the scope it excluded with counts.

Fixture repos are built in tmp_path. The live-shape test copies the real
trigger surfaces into tmp and plants the pre-fix state (weekly-improve.sh
removed) so the known dead stage reappears.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
ROOT = HERE.parent.parent.parent
INVENTORY = SCRIPTS / "trigger-inventory.py"
PLIST = """<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>
<key>Label</key><string>{label}</string>
<key>ProgramArguments</key><array><string>/bin/bash</string><string>{prog}</string></array>
</dict></plist>"""


def _repo(tmp_path):
    r = tmp_path / "repo"
    s = r / "q-system" / ".q-system" / "scripts"
    s.mkdir(parents=True)
    (r / "q-system" / ".q-system" / "stages-exempt.json").write_text(json.dumps({"exempt": [
        {"path": "q-system/.q-system/scripts/e_lib.py", "reason": "imported by a_plist.py"}]}))
    (s / "a_plist.py").write_text("import c_transitive\n")
    (s / "b_hook.sh").write_text("echo hook\n")
    (s / "c_transitive.py").write_text("print('named by a_plist.py')\n")
    (s / "d_dead.py").write_text("print('nobody runs me')\n")
    (s / "e_lib.py").write_text("X = 1\n")
    (s / "f_lefthook.py").write_text("print('pre-commit')\n")
    (s / "h_manual.py").write_text("print('kipi only')\n")
    (s / "i_installed.py").write_text("print('installed plist only')\n")
    (r / "g_root.sh").write_text("echo root\n")
    (s / "com.kipi.a.plist").write_text(PLIST.format(label="com.kipi.a", prog="__KIPI_REPO__/q-system/.q-system/scripts/a_plist.py"))
    (r / ".claude").mkdir()
    (r / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [
        {"type": "command", "command": 'test -f "$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/b_hook.sh" && bash "$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/b_hook.sh"'}]}]}}))
    (r / "plugins" / "p" / "hooks").mkdir(parents=True)
    (r / "plugins" / "p" / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {}}))
    (r / ".github" / "workflows").mkdir(parents=True)
    (r / ".github" / "workflows" / "ci.yml").write_text("jobs:\n  x:\n    steps:\n      - run: bash g_root.sh\n")
    (r / "lefthook.yml").write_text("pre-commit:\n  commands:\n    f:\n      run: python3 q-system/.q-system/scripts/f_lefthook.py\n")
    (r / "kipi").write_text("#!/bin/bash\ncase \"$1\" in\n  manual) python3 q-system/.q-system/scripts/h_manual.py ;;\nesac\n")
    installed = tmp_path / "LaunchAgents"
    installed.mkdir()
    (installed / "com.kipi.i.plist").write_text(PLIST.format(label="com.kipi.i", prog=f"{r}/q-system/.q-system/scripts/i_installed.py"))
    # dead copies inside worktrees: must be counted as excluded, never as stages
    for wt in (r / ".claude" / "worktrees" / "old-1", r / ".wt-parity"):
        ws = wt / "q-system" / ".q-system" / "scripts"
        ws.mkdir(parents=True)
        (ws / "zombie_dead.py").write_text("print('dead copy')\n")
        (wt / "zombie_root.sh").write_text("echo dead copy\n")
    return r, installed


def _run(root, installed, *args):
    env = dict(os.environ, KIPI_INSTALLED_PLISTS=str(installed))
    return subprocess.run([sys.executable, str(INVENTORY), "--root", str(root), *args], capture_output=True, text=True, env=env)


def test_classifies_every_candidate_from_the_tree_not_a_list(tmp_path):
    r, installed = _repo(tmp_path)
    p = _run(r, installed, "--json")
    assert p.returncode == 0, p.stderr
    j = json.loads(p.stdout)
    by = {Path(k).name: v["status"] for k, v in j["stages"].items()}
    assert by["a_plist.py"] == "triggered" and by["b_hook.sh"] == "triggered" and by["f_lefthook.py"] == "triggered"
    assert by["g_root.sh"] == "triggered" and by["i_installed.py"] == "triggered"
    assert by["c_transitive.py"] == "triggered", "named by a triggered script"
    assert j["stages"]["q-system/.q-system/scripts/c_transitive.py"]["via"] == ["q-system/.q-system/scripts/a_plist.py"]
    assert by["h_manual.py"] == "manual-only"
    assert by["e_lib.py"] == "exempt"
    assert by["d_dead.py"] == "dead"
    assert j["dead"] == ["q-system/.q-system/scripts/d_dead.py"]


def test_an_unregistered_new_script_is_visible_without_any_registration(tmp_path):
    r, installed = _repo(tmp_path)
    (r / "q-system" / ".q-system" / "scripts" / "j_brand_new.py").write_text("print('nobody registered me')\n")
    j = json.loads(_run(r, installed, "--json").stdout)
    assert "q-system/.q-system/scripts/j_brand_new.py" in j["dead"]


def test_a_script_in_a_subdirectory_is_a_candidate(tmp_path):
    """Codex standard review: non-recursive globs silently omitted nested scripts."""
    r, installed = _repo(tmp_path)
    sub = r / "q-system" / ".q-system" / "scripts" / "sub"
    sub.mkdir()
    (sub / "k_nested.py").write_text("print('nested and unregistered')\n")
    j = json.loads(_run(r, installed, "--json").stdout)
    assert "q-system/.q-system/scripts/sub/k_nested.py" in j["dead"]


def test_a_yaml_workflow_is_a_trigger_surface(tmp_path):
    r, installed = _repo(tmp_path)
    (r / "q-system" / ".q-system" / "scripts" / "l_yaml.py").write_text("print('yaml')\n")
    (r / ".github" / "workflows" / "other.yaml").write_text("jobs:\n  y:\n    steps:\n      - run: python3 q-system/.q-system/scripts/l_yaml.py\n")
    j = json.loads(_run(r, installed, "--json").stdout)
    assert j["stages"]["q-system/.q-system/scripts/l_yaml.py"]["status"] == "triggered"


def test_a_shared_basename_does_not_let_one_trigger_cover_both(tmp_path):
    """Codex adversarial: root dup.sh and scripts/dup.sh were indistinguishable."""
    r, installed = _repo(tmp_path)
    (r / "dup.sh").write_text("echo root copy\n")
    (r / "q-system" / ".q-system" / "scripts" / "dup.sh").write_text("echo nested copy\n")
    (r / ".github" / "workflows" / "dup.yml").write_text("jobs:\n  d:\n    steps:\n      - run: bash dup.sh\n")
    j = json.loads(_run(r, installed, "--json").stdout)
    assert j["stages"]["dup.sh"]["status"] == "triggered"
    assert j["stages"]["q-system/.q-system/scripts/dup.sh"]["status"] == "dead", "the unregistered duplicate stays visible"
    (r / "lefthook.yml").write_text("pre-commit:\n  commands:\n    d:\n      run: bash q-system/.q-system/scripts/dup.sh\n")
    j = json.loads(_run(r, installed, "--json").stdout)
    assert j["stages"]["q-system/.q-system/scripts/dup.sh"]["status"] == "triggered"


def test_a_planted_dead_stage_inside_a_worktree_copy_is_not_counted(tmp_path):
    r, installed = _repo(tmp_path)
    p = _run(r, installed)
    j = json.loads(_run(r, installed, "--json").stdout)
    assert not any("zombie" in d for d in j["dead"]), j["dead"]
    assert not any("zombie" in k for k in j["stages"])
    ex = j["excluded"]
    assert ex[".claude/worktrees/"] == {"trees": 1, "scripts": 2} and ex[".wt-*"] == {"trees": 1, "scripts": 2}, ex
    assert "excluded: .claude/worktrees/ 1 tree(s), 2 script(s); .wt-* 1 tree(s), 2 script(s)" in p.stdout


def test_a_stale_exemption_is_red(tmp_path):
    r, installed = _repo(tmp_path)
    (r / "q-system" / ".q-system" / "stages-exempt.json").write_text(json.dumps({"exempt": [
        {"path": "q-system/.q-system/scripts/gone.py", "reason": "was a library"}]}))
    p = _run(r, installed)
    assert p.returncode == 2 and "stale exemption" in p.stderr and "gone.py" in p.stderr


def test_an_exemption_without_a_reason_is_red(tmp_path):
    r, installed = _repo(tmp_path)
    (r / "q-system" / ".q-system" / "stages-exempt.json").write_text(json.dumps({"exempt": [
        {"path": "q-system/.q-system/scripts/e_lib.py"}]}))
    p = _run(r, installed)
    assert p.returncode == 2 and "reason" in p.stderr


def test_text_report_prints_the_diff_and_the_scope(tmp_path):
    r, installed = _repo(tmp_path)
    out = _run(r, installed).stdout
    assert "DEAD (1)" in out and "d_dead.py" in out
    assert "TRIGGERED (6)" in out and "MANUAL-ONLY (1)" in out and "EXEMPT (1)" in out
    assert "triggers read:" in out and "installed plists" in out


def _live_copy(tmp_path):
    """The real repo's trigger surfaces and scripts, copied; nothing live is read
    by the inventory under test except through this copy."""
    r = tmp_path / "live"
    shutil.copytree(SCRIPTS, r / "q-system" / ".q-system" / "scripts")
    shutil.copy(ROOT / "q-system" / ".q-system" / "stages-exempt.json", r / "q-system" / ".q-system" / "stages-exempt.json")
    (r / ".claude").mkdir()
    shutil.copy(ROOT / ".claude" / "settings.json", r / ".claude" / "settings.json")
    for hooks in ROOT.glob("plugins/*/hooks/hooks.json"):
        dest = r / hooks.relative_to(ROOT)
        dest.parent.mkdir(parents=True)
        shutil.copy(hooks, dest)
    shutil.copytree(ROOT / ".github" / "workflows", r / ".github" / "workflows")
    for f in ("lefthook.yml", "kipi"):
        shutil.copy(ROOT / f, r / f)
    for sh in ROOT.glob("*.sh"):
        shutil.copy(sh, r / sh.name)
    return r


def test_surfaces_the_known_dead_stages_on_a_copy_of_this_repo(tmp_path):
    r = _live_copy(tmp_path)
    empty = tmp_path / "no-installed-plists"
    empty.mkdir()
    (r / "q-system" / ".q-system" / "scripts" / "weekly-improve.sh").unlink()  # the pre-fix state: nothing named route-overrides-to-learn.py
    (r / "q-system" / ".q-system" / "scripts" / "com.kipi.weekly-improve.plist").unlink()
    p = _run(r, empty, "--json")
    assert p.returncode == 0, p.stderr[-800:]
    j = json.loads(p.stdout)
    assert "q-system/.q-system/scripts/route-overrides-to-learn.py" in j["dead"], "the stage that was built and never ran"
    assert j["stages"]["kipi-push-upstream.sh"]["status"] == "manual-only", "the upstream push has no scheduled trigger"
    assert j["stages"]["q-system/.q-system/scripts/lessons-daily.sh"]["status"] == "triggered", "the template from issue 5 counts as a trigger"


def test_after_the_fix_route_overrides_is_triggered_through_weekly_improve(tmp_path):
    r = _live_copy(tmp_path)
    empty = tmp_path / "no-installed-plists"
    empty.mkdir()
    j = json.loads(_run(r, empty, "--json").stdout)
    st = j["stages"]["q-system/.q-system/scripts/route-overrides-to-learn.py"]
    assert st["status"] == "triggered" and "q-system/.q-system/scripts/weekly-improve.sh" in st["via"], st


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
