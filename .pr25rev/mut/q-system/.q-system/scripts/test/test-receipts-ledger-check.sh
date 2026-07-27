#!/usr/bin/env bash
# Pairs with receipts-ledger-check.py (the content gate on the one .jsonl that
# blocked-paths lets through).
#
# Why this test exists: the by-path exception in lefthook.yml is PERMANENT, and
# its original justification was a human reading the file once. A one-time read
# defending a permanent path is prompt-only enforcement. The checker replaces
# that read -- and this file is what proves the checker actually refuses, since
# an unenforcing gate looks identical to a passing one.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
CHECK="$ROOT/q-system/.q-system/scripts/receipts-ledger-check.py"
LEDGER=".prd-os/receipts.jsonl"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

WORK="$(mktemp -d)"
mkdir -p "$WORK/.prd-os"
cd "$WORK"
git init -q .
git config user.email t@t.t
git config user.name t

stage() { printf '%s\n' "$1" > "$LEDGER"; git add -f "$LEDGER" >/dev/null 2>&1; }
allows() { python3 "$CHECK" >/dev/null 2>&1; }

VALID='{"issue_id":"fcu-dry-run-final-state","prd_id":"prd-fail-closed-fleet-updater","finding_id":"finding-3","closed_at":"2026-07-26T00:00:00Z","commit_sha":"deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"}'

# --- the real producer's output must pass ----------------------------------
stage "$VALID"
allows || fail "a well-formed receipt was refused (false positive)"
ok "a well-formed receipt passes"

NESTED='{"issue_id":"x","prd_id":"p","finding_id":"finding-1","closed_at":"2026-07-26T00:00:00Z","receipts":{"findings_triaged":"2026-05-14T16:19:13Z","reviewed":"2026-05-14T16:19:13Z","verified":"2026-05-14T16:19:13Z"}}'
stage "$NESTED"
allows || fail "the nested receipts shape was refused"
ok "the nested receipts shape passes"

# --- and the real committed ledger must pass, or the gate is unshippable ---
if [ -f "$ROOT/$LEDGER" ]; then
  cp "$ROOT/$LEDGER" "$LEDGER"
  git add -f "$LEDGER" >/dev/null 2>&1
  allows || fail "the repo's REAL ledger fails its own gate; the gate cannot ship"
  ok "the repo's real committed ledger passes"
fi

# --- negative self-test: what must never reach a public repo ---------------
# A gate is judged by what it refuses. Each of these is a shape that would put
# identifying content into a public repo through the one exempted path.
i=0
while IFS='|' read -r label payload; do
  [ -n "$label" ] || continue
  stage "$payload"
  if allows; then fail "LEAKED THROUGH: $label -- $payload"; fi
  i=$((i + 1))
done <<'CASES'
free-text field|{"issue_id":"x","notes":"call Acme Corp about pricing"}
a home path as an id|{"issue_id":"/Users/someone/projects/consulting","closed_at":"2026-07-26T00:00:00Z"}
an email address|{"issue_id":"a","prd_id":"contact@example.com"}
whitespace inside an id|{"issue_id":"Acme Corp deal","closed_at":"2026-07-26T00:00:00Z"}
an unknown key|{"issue_id":"x","client_name":"acme"}
an unknown nested receipts key|{"issue_id":"x","receipts":{"invoiced":"2026-01-01T00:00:00Z"}}
a non-ISO timestamp|{"issue_id":"x","closed_at":"last Tuesday"}
a non-hex commit sha|{"issue_id":"x","commit_sha":"not-a-sha-at-all"}
a non-string value|{"issue_id":"x","closed_at":12345}
a JSON array instead of an object|["issue_id","x"]
a merge conflict marker|<<<<<<< HEAD
an over-long value|{"issue_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
CASES
ok "$i leak shapes all blocked"

# --- the gate is a no-op when the ledger is not in the commit --------------
git rm -q --cached "$LEDGER" >/dev/null 2>&1 || true
printf 'unrelated\n' > other.txt
git add other.txt
allows || fail "the gate fired on a commit that does not touch the ledger"
ok "the gate is a no-op when the ledger is not staged"

echo "PASS: receipts-ledger-check ($PASS checks)"
