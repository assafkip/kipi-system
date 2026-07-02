#!/usr/bin/env bash
# Required check for issue token-guard-template-blocking (spillover sp-dd731488).
# Scar 2026-07-01: settings-template.json wired token-guard as
# `test -f X && python3 X || true`, which swallowed exit 2 — the circuit
# breaker could never block in any instance built from the template, while the
# skeleton's own settings.json blocked correctly. This test extracts the ACTUAL
# command strings from the template and proves exit-2 propagation, so the
# `|| true` form cannot come back unnoticed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
TEMPLATE="$REPO_ROOT/settings-template.json"

# 1) Pull every token-guard hook command out of the template (json-aware, no grep guessing).
# Lines are "event<TAB>matcher<TAB>command" so the test also locks WHICH events
# (and, for PostToolUse, which tools) carry the wiring (Codex finding
# 2026-07-02: command-only extraction would pass with both wirings moved to the
# wrong event; hooks-review 2026-07-02: the PostToolUse leg — successful-edit
# spiral reset + commit reset — was wired NOWHERE, dead code since March).
# macOS ships bash 3.2: no mapfile, so read-loop into the arrays
extract_wirings() { # $1 = settings file; prints event\tmatcher\tcommand
  python3 - "$1" <<'EOF'
import json, sys
hooks = json.load(open(sys.argv[1]))["hooks"]
for event, groups in hooks.items():
    for g in groups:
        for h in g.get("hooks", []):
            cmd = h.get("command", "")
            if "token-guard.py" in cmd:
                # empty matcher prints as "-": tab is IFS whitespace, so bash
                # `read` collapses "\t\t" and would shift cmd into the matcher field
                print(f"{event}\t{g.get('matcher') or '-'}\t{cmd}")
EOF
}

# Both settings files must carry all three wirings: the template feeds the
# fleet, the skeleton's own settings.json is its runtime (sync-scar 2026-06-30).
check_events() { # $1 = label, $2 = extracted lines
  local label="$1" lines="$2" events="" post_matcher=""
  while IFS=$'\t' read -r _event _matcher _cmd; do
    [ -n "$_event" ] || continue
    events="$events $_event"
    [ "$_event" = "PostToolUse" ] && post_matcher="$_matcher"
  done <<< "$lines"
  for required in UserPromptSubmit PreToolUse PostToolUse; do
    case "$events" in
      *"$required"*) :;;
      *) echo "FAIL($label): no token-guard wiring on $required (found:$events)"; exit 1;;
    esac
  done
  # The PostToolUse leg needs Edit/Write (spiral reset) AND Bash (commit reset)
  for tool in Edit Write Bash; do
    case "$post_matcher" in
      *"$tool"*) :;;
      *) echo "FAIL($label): PostToolUse token-guard matcher '$post_matcher' missing $tool"; exit 1;;
    esac
  done
}

check_events "template" "$(extract_wirings "$TEMPLATE")"
check_events "skeleton" "$(extract_wirings "$REPO_ROOT/.claude/settings.json")"

COMMANDS=()
EVENTS=""
while IFS=$'\t' read -r _event _matcher _cmd; do
  [ -n "$_cmd" ] || continue
  COMMANDS+=("$_cmd")
  EVENTS="$EVENTS $_event"
done <<< "$(extract_wirings "$TEMPLATE")"

[ "${#COMMANDS[@]}" -ge 3 ] || { echo "FAIL: expected >=3 token-guard wirings in template, found ${#COMMANDS[@]}"; exit 1; }

# 2) Static: the swallow form is banned
for cmd in "${COMMANDS[@]}"; do
  case "$cmd" in
    *"|| true"*) echo "FAIL: token-guard command swallows exit codes: $cmd"; exit 1;;
  esac
done

# 3) Functional: run each REAL command string against a fixture project dir
FIXTURE="$(mktemp -d)"
# Clean up on ANY exit, not just success (Codex nit 2026-07-02: failing runs leaked the tempdir)
trap 'python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$FIXTURE"' EXIT
mkdir -p "$FIXTURE/q-system/.q-system"
printf '#!/usr/bin/env python3\nimport sys; sys.exit(2)\n' > "$FIXTURE/q-system/.q-system/token-guard.py"

for cmd in "${COMMANDS[@]}"; do
  rc=0
  CLAUDE_PROJECT_DIR="$FIXTURE" sh -c "$cmd" >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 2 ] || { echo "FAIL: exit 2 not propagated (got $rc) by: $cmd"; exit 1; }
done

# 4) Missing script must be a no-op (fresh instances before first kipi update)
python3 -c 'import os,sys; os.remove(sys.argv[1])' "$FIXTURE/q-system/.q-system/token-guard.py"
for cmd in "${COMMANDS[@]}"; do
  rc=0
  CLAUDE_PROJECT_DIR="$FIXTURE" sh -c "$cmd" >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 0 ] || { echo "FAIL: missing token-guard.py should be a no-op (got $rc) for: $cmd"; exit 1; }
done

echo "PASS: token-guard template wiring propagates exit 2 and no-ops when missing (${#COMMANDS[@]} wirings on:$EVENTS)"
