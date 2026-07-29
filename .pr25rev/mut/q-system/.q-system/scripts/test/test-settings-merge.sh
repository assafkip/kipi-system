#!/usr/bin/env bash
# Required check for kipi-settings-merge.py (extracted from kipi-update.sh).
# Scar 2026-07-02: the inline merge deduped hooks by EXACT command string, so a
# template command-form change (token-guard `|| true` -> if-then) left BOTH
# forms in every instance — token-guard ran twice per tool call and all its
# counters doubled (50-call ceiling behaved as 25). Observed live in
# school-negotiator: 3 token-guard commands per event (current, prior form,
# pre-flattening `q-system/q-system/` fossil). This test proves the merge
# retires stale variants of the same script while instance-added hooks survive.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
MERGE="$REPO_ROOT/kipi-settings-merge.py"
# Skeleton-only harness: instances receive this test via sync but not the
# merge script (repo-root files do not propagate). No-op there.
[ -f "$MERGE" ] || { echo "SKIP: kipi-settings-merge.py absent (instance)"; exit 0; }

FIXTURE="$(mktemp -d)"
trap 'python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$FIXTURE"' EXIT

cat > "$FIXTURE/template.json" <<'EOF'
{
  "permissions": {"allow": ["Bash(ls:*)"]},
  "hooks": {
    "PreToolUse": [
      {"matcher": ".*", "hooks": [
        {"type": "command", "command": "if [ -f \"$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py\" ]; then python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py\"; fi", "timeout": 5}
      ]}
    ]
  }
}
EOF

cat > "$FIXTURE/instance.json" <<'EOF'
{
  "mcpServers": {"custom-server": {"command": "npx custom"}},
  "permissions": {"allow": ["Bash(instance-only:*)"]},
  "hooks": {
    "PreToolUse": [
      {"matcher": ".*", "hooks": [
        {"type": "command", "command": "test -f \"$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py\" && python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py\" || true", "timeout": 5},
        {"type": "command", "command": "test -f \"$CLAUDE_PROJECT_DIR/q-system/q-system/.q-system/token-guard.py\" && python3 \"$CLAUDE_PROJECT_DIR/q-system/q-system/.q-system/token-guard.py\" || true", "timeout": 5},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/instance-custom-gate.py\"", "timeout": 5}
      ]}
    ]
  }
}
EOF

python3 "$MERGE" "$FIXTURE/template.json" "$FIXTURE/instance.json" >/dev/null

python3 - "$FIXTURE/instance.json" <<'EOF'
import json, sys
merged = json.load(open(sys.argv[1]))
cmds = [h["command"]
        for g in merged["hooks"]["PreToolUse"]
        for h in g["hooks"]]

tg = [c for c in cmds if "token-guard.py" in c]
assert len(tg) == 1, f"expected exactly 1 token-guard wiring after merge, got {len(tg)}: {tg}"
assert tg[0].startswith("if [ -f"), f"template's current form must win, got: {tg[0][:60]}"
assert "|| true" not in tg[0], "stale swallow form survived the merge"

assert any("instance-custom-gate.py" in c for c in cmds), \
    "instance-added hook for a script the template does not know must survive"

assert "custom-server" in merged.get("mcpServers", {}), "instance mcpServers dropped"
assert "Bash(instance-only:*)" in merged["permissions"]["allow"], "instance permission dropped"
assert "Bash(ls:*)" in merged["permissions"]["allow"], "template permission dropped"
EOF
echo "ok: stale token-guard variants retired, template form wins, instance hooks/MCP/permissions survive"

echo "PASS: kipi-settings-merge dedupes hooks by invoked script, not raw command string"
