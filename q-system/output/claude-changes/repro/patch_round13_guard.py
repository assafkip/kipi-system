#!/usr/bin/env python3
"""Round-13 blocker on claude-path-write-guard.py (ASK-291).

THE FINDING: "An environment assignment before a re-baselining command hides the
executable, allowing a same-call .claude tamper to be permanently recorded as
trusted" (claude-path-write-guard.py:1109). The reviewer's measurement:

    command=touch $UNSET/.claude/rules/pwn.md; KIPI_NOTIFY=/usr/bin/true python3 <trip> --baseline --quiet
    voids_layer2=False   guard_reason=None   trusted_sha=pwned   next_enforce_rc=0

CONFIRMED. `_program_names` read argv[0] literally, so the program was the token
`KIPI_NOTIFY=/usr/bin/true` -- whose basename is `true`, which is not an
interpreter, so argv[1] was never consulted either.

TWO FIXES, because the two callers of that function fail in OPPOSITE directions
and one rule cannot serve both:

  A. `_program_names` now strips the prefix that stands between the shell and the
     executable -- leading `NAME=value` assignments, and `env` with its own
     options and assignments. `_stage()` has done this since round 2; this
     function never learned, and one file holding two answers to "what is argv[0]"
     is exactly what `_program_names` was factored out to prevent. This is the
     EXEMPTION side, where a miss is a false block and an over-skip is a hole, so
     it stays precise and narrow.

     It also shuts a hole nobody had named: `os.path.basename` of an assignment
     token reads its VALUE, so `FOO=path/to/apply-claude-changes.sh <write>`
     answered SANCTIONED and disarmed the pipeline rule in `_analyse_statements`
     (line 845 passes RAW tokens). Measured True before this patch, phase 5.

  B. `_voids_layer2` stops asking the program position at all and names the four
     rebaseliners with NO GRAMMAR, exactly as it already names the baseline file
     one line above (round 11). This is the WITHDRAWAL side: matching text here
     removes a handoff rather than granting an exemption, so the substring rule
     that was round 2's blocker in `_is_sanctioned` is fail-CLOSED here. It costs
     nothing to be right about `env` and everything to be wrong about the next
     wrapper: `nice`, `timeout 20`, `command`, `nohup`, `stdbuf -oL` and every
     other prefix program are all covered by it without a table of which flags
     take a value -- the fail-open surface round 10 deleted one for.

THE COST, stated not hidden: a command that BOTH makes a `.claude/` write this
parser cannot anchor AND mentions one of the four filenames in any position now
blocks, where before it had to run one of them in the program position. That is
the same price round 11 already charged for `LAYER2_BASELINE_NAME in stage`, and
the escape hatch is unchanged and free: run the two halves as SEPARATE Bash
calls, between which Layer 2 runs.

RED before this patch, probe_round13_findings.sh: passed=12 failed=25 (1 of the
25 is the harness's own negative self-test).
"""
import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TARGET = os.path.join(ROOT, "q-system", ".q-system", "scripts",
                      "claude-path-write-guard.py")

src = io.open(TARGET, encoding="utf-8").read()


def swap(old, new, label):
    global src
    if src.count(old) != 1:
        sys.exit("%s ANCHOR NOT UNIQUE (%d hits)" % (label, src.count(old)))
    src = src.replace(old, new)


