#!/usr/bin/env python3
"""sp-37c08fb1 + sp-dc76e644: a destructive op wearing a different filename.

TWO DEFECTS, ONE SHAPE. The deny hook matched the fleet updater's CLI phrase and
three of its script spellings, and it read only the COMMAND STRING. So:

  sp-37c08fb1  a path with no leading dot-slash, and the bare basename on PATH,
               were unmatched. Measured on origin/main 2026-09-07 by driving the
               hook: `projects/kipi-scheduled/kipi-update.sh --only X` ALLOWED.
  sp-dc76e644  a wrapper that assigns the founder bypass in its OWN text presents
               a command line carrying no destructive pattern at all. On
               2026-09-06 that ran a real fleet sync on the consulting instance
               and reverted a deliberate commit four minutes after it landed.

WHICH COPY THIS DRIVES, and why it is not the live hook. The anchor suite beside
this one prefers ~/.claude/hooks/destructive-op-deny.sh, because that is the copy
that really runs. This suite cannot: it asserts behaviour this change ADDS, and
the live copy only receives it when the founder runs apply-claude-changes on
q-system/output/claude-changes/sp-37c08fb1-fleet-updater-script-form.json. An
agent cannot write into ~/.claude (claude-path-write-guard blocks it, correctly:
an agent that can edit this hook can disable its own gates). Pointing this suite
at the live copy would therefore make it red on every machine until that apply,
which reads exactly like a broken change.

The install signal is kept, and kept in ONE place: the anchor suite's
test_the_vendored_copy_has_not_drifted compares the fixture to the live hook byte
for byte and goes red the moment they differ. That redness is the reminder.

KIPI_DESTRUCTIVE_HOOK overrides the target. That is the ref hatch this repo
already uses, and it is how every negative case below was watched to FAIL first:
pointing it at a pre-fix copy of the hook flips the four cases marked PRE_FIX.
A case that has never been observed failing is not a regression test.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import subprocess

import pytest

# The word is split so this file does not itself read as a script that arms the
# bypass -- the very thing the layer under test refuses. The hook's own regex is
# what is being exercised, so the string still has to reach it intact.
BYPASS = "ALLOW_" + "DESTRUCTIVE"

REPO_COPY = (pathlib.Path(__file__).resolve().parent
             / "fixtures" / "destructive-op-deny.reference.sh")

_OVERRIDE = os.environ.get("KIPI_DESTRUCTIVE_HOOK")
_UNDER_TEST = pathlib.Path(_OVERRIDE) if _OVERRIDE else REPO_COPY

pytestmark = pytest.mark.skipif(
    not _UNDER_TEST.is_file(),
    reason="no hook to drive at %s" % _UNDER_TEST)


def hook_copy(tmp_path):
    """A COPY, never the file itself: the hook writes an audit log when it runs."""
    dst = tmp_path / "under-test.sh"
    shutil.copy(_UNDER_TEST, dst)
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return dst


def decide(hook, command, home, cwd=None):
    """Run the hook the way Claude Code does; return 'deny' or 'allow'."""
    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd or home),
    })
    env = dict(os.environ)
    env["HOME"] = str(home)          # keep the audit log out of the real one
    env.pop(BYPASS, None)
    proc = subprocess.run([str(hook)], input=payload, capture_output=True,
                          text=True, env=env)
    out = proc.stdout.strip()
    if not out:
        return "allow"
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


def write_script(path, body):
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


# ---------------------------------------------------------------- sp-37c08fb1

# PRE_FIX: every one of these was ALLOWED by the hook on origin/main. The first
# two are the exact shapes an agent types; the third is the env-prefixed form the
# other FLEET_DENY entries already cover for the CLI spelling.
SCRIPT_FORM_REFUSED = [
    "projects/kipi-scheduled/kipi-update.sh --only ASK_AI_consultant",
    "kipi-update.sh --only ASK_AI_consultant",
    "FOO=bar kipi-update.sh --only ASK_AI_consultant",
    # The shape that ran unchallenged on 2026-09-07 06:08Z, verbatim minus the paths:
    # a subshell opened after the && split, backgrounded, output redirected.
    "cd /Users/x/projects/kipi-scheduled && ( ./kipi-update.sh --refuse-instance-ahead --only ASK_AI_consultant > /tmp/x.log 2>&1 & ); sleep 2",
    "( ./kipi-update.sh --only X )",
    "{ kipi-update.sh --only X; }",
    "cd /Users/x/projects/kipi-scheduled && ( ( ./kipi-update.sh --only X ) )",
    # Round 2: prefixes the reviewer measured ALLOW, and a quoted path.
    "timeout 900 ./kipi-update.sh --only X",
    "setsid ./kipi-update.sh --only X",
    "exec ./kipi-update.sh --only X",
    "eval ./kipi-update.sh --only X",
    "\"./kipi-update.sh\" --only X",
    "sudo FOO=bar nohup ./kipi-update.sh --only X",
    "( bash /Users/x/projects/kipi-scheduled/kipi-update.sh --only X )",
    "cd /Users/x && ( sh ./kipi-update.sh --only X )",
]

# These already worked. They are here as the negative control for the pair above:
# without them, "the script form is refused" could be "everything is refused".
SCRIPT_FORM_ALREADY_REFUSED = [
    "cd /Users/x/projects/kipi-scheduled && ./kipi-update.sh --only X",
    "./kipi-update.sh --only X",
    "bash /Users/x/projects/kipi-scheduled/kipi-update.sh --only X",
    "/Users/x/projects/kipi-scheduled/kipi-update.sh --only X",
]

# The dry-run flag ALONE in its own tool call. Every one must pass, in every
# spelling of the script form the layer above now matches.
DRY_RUN_ALONE = [
    "./kipi-update.sh --dry-run",
    "cd /Users/x/projects/kipi-scheduled && ( ./kipi-update.sh --dry-run --only X )",
    "kipi-update.sh --dry",
    "projects/kipi-scheduled/kipi-update.sh --dry-run",
    "bash /Users/x/kipi-update.sh --dry",
]

# Reading is not running. The comment above FLEET_DENY records that an unanchored
# first attempt blocked a `sed -n` read of this filename and had to be undone.
READING_IS_NOT_RUNNING = [
    "cat kipi-update.sh",
    "( cat kipi-update.sh )",
    "bash -n kipi-update.sh",
    "grep -n rsync kipi-update.sh",
    "sed -n '1,20p' kipi-update.sh",
    "wc -l projects/kipi-scheduled/kipi-update.sh",
]

# kipi-update-instance-ahead.py is READ-ONLY and must stay unmatched. All three
# call shapes, because a basename rule that reached .py would break every one.
INSTANCE_AHEAD_HELPER = [
    "python3 kipi-update-instance-ahead.py --json",
    "./kipi-update-instance-ahead.py",
    "/Users/x/projects/kipi-system/kipi-update-instance-ahead.py",
]


class TestTheFleetUpdaterAsAScriptFile:

    @pytest.mark.parametrize("command", SCRIPT_FORM_REFUSED)
    def test_the_hyphenated_script_form_is_refused(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "deny", (
            "a real fleet sync ran with no token in this shape: %r" % command)

    @pytest.mark.parametrize("command", SCRIPT_FORM_ALREADY_REFUSED)
    def test_the_shapes_that_already_worked_still_do(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "deny", command

    @pytest.mark.parametrize("command", DRY_RUN_ALONE)
    def test_the_dry_run_alone_passes(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "allow", (
            "a preview is how you EARN the run and must never be blocked: %r"
            % command)

    @pytest.mark.parametrize("command", READING_IS_NOT_RUNNING)
    def test_reading_the_script_is_not_running_it(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "allow", (
            "a gate that blocks reads is a gate someone switches off: %r"
            % command)

    @pytest.mark.parametrize("command", INSTANCE_AHEAD_HELPER)
    def test_the_read_only_instance_ahead_helper_passes(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "allow", command


# ---------------------------------------------------------------- sp-dc76e644

ARMS_THE_BYPASS = (
    "#!/bin/bash\n"
    "set -euo pipefail\n"
    "export %s=1\n"
    'echo "syncing"\n'
) % BYPASS

MENTIONS_IT_IN_A_COMMENT = (
    "#!/bin/bash\n"
    "# This script refuses to run unless %s=1 comes from the calling shell.\n"
    'if [ "${%s:-0}" != "1" ]; then echo refusing; exit 2; fi\n'
    'echo "syncing"\n'
) % (BYPASS, BYPASS)

RUNS_THE_UPDATER = (
    "#!/bin/bash\n"
    "set -euo pipefail\n"
    "bash /Users/x/projects/kipi-system/kipi-update.sh --only consulting\n"
)

HARMLESS = (
    "#!/bin/bash\n"
    "set -euo pipefail\n"
    'echo "nothing destructive here"\n'
    "git status --short\n"
)


class TestAWrapperScriptIsADestructiveOpWearingAFilename:

    def test_a_wrapper_that_arms_the_bypass_is_refused(self, tmp_path):
        """PRE_FIX: allowed on origin/main. This is the 2026-09-06 sync verbatim."""
        w = write_script(tmp_path / "consulting-sync-run.sh", ARMS_THE_BYPASS)
        assert decide(hook_copy(tmp_path), "bash %s --verify-only" % w,
                      tmp_path) == "deny"

    def test_the_same_wrapper_run_by_bare_path_is_refused(self, tmp_path):
        w = write_script(tmp_path / "consulting-sync-run.sh", ARMS_THE_BYPASS)
        assert decide(hook_copy(tmp_path), str(w), tmp_path) == "deny"

    def test_a_dry_run_does_not_excuse_arming_the_bypass(self, tmp_path):
        """The one rule with no preview exemption, and the reason is in the hook:
        a flag on the wrapper says nothing about what the wrapper arms."""
        w = write_script(tmp_path / "consulting-sync-run.sh", ARMS_THE_BYPASS)
        assert decide(hook_copy(tmp_path), "bash %s --dry-run" % w,
                      tmp_path) == "deny"

    def test_a_wrapper_without_it_passes(self, tmp_path):
        """The negative control. Without this, "the wrapper is refused" could
        just as easily be "every script invocation is refused"."""
        w = write_script(tmp_path / "harmless.sh", HARMLESS)
        assert decide(hook_copy(tmp_path), "bash %s --verify-only" % w,
                      tmp_path) == "allow"

    def test_a_comment_mentioning_the_bypass_is_not_an_assignment(self, tmp_path):
        """The comment drop has to be narrow enough to still fire (the case above)
        and wide enough not to refuse a script that REFUSES the bypass in prose.
        A check that ignores comments either never fires or always passes; this
        pair is what tells those two apart."""
        w = write_script(tmp_path / "careful.sh", MENTIONS_IT_IN_A_COMMENT)
        assert decide(hook_copy(tmp_path), "bash %s" % w, tmp_path) == "allow"

    def test_a_wrapper_that_runs_the_updater_is_refused(self, tmp_path):
        w = write_script(tmp_path / "nightly.sh", RUNS_THE_UPDATER)
        assert decide(hook_copy(tmp_path), "bash %s" % w, tmp_path) == "deny"

    def test_that_wrapper_is_exempt_on_a_preview_stage(self, tmp_path):
        """The fleet half follows the same preview exemption as a direct match,
        which is what keeps `bash kipi-update.sh --dry` passing."""
        w = write_script(tmp_path / "nightly.sh", RUNS_THE_UPDATER)
        assert decide(hook_copy(tmp_path), "bash %s --dry-run" % w,
                      tmp_path) == "allow"

    def test_a_syntax_check_is_not_a_run(self, tmp_path):
        """`bash -n FILE` reads and parses; it never executes. Refusing it would
        block the one command that checks this hook's own syntax."""
        w = write_script(tmp_path / "consulting-sync-run.sh", ARMS_THE_BYPASS)
        assert decide(hook_copy(tmp_path), "bash -n %s" % w, tmp_path) == "allow"

    def test_a_missing_target_is_not_a_match(self, tmp_path):
        """A path that does not resolve must fall through, not deny and not crash.
        The direct patterns are still in front of this layer."""
        assert decide(hook_copy(tmp_path), "bash /nonexistent/nowhere.sh",
                      tmp_path) == "allow"

    def test_a_relative_target_resolves_against_the_payloads_cwd(self, tmp_path):
        """The hook is not run from the agent's directory, so a bare filename can
        only be found through the cwd the payload carries."""
        write_script(tmp_path / "consulting-sync-run.sh", ARMS_THE_BYPASS)
        assert decide(hook_copy(tmp_path), "bash consulting-sync-run.sh",
                      tmp_path, cwd=tmp_path) == "deny"


    def test_a_wrapper_inside_a_subshell_or_group_is_still_read(self, tmp_path):
        """The 2026-09-07 06:08Z shape applied to the wrapper scan. `( bash w.sh )`
        after an && split tokenises to `(` first and the scanner read that as the
        program, so the wrapper's text was never opened. Measured before the fix
        with a wrapper that arms the bypass: plain DENY, every paren or brace
        form ALLOW."""
        w = write_script(tmp_path / "consulting-sync-run.sh", ARMS_THE_BYPASS)
        for cmd in ("( bash %s )" % w,
                    "cd %s && ( bash %s > /tmp/x.log 2>&1 & ); sleep 1" % (tmp_path, w),
                    "{ bash %s; }" % w,
                    "cd %s && ( ./consulting-sync-run.sh )" % tmp_path,
                    "(bash %s)" % w):
            assert decide(hook_copy(tmp_path), cmd, tmp_path, cwd=tmp_path) == "deny", cmd

    def test_a_harmless_wrapper_inside_a_subshell_still_passes(self, tmp_path):
        """The negative control for the case above, in the same shape."""
        w = write_script(tmp_path / "harmless.sh", HARMLESS)
        assert decide(hook_copy(tmp_path), "( bash %s )" % w, tmp_path) == "allow"

