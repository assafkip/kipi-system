#!/usr/bin/env bash
# ASK-1954 reproducer: run the two new classes against the REPO hook source.
set -uo pipefail
cd "$(dirname "$0")"
export KIPI_DESTRUCTIVE_HOOK="$PWD/q-system/.q-system/hooks/destructive-op-deny.sh"
SELECT="${1:-SamePrograms or TransparentPrefix}"
if [ "$SELECT" = "all" ]; then
  python3 -m pytest test_destructive_op_deny_anchor.py -q
else
  python3 -m pytest test_destructive_op_deny_anchor.py -k "$SELECT" -q
fi
