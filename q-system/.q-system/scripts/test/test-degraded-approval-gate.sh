#!/usr/bin/env bash
# A DEGRADED APPROVAL IS AN APPROVAL (ASK-3832, RULE-2026-11-06-C).
#
# This file used to pin the opposite. ASK-2036 (sp-e9284708) taught rework_gate
# to read `degraded` and return 50 on a fallback APPROVE, and the worker then
# took auto-merge OFF and skipped the issue. Nothing re-ran the review on a
# degraded record, so every such PR sat approved and unmerged: 39 of them
# between 2026-09-16 (codex out of credits) and 2026-10-23. The founder ruled
# the opposite twice -- 2026-09-23 "you dont need codex credits, you can use
# opus as a fallback", and 2026-11-06 RULE-2026-11-06-C "A degraded (Opus)
# approval is an approval: gate 50 is removed."
#
# WHAT STAYS PINNED, and why each still matters:
#   - the reader is three-valued (case 0). converge.sh still reads the flag, and
#     the worker names a degraded approval in its log, so the reader is live.
#   - the 1-to-4-argument forms are byte-identical to the pre-ASK-2036 lib
#     (case 3). Removing a branch must not move any other exit code.
#   - automerge_disarm still behaves (case 8). converge.sh calls it.
#
# WHAT IS NEW: no input reaches 50 (case 5, exhaustive), the worker carries no
# gate-50 branch (case 7), and the real `kipi work` arms a degraded approval
# end to end against a fixture (case 10, the DoR check).
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

# THE PRE-ASK-2036 READER, taken from git rather than reconstructed. Case 3's
# claim is "every 1-to-4-argument form returns what it returned before any of
# the degraded work", and a hand-typed expectation would assert my model of
# that instead of the thing itself. Derived from history by the one property
# that defines it: the newest commit of this file whose blob does not yet
# define degraded_from_record. Not HEAD (PR #446 review, finding 2): HEAD
# carries the shipped lib, and a lib compared against itself agrees for free.
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
# caller sees.
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
SHA_B="cafebabecafebabecafebabecafebabecafebabe"
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
# Still load-bearing after ASK-3832: converge.sh reads the flag, and the worker
# names a degraded approval in its run log. A reader that silently stopped
# finding the key would make that log line lie.
if ( . "$LIB" >/dev/null 2>&1; declare -F degraded_from_record >/dev/null ); then
  ok "degraded_from_record is defined in pr-verdict-lib.sh"
else
  bad "pr-verdict-lib.sh defines no degraded_from_record -- converge.sh calls it"
fi
R_TRUE="$(reader_says "$LIB" "$RECS/degraded-true.json")"
R_FALSE="$(reader_says "$LIB" "$RECS/degraded-false.json")"
R_ABSENT="$(reader_says "$LIB" "$RECS/degraded-absent.json")"
[ "$R_TRUE" = "1" ]  && ok "degraded:true reads as 1"      || bad "degraded:true read as '$R_TRUE', want 1"
[ "$R_FALSE" = "0" ] && ok "degraded:false reads as 0"     || bad "degraded:false read as '$R_FALSE', want 0"
[ -z "$R_ABSENT" ]   && ok "an absent key reads as EMPTY (unknown), not 0" \
                     || bad "an absent key read as '$R_ABSENT', want empty"
[ -z "$(reader_says "$LIB" "$WORK/no-such-record.json")" ] \
  && ok "a missing record reads as EMPTY, not 0" \
  || bad "a missing record did not read as empty"

echo
echo "== 1. THE RULING: a degraded APPROVE is an approval (RULE-2026-11-06-C) =="
G_TRUE="$(gate_code "$LIB" "APPROVE" "" "$SHA" "$SHA" "$R_TRUE")"
G_FALSE="$(gate_code "$LIB" "APPROVE" "" "$SHA" "$SHA" "$R_FALSE")"
[ "$G_TRUE" = "10" ] \
  && ok "degraded:true + APPROVE at its own head reaches the approved branch (exit 10), where the worker arms it" \
  || bad "THE DEFECT: degraded:true + APPROVE returned $G_TRUE, want 10 -- gate 50 still parks a fallback approval"
