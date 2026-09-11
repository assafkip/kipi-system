#!/usr/bin/env python3
"""One-shot patcher for the round-8 BLOCKER on claude-path-write-guard.py
(ASK-291).

Rounds 6 and 7 closed the sanctioned-command bypass for `$(...)`/backticks and
then for `<(...)`/`>(...)`: an exemption handed to the OUTER program must not
reach inside a substitution. Round 8 is the same underlying hole through a door
that needs no substitution at all.

    touch $UNSET/.claude/rules/pwn.md; <tripwire> --register .claude/rules/pwn.md

Layer 1 waves statement 1 through on a STATED ground -- `resolve()` cannot anchor
the token, and the file is one Layer 2 watches, so the hash will move and Layer 2
reverts it. Statement 2 falsifies that ground inside the same tool call: the
shell runs both, then the re-baseline records the tamper as trusted, and the
PostToolUse tripwire sees no drift. Both layers defeated, no alarm.

So the fix is not another opener in the extractor. It is: THE HANDOFF TO LAYER 2
IS VOID WHEN THE SAME COMMAND RE-BASELINES LAYER 2. Order-independent, because
`&&`/`||`/`;`/subshells do not hand this parser a reliable execution order and
inventing one is a new failure surface.

WHY THIS FILE EXISTS AT ALL: the guard scripts are self-watched by Layer 2, so a
plain Edit is reverted one tool call later (sp-39c1b891 -- the watched guards
have no sanctioned EDIT path once armed). The working route is write-then-
register inside a SINGLE tool call, which means the write has to be scripted.
Committed rather than deleted: it IS the provenance of the diff.

Usage: python3 patch_round8_guard.py <path-to-claude-path-write-guard.py>
Every anchor must match exactly once or the run aborts without writing.
"""
import io
import sys

TARGET = sys.argv[1]
src = io.open(TARGET, encoding="utf-8").read()

pairs = []

# --- the re-baseliner set, as DATA --------------------------------------------
# Its own name rather than SANCTIONED inline: the two lists answer different
# questions, and probe_round8_findings.sh --self-test empties THIS one in a COPY
# to reconstruct the pre-fix guard exactly. The production file therefore needs
# no test switch -- a guard carrying a "behave like the old version" flag is a
# hole, not a fixture.
pairs.append((
'''SANCTIONED = ("apply-claude-changes.sh", "apply_claude_changes.py",
              "claude-integrity-tripwire.py", "kipi-update.sh")''',
'''SANCTIONED = ("apply-claude-changes.sh", "apply_claude_changes.py",
              "claude-integrity-tripwire.py", "kipi-update.sh")

# The same four programs, named a SECOND time for a DIFFERENT property: each one
# rewrites Layer 2's baseline (the tripwire directly; the other three by calling
# it once they have written). Being sanctioned to write and being able to erase
# the backstop are not the same claim -- a future entrypoint could be one without
# the other -- so the next person editing one list does not silently change the
# other. See _rebaselines_layer2(), which is the only reader.
REBASELINERS = SANCTIONED'''))

# --- one reading of argv, shared by both program tests -------------------------
pairs.append((
'''    if not tokens:
        return False
    cands = [os.path.basename(tokens[0])]
    if cands[0] in ("bash", "sh", "zsh", "python", "python3") and len(tokens) > 1:
        for t in tokens[1:]:
            if not t.startswith("-"):
                cands.append(os.path.basename(t))
                break
    return any(c in SANCTIONED for c in cands)''',
'''    return any(c in SANCTIONED for c in _program_names(tokens))


def _program_names(tokens):
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
    cands = [os.path.basename(tokens[0])]
    if cands[0] in ("bash", "sh", "zsh", "python", "python3") and len(tokens) > 1:
        for t in tokens[1:]:
            if not t.startswith("-"):
                cands.append(os.path.basename(t))
                break
    return cands


def _rebaselines_layer2(command):
    """True if ANY stage of this command rewrites Layer 2's baseline.

    WHY THIS EXISTS (review finding, PR #85 round 8, BLOCKER). Layer 1 hands an
    UNANCHORABLE `.claude/` write to Layer 2 -- `resolve()` returns None, the
    named gap this file already documents -- on the explicit ground that the file
    lands and the hash moves, so the tripwire reverts it. That ground is a claim
    about what happens AFTER this tool call. A sanctioned re-baseline in the SAME
    call falsifies it:

        touch $UNSET/.claude/rules/pwn.md; <tripwire> --register .claude/rules/pwn.md

    The shell runs both before any PostToolUse hook fires, `--register` records
    the tampered file as the trusted state, and the tripwire that was supposed to
    be the backstop reports clean. Measured against the pre-fix guard by Codex
    and by probe_round8_findings.sh phase 1: rc=0, six shapes through.

    It is round 6 and round 7's hole a third time -- an exemption granted to one
    program reaching work it was never granted for -- but it needs no
    substitution at all, so the extractor could never have caught it. The
    exemption that matters here is not `_is_sanctioned` returning `ok` for a
    statement; it is the HANDOFF taken by a DIFFERENT statement whose backstop
    the sanctioned one erases.

    ORDER-INDEPENDENT on purpose. `;` is linear but `&&`, `||`, subshells and
    background jobs are not, and a parser that decides which side of a `;` runs
    first is a new failure surface guarding a hole it may get wrong. Blocking
    both orders costs one tool call and mis-ordering costs the gate.

    THE ESCAPE HATCH, and why the false-block cost is affordable: split the
    command into TWO Bash calls. Layer 2 then runs BETWEEN them, which is exactly
    the property the handoff assumed. probe_round8_findings.sh phase 3 pins the
    one real false block this buys (a temp fixture tree built in the same command
    as a re-baseline) rather than pretending the fix is free.

    Substitution bodies are searched too: `--register` hidden in a `<(...)` still
    erases the baseline.
    """
    for text in [command] + extract_substitutions(command):
        for stmt in split_outside_quotes(strip_heredocs(text), STATEMENT_OPS):
            for stage in split_outside_quotes(stmt, ("|",)):
                try:
                    tokens = shlex.split(stage, comments=True)
                except ValueError:
                    tokens = stage.split()
                if any(c in REBASELINERS for c in _program_names(tokens)):
                    return True
    return False'''))

