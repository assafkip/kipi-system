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

# THE REPO COPY, so this suite can run somewhere other than one laptop (Codex
# major, PR #274). The hook is machine-local, so with no copy in the repo every
# case here skipped on every runner and verify.sh reported
# `pytest:test_destructive_op_deny_anchor.py ok` having executed NOTHING: 95
# assertions about the fleet's most destructive guard, gated by a false green.
#
# WHERE THE COPY LIVES IS THE WHOLE ARGUMENT (PR #269, rounds 4 and 5).
#
# Round 4: an earlier revision put a byte-identical copy at
# q-system/.q-system/hooks/destructive-op-deny.sh. Codex reviewed it as
# ENFORCEMENT and flagged its MCP wildcards. It was right to -- a shell script
# under `hooks/` reads as live, the capability gate treats it as a wiring
# surface, and ASK-1144 / PR #279 was already landing that exact path. Two
# branches adding one file is a guaranteed conflict and a second owner for a gate
# that must have exactly one.
#
# Round 5: referencing that path WITHOUT shipping a file left all 95 cases
# skipping and the suite exiting 0, which is the false green this whole thing was
# reported for. Deferring to #279 made the report true for longer.
#
# So: a FIXTURE, under tests/fixtures/, non-executable, with `.reference.` in its
# name. It cannot be mistaken for the gate by a reader, by the capability gate,
# or by a reviewer, and it collides with nothing. The deny SEMANTICS stay with
# ASK-1144; this file only has to be the same bytes, and the drift check below
# fails the moment it is not.
#
# The live hook is still the one that runs, and it is still what these cases
# prefer. sp-66e74091 carries the coupling.
REPO_COPY = (pathlib.Path(__file__).parent
             / "q-system/.q-system/tests/fixtures/destructive-op-deny.reference.sh")

if _OVERRIDE:
    _UNDER_TEST = pathlib.Path(_OVERRIDE)
elif HOOK.is_file():
    _UNDER_TEST = HOOK
else:
    _UNDER_TEST = REPO_COPY

# ASK-1954: THE COPY THIS CHANGE EDITS, WHICH IS NONE OF THE THREE ABOVE.
#
# The cascade above prefers the LIVE hook, then the reference fixture. Neither is
# the reviewed source: `install-claude-hooks.py` installs ~/.claude/hooks/ FROM
# this path, so this is the file a diff and a reviewer actually see. Measured
# 2026-09-26 (PR #447 review, finding 2): all three copies differ -- live 994
# lines, repo source 1206, fixture 501 -- so the ASK-1954 cases below were
# asserting a symmetry invariant about a file that has none of the change, and
# the registered verify suite went from 94 passed to 8 failed for that reason
# alone. A test that does not execute the copy under review is decoration
# (wiring-check.md, load-path proof).
#
# SCOPED TO THE ASK-1954 CLASSES ON PURPOSE, not flipped for the whole module.
# The 94 pre-existing cases keep the cascade: two of them
# (test_the_vendored_copy_has_not_drifted, the git-clean false positive) are RED
# against the repo source today because the fixture mirrors the drifted INSTALLED
# copy. Repointing the module would trade one false green for a red suite, and a
# red suite gets switched off. That drift is ASK-2131 / sp-28b070b4, which owns
# deciding which copy is authoritative and re-syncing the fixture.
REPO_SOURCE = (pathlib.Path(__file__).parent
               / "q-system/.q-system/hooks/destructive-op-deny.sh")

# The override still wins, so `.repro-1954.sh` and any candidate copy can drive
# these cases; absent it, the repo source is the default rather than the live one.
_ASK1954_SOURCE = pathlib.Path(_OVERRIDE) if _OVERRIDE else REPO_SOURCE

ask1954 = pytest.mark.skipif(
    not _ASK1954_SOURCE.is_file(),
    reason="the reviewed hook source is absent: %s" % _ASK1954_SOURCE)

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


