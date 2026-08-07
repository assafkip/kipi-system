#!/usr/bin/env bash
# Ref-hatch runner: section 31 against the pre-fix audit script (ASK-285 round 6).
W=/Users/assafkipnis/.config/kipi/worktrees/ask-285
export BUDGET_AUDIT="$W/.review-scratch/head-audit-285-r6.py"
bash "$W/q-system/.q-system/scripts/test/test-instruction-budget-ratchet.sh" 2>&1 |
  sed -n '/== 31/,$p'
