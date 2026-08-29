#!/usr/bin/env python3
"""Round-11 pass 3 on claude-path-write-guard.py (ASK-291).

MEASURED, not reasoned about (scan_round11_falseblocks.sh). Pass 2's three false
blocks all came from tokens that are NOT PATHS AT ALL:

    P=$(printf        (an assignment fragment left by splitting the stage)
    D=$(mktemp        (same)
    {print $1}        (an awk PROGRAM TEXT)

Every component of each was "unknowable" (holds `$` or a brace), every component
was therefore skipped, the loop ended having compared nothing, and the function
returned True. An over-approximation that returns True for a token it understood
NOTHING about is not conservative, it is vacuous -- and it took out the one case
the suite pins as a deliberate Layer 1 MISS (D1, the proof Layer 2 is
load-bearing) plus the temp-dir fixture and the pipe-into-awk escape hatch.

TWO CORRECTIONS:

1. REACH REQUIRES EVIDENCE. At least one component must be CONCRETE (a literal
   or a glob) and actually match the baseline's component at that position.
   Unknowable components still do not veto -- they just no longer count as
   agreement. `${!V}/rules/pwn.md` was already falling at `rules` != `.q-system`;
   now `{print $1}` falls too, for the honest reason that it agrees with nothing.

2. COMPARE THE PATH RELATIVE TO cwd. Pass 2 compared absolute paths, so the cwd
   components matched literally on BOTH sides and supplied the "evidence" that
   correction 1 asks for -- every token under cwd would have inherited a match it
   did not earn. The question is only ever about the tail below the repo root, so
   that is what is compared; a token that relpath puts outside cwd cannot be the
   baseline and says so immediately.

This restores the named bound from pass 1: a token that is entirely expansions
reaches nothing, and Layer 2's armed marker is what covers that residue.
"""
import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TARGET = os.path.join(ROOT, "q-system", ".q-system", "scripts", "claude-path-write-guard.py")
src = io.open(TARGET, encoding="utf-8").read()

old_body = '''    raw = _subst(unquote(token), assigns)
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

new_body = '''    raw = _subst(unquote(token), assigns)
    if not raw or raw.startswith("-"):
        return False
    # RELATIVE TO cwd, never absolute. Comparing absolute paths let the cwd
    # components match literally on both sides, which handed every token under
    # cwd the "concrete agreement" the check below demands without it having
    # earned any (pass 2). The question is only about the tail below the root.
    if os.path.isabs(raw):
        rel = os.path.relpath(os.path.normpath(raw), cwd)
    else:
        rel = os.path.normpath(raw)
    parts = [p for p in rel.split(os.sep) if p not in ("", ".")]
    base_parts = [p for p in LAYER2_BASELINE_REL.split(os.sep) if p not in ("", ".")]
    if not parts or parts[0] == ".." or len(parts) > len(base_parts):
        return False
    # REACH REQUIRES EVIDENCE. An unknowable component (an expansion, a brace)
    # cannot veto -- it really could be anything -- but it cannot AGREE either.
    # Pass 2 let a token made entirely of unknowable components fall out of this
    # loop having compared nothing and return True, which blocked `{print $1}`
    # (an awk program text) as though it named the baseline.
    concrete_matches = 0
    for got, want in zip(parts, base_parts):
        if UNRESOLVED.search(got) or "{" in got or "}" in got:
            continue
        if NOT_A_LITERAL.search(got):
            if not fnmatch.fnmatchcase(want, got):
                return False
        elif got != want:
            return False
        concrete_matches += 1
    return concrete_matches > 0'''

if src.count(old_body) != 1:
    sys.exit("BODY ANCHOR NOT UNIQUE (%d hits)" % src.count(old_body))
src = src.replace(old_body, new_body)

# Signature and call site: baseline_abs is no longer read.
sig_old = "def _could_name_baseline(token, cwd, assigns, baseline_abs):"
sig_new = "def _could_name_baseline(token, cwd, assigns):"
if src.count(sig_old) != 1:
    sys.exit("SIGNATURE ANCHOR NOT UNIQUE (%d hits)" % src.count(sig_old))
src = src.replace(sig_old, sig_new)

call_old = '''    baseline_abs = os.path.normpath(os.path.join(cwd or os.getcwd(),
                                                 LAYER2_BASELINE_REL))
    for text in [command] + extract_substitutions(command):'''
call_new = '''    cwd = cwd or os.getcwd()
    for text in [command] + extract_substitutions(command):'''
if src.count(call_old) != 1:
    sys.exit("CALL ANCHOR NOT UNIQUE (%d hits)" % src.count(call_old))
src = src.replace(call_old, call_new)

arg_old = '''                if any(_could_name_baseline(t, cwd or os.getcwd(), assigns,
                                            baseline_abs)
                       for t in tokens):'''
arg_new = '''                if any(_could_name_baseline(t, cwd, assigns) for t in tokens):'''
if src.count(arg_old) != 1:
    sys.exit("ARG ANCHOR NOT UNIQUE (%d hits)" % src.count(arg_old))
src = src.replace(arg_old, arg_new)

# The docstring paragraph pass 2 wrote about the empty-prefix bound is now stated
# by the code as "concrete_matches > 0"; correct the claim rather than leave two
# descriptions of one rule.
doc_old = '''    A token that is ENTIRELY expansions still returns True only if every one of
    its components is unknowable AND it is no deeper than the baseline -- the
    unanchorable `.claude` write (`${!V}/rules/pwn.md`) fails at its second
    component (`rules` != `.q-system`), which is what keeps the round-8/9 handoff
    allow alive instead of collapsing every handoff into a block."""'''
doc_new = '''    A token that is ENTIRELY expansions reaches NOTHING: it agrees with no
    component, so there is no evidence it names the baseline, and returning True
    on zero evidence is what made pass 2 block an awk program text. That is the
    named bound of this whole check -- `rm -f "${!V}"` is not caught here -- and
    Layer 2\'s armed marker is what covers it. It is also what keeps the round-8/9
    handoff alive: the unanchorable `.claude` write is itself such a token, and
    blocking on it would collapse every handoff and delete the handoff."""'''
if src.count(doc_old) != 1:
    sys.exit("DOC ANCHOR NOT UNIQUE (%d hits)" % src.count(doc_old))
src = src.replace(doc_old, doc_new)

io.open(TARGET, "w", encoding="utf-8").write(src)
print("patched %s (pass 3)" % TARGET)