def source_copy(tmp_path):
    """ASK-1954: a copy of the REVIEWED hook source, never the installed one.

    See REPO_SOURCE for why these cases do not ride the _UNDER_TEST cascade."""
    src = _ASK1954_SOURCE
    assert src.is_file(), "the reviewed hook source is absent: %s" % src
    dst = tmp_path / "reviewed-source.sh"
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
        assert REPO_COPY.is_file(), (
            "the reference fixture is missing: %s. Without it this whole module "
            "skips on any machine but one laptop, and a suite that skips reads "
            "exactly like a suite that passes." % REPO_COPY)
        if not HOOK.is_file():
            pytest.skip("no live hook on this machine, so there is nothing to "
                        "compare the fixture against. The other %d cases still "
                        "ran, against the fixture." % 94)
        assert REPO_COPY.read_bytes() == HOOK.read_bytes(), (
            "the reference fixture and the live hook have diverged. Re-sync:\n"
            "  cat %s > %s" % (HOOK, REPO_COPY))

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


# ===================================================================== ASK-1954
# THE DENY LIST AND THE ARGV PARSER NAME DIFFERENT PROGRAMS.
#
# ASK-1131 established the shape: a POSITIONAL substring pattern requires its
# dangerous token immediately after the command name, so a leading flag or a
# transparent prefix hides it, and `argv_deny_reason` exists to read the
# invocation instead. That fix was applied to exactly two programs -- `rm` and
# `git` -- and BASH_DENY + FLEET_DENY between them name eleven. The other nine
# kept the hole ASK-1131 was filed about, each in its own program:
#
#   find . -delete                  DENIED   (pattern matches)
#   sudo find . -delete             DENIED   (substring is position-free here)
#   ./kipi-update.sh                DENIED   (FLEET_DENY, command-anchored)
#   nohup ./kipi-update.sh          ALLOWED  <- the prefix sits between the
#                                               anchor and the script name, and
#                                               argv_deny_reason -- which DOES
#                                               strip nohup -- has no arm for it
#
# The two layers are not redundant, they are complementary, and a program in one
# and not the other has whichever hole the other layer was built to close. So the
# invariant is SYMMETRY, derived from the hook rather than restated here: every
# program the deny lists name has an argv arm, and every argv arm has a list
# entry. Deriving it is the point -- a hand-typed copy of either set agrees on the
# day it is written and goes green-but-wrong the next time a pattern lands.


def _hook_text():
    return _ASK1954_SOURCE.read_text(encoding="utf-8")


_WRAPPERS = ("bash", "sh", "zsh", "source")


def _deny_list_programs(text):
    """Programs named by BASH_DENY + FLEET_DENY, read from the hook.

    Each entry is an ERE. Bracket expressions are stripped first, then any
    leading alternation groups (the command-position anchors and the
    interpreter-wrapper group), and the program is the first identifier left.

    STRIPPING ORDER IS THE WHOLE PARSE, and the first version of it was wrong in
    a way that read as a finding. It tried to remove the anchor group with one
    non-greedy pattern whose character class omitted `:`, so `[[:space:]]` inside
    the group ended the match early, the group survived, and the first
    identifier in `(^|[;&|][[:space:]]*)rsync...` came back as `space`. Three
    entries reported a program that does not exist and `rsync` and
    `kipi-update.sh` were invisible -- a derivation that is not reading what you
    think, going RED for the wrong reason. Brackets come out first now, which
    removes the `:` problem at the source rather than spelling around it.
    """
    progs = set()
    for name in ("BASH_DENY", "FLEET_DENY"):
        block = re.search(r"declare -a %s=\(\n(.*?)\n  \)" % name, text, re.S)
        assert block, "%s block not found; the hook was restructured" % name
        for line in block.group(1).splitlines():
            line = line.strip()
            if not line.startswith("'"):
                continue                       # comment line inside the array
            entry = line.split("'")[1]
            body = entry
            # An entry that opens on a redirect or on `:` names no program: it
            # matches a redirection target or the fork bomb. Read from the shape
            # rather than from a list of words those entries happen to contain.
            if re.match(r"^[>:]", body):
                continue
            # AN INTERPRETER WRAPPER IS A PROGRAM TOO (PR #447 finding 1).
            #
            # This used to resolve the wrapper entry to the SCRIPT alone, on the
            # reasoning that the wrapper is not the destructive program. But
            # `$prog` in argv_deny_reason is whatever the invocation NAMES, and
            # `bash kipi-update.sh` names `bash`. The script had an arm, so the
            # symmetry check was green while `nohup bash kipi-update.sh` ran the
            # fleet-wide delete: the derived set agreed and the hook did not. A
            # derivation that cannot express the divergence it exists to catch is
            # worse than no derivation, because it retires the question.
            #
            # Read off the RAW entry, before the stripping below. The old
            # `tok in _WRAPPERS` branch was already dead code for this reason:
            # the leading-group loop consumes `(bash|sh|zsh|source)` on its way
            # to the script, so the wrapper token never reached that check.
            for group in re.findall(r"\(([^()]*)\)", entry):
                progs |= set(group.split("|")) & set(_WRAPPERS)
            body = re.sub(r"\[\[:[a-z]+:\]\]", "", body)   # POSIX classes
            body = re.sub(r"\[[^]]*\]", "", body)          # ordinary brackets
            while True:                                    # leading groups
                stripped = re.sub(r"^\([^()]*\)[*+?]?", "", body)
                if stripped == body:
                    break
                body = stripped
                if re.search(r"^[*+?.\\/~-]*[A-Za-z]", body) \
                        and not body.startswith("("):
                    break
            m = re.search(r"([A-Za-z][A-Za-z0-9_-]*(?:\\?\.sh)?)", body)
            if not m:
                continue
            progs.add(m.group(1).replace("\\", ""))
    return progs


