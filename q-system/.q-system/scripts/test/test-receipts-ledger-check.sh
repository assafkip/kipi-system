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

# --- ASK-1814: the prd_id prd_split.py --from-linear writes, and close copies ---
LINEAR='{"issue_id":"ASK-1808","prd_id":"linear:ASK-1808","finding_id":"linear-dor","closed_at":"2026-09-19T00:01:20Z","commit_sha":"3ff7154ab315eeecf864428f03ec01d474251cc5"}'
stage "$LINEAR"
allows || fail "a Linear-split issue's receipt was refused (prd_id linear:ASK-n)"
ok "a Linear-split receipt passes"

# --- ASK-1968: finding_class, copied at close from the finding it closes ---
CLASSED='{"issue_id":"x","prd_id":"p","finding_id":"finding-1","closed_at":"2026-07-26T00:00:00Z","finding_class":"wiring"}'
stage "$CLASSED"
allows || fail "a receipt carrying a listed finding_class was refused"
ok "a receipt with finding_class=wiring passes"

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
linear: with free text after it|{"issue_id":"x","prd_id":"linear:call-acme-about-pricing"}
linear: with a lowercase key|{"issue_id":"x","prd_id":"linear:ask-1"}
linear: with no key|{"issue_id":"x","prd_id":"linear:-1"}
linear: with no number|{"issue_id":"x","prd_id":"linear:ASK-"}
linear: form on a key other than prd_id|{"issue_id":"linear:ASK-1","prd_id":"p"}
a different scheme|{"issue_id":"x","prd_id":"jira:ASK-1"}
linear: with a trailing suffix|{"issue_id":"x","prd_id":"linear:ASK-1-acme"}
linear: with a team key longer than the producer allows|{"issue_id":"x","prd_id":"linear:ACMECORPPRICINGDEAL-1"}
a Linear URL instead of the id|{"issue_id":"x","prd_id":"https://linear.app/ask-consulting/issue/ASK-1"}
finding_class as free text|{"issue_id":"x","finding_class":"some free text"}
finding_class off the fixed list|{"issue_id":"x","finding_class":"bogus"}
an over-long value|{"issue_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
CASES
ok "$i leak shapes all blocked"

# --- ASK-3829: receipt fragments, one new file per close ----------------------
# Every close now writes its receipt as a fragment (GitHub ignores merge=union, so
# parallel closes conflicted on the one ledger). Same public repo, same content rule,
# and lefthook's blocked-paths admits exactly the name the writer gives.
git rm -q --cached "$LEDGER" >/dev/null 2>&1 || true
rm -f "$LEDGER"
FRAGS=".prd-os/receipts.d"
# Through the real chokepoint, so a writer/gate drift on the name fails here.
frag_write() {
  python3 - "$ROOT/plugins/prd-os/scripts" "$1" "${2:-receipt}" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import ledger_fragments
print(ledger_fragments.append_line(".prd-os/receipts.jsonl", sys.argv[2], kind=sys.argv[3]))
PY
}
# Raw bytes under a writer-shaped name; the name hash is of the bytes unless $2 overrides it.
frag_raw() {
  python3 - "$1" "${2:-}" <<'PY'
import hashlib, pathlib, sys
data = sys.argv[1].encode().decode("unicode_escape").encode()
sha = sys.argv[2] or hashlib.sha256(data).hexdigest()[:16]
p = pathlib.Path(".prd-os/receipts.d") / f"20261106T000000000000Z-receipt-{sha}.jsonl"
p.parent.mkdir(parents=True, exist_ok=True)
p.write_bytes(data)
print(p)
PY
}
unstage_frags() { git rm -r -q --cached "$FRAGS" >/dev/null 2>&1 || true; rm -f "$FRAGS"/*.jsonl; }
BLOCKED_LINE="$(grep -E '^[[:space:]]+blocked=\$\(git diff --cached' "$ROOT/lefthook.yml" | sed 's/^[[:space:]]*//')"
[ -n "$BLOCKED_LINE" ] || fail "could not find lefthook.yml's blocked-paths line to test"
blocked_by_lefthook() { local blocked; eval "$BLOCKED_LINE"; [ -n "$blocked" ]; }

F="$(frag_write "$VALID")"
git add -f "$F"
allows || fail "a well-formed receipt fragment from the real writer was refused"
ok "a well-formed receipt fragment passes"
blocked_by_lefthook && fail "lefthook blocked-paths refused the writer's own fragment name: $F"
ok "lefthook blocked-paths admits the writer's fragment name"
unstage_frags

mkdir -p "$FRAGS"; printf '%s\n' "$VALID" > "$FRAGS/notes.jsonl"; git add -f "$FRAGS/notes.jsonl"
blocked_by_lefthook || fail "lefthook blocked-paths admitted a hand-named .jsonl under receipts.d"
allows && fail "the gate admitted a hand-named fragment"
ok "a hand-named fragment is refused by both lefthook and the gate"
unstage_frags

mkdir -p "$FRAGS/nested"
printf '%s\n' "$VALID" > "$FRAGS/nested/20261106T000000000000Z-receipt-0123456789abcdef.jsonl"
git add -f "$FRAGS/nested"
blocked_by_lefthook || fail "lefthook blocked-paths admitted a nested path under receipts.d"
allows && fail "the gate admitted a nested fragment path"
git rm -r -q --cached "$FRAGS/nested" >/dev/null 2>&1
rm -f "$FRAGS"/nested/*.jsonl
rmdir "$FRAGS/nested"
ok "a nested fragment path is refused by both"

while IFS='|' read -r label payload hash; do
  [ -n "$label" ] || continue
  F="$(frag_raw "$payload" "$hash")"; git add -f "$F"
  if allows; then fail "FRAGMENT LEAKED THROUGH: $label"; fi
  unstage_frags
done <<CASES
two records in one fragment|$VALID\n$VALID\n|
an empty fragment||
free text in a fragment|{"issue_id":"x","notes":"call Acme Corp about pricing"}\n|
a name hash that does not match the bytes|$VALID\n|0123456789abcdef
CASES
ok "fragment shapes refused: two records, empty, free text, edited bytes"

F="$(frag_write '{"issue_id":"x","notes":"call Acme Corp about pricing"}')"; git add -f "$F"
allows && fail "a free-text receipt written through the real writer passed the gate"
unstage_frags
F="$(frag_write "$VALID" gate)"; git add -f "$F"
allows && fail "a gate row filed under receipts.d passed the gate"
unstage_frags
ok "the gate refuses what the writer would accept but the ledger must not hold"

F="$(frag_write "$VALID")"; git add -f "$F"; git commit -q -m "one receipt" >/dev/null
printf '%s\n' '{"issue_id":"y","closed_at":"2026-07-26T00:00:00Z"}' > "$F"; git add -f "$F"
allows && fail "an edited (already committed) fragment passed the gate"
git reset -q HEAD -- "$F"
git checkout -q -- "$F"
ok "a committed fragment cannot be edited in a later commit"
# A rename keeps the bytes and the hash, so only write-once catches it, and it would
# move the receipt in the fold order (the timestamp is the sort key).
MOVED="$FRAGS/19990101T000000000000Z-receipt-${F##*-receipt-}"
git mv "$F" "$MOVED"
allows && fail "a renamed (re-timestamped) fragment passed the gate"
git mv "$MOVED" "$F"
ok "a committed fragment cannot be renamed to another valid name"

# --- the gate is a no-op when the ledger is not in the commit --------------
git rm -q --cached "$LEDGER" >/dev/null 2>&1 || true
printf 'unrelated\n' > other.txt
git add other.txt
allows || fail "the gate fired on a commit that does not touch the ledger"
ok "the gate is a no-op when the ledger is not staged"

echo "PASS: receipts-ledger-check ($PASS checks)"
