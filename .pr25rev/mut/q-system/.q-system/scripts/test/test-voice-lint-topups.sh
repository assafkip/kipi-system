#!/usr/bin/env bash
# H8+H10: voice-lint emphasis-opener detector + voice-substance >=2-anchor fix. Pairs with issue voice-lint-topups.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
VL="$ROOT/q-system/.q-system/scripts/voice-lint.py"
VS="$ROOT/q-system/.q-system/scripts/voice-substance-lint.py"
fail() { echo "FAIL: $1" >&2; exit 1; }
T="$(mktemp -d)"; mkdir -p "$T/q-system/output"

# H8: voice-lint BLOCKS an emphasis-opener on a published path
printf 'I shipped a real thing. It is worth mentioning that the pipeline worked.\n' > "$T/q-system/output/linkedin-test.md"
OUT="$(python3 "$VL" "$T/q-system/output/linkedin-test.md" 2>&1)" && rc=0 || rc=$?
[ "${rc:-0}" -eq 2 ] || fail "voice-lint did not BLOCK an emphasis-opener on a published path (rc=${rc:-0})"
echo "$OUT" | grep -qi "worth mentioning" || fail "voice-lint did not flag the emphasis-opener phrase: $OUT"
# clean published draft -> exit 0
printf 'I shipped it on 2026-06-19 and the test passed.\n' > "$T/q-system/output/linkedin-clean.md"
python3 "$VL" "$T/q-system/output/linkedin-clean.md" >/dev/null 2>&1 && rc=0 || rc=$?
[ "${rc:-1}" -eq 0 ] || fail "voice-lint blocked a clean draft (rc=${rc:-1})"

# H10: a single-proper-noun draft now WARNs (>=2 anchors required) and STAYS exit 0 (WARN-class)
python3 -c "print('We are looking at a topic here that continues on. ' * 11 + 'Acme appears once.')" > "$T/one.md"
OUT="$(python3 "$VS" "$T/one.md" 2>&1)" && rc=0 || rc=$?
[ "${rc:-1}" -eq 0 ] || fail "voice-substance HARD-BLOCKED (rc=${rc:-1}) -- must stay WARN-class exit 0"
echo "$OUT" | grep -qi "anchor" || fail "voice-substance did not WARN on a single-proper-noun draft: $OUT"
# >=2 anchors -> clean (no false-positive)
python3 -c "print('We are looking at a topic here that continues on. ' * 10 + 'I shipped Acme on 2026-06-19 with 3 wins.')" > "$T/two.md"
python3 "$VS" "$T/two.md" 2>&1 | grep -qi "no-substance-anchor\|fewer than 2" && fail "voice-substance warned on a 2-anchor draft (false positive)" || true

# MCP linter (DraftScanner via Linter.voice_lint) catches the emphasis-opener too
python3 - "$ROOT" <<'PYI'
import sys, os, json
sys.path.insert(0, os.path.join(sys.argv[1], "plugins/kipi-core/kipi-mcp/src"))
from kipi_mcp.linter import Linter
res = Linter().voice_lint("It is worth mentioning the synergy in this draft.")
assert "worth mentioning" in json.dumps(res).lower(), "MCP voice_lint missed the emphasis-opener: " + json.dumps(res)
print("MCP voice_lint catches the emphasis-opener")
PYI

echo "PASS: voice-lint blocks emphasis-openers (published), voice-substance requires >=2 anchors (WARN/exit 0), MCP voice_lint catches it"
