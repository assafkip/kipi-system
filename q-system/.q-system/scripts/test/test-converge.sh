#!/usr/bin/env bash
# Reproducer + acceptance criteria for the convergence driver (ASK-113).
#
# THE DEFECT IT CLOSES: linear-worker.sh runs exactly one round, so a human had
# to re-dispatch every subsequent round by hand. PR #11 burned four rounds that
# way across one evening. Sana is a robot; the loop should drive itself.
#
# THE RISK IN A DRIVER LIKE THIS is the infinite loop and the false stop, and
# neither shows up in a single happy-path run. So this suite drives the REAL
# converge.sh against a FAKE worker + FAKE gh with scripted verdict sequences.
# Testing against the real worker would cost ~1 hour and real model spend per
# case, which in practice means the loop logic ships untested.
#
# Isolation: KIPI_STATE_DIR, KIPI_CONVERGE_WORKER, KIPI_NOTIFY and PATH all
# point into a mktemp dir. Never runs the real worker, never calls real gh,
# never touches live Linear, never pages Slack.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
CONV="$ROOT/q-system/.q-system/scripts/converge.sh"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$CONV" ] || fail "converge.sh does not exist at $CONV"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/state/pr-reviews"

# --- fake gh: PR number and head sha come from files the fake worker writes ---
cat > "$WORK/bin/gh" <<'EOF'
#!/usr/bin/env bash
# gh pr list --head <branch> --json number -q .[0].number
# gh pr view <n> --json headRefOid -q .headRefOid
case "${1:-} ${2:-}" in
  "pr list") cat "$FAKE_PR_FILE" 2>/dev/null ;;
  "pr view") cat "$FAKE_SHA_FILE" 2>/dev/null ;;
esac
exit 0
EOF
chmod +x "$WORK/bin/gh"

# --- fake worker: emits the Nth scripted verdict, then advances the sha --------
# SEQ is "verdict;sha" per round, pipe-separated. A repeated sha models a rework
# pass that changed no code.
cat > "$WORK/bin/fakeworker" <<'EOF'
#!/usr/bin/env bash
N=$(( $(cat "$FAKE_ROUND_FILE" 2>/dev/null || echo 0) + 1 ))
echo "$N" > "$FAKE_ROUND_FILE"
ENTRY="$(echo "$FAKE_SEQ" | cut -d'|' -f"$N")"
[ -n "$ENTRY" ] || exit 0
V="${ENTRY%%;*}"; S="${ENTRY##*;}"
echo "$S" > "$FAKE_SHA_FILE"
PR="$(cat "$FAKE_PR_FILE")"
[ "$V" = "NONE" ] && exit 0   # review died: no verdict record written
python3 -c "
import json,sys
json.dump({'pr':int(sys.argv[1]),'issue':'ASK-999','verdict':sys.argv[2],
           'review':'x','ts':'t'}, open(sys.argv[3],'w'))
" "$PR" "$V" "$FAKE_STATE/pr-reviews/pr-$PR.verdict.json"
exit 0
EOF
chmod +x "$WORK/bin/fakeworker"

export PATH="$WORK/bin:$PATH"
export KIPI_STATE_DIR="$WORK/state"
export KIPI_CONVERGE_WORKER="$WORK/bin/fakeworker"
export KIPI_NOTIFY="/usr/bin/true"
export FAKE_STATE="$WORK/state"
export FAKE_PR_FILE="$WORK/pr" FAKE_SHA_FILE="$WORK/sha" FAKE_ROUND_FILE="$WORK/round"

