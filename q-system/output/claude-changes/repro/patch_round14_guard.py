#!/usr/bin/env python3
"""Apply the PR #85 round-14 fixes to claude-path-write-guard.py.

WHY A SCRIPT AND NOT AN EDIT: the guard is in the tripwire's EXTRA_WATCHED, so an
ordinary Write/Edit is reverted and quarantined by Layer 2 before the next tool
call. The sanctioned route is patch-then-register in ONE Bash call, so the
baseline moves with the change before PostToolUse enforcement runs. Every round
of this issue that touched this file went in the same way.

Refuses on any anchor that is not found exactly once, so a partial application is
impossible.
"""
import os
import sys

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "..", "..", ".q-system", "scripts",
                     "claude-path-write-guard.py")
GUARD = os.path.normpath(GUARD)

# --- fix A: the rebaseliner/baseline name match is path-shaped, not substring --
A_OLD = '''            for stage in split_outside_quotes(stmt, ("|",)):
                if LAYER2_BASELINE_NAME in stage:
                    return True
                # THE NAME, NOT THE POSITION (review finding, round 13 BLOCKER).
                # This used to ask `_program_names` whether a rebaseliner sat in
                # the program position, and an environment assignment in front of
                # it answered no. Fixing the parser fixes that ONE spelling; the
                # next one is `nice`, then `timeout 20`, then `command`, then
                # `nohup`, each with its own operand grammar to get right.
                #
                # So this test now has no grammar at all, exactly like the
                # baseline-filename test one line above (round 11). The direction
                # of failure is why that is safe HERE and was round 2's blocker in
                # `_is_sanctioned`: matching text there GRANTS an exemption
                # (fail-open); matching text here WITHDRAWS a handoff
                # (fail-closed). Same rule, opposite consequence.
                #
                # The cost is the one round 8 priced and round 11 already charged:
                # naming one of these four files in a command that ALSO makes an
                # unanchorable `.claude/` write blocks. The escape hatch is
                # unchanged and free -- two Bash calls, with Layer 2 in between.
                if any(name in stage for name in REBASELINERS):
                    return True
                try:
                    tokens = shlex.split(stage, comments=True)
                except ValueError:
                    tokens = stage.split()
                assigns = dict(a.groups() for a in
                               (ASSIGN.match(t) for t in tokens) if a)
                if any(_could_name_baseline(t, cwd, assigns) for t in tokens):
                    return True
    return False
'''

A_NEW = '''            for stage in split_outside_quotes(stmt, ("|",)):
                try:
                    tokens = shlex.split(stage, comments=True)
                except ValueError:
                    tokens = stage.split()
                assigns = dict(a.groups() for a in
                               (ASSIGN.match(t) for t in tokens) if a)
                # THE NAME, NOT THE POSITION (review finding, round 13 BLOCKER).
                # Both tests below ask only whether the stage NAMES the file --
                # never where. An environment assignment, `env`, `nice`,
                # `timeout 20`, `command`, `nohup` and `stdbuf -oL` all sit
                # between the shell and the executable, and enumerating their
                # operand grammars is the fail-open surface round 10 deleted a
                # table for.
                #
                # The direction of failure is why a loose match is safe HERE and
                # was round 2's blocker in `_is_sanctioned`: matching text there
                # GRANTS an exemption (fail-open); matching here WITHDRAWS a
                # handoff (fail-closed).
                if _stage_names(stage, (LAYER2_BASELINE_NAME,), tokens, assigns):
                    return True
                if _stage_names(stage, REBASELINERS, tokens, assigns):
                    return True
                if any(_could_name_baseline(t, cwd, assigns) for t in tokens):
                    return True
    return False


def _stage_names(stage, names, tokens, assigns):
    """True if this stage NAMES one of `names` AS A FILE, in any argv position.

    SCAR (review finding, PR #85 round 14, MAJOR): round 13 made this test a raw
    `name in stage` substring match on the stated ground that it costs only "a
    command that BOTH makes an unanchorable `.claude/` write AND names one of the
    four files". The `.claude` half was never required. `_stage`'s no-backstop
    rule refuses ANY unreadable argument once this returns True, so a mention in
    a place the shell never executes was enough:

        python3 build.py --out dist/*.js  # see kipi-update.sh          BLOCKED
        git commit -m 'fix apply_claude_changes.py' -- q-system/*       BLOCKED

    The second is the exact commit shape this PR's own commits use, on a
    PreToolUse hook shipping to 23 machines. A gate that blocks the commit
    describing it is how a gate gets switched off -- five rounds of this issue
    are that same false-block class.

    So the mention must be PATH-SHAPED: some token whose basename is the name.
    That keeps every property round 13 bought (position-free, wrapper-free,
    grammar-free) and drops only the two shapes that cannot invoke anything:

      * a COMMENT -- `shlex.split(comments=True)` removes it, and so does the
        shell itself, so nothing is lost,
      * a PHRASE -- prose carrying the name as one word among several. Its
        basename is the whole phrase, which matches nothing.

    THE ONE PLACE THE RAW TEXT STILL WINS: an inline code string is a program
    this parser cannot read, so a rebaseliner invoked from inside one shows no
    path-shaped token. When the stage carries an INLINE_CODE_FLAGS token AND a
    shell sink to consume it, fall back to the substring match -- the same
    posture `_stage` already takes for `python3 -c "<code touching .claude>"`.
    Both conditions are checked over TOKENS, not the program position, so
    `nice bash -c '<code>'` is covered and `git -c user.name=x commit -m '<prose
    naming a rebaseliner>'` is not (git is no shell sink).
    """
    if any(t in INLINE_CODE_FLAGS for t in tokens) and \\
            any(_basename_of(t, assigns) in SHELL_SINKS for t in tokens):
        return any(name in stage for name in names)
    return any(_basename_of(t, assigns) in names for t in tokens)


def _basename_of(token, assigns):
    """The last path component a token names, with quotes and known variables
    resolved first. `FOO=q-system/.../tripwire.py` yields `tripwire.py`, which is
    deliberate: naming a rebaseliner in an assignment VALUE withdraws the handoff
    (fail-closed) even though it grants no exemption (round 13 phase 5)."""
    raw = _subst(unquote(token), assigns).strip()
    if not raw:
        return ""
    return os.path.basename(os.path.normpath(raw))
'''

