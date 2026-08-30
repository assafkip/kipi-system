#!/usr/bin/env python3
"""One-shot patcher for the round-10 BLOCKER on claude-path-write-guard.py
(ASK-291).

THE FINDING: "awk is treated as read-only, allowing it to overwrite
.claude/settings.json and sanction the disabled hooks with a same-command
baseline rewrite" (guard:994).

CONFIRMED, and the defect is one level up from `awk`. `READ_ONLY` declared
"programs that cannot write to a path they are given" while holding eight
programs that can. The file's answer to two of them was `READER_WRITE_FLAGS`,
an inner enumeration of the write FORMS of `sed` and `find` -- and that inner
list is exactly the fail-open surface this file's own header warns about:

    "Enumerating writers and getting it wrong yields a false ALLOW (silent, and
     the gate was never real). A gate fails closed; a filter fails open."

It knew `sed -i` and missed `sed 'w FILE'` / `sed 's///w FILE'` / `sed 'W FILE'`.
It knew `find -delete` / `-exec` and missed `-fprint` / `-fls` / `-fprintf`. It
never covered `awk` at all, despite the comment directly above it naming
"awk-into-a-file" as one of the two cases it handled. Measured live against the
pre-fix guard, all rc=0: sed 'w ...', sort -o, sort --output=, uniq OUT, tree -o,
xxd OUT, yq -i, find -fprint, awk system(), awk pipe-to-command.

TWO CHANGES, and neither is another spelling.

1. READ_ONLY STATES THE PROPERTY THE EXEMPTION ACTUALLY NEEDS, and holds only
   programs that have it: NO file-writing channel on ANY command line. Every
   program with a channel is dropped, and READER_WRITE_FLAGS -- the inner
   writer-enumeration -- is deleted with them. Enumerating a program's write
   forms is out-guessing its manual forever. Enumerating programs with no write
   channel at all is a claim that can be checked once and stays checked, and a
   mistake in it is a false BLOCK (loud, harmless) instead of a false ALLOW.
   The test suite pins the exact set, so growing it is a reviewed decision.

2. awk AND sed ARE INTERPRETERS, NOT READERS. Their write channel lives inside a
   PROGRAM TEXT, which component-wise path resolution structurally cannot see --
   the same shape this file already handles for python/perl/node ("an
   interpreter carries its target INSIDE a code string", guard:1035). awk and sed
   differ only in taking their script POSITIONALLY, so no inline-code flag
   announces it. They were misfiled as readers because they default to printing.
   The verdict therefore depends on ZERO awk/sed grammar: a `.claude` mention
   anywhere in the STAGE is a block.

NAMED COST, not hidden: a plain READ through one of these programs now blocks
too (`awk '{print $1}' .claude/settings.json`, `sed -n 1p .claude/settings.json`,
`sort .claude/settings.json`, `find .claude -name '*.md'`). That is the direction
this file's header chooses on purpose. The escape hatch is free and is pinned as
an allow: pipe the file in (`cat .claude/settings.json | awk '{print $1}'`), so
the interpreter's own stage names no path. Scoping the rule to the STAGE rather
than the statement is what keeps that hatch open.

WHY THE WRITE IS SCRIPTED: claude-path-write-guard.py is in the tripwire's
EXTRA_WATCHED set, so an unregistered edit is drift that --enforce reverts. The
edit and the --register have to land inside a SINGLE tool call.
"""
import io
import sys

TARGET = "q-system/.q-system/scripts/claude-path-write-guard.py"
src = io.open(TARGET, encoding="utf-8").read()

pairs = []

