#!/usr/bin/env bash
# Reproducer for PR #85 round 12 (BLOCKER).
#
# THE FINDING, in the reviewer's words: "Running from a repo subdirectory lets
# one Bash call delete both tripwire records and tamper with .claude/settings.json,
# after which Layer 2 silently sanctions the tamper as a fresh tree"
# (claude-path-write-guard.py:980). Their measurement, cwd = <root>/q-system:
#
#     voids_layer2=False
#     analyse=None
#
# CONFIRMED, and it is a unit mismatch, not a missing spelling. `_could_name_baseline`
# rebases the candidate token against the SESSION CWD and then compares it,
# component by component, against `LAYER2_BASELINE_REL` -- which is relative to the
# REPO ROOT. The two agree only while cwd IS the root. From `<root>/q-system`:
#
#   * an ABSOLUTE baseline path becomes `.q-system/claude-integrity-baseline.json`
#     after relpath-to-cwd, whose component 0 (`.q-system`) is compared against the
#     baseline's component 0 (`q-system`) -- mismatch, no reach, allowed. The
#     round-11 `parts[0] == ".."` arm then swallows the `.claude` half for free.
#   * a RELATIVE delete written the way anyone in that directory would write it
#     (`rm -f .q-system/claude-integrity-baseline.json`) misses identically.
#
# So round 11's whole reach test silently switches off for every agent session
# whose cwd is not the repo root, which is most of them.
#
# WHAT DONE LOOKS LIKE (stated before the fix, per verification-loops):
#   phase 1  the reviewer's verbatim vector is caught from `<root>/q-system`
#   phase 2  the CLASS is caught: absolute, relative, dot-dot, and glob spellings
#            of the baseline, from cwd at three different depths
#   phase 3  cwd == root is unchanged -- round 11's greens stay green
#   phase 4  THE FALSE BLOCKS STAY DEAD. Rebasing to the root means cwd
#            components now sit in front of the token's, and a cwd that happens
#            to match the baseline's leading components must NOT hand a token
#            agreement it did not earn. That is exactly the pass-2 defect the
#            previous commit paid for (`{print $1}` blocked as a path), and it
#            comes back through a new door if evidence is counted over the padded
#            path instead of over the token.
#   phase 5  a token that reaches NO guarded root is still allowed (round 5's
#            project-scoping: another tree's baseline is that tree's business)
#
# NEGATIVE SELF-TEST: phase 0 asserts a verdict that is wrong today and wrong
# after the fix, so a harness that cannot fail is visible as such.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
GUARD="$ROOT/q-system/.q-system/scripts/claude-path-write-guard.py"
SUB="$ROOT/q-system"
DEEP="$ROOT/q-system/.q-system"
PASS=0; FAIL=0

pass() { PASS=$((PASS+1)); printf 'ok    %s\n' "$1"; }
fail() { FAIL=$((FAIL+1)); printf 'FAIL  %s\n' "$1"; }

# --- unit probe: the reach test itself, no filesystem, no hook envelope --------
voids() { # cmd cwd -> True/False
  GUARD="$GUARD" python3 -c '
import importlib.util, os, sys
p = os.environ["GUARD"]
s = importlib.util.spec_from_file_location("g", p)
g = importlib.util.module_from_spec(s); s.loader.exec_module(g)
print(g._voids_layer2(sys.argv[1], sys.argv[2]))
' "$1" "$2" 2>/dev/null
}

reaches() { # token cwd -> True/False  (the unit under test, directly)
  GUARD="$GUARD" python3 -c '
import importlib.util, os, sys
p = os.environ["GUARD"]
s = importlib.util.spec_from_file_location("g", p)
g = importlib.util.module_from_spec(s); s.loader.exec_module(g)
print(g._could_name_baseline(sys.argv[1], sys.argv[2], {}))
' "$1" "$2" 2>/dev/null
}

# --- end-to-end probe: the real hook, real stdin envelope, real rc ------------
run_at() { # cmd cwd -> rc
  python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]},"cwd":sys.argv[2]}))' "$1" "$2" \
    | CLAUDE_PROJECT_DIR="$ROOT" python3 "$GUARD" >/dev/null 2>&1
  echo $?
}

expect_voids() { # want desc cmd cwd
  local want="$1" desc="$2" got
  got="$(voids "$3" "$4")"
  [ "$got" = "$want" ] && pass "$desc (voids=$got)" || fail "$desc (voids=$got want=$want)"
}

expect_reach() { # want desc token cwd
  local want="$1" desc="$2" got
  got="$(reaches "$3" "$4")"
  [ "$got" = "$want" ] && pass "$desc (reach=$got)" || fail "$desc (reach=$got want=$want)"
}

expect_rc() { # want desc cmd cwd
  local want="$1" desc="$2" got
  got="$(run_at "$3" "$4")"
  [ "$got" = "$want" ] && pass "$desc (rc=$got)" || fail "$desc (rc=$got want=$want)"
}

BASE_REL="q-system/.q-system/claude-integrity-baseline.json"

echo "=== phase 0: negative self-test (this harness must be able to fail) ==="
got="$(reaches "definitely-not-the-baseline.txt" "$ROOT")"
if [ "$got" = "True" ]; then
  fail "negative self-test: a nonsense token must NOT reach the baseline"
