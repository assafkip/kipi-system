#!/usr/bin/env python3
"""Apply the PR #85 round-15 fix to claude-path-write-guard.py.

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

# --- fix: a rebaseliner is INVOKED, not merely spelled -----------------------
A_OLD = '''            for stage in split_outside_quotes(stmt, ("|",)):
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
'''

A_NEW = '''            stages = []
            for stage in split_outside_quotes(stmt, ("|",)):
                tokens = _tokens_of(stage)
                assigns = dict(a.groups() for a in
                               (ASSIGN.match(t) for t in tokens) if a)
                stages.append((stage, tokens, assigns))
            # A PIPE CARRIES A NAME PAST THIS PARSER (review finding, round 15
            # fix, fail-closed side). `echo <tripwire> | xargs python3` EXECUTES
            # a token sitting in echo's argument position, so the slot test
            # cannot see it. When any stage of a pipeline is a sink, no stage can
            # be read for who-runs-what, and every stage falls back to naming.
            piped_into_sink = len(stages) > 1 and any(
                _basename_of(t, a) in SHELL_SINKS
                for _st, tk, a in stages for t in _exec_slots(tk, a))
            for stage, tokens, assigns in stages:
                # TWO TESTS, TWO QUESTIONS -- and only one of them is about
                # position. REACHING the baseline FILE (below) is done from any
                # argv position: `rm -f <baseline>`, `mv`, a redirect target. So
                # that test stays grammar-free, exactly as round 11 left it.
                #
                # INVOKING a rebaseliner is a different claim, and round 15's
                # MAJOR is that this line was answering it with spelling. See
                # _stage_names for what replaced it and what it still costs.
                #
                # The direction of failure is why a loose match is safe HERE and
                # was round 2's blocker in `_is_sanctioned`: matching text there
                # GRANTS an exemption (fail-open); matching here WITHDRAWS a
                # handoff (fail-closed). Every narrowing on this side is a hole
                # unless the shapes it drops cannot execute -- which is why the
                # wrapper prefixes below widen the candidate set instead of
                # being parsed.
                if _stage_names(stage, (LAYER2_BASELINE_NAME,), tokens, assigns):
                    return True
                if _stage_names(stage, REBASELINERS, tokens, assigns,
                                slots_only=not piped_into_sink):
                    return True
'''

B_OLD = '''    THE ONE PLACE THE RAW TEXT STILL WINS: an inline code string is a program
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
'''

B_NEW = '''    THE ONE PLACE THE RAW TEXT STILL WINS: an inline code string is a program
    this parser cannot read, so a rebaseliner invoked from inside one shows no
    path-shaped token. When the stage carries an INLINE_CODE_FLAGS token AND a
    shell sink to consume it, fall back to the substring match -- the same
    posture `_stage` already takes for `python3 -c "<code touching .claude>"`.
    Both conditions are checked over TOKENS, not the program position, so
    `nice bash -c '<code>'` is covered and `git -c user.name=x commit -m '<prose
    naming a rebaseliner>'` is not (git is no shell sink).

    SCAR (review finding, PR #85 round 15, MAJOR). "Path-shaped" was still
    spelling, not behaviour. A bare filename is one token whose basename IS the
    name wherever it sits, so an option's VALUE read as an invocation:

        git commit -m claude-integrity-tripwire.py -- q-system/*     BLOCKED
        python3 build.py --label claude-integrity-tripwire.py \\
                         --out dist/*.js                             BLOCKED

    The QUOTED form of the same message was allowed, so the verdict turned on
    whether the operator happened to type quotes. Five rounds of this issue have
    been that same false-block class, on a PreToolUse hook shipping to 23
    machines; a gate that blocks an ordinary commit is how a gate gets turned
    off.

    So `slots_only` asks the question the name was standing in for: could this
    stage EXECUTE that file? A token counts when it is in an EXECUTABLE SLOT
    (_exec_slots), plus an assignment VALUE, which _exec_position strips and
    which withdraws the handoff on its own (round 13 phase 5).

    NOT a return to `_program_names`, which round 13's blocker went through.
    _exec_slots never decides WHICH token is argv[0] behind a wrapper -- it
    widens to every later non-flag token and lets the caller be wrong in the
    fail-closed direction. `slots_only=False` (the baseline-FILE test, and any
    pipeline feeding a sink) keeps the any-position match untouched.

    WHAT IT STILL COSTS, named so the next round reads a decision: a wrapper
    this parser does not know, in front of a DIRECT (non-interpreter) invocation
    -- `setarch x86_64 ./claude-integrity-tripwire.py` -- is missed. Interpreted
    invocation behind an unknown wrapper is not, because the interpreter itself
    is the anchor and needs no prefix table. Pinned in probe_round15 phase 2.
    """
    if any(t in INLINE_CODE_FLAGS for t in tokens) and \\
            any(_basename_of(t, assigns) in SHELL_SINKS for t in tokens):
        return any(name in stage for name in names)
    if slots_only:
        if any(_basename_of(v, assigns) in names for v in assigns.values()):
            return True
        return any(_basename_of(t, assigns) in names
                   for t in _exec_slots(tokens, assigns))
    return any(_basename_of(t, assigns) in names for t in tokens)
