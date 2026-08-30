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

# THE VENDORED COPY, ON EVERY MACHINE (Codex minor 4, PR #274 -- and the defect
# turned out to be wider than the finding said).
#
# This used to prefer the LIVE hook whenever one existed, on the reasoning that
# the live hook is what really runs. The consequence, measured when verify.sh
# refused the round-4 commit: the suite graded ~/.claude/hooks/... on the
# founder's laptop and the repo copy in CI, so the SAME suite was green about two
# different programs depending on where it ran -- exactly the false green the
# drift case below was written to prevent, arriving through the door next to it.
#
# It also made a hook change uncommittable. Nine cases pinning THIS branch's fix
# failed locally against a live hook that predates the fix, and the only way to
# make them pass would have been to deploy unreviewed guard code to the machine
# first. A gate you can only clear by shipping the thing under review is not a
# gate.
#
# So: the repo copy is the artifact under review, it is what CI executes, and it
# is what every behavioural case here grades. KIPI_DESTRUCTIVE_HOOK still points
# this at the live file for a deliberate check of the deployed copy.
if _OVERRIDE:
    _UNDER_TEST = pathlib.Path(_OVERRIDE)
else:
    _UNDER_TEST = VENDORED

CURRENT = "'kipi[[:space:]]+update'"
# Command position, allowing an env-var assignment prefix and command
# substitution, because those really do invoke it.
ANCHORED = (
    r"'(^|[;&|]|\$\(|`)[[:space:]]*"
    r"([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*kipi[[:space:]]+update'"
)

# The REVIEWED copy: this file as it stands on origin/main. Compared against the
# live hook below, deliberately NOT against the working tree -- comparing to the
# working tree makes every in-progress hook edit look like machine drift and
# blocks the commit that would fix it.
_VENDORED_REL = "q-system/.q-system/hooks/destructive-op-deny.sh"
try:
    _SHIPPED = subprocess.run(
        ["git", "-C", str(pathlib.Path(__file__).parent), "show",
         "origin/main:%s" % _VENDORED_REL],
        capture_output=True, check=True).stdout
except Exception:
    # No origin/main, no git, or the file is not on main yet (it is NEW in
    # PR #274). Nothing to compare against; the case skips and says so.
    _SHIPPED = None

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

    @pytest.mark.skipif(not HOOK.is_file() or _SHIPPED is None,
                        reason="needs BOTH a live hook and a copy of this file "
                               "on origin/main; one of them is absent here")
    def test_the_live_hook_is_running_reviewed_code(self):
        """The vendored copy and the live hook are byte-identical, ON A MACHINE
        THAT HAS BOTH.

        READ THIS CASE'S SILENCE NARROWLY (Codex minor, PR #274). An earlier
        docstring here said "the vendored copy is what CI actually executes, so
        if it drifts CI is green about a different program" -- which reads as a
        promise that CI is protected. It is not, and cannot be: the skipif right
        above tests HOOK, which is ~/.claude/hooks/destructive-op-deny.sh, and
        this module's own premise is that a runner does not have that file. So
        in CI this case SKIPS, every time, and nothing about drift is checked
        there at all.

        What it does cover is still worth having, and it is where drift is
        CREATED rather than where it is suffered: the founder's laptop, the only
        machine with a live hook to edit. Editing the live copy and forgetting to
        re-vendor goes red here on the next local run.

        What nothing covers: a push whose vendored copy was never re-synced, by
        someone whose laptop never ran the suite. Closing that needs a
        pre-push-side check with the live hook in hand, which is a different
        gate with a different blast radius, not a wider assertion here.
        """
        assert VENDORED.is_file(), "the vendored reference copy is missing: %s" % VENDORED
        assert HOOK.read_bytes() == _SHIPPED, (
            "the live hook on this machine is not the reviewed copy on "
            "origin/main. Deploy it through the sanctioned path -- "
            "apply-claude-changes.sh, never by hand -- or, if the live file is "
            "AHEAD, vendor it into the repo so it gets reviewed.\n"
            "  live:   %s\n"
            "  wanted: origin/main:%s" % (HOOK, _VENDORED_REL))

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