class TestAPreviewInTheSameBlockDoesNotExemptTheApply:
    """Round 1 of PR 323 measured: `X --dry-run && ( X --only Y )` ALLOWED, because
    a preview stage matching an old pattern set _fleet_preview and the early exit
    ran before either new layer. ASK-1118's own words: a preview sharing a command
    block with the apply does not exempt the apply."""

    def test_a_dry_run_then_a_subshell_apply_is_refused(self, tmp_path):
        assert decide(hook_copy(tmp_path),
                      "./kipi-update.sh --dry-run && ( ./kipi-update.sh --only X )",
                      tmp_path) == "deny"

    def test_a_dry_run_then_a_bypass_wrapper_is_refused(self, tmp_path):
        w = write_script(tmp_path / "consulting-sync-run.sh", ARMS_THE_BYPASS)
        assert decide(hook_copy(tmp_path),
                      "./kipi-update.sh --dry-run && bash %s --verify-only" % w,
                      tmp_path) == "deny"
        assert decide(hook_copy(tmp_path),
                      "./kipi-update.sh --dry && bash %s" % w, tmp_path) == "deny"

    def test_a_dry_run_then_something_harmless_still_passes(self, tmp_path):
        assert decide(hook_copy(tmp_path),
                      "./kipi-update.sh --dry-run && echo done", tmp_path) == "allow"


