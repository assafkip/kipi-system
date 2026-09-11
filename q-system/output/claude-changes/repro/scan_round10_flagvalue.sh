#!/usr/bin/env bash
# Throwaway measurement, part 3: a .claude path GLUED TO A FLAG token. The flag
# skip in _stage()/_unanchored_unwatched() exists because a flag is not a path --
# but `--output=.claude/x` and `-o.claude/x` are a flag AND a path.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
GUARD="$ROOT/q-system/.q-system/scripts/claude-path-write-guard.py"
TRIP="q-system/.q-system/scripts/claude-integrity-tripwire.py"

run() {
  python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]},"cwd":sys.argv[2]}))' "$1" "$ROOT" \
    | CLAUDE_PROJECT_DIR="$ROOT" python3 "$GUARD" >/dev/null 2>&1
  printf 'rc=%s  %s\n' "$?" "$1"
}

run "sort --output=.claude/settings.json /dev/null"
run "sort -o.claude/settings.json /dev/null"
run "tar --file=.claude/settings.json -c /dev/null"
run "cp --target-directory=.claude /etc/hosts"
run "install --mode=644 /etc/hosts .claude/settings.json"
run "sort --output=.claude/settings.json /dev/null; python3 $TRIP --baseline"
echo "--- controls: free text in a flag value must not become a false block ---"
run "python3 script.py --desc=see-the-guard-notes"
run "python3 script.py --output=/tmp/out.json"