[ "$G_TRUE" = "$G_FALSE" ] \
  && ok "the gate answers a degraded and a non-degraded approval the same ($G_TRUE)" \
  || bad "THE DEFECT: degraded:true -> $G_TRUE, degraded:false -> $G_FALSE -- the flag still moves the merge decision"

echo
echo "== 2. the gate's answer, from the RECORD, end to end =="
# Case 1 passes the reader's output by hand. This one wires reader -> gate the
# way converge.sh does, so a reader and a gate cannot both pass while disagreeing.
E2E="$(gate_code "$LIB" "APPROVE" "" "$SHA" "$SHA" "$(reader_says "$LIB" "$RECS/degraded-true.json")")"
[ "$E2E" = "10" ] \
  && ok "record -> degraded_from_record -> rework_gate returns 10 (an approval)" \
  || bad "the end-to-end path returned $E2E, want 10"

echo
echo "== 3. THE MIGRATION FLOOR: every 1-to-4-argument form is unchanged =="
if [ -z "$PREFIX_LIB" ]; then
  bad "no pre-ASK-2036 pr-verdict-lib.sh found in the last 40 commits touching it, so 'unchanged' is UNPROVEN (not skipped: an unrun check reading green is the failure this case guards)"
else
  ok "baseline is $PREFIX_SHA, a version of the lib that predates degraded_from_record (not HEAD)"
  # NEGATIVE SELF-TEST on the baseline itself. If the two libs were the same file
  # every compat() below would agree for free and case 3 would prove nothing.
  if diff -q "$LIB" "$PREFIX_LIB" >/dev/null 2>&1; then
    bad "the baseline is BYTE-IDENTICAL to the shipped lib -- case 3 is comparing the lib against itself"
  else
    ok "the baseline differs from the shipped lib, so the comparison below has something to compare"
  fi
  COMPAT_FAIL=0
  compat() {   # compat <label> <args...>
    local label="$1"; shift
    local now old
    old="$(gate_run "$PREFIX_LIB" "$@")"
    now="$(gate_run "$LIB" "$@")"
    if [ "$old" = "$now" ]; then
      echo "    same as before: $label -> $old"
    else
      COMPAT_FAIL=1
      bad "BEHAVIOUR CHANGED for $label: before '$old', now '$now'"
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
    && ok "every 1-to-4-argument form returns the pre-ASK-2036 exit code AND stdout" \
    || true

  # THE 5TH ARGUMENT IS INERT NOW. converge.sh still passes it; whatever it
  # carries, the answer must be the 4-argument answer of the baseline.
  INERT_FAIL=0
  for deg in "" 0 1; do
    for ms in "" CLEAN DIRTY; do
      OLD4="$(gate_run "$PREFIX_LIB" "APPROVE" "$ms" "$SHA" "$SHA")"
      NEW5="$(gate_run "$LIB" "APPROVE" "$ms" "$SHA" "$SHA" "$deg")"
      if [ "$OLD4" != "$NEW5" ]; then
        INERT_FAIL=1
        bad "degraded='$deg' merge='$ms' moved the answer: baseline 4-arg '$OLD4', now 5-arg '$NEW5'"
      fi
    done
  done
  [ "$INERT_FAIL" = "0" ] \
    && ok "the 5th argument (degraded) changes no exit code and no line, for '', 0 and 1" \
    || true
fi

echo
echo "== 4. every other branch is where it was =="
[ "$(gate_code "$LIB" "REQUEST CHANGES" "" "$SHA" "$SHA" "1")" = "0" ] \
  && ok "degraded:true + REQUEST CHANGES still reworks (exit 0)" \
  || bad "degraded:true changed the REQUEST CHANGES path"
[ "$(gate_code "$LIB" "BLOCK" "" "$SHA" "$SHA" "1")" = "0" ] \
  && ok "degraded:true + BLOCK still reworks (exit 0)" \
  || bad "degraded:true changed the BLOCK path"
[ "$(gate_code "$LIB" "" "" "$SHA" "$SHA" "1")" = "20" ] \
  && ok "degraded:true + no verdict is still unreviewed (exit 20)" \
  || bad "degraded:true changed the unreviewed path"
[ "$(gate_code "$LIB" "APPROVE" "CLEAN" "$SHA" "$SHA_B" "1")" = "40" ] \
  && ok "a drifted head still returns 40 when the record is degraded" \
  || bad "a degraded record on a drifted head did not return 40"
# A degraded approval on a PR that no longer merges is a REBASE round, exactly
# like any other approval. Under gate 50 it was parked here too.
[ "$(gate_code "$LIB" "APPROVE" "DIRTY" "$SHA" "$SHA" "1")" = "30" ] \
  && ok "degraded:true + DIRTY returns 30, the rebase round every approval gets" \
  || bad "a degraded approval on a DIRTY PR did not return 30"

echo
echo "== 5. NO INPUT REACHES 50 =="
# converge.sh still carries a `[ "$GATE" = "50" ]` branch (not in this PR's
# files). This sweep is what proves that branch cannot fire: rework_gate is the
# only producer of the code, and no verdict, merge state, sha pair or flag
# value makes it return 50.
# One subshell sources the lib once; 525 sources would cost seconds for nothing.
SWEEP="$( . "$LIB" >/dev/null 2>&1
  declare -F rework_gate >/dev/null || { printf '|0'; exit 0; }
  n=0
  for v in "APPROVE" "APPROVE WITH NITS" "REQUEST CHANGES" "BLOCK" ""; do
    for ms in "" CLEAN DIRTY BEHIND BLOCKED UNSTABLE UNKNOWN; do
      for pair in "$SHA:$SHA" "$SHA:$SHA_B" ":$SHA" "$SHA:" ":"; do
        for deg in "" 0 1; do
          n=$((n+1))
          rework_gate "$v" "$ms" "${pair%%:*}" "${pair#*:}" "$deg" >/dev/null 2>&1
          [ $? = 50 ] && printf ' [%s|%s|%s|%s]' "$v" "$ms" "$pair" "$deg"
        done
      done
    done
  done
  printf '|%s' "$n" )"
