#!/usr/bin/env python3
"""Tests for hook-path-resolve-check.py (ASK-1959).

The three cases below are the Definition of Ready of ASK-1959, in order. Each
one is a control somebody did not run before declaring five live hooks dead:

  1. a hook path reachable ONLY through a symlink is LIVE (exit 0)
  2. a genuinely missing path is DEAD (exit 2)
  3. a hook that only ever `exit 0` but denies via JSON is NOT dead

Case 1 is the incident: the home directory is reachable under two spellings, a
root-owned symlink pointing at the real account directory, so a checker that
compares the RAW project dir against the RAW hook path sees two unrelated
strings and reports a live hook as unreachable. The absolute paths are
deliberately not written here -- this file ships to every instance and to a
public repo, and the push tripwire blocks a home path in the skeleton.
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


def _load_checker():
    """Import the checker BESIDE this test, so a value can be read from its owner.

    Every behavioural assertion in this file runs the script as a subprocess, the
    way the wired hook does. This import exists for one narrow job: reading a
    declared constant instead of typing a second copy of it into the test. The
    module computes its REPO_ROOT from its own location and runs nothing at
    import time, so loading it here has no side effects.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("hook_path_resolve_check", CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

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

# An injector whose only non-benign exit text is PROSE. The docstring is the
# real shape: q-system/hooks/lessons-index.py documents itself as "any error ->
# emit nothing, exit 0." and every executable exit in it is sys.exit(0). A
# scanner reading raw source captures the sentence-final "0." as an exit
# argument it cannot evaluate and promotes a pure injector to LIVE.
PROSE_ONLY_EXIT_HOOK = '''#!/usr/bin/env python3
"""Fail-closed and never-blocks: any error -> emit nothing, exit 0. A caller
that wants a refusal should exit 2 instead, which this hook never does."""
import json, sys
# On a bad payload the older draft used to exit 1; it emits nothing now.
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "fyi"}}))
sys.exit(0)  # never block session start
'''

# The negative half. Same prose, but this one actually refuses. Stripping
# comments must not strip the code beside them.
PROSE_PLUS_REAL_EXIT_HOOK = '''#!/usr/bin/env python3
"""Fail-closed and never-blocks: any error -> emit nothing, exit 0."""
import sys
# On a bad payload the older draft used to exit 1; it refuses now.
print("nope", file=sys.stderr)
sys.exit(2)
'''

# A pure injector whose ONLY resemblance to a refusal is ordinary Python: a
# loop `continue` with the token `False` assigned a few characters later.
# Neither is a hook envelope. open-loops.py, memory_autocapture.py and
# prompt-only-enforcement-guard.py all matched on this shape.
CONTINUE_LOOP_INJECTOR = '''#!/usr/bin/env python3
import json, sys
for row in []:
    if row is None:
        continue
    blocked = False
    print(blocked)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "fyi"}}))
sys.exit(0)
'''

# The negative half of the case above: a real `{"continue": false}` refusal,
# which is how a PreToolUse hook stops the session without exiting non-zero.
JSON_CONTINUE_FALSE_GUARD = '''#!/usr/bin/env python3
import json, sys
print(json.dumps({"continue": False, "stopReason": "fixture refuses"}))
sys.exit(0)
'''

# A real gate whose only exit is `raise SystemExit(<return code>)`. This is the
# shape prompt-only-enforcement-guard.py ships, and the exit pattern could not
# see it because the alternation is case-sensitive.
SYSTEM_EXIT_GUARD = '''#!/usr/bin/env python3
import sys


def main(argv):
    if argv:
        print("nope", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''

# An injector whose window after `hookSpecificOutput` carries every refusal
# value as a SUBSTRING of an ordinary identifier and none of them as a value.
INFIX_REFUSAL_INJECTOR = '''#!/usr/bin/env python3
import json, sys
false_positives = []
blocklist = []
denylist = []
asked = len(false_positives) + len(blocklist) + len(denylist)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": str(asked)}}))
sys.exit(0)
'''

# A shell guard carrying the same trap: the only "exit 2" is a comment.
SHELL_PROSE_ONLY_HOOK = """#!/usr/bin/env bash
set -euo pipefail
# Advisory only. A blocking version would exit 2 here; this one never does.
echo "fyi"
exit 0
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
    """Case 1. The project dir is handed in through a symlink, the way the
    short home-directory spelling hands the real repo to every process that
    inherited it.

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

        # The checker is handed the SYMLINKED spelling of the settings file.
        # That is the whole fixture: the project dir it derives is "<tmp>/link",
        # and only the realpath in project_dir_for turns it into "<tmp>/real".
        code, report = _run(link, os.path.join(link, ".claude", "settings.json"))

        site = _by_script(report)["guard.py"]
        assert site["status"] == "LIVE", report
        assert site["resolved"] == os.path.realpath(script), site
        # The realpath inside project_dir_for, pinned. Delete it and every
        # candidate is built under "<tmp>/link", so this equality breaks while
        # the status stays LIVE -- which is why asserting the status alone left
        # the call the PR is named for unpinned (codex, PR #409 round 6).
        assert site["candidate"] == os.path.realpath(script), site
        assert report["dead"] == 0, report
        assert code == 0, (code, report)


def test_named_settings_file_resolves_against_its_own_repo():
    """The documented CLI form, run from inside a Claude session.

    `hook-path-resolve-check.py <other-repo>/.claude/settings.json` is in this
    tool's own usage block, and every Claude session exports CLAUDE_PROJECT_DIR
    for the repo the session is in. While the env var won, every hook in the
    named file resolved under the SESSION's root, found nothing, and reported
    live wiring DEAD -- the verdict this tool exists to stop. Found three times
    by review before the preference was removed rather than special-cased
    (codex, PR #409 rounds 4, 6 and 8).
    """
    with tempfile.TemporaryDirectory() as tmp:
        other = os.path.join(tmp, "other-repo")
        script = os.path.join(other, "q-system", ".q-system", "scripts", "guard.py")
        _write(script, EXIT2_GUARD)
        settings = os.path.join(other, ".claude", "settings.json")
        _write(settings, json.dumps(_settings([
            'python3 "$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/guard.py"'])))

        session_repo = os.path.join(tmp, "session-repo")
        os.makedirs(session_repo)

        # The env var names a DIFFERENT repo, exactly as a live session would.
        code, report = _run(session_repo, settings)

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


def test_directory_reference_is_not_dead():
    """The third false-DEAD source (codex, PR #409 round 3).

    `cd "$CLAUDE_PROJECT_DIR/q-consult"` is a live SessionStart hook in the
    consulting instance. isfile() on a directory is False, so the checker called
    the reference DEAD, exited 2, and told the reader to remove working wiring
    -- the exact verdict it was built to stop somebody acting on.

    The directory EXISTS in this fixture, which is the whole point: the
    reference resolves, so nothing here is dead.
    """
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "q-consult"))

        settings = os.path.join(tmp, ".claude", "settings.json")
        cmd = 'cd "$CLAUDE_PROJECT_DIR/q-consult" && echo hi'
        _write(settings, json.dumps(_settings([cmd])))

        code, report = _run(tmp, settings)

        site = _by_script(report)["q-consult"]
        assert site["status"] == "UNKNOWN", report
        assert report["dead"] == 0, report
        assert code == 0, (code, report)


def test_missing_non_script_path_is_unknown_not_dead():
    """The same rule where the path is NOT there either.

    An extensionless or non-script reference may be a directory the hook itself
    creates, an output file, or a binary. This tool cannot tell which, so it
    reports and does not condemn. A missing .py/.sh is still DEAD -- pinned by
    test_missing_path_is_dead -- so this is a narrowing, not an amnesty.
    """
    with tempfile.TemporaryDirectory() as tmp:
        settings = os.path.join(tmp, ".claude", "settings.json")
        cmd = 'cd "$CLAUDE_PROJECT_DIR/not-created-yet" && echo hi'
        _write(settings, json.dumps(_settings([cmd])))

        code, report = _run(tmp, settings)

        site = _by_script(report)["not-created-yet"]
        assert site["status"] == "UNKNOWN", report
        assert report["dead"] == 0, report
        assert code == 0, (code, report)


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


def test_prose_exit_is_not_read_as_enforcement():
    """Comments and docstrings describe a hook; they do not enforce anything.

    `lessons-index.py` says "exit 0." in its module docstring and terminates
    through `sys.exit(0)` on every branch. Scanning the raw source captures the
    sentence-final `0.`, which is not in BENIGN_EXIT, so a pure injector was
    reported LIVE (codex P2, PR #409). Neither bucket is fatal, so this never
    produced a false block -- it produced a report that overstates how much of
    the settings file is a gate, which is the one thing this tool exists to
    state accurately.
    """
    with tempfile.TemporaryDirectory() as tmp:
        py = os.path.join(tmp, "q-system", "hooks", "injector.py")
        sh = os.path.join(tmp, "q-system", "hooks", "injector.sh")
        _write(py, PROSE_ONLY_EXIT_HOOK)
        _write(sh, SHELL_PROSE_ONLY_HOOK)
        settings = os.path.join(tmp, ".claude", "settings.json")
        _write(settings, json.dumps(_settings([
            'python3 "$CLAUDE_PROJECT_DIR/q-system/hooks/injector.py"',
            'bash "$CLAUDE_PROJECT_DIR/q-system/hooks/injector.sh"',
        ])))

        code, report = _run(tmp, settings)

        by = _by_script(report)
        assert by["injector.py"]["status"] == "ADDITIVE", by["injector.py"]
        assert by["injector.sh"]["status"] == "ADDITIVE", by["injector.sh"]
        assert code == 0, (code, report)


def test_stripping_prose_does_not_swallow_a_real_refusal():
    """The negative self-test for the case above, and the one that matters.

    A false ADDITIVE is the failure that retires a working gate, so the fix for
    a false LIVE is only safe if it is provably conservative: same docstring,
    same comment, one real `sys.exit(2)` beside them, still LIVE.
    """
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "q-system", "hooks", "guard.py")
        _write(script, PROSE_PLUS_REAL_EXIT_HOOK)
        settings = os.path.join(tmp, ".claude", "settings.json")
        _write(settings, json.dumps(_settings([
            'python3 "$CLAUDE_PROJECT_DIR/q-system/hooks/guard.py"',
        ])))

        code, report = _run(tmp, settings)

        assert report["sites"][0]["status"] == "LIVE", report["sites"][0]
        assert code == 0, (code, report)


def test_loop_continue_beside_a_refusal_word_is_not_enforcement():
    """A bare `continue` is a loop keyword, not a hook envelope key.

    Unquoted in BLOCK_SIGNALS it matched any Python `continue` statement, and
    the 400-character window then only needed the token `False`, `block` or
    `deny` to appear somewhere after it. Three of this repo's real injectors
    classified LIVE on exactly that accident (codex, PR #409 round 8). In an
    envelope `continue` is always a JSON key, so it is quoted here the way
    `decision` already was.
    """
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "q-system", "hooks", "inject.py"),
               CONTINUE_LOOP_INJECTOR)
        _write(os.path.join(tmp, "q-system", "hooks", "refuse.py"),
               JSON_CONTINUE_FALSE_GUARD)
        settings = os.path.join(tmp, ".claude", "settings.json")
        _write(settings, json.dumps(_settings([
            'python3 "$CLAUDE_PROJECT_DIR/q-system/hooks/inject.py"',
            'python3 "$CLAUDE_PROJECT_DIR/q-system/hooks/refuse.py"',
        ])))

        code, report = _run(tmp, settings)

        by = _by_script(report)
        assert by["inject.py"]["status"] == "ADDITIVE", by["inject.py"]
        # The negative half, and the one that matters: quoting `continue` must
        # not stop the tool seeing a real {"continue": false} refusal.
        assert by["refuse.py"]["status"] == "LIVE", by["refuse.py"]
        assert code == 0, (code, report)


def test_a_refusal_word_inside_an_identifier_is_not_a_refusal():
    """`false_positives`, `blocklist` and `denylist` are variable names.

    The refusal check is a search inside a 400-character window, so without
    word boundaries every one of those identifiers reads as the VALUE of the
    envelope key beside it and promotes an injector to LIVE. The value is what
    has to be there, not a substring of a name.
    """
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "q-system", "hooks", "inject.py"),
               INFIX_REFUSAL_INJECTOR)
        settings = os.path.join(tmp, ".claude", "settings.json")
        _write(settings, json.dumps(_settings([
            'python3 "$CLAUDE_PROJECT_DIR/q-system/hooks/inject.py"'])))

        code, report = _run(tmp, settings)

        assert report["sites"][0]["status"] == "ADDITIVE", report["sites"][0]
        assert code == 0, (code, report)


def test_system_exit_of_a_return_code_is_enforcement():
    """`raise SystemExit(main(...))` is an exit this tool cannot evaluate.

    The alternation is case-sensitive, so the `Exit(` inside `SystemExit(` was
    invisible and three real gates in this repo -- including
    prompt-only-enforcement-guard.py, which returns 2 on a block -- had NO
    exit signal at all. They read LIVE only by accident, through the bare
    `continue` match above. Narrowing that accident away without this would
    have turned working gates ADDITIVE, which is the one error this tool must
    not make.
    """
    with tempfile.TemporaryDirectory() as tmp:
        _write(os.path.join(tmp, "q-system", "hooks", "guard.py"),
               SYSTEM_EXIT_GUARD)
        settings = os.path.join(tmp, ".claude", "settings.json")
        _write(settings, json.dumps(_settings([
            'python3 "$CLAUDE_PROJECT_DIR/q-system/hooks/guard.py"'])))

        code, report = _run(tmp, settings)

        assert report["sites"][0]["status"] == "LIVE", report["sites"][0]
        assert code == 0, (code, report)


def _run_hook_mode(repo, edited_path):
    """Drive --hook the way the PostToolUse wiring does: hook JSON on stdin."""
    checker = os.path.join(repo, "q-system", ".q-system", "scripts",
                           "hook-path-resolve-check.py")
    proc = subprocess.run(
        [sys.executable, checker, "--hook"],
        input=json.dumps({"tool_input": {"file_path": edited_path}}),
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stderr


def _hook_tree(tmp, hook_command):
    """A repo carrying its own copy of the checker plus one settings file.

    The checker resolves REPO_ROOT from its own location, so the copy has to
    live at the real depth for --hook to scan the fixture's settings file
    rather than this repo's.
    """
    scripts = os.path.join(tmp, "q-system", ".q-system", "scripts")
    os.makedirs(scripts, exist_ok=True)
    with open(os.path.abspath(CHECK), encoding="utf-8") as fh:
        _write(os.path.join(scripts, "hook-path-resolve-check.py"), fh.read())
    settings = os.path.join(tmp, ".claude", "settings.json")
    _write(settings, json.dumps(_settings([hook_command])))
    return settings


def test_hook_mode_blocks_an_edit_that_leaves_a_dead_path():
    """--hook is the only always-on consumer and nothing exercised it, so
    mutating its `return 2` to `return 0` left the whole suite green (codex,
    PR #409 round 8). This is the case that goes red on that mutant."""
    with tempfile.TemporaryDirectory() as tmp:
        settings = _hook_tree(
            tmp, 'python3 "$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/gone.py"')

        code, err = _run_hook_mode(tmp, settings)

        assert code == 2, (code, err)
        assert "gone.py" in err, err
        # The refusal has to name the resolved path, or the reader repeats the
        # 2026-09-20 mistake of deleting wiring without looking at it.
        assert "BLOCKED by hook-path-resolve-check" in err, err


def test_hook_mode_ignores_an_edit_to_anything_else():
    """Self-scoping. Running a 137-site scan on every Edit is token spend for
    nothing, so a non-settings path exits 0 and says nothing at all."""
    with tempfile.TemporaryDirectory() as tmp:
        _hook_tree(
            tmp, 'python3 "$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/gone.py"')

        code, err = _run_hook_mode(tmp, os.path.join(tmp, "README.md"))

        # The settings file in this tree DOES carry a dead path, so a pass here
        # proves the scope check fired rather than the scan finding nothing.
        assert code == 0, (code, err)
        assert err.strip() == "", err


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

    # Every settings file this tree HAS is scanned. The contract being held is
    # "wire it in BOTH files" (what settings-template-sync-check.py exists for),
    # so a control that only ever saw one of the two could not see half of it.
    #
    # Which files a tree HAS is decided by the tree, not by this test. The
    # skeleton carries `.claude/settings.json` plus `settings-template.json`;
    # kipi-new-instance.sh copies the template INTO `.claude/settings.json` and
    # never ships the template, so an instance carries one. This test ships to
    # every instance through the capability manifest, and asserting both files
    # exist made it red in all of them (codex, PR #409 rounds 6 and 7).
    #
    # The candidate names come from the module that owns them, never restated
    # here; the existence filter is this test's own, so dropping a file from
    # default_targets() while it still exists on disk turns this red.
    candidates = _load_checker().SETTINGS_CANDIDATES
    present = {rel for rel in candidates if os.path.isfile(os.path.join(repo, rel))}
    assert present, ("no settings file found under", repo)
    scanned = {os.path.relpath(p, repo) for p in report["files"]}
    assert scanned == present, (scanned, present)


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
