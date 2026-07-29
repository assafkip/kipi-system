#!/usr/bin/env bash
# R1: a FAILING Bash command that merely CONTAINS the substring "git commit"
# (no commit attempted, nothing staged) mints the 8-call grace budget and
# permanently hijacks the volume-ceiling block message for the rest of the
# user-message window.
#
# Producer is real: `grep -rn "git commit" <path>` exits 1 when there is no
# match. The response shape (dict with a truthy `error`) is the LIVE shape,
# proven by the control experiment in the review, not an invented fixture.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
PR_GUARD="$HERE/token-guard.py"
BASE_GUARD="$REPO/q-system/.q-system/token-guard.py"
FIXTURE="$HERE/fx"; mkdir -p "$FIXTURE"
SESSION="repro1-$$"
CACHE="/tmp/claude-guard-$SESSION.json"

seed_ceiling() {
python3 - "$CACHE" "$SESSION" <<'EOF'
import json, sys, time
json.dump({"actor_key": sys.argv[2], "tool_calls_since_user": 50,
  "agent_calls_since_user": 0, "mcp_timestamps": [], "repeat_map": {},
  "consecutive_reads": 0, "warnings_issued": 1, "file_read_counts": {},
  "greps_since_write": 0, "edit_targets": {}, "agents_without_write": 0,
  "last_write_time": time.time(), "calls_since_write": 1,
  "last_volume_reset": time.time()}, open(sys.argv[1], "w"))
EOF
}

# The exact payload the runtime delivers for `grep -rn "git commit" ...` with
# zero matches: exit 1, no output, truthy `error`.
python3 - "$FIXTURE" "$SESSION" <<'EOF'
import json, os, sys
fixture, session = sys.argv[1], sys.argv[2]
json.dump({"session_id": session, "hook_event_name": "PostToolUse",
  "tool_name": "Bash",
  "tool_input": {"command": 'grep -rn "git commit" q-system/canonical/'},
  "tool_response": {"stdout": "", "stderr": "", "error": "Exit code 1"}},
  open(os.path.join(fixture, "failing-grep.json"), "w"))
EOF

edit_at_ceiling() { # $1 = distinct probe id
  local p="{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PreToolUse\", \"tool_name\": \"Edit\", \"tool_input\": {\"file_path\": \"/tmp/probe-$1.txt\", \"old_string\": \"a$1\", \"new_string\": \"b$1\"}}"
  ERR="$(printf '%s' "$p" | CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$1GUARDVAR" 2>&1 >/dev/null)"
}

run_edit() { # $1 = guard, $2 = probe id -> CODE, ERR
  local p="{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PreToolUse\", \"tool_name\": \"Edit\", \"tool_input\": {\"file_path\": \"/tmp/probe-$2.txt\", \"old_string\": \"a$2\", \"new_string\": \"b$2\"}}"
  ERR="$(printf '%s' "$p" | CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$1" 2>&1 >/dev/null)"
  CODE=$?
}

echo "=============== BASE (main) ==============="
seed_ceiling
CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$BASE_GUARD" < "$FIXTURE/failing-grep.json" >/dev/null
run_edit "$BASE_GUARD" b1
echo "exit=$CODE"
echo "msg: $ERR"

echo
echo "=============== PR #27 ==============="
seed_ceiling
CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$PR_GUARD" < "$FIXTURE/failing-grep.json" >/dev/null
python3 -c "
import json,sys
c=json.load(open('$CACHE'))
print('gate_grace_remaining =', c.get('gate_grace_remaining'))
print('gate_grace_gate      =', repr(c.get('gate_grace_gate')))
"
i=0
while [ $i -lt 8 ]; do
  i=$(( i + 1 ))
  run_edit "$PR_GUARD" "p$i"
  [ "$CODE" -eq 0 ] || { echo "grace call $i unexpectedly exited $CODE"; }
done
echo "-- 8 grace calls consumed (each one an Edit the ceiling would have blocked on main) --"
run_edit "$PR_GUARD" "p9"
echo "exit=$CODE"
echo "msg: $ERR"
rm -f "$CACHE"