# ---------------------------------------------------------------------------
# PR #274 round 4 (Codex review of the round-3 branch). Two majors, both about
# the same edit: closing the argv holes for `rm`/`git` regressed the FLEET rules
# and made every Bash tool call quadratic.
# ---------------------------------------------------------------------------

# Each of these DENIED before this PR and ALLOWED on the branch as reviewed.
# Measured, not reasoned: probe output is in the commit message. The shape is
# always the same -- a preview stage sets the exemption, the apply stage escapes
# the POSITIONAL fleet regex, nothing denies, and the preview's early exit then
# allows the whole command.
FLEET_APPLY_BEHIND_A_PREVIEW = [
    # absolute path: the regex wants `rsync` at command position
    "rsync -n --delete /a/ /b/ && /usr/bin/rsync -a --delete /a/ /b/",
    # a transparent prefix moves it along
    "rsync -avn --delete /a/ /b/ ; time rsync -a --delete /a/ /b/",
    "kipi update --dry ; env FOO=1 rsync -a --delete /a/ /b/",
]

# The quoted forms. Round 3 of this PR added a whole quote-stripping layer
# because `"rm" -rf` slipped; the identical shape on the fleet delete was not
# covered, and it needs no preview stage to get through.
FLEET_APPLY_QUOTED = [
    '"rsync" -a --delete /a/ /b/',
    "'rsync' -a --delete /a/ /b/",
]

# The other direction. A fix that denies these is not a fix, it is the gate
# being switched off by whoever hits them.
FLEET_MUST_STILL_RUN = [
    "kipi update --dry",
    # kipi-update-deletion-guard.py's own documented usage line
    "rsync -ain --delete /a/ /b/ | python3 guard.py",
    # reading the script is not running it (see the comment above FLEET_DENY)
    "sed -n '1,20p' kipi-update.sh",
    "ls -l /usr/bin/rsync",
    "rsync -av /a/ /b/",
    "rsync --dry-run --delete /a/ /b/",
]