N_SWEPT="${SWEEP##*|}"; HIT50="${SWEEP%|*}"
if [ "$N_SWEPT" != "525" ]; then
  bad "the sweep ran $N_SWEPT combinations, want 525 -- the lib did not load, so 'none returned 50' would be vacuous"
elif [ -z "$HIT50" ]; then
  ok "0 of $N_SWEPT input combinations return 50"
else
  bad "THE DEFECT: rework_gate still returns 50 for:$HIT50"
fi

# MUTATION: put the ASK-2036 line back. Case 1 must go RED, or it proves nothing.
MUT="$(lib_copy "$WORK/mut-gate" "$LIB")"
python3 - "$MUT" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
i = s.index("rework_gate() {")
anchor = '      case "$merge_state" in'
j = s.index(anchor, i)
s = s[:j] + '      case "${5:-}" in 1) return 50 ;; esac\n' + s[j:]
open(p, "w").write(s)
PY
if diff -q "$LIB" "$MUT" >/dev/null 2>&1 || [ ! -s "$MUT" ]; then
  bad "mutation did not apply; case 1's coverage is UNPROVEN"
elif ! ( . "$MUT" >/dev/null 2>&1; declare -F rework_gate >/dev/null ); then
  bad "mutant lib does not load -- that is a syntax break, not a live mutation test"
else
  M="$(gate_code "$MUT" "APPROVE" "" "$SHA" "$SHA" "1")"
  [ "$M" = "50" ] \
    && ok "mutant KILLED: with gate 50 put back, a degraded approval returns $M and case 1 would go red" \
    || bad "THE MUTANT SURVIVED: re-adding gate 50 still returned $M, so case 1 cannot tell"
fi

