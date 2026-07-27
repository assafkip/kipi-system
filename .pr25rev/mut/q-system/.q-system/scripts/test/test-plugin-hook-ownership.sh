#!/usr/bin/env bash
# Required check for issue lint-hook-ownership-dedupe (spillover sp-700047ff).
# Scar 2026-07-02: plugins/kipi-core/hooks/hooks.json wired six lints against
# $CLAUDE_PROJECT_DIR/q-system scripts — the same six settings-template.json
# regenerates into every instance's settings.json — so instances with kipi-core
# ran each lint TWICE per Edit/Write. Ownership rule this test pins: a plugin's
# hooks.json may only invoke scripts the plugin itself ships
# (CLAUDE_PLUGIN_ROOT); wirings for kipi-update-propagated q-system/ scripts
# belong to the settings template, which ships alongside those scripts.
#
# Deliberately narrower than "no CLAUDE_PROJECT_DIR at all" (Codex finding-2 on
# prd-lint-hook-ownership-dedupe-2026-07-02): only CLAUDE_PROJECT_DIR paths
# under q-system/ are template-owned. The RAW command string is scanned, so
# ${VAR} vs $VAR spelling, wrappers, and `bash -c` nesting cannot hide a
# reference (Codex finding-3, same review).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
# Instances receive this test via q-system sync; plugins/ also propagates, so
# the assertion holds there too. Skip only if the tree has no plugin hooks.
ls "$REPO_ROOT"/plugins/*/hooks/hooks.json >/dev/null 2>&1 \
  || { echo "SKIP: no plugins/*/hooks/hooks.json in this tree"; exit 0; }

python3 - "$REPO_ROOT" <<'EOF'
import glob, json, os, re, sys

repo_root = sys.argv[1]
# $CLAUDE_PROJECT_DIR or ${CLAUDE_PROJECT_DIR}, optionally quoted, followed by
# /q-system/ — the kipi-update-propagated tree whose wirings the template owns.
Q_SYSTEM_REF = re.compile(r"\$\{?CLAUDE_PROJECT_DIR\}?[\"']?/q-system/")

violations = []
for path in sorted(glob.glob(os.path.join(repo_root, "plugins/*/hooks/hooks.json"))):
    hooks = json.load(open(path)).get("hooks", {})
    for event, groups in hooks.items():
        for group in groups:
            for hook in group.get("hooks", []):
                command = hook.get("command", "")
                if Q_SYSTEM_REF.search(command):
                    rel = os.path.relpath(path, repo_root)
                    violations.append(f"{rel} [{event}]: {command[:100]}")

if violations:
    print("FAIL: plugin hooks wire template-owned q-system scripts "
          "(plugin hooks may only invoke plugin-shipped scripts):")
    for v in violations:
        print(f"  {v}")
    sys.exit(1)
EOF

echo "ok: no plugin hooks.json wires a CLAUDE_PROJECT_DIR/q-system script (template-owned)"

# --- Template PostToolUse lints must propagate exit 2 (no `|| true`) ---
# Codex adversarial finding on issue lint-hook-ownership-dedupe: removing the
# plugin's UNMASKED voice-lint/voice-substance-lint copies while the template's
# copies ended in `|| true` would have downgraded both lints to advisory in
# every instance — the same swallow-form scar as token-guard (sp-dd731488).
# Rule: a PostToolUse hook exists to validate an edit; swallowing its exit code
# is banned. Informational SessionStart/UserPromptSubmit hooks may swallow.
TEMPLATE="$REPO_ROOT/settings-template.json"
if [ -f "$TEMPLATE" ]; then
  python3 - "$TEMPLATE" <<'EOF'
import json, sys

hooks = json.load(open(sys.argv[1])).get("hooks", {})
violations = [
    f"[{'PostToolUse'}] {h.get('command', '')[:100]}"
    for group in hooks.get("PostToolUse", [])
    for h in group.get("hooks", [])
    if "|| true" in h.get("command", "")
]
if violations:
    print("FAIL: template PostToolUse hooks swallow exit codes (blocking lints must propagate exit 2):")
    for v in violations:
        print(f"  {v}")
    sys.exit(1)
EOF
  echo "ok: no template PostToolUse hook swallows exit codes"
else
  echo "ok: no settings-template.json in this tree (instance) — template check skipped"
fi

echo "PASS: plugin hooks wire only plugin-shipped scripts; template PostToolUse lints propagate exit 2"
