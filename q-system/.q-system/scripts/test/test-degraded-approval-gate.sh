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
# claim is "the absent-key case returns what it returns BEFORE this fix", and a
# hand-typed expectation would assert my model of that instead of the thing
# itself -- the restated-value defect the lessons corpus names. If no such
# version can be found (a shallow clone carrying only post-fix commits) the case
# says so and FAILS rather than quietly skipping: an unrun check that reads as
# green is the worse outcome.
#
# NOT `HEAD` (PR #446 review, finding 2 -- minor). `HEAD:` resolved to the pre-fix
# lib only while the fix was uncommitted. The moment it lands, HEAD carries the
# FIXED lib, this case compares the lib against ITSELF, and every shape trivially
# agrees -- so a committed regression in the 1-to-4-argument forms, exactly what
# this migration floor exists to catch, would pass green forever. The baseline is
# a historical artifact, so it is DERIVED from history by the one property that
# defines it: the newest commit of this file whose blob does not yet define
# degraded_from_record. That is better than a pinned sha (nothing to update, and
# it survives a squash merge rewriting the sha) and it is self-verifying: a
# baseline that DOES define the reader is rejected by the same condition that
# selected it, so a self-comparison is structurally impossible here.
LIB_REL="q-system/.q-system/scripts/pr-verdict-lib.sh"
PREFIX_LIB=""; PREFIX_SHA=""
while read -r sha; do
  [ -n "$sha" ] || continue
  git -C "$REPO" show "$sha:$LIB_REL" > "$WORK/prefix-raw.sh" 2>/dev/null || continue
  [ -s "$WORK/prefix-raw.sh" ] || continue
  grep -q 'degraded_from_record()' "$WORK/prefix-raw.sh" && continue
  PREFIX_SHA="$sha"
  PREFIX_LIB="$(lib_copy "$WORK/prefix" "$WORK/prefix-raw.sh")"
  break
done <<EOF
$(git -C "$REPO" rev-list HEAD -- "$LIB_REL" 2>/dev/null | head -40)
EOF

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
  bad "no pre-fix pr-verdict-lib.sh found in the last 40 commits touching it, so 'unchanged from before the fix' is UNPROVEN (not skipped: an unrun check reading green is the failure this case guards)"
else
  ok "baseline is $PREFIX_SHA, a version of the lib that predates degraded_from_record (not HEAD, which now carries the fix)"
  # NEGATIVE SELF-TEST on the baseline itself. If the two libs were the same file
  # every compat() below would agree for free and case 3 would prove nothing.
  if diff -q "$LIB" "$PREFIX_LIB" >/dev/null 2>&1; then
    bad "the baseline is BYTE-IDENTICAL to the shipped lib -- case 3 is comparing the lib against itself and proves nothing"
  else
    ok "the baseline differs from the shipped lib, so the comparison below has something to compare"
  fi
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
echo "== 8. gate 50 DISARMS an arm that already happened (PR #446 finding 1) =="
# WHY THIS CASE EXISTS. Not arming at gate 50 is only half the fix: step 5 arms
# UNCONDITIONALLY 42 lines before it runs the review, so at the moment gate 50
# fires GitHub may already be queued to land the PR -- on a required status the
# degraded fallback posted itself. A branch that prints "not merged" over that is
# a sentence, not a gate.
#
# A FAKE gh, because the real one needs a real PR and a network. The stub also
# LOGS every call, which is how the no-op case proves it never wrote.
GHBIN="$WORK/bin"; mkdir -p "$GHBIN"
GHPROBES="$WORK/gh-probes"   # one answer per line, popped in order
GHMERGERC="$WORK/gh-merge-rc"
GHLOG="$WORK/gh-calls"
cat > "$GHBIN/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALL_LOG"
case "$*" in
  *"pr view"*)
    ans="$(sed -n 1p "$GH_PROBES")"
    sed '1d' "$GH_PROBES" > "$GH_PROBES.rest" && mv "$GH_PROBES.rest" "$GH_PROBES"
    case "$ans" in
      true|false) printf '%s\n' "$ans"; exit 0 ;;
      empty)      printf '\n'; exit 0 ;;
      *)          exit 1 ;;   # gh could not answer at all
    esac ;;
  *"pr merge"*) exit "$(cat "$GH_MERGE_RC")" ;;
esac
exit 0
STUB
chmod +x "$GHBIN/gh"

disarm_says() {   # disarm_says <probe-answers...> -- <merge-rc>
                  # -> "<state>|<was>|<count of gh pr merge calls>"
  : > "$GHPROBES"
  while [ "$1" != "--" ]; do printf '%s\n' "$1" >> "$GHPROBES"; shift; done
  shift
  printf '%s\n' "$1" > "$GHMERGERC"
  : > "$GHLOG"
  (
    export PATH="$GHBIN:$PATH" GH_PROBES="$GHPROBES" GH_MERGE_RC="$GHMERGERC" GH_CALL_LOG="$GHLOG"
    . "$LIB" >/dev/null 2>&1
    automerge_disarm 900 "$WORK" /dev/null
    printf '%s|%s|%s' "$AUTOMERGE_DISARM_STATE" "$AUTOMERGE_DISARM_WAS" \
      "$(grep -c 'pr merge' "$GH_CALL_LOG" 2>/dev/null | tr -d '[:space:]')"
  )
}

