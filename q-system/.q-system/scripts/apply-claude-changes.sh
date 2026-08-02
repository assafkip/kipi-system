#!/usr/bin/env bash
# apply-claude-changes: land an agent-authored proposal inside .claude/ safely.
#
# The founder types one command and reads ONE line. There is no diff to review
# and no confirmation prompt -- an earlier design had both and was rejected:
# "that isn't sustainable for an autonomous system to send me a diff to review."
# All safety is mechanical and lives in the engine beside this file.
#
# Exit codes: 0 applied (or already applied), 2 refused, 3 applied-then-reverted.
#
# Deliberately thin. `readlink -f` is GNU-only (macOS ships the BSD one, which
# has no -f), so the directory is resolved with cd/pwd instead.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ENGINE="$SCRIPT_DIR/apply_claude_changes.py"

if [ ! -f "$ENGINE" ]; then
  echo "REFUSED: engine missing at $ENGINE" >&2
  exit 2
fi

# Never let a founder-run apply fire founder notifications at itself.
export KIPI_NOTIFY=/usr/bin/true

exec python3 "$ENGINE" "$@"
