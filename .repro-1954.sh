#!/usr/bin/env bash
# ASK-1954 reproducer: run the two new classes against the REPO hook source.
set -uo pipefail
cd "$(dirname "$0")"
export KIPI_DESTRUCTIVE_HOOK="$PWD/q-system/.q-system/hooks/destructive-op-deny.sh"
python3 -m pytest test_destructive_op_deny_anchor.py \
  -k "SamePrograms or TransparentPrefix" -q
