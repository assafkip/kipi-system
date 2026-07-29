#!/usr/bin/env bash
# R2: while the grace budget is live, check_volume returns ("warn", ...) and
# warn() exits 0 immediately -- so checks 4..11 (subagent ceiling, MCP rate
# limit, edit spiral) never run. For the 8 grace calls the run has NO
# circuit breaker except sensitive-file and exact-retry.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
PR_GUARD="$HERE/token-guard.py"
BASE_GUARD="$REPO/q-system/.q-system/token-guard.py"
FIXTURE="$HERE/fx"; mkdir -p "$FIXTURE"
SESSION="repro2-$$"
CACHE="/tmp/claude-guard-$SESSION.json"

seed() { # $1 = grace remaining (0 = base-like state)
python3 - "$CACHE" "$SESSION" "$1" <<'EOF'
import json, sys, time
json.dump({"actor_key": sys.argv[2], "tool_calls_since_user": 50,
  "agent_calls_since_user": 40, "mcp_timestamps": [], "repeat_map": {},
  "consecutive_reads": 0, "warnings_issued": 1, "file_read_counts": {},
  "greps_since_write": 0, "edit_targets": {"/tmp/stuck.py": 9},
  "agents_without_write": 0, "last_write_time": time.time(),
  "calls_since_write": 1, "last_volume_reset": time.time(),
  "gate_grace_remaining": int(sys.argv[3]),
  "gate_grace_gate": "plugin-version-bump" if int(sys.argv[3]) else None,
  "gate_grace_grants": 1 if int(sys.argv[3]) else 0}, open(sys.argv[1], "w"))
EOF
}

fire() { # $1 = guard, $2 = payload json
  ERR="$(printf '%s' "$2" | CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$1" 2>&1 >/dev/null)"
  CODE=$?
}

AGENT_CALL="{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PreToolUse\", \"tool_name\": \"Agent\", \"tool_input\": {\"prompt\": \"go\"}}"
SPIRAL_EDIT="{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PreToolUse\", \"tool_name\": \"Edit\", \"tool_input\": {\"file_path\": \"/tmp/stuck.py\", \"old_string\": \"x\", \"new_string\": \"y\"}}"

echo "AGENT_CEILING=30, cache has agent_calls_since_user=40 (10 over)"
echo "EDIT_FAIL_LIMIT=3, cache has 9 failed edits on /tmp/stuck.py"
echo
for g in 0 8; do
  echo "--- gate_grace_remaining = $g ---"
  seed $g; fire "$PR_GUARD" "$AGENT_CALL"
  echo "  Agent spawn  -> exit=$CODE  :: ${ERR:0:95}"
  seed $g; fire "$PR_GUARD" "$SPIRAL_EDIT"
  echo "  spiral Edit  -> exit=$CODE  :: ${ERR:0:95}"
done
rm -f "$CACHE"