# --- fix B: a glob cannot match a leading dot, because no shell glob does ------
B_OLD = '''        if NOT_A_LITERAL.search(got):
            if not fnmatch.fnmatchcase(want, got):
                return False
'''

B_NEW = '''        if NOT_A_LITERAL.search(got):
            # A LEADING DOT MUST BE WRITTEN OUT (review finding, round 14).
            # fnmatch does not know the one rule every shell applies to globs:
            # `*`, `?` and `[...]` never match a leading `.`. So `q-system/*`
            # fnmatch-ed onto `q-system/.q-system` and `cp -r q-system/* /tmp/`
            # was refused with stderr claiming it "re-baselines Layer 2", which
            # it cannot -- the expansion does not contain the baseline's
            # directory at all. `q-system/.q-*` still reaches it, because that
            # pattern wrote the dot.
            if want.startswith(".") and not got.startswith("."):
                return False
            if not fnmatch.fnmatchcase(want, got):
                return False
'''

# --- fix C: gh has read-only subcommands, exactly as git does ------------------
C_OLD = '''# Piping into an interpreter re-enters the shell with content this parser never
# inspected.'''

C_NEW = '''# `gh` is a routine READER in this fleet's review loop, and a `.claude/` pathspec
# on a read is a read (review finding, round 14: `gh pr diff 85 --
# .claude/settings.json` was refused with a message asserting it "would write
# inside .claude/"). Same shape as GIT_READ_ONLY and the same posture as
# READ_ONLY after round 10: membership is the claim "this subcommand has no
# file-writing channel", checkable once. Everything not listed still blocks, so
# `gh release download -D .claude` and an unknown subcommand are refused. A
# one-element entry matches on the first word alone.
GH_READ_ONLY = {
    ("api",), ("search",), ("browse",),
    ("pr", "diff"), ("pr", "view"), ("pr", "list"), ("pr", "checks"),
    ("pr", "status"), ("issue", "view"), ("issue", "list"),
    ("run", "view"), ("run", "list"), ("release", "view"), ("release", "list"),
    ("repo", "view"), ("auth", "status"), ("label", "list"),
}

# Piping into an interpreter re-enters the shell with content this parser never
# inspected.'''

D_OLD = '''    if prog == "git":
        sub = args[0] if args and not args[0].startswith("-") else ""
        if sub in GIT_READ_ONLY:
            return ok
        return "git %s targets .claude/: %s" % (sub or "?", touches[0])
'''

D_NEW = '''    if prog == "git":
        sub = args[0] if args and not args[0].startswith("-") else ""
        if sub in GIT_READ_ONLY:
            return ok
        return "git %s targets .claude/: %s" % (sub or "?", touches[0])

    if prog == "gh":
        words = tuple(a for a in args if not a.startswith("-"))[:2]
        if words[:1] in GH_READ_ONLY or words in GH_READ_ONLY:
            return ok
        return "gh %s targets .claude/: %s" % (" ".join(words) or "?", touches[0])
'''

PATCHES = [("rebaseliner name match", A_OLD, A_NEW),
           ("glob leading-dot rule", B_OLD, B_NEW),
           ("GH_READ_ONLY table", C_OLD, C_NEW),
           ("gh subcommand branch", D_OLD, D_NEW)]


def main():
    text = open(GUARD).read()
    for name, old, new in PATCHES:
        n = text.count(old)
        if n != 1:
            sys.stderr.write("REFUSED: anchor %r found %d times, expected 1\n"
                             % (name, n))
            return 1
        text = text.replace(old, new)
    import ast
    ast.parse(text)  # never install a file that will not import
    with open(GUARD, "w") as fh:
        fh.write(text)
    print("patched %s (%d anchors)" % (GUARD, len(PATCHES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
