#!/usr/bin/env bash
# Throwaway measurement, part 2: the same reader-write class INSIDE a command that
# re-baselines Layer 2 (the exact position the round-10 finding names, guard:994).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
GUARD="$ROOT/q-system/.q-system/scripts/claude-path-write-guard.py"
TRIP="q-system/.q-system/scripts/claude-integrity-tripwire.py"

run() {
  python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]},"cwd":sys.argv[2]}))' "$1" "$ROOT" \
    | CLAUDE_PROJECT_DIR="$ROOT" python3 "$GUARD" 2>/tmp/round10.err >/dev/null
  local rc=$?
  printf 'rc=%s  %s\n' "$rc" "$1"
  [ "$rc" != 0 ] && sed -n '1p' /tmp/round10.err | sed 's/^/      /'
  return 0
}

run "awk -v f=.claude/settings.json 'BEGIN{print \"x\" > f}'; python3 $TRIP --baseline"
run "P=.claude; V=P; awk -v f=\${!V}/settings.json 'BEGIN{print \"x\" > f}'; python3 $TRIP --baseline"
run "sed -n 'w .claude/settings.json' /etc/hosts; python3 $TRIP --baseline"
run "sort -o .claude/settings.json /dev/null; python3 $TRIP --baseline"
run "uniq /dev/null .claude/settings.json; python3 $TRIP --baseline"
run "tree -o .claude/settings.json .; python3 $TRIP --baseline"
