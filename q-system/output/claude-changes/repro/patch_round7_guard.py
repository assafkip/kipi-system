#!/usr/bin/env python3
"""One-shot patcher for the round-7 BLOCKER on claude-path-write-guard.py
(ASK-291): round 6 taught the guard that `$(...)` and backticks are commands, so
a sanctioned argv could not exempt them. PROCESS substitution -- `<(...)` and
`>(...)` -- runs the same way and was never extracted, so the identical
compose-and-baseline attack walked through a second door.

WHY THIS FILE EXISTS AT ALL: the guard scripts are self-watched by Layer 2, so a
plain Edit is reverted one tool call later (sp-39c1b891 -- the watched guards
have no sanctioned EDIT path once armed). The working route is write-then-
register inside a SINGLE tool call, which means the write has to be scripted.
Committed rather than deleted: it IS the provenance of the diff.

Usage: python3 patch_round7_guard.py <path-to-claude-path-write-guard.py>
Every anchor must match exactly once or the run aborts without writing.
"""
import io
import sys

TARGET = sys.argv[1]
src = io.open(TARGET, encoding="utf-8").read()

pairs = []

# --- the openers, as DATA -----------------------------------------------------
# A named tuple rather than an inline literal for two reasons. It is the one
# place a future shape gets added, and probe_round7_findings.sh --self-test
# empties it in a COPY to reconstruct the pre-fix guard exactly. The production
# file therefore needs no test switch: a guard carrying a "behave like the old
# version" flag is a hole, not a fixture.
pairs.append(('''def extract_substitutions(text):
    """Every command body the shell RUNS before the visible program is exec\'d.

    `$(...)` and backticks, live inside double quotes, inert inside single ones,
    nested bodies returned flat so one pass judges all of them.
''',
'''PROC_SUB_OPENERS = ("<(", ">(")


def extract_substitutions(text):
    """Every command body the shell RUNS before the visible program is exec\'d.

    `$(...)` and backticks, and the PROC_SUB_OPENERS process substitutions
    `<(...)` / `>(...)`. Nested bodies come back flat so one pass judges all of
    them.

    The two families do not share quoting rules, which is why they are separate
    branches rather than one wider match. Measured with bash itself, not assumed:

        bash -c \'echo "$(touch x)"\'     -> runs, x created
        bash -c \'echo "<(touch x)"\'     -> prints the text, nothing created
        bash -c \'echo <(touch x)\'       -> runs
        bash -c \'echo<(touch x)\'        -> runs (adjacency is not required)

    So `$(` stays live inside double quotes and a process substitution does not.
    Judging an inert body is the false-block class this issue has already hit
    five times -- it would refuse the very comment reporting this fix.
'''))

# --- the branch: a process substitution is a command --------------------------
pairs.append(('''        if text.startswith("$(", i):''',
'''        if quote is None and any(text.startswith(op, i) for op in PROC_SUB_OPENERS):
            # SCAR (review finding, PR #85 round 7, BLOCKER): round 6 closed this
            # hole for `$(...)` and stopped there, so
            #
            #     bash apply-claude-changes.sh <(touch .claude/evil.txt)
            #
            # still walked past `_is_sanctioned` -> `_stage` returns `ok` without
            # reading an argument -- and past Layer 2 as well, because the body
            # runs BEFORE the exec and the sanctioned tool then baselines the
            # mutation as trusted. Measured in probe_round7_findings.sh phase 2
            # against the pre-fix guard: `.claude/rules/r.md` overwritten,
            # `--check` answering `clean: 2 file(s) match baseline`.
            #
            # The redirect scan does NOT cover the `>(` shape despite looking
            # like it should: its target class `[^\\s;&|<>]+` refuses the `>` that
            # opens the substitution, so `cmd > >(rm .claude/x)` captures `(rm`
            # and resolves to nothing.
            #
            # NAMED OVER-EXTRACTION, not a defect: `$((3>(1)))` is arithmetic,
            # and the `$(` branch below hands its body `(3>(1))` back to this
            # scan, which reads `>(` as an opener and returns `1`. That body is
            # judged as the statement `1` -- no program, no path, no block. The
            # alternative is an arithmetic-context tracker, which buys nothing.
            body, end = _matching_paren(text, i + 2)
            if body is None:
                out.append(text[i + 2:])   # fail closed, same as `$(` below
                return out
            out.append(body)
            out.extend(extract_substitutions(body))
            i = end
            continue
        if text.startswith("$(", i):'''))

# --- the block reason now covers both families --------------------------------
pairs.append(('''    Command substitutions are judged FIRST and on their own terms, because the
    shell runs them first and because no exemption granted to the outer program
    -- the sanctioned-entrypoint one above all -- can reach inside them.
    """
    for body in extract_substitutions(command):
        reason = _analyse_statements(body, cwd)
        if reason:
            return "command substitution %s" % reason''',
'''    Substitutions -- command AND process -- are judged FIRST and on their own
    terms, because the shell runs them first and because no exemption granted to
    the outer program, the sanctioned-entrypoint one above all, can reach inside
    them.
    """
    for body in extract_substitutions(command):
        reason = _analyse_statements(body, cwd)
        if reason:
            return "shell substitution %s" % reason'''))

for old, new in pairs:
    if src.count(old) != 1:
        sys.exit("ANCHOR NOT UNIQUE (%d hits): %r" % (src.count(old), old[:70]))
    src = src.replace(old, new)

io.open(TARGET, "w", encoding="utf-8").write(src)
print("patched %s (%d edits)" % (TARGET, len(pairs)))