# --- thread the void from analyse() down to the two handoff sites --------------
pairs.append((
'''    for body in extract_substitutions(command):
        reason = _analyse_statements(body, cwd)
        if reason:
            return "shell substitution %s" % reason
    return _analyse_statements(command, cwd)''',
'''    # Computed ONCE over the whole command, never per body: a substitution body
    # names no sanctioned program of its own, so a per-body flag would read False
    # for `<tripwire> --register x <(touch $UNSET/.claude/rules/pwn.md)`.
    blind = _rebaselines_layer2(command)
    for body in extract_substitutions(command):
        reason = _analyse_statements(body, cwd, blind)
        if reason:
            return "shell substitution %s" % reason
    return _analyse_statements(command, cwd, blind)'''))

pairs.append((
'''def _analyse_statements(command, cwd):
    """The statement-and-stage walk over one command string."""''',
'''def _analyse_statements(command, cwd, layer2_blind=False):
    """The statement-and-stage walk over one command string.

    `layer2_blind` is True when this command also re-baselines Layer 2, which
    voids every handoff to it. See _rebaselines_layer2()."""'''))

pairs.append((
'''            reason = _stage(seg, assigns, [effective_cwd], cwd)''',
'''            reason = _stage(seg, assigns, [effective_cwd], cwd, layer2_blind)'''))

pairs.append((
'''def _stage(seg, assigns, cwd_box, session_cwd=None):''',
'''def _stage(seg, assigns, cwd_box, session_cwd=None, layer2_blind=False):'''))

# --- handoff site 1: the redirect target ---------------------------------------
pairs.append((
'''        if target is None and unwatched_by_layer2(literal_claude_tail(raw, assigns) or ""):
            return ("redirects into a .claude/ file Layer 2 does not watch: %s"
                    % redir.group(1))''',
'''        if target is None:
            tail = literal_claude_tail(raw, assigns) or ""
            if unwatched_by_layer2(tail):
                return ("redirects into a .claude/ file Layer 2 does not watch: %s"
                        % redir.group(1))
            # Watched, but this command erases the baseline that would catch it.
            if layer2_blind and protected_position(tail):
                return ("redirects into .claude/ while re-baselining Layer 2: %s"
                        % redir.group(1))'''))

# --- handoff site 2: unanchorable argument tokens ------------------------------
pairs.append((
'''    touches += _unanchored_unwatched(args, effective_cwd, assigns)''',
'''    touches += _unanchored_unwatched(args, effective_cwd, assigns, layer2_blind)'''))

pairs.append((
'''def _unanchored_unwatched(args, cwd, assigns):''',
'''def _unanchored_unwatched(args, cwd, assigns, layer2_blind=False):'''))

pairs.append((
'''        tail = literal_claude_tail(arg, assigns)
        if tail and unwatched_by_layer2(tail):
            out.append(tail)
    return out''',
'''        tail = literal_claude_tail(arg, assigns)
        if not tail:
            continue
        # Normally only the files Layer 2 refuses to watch fail closed here. When
        # the command re-baselines Layer 2, NO protected position has a backstop
        # left, so every one of them does (review finding, round 8).
        if unwatched_by_layer2(tail) or (layer2_blind and protected_position(tail)):
            out.append(tail)
    return out'''))

# --- say the escape hatch in the block message, not only in a docstring --------
# The operator who trips this needs the remedy in the stderr they actually read.
pairs.append((
'''    reason = analyse(command, cwd)
    if reason:
        sys.stderr.write(
            "BLOCKED by claude-path-write-guard (ASK-282): %s\\n"
            ".claude/ wires every hook, rule and agent; an agent that writes there can "
            "disable its own gates. Use the sanctioned path: a proposal applied by "
            "apply-claude-changes.sh (additive-only, ratcheted, auto-reverting).\\n" % reason)
        return 2''',
'''    reason = analyse(command, cwd)
    if reason:
        sys.stderr.write(
            "BLOCKED by claude-path-write-guard (ASK-282): %s\\n"
            ".claude/ wires every hook, rule and agent; an agent that writes there can "
            "disable its own gates. Use the sanctioned path: a proposal applied by "
            "apply-claude-changes.sh (additive-only, ratcheted, auto-reverting).\\n" % reason)
        if _rebaselines_layer2(command):
            sys.stderr.write(
                "This command also RE-BASELINES Layer 2 (%s), so a .claude/ path this "
                "parser cannot anchor has no backstop left and fails closed instead of "
                "being handed off (ASK-291 round 8). If the block is unexpected, run the "
                "two halves as SEPARATE Bash calls -- Layer 2 then runs between them, "
                "which is what the handoff assumes.\\n" % ", ".join(REBASELINERS))
        return 2'''))

for old, new in pairs:
    if src.count(old) != 1:
        sys.exit("ANCHOR NOT UNIQUE (%d hits): %r" % (src.count(old), old[:70]))
    src = src.replace(old, new)

io.open(TARGET, "w", encoding="utf-8").write(src)
print("patched %s (%d edits)" % (TARGET, len(pairs)))
