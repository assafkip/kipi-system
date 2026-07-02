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

# 1) Pull every token-guard hook command out of the template (json-aware, no grep guessing)
# macOS ships bash 3.2: no mapfile, so read-loop into the array
COMMANDS=()
while IFS= read -r _cmd; do COMMANDS+=("$_cmd"); done < <(python3 - "$TEMPLATE" <<'EOF'
import json, sys
hooks = json.load(open(sys.argv[1]))["hooks"]
for event, groups in hooks.items():
    for g in groups:
        for h in g.get("hooks", []):
            cmd = h.get("command", "")
            if "token-guard.py" in cmd:
                print(cmd)
EOF
)

[ "${#COMMANDS[@]}" -ge 2 ] || { echo "FAIL: expected >=2 token-guard wirings in template, found ${#COMMANDS[@]}"; exit 1; }

# 2) Static: the swallow form is banned
for cmd in "${COMMANDS[@]}"; do
  case "$cmd" in
    *"|| true"*) echo "FAIL: token-guard command swallows exit codes: $cmd"; exit 1;;
  esac
done

# 3) Functional: run each REAL command string against a fixture project dir
FIXTURE="$(mktemp -d)"
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

python3 -c 'import shutil,sys; shutil.rmtree(sys.argv[1])' "$FIXTURE"
echo "PASS: token-guard template wiring propagates exit 2 and no-ops when missing (${#COMMANDS[@]} wirings)"
