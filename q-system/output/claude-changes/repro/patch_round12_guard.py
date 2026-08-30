#!/usr/bin/env python3
"""Round-12 blocker on claude-path-write-guard.py (ASK-291).

THE FINDING: "Running from a repo subdirectory lets one Bash call delete both
tripwire records and tamper with .claude/settings.json, after which Layer 2
silently sanctions the tamper as a fresh tree." Measured by the reviewer with
cwd = <root>/q-system: `voids_layer2=False`, `analyse=None`.

IT IS A UNIT MISMATCH, not a missing spelling. `_could_name_baseline` rebased the
candidate token against the SESSION CWD, then compared it component-by-component
against `LAYER2_BASELINE_REL`, which is relative to the REPO ROOT. Those two
agree only while cwd IS the root. From `<root>/q-system` an absolute baseline
path relpaths to `.q-system/claude-integrity-baseline.json`, whose component 0 is
matched against the baseline's component 0 (`q-system`) -- mismatch, no reach,
allowed. Round 11's whole reach test switched itself off for every session whose
cwd is not the repo root, which is most of them.

Pass 3 of round 11 introduced this while fixing the opposite error, and the two
have to be fixed TOGETHER or they trade places:

  * comparing ABSOLUTE paths (round 11 pass 2) let the cwd components match
    literally on both sides, so every token under cwd inherited "concrete
    agreement" it never earned -- that is what blocked `{print $1}`.
  * comparing CWD-RELATIVE paths (round 11 pass 3) fixed that by throwing the
    positioning away with the padding, so from a subdirectory nothing lines up.

THE FIX SEPARATES THE TWO THINGS THOSE PASSES CONFLATED: rebase to the ROOT for
POSITIONING (so component i of the token is compared against component i of the
baseline, from any cwd), and count EVIDENCE only over components the TOKEN itself
supplied. A cwd component still has to MATCH -- a cwd that is not on the
baseline's path means no reach from there -- but it is not evidence, because
nobody wrote it. That is what keeps `{print $1}` (padded to `q-system/{print $1}`
from `<root>/q-system`) from becoming a false block through the new door.

Every guarded root is tried, not just GUARD_REPO_ROOT, because `guarded_roots()`
already owns the answer to "whose tree is this" and a per-tree baseline is a real
thing. A token that reaches none of them is another checkout's business (round 5).

RED before this patch, probe_round12_findings.sh: passed=17 failed=12 (1 of the
12 is the harness's own negative self-test).
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

new_body = '''    raw = _subst(unquote(token), assigns)
    if not raw or raw.startswith("-"):
        return False
    known_cwd = bool(cwd) and cwd != UNKNOWN_CWD
    # HOW MANY COMPONENTS THE TOKEN ITSELF SUPPLIED (review finding, round 12).
    # `..` consumes a cwd component instead of adding one, so the token's own
    # components are always the LAST `own` of the rebased path. An absolute token
    # supplied all of them; so does a relative token read with no cwd, which is
    # read as root-relative. `_agrees` is where this count earns its keep.
    own = None
    if not os.path.isabs(raw) and known_cwd:
        own = len([p for p in os.path.normpath(raw).split(os.sep)
                   if p not in ("", ".", "..")])
    base_parts = [p for p in LAYER2_BASELINE_REL.split(os.sep) if p not in ("", ".")]
    for root in guarded_roots(cwd if known_cwd else None):
        if os.path.isabs(raw):
            full = os.path.normpath(raw)
        elif known_cwd:
            full = os.path.normpath(os.path.join(cwd, raw))
        else:
            full = os.path.normpath(os.path.join(root, raw))
        parts = [p for p in os.path.relpath(full, root).split(os.sep)
                 if p not in ("", ".")]
        if not parts or parts[0] == ".." or len(parts) > len(base_parts):
            continue  # above this root, or strictly deeper than the baseline
        first_own = 0 if own is None else max(0, len(parts) - own)
        if _agrees(parts, base_parts, first_own):
            return True
    return False


def _agrees(parts, base_parts, first_own):
    """Component-wise agreement between a ROOT-REBASED token and the baseline.

    REACH REQUIRES EVIDENCE. An unknowable component (an expansion, a brace)
    cannot veto -- it really could be anything -- but it cannot AGREE either.
    Round 11 pass 2 let a token made entirely of unknowable components fall out
    of this loop having compared nothing and return True, which blocked
    `{print $1}` (an awk program text) as though it named the baseline.

    `first_own` is where the TOKEN's own components start; anything before it came
    from the cwd the token was rebased against. Those still have to MATCH -- a cwd
    that is not on the baseline's path means nothing under it can reach the
    baseline by a relative name -- but they are NOT evidence, because the token
    did not supply them. Counting them is round 11 pass 2's defect arriving
    through a new door: from `<root>/q-system` the padded path of `{print $1}` is
    `q-system/{print $1}`, whose first component agrees with the baseline's
    perfectly and was written by nobody."""
    evidence = 0
    for i, (got, want) in enumerate(zip(parts, base_parts)):
        if UNRESOLVED.search(got) or "{" in got or "}" in got:
            continue
        if NOT_A_LITERAL.search(got):
            if not fnmatch.fnmatchcase(want, got):
                return False
        elif got != want:
            return False
        if i >= first_own:
            evidence += 1
    return evidence > 0'''

if src.count(old_body) != 1:
    sys.exit("BODY ANCHOR NOT UNIQUE (%d hits)" % src.count(old_body))
src = src.replace(old_body, new_body)

# The docstring's positioning paragraph described the cwd-relative rule the body
# no longer implements. Two descriptions of one rule is how the previous rounds
# drifted; correct the claim in place rather than leaving it to be read as true.
doc_old = '''      - a component holding an EXPANSION (`$`, backtick, brace) could be any
        single component. Unknowable, so it does not veto -- it is skipped,'''
doc_new = '''      - the token is rebased onto each GUARDED ROOT, never onto the cwd, because
        `LAYER2_BASELINE_REL` is root-relative and comparing it against a
        cwd-relative path silently switched this whole check off for every
        session below the root (round 12 BLOCKER),
      - a component holding an EXPANSION (`$`, backtick, brace) could be any
        single component. Unknowable, so it does not veto -- it is skipped,'''
if src.count(doc_old) != 1:
    sys.exit("DOC ANCHOR NOT UNIQUE (%d hits)" % src.count(doc_old))
src = src.replace(doc_old, doc_new)

io.open(TARGET, "w", encoding="utf-8").write(src)
print("patched %s (round 12)" % TARGET)