class TestFleetDeleteIsDecidedFromArgv:
    """The fleet rules must not be weaker than they were before this PR."""

    @pytest.mark.parametrize("command",
                             FLEET_APPLY_BEHIND_A_PREVIEW + FLEET_APPLY_QUOTED)
    def test_a_real_fleet_apply_is_refused(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "deny", (
            "this fleet-wide delete was ALLOWED. A guard fix that permits more "
            "than it did before is worse than the holes it closes: %r" % command)

    @pytest.mark.parametrize("command", FLEET_MUST_STILL_RUN)
    def test_the_previews_and_the_reads_still_run(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "allow", (
            "the fleet argv rules refused an ordinary command: %r" % command)

    def test_a_bare_apply_is_still_refused(self, tmp_path):
        """The pre-existing positional rules did not stop working."""
        for command in ("rsync -a --delete /a/ /b/", "kipi update",
                        "rsync -a --delete /a/ /b/ | head -n 20"):
            assert decide(hook_copy(tmp_path), command, tmp_path) == "deny", command


class TestTheScanIsNotQuadratic:
    """This hook runs PreToolUse on EVERY Bash call, so its cost is a property.

    Measured on the branch as reviewed, against a `cat > f <<EOF` heredoc of
    filler words -- how this fleet writes RCAs and PRDs, and the input that pays
    the whole cost because a denial short-circuits and a benign command does not:

        1000 words 1.41s    3000 words 9.93s    6000 words 34.77s

    After the candidate filter: 0.12s / 0.20s / 0.35s, and 12000 words in 0.75s.

    The ceiling below is deliberately loose. A tight one turns an unrelated slow
    runner into a red build and gets the case deleted; 5s still catches a return
    of the quadratic, which was 70x over that at this size and rising.
    """

    # 1 word in 4 is a CANDIDATE token. The first version of this case used
    # filler with zero rm/git tokens in it, so the candidate filter skipped
    # every position and it measured the one input the filter already handled:
    # it stayed green at 0.35s while a git-dense document of the same length
    # took 8.43s and blew the hook timeout (Codex major, PR #274 round 5). A
    # perf case whose input avoids the expensive path is decoration.
    # THE FILLER IS THE INSTRUMENT, and it has been wrong twice (Codex major,
    # PR #274 rounds 5 and 6). Round 4 used plain words: no candidate token, so
    # the filter skipped every position and it measured nothing. Round 5 used
    # bare `git`: rejected by the subcommand pre-filter in one iteration, so it
    # passed at 1.29s while `git push` prose took 8.28s. Each filler was picked
    # to exercise the path the PREVIOUS fix added, and each time the real cost
    # had moved. So the parameters below are the three shapes in order, and the
    # `git push` one is the load-bearing case: it reaches the full rule at every
    # candidate, which is the only input that can still be quadratic.
    @pytest.mark.parametrize("filler", [["word", "text"], ["git", "word"],
                                        ["git", "push"]])
    def test_a_long_benign_command_dense_in_candidates_is_decided_quickly(
            self, tmp_path, filler):
        import time
        body = " ".join((filler[0] if i % 2 == 0 else filler[1])
                        if (i // 2) % 2 == 0 else "w%d" % i
                        for i in range(8000))
        command = "cat > /tmp/doc.md <<'EOF'\n%s\nEOF" % body
        hook = hook_copy(tmp_path)
        start = time.time()
        verdict = decide(hook, command, tmp_path)
        elapsed = time.time() - start
        assert verdict == "allow", "the filler heredoc should not be denied"
        assert elapsed < 5.0, (
            "an 8000-word benign command built from %r took %.1fs. The hook is "
            "wired at timeout 5, and a PreToolUse hook that is killed returns "
            "NO decision -- so a real deletion buried in a long enough command "
            "is never refused." % (filler, elapsed))


# Every one of these ALLOWED before round 5. The token is `(rm`, whose
# basename is `(rm`, so no rule matched and no candidate position was offered.
# Round 3 added a whole layer to strip `"` `\'` and `\\` from the program token
# and stopped one character short of the class it was written for.
GROUPED = [
    "(rm -v -rf /tmp/d)",
    "$(rm -v -rf /tmp/d)",
    "`rm -v -rf /tmp/d`",
    "(git push -q --force origin main)",
    "(git -C /tmp/r reset -q --hard)",
    "(rsync -a --delete /a/ /b/)",
]


class TestShellGroupingDoesNotHideTheProgram:
    @pytest.mark.parametrize("command", GROUPED)
    def test_a_grouped_invocation_is_refused(self, tmp_path, command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "deny", (
            "shell grouping walked through the argv scan: %r" % command)

    @pytest.mark.parametrize("command", ["echo hello", "ls -la /tmp",
                                         "python3 -c 'print(1)'"])
    def test_stripping_them_does_not_deny_ordinary_commands(self, tmp_path,
                                                            command):
        assert decide(hook_copy(tmp_path), command, tmp_path) == "allow", command


class TestManyStagesAreAlsoBounded:
    """The fourth report of the timeout class, one level up (PR #274 round 7).

    ARGV_SCAN_TOKENS bounds the work INSIDE a stage. Nothing bounded how many
    stages a command has, and the per-stage cost is fork-bound in the fleet
    loop's greps, so it does not care what the stages contain:

        500 stages 3.30s    1000 stages 6.66s   <- over the 5s hook timeout

    The filler here is deliberately the shape that defeated round 5, so this
    case cannot pass for the cheap reason two earlier perf cases did.
    """

    def test_a_command_with_many_stages_is_decided_quickly(self, tmp_path):
        import time
        command = " ; ".join("echo git push word%d" % i for i in range(1000))
        hook = hook_copy(tmp_path)
        start = time.time()
        verdict = decide(hook, command, tmp_path)
        elapsed = time.time() - start
        assert verdict == "allow", command[:60]
        assert elapsed < 5.0, (
            "1000 benign stages took %.1fs against a hook wired at timeout 5. "
            "A killed PreToolUse hook returns NO decision." % elapsed)


class TestTheCandidateListCannotDriftFromTheRules:
    """The perf fix skips start positions whose program token matches no rule.

    That is only outcome-identical while the skip list names every rule. A rule
    added to argv_deny_reason and forgotten here would never be offered a
    position and would read exactly like a rule that works -- so this parses BOTH
    out of the hook and compares them, rather than trusting a comment that says
    to keep them in sync.
    """

    @staticmethod
    def _arms(text, header):
        """The labels of the first `case` block whose header line matches."""
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if header not in line:
                continue
            # Depth-tracked. A flat "stop at the first esac" scan returned the
            # arms of the NESTED case that walks git's global flags (-C, -c,
            # --git-dir), which is a confidently wrong answer rather than an
            # error -- the failure mode this whole class exists to prevent.
            arms, depth = set(), 1
            for rest in lines[i + 1:]:
                stripped = rest.strip()
                if re.search(r"\bcase\b.*\bin\b", stripped):
                    depth += 1
                    continue
                if stripped.startswith("esac"):
                    depth -= 1
                    if depth == 0:
                        return arms
                    continue
                if depth != 1:
                    continue
                m = re.match(r"^([A-Za-z0-9_.|\-]+)\)", stripped)
                if m:
                    arms |= {a for a in m.group(1).split("|") if a != "*"}
            raise AssertionError("unterminated case block for header %r" % header)
        raise AssertionError("no case block found for header %r" % header)

    def test_every_argv_rule_has_a_candidate_position(self):
        text = _UNDER_TEST.read_text(encoding="utf-8")
        rules = self._arms(text, 'case "$prog" in')
        assert rules, "parsed no rules out of argv_deny_reason; this test is inert"
        for header in ('case "${_sw[$_i]##*/}" in', 'case "${_dw[$_i]##*/}" in'):
            candidates = self._arms(text, header)
            assert rules <= candidates, (
                "argv_deny_reason handles %s but the candidate filter at %s only "
                "offers positions to %s. The missing rule is never evaluated and "
                "there is nothing to see: it fails exactly like a rule that never "
                "matches." % (sorted(rules), header, sorted(candidates)))


class TestAcceptedFalsePositives:
    """Pinned because they are a CHOICE, not an oversight (Codex minor, #274).

    Basename matching at every start position means a token that is a PATH TO
    `rm`, followed by any short cluster containing r, R or f, is refused:

        cp /bin/rm /tmp/x -f    -> deny

    It is the same trade already taken one step out for `docker rm -f`, and the
    fix in the other direction is worse than the bug. Skipping slash-carrying
    tokens at non-initial positions would let `sudo -u root /bin/rm -rf DIR`
    through, which is a real deletion, to save a refused `cp`. This file's
    standing trade since 2026-08-07 is that a miss costs a deleted volume and a
    false positive costs one tool call, so it stays fail-closed.

    If this ever flips to allow, that is a deliberate widening and it needs to
    arrive with the `sudo -u root /bin/rm` case still denied.
    """

    def test_a_path_to_rm_as_an_argument_is_refused(self, tmp_path):
        assert decide(hook_copy(tmp_path), "cp /bin/rm /tmp/x -f",
                      tmp_path) == "deny"

    def test_and_the_deletion_it_protects_stays_denied(self, tmp_path):
        assert decide(hook_copy(tmp_path), "sudo -u root /bin/rm -rf /tmp/d",
                      tmp_path) == "deny"

    def test_prose_naming_an_rsync_delete_is_refused(self, tmp_path):
        """New with the fleet argv scan, and stated rather than discovered.

        `set -f; ( $stage )` word-splits without honouring quotes, so a commit
        message that NAMES `rsync ... --delete` is read as an invocation. The
        anchored regex it joins did not do this.

        Consistent with what this hook has done since 2026-08-07 -- `echo "rm -rf
        x"` is denied on purpose, and the deny message names the way out: write
        docs with the Write/Edit tool, not a heredoc. The `kipi` arm was pulled
        back out of the anywhere-scan precisely because it cost this on the
        FLEET rule's own prose cases and bought no coverage; rsync keeps it
        because its regex is anchored and the argv pass is the only thing that
        catches `/usr/bin/rsync -a --delete`.
        """
        assert decide(hook_copy(tmp_path),
                      'git commit -m "note: rsync -a --delete wiped the tree"',
                      tmp_path) == "deny"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
