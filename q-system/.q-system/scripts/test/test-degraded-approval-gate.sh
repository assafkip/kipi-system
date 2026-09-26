#!/usr/bin/env bash
# Reproducer for ASK-2036 (sp-e9284708, promoted from the PR #114 review):
# `degraded` was written into every verdict record and read by NO production
# consumer. The only reader was `consumer_says`, a python heredoc defined inside
# test-review-degraded-provenance.sh -- so the fail-safe that file proves lived
# entirely inside that file.
#
# WHAT THAT COST. During a codex outage pr-review-agent.sh runs the Opus fallback
# so `kipi/reviewer-approved` does not wedge, and that status posts SUCCESS. The
# record says `degraded: true` and the human-facing surfaces say DEGRADED out
# loud, but `rework_gate` -- the one thing the worker and converge actually gate
# on -- never looked at the flag. An APPROVE written by the fallback reached the
# same waiting-on-merge branch as an APPROVE from a real second lab, and the
# worker ARMED auto-merge on it. The independence the codex engine exists to buy
# was gone and nothing in the loop could tell.
#
# THE FIX IS THREE-VALUED, NOT BINARY, and that is the half a careless migration
# breaks. Every record written before ASK-445 has no `degraded` key at all.
# Reading absent as `false` is a lie in the safe direction; reading it as `true`
# re-reviews every historical record on the board at once. Absent is UNKNOWN and
# keeps today's exit code, byte for byte -- case 3 below proves that against the
# PRE-FIX lib rather than against my model of it.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$SCRIPTS/../../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

LIB="$SCRIPTS/pr-verdict-lib.sh"
[ -f "$LIB" ] || { echo "missing $LIB"; exit 1; }

# ---------------------------------------------------------------------------
# A lib copy we can mutate, with repo-slug-lib.sh beside it -- pr-verdict-lib.sh
# sources that from its own BASH_SOURCE dir, so a copy alone would not load.
# ---------------------------------------------------------------------------
lib_copy() {   # lib_copy <dir> <source-lib>  -> prints the copied lib path
  local dir="$1" src="$2"
  mkdir -p "$dir"
  cp "$src" "$dir/pr-verdict-lib.sh"
  cp "$SCRIPTS/repo-slug-lib.sh" "$dir/repo-slug-lib.sh"
  printf '%s' "$dir/pr-verdict-lib.sh"
}

# THE PRE-FIX READER, taken from git rather than reconstructed. Case 3's whole
# claim is "the absent-key case returns what it returns TODAY", and a hand-typed
# expectation would assert my model of today instead of today itself -- the
# restated-value defect the lessons corpus names. If the file is not in git yet
# (a fresh worktree, a detached state) the case says so and fails rather than
# quietly skipping: an unrun check that reads as green is the worse outcome.
PREFIX_LIB=""
if git -C "$REPO" show "HEAD:q-system/.q-system/scripts/pr-verdict-lib.sh" \
     > "$WORK/prefix-raw.sh" 2>/dev/null && [ -s "$WORK/prefix-raw.sh" ]; then
  PREFIX_LIB="$(lib_copy "$WORK/prefix" "$WORK/prefix-raw.sh")"
fi

# ---------------------------------------------------------------------------
# Drive rework_gate in a subshell against a chosen lib. Prints "<exit>|<stdout>"
# so a case can compare BOTH halves: the gate's NOTE lines are part of what a
# caller sees, and a migration that changed only the prose would still be a
# behaviour change for anyone grepping the run log.
# ---------------------------------------------------------------------------
gate_run() {   # gate_run <lib> <verdict> <merge-state> <reviewed-sha> <cur-sha> [degraded]
  local lib="$1"; shift
  local out rc
  out="$( . "$lib" >/dev/null 2>&1; rework_gate "$@" 2>/dev/null )"; rc=$?
  printf '%s|%s' "$rc" "$out"
}
gate_code() { gate_run "$@" | cut -d'|' -f1; }

reader_says() {   # reader_says <lib> <record>
  ( . "$1" >/dev/null 2>&1; degraded_from_record "$2" 2>/dev/null )
}

