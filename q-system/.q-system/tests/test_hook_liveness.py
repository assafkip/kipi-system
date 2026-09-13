"""ASK-1250: a PreToolUse guard at 0644 is OFF, and the check has to say so.

Every fixture lives under tmp_path. The guard copy is the committed reference
destructive-op-deny script, so the negative case is the real file shape the
scar was about, not an invented one-liner.
"""
import importlib.util
import json
import shutil
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
REFERENCE_GUARD = Path(__file__).resolve().parent / "fixtures" / "destructive-op-deny.reference.sh"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook_liveness = _load("hook_liveness", "hook_liveness.py")
fleet_health = _load("fleet_health_daily", "fleet-health-daily.py")


def _settings(tmp_path, command):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    hooks = {"PreToolUse": [{"matcher": "Bash",
                             "hooks": [{"type": "command", "command": command}]}]}
    settings.write_text(json.dumps({"hooks": hooks}))
    return settings


def _guard(tmp_path, mode):
    guard = tmp_path / "hooks" / "destructive-op-deny.sh"
    guard.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(REFERENCE_GUARD, guard)
    guard.chmod(mode)
    return guard


def test_executable_bare_path_guard_is_live(tmp_path):
    guard = _guard(tmp_path, 0o755)
    checked = []
    assert hook_liveness.audit([_settings(tmp_path, str(guard))], checked) == []
    assert checked == [str(guard)], "the guard was never judged, so green means nothing"


def test_0644_bare_path_guard_goes_red_for_its_mode(tmp_path):
    guard = _guard(tmp_path, 0o644)
    problems = hook_liveness.audit([_settings(tmp_path, str(guard))])
    assert [(p.path, p.reason) for p in problems] == [(str(guard), "not executable (0o644)")]


def test_missing_guard_goes_red(tmp_path):
    missing = tmp_path / "hooks" / "gone.sh"
    problems = hook_liveness.audit([_settings(tmp_path, str(missing))])
    assert [(p.path, p.reason) for p in problems] == [(str(missing), "missing")]


def test_interpreter_run_script_does_not_need_the_bit(tmp_path):
    guard = _guard(tmp_path, 0o644)
    assert hook_liveness.audit([_settings(tmp_path, f"bash {guard}")]) == []


def test_project_dir_guard_form_is_resolved(tmp_path):
    guard = _guard(tmp_path, 0o644)
    command = f'test -f "$CLAUDE_PROJECT_DIR/hooks/{guard.name}" && "$CLAUDE_PROJECT_DIR/hooks/{guard.name}"'
    problems = hook_liveness.audit([_settings(tmp_path, command)])
    assert [p.reason for p in problems] == ["not executable (0o644)"]


def test_unreadable_settings_is_not_silence(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{not json")
    problems = hook_liveness.audit([settings])
    assert len(problems) == 1 and problems[0].reason.startswith("unreadable")


def test_fleet_health_files_the_0644_guard(tmp_path):
    guard = _guard(tmp_path, 0o644)
    findings = fleet_health.detect_hook_not_executable(
        None, settings_paths=[_settings(tmp_path, str(guard))])
    assert len(findings) == 1
    assert findings[0]["subject"] == str(guard)
    assert "not executable (0o644)" in findings[0]["title"]


def test_detector_is_registered_with_an_action_and_a_lesson():
    ids = [d["id"] for d in fleet_health.DETECTORS]
    assert "hook-not-executable" in ids
    assert fleet_health.validate_detectors() == []
