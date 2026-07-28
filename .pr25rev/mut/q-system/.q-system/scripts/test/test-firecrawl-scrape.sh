#!/usr/bin/env bash
# H7: firecrawl scrape-to-file, OFFLINE (mock response). Pairs with issue firecrawl-scrape.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
S="$ROOT/q-system/.q-system/scripts/firecrawl-scrape.py"
fail() { echo "FAIL: $1" >&2; exit 1; }
T="$(mktemp -d)"

# 1. no key + no mock -> exit 3 (env-var only)
( unset FIRECRAWL_API_KEY; unset FIRECRAWL_MOCK_RESPONSE; python3 "$S" "https://example.com/x" "$T/out" ) >/dev/null 2>&1 && rc=0 || rc=$?
[ "${rc:-0}" -eq 3 ] || fail "no-key did not exit 3 (got ${rc:-0})"

# 2. good mock response -> writes a file containing the full markdown
printf '{"data":{"markdown":"# Title\\n\\nFull source body that must be persisted verbatim."}}' > "$T/good.json"
OUTPATH="$(FIRECRAWL_MOCK_RESPONSE="$T/good.json" python3 "$S" "https://example.com/article" "$T/out")" || fail "good scrape errored"
[ -f "$OUTPATH" ] || fail "no file written for a good scrape"
grep -q "Full source body that must be persisted" "$OUTPATH" || fail "file missing the full markdown body"

# 3. empty body -> fail-CLOSED (exit 5), persists nothing
printf '{"data":{"markdown":"   "}}' > "$T/empty.json"
BEFORE="$(ls "$T/out" | wc -l | tr -d ' ')"
FIRECRAWL_MOCK_RESPONSE="$T/empty.json" python3 "$S" "https://example.com/empty" "$T/out" >/dev/null 2>&1 && rc=0 || rc=$?
[ "${rc:-0}" -eq 5 ] || fail "empty body did not fail-closed with exit 5 (got ${rc:-0})"
AFTER="$(ls "$T/out" | wc -l | tr -d ' ')"
[ "$BEFORE" -eq "$AFTER" ] || fail "empty body wrote a file (must persist nothing)"

# 4. filename sanitized (no ? & /)
SAFE="$(FIRECRAWL_MOCK_RESPONSE="$T/good.json" python3 "$S" "https://e.com/a/b?c=d&e=f" "$T/out2")" || fail "sanitize scrape errored"
case "$(basename "$SAFE")" in *'?'*|*'&'*|*'/'*) fail "filename not sanitized: $SAFE";; esac

# 5. type-confused bodies (markdown:null, data-as-list) -> fail-CLOSED exit 5, no file
#    Firecrawl returns markdown:null on a no-content scrape; must NOT crash with AttributeError.
mkdir -p "$T/out3"
for body in '{"data":{"markdown":null}}' '{"data":[1,2,3]}'; do
  printf '%s' "$body" > "$T/tc.json"
  B="$(ls "$T/out3" | wc -l | tr -d ' ')"
  FIRECRAWL_MOCK_RESPONSE="$T/tc.json" python3 "$S" "https://example.com/nc" "$T/out3" >/dev/null 2>&1 && rc=0 || rc=$?
  [ "${rc:-0}" -eq 5 ] || fail "type-confused body did not fail-closed with exit 5 (got ${rc:-0}) for: $body"
  A="$(ls "$T/out3" | wc -l | tr -d ' ')"
  [ "$B" -eq "$A" ] || fail "type-confused body wrote a file (must persist nothing) for: $body"
done

echo "PASS: env-key gated (exit 3), persists full markdown, fail-closed on empty/null/type-confused body (exit 5, no file), sanitized filename"
