#!/usr/bin/env bash
# Throwaway: one mutant per decision point in jev_backlog_rank.py. Every mutant
# must turn test_jev_backlog_rank.py RED. A guard that survives its mutant is
# decoration, so the sweep also asserts the mutation actually landed on disk --
# a mutation target that silently misses reads as "SURVIVED" and lies.
#
# The sweep rewrites a TRACKED file, so the restore is a trap and the stash is a
# mktemp: a fixed /tmp path is shared between concurrent runs (two sweeps restore
# each other's mutant), and without a trap a Ctrl-C or a crash leaves a mutant in
# the working tree that reads as ordinary source.
set -u
S=q-system/.q-system/scripts/jev_backlog_rank.py
T=q-system/.q-system/scripts/test_jev_backlog_rank.py
ORIG=$(mktemp "${TMPDIR:-/tmp}/jbr.orig.XXXXXX")
cp "$S" "$ORIG"
# Idempotent: the explicit call at the end and the EXIT trap both run it.
restore () { [ -f "$ORIG" ] && cp "$ORIG" "$S"; return 0; }
trap restore EXIT INT TERM

mutate () {
  local name="$1"; shift
  cp "$ORIG" "$S"
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
# The WIDTH of the project guard, not only its existence. The correct substring
# matcher was applied as a mutation on 2026-09-28 and the whole suite stayed
# green, which is how a prefix matcher shipped in a guard whose own docstring
# says it errs toward client.
mutate "project guard narrowed from substring to a prefix" \
  'if proj and any(r in proj for r in roots):' \
  'if proj and any(proj.startswith(r) for r in roots):'
mutate "a torn cache row kills every later run instead of being skipped" \
  'torn += 1
            continue' 'torn += 1
            raise'
mutate "the command table promises a restore undo does not perform" \
  '  undo    PRINTS the restore plan for a closed batch. It restores nothing' \
  '  undo    put a closed batch back exactly where it was'
mutate "empty roots file runs unguarded instead of refusing" \
  'if not required:' 'if False:'
mutate "roots restated in the module instead of read from the file" \
  'required = _read_roots_file(ROOTS_FILE)' 'required = ["acme foundry"]'
mutate "guard tokens replace the required list instead of widening it" \
  '_ROOTS = tuple(sorted({r for r in required + _guard_tokens() if r}))' \
  '_ROOTS = tuple(sorted({r for r in _guard_tokens() if r})) or tuple(required)'
mutate "a short root line is dropped in silence instead of refusing" \
  'if len(line) < MIN_ROOT_CHARS:' 'if False:'
mutate "a canceled-type Duplicate enters the answer key" \
  'return st.get("type") == "duplicate" or _norm(st.get("name", "")) == "duplicate"' \
  'return st.get("type") == "duplicate"'
mutate "a vendor error is cached as an answer and never retried" \
  'if _score_of(r["response"]) is not None:' 'if True:'
mutate "the gate skips the minimum-cases floor" \
  'if n_scored < min_cases:' 'if False:'
mutate "the gate skips the vendor-error-rate ceiling" \
  'if rate > max_error_rate:' 'if False:'
mutate "precision reports a short population under the larger k" \
  'if k <= 0 or len(ranked) < k:' 'if k <= 0:'
mutate "close writes Linear before the receipt lands" \
  'flush()
    if apply:' 'if apply:'
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
  'if _is_duplicate(i) or stype not in ("canceled", "completed"):' \
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

restore
echo "--- restored; confirming green ---"
python3 "$T" 2>&1 | tail -3
