#!/usr/bin/env bash
# Reproducer for the round-3 phantom finding on PR #79.
# A crashed codex run echoes the prompt (which contains the literal FINDINGS
# template) and writes nothing else. findings_block takes the LAST COMPLETE
# block to avoid the echo -- but when the echo is the ONLY block, last == echo.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/q-system/.q-system/scripts/pr-verdict-lib.sh"

T="$(mktemp -d)"
F="$T/echo_only.md"
printf '%s\n' \
  'Reading additional input from stdin...' \
  'ERROR codex_core::session: failed to load skill' \
  '- **Last, a machine-readable findings block**, EXACTLY this shape:' \
  'FINDINGS:' \
  'severity|one-sentence claim|file:line' \
  'END FINDINGS' > "$F"

echo "=== findings_block on a prompt-echo-only review ==="
findings_block "$F"
echo "=== has_complete_findings_block ==="
has_complete_findings_block "$F"; echo "rc=$?"
rm -rf "$T"