# --- A. the executable is not always argv[0] ---------------------------------
swap('''def _program_names(tokens):
    """The basenames a segment could be EXECUTING: argv[0], plus argv[1] when
    argv[0] is an interpreter, since `bash apply-claude-changes.sh ...` is the
    normal form.

    Factored out so the re-baseline test below asks the SAME structural question
    of the SAME positions. Two program allowlists reading argv two ways is how a
    bypass survives a round: round 1 shipped a substring match here and it took
    a review to notice the other test had never agreed with it.
    """
    if not tokens:
        return []
    cands = [os.path.basename(tokens[0])]''',
     '''# `env`'s two options whose value is a SEPARATE token. Deliberately short: an
# option this tuple does not know costs one skipped token, and the only thing
# downstream of a miss here is a false block on the sanctioned route.
ENV_SEPARATE_VALUE_OPTS = ("-u", "--unset", "-C", "--chdir")


def _env_split_string(tok, tokens, i):
    """`env -S "python3 x --baseline"` hides an entire command line inside ONE
    token. Returns that line's tokens, or None when this is not that option."""
    if tok in ("-S", "--split-string"):
        value = tokens[i + 1] if i + 1 < len(tokens) else ""
    elif tok.startswith("--split-string="):
        value = tok.split("=", 1)[1]
    elif tok.startswith("-S") and len(tok) > 2:
        value = tok[2:]
    else:
        return None
    try:
        return shlex.split(value)
    except ValueError:
        return value.split()


def _strip_one_prefix(tokens):
    """Remove ONE layer of what stands between the shell and the executable: the
    leading `NAME=value` assignments, plus one `env` and its own arguments.
    Returns the shorter list, or None when there was nothing to strip -- which is
    how _exec_position() terminates."""
    i = 0
    while i < len(tokens) and ASSIGN.match(tokens[i]):
        i += 1
    if i >= len(tokens) or os.path.basename(tokens[i]) != "env":
        return tokens[i:] if i else None
    i += 1
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--":
            return tokens[i + 1:]
        if ASSIGN.match(tok):
            i += 1
        elif not tok.startswith("-"):
            break
        elif tok in ENV_SEPARATE_VALUE_OPTS:
            i += 2
        else:
            inner = _env_split_string(tok, tokens, i)
            if inner is not None:
                return inner
            i += 1
    return tokens[i:]


def _exec_position(tokens):
    """The tokens from the EXECUTABLE onward.

    SCAR (review finding, PR #85 round 13, BLOCKER). `_program_names` read argv[0]
    literally, so in

        touch $UNSET/.claude/rules/pwn.md; KIPI_NOTIFY=/usr/bin/true python3 <tripwire> --baseline

    the program was `KIPI_NOTIFY=/usr/bin/true`, whose basename is `true` -- not an
    interpreter, so argv[1] was never consulted either. Measured by the reviewer:
    voids_layer2=False, trusted_sha=pwned, next_enforce_rc=0. `_stage()` has
    stripped these tokens since round 2; this function never did, and one file
    holding two answers to "what is argv[0]" is the drift `_program_names` was
    factored out to prevent.

    It also shuts a hole nobody had named: `os.path.basename` of an assignment
    reads its VALUE, so `FOO=path/to/apply-claude-changes.sh <write>` reported
    SANCTIONED and disarmed the pipeline rule at _analyse_statements, which passes
    RAW tokens. Pinned as a non-sanction, probe_round13 phase 5.

    WRAPPER PROGRAMS (`nice`, `timeout`, `command`, `nohup`, `stdbuf`) are
    deliberately NOT stripped here. Each carries its own operand grammar --
    `timeout`'s duration is neither an option nor an assignment -- and a table of
    which flags take a value is the fail-open surface round 10 deleted one for.
    They are covered where a miss is actually a hole: _voids_layer2 names the
    rebaseliners with no grammar at all. Missing one HERE can only cost a false
    block on the sanctioned route, which is the safe direction to be wrong in.
    """
    for _ in range(8):  # bounded: `env env env ...` must not loop forever
        stripped = _strip_one_prefix(tokens)
        if stripped is None:
            return tokens
        tokens = stripped
    return tokens


def _program_names(tokens):
    """The basenames a segment could be EXECUTING: argv[0] once the assignment and
    `env` prefix is off it, plus argv[1] when argv[0] is an interpreter, since
    `bash apply-claude-changes.sh ...` is the normal form.

    ONE CALLER NOW: `_is_sanctioned`, which GRANTS an exemption. Round 1 shipped a
    substring match here and it took a review to catch, because in this direction
    matching loose text is fail-OPEN. `_voids_layer2` used to share this function
    and no longer does -- it withdraws a handoff rather than granting anything, so
    loose text there is fail-CLOSED and it names the rebaseliners directly
    (round 13). Two callers with opposite failure directions were never really
    asking one question; pretending they were is what let an `env` prefix pass.
    """
    tokens = _exec_position(tokens)
    if not tokens:
        return []
    cands = [os.path.basename(tokens[0])]''',
     "PROGRAM_NAMES")

# --- B. the withdrawal side asks about the NAME, not the position ------------
swap('''                if LAYER2_BASELINE_NAME in stage:
                    return True
                try:
                    tokens = shlex.split(stage, comments=True)
                except ValueError:
                    tokens = stage.split()
                if any(c in REBASELINERS for c in _program_names(tokens)):
                    return True''',
     '''                if LAYER2_BASELINE_NAME in stage:
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
                    tokens = stage.split()''',
     "VOIDS")

# The constant's comment named a reader that has never existed under that name,
# and now points at the wrong shape as well. Correct the claim in place: a stale
# description is how the earlier rounds drifted.
swap('''# other. See _rebaselines_layer2(), which is the only reader.''',
     '''# other. Read by _voids_layer2(), which matches these names against a stage's
# TEXT rather than its program position -- see the comment there for why the
# loose match is the safe direction in that one place.''',
     "REBASELINERS_DOC")

swap('''    voids every handoff to it. See _rebaselines_layer2()."""''',
     '''    voids every handoff to it. See _voids_layer2()."""''',
     "BASELINE_NAME_DOC")

io.open(TARGET, "w", encoding="utf-8").write(src)
print("patched %s (round 13)" % TARGET)