echo
echo "== 6. MUTATION: point the reader at a key that does not exist =="
MUT2="$(lib_copy "$WORK/mut-reader" "$LIB")"
python3 - "$MUT2" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
i = s.index("degraded_from_record()")
head, tail = s[:i], s[i:]
tail = tail.replace('"degraded"', '"degraded_absent_on_purpose"', 1)
open(p, "w").write(head + tail)
PY
if diff -q "$LIB" "$MUT2" >/dev/null 2>&1; then
  bad "reader mutation did not apply; the reader's coverage is UNPROVEN"
else
  M2="$(reader_says "$MUT2" "$RECS/degraded-true.json")"
  [ -z "$M2" ] \
    && ok "reader mutant KILLED: with the key renamed, a degraded record reads unknown, not 1" \
    || bad "THE MUTANT SURVIVED: the reader returned '$M2'; the key name is not load-bearing"
fi

echo
echo "== 7. the worker carries no gate-50 branch and no disarm =="
# The two branches ASK-2036 added (top-of-run gate and closing re-gate) both
# took auto-merge OFF a degraded approval. A leftover one is dead today and a
# live disarm the day anyone re-adds a 50 to the lib.
W="$SCRIPTS/linear-worker.sh"
if grep -qE '(GATE|FINAL_GATE)" = "50"' "$W"; then
  bad "THE DEFECT: linear-worker.sh still branches on gate 50: $(grep -nE '(GATE|FINAL_GATE)" = "50"' "$W" | cut -d: -f1 | tr '\n' ' ')"
else
  ok "linear-worker.sh has no gate-50 branch"
fi
# A STATEMENT, not the word: anchored to start of line so a `#` comment that
# explains the history can never satisfy it (the PR #446 scar on this file).
CALL_RE='^[[:space:]]*(disarm_automerge|automerge_disarm)[[:space:]]+"'
if grep -Eq "$CALL_RE" "$W"; then
  bad "THE DEFECT: linear-worker.sh still CALLS a disarm: $(grep -nE "$CALL_RE" "$W" | cut -d: -f1 | tr '\n' ' ')"
else
  ok "linear-worker.sh calls no disarm"
fi

echo
echo "== 8. automerge_disarm still behaves (converge.sh calls it) =="
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
  bad "pr-verdict-lib.sh defines no automerge_disarm -- converge.sh calls it"
else
  ok "automerge_disarm is defined in pr-verdict-lib.sh"
  D="$(disarm_says true false -- 0)"
  [ "$D" = "disarmed|1|1" ] \
    && ok "an ARMED PR is disarmed and reported as having been armed (state|was|merge-calls = $D)" \
    || bad "an armed PR gave '$D', want 'disarmed|1|1'"
  D="$(disarm_says false -- 0)"
  [ "$D" = "disarmed|0|0" ] \
    && ok "an explicitly unarmed PR is a real no-op: gh pr merge never ran ($D)" \
    || bad "an unarmed PR gave '$D', want 'disarmed|0|0'"
  D="$(disarm_says cannot-answer false -- 0)"
  [ "$D" = "disarmed|0|1" ] \
    && ok "an unreadable probe still attempts the disarm ($D)" \
    || bad "an unreadable probe gave '$D', want 'disarmed|0|1'"
  D="$(disarm_says empty false -- 0)"
  [ "$D" = "disarmed|0|1" ] \
    && ok "an EMPTY probe answer also attempts the disarm ($D)" \
    || bad "an empty probe gave '$D', want 'disarmed|0|1'"
  D="$(disarm_says true true -- 1)"
  [ "$D" = "armed|1|1" ] \
    && ok "a refused disarm on a still-armed PR reports armed ($D)" \
    || bad "a refused disarm gave '$D', want 'armed|1|1'"
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

echo
echo "== 9. WHAT degraded:false DOES NOT SAY (PR #446 round 3, finding 1) =="
# The reader's contract must not call `0` an independent review: the writer
# sets the flag only on the codex-outage branch, and both engine defaults read
# `claude`, so `0` on the scheduled path is Claude reviewing Claude.
if grep -Eq '^#[[:space:]]+0[[:space:]]+the record says NOT degraded.*independent' "$LIB"; then
  bad "degraded_from_record's contract reads 0 as 'a real independent review' -- the writer does not record that"
