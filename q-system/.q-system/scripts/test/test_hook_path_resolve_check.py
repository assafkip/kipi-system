#!/usr/bin/env python3
"""Tests for hook-path-resolve-check.py (ASK-1959).

The three cases below are the Definition of Ready of ASK-1959, in order. Each
one is a control somebody did not run before declaring five live hooks dead:

  1. a hook path reachable ONLY through a symlink is LIVE (exit 0)
  2. a genuinely missing path is DEAD (exit 2)
  3. a hook that only ever `exit 0` but denies via JSON is NOT dead

Case 1 is the incident: /Users/assafkip is a root-owned symlink to
/Users/assafkipnis, so a checker that compares the RAW project dir against the
RAW hook path sees two unrelated strings and reports a live hook as unreachable.
Case 3 is the other half: a guard that blocks by emitting permissionDecision
deny never exits non-zero, so a checker that equates "never exits 2" with "dead"
retires a working gate.

Runnable two ways, because this repo has both conventions:
    python3 q-system/.q-system/scripts/test/test_hook_path_resolve_check.py
    python3 -m pytest q-system/.q-system/scripts/test/test_hook_path_resolve_check.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(HERE, "..", "hook-path-resolve-check.py")

# A guard that blocks the way the real claude-path-write-guard does: it always
# terminates 0 and carries the refusal in the JSON envelope. Exit code alone
# cannot tell this apart from a no-op.
JSON_DENY_GUARD = """#!/usr/bin/env python3
import json, sys
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "fixture refuses"}}))
sys.exit(0)
"""

EXIT2_GUARD = """#!/usr/bin/env python3
import sys
print("nope", file=sys.stderr)
sys.exit(2)
"""

ADDITIVE_HOOK = """#!/usr/bin/env python3
import json
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "fyi"}}))
"""


def _settings(commands):
    """A settings.json carrying one PreToolUse group with these commands."""
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": ".*",
                    "hooks": [{"type": "command", "command": c} for c in commands],
                }
            ]
        }
    }


def _write(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.chmod(path, 0o755)


def _run(project_dir, settings_path):
    """Invoke the checker exactly as the hook wiring does.

    `settings_path=None` passes no path argument, which is what the wired hook
    command does: the checker then resolves its own targets and the test cannot
    drift from that set.
    """
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = project_dir
    argv = [sys.executable, CHECK, "--json"]
    if settings_path is not None:
        argv.append(settings_path)
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        env=env,
    )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - failure path
        raise AssertionError(
            f"checker emitted non-JSON on stdout:\n{proc.stdout}\n{proc.stderr}"
        ) from exc
    return proc.returncode, report


def _by_script(report):
    return {os.path.basename(r["script"]): r for r in report["sites"]}


def test_symlinked_project_dir_is_live():
    """Case 1. The project dir is handed in through a symlink, as /Users/assafkip
    hands the real repo to every process that inherited that spelling.

    A raw-string containment test sees "<tmp>/link/..." against a project dir of
    "<tmp>/real/..." and concludes the hook is outside the repo, hence dead. The
    only correct answer is that the hook is LIVE.
    """
    with tempfile.TemporaryDirectory() as tmp:
        real = os.path.join(tmp, "real")
        script = os.path.join(real, "q-system", ".q-system", "scripts", "guard.py")
        _write(script, EXIT2_GUARD)

        link = os.path.join(tmp, "link")
        os.symlink(real, link)

        settings = os.path.join(real, ".claude", "settings.json")
        cmd = ('test -f "$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/guard.py" '
               '&& python3 "$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/guard.py"')
        _write(settings, json.dumps(_settings([cmd])))

        # The project dir arrives via the symlink. That is the whole fixture.
        code, report = _run(link, settings)

        site = _by_script(report)["guard.py"]
        assert site["status"] == "LIVE", report
        assert site["resolved"] == os.path.realpath(script), site
        assert report["dead"] == 0, report
        assert code == 0, (code, report)


def test_missing_path_is_dead():
    """Case 2. A path that resolves to nothing is the one fatal state."""
    with tempfile.TemporaryDirectory() as tmp:
        settings = os.path.join(tmp, ".claude", "settings.json")
        cmd = 'python3 "$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/never-existed.py"'
        _write(settings, json.dumps(_settings([cmd])))

        code, report = _run(tmp, settings)

        site = _by_script(report)["never-existed.py"]
        assert site["status"] == "DEAD", report
        assert report["dead"] == 1, report
        assert code == 2, (code, report)


def test_dangling_symlink_is_dead():
    """Case 2, the harder half. Resolving through symlinks must not become
    'assume it is there'. A link whose target was deleted is genuinely dead and
    has to stay reportable, or the fix for case 1 blinds the check entirely."""
    with tempfile.TemporaryDirectory() as tmp:
        scripts = os.path.join(tmp, "q-system", ".q-system", "scripts")
        os.makedirs(scripts)
        target = os.path.join(tmp, "gone.py")
        _write(target, EXIT2_GUARD)
        link = os.path.join(scripts, "guard.py")
        os.symlink(target, link)
        os.remove(target)

        settings = os.path.join(tmp, ".claude", "settings.json")
        cmd = 'python3 "$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/guard.py"'
        _write(settings, json.dumps(_settings([cmd])))

        code, report = _run(tmp, settings)

        assert _by_script(report)["guard.py"]["status"] == "DEAD", report
        assert code == 2, (code, report)


def test_json_deny_guard_is_not_dead():
    """Case 3. The guard never exits non-zero; it refuses in the envelope.

    Asserting LIVE rather than merely 'not DEAD' is deliberate: ADDITIVE is the
    non-fatal bucket, so `status != DEAD` would pass even if the checker failed
    to see the refusal. Only LIVE pins that permissionDecision deny was read as
    enforcement.
    """
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "q-system", ".q-system", "scripts", "json-guard.py")
        _write(script, JSON_DENY_GUARD)

        settings = os.path.join(tmp, ".claude", "settings.json")
        cmd = 'python3 "$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/json-guard.py"'
        _write(settings, json.dumps(_settings([cmd])))

        code, report = _run(tmp, settings)

        site = _by_script(report)["json-guard.py"]
        assert site["status"] == "LIVE", report
        assert site["status"] != "DEAD", report
        assert code == 0, (code, report)


def test_additive_hook_is_reported_but_not_fatal():
    """An injector that never blocks is ADDITIVE by design, not broken. Calling
    it dead would turn this gate red on its own population -- four of this
    repo's UserPromptSubmit hooks are exactly this shape -- and a gate red on
    its own population gets switched off."""
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "q-system", ".q-system", "scripts", "inject.py")
        _write(script, ADDITIVE_HOOK)

        settings = os.path.join(tmp, ".claude", "settings.json")
        cmd = 'python3 "$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/inject.py"'
        _write(settings, json.dumps(_settings([cmd])))

        code, report = _run(tmp, settings)

        assert _by_script(report)["inject.py"]["status"] == "ADDITIVE", report
        assert report["dead"] == 0, report
        assert code == 0, (code, report)


def test_default_value_expansion_does_not_swallow_the_brace():
    """Regression. This repo's integrity-restore hook nests the reference inside
    a shell default-value expansion:

        N="${KIPI_NOTIFY:-$CLAUDE_PROJECT_DIR/.../slack-notify.sh}"

    A path regex that does not stop at `}` carries the closing brace into the
    filename, resolves nothing, and reports a live hook DEAD -- the same false
    verdict the symlink bug produced. Found by the live control below on the
    first green run; pinned here so it stays found when settings.json changes.
    """
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "q-system", ".q-system", "scripts", "notify.sh")
        _write(script, "#!/usr/bin/env bash\nexit 2\n")

        settings = os.path.join(tmp, ".claude", "settings.json")
        cmd = ('N="${KIPI_NOTIFY:-$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/notify.sh}"; '
               '"$N" "message"')
        _write(settings, json.dumps(_settings([cmd])))

        code, report = _run(tmp, settings)

        scripts = _by_script(report)
        assert "notify.sh}" not in scripts, report
        assert scripts["notify.sh"]["status"] == "LIVE", report
        assert code == 0, (code, report)


def test_unextractable_command_is_unknown_not_dead():
    """A command with no script path in it cannot be judged. Reported as
    UNKNOWN and never fatal: a check that cannot see must not report dead, the
    same posture hook_envelope_audit.py takes."""
    with tempfile.TemporaryDirectory() as tmp:
        settings = os.path.join(tmp, ".claude", "settings.json")
        _write(settings, json.dumps(_settings(['echo "no script here"'])))

        code, report = _run(tmp, settings)

        assert report["sites"][0]["status"] == "UNKNOWN", report
        assert code == 0, (code, report)


def test_repo_settings_have_no_dead_hooks():
    """The live control. Run the checker against this repo's own settings files.
    This is the assertion the incident needed and nobody made.

    No path argument is passed, so the checker picks its own targets through
    `default_targets()` -- the identical set the wired PostToolUse hook scans,
    because the hook passes no paths either. An earlier version of this control
    named `.claude/settings.json` by hand and scanned that file alone, so a dead
    path in `settings-template.json` sailed through a green suite while the
    wired hook would have blocked on it (codex, PR #409 round 1). Restating the
    target set in the test made the test a second source of truth for it;
    deriving it from the code that owns it is the fix.
    """
    repo = os.path.realpath(os.path.join(HERE, "..", "..", "..", ".."))
    code, report = _run(repo, None)

    dead = [s for s in report["sites"] if s["status"] == "DEAD"]
    assert dead == [], dead
    # A parse that found nothing would report zero dead and read as green.
    assert len(report["sites"]) > 20, report["sites"]
    assert code == 0, (code, report)

    # Both halves of the "wire it in BOTH files" contract are covered. That
    # contract is what settings-template-sync-check.py exists to hold, so a
    # control that only ever saw one of the two files could not see half of it.
    scanned = {os.path.relpath(p, repo) for p in report["files"]}
    assert scanned == {
        os.path.join(".claude", "settings.json"),
        "settings-template.json",
    }, scanned


def _main():
    failures = []
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failures.append(fn.__name__)
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(tests) - len(failures)}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_main())
