#!/usr/bin/env python3
"""Round-11 pass 2 on claude-path-write-guard.py (ASK-291).

CAUGHT BY THE PERMANENT SUITE, not by review: test-claude-write-path.sh case D1
went from `ok L1 MISSES the command-substitution write (proved, exit 0)` to
`FAIL ... exit 2 -- test is no longer decisive`. That case is PINNED as a MISS on
purpose: it is the proof that Layer 2 is load-bearing, so Layer 1 blocking it
does not read as "stronger", it reads as "the decisive test is gone".

THE DEFECT: pass 1 bounded a glob by its LITERAL PREFIX as a flat string.

    token   .$P/settings.json      ->  prefix "."
    anchored to cwd, normpath      ->  cwd
    baseline_abs.startswith(cwd)   ->  True

So every token starting with `.` reached the baseline, which is nearly every
relative path. The prefix rule was sound about globs and wrong about PATHS: a
shell glob does not cross `/`. `*` matches inside ONE component, so a flat
startswith over-approximates by exactly the amount that made this useless.

THE FIX: ask the question component-wise, which is what a path is.
  - a component holding an EXPANSION (`$`, backtick, brace) can be any single
    component -- unknowable, so it does not veto,
  - a component holding a GLOB is matched with fnmatch against the baseline's
    component at that position -- precise, no filesystem access,
  - a LITERAL component must equal, and
  - a token with FEWER components than the baseline is a containing directory
    (`rm -rf q-system` reaches it), while MORE components names something
    deeper and cannot be it.

`.$P/settings.json` now falls at component 2 (`settings.json` != `.q-system`)
instead of passing on a one-character prefix, and the round-11 phase-2 shapes
still fall to the same rule.
"""
import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TARGET = os.path.join(ROOT, "q-system", ".q-system", "scripts", "claude-path-write-guard.py")
src = io.open(TARGET, encoding="utf-8").read()

old = '''    A GLOB IS BOUNDED BY ITS LITERAL PREFIX. `claude-integrity-base*.json`
    cannot match anything that does not start with `claude-integrity-base`, so
    the prefix is a sound over-approximation of what the token can name -- no
    globbing, no filesystem access, no guessing at the shell\'s expansion.

    A PLAIN LITERAL matches on equality or DIRECTORY CONTAINMENT, so `rm -rf
    q-system` reaches the baseline just as surely as naming the file, and is
    treated the same.

    An EMPTY prefix (the whole token is an expansion) returns False. That is the
    named bound in this patch\'s docstring: the unanchorable `.claude` write is
    itself such a token, so returning True here would collapse every handoff
    into a block and delete the handoff entirely."""
    raw = _subst(unquote(token), assigns)
    if not raw or raw.startswith("-"):
        return False
    m = NOT_A_LITERAL.search(raw)
    prefix = raw[:m.start()] if m else raw
    if not prefix:
        return False
    cand = prefix if os.path.isabs(prefix) else os.path.join(cwd, prefix)
    cand = os.path.normpath(cand)
    if m:
        return baseline_abs.startswith(cand)
    return baseline_abs == cand or baseline_abs.startswith(cand + os.sep)'''

new = '''    ASKED COMPONENT-WISE, because that is what a path is. Pass 1 bounded a glob
    by its flat literal prefix and `.$P/settings.json` produced the prefix "."
    -- which anchors to cwd, and every relative path starts with cwd. That made
    the check fire on nearly everything, and the permanent suite caught it: case
    D1 is PINNED as a Layer 1 MISS (it is the proof Layer 2 is load-bearing), and
    it started blocking. A shell glob does not cross `/`; `*` matches within ONE
    component. So:

      - a component holding an EXPANSION (`$`, backtick, brace) could be any
        single component. Unknowable, so it does not veto -- it is skipped,
      - a component holding a GLOB is fnmatch-ed against the baseline\'s
        component at that position. Precise, no filesystem access, no guessing,
      - a LITERAL component must be equal, and
      - FEWER components than the baseline means a CONTAINING DIRECTORY, so
        `rm -rf q-system` reaches the baseline and is treated as such. MORE
        components names something strictly deeper, which the baseline is not.

    A token that is ENTIRELY expansions still returns True only if every one of
    its components is unknowable AND it is no deeper than the baseline -- the
    unanchorable `.claude` write (`${!V}/rules/pwn.md`) fails at its second
    component (`rules` != `.q-system`), which is what keeps the round-8/9 handoff
    allow alive instead of collapsing every handoff into a block."""
    raw = _subst(unquote(token), assigns)
    if not raw or raw.startswith("-"):
        return False
    if not os.path.isabs(raw):
        raw = os.path.join(cwd, raw)
    parts = [p for p in os.path.normpath(raw).split(os.sep) if p not in ("", ".")]
    base_parts = [p for p in baseline_abs.split(os.sep) if p not in ("", ".")]
    if not parts or len(parts) > len(base_parts):
        return False
    for got, want in zip(parts, base_parts):
        if UNRESOLVED.search(got) or "{" in got or "}" in got:
            continue  # an expansion can be any single component
        if NOT_A_LITERAL.search(got):
            if not fnmatch.fnmatchcase(want, got):
                return False
        elif got != want:
            return False
    return True'''

if src.count(old) != 1:
    sys.exit("ANCHOR NOT UNIQUE (%d hits)" % src.count(old))
src = src.replace(old, new)

if "\nimport fnmatch\n" not in src:
    anchor = "\nimport os\n"
    if src.count(anchor) != 1:
        sys.exit("IMPORT ANCHOR NOT UNIQUE (%d hits)" % src.count(anchor))
    src = src.replace(anchor, "\nimport fnmatch\nimport os\n")

io.open(TARGET, "w", encoding="utf-8").write(src)
print("patched %s (pass 2)" % TARGET)