# ---------------------------------------------------------------------------
# THREE RECORDS FOR ONE PR. Same pr, same verdict, same sha -- the ONLY thing
# that differs is the degraded key, so any difference in outcome is attributable
# to it and to nothing else.
# ---------------------------------------------------------------------------
SHA="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
RECS="$WORK/recs"; mkdir -p "$RECS"
write_rec() {   # write_rec <name> <degraded-json-or-ABSENT>
  local name="$1" deg="$2"
  if [ "$deg" = "ABSENT" ]; then
    cat > "$RECS/$name.json" <<JSON
{"pr":900,"issue":"ASK-900","verdict":"APPROVE","engine":"codex",
 "invoker":"worker","round":1,"head_sha":"$SHA","ts":"2026-07-30T00:00:00Z"}
JSON
  else
    cat > "$RECS/$name.json" <<JSON
{"pr":900,"issue":"ASK-900","verdict":"APPROVE","engine":"codex",
 "reviewed_by":"claude-opus-5","degraded":$deg,
 "invoker":"worker","round":1,"head_sha":"$SHA","ts":"2026-09-22T00:00:00Z"}
JSON
  fi
}
write_rec degraded-true  true
write_rec degraded-false false
write_rec degraded-absent ABSENT

echo "== 0. the reader exists and is three-valued =="
# NEGATIVE SELF-TEST FIRST. Every case below reads the flag through
# degraded_from_record; if that function is missing, the subshell prints nothing,
# the gate gets an empty 5th argument, and EVERY case would agree with today's
# behaviour and report green about a fix that was never made.
if ( . "$LIB" >/dev/null 2>&1; declare -F degraded_from_record >/dev/null ); then
  ok "degraded_from_record is defined in pr-verdict-lib.sh"
else
  bad "THE DEFECT: pr-verdict-lib.sh defines no degraded_from_record -- no production reader of the flag exists"
fi
R_TRUE="$(reader_says "$LIB" "$RECS/degraded-true.json")"
R_FALSE="$(reader_says "$LIB" "$RECS/degraded-false.json")"
R_ABSENT="$(reader_says "$LIB" "$RECS/degraded-absent.json")"
[ "$R_TRUE" = "1" ]  && ok "degraded:true reads as 1"      || bad "degraded:true read as '$R_TRUE', want 1"
[ "$R_FALSE" = "0" ] && ok "degraded:false reads as 0"     || bad "degraded:false read as '$R_FALSE', want 0"
[ -z "$R_ABSENT" ]   && ok "an absent key reads as EMPTY (unknown), not 0" \
                     || bad "an absent key read as '$R_ABSENT', want empty -- a legacy record must not claim independence"
[ -z "$(reader_says "$LIB" "$WORK/no-such-record.json")" ] \
  && ok "a missing record reads as EMPTY, not 0" \
  || bad "a missing record did not read as empty"

echo
echo "== 1. THE DEFECT: an APPROVE on a degraded record is not an approval to merge =="
G_TRUE="$(gate_code "$LIB" "APPROVE" "" "$SHA" "$SHA" "$R_TRUE")"
G_FALSE="$(gate_code "$LIB" "APPROVE" "" "$SHA" "$SHA" "$R_FALSE")"
if [ "$G_TRUE" = "10" ]; then
  bad "THE DEFECT: degraded:true + APPROVE reached the waiting-on-merge branch (exit 10) -- the same branch a real codex approval reaches"
elif [ "$G_TRUE" = "$G_FALSE" ]; then
  # How the failure SHOWS, per the acceptance criterion: both codes, side by side.
  bad "THE DEFECT: the gate cannot tell the two apart -- degraded:true -> $G_TRUE, degraded:false -> $G_FALSE (identical)"
else
  ok "degraded:true -> $G_TRUE, degraded:false -> $G_FALSE: the gate separates them"
fi
[ "$G_FALSE" = "10" ] \
  && ok "degraded:false + APPROVE still reaches waiting-on-merge (exit 10)" \
  || bad "degraded:false + APPROVE returned $G_FALSE, want 10 -- a real codex approval must still be terminal"

echo
echo "== 2. the gate's answer comes from the RECORD, end to end =="
# Case 1 passes the reader's output by hand. This one wires reader -> gate the
# way a caller does, so a reader that works and a gate that ignores it cannot
# both pass.
E2E="$(gate_code "$LIB" "APPROVE" "" "$SHA" "$SHA" "$(reader_says "$LIB" "$RECS/degraded-true.json")")"
[ "$E2E" = "50" ] \
  && ok "record -> degraded_from_record -> rework_gate returns 50 (degraded approval, not independent)" \
  || bad "the end-to-end path returned $E2E, want 50"

