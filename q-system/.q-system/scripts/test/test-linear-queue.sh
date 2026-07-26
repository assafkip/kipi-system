#!/usr/bin/env bash
# Reproducer + regression suite for linear-queue.py (the capture half of the
# queue/drain split). Pairs with .claude/rules/linear-first.md.
#
# WHY (ASK-113): there is no Linear API key in ~/.config/kipi/, so a bash script
# such as kipi-new-instance.sh cannot reach the Linear MCP server. Capture must
# therefore be a local append that CANNOT fail on a network problem, and the
# Linear write happens later, agent-side, where credentials exist.
#
# Test isolation: every case runs against $TMP via KIPI_LINEAR_QUEUE. The live
# queue at <repo-root>/.linear-queue.jsonl is never opened by this suite.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
Q="$SCRIPT_DIR/../linear-queue.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export KIPI_LINEAR_QUEUE="$TMP/queue.jsonl"

pass=0
fail=0
ok() { echo "  PASS: $1"; pass=$((pass + 1)); }
no() { echo "  FAIL: $1 -- $2"; fail=$((fail + 1)); }

pending_count() { python3 "$Q" pending --json 2>/dev/null | python3 -c "import json,sys;print(len(json.load(sys.stdin)))" 2>/dev/null; }

echo "=== linear-queue capture ==="

# -- Case 1: capture works with no network and no credentials ------------------
python3 "$Q" add --repo demo --kind issue --title "Add case intake" >/dev/null 2>&1
rc=$?
[ "$rc" -eq 0 ] && ok "add exits 0" || no "add exits 0" "got $rc"
[ -f "$KIPI_LINEAR_QUEUE" ] && ok "add creates the queue file" || no "add creates the queue file" "missing"
[ "$(pending_count)" = "1" ] && ok "one pending item" || no "one pending item" "got $(pending_count)"

# -- Case 2: capture NEVER fails hard, even on a garbage-adjacent environment --
# A capture that exits non-zero would block a founder's `kipi new`. It must not.
KIPI_LINEAR_QUEUE="$TMP/nested/deep/queue.jsonl" python3 "$Q" add --repo demo2 --kind project --title "demo2" >/dev/null 2>&1
[ "$?" -eq 0 ] && ok "add creates missing parent dirs rather than failing" || no "add survives missing dirs" "non-zero exit"

# -- Case 3: the same key is not captured twice while still pending -----------
python3 "$Q" add --repo demo --kind issue --title "Add case intake" >/dev/null 2>&1
[ "$(pending_count)" = "1" ] && ok "duplicate capture is idempotent" || no "duplicate capture is idempotent" "got $(pending_count)"

# -- Case 4: a distinct title is a distinct item ------------------------------
python3 "$Q" add --repo demo --kind issue --title "Add slack notify" >/dev/null 2>&1
[ "$(pending_count)" = "2" ] && ok "distinct title queues separately" || no "distinct title queues separately" "got $(pending_count)"

# -- Case 5: THE CORE CASE. Draining removes it from pending, append-only -----
before_lines=$(wc -l < "$KIPI_LINEAR_QUEUE" | tr -d ' ')
key=$(python3 "$Q" pending --json | python3 -c "import json,sys;print(json.load(sys.stdin)[0]['key'])")
python3 "$Q" mark-drained --key "$key" --identifier "ASK-900" >/dev/null 2>&1
[ "$(pending_count)" = "1" ] && ok "drained item leaves pending" || no "drained item leaves pending" "got $(pending_count)"
after_lines=$(wc -l < "$KIPI_LINEAR_QUEUE" | tr -d ' ')
[ "$after_lines" -gt "$before_lines" ] && ok "drain APPENDS, never rewrites ($before_lines -> $after_lines)" \
  || no "drain appends" "$before_lines -> $after_lines"

# -- Case 6: re-capturing a drained key does NOT resurrect it -----------------
# Otherwise a re-run of kipi-new-instance.sh would create a second Linear project,
# and Linear projects cannot be deleted by an agent.
python3 "$Q" add --repo demo --kind issue --title "Add case intake" >/dev/null 2>&1
[ "$(pending_count)" = "1" ] && ok "re-capture of a drained key is a no-op" || no "re-capture of a drained key is a no-op" "got $(pending_count)"

# -- Case 7: drain is idempotent ----------------------------------------------
python3 "$Q" mark-drained --key "$key" --identifier "ASK-900" >/dev/null 2>&1
[ "$(pending_count)" = "1" ] && ok "double-drain is a no-op" || no "double-drain is a no-op" "got $(pending_count)"

# -- Case 8: a corrupt line does not take the whole queue down ----------------
printf 'this is not json\n' >> "$KIPI_LINEAR_QUEUE"
python3 "$Q" pending --json >/dev/null 2>&1
[ "$?" -eq 0 ] && ok "corrupt line is skipped, not fatal" || no "corrupt line is skipped" "non-zero exit"
[ "$(pending_count)" = "1" ] && ok "corrupt line does not change pending" || no "corrupt line does not change pending" "got $(pending_count)"

# -- Case 9: the key is the same one linear-sync.py computes ------------------
# If these two disagree, the drain creates duplicates of things the sync already
# knows about. One shared derivation, pinned at both ends.
qk=$(python3 "$Q" key --repo "4_points_consulting" --title "Case Intake" 2>/dev/null)
sk=$(python3 "$SCRIPT_DIR/../linear-sync.py" key --repo "4_points_consulting" --capability "Case Intake" 2>/dev/null)
[ -n "$qk" ] && [ "$qk" = "$sk" ] && ok "queue and sync agree on the key ($qk)" \
  || no "queue and sync agree on the key" "queue='$qk' sync='$sk'"

echo
echo "  pass=$pass fail=$fail"
[ "$fail" -eq 0 ] || exit 1
