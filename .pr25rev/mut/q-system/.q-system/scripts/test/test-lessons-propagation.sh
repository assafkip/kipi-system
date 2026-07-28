#!/usr/bin/env bash
# Test: q-system/lessons/ propagates via kipi update (not excluded from the rsync sync).
# Derives the exclude list from kipi-update.sh itself, so this is not a tautology.
# Pairs with issue lessons-scaffold / PRD prd-cross-instance-learning-2026-06-19.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
LESSONS="$ROOT/q-system/lessons"
UPDATE="$ROOT/kipi-update.sh"
fail() { echo "FAIL: $1" >&2; exit 1; }

[ -f "$LESSONS/README.md" ] || fail "q-system/lessons/README.md missing"
ls "$LESSONS"/*.md >/dev/null 2>&1 || fail "no lesson files in q-system/lessons/"

# 1. no exclude/filter directive in kipi-update.sh references lessons (any form: =, space, --filter)
if grep -iE 'exclude|filter' "$UPDATE" | grep -qi 'lessons'; then
  fail "kipi-update.sh excludes/filters lessons (it must propagate)"
fi

# 2. derive the REAL excludes kipi-update.sh applies, run a dry-run with them, expect lessons/ present
ARGS=()
while IFS= read -r e; do [ -n "$e" ] && ARGS+=(--exclude="$e"); done \
  < <(grep -oE -- '--exclude=[^[:space:]]*' "$UPDATE" | sed -E 's/^--exclude=//; s/"//g')
TMP="$(mktemp -d)"; trap 'rmdir "$TMP" 2>/dev/null || true' EXIT  # -n dry-run never populates $TMP
INCL="$(rsync -ain --delete ${ARGS[@]+"${ARGS[@]}"} "$ROOT/q-system/" "$TMP/" 2>/dev/null | grep -c 'lessons/' || true)"
[ "$INCL" -ge 1 ] || fail "dry-run with kipi-update's real excludes omitted lessons/ (propagation broken)"

# 3. NEGATIVE self-test: add lessons/ to those same real excludes; it must vanish
EXCL="$(rsync -ain --delete ${ARGS[@]+"${ARGS[@]}"} --exclude='lessons/' "$ROOT/q-system/" "$TMP/" 2>/dev/null | grep -c 'lessons/' || true)"
[ "$EXCL" -eq 0 ] || fail "negative self-test broken: lessons/ appeared even when excluded"

echo "PASS: kipi-update's real excludes fan lessons/ down (and exclude it when told to)"