'''

C_OLD = '''def _stage_names(stage, names, tokens, assigns):
'''
C_NEW = '''def _stage_names(stage, names, tokens, assigns, slots_only=False):
'''

# --- the new helpers, inserted ahead of their only caller --------------------
D_OLD = '''def _voids_layer2(command, cwd=None):
'''

D_NEW = '''def _tokens_of(seg):
    """One stage's tokens, with the shell's own comment rule applied. Factored
    out of _voids_layer2 in round 15 because _exec_slots needs the same answer
    and two spellings of "what are this stage's tokens" is the drift
    `_program_names` was split off to prevent."""
    try:
        return shlex.split(seg, comments=True)
    except ValueError:
        return seg.split()


# Programs that stand between the shell and the executable and then run one of
# their own operands. `env` is stripped by _exec_position already; the rest are
# named here for ONE purpose: widening the candidate set. Their operand grammars
# are deliberately NOT parsed -- `timeout`'s duration is neither a flag nor an
# assignment, and a table of which flags take a value is the fail-open surface
# round 10 deleted one for. Naming a wrapper costs a wider net, never a narrower
# one, so a member missing from this set can only ever cost a false NEGATIVE on
# a direct invocation -- the residual named in _stage_names.
EXEC_WRAPPERS = {"env", "nice", "timeout", "command", "nohup", "stdbuf",
                 "setsid", "ionice", "time", "chrt", "taskset", "sudo", "doas",
                 "runuser", "su", "xargs"}


def _exec_slots(tokens, assigns):
    """The tokens of ONE stage that could be the program it EXECUTES.

    Deliberately a SET, not an answer. Round 13's blocker was a function that
    committed to a single argv[0] and was wrong behind an assignment; the fix
    there was to stop asking about position at all, and round 15's finding is
    the bill for that. This returns every token that could hold the program and
    lets a miss be a false block rather than a hole.

    Two sources, neither of which needs a wrapper's operand grammar:

      * argv[0] once _exec_position has taken the assignment and `env` prefix
        off. When its basename is a known wrapper, EVERY later non-flag token
        joins the set, because which one is the program is exactly what the
        grammar would have told us.
      * an interpreter's first non-flag operand, from wherever the interpreter
        sits. `nice python3 X`, `timeout 20 python3 X` and `stdbuf -oL python3
        X` are one invocation with three prefixes, and the interpreter anchors
        all three without any of them being known.

    `python3 build.py --label <name> --out dist/*.js` therefore yields
    {python3, build.py}: the interpreter's operand is build.py, and <name> is
    what it is -- data.
    """
    toks = _exec_position(tokens)
    i = 0
    while i < len(toks) and toks[i].startswith("-"):
        i += 1
    if i >= len(toks):
        return []
    slots = [toks[i]]
    if _basename_of(toks[i], assigns) in EXEC_WRAPPERS:
        slots.extend(t for t in toks[i + 1:] if not t.startswith("-"))
    for j, tok in enumerate(toks):
        if _basename_of(tok, assigns) not in SHELL_SINKS:
            continue
        for later in toks[j + 1:]:
            if not later.startswith("-"):
                slots.append(later)
                break
    return slots


def _voids_layer2(command, cwd=None):
'''


def main():
    src = open(GUARD, encoding="utf-8").read()
    for name, old, new in (("A: the two tests, split", A_OLD, A_NEW),
                           ("B: _stage_names body", B_OLD, B_NEW),
                           ("C: _stage_names signature", C_OLD, C_NEW),
                           ("D: _exec_slots + _tokens_of", D_OLD, D_NEW)):
        if src.count(old) != 1:
            sys.stderr.write("anchor %s found %d times, refusing\n"
                             % (name, src.count(old)))
            return 1
        src = src.replace(old, new)
    open(GUARD, "w", encoding="utf-8").write(src)
    sys.stderr.write("patched %s\n" % GUARD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