echo
echo "== 3. THE MIGRATION FLOOR: an absent key returns exactly what it returns today =="
if [ -z "$PREFIX_LIB" ]; then
  bad "could not read pr-verdict-lib.sh from HEAD, so 'unchanged from today' is UNPROVEN (not skipped: an unrun check reading green is the failure this case guards)"
else
  # Every shape a pre-ASK-445 caller can produce, compared against the pre-fix
  # lib itself. 1-4 args are what converge.sh and linear-worker.sh pass today;
  # the 5th being EMPTY is what a caller reading an absent key passes tomorrow.
  SHA_B="cafebabecafebabecafebabecafebabecafebabe"
  COMPAT_FAIL=0
  compat() {   # compat <label> <args...>
    local label="$1"; shift
    local now old
    old="$(gate_run "$PREFIX_LIB" "$@")"
    now="$(gate_run "$LIB" "$@")"
    if [ "$old" = "$now" ]; then
      echo "    same as today: $label -> $old"
    else
      COMPAT_FAIL=1
      bad "BEHAVIOUR CHANGED for $label: today '$old', after the fix '$now'"
    fi
  }
  compat "APPROVE (1 arg)"                     "APPROVE"
  compat "REQUEST CHANGES (1 arg)"             "REQUEST CHANGES"
  compat "'' (1 arg, unreviewed)"              ""
  compat "APPROVE CLEAN (2 args)"              "APPROVE" "CLEAN"
  compat "APPROVE DIRTY (2 args)"              "APPROVE" "DIRTY"
  compat "APPROVE 4-arg matched sha"           "APPROVE" "CLEAN" "$SHA" "$SHA"
  compat "APPROVE 4-arg drifted sha"           "APPROVE" "CLEAN" "$SHA" "$SHA_B"
  compat "APPROVE 4-arg no reviewed sha"       "APPROVE" "CLEAN" ""     "$SHA_B"
  compat "APPROVE 4-arg unreadable head"       "APPROVE" "CLEAN" "$SHA" ""
  compat "BLOCK 4-arg"                         "BLOCK"   "DIRTY" "$SHA" "$SHA_B"
  [ "$COMPAT_FAIL" = "0" ] \
    && ok "every 1-to-4-argument form returns the pre-fix exit code AND the pre-fix stdout" \
    || true

  # And the absent-key case specifically: the 5th argument is EMPTY, which is
  # what degraded_from_record returns for a legacy record.
  OLD4="$(gate_run "$PREFIX_LIB" "APPROVE" "" "$SHA" "$SHA")"
  NEW5="$(gate_run "$LIB" "APPROVE" "" "$SHA" "$SHA" "$R_ABSENT")"
  [ "$OLD4" = "$NEW5" ] \
    && ok "an absent degraded key is byte-identical to the pre-fix reader ($OLD4) -- no historical record is re-reviewed" \
    || bad "an absent key changed behaviour: today '$OLD4', after the fix '$NEW5'"
fi

echo
echo "== 4. degraded modifies the APPROVING branch and nothing else =="
# A rework verdict is already non-terminal; a degraded reviewer does not make it
# more so, and returning 50 there would hide a real BLOCK behind an outage.
[ "$(gate_code "$LIB" "REQUEST CHANGES" "" "$SHA" "$SHA" "1")" = "0" ] \
  && ok "degraded:true + REQUEST CHANGES still reworks (exit 0)" \
  || bad "degraded:true changed the REQUEST CHANGES path"
[ "$(gate_code "$LIB" "BLOCK" "" "$SHA" "$SHA" "1")" = "0" ] \
  && ok "degraded:true + BLOCK still reworks (exit 0)" \
  || bad "degraded:true changed the BLOCK path"
[ "$(gate_code "$LIB" "" "" "$SHA" "$SHA" "1")" = "20" ] \
  && ok "degraded:true + no verdict is still unreviewed (exit 20)" \
  || bad "degraded:true changed the unreviewed path"
