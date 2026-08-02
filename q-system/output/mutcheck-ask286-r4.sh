#!/usr/bin/env bash
# Mutation check for the ASK-286 codex-round-4 fix. Cases 7-9 of
# test-claim-page-once-routing.sh only prove the fix is PRESENT; these prove they
# would FAIL if it were removed. Both guards are inside page_once's failure arm,
# which the happy-path cases never reach, so without this an implementation with
# neither guard could ship green.
#
# Mutates a COPY of linear-worker.sh -- never the tracked file.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKER="$REPO/q-system/.q-system/scripts/linear-worker.sh"
LEDGER_PY="$REPO/q-system/.q-system/scripts/attempts-ledger.py"
W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
SURVIVORS=0

# Run the three round-4 observations against a given (possibly mutated) worker.
# Echoes "contend=N broken=N alerts=N".
observe() {
  local worker="$1" dir; dir="$(mktemp -d)"
  (
    set -uo pipefail
    LEDGER="$LEDGER_PY"; ATTEMPTS="$dir/attempts.json"
    NOTIFY="$dir/notify.sh"
    printf '#!/usr/bin/env bash\necho "$*" >> "%s"\n' "$dir/slack.log" > "$NOTIFY"
    chmod +x "$NOTIFY"; : > "$dir/slack.log"; : > "$dir/perm.log"
    say() { :; }
    LEDGER_FAULT_ALERTED=0
    eval "$(awk '/^claim_page_once\(\)/{print; exit}' "$worker")"
    eval "$(sed -n '/^ledger_fault() {/,/^}/p' "$worker")"
    eval "$(sed -n '/^page_once() {/,/^}/p' "$worker")"
    attempt_page() { page_once "$1" stuck_paged 2>/dev/null && echo "$1" >> "$dir/perm.log"; }
    new_run() { LEDGER_FAULT_ALERTED=0; }

    # A. contended cycle, then a claiming cycle. One real state.
    echo '{}' > "$ATTEMPTS"; rm -f "$ATTEMPTS.lock"
    python3 - "$ATTEMPTS.lock" <<'PY' &
import fcntl, sys, time
fh = open(sys.argv[1], "a"); fcntl.flock(fh.fileno(), fcntl.LOCK_EX); time.sleep(60)
PY
    H=$!; sleep 1
    new_run; KIPI_ATTEMPTS_LOCK_TRIES=2 attempt_page ASK-CONTEND
    kill "$H" 2>/dev/null; wait "$H" 2>/dev/null
    new_run; attempt_page ASK-CONTEND
    C="$(grep -c ASK-CONTEND "$dir/perm.log" || true)"

    # B. unwritable ledger, five separate runs.
    : > "$dir/perm.log"; : > "$dir/slack.log"
    for _ in 1 2 3 4 5; do new_run; LEDGER="$dir/nope.py" attempt_page ASK-BROKEN; done
    B="$(grep -c ASK-BROKEN "$dir/perm.log" || true)"

    # C. one run, four queued issues, one broken ledger.
    : > "$dir/slack.log"; new_run
    for i in Q1 Q2 Q3 Q4; do LEDGER="$dir/nope.py" attempt_page "$i"; done
    A="$(wc -l < "$dir/slack.log" | tr -d ' ')"
    echo "contend=$C broken=$B alerts=$A"
  )
  rm -rf "$dir"
}

check() {
  local name="$1" got="$2" want="contend=1 broken=0 alerts=1"
  if [ "$got" = "$want" ]; then
    echo "  SURVIVED  $name -> $got"; SURVIVORS=$((SURVIVORS + 1))
  else
    echo "  KILLED    $name -> $got (baseline: $want)"
  fi
}

echo "BASELINE (unmutated): $(observe "$WORKER")"
echo

# MUTANT 1: the failure arm returns 0 again -- the round-4 major itself. The
# caller then writes its permanent Linear comment off a ledger that recorded
# nothing.
sed 's/^       return 1 ;;$/       return 0 ;;/' "$WORKER" > "$W/m1.sh"
cmp -s "$WORKER" "$W/m1.sh" && { echo "MUTANT 1 did not apply -- re-point this harness"; exit 1; }
check "fault arm returns 0 (page anyway)" "$(observe "$W/m1.sh")"

# MUTANT 2: the once-per-run guard removed, so a broken ledger alerts once per
# QUEUED ISSUE -- cry-wolf re-created inside the channel the notice moved into.
grep -v '^  \[ "\$LEDGER_FAULT_ALERTED" -eq 0 \] || return 0$' "$WORKER" > "$W/m2.sh"
cmp -s "$WORKER" "$W/m2.sh" && { echo "MUTANT 2 did not apply -- re-point this harness"; exit 1; }
check "once-per-run guard removed" "$(observe "$W/m2.sh")"

echo
[ "$SURVIVORS" -eq 0 ] && echo "ALL MUTANTS KILLED" || { echo "$SURVIVORS MUTANT(S) SURVIVED"; exit 1; }
