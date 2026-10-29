"""ASK-3361: the Gmail trash lift reaches the hook that RUNS, not only the repo.

install-claude-hooks.py refuses a source weaker than the installed hook (its
differential gate), so this change can never land through the installer. That
is the gate working. The founder's ruling (2026-10-29, option "b") lands through
proposals/destructive-op-allow-gmail-trash.json and apply-claude-changes.sh
instead. PR #562 round 1 review (major): without a landing path the merged
source stays uninstallable and `--check` reports drift on every run.

These cases pin that the proposal, applied to the hook as it was before the
lift, yields the repo's hook byte for byte, keeps it executable, and leaves the
installer's drift check clean. Every write is under tmp_path.
"""
import json
import os
import pathlib
import re
import subprocess
import sys

QSYS = pathlib.Path(__file__).resolve().parents[1]
HOOK = QSYS / "hooks" / "destructive-op-deny.sh"
PROPOSAL = QSYS / "proposals" / "destructive-op-allow-gmail-trash.json"
ENGINE = QSYS / "scripts" / "apply_claude_changes.py"
INSTALLER = QSYS / "scripts" / "install-claude-hooks.py"


def _edit():
    prop = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    assert len(prop["edits"]) == 1, "one edit, to one file"
    edit = prop["edits"][0]
    assert edit["file"] == ".claude/hooks/destructive-op-deny.sh"
    assert edit["op"] == "insert_before"
    return edit


def _before_the_lift():
    """The repo hook with the proposal's insert taken out: the hook it applies to."""
    edit, text = _edit(), HOOK.read_text(encoding="utf-8")
    assert text.count(edit["insert"]) == 1, "the repo hook does not carry the proposal's block exactly once"
    pre = text.replace(edit["insert"], "")
    assert pre.count(edit["anchor"]) == 1, "the anchor is not unique in the pre-lift hook"
    return pre


def _home(tmp_path):
    home = tmp_path / "home"
    hooks = home / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (home / "q-system" / "output").mkdir(parents=True)
    installed = hooks / "destructive-op-deny.sh"
    installed.write_text(_before_the_lift(), encoding="utf-8")
    installed.chmod(0o755)
    settings = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": str(installed), "timeout": 5}]}]}}
    (home / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    return home, installed


def test_the_block_is_the_gmail_trash_allowance():
    insert = _edit()["insert"]
    assert "mcp__claude_ai_Gmail__trash_thread|mcp__claude_ai_Gmail__trash_message)" in insert
    assert "exit 0" in insert


def test_applying_the_proposal_yields_the_repo_hook(tmp_path):
    home, installed = _home(tmp_path)
    proc = subprocess.run([sys.executable, str(ENGINE), str(PROPOSAL), "--root", str(home)],
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert installed.read_bytes() == HOOK.read_bytes(), "the applied hook differs from the repo copy"
    assert os.access(installed, os.X_OK), "the applied hook lost its execute bit: the guard is OFF"


def test_before_the_apply_the_drift_check_names_a_command_that_can_succeed(tmp_path):
    """PR #562 review: `--check` printed only the installer, which refuses this
    change, so its remediation could never succeed. It now names the proposal."""
    home, _ = _home(tmp_path)
    proc = subprocess.run([sys.executable, str(INSTALLER), "--check", "--home", str(home)],
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    named = re.findall(r"apply-claude-changes\.sh (\S+\.json) --root \$HOME", proc.stdout)
    assert named == ["q-system/.q-system/proposals/destructive-op-allow-gmail-trash.json"], proc.stdout


def test_applying_every_proposal_the_check_names_clears_the_check(tmp_path):
    """PR #562 round 2: the hint once named a stale sibling proposal whose block
    the repo source lacks, so following every printed line left --check red.
    The only proof the hint is right: do everything it says, then --check is 0."""
    home, _ = _home(tmp_path)
    proc = subprocess.run([sys.executable, str(INSTALLER), "--check", "--home", str(home)],
                          capture_output=True, text=True, timeout=300)
    named = re.findall(r"apply-claude-changes\.sh (\S+\.json) --root \$HOME", proc.stdout)
    assert named, "the check named nothing to apply: " + proc.stdout
    repo = QSYS.parents[1]
    for rel in named:
        subprocess.run([sys.executable, str(ENGINE), str(repo / rel), "--root", str(home)],
                       capture_output=True, text=True, timeout=300, check=True)
    after = subprocess.run([sys.executable, str(INSTALLER), "--check", "--home", str(home)],
                           capture_output=True, text=True, timeout=300)
    assert after.returncode == 0, after.stdout + after.stderr


def test_the_check_prints_the_working_command_before_the_refusing_one(tmp_path):
    """PR #562 round 3: the installer line came first and the first action
    dead-ended. The proposal's apply now leads."""
    home, _ = _home(tmp_path)
    out = subprocess.run([sys.executable, str(INSTALLER), "--check", "--home", str(home)],
                         capture_output=True, text=True, timeout=300).stdout
    assert out.index("apply-claude-changes.sh") < out.index("run: python3"), out


def test_a_proposal_whose_anchor_the_installed_hook_lacks_is_not_named(tmp_path):
    """PR #562 round 3: if the installed hook was reworded at the anchor, the
    apply refuses too, so the check must not send him there."""
    home, installed = _home(tmp_path)
    anchor = _edit()["anchor"]
    installed.write_text(installed.read_text(encoding="utf-8").replace(anchor, "  # reworded here\n"),
                         encoding="utf-8")
    out = subprocess.run([sys.executable, str(INSTALLER), "--check", "--home", str(home)],
                         capture_output=True, text=True, timeout=300).stdout
    assert "destructive-op-allow-gmail-trash.json" not in out, out


def test_the_installer_refusal_names_the_proposal(tmp_path):
    """PR #562 round 3: the refusal is the first message he reads."""
    home, _ = _home(tmp_path)
    out = subprocess.run([sys.executable, str(INSTALLER), "--dry-run", "--home", str(home)],
                         capture_output=True, text=True, timeout=300).stdout
    assert "REFUSED destructive-op-deny.sh" in out, out
    assert "apply it with: bash q-system/.q-system/scripts/apply-claude-changes.sh " \
           "q-system/.q-system/proposals/destructive-op-allow-gmail-trash.json --root $HOME" in out, out


def test_after_the_apply_the_drift_check_is_clean(tmp_path):
    home, _ = _home(tmp_path)
    subprocess.run([sys.executable, str(ENGINE), str(PROPOSAL), "--root", str(home)],
                   capture_output=True, text=True, timeout=300, check=True)
    proc = subprocess.run([sys.executable, str(INSTALLER), "--check", "--home", str(home)],
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