# DRIFT OUTRANKS DEGRADED, for the reason drift already outranks the merge state:
# the code at the head was never read by ANYONE, so the re-review has to happen
# first and the fresh record then decides whether it was independent.
[ "$(gate_code "$LIB" "APPROVE" "CLEAN" "$SHA" "cafebabecafebabecafebabecafebabecafebabe" "1")" = "40" ] \
  && ok "a drifted head still returns 40 even when the record is degraded" \
  || bad "degraded outranked drift -- a re-review of the real head must come first"
# And a degraded approval on a PR that no longer merges is still degraded: 50
# beats 30, because rebasing code nobody independently read does not make it read.
[ "$(gate_code "$LIB" "APPROVE" "DIRTY" "$SHA" "$SHA" "1")" = "50" ] \
  && ok "degraded:true + DIRTY returns 50, not a rebase round on unreviewed code" \
  || bad "a degraded approval on a DIRTY PR did not return 50"

echo
echo "== 5. MUTATION: delete the gate's read of degraded, case 1 must go RED =="
MUT="$(lib_copy "$WORK/mut-gate" "$LIB")"
sed -i.bak '/case "\$degraded" in 1) return 50 ;; esac/d' "$MUT" && rm -f "$MUT.bak"
if diff -q "$LIB" "$MUT" >/dev/null 2>&1 || [ ! -s "$MUT" ]; then
  bad "mutation did not apply (sed matched nothing or emptied the lib); case 1's coverage is UNPROVEN"
elif ! ( . "$MUT" >/dev/null 2>&1; declare -F rework_gate >/dev/null ); then
  bad "mutant lib does not load -- that is a syntax break, not a live mutation test"
else
  ok "mutant differs from the shipped lib and still loads"
  M="$(gate_code "$MUT" "APPROVE" "" "$SHA" "$SHA" "1")"
  [ "$M" = "10" ] \
    && ok "mutant KILLED: without that line a degraded approval is waiting-on-merge again (exit $M)" \
    || bad "THE MUTANT SURVIVED: the gate still returned $M without its degraded read, so case 1 proves nothing"
fi

echo
echo "== 6. MUTATION: point the reader at a key that does not exist =="
# The gate branch and the reader are two decision points. Killing only the gate
# would leave a reader that could silently stop finding the field.
MUT2="$(lib_copy "$WORK/mut-reader" "$LIB")"
python3 - "$MUT2" <<'PY'
import re, sys
p = sys.argv[1]
s = open(p).read()
# Only inside degraded_from_record, so the mutation is attributable to the reader.
i = s.index("degraded_from_record()")
head, tail = s[:i], s[i:]
tail = tail.replace('"degraded"', '"degraded_absent_on_purpose"', 1)
open(p, "w").write(head + tail)
PY
if diff -q "$LIB" "$MUT2" >/dev/null 2>&1; then
  bad "reader mutation did not apply; the reader's coverage is UNPROVEN"
else
  ok "reader mutant differs from the shipped lib"
  M2="$(reader_says "$MUT2" "$RECS/degraded-true.json")"
  M2G="$(gate_code "$MUT2" "APPROVE" "" "$SHA" "$SHA" "$M2")"
  if [ "$M2G" = "10" ] && [ -z "$M2" ]; then
    ok "reader mutant KILLED: the flag is unreadable, the record reads unknown, and the gate falls back to 10"
  else
    bad "THE MUTANT SURVIVED: reader returned '$M2' and the gate returned $M2G; the key name is not load-bearing"
  fi
fi

echo
echo "== 7. the production consumers pass the flag (a reader nobody calls is the defect) =="
# THE WHOLE POINT OF THIS ISSUE. degraded was written, schema'd and documented
# for three weeks while its only reader lived inside a test file. A lib function
# with no caller is exactly that defect again, one layer down, so the wiring is
# asserted here rather than assumed.
for f in converge.sh linear-worker.sh; do
  if grep -q 'degraded_from_record' "$SCRIPTS/$f"; then
    ok "$f reads the flag through degraded_from_record"
  else
    bad "THE DEFECT: $f never calls degraded_from_record -- the reader has no production caller"
  fi
  if grep -qE '(GATE|FINAL_GATE)" = "50"' "$SCRIPTS/$f"; then
    ok "$f handles gate exit 50"
  else
    bad "$f gets exit 50 from the gate and has no branch for it"
  fi
done

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: a degraded approval is a production decision, not a field nobody reads"