else
  ok "the contract for 0 does not claim independence"
fi
if grep -q 'pr-review-agent.sh:38-70' "$LIB"; then
  ok "the contract points at the engine posture that decides when 1 is written"
else
  bad "the reader's contract does not say WHEN the writer sets the flag"
fi
cat > "$RECS/scheduled-claude.json" <<JSON
{"pr":900,"issue":"ASK-900","verdict":"APPROVE","engine":"claude",
 "reviewed_by":"claude-opus-5","degraded":false,
 "invoker":"worker","round":1,"head_sha":"$SHA","ts":"2026-09-26T00:00:00Z"}
JSON
G_SCHED="$(gate_code "$LIB" "APPROVE" "" "$SHA" "$SHA" "$(reader_says "$LIB" "$RECS/scheduled-claude.json")")"
[ "$G_SCHED" = "10" ] \
  && ok "a scheduled claude-primary APPROVE is terminal (exit 10)" \
  || bad "the scheduled-path record returned $G_SCHED, want 10"
# The codex-outage fallback shape, written the way the fallback writes it.
# Under ASK-2036 this was the one shape gate 50 owned; under RULE-2026-11-06-C
# it is an approval like the one above.
cat > "$RECS/codex-outage-fallback.json" <<JSON
{"pr":900,"issue":"ASK-900","verdict":"APPROVE","engine":"codex",
 "reviewed_by":"claude-opus-5","degraded":true,
 "invoker":"worker","round":1,"head_sha":"$SHA","ts":"2026-09-26T00:00:00Z"}
JSON
G_FB="$(gate_code "$LIB" "APPROVE" "" "$SHA" "$SHA" "$(reader_says "$LIB" "$RECS/codex-outage-fallback.json")")"
[ "$G_FB" = "10" ] \
  && ok "the codex-outage fallback shape is an approval too (exit 10)" \
  || bad "THE DEFECT: the fallback-shaped record returned $G_FB, want 10"

echo
echo "== 10. kipi work ARMS a degraded approval, end to end (the DoR check) =="
# The cases above prove the lib. This one drives the real entrypoint, `kipi
# work`, against a fixture whose only open PR carries a degraded APPROVE pinned
# to its head, and reads what the worker DID: the run line and the gh calls.
#
# --apply, NOT --dry, AND THAT IS NOT A SHORTCUT. `kipi work` is dry by default
# and rejects a literal `--dry`; its dry branch prints "[dry] would work <id>"
# and continues BEFORE the severity-floor gate, because kipi-dispatch.sh greps
# that line to pick the next issue and the pick must stay cheap. So the arm
# decision is only observable on an --apply run. Every side effect is stubbed:
# gh, python3's Linear calls, the agent, the notifier, HOME and the state dir.
# Gate 10 then arms and `continue`s before any claim, worktree or agent.
REAL_PY="$(command -v python3)"
W2="$WORK/w2"; mkdir -p "$W2/home" "$W2/bin" "$W2/state/pr-reviews"
G() { git -c user.email=t@t.t -c user.name=t "$@"; }
git init -q --bare "$W2/origin" && git -C "$W2/origin" symbolic-ref HEAD refs/heads/main
git init -q "$W2/skel"
G -C "$W2/skel" commit -q --allow-empty -m c1
git -C "$W2/skel" branch -M main
git -C "$W2/skel" remote add origin "$W2/origin"
git -C "$W2/skel" push -q -u origin main

# The python3 stub fakes exactly the Linear picker and linear-sync.py, keyed on
# the heredoc's CONTENT, the same discrimination test-severity-floor.sh uses.
cat > "$W2/bin/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  SRC="\$(mktemp)"; cat > "\$SRC"
      if grep -q 'linear-sync.py' "\$SRC"; then
        rm -f "\$SRC"
        printf '{"ready":[{"id":"ASK-AAA","title":"t","project":"p"}],"total_open":1}\n'
        exit 0
      fi
      shift
      "$REAL_PY" "\$SRC" "\$@"; RC=\$?
      rm -f "\$SRC"; exit \$RC ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
