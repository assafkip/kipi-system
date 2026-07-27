#!/usr/bin/env bash
# Does a REBASE round also spend a REVIEW round?
# linear-worker.sh:73-77 claims: "A PR that has converged on CONTENT must also
# not lose its review budget to rebase tries."
# linear-worker.sh:555-560 bumps `rounds` unconditionally whenever a PR exists.
set -uo pipefail
W="$(ls -d /Users/assafkipnis/projects/kipi-system/.pr25rev/reset-* | head -1)"
echo "ledger after ONE gate-30 rebase round:"
python3 -m json.tool "$W/state/linear-worker-attempts.json" | sed 's/^/    /'
echo "the review the rebase round also triggered:"
grep -iE "^.*review PR|converged|no verdict recorded" "$W/run.out" | sed 's/^/    /'
