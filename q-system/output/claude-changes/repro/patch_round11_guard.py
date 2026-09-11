#!/usr/bin/env python3
"""One-shot patcher for the round-11 BLOCKER, Layer 1 half (ASK-291).

THE FINDING: "Deleting the baseline in the same Bash call as an unanchored
.claude write makes enforcement trust the tampered tree forever."

THIS IS ROUND 8 WITH A DIFFERENT VERB. Round 8 established the principle: the
handoff Layer 1 takes for an UNANCHORABLE `.claude/` write is a claim about what
happens AFTER this tool call -- the file lands, the hash moves, the tripwire
reverts it -- and a same-command re-baseline falsifies that claim. Deleting the
baseline falsifies the identical claim. Layer 1 never looked, because
`_rebaselines_layer2` asked WHICH PROGRAM RAN (`REBASELINERS`, the four
sanctioned appliers) and `rm` is not one of them. The baseline lives OUTSIDE
`.claude/`, so no `.claude` component appears in the delete either.

Measured against the pre-fix guard by probe_round11_findings.sh: 9 shapes, rc=0.

THE FIX IS THE QUESTION, NOT THE VERB. `_rebaselines_layer2` becomes
`_voids_layer2`, and it stops asking "did a sanctioned applier run" and starts
asking "can this command still be trusted to leave Layer 2 able to catch what I
am handing it". Enumerating the verbs that can unlink a file (`rm`, `mv`,
`shred`, `truncate`, `install`, `>`, a python one-liner, ...) is precisely the
fail-open surface this file's header warns about and round 10 deleted a table
for. So the new tests are about the PATH, not the program:

  (b) the baseline's filename appears in the text of any stage. Verdict needs
      zero grammar -- it covers `rm`, `mv`, `> base`, and `python3 -c
      "os.remove('base')"` identically, because all four have to NAME it.
  (c) a token could NAME the baseline. A glob can only match paths beginning
      with its literal prefix, so `claude-integrity-base*.json` is caught by
      bounding it; a plain literal is caught by equality or directory
      containment, so `rm -rf q-system` is caught too.

HONEST BOUND: a token whose literal prefix is EMPTY (`rm -f "${!V}"`, the path
entirely behind an indirect expansion) is not bounded by (c) and does not name
the baseline for (b). Treating every all-metacharacter token as reaching the
baseline would eat the pinned round-8/9 allow -- the unanchorable `.claude`
write is itself such a token, so every handoff would become a block and the
handoff would cease to exist. Captured as spillover instead of pretended away.
Layer 2's armed-marker (patch_round11_tripwire.py) is what covers that residue.
"""
import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TARGET = os.path.join(ROOT, "q-system", ".q-system", "scripts", "claude-path-write-guard.py")
src = io.open(TARGET, encoding="utf-8").read()

pairs = []

# ---------------------------------------------------------------- change 1 --
# Name the baseline Layer 1 is protecting, next to the list it complements.
pairs.append(('''REBASELINERS = SANCTIONED''',
              '''REBASELINERS = SANCTIONED

# Layer 2's baseline, named here because Layer 1 is the only thing that can
# protect it. Every other piece of Layer 2's machinery is watched BY the
# baseline -- both guard scripts are in the tripwire's EXTRA_WATCHED, so
# deleting one lands as `removed` on the next tool call (round-2 scar). The
# baseline is the one piece that cannot watch itself, which is exactly why
# round 11's blocker went through it.
#
# Kept in sync with claude-integrity-tripwire.py's BASELINE_REL by a test, not
# by hope: two files disagreeing about where the baseline lives would silently
# turn this whole check off.
LAYER2_BASELINE_REL = os.path.join(
    "q-system", ".q-system", "claude-integrity-baseline.json")
LAYER2_BASELINE_NAME = os.path.basename(LAYER2_BASELINE_REL)'''))

# ---------------------------------------------------------------- change 2 --
# The reach test, and the rename of the predicate that reads it.
pairs.append(('''def _rebaselines_layer2(command):
    """True if ANY stage of this command rewrites Layer 2\'s baseline.''',
              '''def _could_name_baseline(token, cwd, assigns, baseline_abs):
    """True if `token` could name Layer 2\'s baseline file.

    NOT a check for a writer. The question is reach: if this command can NAME
    the baseline, Layer 1 cannot promise the baseline still exists when the
    PostToolUse hook fires, and every handoff that depends on it is void.

    A GLOB IS BOUNDED BY ITS LITERAL PREFIX. `claude-integrity-base*.json`
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
    return baseline_abs == cand or baseline_abs.startswith(cand + os.sep)


def _voids_layer2(command, cwd=None):
    """True if ANY stage of this command could leave Layer 2 unable to catch
    what Layer 1 is handing off to it -- by REWRITING its baseline (round 8) or
    by REACHING the baseline file at all (round 11).'''))