def _argv_arm_programs(text):
    """The program basenames `argv_deny_reason` dispatches on, read from it."""
    fn = re.search(r"argv_deny_reason\(\) \{.*?\n    case \"\$prog\" in\n(.*?)"
                   r"\n    esac", text, re.S)
    assert fn, "argv_deny_reason's prog dispatch not found; the hook was restructured"
    arms = set()
    for line in fn.group(1).splitlines():
        m = re.match(r"\s{6}([A-Za-z0-9_.|*-]+)\)\s*$", line)
        if not m or m.group(1) == "*":
            continue
        for alt in m.group(1).split("|"):
            arms.add(alt)
    assert arms, "derived an EMPTY arm set; the parse is broken, not the hook"
    return arms


@ask1954
class TestTheCasesReadTheCopyUnderReview:
    """Load-path proof (wiring-check.md), and the reason it is a case not a note.

    PR #447 finding 2: the ASK-1954 cases rode the _UNDER_TEST cascade, which
    prefers the INSTALLED hook and falls back to the reference fixture, so they
    asserted a symmetry invariant about a file carrying none of the change while
    the registered verify suite went red. Grepping that the source contains the
    fix proves nothing about which copy a test executes; this asserts the copy."""

    def test_the_source_under_test_is_the_reviewed_repo_copy(self):
        assert _ASK1954_SOURCE.is_file(), _ASK1954_SOURCE
        if not os.environ.get(_HOOK_ENV):
            assert _ASK1954_SOURCE == REPO_SOURCE, (
                "with no override these cases must read the repo source, which "
                "is the copy install-claude-hooks.py installs FROM and the only "
                "one a reviewer sees: %s" % _ASK1954_SOURCE)
        assert "ASK-1954" in _hook_text(), (
            "the copy under test carries none of this change, so every case "
            "below is measuring a different program: %s" % _ASK1954_SOURCE)


@ask1954
class TestTheTwoLayersCoverTheSamePrograms:
    """The DoR check: any program in one set and not the other is a finding."""

    def test_the_derivations_are_bound_to_the_hook_not_restated(self, tmp_path):
        """Floor under both parses (derive-a-value-from-its-owner, step 3).

        An empty or near-empty parse turns the symmetry assertion below into a
        no-op that reads as green, so each derivation has to return something
        and has to see the two programs everyone already knows are there."""
        text = _hook_text()
        listed = _deny_list_programs(text)
        armed = _argv_arm_programs(text)
        assert len(listed) >= 8, listed
        assert {"rm", "git"} <= listed, listed
        assert {"rm", "git"} <= armed, armed
        # The interpreter wrappers, pinned so the collapse that hid PR #447
        # finding 1 cannot come back and read as green again. `bash
        # kipi-update.sh` dispatches on `bash`, so `bash` is a program here.
        assert set(_WRAPPERS) <= listed, (
            "the wrapper entry collapsed to the script again, which is the "
            "parse that reported symmetry while `nohup bash kipi-update.sh` "
            "ran the fleet-wide delete: %s" % sorted(listed))

    def test_every_deny_list_program_has_an_argv_arm(self):
        text = _hook_text()
        listed = _deny_list_programs(text)
        armed = _argv_arm_programs(text)
        missing = sorted(listed - armed)
        assert not missing, (
            "these programs are named by BASH_DENY/FLEET_DENY but "
            "argv_deny_reason does not dispatch on them, so each one keeps the "
            "ASK-1131 hole the argv layer exists to close (a leading flag or a "
            "transparent prefix hides the dangerous token): %s" % missing)

    def test_every_argv_arm_has_a_deny_list_entry(self):
        text = _hook_text()
        listed = _deny_list_programs(text)
        armed = _argv_arm_programs(text)
        extra = sorted(armed - listed)
        assert not extra, (
            "argv_deny_reason dispatches on these but no BASH_DENY/FLEET_DENY "
            "entry names them, so the cheap substring layer that runs first is "
            "blind to their plain spelling: %s" % extra)


