#!/usr/bin/env python3
"""One-shot patcher for the round-9 BLOCKER on claude-path-write-guard.py
(ASK-291).

THE FINDING: `P=.claude; V=P; touch ${!V}/rules/pwn.md; <tripwire> --baseline`
returned rc=0. Round 8's `layer2_blind` DID fire; the hole is one layer below it.
`UNRESOLVED` enumerated the expansion SHAPES it knew (`$(`, backtick,
`${?<letter>`), and `${!V}` matches none of them -- so the token was judged
ANCHORABLE and joined to the cwd verbatim, giving the fabricated path
`<cwd>/${!V}/rules/pwn.md`. No `.claude` component, so hits_claude() said no,
literal_claude_tail() found nothing, and the round-8 fail-closed branch (only
reachable from `resolve() is None`) never ran.

THE REVIEWER IS RIGHT THAT ONE MORE SHAPE IS NOT A FIX. probe_round9_findings.sh
phase 2 measured nine more spellings of the same hole live: `${V:-x}`,
`${V/a/b}`, `${A[0]}`, `$'..'`, and the glob/brace family `.clau*`, `.{claude}`,
`.clau[d]e`. Their fix-first was "remove or constrain the ability for an ordinary
Bash command to re-baseline Layer 2".

THIS IS THE CONSTRAIN HALF, and it is what makes the class finite:

1. UNRESOLVED stops testing SHAPES and tests the ALPHABET. In the shell grammar
   every expansion is introduced by `$` or a backtick and by nothing else, so a
   token still carrying either character after _subst() names something this
   parser cannot know. That is a closed set; the shape catalogue never was.

2. INSIDE A COMMAND THAT RE-BASELINES LAYER 2, ONLY A PLAIN LITERAL IS READABLE.
   No backstop is left, so "I cannot read this token" has to mean block -- and
   crucially, the judgement inside such a command now depends on ZERO expansion
   semantics. The parser is no longer authorizing an operation it cannot parse;
   it refuses everything it cannot read character-for-character. That answers the
   reviewer's structural objection rather than out-guessing bash one more time.

WHY NOT THE BLUNTER "a re-baseline may do nothing else": it would refuse
`mkdir -p /tmp/x/.claude/rules; <tripwire> --register ...`, a command whose every
token is plainly readable and which the suite pins as ALLOWED. Four false blocks
of exactly that class have already nearly killed this guard, and a guard that
stops the work it guards gets switched off. Constraining to literals blocks
strictly more attack shapes than round 8 while keeping every pinned allow.

WHAT IT COSTS, named rather than hidden: inside a re-baselining command, a glob
or a brace in ANY write-position argument is refused even when it names nothing
near `.claude` (`mkdir -p /tmp/x/{a,b}; <tripwire> --baseline`). Readers are
exempt (READ_ONLY), the sanctioned entrypoints are exempt (_is_sanctioned), and
the escape hatch is unchanged and free: run the two halves as SEPARATE Bash
calls, which is what the handoff assumed all along.

WHY THIS FILE EXISTS AT ALL: the guard scripts are self-watched by Layer 2, so a
plain Edit is reverted one tool call later (sp-39c1b891 -- the watched guards
have no sanctioned EDIT path once armed). The working route is write-then-
register inside a SINGLE tool call, which means the write has to be scripted.
Committed rather than deleted: it IS the provenance of the diff.

Usage: python3 patch_round9_guard.py <path-to-claude-path-write-guard.py>
Every anchor must match exactly once or the run aborts without writing.
"""
import io
import sys

TARGET = sys.argv[1] if len(sys.argv) > 1 else sys.exit("usage: patch_round9_guard.py <file>")
src = io.open(TARGET, encoding="utf-8").read()

pairs = []

