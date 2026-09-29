#!/usr/bin/env bash
# The brake is WIRED into linear-worker.sh, not merely written (ASK-2010, Step 4).
#
# Why this exists as a separate test from test_usage_breaker.py: that one proves
# the breaker DECIDES correctly against a real week of ledger rows. It cannot see
# whether anything calls it. The scar this repo keeps re-learning is a correct
# engine nobody loads (wiring-check.md, "text-in-a-file is NOT wired"), so this
# drives the worker itself and reads its exit code.
#
# The breaker is injected as a stub on purpose. Asserting the real decision here
# would make this test depend on the machine's live ledger, which is the live
# data path fable-discipline forbids a test to touch, and the decision already
# has its own test against a frozen copy of that ledger.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKER="$SCRIPT_DIR/../linear-worker.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

ok()   { PASS=$((PASS+1)); echo "  ok   $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL $1"; }

make_stub() {  # $1 = exit code
  local p="$TMP/breaker-$1.sh"
  printf '#!/usr/bin/env bash\necho "stub breaker rc=%s $*"\nexit %s\n' "$1" "$1" > "$p"
  chmod +x "$p"
  echo "bash $p"
}

# macOS ships no `timeout`, and a `|| true` around a missing binary is a silent
# no-op -- so the bound is hand-rolled: background, poll, kill (portability-lint).
run_bounded() {  # $1 = seconds, rest = command; stdout+stderr -> $TMP/last-out.txt
  local secs="$1"; shift
  ( "$@" >"$TMP/last-out.txt" 2>&1 ) &
  local pid=$! waited=0
  while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt "$secs" ]; do
    sleep 1; waited=$((waited+1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    echo 124; return
  fi
  wait "$pid"; echo $?
}

run_worker() {  # $1 = breaker COMMAND, $2 = state dir, $3 = script (default: the worker)
  # KIPI_NOTIFY is /usr/bin/true on purpose: this drives the REAL worker, whose
  # failure paths page. Scar 2026-08-01, a green suite paged the founder twice.
  KIPI_STATE_DIR="${2:-$TMP/state}" \
  KIPI_USAGE_BREAKER_CMD="$1" \
  KIPI_USAGE_BREAKER_BOT="worker-test" \
  KIPI_NOTIFY=/usr/bin/true \
  run_bounded 60 bash "${3:-$WORKER}"
}

mkdir -p "$TMP/state"

# 1. paused: the worker stops, with the DoR's exit code, before any work.
rc="$(run_worker "$(make_stub 3)")"
[ "$rc" = "3" ] && ok "a paused breaker exits the worker 3" \
                || bad "a paused breaker should exit 3, got $rc"
grep -q "PAUSED: usage breaker" "$TMP/last-out.txt" \
  && ok "the pause is announced, not silent" \
  || bad "no PAUSED line in the worker's output"
cp "$TMP/last-out.txt" "$TMP/paused-out.txt"

# The brake must come BEFORE the expensive setup: a run that already fetched has
# paid for the work it was about to refuse. Asserted on the SOURCE, by line
# number, because the runtime tell is not reliable -- an unbraked run here exits
# 9 and prints its INFRA line into $LOG, not onto the stream this test captures,
# so an "output holds no INFRA" check passes whatever the ordering is. That
# version was written, measured against a real unbraked run, and thrown away:
# a check that cannot go red is decoration (a-check-must-be-able-to-fail).
brake_line="$(grep -n "THE BRAKE (ASK-2010" "$WORKER" | head -1 | cut -d: -f1)"
fetch_line="$(grep -n "FETCH ONCE, BEFORE ANY WORKTREE EXISTS" "$WORKER" | head -1 | cut -d: -f1)"
if [ -n "$brake_line" ] && [ -n "$fetch_line" ] && [ "$brake_line" -lt "$fetch_line" ]; then
  ok "the brake block ($brake_line) precedes the fetch ($fetch_line)"
else
  bad "brake at '${brake_line:-none}', fetch at '${fetch_line:-none}': not ordered"
fi

# 2. running: the worker is NOT stopped by the brake. It may still exit nonzero
#    for its own reasons (no queue, a dead environment); what it may not do is
#    exit 3 or print the pause line.
rc="$(run_worker "$(make_stub 0)")"
[ "$rc" = "3" ] && bad "a passing breaker must not pause the worker (rc=3)" \
                || ok "a passing breaker lets the worker through (rc=$rc)"
grep -q "PAUSED: usage breaker" "$TMP/last-out.txt" \
  && bad "the worker announced a pause the breaker never ordered" \
  || ok "no pause announced when the breaker says run"
cmp -s "$TMP/paused-out.txt" "$TMP/last-out.txt" \
  && bad "braked and unbraked runs produced identical output" \
  || ok "the braked run stopped somewhere the unbraked run did not"

# 3. MUTATION: the brake removed entirely. If this still reports a pause, the
#    assertions above are reading something other than the wiring.
MUT="$TMP/worker-no-brake.sh"
# fable-discipline-lint-skip -- this python READS $WORKER as text to build the
# mutant; it never executes it, so there is no outbound channel here to stub.
# Every line that actually RUNS the worker goes through run_worker, which pins
# KIPI_NOTIFY=/usr/bin/true.
python3 - "$WORKER" "$MUT" <<'PY'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
start = src.index("# --- THE BRAKE (ASK-2010")
end = src.index("# --- WHICH REPO THIS RUN WORKS IN", start)
open(sys.argv[2], "w", encoding="utf-8").write(src[:start] + src[end:])
PY
mkdir -p "$TMP/state2"
mrc="$(run_worker "$(make_stub 3)" "$TMP/state2" "$MUT")"
[ "$mrc" = "3" ] && bad "MUTANT SURVIVED: worker still exits 3 with the brake cut out" \
                 || ok "mutant killed: without the brake block the worker does not pause (rc=$mrc)"
grep -q "PAUSED: usage breaker" "$TMP/last-out.txt" \
  && bad "MUTANT SURVIVED: pause line printed with the brake cut out" \
  || ok "mutant killed: no pause line without the brake block"

# 4. a missing breaker engine runs unbraked and SAYS SO. No injected command
#    here on purpose: this is the production path with the engine absent, so
#    KIPI_SKEL points at an empty tree and the worker falls back to its default.
mkdir -p "$TMP/empty-skel" "$TMP/state4"
rc="$(KIPI_STATE_DIR="$TMP/state4" KIPI_SKEL="$TMP/empty-skel" \
      KIPI_USAGE_BREAKER_BOT="worker-test" KIPI_NOTIFY=/usr/bin/true \
      run_bounded 60 bash "$WORKER")"
[ "$rc" = "3" ] && bad "a missing breaker must not pause the worker" \
                || ok "a missing breaker does not pause the worker"
grep -q "running unbraked" "$TMP/last-out.txt" \
  && ok "a missing breaker is announced, not silent" \
  || bad "a missing breaker was silent"

# 5. ASK-2010: a DRY run asks the brake without spending its one trial run.
#    kipi-dispatch.sh runs `kipi work` with no --apply to pick the next issue,
#    and the converge it launches does the real --apply round minutes later.
#    Both pass through here, so the pick consumed the 24h trial and the round
#    that was going to spend was held for another day (claude review of PR #472,
#    minor). Both cases use a PAUSING stub so the worker stops at the brake and
#    does no real work -- an --apply run past an open brake would fetch, claim
#    and dispatch a model.
argstub() {  # $1 = exit code, $2 = file to record argv into
  local p="$TMP/argstub-$1.sh"
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "%s"\nexit %s\n' "$2" "$1" > "$p"
  chmod +x "$p"
  echo "bash $p"
}
mkdir -p "$TMP/state5"
: > "$TMP/argv-dry.txt"
run_worker "$(argstub 3 "$TMP/argv-dry.txt")" "$TMP/state5" >/dev/null
grep -q -- '--dry' "$TMP/argv-dry.txt" \
  && ok "a dry worker run asks the brake with --dry, so the trial is not spent on a pick" \
  || bad "THE DEFECT: a dry run asked the brake as if it were about to spend: $(cat "$TMP/argv-dry.txt")"

mkdir -p "$TMP/state5b"
: > "$TMP/argv-apply.txt"
run_worker_apply() {
  KIPI_STATE_DIR="$2" KIPI_USAGE_BREAKER_CMD="$1" KIPI_USAGE_BREAKER_BOT="worker-test" \
  KIPI_NOTIFY=/usr/bin/true run_bounded 60 bash "$WORKER" --apply --limit 1 --issue ASK-BRAKE-TEST
}
arc="$(run_worker_apply "$(argstub 3 "$TMP/argv-apply.txt")" "$TMP/state5b")"
[ "$arc" = "3" ] || bad "the --apply probe must stop at the brake (rc=3), got $arc -- it may have done real work"
grep -q -- '--dry' "$TMP/argv-apply.txt" \
  && bad "THE DEFECT: the round that actually spends asked with --dry, so its trial is never granted" \
  || ok "an --apply run asks the brake for real, so the trial is spent by the round that uses it"
grep -q -- '--bot worker-test' "$TMP/argv-apply.txt" \
  && ok "the brake is asked about the bot the worker names" \
  || bad "the brake was not asked about --bot worker-test: $(cat "$TMP/argv-apply.txt")"

echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