cat > "$W2/bin/claude" <<EOF
#!/usr/bin/env bash
echo "worked" >> "$W2/worked.txt"
exit 0
EOF
cat > "$W2/notify.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$W2/pages.txt"
EOF
# gh: PR 901 is open on sana/ask-aaa, CLEAN, its head is \$SHA, and its arm
# state flips to true only once something has called `pr merge --auto`.
cat > "$W2/bin/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$W2/gh-calls"
case "\$*" in
  "pr list"*)                             echo 901 ;;
  "pr view 901 --json mergeStateStatus"*) echo CLEAN ;;
  "pr view 901 --json headRefOid"*)       echo $SHA ;;
  "pr view 901 --json autoMergeRequest"*)
    if grep -q -- 'pr merge --auto' "$W2/gh-calls"; then echo true; else echo false; fi ;;
esac
exit 0
EOF
chmod +x "$W2/bin/python3" "$W2/bin/claude" "$W2/bin/gh" "$W2/notify.sh"
# The record the codex-outage fallback writes: asked for codex, Opus answered.
cat > "$W2/state/pr-reviews/pr-901.verdict.json" <<JSON
{"pr":901,"issue":"ASK-AAA","verdict":"APPROVE","engine":"codex",
 "reviewed_by":"claude-opus-5","degraded":true,
 "invoker":"worker","round":1,"head_sha":"$SHA","ts":"2026-10-23T00:00:00Z"}
JSON
: > "$W2/gh-calls"; : > "$W2/worked.txt"; : > "$W2/pages.txt"
( cd "$W2/skel" \
  && env -u KIPI_LINEAR_CLAIMS -u KIPI_SESSION_ID -u CLAUDE_SESSION_ID -u KIPI_TARGET_REPO \
       -u KIPI_USAGE_BREAKER_CMD -u KIPI_PR_REVIEWER \
       PATH="$W2/bin:$PATH" HOME="$W2/home" KIPI_SKEL="$W2/skel" KIPI_STATE_DIR="$W2/state" \
       KIPI_NOTIFY="$W2/notify.sh" \
       bash "$REPO/kipi" work --apply --issue ASK-AAA --limit 1 ) > "$W2/run.out" 2>&1
echo "    kipi work said: $(grep -E 'ASK-AAA' "$W2/run.out" | grep -E 'skip|arm|DEGRADED|degraded' | head -3 | tr '\n' ' ')"

grep -q "nothing to rework" "$W2/run.out" \
  && ok "the run reached the approved branch (gate 10), not unreviewed (20) or a rework round" \
  || bad "the run did not reach gate 10. It said: $(grep -i 'skip' "$W2/run.out" | head -2 | tr '\n' ' ')"
grep -q "auto-merge is armed" "$W2/run.out" \
  && ok "the worker's action on a degraded approval is ARM" \
  || bad "THE DEFECT: the worker did not arm the degraded approval. It said: $(grep -i 'ASK-AAA' "$W2/run.out" | head -3 | tr '\n' ' ')"
grep -q -- "pr merge --auto --squash 901" "$W2/gh-calls" \
  && ok "gh was asked to arm PR 901 (pr merge --auto --squash 901)" \
  || bad "gh was never asked to arm PR 901. gh calls: $(tr '\n' ';' < "$W2/gh-calls")"
grep -q -- "--disable-auto" "$W2/gh-calls" \
  && bad "THE DEFECT: the worker took auto-merge OFF a degraded approval" \
  || ok "the worker never called --disable-auto"
grep -q "RULE-2026-11-06-C" "$W2/run.out" \
  && ok "the run log names the degraded review and the ruling it was armed under" \
  || bad "the run log does not say this approval came from the degraded fallback"
[ ! -s "$W2/worked.txt" ] \
  && ok "no agent was dispatched (an approval is a skip, not a round)" \
  || bad "an agent ran on an approved PR"
[ ! -s "$W2/pages.txt" ] \
  && ok "nobody was paged" \
  || bad "the run paged: $(cat "$W2/pages.txt")"

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: a degraded approval is an approval, and kipi work arms it"
