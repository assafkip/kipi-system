#!/usr/bin/env bash
# Pairs with: instance-registry.json (the two rows ASK-842 decided) and
# repo-preflight.sh check 0 (reversed by RULE-2026-10-30-A, see section 3).
#
# WHY A TEST FOR A DECISION
# -------------------------
# ASK-842 decided that `cole-gtm` (registry name `gtm-partner`) and
# `reddit-build-radar` stay OFF for unattended dispatch, and that the 4 issues on
# those surfaces get worked as supervised founder-initiated runs instead.
#
# "Leave them off" is not a thing a repo can be left in. repo-preflight.sh states
# the reason at its own check 0: `dispatch.enabled` ABSENT is a DEFAULT, and a
# default is not a refusal -- it records that nobody switched the repo on yet, and
# it evaporates the moment anyone writes `true`. A decision stored as an absence is
# indistinguishable from a decision never taken, so the next reader of the bucket
# re-derives it from scratch, which is the specific waste ASK-842 exists to end.
#
# So the decision is stored as an explicit `enabled: false` carrying its issue id,
# and this file is what makes that storage load-bearing rather than a comment: a
# later flip to `true` turns this red and has to argue with the recorded reason.
#
# THE FLIP IS NOT FORBIDDEN, IT IS MADE VISIBLE. This is a ratchet on the WRITE,
# not a veto. Whoever enables one of these rows edits the decision record in the
# same change (decisions.md RULE-016) and updates the expectation here. That is one
# extra minute for a deliberate change and a red suite for an accidental one.
#
# NEVER A LIVE DATA PATH. This reads the registry and shells the preflight against
# a mktemp fixture. It dispatches nothing, enters no repo, and makes no network
# call: each fixture carries the .kipi-no-dispatch kill switch, which preflight
# checks right after check 0 and before every network-touching check.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Derived from the SCRIPT, never from $PWD: a test that asks whatever checkout it
# happens to run in proves nothing about the caller (test-dispatch-stale-checkout
# learned this first, test-repo-preflight repeats it).
REPO="$(cd "$HERE" && git rev-parse --show-toplevel)"
# $1 overrides the registry under test. That exists for ONE reason: to run this
# suite against a deliberately mutated copy and watch it go red, because a guard
# nobody has seen fail is decoration. The mutation that matters is flipping either
# decided row to `enabled: true` -- see the header. Default is the real registry.
REGISTRY="${1:-${KIPI_ASK842_REGISTRY:-$REPO/instance-registry.json}}"
PREFLIGHT="$REPO/q-system/.q-system/scripts/repo-preflight.sh"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

echo "== ASK-842: the recorded dispatch decision for cole-gtm and reddit-build-radar =="

# --- 1. the decision exists, in the registry, as a value and not as an absence ---
# Checked per row so a failure names WHICH row regressed. `enabled` must be the
# JSON boolean false, not the string "false" and not a missing key -- the same
# strictness the dispatcher applies on the true side (`is not True`).
for ROW in gtm-partner reddit-build-radar; do
  OUT="$(REG="$REGISTRY" ROW="$ROW" python3 - <<'PY' 2>&1
import json, os
reg, want = os.environ["REG"], os.environ["ROW"]
rows = [e for e in json.load(open(reg)).get("instances", []) if e.get("name") == want]
if len(rows) != 1:
    print("ROWCOUNT:%d" % len(rows)); raise SystemExit(0)
d = rows[0].get("dispatch")
if not isinstance(d, dict):
    print("NODISPATCH"); raise SystemExit(0)
if d.get("enabled") is not False:
    print("NOTFALSE:%r" % (d.get("enabled"),)); raise SystemExit(0)
if "ASK-842" not in str(d.get("decision", "")):
    print("NODECISIONREF:%r" % (d.get("decision"),)); raise SystemExit(0)
if len(str(d.get("reason", ""))) < 40:
    print("NOREASON:%r" % (d.get("reason"),)); raise SystemExit(0)
print("OK")
PY
)"
  case "$OUT" in
    OK) ok "$ROW carries dispatch.enabled=false with the ASK-842 decision and its reason" ;;
    *)  bad "$ROW does not carry the recorded decision ($OUT)" ;;
  esac
done

# --- 2. the decision agrees with what the dispatcher actually does --------------
# Rule 1 asserts the RECORD. This asserts the EFFECT, read with the dispatcher's
# own predicate from fleet_candidates() in kipi-dispatch.sh. Two sides deriving one
# answer from different sources is how a record drifts into decoration: a row could
# say `enabled: false` while some later reader keyed off a different field.
OUT="$(REG="$REGISTRY" python3 - <<'PY' 2>&1
import json, os
enabled = []
for e in json.load(open(os.environ["REG"])).get("instances", []):
    d = e.get("dispatch")
    if isinstance(d, dict) and d.get("enabled") is True:
        enabled.append(e.get("path", ""))
leaked = [p for p in enabled if p.rstrip("/").endswith("/cole-gtm")
          or "/cole-gtm/projects/reddit-build-radar" in p]
print("LEAKED:" + ",".join(leaked) if leaked else "OK")
PY
)"
case "$OUT" in
  OK) ok "neither decided path is emitted as a dispatch candidate" ;;
  *)  bad "a decided-off path is dispatchable ($OUT)" ;;
esac

# --- 3. check 0 refuses NOTHING now (RULE-2026-10-30-A) -----------------------
# ASK-842's DoR forbade softening the client-repo refusal, and this section
# asserted it held. The founder reversed it, 2026-10-30, verbatim: "The unattended
# agent should and can reach client repos to work on the tickets. That's the
# ruling from now on." So no path shape earns a client-repo refusal, the
# engagement root included. The two ASK-842 rows above stay off for a different,
# measured reason: neither path exists on disk (checked 2026-10-30), so there is
# no checkout to enter.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
for SUB in consulting/projects/some_client consulting persona/projects/own_thing; do
  mkdir -p "$TMP/$SUB"
  : > "$TMP/$SUB/.kipi-no-dispatch"
done

for SUB in consulting/projects/some_client consulting persona/projects/own_thing; do
  OUT="$(bash "$PREFLIGHT" "$TMP/$SUB" "" 2>&1)"
  case "$OUT" in
    *"FAIL client-repo:"*) bad "check 0 still refuses $SUB as a client path, against RULE-2026-10-30-A" ;;
    *"FAIL kill-switch:"*) ok "no client-repo refusal for $SUB (it reached the kill switch)" ;;
    *)                     bad "unexpected preflight output for $SUB: $OUT" ;;
  esac
done

echo "-- $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
