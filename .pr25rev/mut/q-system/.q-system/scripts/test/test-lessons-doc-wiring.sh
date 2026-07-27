#!/usr/bin/env bash
# Keeps H0 docs/wiring in sync. Pairs with issue lessons-doc-wiring-sync.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
fail() { echo "FAIL: $1" >&2; exit 1; }
grep -q "q-system/lessons/" "$ROOT/.claude/rules/folder-structure.md" || fail "folder-structure.md does not reference q-system/lessons/"
grep -qi "New cross-instance lesson" "$ROOT/.claude/rules/folder-structure.md" || fail "folder-structure.md missing the lessons Placement Rule"
grep -qi "To add a lesson" "$ROOT/q-system/lessons/README.md" || fail "README.md missing the authoring instruction"
grep -q "lessons-index.py" "$ROOT/.claude/settings.json" || fail ".claude/settings.json does not register lessons-index.py"
echo "PASS: folder-structure tree+rule, README authoring instruction, and skeleton settings consumer are all in sync"