if ! ( . "$LIB" >/dev/null 2>&1; declare -F automerge_disarm >/dev/null ); then
  bad "THE DEFECT: pr-verdict-lib.sh defines no automerge_disarm -- gate 50 can only decline to arm, never undo an arm"
else
  ok "automerge_disarm is defined in pr-verdict-lib.sh"
  D="$(disarm_says true false -- 0)"
  [ "$D" = "disarmed|1|1" ] \
    && ok "an ARMED PR is disarmed and reported as having been armed (state|was|merge-calls = $D)" \
    || bad "an armed PR gave '$D', want 'disarmed|1|1'"
  # THE NO-OP. An explicit false is the ONLY answer that skips the write, so a PR
  # sitting at 50 across many scheduled runs does not call gh every time.
  D="$(disarm_says false -- 0)"
  [ "$D" = "disarmed|0|0" ] \
    && ok "an explicitly unarmed PR is a real no-op: gh pr merge never ran (state|was|merge-calls = $D)" \
    || bad "an unarmed PR gave '$D', want 'disarmed|0|0' -- either it wrote anyway or it mis-reported"
  # AN UNREADABLE PROBE STILL WRITES. The bias is the opposite of the arm's: a
  # skipped disarm leaves unreviewed code queued to land.
  D="$(disarm_says cannot-answer false -- 0)"
  [ "$D" = "disarmed|0|1" ] \
    && ok "an unreadable probe still attempts the disarm rather than assuming nothing to do ($D)" \
    || bad "an unreadable probe gave '$D', want 'disarmed|0|1' -- an unknown state must not short-circuit"
  D="$(disarm_says empty false -- 0)"
  [ "$D" = "disarmed|0|1" ] \
    && ok "an EMPTY probe answer (gh exit 0, no output) also attempts the disarm ($D)" \
    || bad "an empty probe gave '$D', want 'disarmed|0|1'"
  # THE DANGEROUS STATE, named: gh refused and the PR is still armed.
  D="$(disarm_says true true -- 1)"
  [ "$D" = "armed|1|1" ] \
    && ok "a refused disarm on a still-armed PR reports armed, which is what a caller pages on ($D)" \
    || bad "a refused disarm gave '$D', want 'armed|1|1'"
  # A refusal whose REASON was "auto-merge is not enabled" is the job already done.
  D="$(disarm_says true false -- 1)"
  [ "$D" = "disarmed|1|1" ] \
    && ok "a refusal re-probed as unarmed reads disarmed, not armed ($D)" \
    || bad "a refusal on an already-unarmed PR gave '$D', want 'disarmed|1|1'"
  D="$(disarm_says true cannot-answer -- 1)"
  [ "$D" = "unknown|1|1" ] \
    && ok "a refusal with an unreadable re-probe is UNKNOWN, never a claim ($D)" \
    || bad "an unreadable re-probe gave '$D', want 'unknown|1|1'"
  [ -z "$( . "$LIB" >/dev/null 2>&1; automerge_disarm "" "$WORK" /dev/null; printf '%s' "$AUTOMERGE_DISARM_STATE" )" ] \
    && ok "an empty PR number disarms NOTHING and returns an empty state" \
    || bad "an empty PR number did not return an empty state -- gh would act on the cwd's branch"
fi

# WIRED, not merely defined. A disarm function nobody calls at gate 50 is the
# same defect this whole issue is about, one layer down.
#
# MATCHES A CALL, NOT THE WORD, and this paragraph is the reason the pattern
# looks over-specified. The first version of both checks below was
# `grep -q 'disarm'` plus an awk proximity test on the same bare word. The
# mutation that DELETES both call lines from linear-worker.sh's gate-50 branches
# left the suite at 38 passed, 0 failed: the wrapper function is still DEFINED in
# that file, and the gate-50 comment blocks explain the disarm in prose, so a word
# match found plenty and the check proved nothing. A grep cannot tell a comment
# from a statement. Both patterns are now anchored to a STATEMENT -- start of
# line, optional indent, the function name, whitespace, its first quoted argument
# -- which a `#` line can never satisfy. A check that cannot go red is decoration.
CALL_RE='^[[:space:]]*(disarm_automerge|automerge_disarm)[[:space:]]+"'
for f in linear-worker.sh converge.sh; do
  if grep -Eq "$CALL_RE" "$SCRIPTS/$f"; then
    ok "$f CALLS a disarm (a statement, not the word in a comment)"
  else
    bad "THE DEFECT: $f branches on gate 50 but never disarms an auto-merge armed before the review"
  fi
