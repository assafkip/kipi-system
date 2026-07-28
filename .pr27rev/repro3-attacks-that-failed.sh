#!/usr/bin/env bash
# Attacks on PR #27 that the code SURVIVED. Recorded so the review is calibrated.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PR_GUARD="$HERE/token-guard.py"
FIXTURE="$HERE/fx"; mkdir -p "$FIXTURE"
SESSION="repro3-$$"
CACHE="/tmp/claude-guard-$SESSION.json"

seed() {
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
post() { CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$PR_GUARD" < "$1" >/dev/null; }
edit() {
  local p="{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PreToolUse\", \"tool_name\": \"Edit\", \"tool_input\": {\"file_path\": \"/tmp/e-$1.txt\", \"old_string\": \"a$1\", \"new_string\": \"b$1\"}}"
  ERR="$(printf '%s' "$p" | CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$PR_GUARD" 2>&1 >/dev/null)"; CODE=$?
}
grace() { python3 -c "import json;print(json.load(open('$CACHE')).get('gate_grace_remaining'))"; }

python3 - "$FIXTURE" "$SESSION" <<'EOF'
import json, os, sys
fx, s = sys.argv[1], sys.argv[2]
LH = ("╭──────╮\n"
 "│ \U0001f94a lefthook v2.1.6  hook: pre-commit │\n╰──────╯\n"
 "┃  gitleaks ❯ \n\nclean\n\n┃  plugin-version-bump ❯ \n\nBLOCK: bump plugin.json\n\n"
 "exit status 1\nsummary: (done in 0.10 seconds)\n✔️ gitleaks (0.10 seconds)\n"
 "\U0001f94a plugin-version-bump: A changed plugin must bump its .claude-plugin/plugin.json version. (0.10 seconds)\n")
def pc(resp, cmd="git commit -m 'wip (ASK-214)'"):
    return {"session_id": s, "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": cmd}, "tool_response": resp}
json.dump(pc({"stdout":"","stderr":LH,"error":"Exit code 1"}), open(os.path.join(fx,"refused.json"),"w"))
json.dump(pc({"stdout":"","stderr":"exit status 1\n\U0001f94a gitleaks: Secret detected. (0.2 seconds)\n","error":"Exit code 1"}), open(os.path.join(fx,"refused2.json"),"w"))
json.dump(pc({"stdout":"nothing to commit, working tree clean","stderr":"","error":"Exit code 1"}), open(os.path.join(fx,"noop.json"),"w"))
json.dump(pc({"stdout":"[b abc123] fix\n 1 file changed","stderr":""}), open(os.path.join(fx,"landed.json"),"w"))
json.dump(pc({"stdout":"","stderr":"Dry run\n","error":"Exit code 1"}, "git commit --dry-run -m x"), open(os.path.join(fx,"dry.json"),"w"))
EOF

echo "A) headline case: real lefthook refusal at the ceiling -> Edit allowed?"
seed; post "$FIXTURE/refused.json"; edit h1
echo "   exit=$CODE  grace_left=$(grace)   (want exit 0)"

echo "B) ratchet: refuse, spend all 8, refuse AGAIN -> topped back up to 8?"
seed; post "$FIXTURE/refused.json"
for i in 1 2 3 4 5 6 7 8; do edit "r$i"; done
post "$FIXTURE/refused2.json"
echo "   grace after 2nd refusal = $(grace)  (want 0)"
edit r9; echo "   next call exit=$CODE :: ${ERR:0:70}"

echo "C) --dry-run commit failure mints budget?"
seed; post "$FIXTURE/dry.json"; echo "   grace=$(grace)  (want 0/None)"

echo "D) no-op commit mints budget?"
seed; post "$FIXTURE/noop.json"; echo "   grace=$(grace)  (want 0/None)"

echo "E) landed commit clears budget?"
seed; post "$FIXTURE/refused.json"; post "$FIXTURE/landed.json"; echo "   grace=$(grace)  (want 0)"

echo "F) grace never granted below the ceiling -> a run at 10 calls unaffected?"
python3 - "$CACHE" "$SESSION" <<'EOF'
import json, sys, time
json.dump({"actor_key": sys.argv[2], "tool_calls_since_user": 10,
  "agent_calls_since_user": 0, "mcp_timestamps": [], "repeat_map": {},
  "consecutive_reads": 0, "warnings_issued": 0, "file_read_counts": {},
  "greps_since_write": 0, "edit_targets": {}, "agents_without_write": 0,
  "last_write_time": time.time(), "calls_since_write": 1,
  "last_volume_reset": time.time()}, open(sys.argv[1], "w"))
EOF
post "$FIXTURE/refused.json"; edit f1
echo "   exit=$CODE  grace_left=$(grace)  (want exit 0, grace still 8 = unspent)"
rm -f "$CACHE"
