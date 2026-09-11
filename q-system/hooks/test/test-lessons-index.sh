#!/usr/bin/env bash
# Test suite for lessons-index.py (SessionStart consumer). Pairs with issue lessons-consumer-hook.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
H="$ROOT/q-system/hooks/lessons-index.py"
fail() { echo "FAIL: $1" >&2; exit 1; }
lesson() { printf -- '---\nid: %s\nkind: pattern\ntitle: %s\ndate: %s\n---\nBODY-SECRET-%s\n' "$2" "$4" "$3" "$2" > "$1/$2.md"; }

# 1. flat layout: titles present, bodies absent, README excluded, exit 0
D1="$(mktemp -d)"; mkdir -p "$D1/q-system/lessons"
lesson "$D1/q-system/lessons" alpha 2026-06-01 "Alpha pattern"
lesson "$D1/q-system/lessons" beta 2026-06-10 "Beta pattern"
echo "# readme" > "$D1/q-system/lessons/README.md"
OUT="$(CLAUDE_PROJECT_DIR="$D1" python3 "$H")" || fail "flat: nonzero exit"
echo "$OUT" | python3 -c "import sys,json; a=json.load(sys.stdin)['hookSpecificOutput']['additionalContext']; assert 'Alpha pattern' in a and 'Beta pattern' in a; assert 'BODY-SECRET' not in a; assert a.count('- ')==2" || fail "flat: titles/bodies/count"

# 2. NO CAP: 25 lessons yield 25 titles (ASK-965).
# This case asserted the OPPOSITE until 2026-08-21 -- 25 lessons in, 20 titles out
# -- because the injector capped at 20. It is inverted, not deleted: the cap hid
# 126 of 146 lessons every session and chose which to hide by ALPHABETICAL
# FILENAME (the sort key was date-only and Python's sort is stable). Keeping the
# case with the assertion flipped means a future re-introduction of a cap turns
# this red instead of quietly passing.
D2="$(mktemp -d)"; mkdir -p "$D2/q-system/lessons"
for i in $(seq -w 1 25); do lesson "$D2/q-system/lessons" "l$i" "2026-06-$i" "Title $i"; done
CNT="$(CLAUDE_PROJECT_DIR="$D2" python3 "$H" | python3 -c "import sys,json; print(json.load(sys.stdin)['hookSpecificOutput']['additionalContext'].count('- Title'))")"
[ "$CNT" -eq 25 ] || fail "no-cap: expected all 25 titles, got $CNT"

# 3. absent lessons/ -> empty output, exit 0 (never-blocks)
D3="$(mktemp -d)"; mkdir -p "$D3/q-system"
OUT3="$(CLAUDE_PROJECT_DIR="$D3" python3 "$H")" || fail "absent: nonzero exit"
[ -z "$OUT3" ] || fail "absent: emitted output with no lessons/"

# 4. nested q-system/q-system/ layout found
D4="$(mktemp -d)"; mkdir -p "$D4/q-system/q-system/canonical" "$D4/q-system/q-system/lessons"
lesson "$D4/q-system/q-system/lessons" gamma 2026-06-05 "Gamma nested"
CLAUDE_PROJECT_DIR="$D4" python3 "$H" | python3 -c "import sys,json; assert 'Gamma nested' in json.load(sys.stdin)['hookSpecificOutput']['additionalContext']" || fail "nested: title not found"

rm "$D1"/q-system/lessons/* "$D2"/q-system/lessons/* "$D4"/q-system/q-system/lessons/* 2>/dev/null || true
echo "PASS: titles-only (no bodies), NO cap (all 25 injected), exit 0 on absent lessons, nested layout found, README excluded"