# ---------------------------------------------------------------- change 3 --
# The round-11 half of the docstring, spliced where round 8's ends.
pairs.append(('''    Substitution bodies are searched too: `--register` hidden in a `<(...)` still
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
    return False''',
              '''    Substitution bodies are searched too: `--register` hidden in a `<(...)` still
    erases the baseline.

    ROUND 11 (BLOCKER): the same handoff is voided by DELETING the baseline, and
    the program test could never see it -- `rm` is not a sanctioned applier, and
    the baseline lives OUTSIDE `.claude/` so no `.claude` component appears in
    the delete. Measured, 9 shapes at rc=0 (probe_round11_findings.sh phases
    1-2): rm, mv, `: >`, `echo >`, a variable holding the path, a basename glob,
    a process substitution, `python3 -c "os.remove(...)"`, and an absolute path.

    THE VERB IS NOT THE QUESTION. Enumerating what can unlink a file is the
    fail-open surface this file\'s header warns about and round 10 deleted a
    whole table for. Both new tests are about the PATH:

      - the baseline\'s FILENAME appearing in a stage\'s text. Zero grammar, so
        `rm`, `mv`, a redirect and an interpreter code string all fall to it
        identically -- each one has to NAME the file.
      - a TOKEN that could name the baseline (_could_name_baseline), which
        bounds globs by their literal prefix and catches `rm -rf q-system` by
        directory containment.

    THE COST IS THE SAME ONE ROUND 8 PRICED, and it is only ever charged
    alongside an unanchorable `.claude/` write: mentioning the baseline in such
    a command blocks. The escape hatch is unchanged and free -- two Bash calls,
    between which Layer 2 runs and re-arms on the clean tree, which is exactly
    what the handoff assumes. Reading or deleting the baseline in a command with
    NO unanchorable `.claude/` write is untouched, pinned as allows in phase 3.
    """
    baseline_abs = os.path.normpath(os.path.join(cwd or os.getcwd(),
                                                 LAYER2_BASELINE_REL))
    for text in [command] + extract_substitutions(command):
        for stmt in split_outside_quotes(strip_heredocs(text), STATEMENT_OPS):
            for stage in split_outside_quotes(stmt, ("|",)):
                if LAYER2_BASELINE_NAME in stage:
                    return True
                try:
                    tokens = shlex.split(stage, comments=True)
                except ValueError:
                    tokens = stage.split()
                if any(c in REBASELINERS for c in _program_names(tokens)):
                    return True
                assigns = dict(a.groups() for a in
                               (ASSIGN.match(t) for t in tokens) if a)
                if any(_could_name_baseline(t, cwd or os.getcwd(), assigns,
                                            baseline_abs)
                       for t in tokens):
                    return True
    return False'''))

for old, new in pairs:
    if src.count(old) != 1:
        sys.exit("ANCHOR NOT UNIQUE (%d hits): %r" % (src.count(old), old[:70]))
    src = src.replace(old, new)

# The two call sites. Renamed predicate, and both now pass cwd so the reach test
# resolves relative tokens against the same tree the rest of the guard uses.
callsites = [
    ("    blind = _rebaselines_layer2(command)",
     "    blind = _voids_layer2(command, cwd)"),
    ("        if _rebaselines_layer2(command):",
     "        if _voids_layer2(command, cwd):"),
]
for old, new in callsites:
    if src.count(old) != 1:
        sys.exit("CALLSITE ANCHOR NOT UNIQUE (%d hits): %r" % (src.count(old), old))
    src = src.replace(old, new)

# The stderr help text named only the re-baseline half. Say both, or the founder
# reads "this command RE-BASELINES Layer 2" under an `rm` and distrusts the gate.
old_help = '''            sys.stderr.write(
                "This command also RE-BASELINES Layer 2 (%s), so a .claude/ path this "
                "parser cannot anchor has no backstop left and fails closed instead of "
                "being handed off (ASK-291 round 8). If the block is unexpected, run the "
                "two halves as SEPARATE Bash calls -- Layer 2 then runs between them, "
                "which is what the handoff assumes.\\n" % ", ".join(REBASELINERS))'''
new_help = '''            sys.stderr.write(
                "This command also VOIDS Layer 2 -- it re-baselines it (%s) or it "
                "reaches its baseline file (%s) -- so a .claude/ path this parser "
                "cannot anchor has no backstop left and fails closed instead of being "
                "handed off (ASK-291 rounds 8 and 11). If the block is unexpected, run "
                "the two halves as SEPARATE Bash calls -- Layer 2 then runs between "
                "them, which is what the handoff assumes.\\n"
                % (", ".join(REBASELINERS), LAYER2_BASELINE_REL))'''
if src.count(old_help) != 1:
    sys.exit("HELP ANCHOR NOT UNIQUE (%d hits)" % src.count(old_help))
src = src.replace(old_help, new_help)

io.open(TARGET, "w", encoding="utf-8").write(src)
print("patched %s (%d edits)" % (TARGET, len(pairs) + len(callsites) + 1))
