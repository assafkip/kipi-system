#!/usr/bin/env bash
if [ "${1:-}" = "delegate" ]; then
  echo "ASK-221: delegated to Codex (u-codex)"; exit 0
fi
exec python3 "$(dirname "$0")/../q-system/.q-system/scripts/linear-sync.py" "$@"
