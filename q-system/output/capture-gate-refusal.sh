#!/usr/bin/env bash
# One-off ground-truth capture (ASK-215): the exact text a lefthook-refused
# commit emits, so the grace detector keys off real output, not remembered
# output. Run: bash q-system/output/capture-gate-refusal.sh
set -uo pipefail

SCRATCH="$(mktemp -d)"
trap 'python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$SCRATCH"' EXIT

cd "$SCRATCH"
git init -q .
git config user.email t@t.t
git config user.name t
git config commit.gpgsign false

cat > lefthook.yml <<'YML'
pre-commit:
  parallel: true
  commands:
    plugin-version-bump:
      run: |
        echo "BLOCK: bump plugin.json"
        exit 1
      fail_text: "A changed plugin must bump its .claude-plugin/plugin.json version."
    gitleaks:
      run: |
        echo clean
YML

# lefthook install writes this shim; write it directly so no install step is needed.
mkdir -p .git/hooks
cat > .git/hooks/pre-commit <<'HOOK'
#!/bin/sh
exec lefthook run pre-commit
HOOK
chmod +x .git/hooks/pre-commit

echo hello > a.txt
git add a.txt lefthook.yml

echo "===== LEFTHOOK-REFUSED git commit ====="
set +e
OUT="$(git commit -m 'test (ASK-215)' 2>&1)"
CODE=$?
set -e
echo "exit_code=$CODE"
echo "--- combined output (repr per line) ---"
printf '%s\n' "$OUT" | python3 -c "import sys;[print(repr(l.rstrip(chr(10)))) for l in sys.stdin]"
