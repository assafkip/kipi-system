#!/usr/bin/env bash
# Throwaway: one mutant per decision point in jev_backlog_rank.py. Every mutant
# must turn test_jev_backlog_rank.py RED. A guard that survives its mutant is
# decoration, so the sweep also asserts the mutation actually landed on disk --
# a mutation target that silently misses reads as "SURVIVED" and lies.
set -u
S=q-system/.q-system/scripts/jev_backlog_rank.py
T=q-system/.q-system/scripts/test_jev_backlog_rank.py
cp "$S" /tmp/jbr.orig

mutate () {
  local name="$1"; shift
  cp /tmp/jbr.orig "$S"
  if ! python3 q-system/.q-system/scripts/test/apply-mutant.py "$S" "$@"; then
    echo "BROKEN TARGET: $name"; return
  fi
  if python3 "$T" >/tmp/mut.out 2>&1; then
    echo "SURVIVED (BAD): $name"
  else
    echo "killed: $name  -- $(grep -cE '^(FAIL|ERROR):' /tmp/mut.out) failing test(s)"
  fi
}

mutate "client text guard removed" \
  'return any(r in text for r in roots)' 'return False'
mutate "empty roots file runs unguarded instead of refusing" \
  'if not required:' 'if False:'
mutate "roots restated in the module instead of read from the file" \
  'required = _read_roots_file(ROOTS_FILE)' 'required = ["acme foundry"]'
mutate "guard tokens replace the required list instead of widening it" \
  '_ROOTS = tuple(sorted({r for r in required + _guard_tokens() if r}))' \
  '_ROOTS = tuple(sorted({r for r in _guard_tokens() if r})) or tuple(required)'
mutate "a short root line is kept instead of dropped" \
  'if len(line) > 2:' 'if line:'
mutate "auc ties scored zero" \
  '1.0 if p > n else 0.5 if p == n else 0.0' '1.0 if p > n else 0.0'
mutate "gate margin dropped to zero" \
  'MIN_MARGIN = 0.05' 'MIN_MARGIN = 0.0'
mutate "gate accepts a tie" \
  'if jev_auc > bar:' 'if jev_auc >= bar:'
mutate "gate bar forgets the coin-flip floor" \
  'bar = max(control_auc if control_auc is not None else 0.0, 0.5) + margin' \
  'bar = (control_auc if control_auc is not None else 0.0) + margin'
mutate "minority recall never computed" \
  '"minority_recall": rec,' '"minority_recall": None,'
mutate "recall dropped from the printed header" \
  'precision | minority recall ' 'precision | confidence '
mutate "duplicates enter the answer key" \
  'if stype not in ("canceled", "completed"):' \
  'if stype not in ("canceled", "completed", "duplicate"):'
mutate "45-day window ignored" \
  'if not tat or tat < cut:' 'if False:'
mutate "sana ruling no longer outranks the state" \
  'if ident in ruling:' 'if False:'
mutate "verified check removed from close" \
  'if not batch.get("verified"):' 'if False:'
mutate "client check removed from close" \
  'raise ClientTicket' 'print'
mutate "undo forgets the prior state" \
  '"prior_state_id": it["state_id"],' '"prior_state_id": "backlog",'

cp /tmp/jbr.orig "$S"
echo "--- restored; confirming green ---"
python3 "$T" 2>&1 | tail -3