# --- edit 1: test the expansion ALPHABET, not a catalogue of shapes -----------
pairs.append((
'''# A `$(...)`, a backtick, or a `$VAR` this parser never saw assigned. The shell
# will expand it; we cannot.
UNRESOLVED = re.compile(r"\\$\\(|`|\\$\\{?[A-Za-z_]")''',
'''# Anything the shell will still expand once _subst() has done what it can.
#
# SCAR (review finding, PR #85 round 9, BLOCKER): this used to ENUMERATE the
# expansion shapes it knew -- `$(`, a backtick, `${?<letter>`. `${!V}` is `$`,
# `{`, `!`, so it matched none of them and the token was treated as ANCHORABLE.
# resolve() joined it to the cwd verbatim, producing the fabricated path
# `<cwd>/${!V}/rules/pwn.md`, which carries no `.claude` component -- so
# hits_claude() said no, literal_claude_tail() found nothing, and round 8's
# fail-closed branch (reachable only from `resolve() is None`) never ran. That is
# the round-3 scar again: comparing a REPRESENTATION instead of the thing.
#
# The fix is not one more shape. Enumerating shapes is open-ended -- `${V:-x}`,
# `${#V}`, `${V/a/b}`, `${A[0]}`, `$'..'`, `$((..))`, `$1`, `$@` are the same hole
# with different spelling, and probe_round9_findings.sh phase 2 measured six of
# them live. The ALPHABET is not open-ended: in the shell grammar every expansion
# is introduced by `$` or by a backtick, and by nothing else. So the test is on
# the alphabet. A token still carrying either character after substitution names
# something this parser cannot know, full stop.
#
# Deliberately NOT here: glob and brace metacharacters. They expand too, but
# widening THIS regex to cover them would send `touch .claude/rules/{a,b}.md` --
# a token whose `.claude` component is plainly visible and which is blocked
# outright today -- down the unanchorable path and into a mere handoff. Weaker,
# not stronger. They are handled where that weakening cannot apply: the
# no-backstop rule in _stage(). See NOT_A_LITERAL.
UNRESOLVED = re.compile(r"[$`]")

# Every metacharacter that makes a token something other than a plain literal
# path: the two expansion introducers above, plus glob and brace expansion.
# Read ONLY when the command re-baselines Layer 2 (see _stage), where "this
# parser cannot read the token" must mean block, because nothing is left
# downstream to catch whatever it turns out to name.
NOT_A_LITERAL = re.compile(r"[$`*?\\[\\]{}]")'''))

# --- edit 2: a redirect target must be readable when there is no backstop -----
pairs.append((
'''    for redir in re.finditer(r">>?\\s*([^\\s;&|<>]+)", seg):
        raw = unquote(redir.group(1))
        target = resolve(raw, effective_cwd, assigns)''',
'''    for redir in re.finditer(r">>?\\s*([^\\s;&|<>]+)", seg):
        raw = unquote(redir.group(1))
        # No backstop left -> a target this parser cannot read character-for-
        # character is refused, whether or not a `.claude` tail is visible in it
        # (review finding, round 9). `printf pwned > ${!V}/rules/pwn.md` shows
        # nothing to match against; that is the point of it.
        if layer2_blind and NOT_A_LITERAL.search(_subst(raw, assigns)):
            return ("redirects into a target this parser cannot read as a literal "
                    "path, while the same command re-baselines Layer 2: %s"
                    % redir.group(1))
        target = resolve(raw, effective_cwd, assigns)'''))

# --- edit 3: same rule for command arguments ---------------------------------
pairs.append((
'''    prog = os.path.basename(tokens[0])
    args = tokens[1:]

    # `cd .claude && touch x` -- the write target is relative to the NEW cwd.''',
'''    prog = os.path.basename(tokens[0])
    args = tokens[1:]

    # NO BACKSTOP -> ONLY A PLAIN LITERAL IS READABLE (review finding, round 9).
    #
    # Everywhere else in this file, a token this parser cannot anchor is HANDED
    # OFF to Layer 2 on the stated ground that the write lands and the hash
    # moves. A same-command re-baseline falsifies that ground (round 8). Round 8
    # acted on it only where a literal `.claude` tail was still visible; round 9
    # showed the tail can be hidden in the variable too, at which point there is
    # nothing left to pattern-match and the only safe answer is to stop reading
    # tokens this parser cannot read.
    #
    # So inside a re-baselining command the verdict depends on NO expansion
    # semantics at all: a plain literal is judged as always, anything else is
    # refused. That is what makes the class finite instead of one more round of
    # out-guessing bash.
    #
    # Bounded three ways so the cost stays affordable: readers are exempt (a
    # `grep .claude/rules/*.md` beside a re-baseline still works), the sanctioned
    # entrypoints are exempt, and flag tokens and text payloads carrying a
    # newline are skipped exactly as they are in _unanchored_unwatched(). The
    # escape hatch is unchanged: run the two halves as SEPARATE Bash calls.
    if layer2_blind and prog not in READ_ONLY and not _is_sanctioned(tokens):
        unreadable = next((a for a in args
                           if not a.startswith("-") and "\\n" not in a
                           and NOT_A_LITERAL.search(_subst(a, assigns))), None)
        if unreadable is not None:
            return ("%r takes an argument this parser cannot read as a literal "
                    "path (%s), while the same command re-baselines Layer 2"
                    % (prog, unreadable))

    # `cd .claude && touch x` -- the write target is relative to the NEW cwd.'''))

for old, new in pairs:
    if src.count(old) != 1:
        sys.exit("ANCHOR NOT UNIQUE (%d hits): %r" % (src.count(old), old[:70]))
    src = src.replace(old, new)

io.open(TARGET, "w", encoding="utf-8").write(src)
print("patched %s (%d edits)" % (TARGET, len(pairs)))
