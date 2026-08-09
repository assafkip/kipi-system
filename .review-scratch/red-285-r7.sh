#!/usr/bin/env bash
# ASK-285 round 7: run the ratchet suite against the pre-fix HEAD copy of the
# audit script, so sections 33/34 are watched failing before the fix lands.
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export BUDGET_AUDIT="$PWD/.review-scratch/head-audit-285-r7.py"
bash q-system/.q-system/scripts/test/test-instruction-budget-ratchet.sh 2>&1 | sed -n '/== 33/,$p'
