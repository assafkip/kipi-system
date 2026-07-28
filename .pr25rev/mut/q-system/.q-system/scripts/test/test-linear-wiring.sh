#!/usr/bin/env bash
# Wiring suite for the Linear capture path (ASK-113).
#
# Proves the two founder-facing entry points actually reach linear-queue.py:
#   goal 2  `kipi linear issue "..."`  - issue-first fast path, fully end-to-end here
#   goal 3  `kipi new`                 - queues a Linear project for a new instance
#
# SCOPE LIMIT, stated rather than hidden: case 4 runs the exact invocation
# kipi-new-instance.sh uses and pins that the call site exists, but it does NOT run
# kipi-new-instance.sh itself. That script writes to the real
# instance-registry.json via a hardcoded REGISTRY="$SCRIPT_DIR/..." and would
# register a junk instance in the skeleton. Making it fully testable needs a
# REGISTRY override; captured as spillover rather than bodged here.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0
ok() { echo "  PASS: $1"; pass=$((pass + 1)); }
no() { echo "  FAIL: $1 -- $2"; fail=$((fail + 1)); }

QUEUE="$ROOT/q-system/.q-system/scripts/linear-queue.py"
pending_count() {
  python3 "$QUEUE" pending --json 2>/dev/null \
    | python3 -c "import json,sys;print(len(json.load(sys.stdin)))" 2>/dev/null
}

echo "=== linear wiring ==="

# -- Case 1: kipi linear issue -> a real pending item (goal 2, end to end) ----
export KIPI_LINEAR_QUEUE="$TMP/q1.jsonl"
"$ROOT/kipi" linear issue "Wire up the thing" >/dev/null 2>&1
rc=$?
[ "$rc" -eq 0 ] && ok "kipi linear issue exits 0" || no "kipi linear issue exits 0" "got $rc"
[ "$(pending_count)" = "1" ] && ok "kipi linear issue queues one item" || no "kipi linear issue queues one item" "got $(pending_count)"

# -- Case 2: it is an ISSUE, keyed to the repo you are standing in ------------
kind=$(python3 "$QUEUE" pending --json | python3 -c "import json,sys;print(json.load(sys.stdin)[0]['kind'])" 2>/dev/null)
[ "$kind" = "issue" ] && ok "queued kind is issue" || no "queued kind is issue" "got '$kind'"
key=$(python3 "$QUEUE" pending --json | python3 -c "import json,sys;print(json.load(sys.stdin)[0]['key'])" 2>/dev/null)
case "$key" in
  */wire-up-the-thing) ok "key derives from the title ($key)" ;;
  *) no "key derives from the title" "got '$key'" ;;
esac

# -- Case 3: the read-only subcommands do not blow up -------------------------
"$ROOT/kipi" linear pending >/dev/null 2>&1 && ok "kipi linear pending exits 0" || no "kipi linear pending exits 0" "non-zero"
"$ROOT/kipi" linear status  >/dev/null 2>&1 && ok "kipi linear status exits 0"  || no "kipi linear status exits 0" "non-zero"
"$ROOT/kipi" linear bogus   >/dev/null 2>&1 && no "unknown subcommand is refused" "exited 0" || ok "unknown subcommand is refused"

# -- Case 4: kipi new's project capture (goal 3) ------------------------------
grep -q "linear-queue.py" "$ROOT/kipi-new-instance.sh" \
  && ok "kipi-new-instance.sh has the capture call site" \
  || no "kipi-new-instance.sh has the capture call site" "no reference found"

export KIPI_LINEAR_QUEUE="$TMP/q2.jsonl"
python3 "$QUEUE" add --repo "brand_new_instance" --kind project \
  --title "brand_new_instance" --note "Auto-queued by kipi new." --source kipi-new >/dev/null 2>&1
rc=$?
[ "$rc" -eq 0 ] && ok "the kipi-new invocation shape is valid (exit 0)" || no "kipi-new invocation shape" "got $rc"
k2=$(python3 "$QUEUE" pending --json | python3 -c "import json,sys;print(json.load(sys.stdin)[0]['kind'])" 2>/dev/null)
[ "$k2" = "project" ] && ok "kipi new queues a PROJECT" || no "kipi new queues a PROJECT" "got '$k2'"

# -- Case 5: a second kipi new on the same repo does NOT queue a second project
# Linear projects cannot be deleted by an agent, so this must be idempotent.
python3 "$QUEUE" add --repo "brand_new_instance" --kind project \
  --title "brand_new_instance" --source kipi-new >/dev/null 2>&1
[ "$(pending_count)" = "1" ] && ok "repeat kipi new does not double-queue the project" \
  || no "repeat kipi new does not double-queue" "got $(pending_count)"

# -- Case 6: the drain command is discoverable --------------------------------
[ -f "$ROOT/plugins/kipi-core/commands/linear-drain.md" ] \
  && ok "/linear-drain command file exists" || no "/linear-drain command file exists" "missing"
grep -q "kipi-key" "$ROOT/plugins/kipi-core/commands/linear-drain.md" \
  && ok "/linear-drain tells the agent to preserve the dedup marker" \
  || no "/linear-drain preserves the marker" "no kipi-key instruction"

echo
echo "  pass=$pass fail=$fail"
[ "$fail" -eq 0 ] || exit 1