@ask1954
class TestAnInterpreterWrapperCannotHideTheFleetDelete:
    """PR #447 finding 1. FLEET_DENY entry 2 is
    `(bash|sh|zsh|source)[[:space:]]+[^[:space:]]*kipi-update\\.sh`, whose
    `[^[:space:]]*` matches EMPTY, so the bare-basename spelling is denied at
    command position. Put a transparent prefix in front and the anchor no longer
    matches, and argv_deny_reason -- which strips exactly those prefixes -- had no
    arm to dispatch to afterwards. Measured ALLOW on the branch that closed this
    hole for `./kipi-update.sh`: the same hole, one spelling over."""

    WRAPPED = [
        "nohup bash kipi-update.sh",
        "time zsh kipi-update.sh",
        "env X=1 source kipi-update.sh",
        "nohup sh kipi-update.sh",
        "sudo bash kipi-update.sh",
        "nice -n 10 bash kipi-update.sh",
        "bash kipi-update.sh",                       # control: denied before too
        "nohup bash ./kipi-update.sh",
        "nohup bash kipi-update.sh --dry-run=0",
    ]

    @pytest.mark.parametrize("command", WRAPPED)
    def test_a_wrapped_fleet_sync_is_denied(self, tmp_path, command):
        assert decide(source_copy(tmp_path), command, tmp_path) == "deny", (
            "an interpreter wrapper behind a prefix ran the fleet-wide delete "
            "unchallenged: %r" % command)

    @pytest.mark.parametrize("command", [
        "bash kipi-update.sh --dry-run",
        "nohup bash kipi-update.sh --dry-run",
        "sh kipi-update.sh --dry",
    ])
    def test_a_wrapped_dry_run_is_still_allowed(self, tmp_path, command):
        """The half that decides whether the gate survives contact. Previewing is
        how you earn the run, and the wrapper arm must not change that."""
        assert decide(source_copy(tmp_path), command, tmp_path) == "allow", (
            "the preview carve-out broke for the wrapper spelling: %r" % command)

    @pytest.mark.parametrize("command", [
        "bash -c 'echo hi'",
        "bash ./build.sh",
        "source ~/.zshrc",
        "sh -c 'ls'",
    ])
    def test_an_ordinary_wrapper_invocation_is_untouched(self, tmp_path, command):
        """The arm is keyed on the OPERAND, never on the wrapper alone. Denying
        `bash` outright would refuse every script this fleet runs, and a guard
        that blocks ordinary work gets switched off."""
        assert decide(source_copy(tmp_path), command, tmp_path) == "allow", (
            "the wrapper arm denies ordinary work: %r" % command)