else
  pass "negative self-test asserted a false claim and the harness counted it"
  FAIL=$((FAIL+1)); PASS=$((PASS-1))
  printf '      (deliberate: one FAIL is injected here, expected total FAIL=1)\n'
fi

echo
echo "=== phase 1: the reviewer's verbatim vector, cwd=<root>/q-system ==="
VECTOR="rm -f $ROOT/q-system/.q-system/*claude-integrity-*; printf pwned > $ROOT/.clau*/settings.json"
expect_voids True "reviewer's vector voids Layer 2" "$VECTOR" "$SUB"
expect_rc    2    "reviewer's vector is BLOCKED end to end" "$VECTOR" "$SUB"

echo
echo "=== phase 2: the class -- every spelling, from three cwd depths ==="
expect_reach True "absolute baseline path, cwd=subdir"        "$ROOT/$BASE_REL" "$SUB"
expect_reach True "absolute baseline path, cwd=deep subdir"   "$ROOT/$BASE_REL" "$DEEP"
expect_reach True "absolute glob over the records, cwd=subdir" "$ROOT/q-system/.q-system/*claude-integrity-*" "$SUB"
expect_reach True "relative-from-subdir delete"               ".q-system/claude-integrity-baseline.json" "$SUB"
expect_reach True "bare filename from the deep subdir"        "claude-integrity-baseline.json" "$DEEP"
expect_reach True "glob from the deep subdir"                 "*claude-integrity-*" "$DEEP"
expect_reach True "dot-dot back into the tree from subdir"    "../q-system/.q-system/claude-integrity-baseline.json" "$SUB"
expect_reach True "containing directory named from subdir"    ".q-system" "$SUB"

# The same shapes, in a command, beside an UNANCHORABLE .claude write. That pair
# is the actual hole: the write is handed off to a backstop the same call removes.
expect_voids True "relative delete + unanchorable write (cwd=subdir)" \
  "rm -f .q-system/claude-integrity-baseline.json; printf pwned > \$UNSET/.claude/settings.json" "$SUB"
expect_voids True "bare glob delete + unanchorable write (cwd=deep)" \
  "rm -f *claude-integrity-*; printf pwned > \$UNSET/.claude/settings.json" "$DEEP"

# A GLOB DOES NOT CROSS `/`. `*claude-integrity-*` reaches the baseline from the
# directory that HOLDS it and from nowhere else, so from `<root>/q-system` this is
# a correct NON-reach, not a hole. Pinned because the fix rebases onto the root,
# and the tempting shortcut -- test the glob against every remaining component
# instead of the one at its position -- would turn this into a false block on any
# `rm -f *something*` run from anywhere in the repo.
expect_reach False "a glob does not cross a separator (one level too high)" \
  "*claude-integrity-*" "$SUB"

echo
echo "=== phase 3: cwd == root is unchanged (round 11 stays green) ==="
expect_reach True  "absolute baseline path, cwd=root"       "$ROOT/$BASE_REL" "$ROOT"
expect_reach True  "root-relative baseline path, cwd=root"  "$BASE_REL" "$ROOT"
expect_reach True  "containing dir from root"               "q-system" "$ROOT"
expect_voids True  "round-11 rm vector still voids at root" \
  "rm -f $BASE_REL; printf pwned > \$UNSET/.claude/settings.json" "$ROOT"

echo
echo "=== phase 4: the false blocks stay dead (cwd padding is not evidence) ==="
# Every one of these is a token whose OWN components carry no agreement with the
# baseline. Rebasing to the root puts real cwd components in front of them; if
# those are counted as evidence, each of these becomes a false BLOCK.
expect_reach False "an awk program text is not a path (cwd=subdir)"   '{print $1}' "$SUB"
expect_reach False "an awk program text is not a path (cwd=deep)"     '{print $1}' "$DEEP"
expect_reach False "assignment fragment P=\$(printf (cwd=subdir)"     'P=$(printf' "$SUB"
expect_reach False "assignment fragment D=\$(mktemp (cwd=deep)"       'D=$(mktemp' "$DEEP"
expect_reach False "an all-expansion token reaches nothing (cwd=deep)" '${!V}' "$DEEP"
expect_reach False "an ordinary sibling file (cwd=subdir)"            "output/notes.md" "$SUB"
expect_reach False "an ordinary sibling file (cwd=deep)"              "scripts/foo.py"  "$DEEP"
expect_reach False "a bare subcommand word (cwd=deep)"                "commit" "$DEEP"
expect_reach False "a differently-named json beside the baseline"     "claude-integrity-other.json" "$DEEP"
expect_rc    0     "an ordinary command from a subdir is untouched" \
  "git commit -m 'work' && python3 -m pytest -q" "$DEEP"
expect_rc    0     "the pipe-into-awk escape hatch still passes" \
  "cat .claude/settings.json | awk '{print \$1}'" "$SUB"

echo
echo "=== phase 5: a token reaching no guarded root is still allowed ==="
expect_reach False "another checkout's baseline is that tree's business" \
  "/private/tmp/other-repo/$BASE_REL" "$SUB"

echo
printf 'passed=%d failed=%d\n' "$PASS" "$FAIL"
[ "$FAIL" -le 1 ] || exit 1
