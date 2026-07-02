#!/usr/bin/env bash
# Required checks for the token-guard hook fixes (hooks review 2026-07-02).
# Scar 1: warn() printed top-level {"additionalContext": ...} from PreToolUse,
#   which Claude Code IGNORES (contract: nested hookSpecificOutput with
#   hookEventName). Every warning tier was silent; the guard went from zero
#   feedback straight to exit-2 hard blocks.
# Scar 2: the PostToolUse leg (successful-edit spiral reset, commit reset
#   "Wiring A") existed in the script but was wired in no settings file, so a
#   3rd successful Edit to one file falsely blocked. This test pins the LEG's
#   behavior; the wiring test pins the settings wiring.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
GUARD="$REPO_ROOT/q-system/.q-system/token-guard.py"
SESSION="tg-behavior-test-$$"
CACHE="/tmp/claude-guard-$SESSION.json"
FIXTURE="$(mktemp -d)"
trap 'rm -f "$CACHE"; python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$FIXTURE"' EXIT

run_guard() { # $1 = event JSON on stdin; guard runs with fixture as project dir
  printf '%s' "$1" | CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$GUARD"
}

# --- 1) warn() output must use the nested PreToolUse hookSpecificOutput form ---
# Seed a cache one read short of the read-spiral threshold; the next Read warns.
python3 - "$CACHE" "$SESSION" <<'EOF'
import json, sys, time
cache = {
    "actor_key": sys.argv[2],
    "tool_calls_since_user": 1,
    "agent_calls_since_user": 0,
    "mcp_timestamps": [],
    "repeat_map": {},
    "consecutive_reads": 14,
    "warnings_issued": 0,
    "file_read_counts": {},
    "greps_since_write": 0,
    "edit_targets": {},
    "agents_without_write": 0,
    "last_write_time": time.time(),
    "calls_since_write": 1,
    "last_volume_reset": time.time(),
}
json.dump(cache, open(sys.argv[1], "w"))
EOF

OUT="$(run_guard "{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PreToolUse\", \"tool_name\": \"Read\", \"tool_input\": {\"file_path\": \"/tmp/spiral-probe\"}}")" \
  || { echo "FAIL: warn path exited non-zero"; exit 1; }
python3 - <<EOF
import json, sys
out = json.loads('''$OUT''')
hso = out.get("hookSpecificOutput")
assert isinstance(hso, dict), f"warn() must nest under hookSpecificOutput, got top-level keys: {list(out)}"
assert hso.get("hookEventName") == "PreToolUse", f"hookEventName wrong: {hso.get('hookEventName')}"
assert hso.get("additionalContext"), "additionalContext missing/empty inside hookSpecificOutput"
assert "additionalContext" not in out, "additionalContext must NOT be top-level (Claude Code ignores it there)"
EOF
echo "ok: warn() emits nested PreToolUse hookSpecificOutput"

# --- 2) PostToolUse leg: a SUCCESSFUL Edit clears that file's spiral counter ---
python3 - "$CACHE" <<'EOF'
import json, sys
cache = json.load(open(sys.argv[1]))
cache["edit_targets"] = {"/tmp/some-file.py": 2}
cache["consecutive_reads"] = 0
json.dump(cache, open(sys.argv[1], "w"))
EOF

run_guard "{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PostToolUse\", \"tool_name\": \"Edit\", \"tool_input\": {\"file_path\": \"/tmp/some-file.py\"}, \"tool_response\": {\"filePath\": \"/tmp/some-file.py\"}}" \
  >/dev/null || { echo "FAIL: PostToolUse leg exited non-zero"; exit 1; }
python3 - "$CACHE" <<'EOF'
import json, sys
cache = json.load(open(sys.argv[1]))
assert "/tmp/some-file.py" not in cache.get("edit_targets", {}), \
    f"successful Edit did not clear edit_targets: {cache.get('edit_targets')}"
EOF
echo "ok: PostToolUse successful Edit clears edit_targets"

# --- 3) PostToolUse leg: a FAILED Edit keeps counting (the real spiral) ---
python3 - "$CACHE" <<'EOF'
import json, sys
cache = json.load(open(sys.argv[1]))
cache["edit_targets"] = {"/tmp/some-file.py": 2}
json.dump(cache, open(sys.argv[1], "w"))
EOF
run_guard "{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PostToolUse\", \"tool_name\": \"Edit\", \"tool_input\": {\"file_path\": \"/tmp/some-file.py\"}, \"tool_response\": \"Error: string not found\"}" \
  >/dev/null || { echo "FAIL: PostToolUse failed-edit path exited non-zero"; exit 1; }
python3 - "$CACHE" <<'EOF'
import json, sys
cache = json.load(open(sys.argv[1]))
assert cache.get("edit_targets", {}).get("/tmp/some-file.py") == 2, \
    f"failed Edit must NOT clear edit_targets: {cache.get('edit_targets')}"
EOF
echo "ok: PostToolUse failed Edit keeps the spiral counter"

echo "PASS: token-guard hook behavior (warn shape + PostToolUse edit reset)"