done
# And the call has to sit INSIDE the gate-50 branch, not merely somewhere in the
# file. Checked by proximity: a disarm STATEMENT within 20 lines after the branch.
for f in linear-worker.sh converge.sh; do
  if awk '
      /(GATE|FINAL_GATE)" = "50"/ { n = NR }
      n && NR > n && NR <= n + 20 && /^[[:space:]]*(disarm_automerge|automerge_disarm)[[:space:]]+"/ { found = 1 }
      END { exit !found }' "$SCRIPTS/$f"; then
    ok "$f's disarm call sits inside the gate-50 branch"
  else
    bad "THE DEFECT: $f has no disarm STATEMENT within its gate-50 branch -- an arm from step 5 would survive the gate"
  fi
done

echo
echo "== 9. WHAT degraded:false DOES NOT SAY (PR #446 round 3, finding 1) =="
# THE OVERCLAIM, and why it only became a defect in this PR. The reader's
# contract called `0` "a real independent review". That is wider than anything
# the writer records. `DEGRADED=1` is assigned at ONE place in
# pr-review-agent.sh, inside the codex-outage branch, and both engine defaults
# (`KIPI_REVIEW_ENGINE`, `KIPI_REVIEW_PRIMARY_ENGINE`) have read `claude` since
# the founder directive of 2026-09-06 -- which pr-review-agent.sh:38-70 records
# in full, including the accepted cost: "Sana (the PR author) is Claude, so a
# Claude reviewer shares her lab and model family". So on the path the worker
# actually runs, every record says `degraded: false`, and under the old contract
# that sentence certified the review as independent.
#
# Before this PR nothing read the flag and a wrong comment cost nothing. This PR
# made the flag a MERGE AUTHORITY, so the contract had to stop claiming more
# than the writer puts in.
#
# THE ENGINE POSTURE IS NOT THIS ISSUE'S TO CHANGE. Arming gate 50 on the
# scheduled path needs either the two engine defaults flipped (the founder's
# 2026-09-06 call) or the writer marking a claude-primary review non-independent
# -- and ASK-2036's DoR says in its own words: "Not changing what the writer
# records." Captured instead; see the spillover ref in the PR.

# 9a. The contract line for `0` must not claim independence. Anchored to the
# contract line itself, so restoring the old wording is the mutation that turns
# this red -- and a `0` line that says nothing about independence cannot match.
if grep -Eq '^#[[:space:]]+0[[:space:]]+the record says NOT degraded.*independent' "$LIB"; then
  bad "THE DEFECT: degraded_from_record's contract still reads 0 as 'a real independent review' -- the writer only clears the flag for a codex outage, so under a claude-primary fleet that sentence certifies Claude reviewing Claude"
else
  ok "the contract for 0 does not claim independence"
fi
# 9b. ...and it names the narrow thing the writer actually records, rather than
# leaving the caller to infer it. A deleted caveat is a silent return to 9a.
if grep -q 'pr-review-agent.sh:38-70' "$LIB"; then
  ok "the contract points at the engine posture that decides whether 1 is ever written"
else
  bad "THE DEFECT: the reader's contract does not say WHEN the writer sets the flag, so a caller cannot tell a dormant gate from a passing one"
fi

# 9c. THE BOARD FLOOR, green by construction today and that is the point -- it
# pins the blast radius the DoR names. A record shaped like a SCHEDULED review
# (engine claude, a claude reviewer, degraded false) must stay terminal. A change
# that marks every claude review degraded goes red HERE, naming the wedge,
# instead of holding every open PR on the board at once.
cat > "$RECS/scheduled-claude.json" <<JSON
{"pr":900,"issue":"ASK-900","verdict":"APPROVE","engine":"claude",
 "reviewed_by":"claude-opus-5","degraded":false,
 "invoker":"worker","round":1,"head_sha":"$SHA","ts":"2026-09-26T00:00:00Z"}
JSON
G_SCHED="$(gate_code "$LIB" "APPROVE" "" "$SHA" "$SHA" "$(reader_says "$LIB" "$RECS/scheduled-claude.json")")"
[ "$G_SCHED" = "10" ] \
  && ok "a scheduled claude-primary APPROVE stays terminal (exit 10) -- gate 50 does not hold the whole board" \
  || bad "THE DEFECT: the scheduled-path record returned $G_SCHED, want 10 -- every APPROVE the fleet produces today is this shape, so this holds every open PR"

# 9d. The one shape gate 50 DOES own, written the way the fallback writes it:
# the run was asked for codex, an Opus model produced the prose, and the
# disagreement between those two fields is the record of the outage.
cat > "$RECS/codex-outage-fallback.json" <<JSON
{"pr":900,"issue":"ASK-900","verdict":"APPROVE","engine":"codex",
 "reviewed_by":"claude-opus-5","degraded":true,
 "invoker":"worker","round":1,"head_sha":"$SHA","ts":"2026-09-26T00:00:00Z"}
JSON
G_FB="$(gate_code "$LIB" "APPROVE" "" "$SHA" "$SHA" "$(reader_says "$LIB" "$RECS/codex-outage-fallback.json")")"
[ "$G_FB" = "50" ] \
  && ok "the codex-outage fallback shape is the one gate 50 owns (exit 50)" \
  || bad "the fallback-shaped record returned $G_FB, want 50"

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: a degraded approval is a production decision, not a field nobody reads"
