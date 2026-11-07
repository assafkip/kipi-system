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
    ],
    "UserPromptSubmit": [
      {"hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/memory-scores-surface.py\" 2>/dev/null || true"},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/instance-live-surface.py\" 2>/dev/null || true"},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/chained-live-guard.py\"; python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/memory-scores-surface.py\" || true"}
      ]}
    ],
    "Stop": [
      {"hooks": [
        {"type": "command", "command": "test -f \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/memory_autocapture.py\" && python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/memory_autocapture.py\" 2>/dev/null || true", "async": true}
      ]}
    ]
  }
}
EOF

python3 "$MERGE" "$FIXTURE/template.json" "$FIXTURE/instance.json" >/dev/null

python3 - "$FIXTURE/instance.json" "$REPO_ROOT/settings-template.json" "$REPO_ROOT/kipi-retired-hooks.json" <<'EOF'
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

# ASK-3512: the union keeps every instance-only hook, so hooks RETIRED from the
# template (#571: memory_autocapture, memory-scores-surface) lived on in every
# instance as inert test -f wiring no check could tell from live wiring. The
# retired list is data (kipi-retired-hooks.json), dropped from the INSTANCE side
# only. Negative control: an unlisted live hook must stay.
all_cmds = [h["command"] for ev in merged["hooks"].values() for g in ev for h in g["hooks"]]
for dead in ("memory_autocapture.py", "memory-scores-surface.py"):
    assert not any(dead in c and "chained-live-guard.py" not in c for c in all_cmds), f"retired hook {dead} survived the merge"
assert any("chained-live-guard.py" in c for c in all_cmds), "a live script chained with a retired one was dropped"
# Review minor: a retired script still wired in the template makes the list a silent no-op.
tpl = open(sys.argv[2]).read()
for e in json.load(open(sys.argv[3]))["scripts"]:
    assert e["script"] not in tpl, f"{e['script']} is on the retired list but still wired in settings-template.json"
assert any("instance-live-surface.py" in c for c in all_cmds), \
    "live instance hook not on the retired list was dropped"
assert all(g["hooks"] for ev in merged["hooks"].values() for g in ev), \
    "empty hook group left behind after retiring its only hook"

assert "custom-server" in merged.get("mcpServers", {}), "instance mcpServers dropped"
assert "Bash(instance-only:*)" in merged["permissions"]["allow"], "instance permission dropped"
assert "Bash(ls:*)" in merged["permissions"]["allow"], "template permission dropped"
EOF
echo "ok: stale token-guard variants retired, template form wins, instance hooks/MCP/permissions survive"

# ASK-3685: apply-claude-changes now lets an instance wire its OWN hooks in
# .claude/settings.json, on the premise that this merge keeps them. Codex review
# of PR #615 showed the premise held only by luck: identity was the BASENAME
# alone, so an instance script that happened to share a name with a template
# script (or with a retired one) was deduped or retired away on the next update.
# A script outside the q-system/ subtree is the instance's own, so it is keyed
# by its path instead. Template hooks all live under q-system/ and keep their
# basename identity, so the token-guard fossil dedup above is unchanged.
cat > "$FIXTURE/template2.json" <<'EOF'
{
  "hooks": {
    "PreToolUse": [
      {"matcher": ".*", "hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py\""}
      ]}
    ]
  }
}
EOF
cat > "$FIXTURE/instance2.json" <<'EOF'
{
  "hooks": {
    "PreToolUse": [
      {"matcher": ".*", "hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py\""},
        {"type": "command", "command": "if test -f \"$CLAUDE_PROJECT_DIR/q-inst/token-guard.py\"; then python3 \"$CLAUDE_PROJECT_DIR/q-inst/token-guard.py\"; fi"}
      ]}
    ],
    "Stop": [
      {"hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-inst/memory_autocapture.py\""},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/memory_autocapture.py\""}
      ]}
    ]
  }
}
EOF
python3 "$MERGE" "$FIXTURE/template2.json" "$FIXTURE/instance2.json" >/dev/null
python3 - "$FIXTURE/instance2.json" <<'EOF'
import json, sys
merged = json.load(open(sys.argv[1]))
all_cmds = [h["command"] for ev in merged["hooks"].values() for g in ev for h in g["hooks"]]
assert any("q-inst/token-guard.py" in c for c in all_cmds), \
    "an instance-owned script sharing a template basename was deduped away"
assert sum("q-system/.q-system/token-guard.py" in c for c in all_cmds) == 1, \
    "the template token-guard must stay exactly once"
assert any("q-inst/memory_autocapture.py" in c for c in all_cmds), \
    "an instance-owned script sharing a retired basename was retired away"
assert not any("q-system/.q-system/scripts/memory_autocapture.py" in c for c in all_cmds), \
    "the retired skeleton script must still be dropped"
EOF
echo "ok: instance-owned scripts keep their hooks even when a basename collides"

# Codex round 2 on PR #615, two spellings that defeated a substring test:
#  - "q-system/" deeper in an INSTANCE path still made it skeleton-owned;
#  - a quote between directory and file name hid the q-system/ prefix, so a
#    template script read as an instance path and ran twice (the doubled
#    token-guard scar) or escaped retirement.
# Ownership is now the leading component of the project-relative path, read
# after shell quotes are removed. Anything not provably project-relative keeps
# the old basename identity, so an unknown spelling fails toward dedup.
cat > "$FIXTURE/instance3.json" <<'EOF'
{
  "hooks": {
    "PreToolUse": [
      {"matcher": ".*", "hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system\"/token-guard.py"},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/Q-SYSTEM/.q-system/token-guard.py\""},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-inst/not-q-system/token-guard.py\""}
      ]}
    ],
    "Stop": [
      {"hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts\"/memory_autocapture.py"}
      ]}
    ]
  }
}
EOF
python3 "$MERGE" "$FIXTURE/template2.json" "$FIXTURE/instance3.json" >/dev/null
python3 - "$FIXTURE/instance3.json" <<'EOF'
import json, sys
merged = json.load(open(sys.argv[1]))
all_cmds = [h["command"] for ev in merged["hooks"].values() for g in ev for h in g["hooks"]]
assert any("q-inst/not-q-system/token-guard.py" in c for c in all_cmds), \
    "an instance path containing q-system/ deeper down was deduped away"
skel = [c for c in all_cmds if "token-guard.py" in c and "q-inst/" not in c]
assert len(skel) == 1, f"template token-guard must run once, got {len(skel)}: {skel}"
assert not any("memory_autocapture.py" in c for c in all_cmds), \
    "a quoted spelling of a retired skeleton script escaped retirement"
EOF
echo "ok: ownership reads the leading path component, after shell quotes"

echo "PASS: kipi-settings-merge dedupes hooks by invoked script, not raw command string"