# run_case <name> <pr> <seq> <max-rounds> -> sets RC and ROUNDS
run_case() {
  echo "$2" > "$FAKE_PR_FILE"; echo "0" > "$FAKE_ROUND_FILE"; : > "$FAKE_SHA_FILE"
  rm -f "$FAKE_STATE"/pr-reviews/*.verdict.json
  export FAKE_SEQ="$3"
  set +e
  bash "$CONV" --issue ASK-999 --max-rounds "$4" >"$WORK/out" 2>&1
  RC=$?
  set -e
  ROUNDS="$(cat "$FAKE_ROUND_FILE")"
}

# --- exit 1: goal met -------------------------------------------------------
run_case approve-first 101 "APPROVE;sha1" 4
[ "$RC" = "1" ] || fail "clean APPROVE must exit 1 (goal met), got rc=$RC: $(cat "$WORK/out")"
[ "$ROUNDS" = "1" ] || fail "APPROVE on round 1 must not dispatch a second round, ran $ROUNDS"
ok "APPROVE on round 1 -> exit 1, exactly one dispatch"

run_case nits-first 102 "APPROVE WITH NITS;sha1" 4
[ "$RC" = "1" ] || fail "APPROVE WITH NITS must terminate as goal-met, got rc=$RC"
ok "APPROVE WITH NITS -> exit 1 (the severity floor is what makes this reachable)"

# THE headline case: the loop that could never end before the severity floor.
run_case rc-then-nits 103 "REQUEST CHANGES;sha1|APPROVE WITH NITS;sha2" 4
[ "$RC" = "1" ] || fail "RC-then-nits must converge, got rc=$RC: $(cat "$WORK/out")"
[ "$ROUNDS" = "2" ] || fail "must converge in exactly 2 rounds, ran $ROUNDS"
ok "REQUEST CHANGES then APPROVE WITH NITS -> converges in 2 rounds unattended"

# --- exit 2: turn cap -------------------------------------------------------
run_case never-approves 104 "REQUEST CHANGES;s1|REQUEST CHANGES;s2|REQUEST CHANGES;s3|REQUEST CHANGES;s4|REQUEST CHANGES;s5" 3
[ "$RC" = "2" ] || fail "a never-approving reviewer must hit the cap with exit 2, got rc=$RC"
[ "$ROUNDS" = "3" ] || fail "cap of 3 must dispatch exactly 3 rounds, ran $ROUNDS"
ok "never-approves -> exit 2 at the cap, cannot run forever"

# --- exit 5: no progress ----------------------------------------------------
# Same verdict AND the head sha never moved: the rework changed nothing.
run_case stalled 105 "REQUEST CHANGES;same|REQUEST CHANGES;same|REQUEST CHANGES;same" 4
[ "$RC" = "5" ] || fail "same verdict + unchanged sha must exit 5 (no progress), got rc=$RC"
[ "$ROUNDS" = "2" ] || fail "stall must be caught on round 2, not later; ran $ROUNDS"
ok "unchanged code + same verdict -> exit 5 on round 2, stops early"

# The false-stop guard: same verdict but the sha MOVED is real rework, and must
# NOT be treated as a stall. Without the two-part condition this case would stop
# at round 2 and report a stall on a PR that was actively being fixed.
run_case same-verdict-moving 106 "REQUEST CHANGES;a|REQUEST CHANGES;b|APPROVE WITH NITS;c" 4
[ "$RC" = "1" ] || fail "same verdict with a MOVING sha must keep going, got rc=$RC (false stall)"
[ "$ROUNDS" = "3" ] || fail "expected 3 rounds through the moving-sha path, ran $ROUNDS"
ok "same verdict but code changed -> not a stall, converges on round 3"

# --- exit 7: error threshold ------------------------------------------------
echo "" > "$FAKE_PR_FILE"; echo "0" > "$FAKE_ROUND_FILE"
export FAKE_SEQ="REQUEST CHANGES;sha1"
set +e; bash "$CONV" --issue ASK-999 --max-rounds 4 >"$WORK/out" 2>&1; RC=$?; set -e
[ "$RC" = "7" ] || fail "no PR must exit 7, got rc=$RC"
ok "no PR opened -> exit 7, does not loop against nothing"

run_case review-died 107 "NONE;sha1" 4
[ "$RC" = "7" ] || fail "a review that wrote no verdict must exit 7, got rc=$RC"
[ "$ROUNDS" = "1" ] || fail "must stop immediately on a dead review, ran $ROUNDS"
ok "review died (no verdict record) -> exit 7, no blind rework"

# --- dry mode + arg handling -------------------------------------------------
echo "108" > "$FAKE_PR_FILE"; echo "0" > "$FAKE_ROUND_FILE"
set +e; bash "$CONV" --issue ASK-999 --dry >"$WORK/out" 2>&1; RC=$?; set -e
[ "$RC" = "0" ] || fail "--dry must exit 0, got rc=$RC"
[ "$(cat "$FAKE_ROUND_FILE")" = "0" ] || fail "--dry dispatched a real round"
grep -q '\[dry\]' "$WORK/out" || fail "--dry produced no dry-run line"
ok "--dry inspects and dispatches nothing"

set +e; bash "$CONV" --max-rounds 2 >"$WORK/out" 2>&1; RC=$?; set -e
[ "$RC" = "1" ] || fail "missing --issue must be a usage error"
grep -q 'usage:' "$WORK/out" || fail "usage text missing"
ok "missing --issue -> usage error, never guesses an issue"

# --- wiring ------------------------------------------------------------------
grep -q 'pr-verdict-lib.sh' "$CONV" || fail "converge.sh must use the shared verdict lib"
grep -q 'rework_gate'       "$CONV" || fail "converge.sh must gate on rework_gate, not its own regex"
grep -q "converge)" "$ROOT/kipi"    || fail "kipi CLI has no converge subcommand"
bash -n "$CONV"                     || fail "converge.sh does not parse"
ok "wiring: shared gate, registered in the kipi CLI, parses"

echo "PASS: $PASS/$PASS converge checks"
