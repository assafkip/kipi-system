#!/usr/bin/env python3
"""sp-9166e58a: `kipi update` is the one FLEET_DENY pattern that is not anchored.

READ-ONLY on ~/.claude. This test reads the live hook, copies it into a tmp dir,
patches the COPY, and drives both. It never writes inside .claude/ -- that is
claude-path-write-guard's line and it is the right line: an agent that can edit
destructive-op-deny.sh can disable its own gates. Nothing here proposes that an
agent apply this patch. It exists so the founder's decision is backed by a
measurement instead of an argument.

THE DEFECT. A git commit whose MESSAGE contains the two words is blocked, so
every commit about the updater has to be written to a file and passed with -F.

WHY THIS IS NOT THE FIX THE HOOK ALREADY REJECTED. The comment above emit_deny
(2026-08-07) decides that the hook does NOT try to tell prose from invocation,
and it is right: stripping heredoc bodies would open `bash <<'EOF'`, and any
parser deciding "this string is only prose" is a new bypass surface. This patch
does none of that. It anchors at COMMAND POSITION -- which is the discipline the
other three FLEET_DENY entries already follow, and which the hook's own comment
introduced after an unanchored pattern blocked `sed -n '1,20p' kipi-update.sh`:

    "Anchored at COMMAND POSITION on purpose: a first attempt matched the script
     name anywhere in the line and blocked `sed -n '1,20p' kipi-update.sh`, but
     reading a file is not running it. A gate that blocks reads is a gate someone
     switches off."

Pattern 138 is the only entry that never got that treatment. This is finishing a
change the file already made, not loosening a rule it deliberately set.

THE RISK, STATED PLAINLY. Anchoring means the pattern can no longer match the
phrase in an arbitrary position. The shapes that matter -- bare, chained after
&& ; | , env-var-prefixed, and inside command substitution -- are each asserted
below to STILL be denied. A message containing "; kipi update" would still false-
positive; that is accepted, and is the same residue the other three entries carry.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest

HOOK = pathlib.Path(os.environ.get("HOME", "")) / ".claude/hooks/destructive-op-deny.sh"

# The ref hatch has to beat the machine-local skip, or it cannot rescue anything
# (Codex minor, PR #270): pointing KIPI_DESTRUCTIVE_HOOK at a candidate copy on a
# machine WITHOUT the live hook skipped the whole module, silently, and a suite
# that skips reads exactly like a suite that passes.
_OVERRIDE = os.environ.get("KIPI_DESTRUCTIVE_HOOK")

# A VENDORED reference copy, so this suite can run somewhere other than one
# laptop (Codex major, PR #274). The hook is machine-local with no repo copy, so
# every case here skipped on every runner and verify.sh reported
# `pytest:test_destructive_op_deny_anchor.py ok` having executed NOTHING: 89
# assertions about the fleet's most destructive guard, gated by a false green.
#
# The live hook is still the one that runs, and it is still what these cases
# prefer. The vendored copy is the CI fallback, and test_the_vendored_copy_has_
# not_drifted below pins the two byte-identical whenever both exist, so the copy
# cannot quietly become a different program that passes its own tests.
VENDORED = pathlib.Path(__file__).parent / "q-system/.q-system/hooks/destructive-op-deny.sh"

if _OVERRIDE:
    _UNDER_TEST = pathlib.Path(_OVERRIDE)
elif HOOK.is_file():
    _UNDER_TEST = HOOK
else:
    _UNDER_TEST = VENDORED

CURRENT = "'kipi[[:space:]]+update'"
# Command position, allowing an env-var assignment prefix and command
# substitution, because those really do invoke it.
ANCHORED = (
    r"'(^|[;&|]|\$\(|`)[[:space:]]*"
    r"([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*kipi[[:space:]]+update'"
)

pytestmark = pytest.mark.skipif(
    not _UNDER_TEST.is_file(),
    reason="destructive-op-deny.sh is machine-local; not present here and "
           "KIPI_DESTRUCTIVE_HOOK names no readable copy either")


def variants(tmp_path):
    """(live copy, patched copy). The hook is READ, never written.

    Reads _UNDER_TEST, not HOOK: on a machine with no live hook these classes
    used to fail rather than skip once the module stopped skipping wholesale,
    which is 23 cases that were green only because one laptop had the file.
    """
    live = tmp_path / "live.sh"
    shutil.copy(_UNDER_TEST, live)
    text = live.read_text(encoding="utf-8")
    assert CURRENT in text, (
        "the unanchored pattern is gone from the live hook -- either this was "
        "fixed (delete this test and say so) or the pattern was respelled")
    patched = tmp_path / "patched.sh"
    patched.write_text(text.replace(CURRENT, ANCHORED, 1), encoding="utf-8")
    for p in (live, patched):
        p.chmod(0o755)
    return live, patched


def decide(hook, command, home):
    """Run the hook the way Claude Code does and return 'deny' or 'allow'."""
    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(home),
    })
    env = dict(os.environ)
    env["HOME"] = str(home)          # keep the audit log out of the real one
    env.pop("ALLOW_DESTRUCTIVE", None)
    proc = subprocess.run([str(hook)], input=payload, capture_output=True,
                          text=True, env=env)
    out = proc.stdout.strip()
    if not out:
        return "allow"
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


# The commit message that actually got blocked, and the ones like it.
PROSE = [
    'git commit -m "feat(fleet): the kipi update path never shipped this"',
    'git commit -m "note: kipi update rsyncs the skeleton into every instance"',
]

# Every shape that really does invoke it. None of these may ever be allowed.
REAL = [
    "kipi update",
    "cd ~/projects/kipi-system && kipi update",
    "echo hi; kipi update",
    "false || kipi update",
    "ALLOW_DESTRUCTIVE_NOT_REALLY=1 kipi update",
    "FOO=bar BAZ=qux kipi update",
    "echo $(kipi update)",
    "true | kipi update",
]


class TestTheLiveHookHasTheDefect:
    """Red. Documents the behaviour that is on the machine right now."""

    @pytest.mark.parametrize("command", PROSE)
    def test_a_commit_message_is_denied_today(self, tmp_path, command):
        live, _ = variants(tmp_path)
        assert decide(live, command, tmp_path) == "deny", (
            "the false positive is gone from the live hook; this test has "
            "outlived the defect it documents")


class TestTheAnchoredPatternFixesItWithoutOpeningAHole:

    @pytest.mark.parametrize("command", PROSE)
    def test_a_commit_message_is_allowed(self, tmp_path, command):
        _, patched = variants(tmp_path)
        assert decide(patched, command, tmp_path) == "allow"

    @pytest.mark.parametrize("command", REAL)
    def test_every_real_invocation_is_still_denied(self, tmp_path, command):
        _, patched = variants(tmp_path)
        assert decide(patched, command, tmp_path) == "deny", (
            f"ANCHORING OPENED A HOLE: {command!r} now runs the fleet-wide "
            "delete unchallenged. Do not apply this patch.")

    @pytest.mark.parametrize("command", REAL)
    def test_the_live_hook_denies_them_too_so_nothing_regressed(self, tmp_path, command):
        """Negative control for the pair above: if the live hook already allowed
        one of these, 'still denied' would be proving nothing."""
        live, _ = variants(tmp_path)
        assert decide(live, command, tmp_path) == "deny"

    def test_a_dry_run_stays_exempt_either_way(self, tmp_path):
        live, patched = variants(tmp_path)
        for hook in (live, patched):
            assert decide(hook, "kipi update --dry-run", tmp_path) == "allow"

    def test_the_other_destructive_patterns_are_untouched(self, tmp_path):
        """The patch must not reach outside FLEET_DENY."""
        _, patched = variants(tmp_path)
        for command in ("rm -rf /tmp/whatever", "git reset --hard",
                        "git push --force", "git clean -fd"):
            assert decide(patched, command, tmp_path) == "deny", command


class TestTheProposedPatchIsWhatTheFileAlreadyDoes:
    """The argument for applying it, checked rather than asserted in prose."""

    def test_the_other_fleet_patterns_are_already_command_anchored(self, tmp_path):
        live, _ = variants(tmp_path)
        text = live.read_text(encoding="utf-8")
        block = re.search(r"declare -a FLEET_DENY=\(\n(.*?)\n  \)", text, re.S)
        assert block, "FLEET_DENY block not found; the hook was restructured"
        entries = [l.strip() for l in block.group(1).splitlines() if l.strip()]
        anchored = [e for e in entries if e.startswith("'(^|[;&|")]
        assert len(entries) == 4, entries
        assert len(anchored) == 3, (
            "the anchoring split changed; re-read the hook before trusting "
            "this test's argument")
        assert CURRENT in entries, (
            "the unanchored entry is not the kipi-update one any more")


# ===================================================================== ASK-1118
# THE DRY-RUN EXEMPTION IS EVALUATED OVER THE WHOLE COMMAND STRING.
#
#     case "$COMMAND" in
#       *--dry*) : ;;
#
# A substring test against the WHOLE string, while every FLEET_DENY entry it
# guards is anchored at COMMAND POSITION. The two halves disagree about what a
# "command" is, and the gap runs BOTH ways:
#
#   fails OPEN : `--dry` appearing ANYWHERE in a compound command -- in an echo,
#                in a quoted string, in a preview that precedes the apply --
#                waves through every fleet-delete in that invocation. The guard's
#                own refusal text says "Preview it first with --dry-run", so its
#                recommended workflow, run as one block, disarms it.
#   fails CLOSED: the substring never matches rsync's short `-n`, and
#                kipi-update-deletion-guard.py's own documented usage line is
#                `rsync -ain --delete SRC DEST ... | python3 ...`. The documented
#                way to run the fleet DELETION GUARD is blocked by this guard
#                (sp-9b01d746; already cost one false spillover finding and an
#                unmeasured propagation claim on PR #263).
#
# test_a_dry_run_stays_exempt_either_way above asserts only the SINGLE-command
# case, so it is green today and structurally blind to both directions.
#
# These cases drive the hook the harness drives, so they go red on the live hook
# until the fix lands and green after. KIPI_DESTRUCTIVE_HOOK points them at a
# candidate copy, which is how the fix was watched to flip each one; a case that
# has never been observed failing is not a regression test.

_HOOK_ENV = "KIPI_DESTRUCTIVE_HOOK"


def hook_copy(tmp_path):
    """A copy of the hook under test. Never the live file: decide() runs it, and
    a hook run with HOME redirected still writes an audit log."""
    src = _UNDER_TEST
    assert src.is_file(), "%s does not exist: %s" % (_HOOK_ENV, src)
    dst = tmp_path / "under-test.sh"
    shutil.copy(src, dst)
    dst.chmod(0o755)
    return dst


# An unrelated `--dry` earlier in the block, then a real fleet delete. Every one
# of these must BLOCK. Case 4 is the sharpest: it is the workflow the hook's own
# deny message recommends, typed into one command block.
COMPOUND_DECOYS = [
    # The canary that proved it: before/after showed the file really was deleted.
    'echo "an unrelated mention of --dry in a quoted string"\n'
    "rsync -a --delete /tmp/ask1118-src/ /tmp/ask1118-dst/",
    "echo --dry-run && kipi update",
    "rsync -a --delete /tmp/a/ /tmp/b/ ; echo 'that was not a --dry run'",
    "kipi update --dry-run; kipi update",
    "cd ~/projects/kipi-system && grep -- --dry kipi-update.sh && kipi update",
    # `-n` belongs to head, in a LATER pipeline stage. It is not rsync's dry flag
    # and must not read as one -- the shape a per-segment fix gets wrong if it
    # tests the whole segment instead of the stage that matched.
    "rsync -a --delete /tmp/a/ /tmp/b/ | head -n 20",
    # Short `-n` is RSYNC's spelling and nothing else's. Neither the updater nor
    # its wrapper has one, so reading a bare -n as a preview here would invent an
    # exemption that does not exist. (Added from mutation: dropping the rsync
    # gate in fleet_stage_is_preview survived every case above.)
    "kipi update -n",
    "bash kipi-update.sh -n",
    # A stage that begins with whitespace, because the boundary it followed was
    # consumed by the split. The FLEET_DENY patterns anchor on `^` or on a
    # `[;&|]` that is no longer there, so the deny vanishes unless the stage is
    # re-fed a boundary. (Added from mutation: dropping that survived too.)
    "echo --dry ;   rsync -a --delete SRC DEST",
    "echo --dry &&\t bash /Users/x/kipi-update.sh",
]

# Genuine dry runs in the short spellings. Every one must ALLOW.
SHORT_DRY = [
    # kipi-update-deletion-guard.py's own documented usage line.
    "rsync -ain --delete SRC DEST --exclude .git | python3 kipi-update-deletion-guard.py",
    "rsync -n -a --delete SRC DEST",
    "rsync -avn --delete SRC DEST",
    "rsync --delete -n SRC DEST",
    # `n` is not the last letter of the cluster. (Added from mutation: an
    # exemption regex ending at `n` survived the three cases above.)
    "rsync -nv --delete SRC DEST",
]

# The exemption that already worked. Must keep working.
LONG_DRY = [
    "kipi update --dry-run",
    "kipi update --dry",
    "rsync -a --delete --dry-run SRC DEST",
    "bash kipi-update.sh --dry",
]


class TestTheDryExemptionIsPerSegment:

    @pytest.mark.parametrize("command", COMPOUND_DECOYS)
    def test_an_unrelated_dry_does_not_disarm_the_apply(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "deny", (
            "a --dry elsewhere in the block waved through a real fleet delete: %r"
            % command)

    @pytest.mark.parametrize("command", SHORT_DRY)
    def test_rsyncs_short_dry_run_is_exempt(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "allow", (
            "a genuine dry run was blocked: %r" % command)

    @pytest.mark.parametrize("command", LONG_DRY)
    def test_the_single_command_exemption_still_holds(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "allow", command

    @pytest.mark.parametrize("command", REAL)
    def test_no_real_invocation_became_allowed(self, tmp_path, command):
        """Negative control. Segmenting the exemption must not segment a hole
        into the deny side: every shape the file already blocked stays blocked."""
        assert decide(hook_copy(tmp_path), command, tmp_path) == "deny", command

    def test_the_other_destructive_patterns_are_untouched(self, tmp_path):
        hook = hook_copy(tmp_path)
        for command in ("rm -rf /tmp/whatever", "git reset --hard",
                        "git push --force", "git clean -fd",
                        # BASH_DENY runs BEFORE the fleet block, so a dry flag
                        # must not reach it: this is an rm, not a preview.
                        "rm -rf /tmp/whatever --dry-run"):
            assert decide(hook, command, tmp_path) == "deny", command


# ===================================================================== ASK-1131
# THE THIRD HOLE IN THE SAME PREDICATE: IT IS POSITIONAL.
#
#     'rm[[:space:]]+-[a-zA-Z]*[rRf]'
#     'git[[:space:]]+reset[[:space:]]+--hard'
#
# Each pattern requires the dangerous token to sit IMMEDIATELY after the command
# name. Insert any innocuous flag ahead of it and the match position moves, so
# the delete runs unguarded. Proven with a canary: the plain recursive-force
# delete of a directory is BLOCKED, the same delete with -v inserted first
# EXECUTED and the directory was gone.
#
# This is worse than the dry-run hole. That one needs a compound command; this
# is a single natural invocation, and adding -v to watch what is being removed
# is something people type deliberately.
#
# HOW IT SURFACED, because the method matters more than the bug. Two agents
# measured the same guard and disagreed: one saw the git removal form BLOCKED,
# the other had run it successfully twice with -q inserted. Neither was wrong,
# and it was nearly filed as a long-flag-versus-short-flag runbook nit. Two
# contradictory measurements of one guard meant the guard was broken.
#
# THE FIX IS NOT A FOURTH PATTERN. Three patterns for three holes leaves the
# fourth. The hook now inspects each stage's ARGV -- program, subcommand, and
# every flag wherever it sits -- instead of regexing a substring of the line.
# The substring list is KEPT: it can only ever DENY, so nothing it already
# catches (including the deliberate prose false positives) changes.

# Every one of these really does destroy something, and every one currently
# slips the positional patterns. None may ever be allowed.
FLAG_POSITION = [
    # The coordinator's canary, verbatim in shape.
    "rm -v -rf /tmp/ask1131-canary",
    "rm -i -r /tmp/ask1131-canary",
    "rm --verbose -rf /tmp/ask1131-canary",
    "rm -v --recursive --force /tmp/ask1131-canary",
    "git push -q --force origin main",
    "git push --quiet --force-with-lease origin main",
    "git branch -q -D feature/x",
    "git clean -q -fd",
    "git reset -q --hard",
    # A global flag is a flag too: `git -C dir` moves the subcommand along.
    "git -C /tmp/repo reset --hard",
    "git -c user.name=x push --force origin main",
    # In a LATER stage, so the scan has to split the line before it can read an
    # argv at all: over the whole string the program reads as `echo`/`cd`.
    # (Added from mutation: replacing the stage split with `cat` survived every
    # case above.)
    "echo preparing; rm -v -rf /tmp/ask1131-canary",
    "cd /tmp && git push -q --force origin main",
    # A transparent prefix that takes its OWN options. Stripping the prefix name
    # alone leaves the prefix's option sitting where the program should be, so
    # the scan reads the program as `-u` and finds no rule. These are NOT caught
    # by the substring list either: the leading -v/-i is hole 3 again, so both
    # layers miss them together. (Codex major, PR #274.)
    "sudo -u root rm -v -rf /tmp/ask1131-canary",
    "env -i rm -v -rf /tmp/ask1131-canary",
    "nice -n 10 rm -i -r /tmp/ask1131-canary",
    "sudo -u root git push -q --force origin main",
    # The program token QUOTED or escaped. `"rm" -rf DIR` runs rm, and the
    # substring list misses it too because there is a quote between the name and
    # the space it wants. Escaping the name is also how you bypass an alias, so
    # it is a form people type on purpose. (Codex major, PR #274 round 2.)
    '"rm" -rf /tmp/ask1131-canary',
    "'rm' -rf /tmp/ask1131-canary",
    "\\rm -rf /tmp/ask1131-canary",
    '"git" push --force origin main',
]

# The other half of the fix, and the half a pattern-per-hole approach loses:
# ordinary commands that merely LOOK like the shapes above must still run.
FLAG_POSITION_SAFE = [
    "rm /tmp/one-file.txt",
    "rm -- /tmp/one-file.txt",
    # A LONG flag that happens to spell r, f and d inside it. A short-flag test
    # that forgets to skip `--` reads "interactive" as -r -f and refuses an
    # ordinary single-file delete. (Added from mutation: dropping that skip
    # survived every other case here.)
    "rm --interactive=once /tmp/one-file.txt",
    "ls -rf /tmp",
    "git push origin main",
    "git branch -q feature/x",
    "git reset -q HEAD~1",
    "git clean -n",
    "grep -rf patterns.txt src/",
    "git -C /tmp/repo status",
    # The same option-bearing prefixes in front of something harmless. Offering
    # the rules every starting position must not turn a prefix's own option into
    # a finding.
    "sudo -u root ls -rf /tmp",
    "nice -n 10 rm /tmp/one-file.txt",
]


class TestFlagPositionDoesNotMoveTheTarget:

    @pytest.mark.parametrize("command", FLAG_POSITION)
    def test_a_leading_flag_does_not_hide_the_dangerous_one(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "deny", (
            "a leading flag moved the dangerous one out of match position "
            "and the command ran unguarded: %r" % command)

    @pytest.mark.parametrize("command", FLAG_POSITION_SAFE)
    def test_an_ordinary_command_still_runs(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "allow", (
            "argv inspection blocked an ordinary command: %r" % command)

    @pytest.mark.parametrize("command", REAL)
    def test_the_fleet_shapes_are_unaffected(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "deny", command

    @pytest.mark.skipif(not HOOK.is_file(),
                        reason="no live hook on this machine; nothing to drift from")
    def test_the_vendored_copy_has_not_drifted(self):
        """The vendored copy is what CI actually executes. If it drifts from the
        hook that really runs, CI is green about a different program -- which is
        the same false green vendoring was added to remove, one layer over."""
        assert VENDORED.is_file(), "the vendored reference copy is missing: %s" % VENDORED
        assert VENDORED.read_bytes() == HOOK.read_bytes(), (
            "the vendored copy and the live hook have diverged. Re-vendor with:\n"
            "  cat %s > %s" % (HOOK, VENDORED))

    def test_git_clean_dry_run_is_a_known_false_positive(self, tmp_path):
        """`git clean -n -d` is a PREVIEW and is refused anyway.

        This pins what the hook does, not what it should do (Codex minor, PR
        #274 round 2). The rule lives inside a block that the only write path an
        agent has cannot modify: apply-claude-changes is additive-only, so a
        rule can be superseded by an earlier DENY but never loosened, and every
        earlier loop fires before anything new could clear this. Fixing it needs
        `replace` to reach hook text, which is sp-ae47f005 and is a deliberate
        widening with its own blast radius, not a side effect of this change.

        Left standing rather than hidden because the cost sits on the side this
        file already chose in 2026-08-07: the miss costs a deleted volume, the
        false positive costs one tool call. `git clean -n` alone still passes.
        When sp-ae47f005 lands, this test flips and that is the signal.
        """
        assert decide(hook_copy(tmp_path), "git clean -n -d", tmp_path) == "deny"

    def test_the_prose_false_positive_is_unchanged(self, tmp_path):
        """The hook deliberately does NOT tell prose from invocation, and argv
        inspection must not quietly change that either way: the substring list
        it sits beside is kept precisely so this stays as decided in 2026-08-07."""
        hook = hook_copy(tmp_path)
        assert decide(hook, 'echo "never run rm -rf on a volume"', tmp_path) == "deny"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