@ask1954
class TestEveryDeleteFlagRsyncHasIsCovered:
    """PR #447 finding 3. FLEET_DENY's `--delete` is a SUBSTRING, so it catches
    `--delete-after`, `--delete-before` and `--delete-excluded` at command
    position. The argv arm matched the exact long flag only, so it was strictly
    narrower than the entry it claims to mirror and a transparent prefix let the
    variants through. Every `--delete*` flag rsync has removes at the
    destination, so the arm mirrors the substring rather than enumerating."""

    VARIANTS = ["--delete", "--delete-after", "--delete-before",
                "--delete-excluded", "--delete-delay", "--delete-missing-args"]

    @pytest.mark.parametrize("flag", VARIANTS)
    def test_a_prefixed_delete_variant_is_denied(self, tmp_path, flag):
        command = "nohup rsync -a %s /tmp/a/ /tmp/b/" % flag
        assert decide(source_copy(tmp_path), command, tmp_path) == "deny", (
            "a prefix hid a delete flag the unprefixed form denies: %r" % command)

    @pytest.mark.parametrize("flag", VARIANTS)
    def test_the_preview_carve_out_holds_for_every_variant(self, tmp_path, flag):
        """`rsync -ain --delete ...` is the fleet deletion guard's own documented
        usage line (sp-9b01d746). Widening the flag match must not narrow that."""
        command = "nohup rsync -ain %s /tmp/a/ /tmp/b/" % flag
        assert decide(source_copy(tmp_path), command, tmp_path) == "allow", (
            "widening the delete match broke the documented preview: %r" % command)

    @pytest.mark.parametrize("command", [
        "rsync -a /tmp/a/ /tmp/b/",
        "nohup rsync -av /tmp/a/ /tmp/b/",
        "rsync -a --exclude=.git /tmp/a/ /tmp/b/",
    ])
    def test_a_copy_without_a_delete_flag_is_untouched(self, tmp_path, command):
        """Widening to `--delete*` must not reach a copy that deletes nothing."""
        assert decide(source_copy(tmp_path), command, tmp_path) == "allow", command


@ask1954
class TestATransparentPrefixCannotHideTheFleetDelete:
    """The prefixes `argv_deny_reason` already strips, in front of the updater.

    FLEET_DENY anchors the script at COMMAND POSITION, correctly -- reading the
    file is not running it. A transparent prefix sits between that anchor and the
    script name, so the anchor does not match; and the argv layer, which strips
    exactly these prefixes, had no arm for the updater. Both layers missed the
    same command, which is the ASK-1131 shape in a second program."""

    PREFIXED = [
        "nohup ./kipi-update.sh --dry-run=0",
        "env X=1 ./kipi-update.sh",
        "time ./kipi-update.sh",
        "nohup ./kipi-update.sh",
        "sudo ./kipi-update.sh",
        "nice -n 10 ./kipi-update.sh",
        "nohup kipi update",
    ]

    @pytest.mark.parametrize("command", PREFIXED)
    def test_a_prefixed_fleet_sync_is_denied(self, tmp_path, command):
        assert decide(source_copy(tmp_path), command, tmp_path) == "deny", (
            "a transparent prefix ran the fleet-wide delete unchallenged: %r"
            % command)

    def test_dry_run_zero_is_not_a_preview(self, tmp_path):
        """`--dry-run=0` is not a dry run and never was.

        kipi-update.sh parses `--dry-run` as an exact token (its argv loop, the
        `--dry-run)` arm) and exits 1 on anything else, so `--dry-run=0` is not
        a preview in the updater either. The exemption tested `*--dry*` as a
        SUBSTRING, so the string bought a pass the flag does not."""
        assert decide(source_copy(tmp_path), "./kipi-update.sh --dry-run=0",
                      tmp_path) == "deny"

    @pytest.mark.parametrize("command", [
        "kipi update --dry-run",
        "./kipi-update.sh --dry-run",
        "nohup ./kipi-update.sh --dry-run",
        "env X=1 ./kipi-update.sh --dry-run",
        "time ./kipi-update.sh --dry-run",
    ])
    def test_a_real_dry_run_is_still_allowed(self, tmp_path, command):
        """The other half, and the one that decides whether this gate survives.

        Previewing is how you EARN the run. A guard that refuses the preview is
        a guard someone switches off, and the hook says so in three places."""
        assert decide(source_copy(tmp_path), command, tmp_path) == "allow", (
            "the preview carve-out broke: %r" % command)

    @pytest.mark.parametrize("command", [
        "sed -n '1,20p' kipi-update.sh",
        "cat kipi-update.sh",
        "git log --oneline -- kipi-update.sh",
    ])
    def test_reading_the_updater_is_still_not_running_it(self, tmp_path, command):
        """The reason FLEET_DENY is anchored at all. Adding an argv arm must not
        undo it: a gate that blocks reads is a gate someone switches off."""
        assert decide(source_copy(tmp_path), command, tmp_path) == "allow", (
            "the new arm blocks reading the file: %r" % command)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
