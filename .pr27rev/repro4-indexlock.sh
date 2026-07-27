#!/usr/bin/env bash
# R4: the concurrency case. This repo runs a 15-minute auto-committer
# (AUTO_COMMIT_SUBJECT = "chore: update project files", see git log fbc9404) and
# the fleet runs parallel sessions against one checkout. When a session's
# `git commit` races another git process it fails with index.lock -- which is
# not in NON_GATE_COMMIT_FAILURES, so PR #27 reads it as a gate refusal.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PR_GUARD="$HERE/token-guard.py"
FIXTURE="$HERE/fx"; mkdir -p "$FIXTURE"
SESSION="repro4-$$"
CACHE="/tmp/claude-guard-$SESSION.json"

python3 - "$CACHE" "$SESSION" <<'EOF'
import json, sys, time
json.dump({"actor_key": sys.argv[2], "tool_calls_since_user": 50,
  "agent_calls_since_user": 0, "mcp_timestamps": [], "repeat_map": {},
  "consecutive_reads": 0, "warnings_issued": 1, "file_read_counts": {},
  "greps_since_write": 0, "edit_targets": {}, "agents_without_write": 0,
  "last_write_time": time.time(), "calls_since_write": 1,
  "last_volume_reset": time.time()}, open(sys.argv[1], "w"))
EOF

# Real git text for a lock collision.
python3 - "$FIXTURE" "$SESSION" <<'EOF'
import json, os, sys
fx, s = sys.argv[1], sys.argv[2]
err = ("fatal: Unable to create '/Users/x/projects/kipi-system/.git/index.lock': "
       "File exists.\n\nAnother git process seems to be running in this repository, "
       "e.g.\nan editor opened by 'git commit'. Please make sure all processes\n"
       "are terminated then try again.\n")
json.dump({"session_id": s, "hook_event_name": "PostToolUse", "tool_name": "Bash",
  "tool_input": {"command": "git commit -m 'wip (ASK-215)'"},
  "tool_response": {"stdout": "", "stderr": err, "error": "Exit code 128"}},
  open(os.path.join(fx, "lock.json"), "w"))
EOF

CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$PR_GUARD" < "$FIXTURE/lock.json" >/dev/null
python3 -c "
import json; c=json.load(open('$CACHE'))
print('gate_grace_remaining =', c.get('gate_grace_remaining'))
print('gate_grace_gate      =', repr(c.get('gate_grace_gate')))"

for i in 1 2 3 4 5 6 7 8 9; do
  P="{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PreToolUse\", \"tool_name\": \"Edit\", \"tool_input\": {\"file_path\": \"/tmp/l-$i.txt\", \"old_string\": \"a$i\", \"new_string\": \"b$i\"}}"
  ERR="$(printf '%s' "$P" | CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$PR_GUARD" 2>&1 >/dev/null)"; CODE=$?
done
echo "9th call exit=$CODE"
echo "operator sees: $ERR"
rm -f "$CACHE"