# ---------------------------------------------------------------- change 1 --
pairs.append(('''# Programs that cannot write to a path they are given. Small and stable by
# design. Anything not here is assumed write-capable.
READ_ONLY = {
    "cat", "ls", "head", "tail", "grep", "egrep", "fgrep", "rg", "ag",
    "wc", "stat", "file", "diff", "cmp", "awk", "sed", "cut", "sort", "uniq",
    "md5", "md5sum", "shasum", "sha256sum", "basename", "dirname", "realpath",
    "readlink", "test", "echo", "printf", "pwd", "which", "type", "du", "df",
    "jq", "yq", "column", "less", "more", "nl", "od", "xxd", "tree", "find",
}

# `sed -i` and `awk`-into-a-file are the two readers that can write. `find` can
# too (-delete / -exec). Handled explicitly below rather than dropped from the
# allowlist, because their read forms are common in normal work.
READER_WRITE_FLAGS = {
    "sed": re.compile(r"(^|\\s)-[a-zA-Z]*i"),
    "find": re.compile(r"(^|\\s)(-delete|-exec|-execdir|-ok)"),
}''', '''# Programs with NO file-writing channel on ANY command line. That is the exact
# property this exemption asserts, and it is what the next person adding a name
# here has to establish -- not "this is usually used as a read".
#
# SCAR (review finding, round 10): the set used to say "programs that cannot
# write to a path they are given" while holding eight programs that can, and the
# file's answer for two of them was READER_WRITE_FLAGS -- an inner enumeration of
# the write FORMS of `sed` and `find`. That inner list is precisely the fail-open
# surface this file's header warns about. It knew `sed -i` and missed
# `sed 'w FILE'`; it knew `find -delete` and missed `find -fprint`; and it never
# covered `awk` at all, despite the comment above it naming "awk-into-a-file".
# Enumerating a program's write forms is out-guessing its manual forever.
# Enumerating programs with no write channel at all is a claim that can be
# checked once and stays checked, and a mistake in it is a false BLOCK.
#
# Dropped, each with the channel that disqualifies it:
#   awk, sed    a PROGRAM TEXT that writes -- see SCRIPT_ARG_INTERPRETERS
#   sort        -o FILE / --output=FILE
#   uniq, xxd   the SECOND positional argument is the output file
#   tree        -o FILE
#   yq          -i (in place)
#   find        -delete / -exec / -execdir / -ok / -fprint / -fls / -fprintf
#   less, more  `+'s FILE'` runs the pager's save command at startup
#
# test-claude-write-path.sh pins this exact membership, so a later addition is a
# reviewed decision and not a quiet one.
READ_ONLY = {
    "cat", "ls", "head", "tail", "grep", "egrep", "fgrep", "rg", "ag",
    "wc", "stat", "file", "diff", "cmp", "cut",
    "md5", "md5sum", "shasum", "sha256sum", "basename", "dirname", "realpath",
    "readlink", "test", "echo", "printf", "pwd", "which", "type", "du", "df",
    "jq", "column", "nl", "od",
}

# Programs whose first non-flag argument is a PROGRAM in another language rather
# than a path, and that write THROUGH that program text: awk's `system()`,
# `print > "f"` and `print | "cmd"`; sed's `w FILE`, `W FILE` and `s///w FILE`.
#
# This file already holds exactly this principle for python/perl/node -- "an
# interpreter carries its target INSIDE a code string, where component-wise path
# resolution cannot see it" (see SHELL_SINKS / INLINE_CODE_FLAGS below). awk and
# sed differ only in that their script is POSITIONAL, so no inline-code flag
# announces it; they were misfiled as readers because they default to printing.
#
# The verdict for these depends on ZERO awk/sed grammar, which is the point: a
# `.claude` mention anywhere in the STAGE is a block. Stage, not statement, so
# the escape hatch stays open -- pipe the file in and the interpreter's own stage
# names no path at all. See _stage(), the only reader.
SCRIPT_ARG_INTERPRETERS = {"awk", "gawk", "mawk", "nawk", "sed", "ed"}'''))

# ---------------------------------------------------------------- change 2 --
pairs.append(('''    if _is_sanctioned(tokens):
        return ok

    # A token carrying a NEWLINE is a text payload, not a path''',
              '''    if _is_sanctioned(tokens):
        return ok

    # A PROGRAM TEXT this parser cannot read, in a stage that mentions .claude/
    # (review finding, round 10). `awk 'BEGIN{system("touch .claude/x")}'` and
    # `sed -n 'w .claude/x' f` both write, and neither shows a path token to
    # resolve or a write flag to match -- the target is inside the script.
    #
    # Deliberately NOT a parse of awk/sed: this parser cannot read those
    # languages, so it refuses to authorize based on them. Same posture round 9
    # reached for shell expansions, one layer over.
    #
    # Scoped to `seg` (this ONE pipeline stage), not the whole statement, which
    # is what keeps the escape hatch open and pinned as an allow:
    #     cat .claude/settings.json | awk '{print $1}'
    # stage 2 mentions no .claude, so it passes; the path is stage 1's, where
    # `cat` is a genuine reader.
    if prog in SCRIPT_ARG_INTERPRETERS and ".claude" in seg:
        return ("%r runs a program text this parser cannot read, and that text "
                "mentions .claude/" % prog)

    # A token carrying a NEWLINE is a text payload, not a path'''))

# ---------------------------------------------------------------- change 3 --
pairs.append(('''    if prog in READ_ONLY:
        pat = READER_WRITE_FLAGS.get(prog)
        if pat and pat.search(seg):
            return "%r used in its writing form on .claude/: %s" % (prog, touches[0])
        return ok''',
              '''    # No inner write-form table any more (review finding, round 10): a member of
    # READ_ONLY has no file-writing channel in any form, so there is nothing left
    # to match against. A program that grew one leaves the set instead.
    if prog in READ_ONLY:
        return ok'''))

for old, new in pairs:
    if src.count(old) != 1:
        sys.exit("ANCHOR NOT UNIQUE (%d hits): %r" % (src.count(old), old[:70]))
    src = src.replace(old, new)

io.open(TARGET, "w", encoding="utf-8").write(src)
print("patched %s (%d edits)" % (TARGET, len(pairs)))