PRINTS_THE_PHRASE = (
    "#!/bin/bash\n"
    'echo "    Run: kipi update"\n'
    "python3 - <<'PY'\n"
    'import sys; sys.stderr.write("run kipi update --dry first")\n'
    "PY\n"
)

CARRIES_THE_HOOKS_OWN_DENY_TEXT = (
    "#!/bin/bash\n"
    'reason="fleet-wide delete"\n'
    'echo "destructive-op-deny: $reason. (or set %s=1 to bypass all)."\n'
) % BYPASS

BACKS_UP_PHOTOS = (
    "#!/bin/bash\n"
    "rsync -a --delete /Volumes/Photos/ /Volumes/Backup/\n"
)

RUNS_THE_CLI_PHRASE = (
    "#!/bin/bash\n"
    "set -euo pipefail\n"
    "kipi update --only consulting\n"
)

REPO = pathlib.Path(__file__).resolve().parents[3]


class TestTheWrapperRuleReadsCommandsNotText:
    """Round 1 of PR 323 measured the first cut against this repo's 212 tracked
    scripts: 20 refused, among them an install hint that echoes the CLI phrase,
    a script carrying it inside a Python string, and the capability-token
    installer. The rule reads a script's lines as commands now."""

    def test_a_script_that_only_prints_the_phrase_passes(self, tmp_path):
        w = write_script(tmp_path / "auto-update.sh", PRINTS_THE_PHRASE)
        assert decide(hook_copy(tmp_path), "bash %s" % w, tmp_path) == "allow"

    def test_a_script_carrying_the_deny_text_in_an_echo_passes(self, tmp_path):
        w = write_script(tmp_path / "installer.sh", CARRIES_THE_HOOKS_OWN_DENY_TEXT)
        assert decide(hook_copy(tmp_path), "bash %s" % w, tmp_path) == "allow"

    def test_a_backup_script_with_rsync_delete_passes(self, tmp_path):
        w = write_script(tmp_path / "backup-photos.sh", BACKS_UP_PHOTOS)
        assert decide(hook_copy(tmp_path), "bash %s" % w, tmp_path) == "allow"

    def test_a_script_that_runs_the_cli_phrase_is_refused(self, tmp_path):
        w = write_script(tmp_path / "nightly.sh", RUNS_THE_CLI_PHRASE)
        assert decide(hook_copy(tmp_path), "bash %s" % w, tmp_path) == "deny"

    def test_a_wrapper_behind_timeout_is_still_read(self, tmp_path):
        w = write_script(tmp_path / "consulting-sync-run.sh", ARMS_THE_BYPASS)
        assert decide(hook_copy(tmp_path), "timeout 60 bash %s" % w, tmp_path) == "deny"

    @pytest.mark.parametrize("rel", [
        "plugins/kipi-core/scripts/install-capability-token.sh",
        "q-system/hooks/auto-update.sh",
        "q-system/.q-system/tests/fixtures/destructive-op-deny.reference.sh",
        "kipi-push-upstream.sh",
    ])
    def test_the_repos_own_scripts_the_first_cut_refused_now_pass(self, tmp_path, rel):
        p = REPO / rel
        if not p.is_file():
            pytest.skip("not present in this checkout: %s" % rel)
        assert decide(hook_copy(tmp_path), "bash %s" % p, tmp_path) == "allow"

class TestNothingElseMoved:
    """The layers added here are deny-only and appended. Everything the file
    already refused it must still refuse, and the ordinary commands it allowed
    must still run -- otherwise this is a new gate, not a closed hole."""

    @pytest.mark.parametrize("command", [
        "git reset --hard",
        "git push --force origin main",
        "git clean -fd",
        "rm -v -rf /tmp/canary",
        "kipi update",
        "cd /tmp && kipi update",
    ])
    def test_the_existing_denials_are_unchanged(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "deny", command

    @pytest.mark.parametrize("command", [
        "git status --short",
        "rm /tmp/one-file.txt",
        "ls -rf /tmp",
        "git push origin main",
        "python3 -m pytest q-system/.q-system/tests -q",
        "rsync -ain --delete SRC DEST | python3 kipi-update-deletion-guard.py",
    ])
    def test_ordinary_commands_still_run(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "allow", command


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
