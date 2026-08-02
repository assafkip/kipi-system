#!/usr/bin/env bash
# Pairs with q-system/.q-system/scripts/scheduling-claim-gate.py (ASK-292).
#
# The gate's own --self-test covers evaluate(). It CANNOT cover the hook contract:
# stdin shape, transcript parsing, and the exit code Claude Code actually reads. A
# gate whose evaluate() is perfect and whose exit code is 0 is a gate that never
# blocks anything, and this repo has shipped exactly that (a checklist "wired" into
# an instance ran from the marketplace clone and sat inert for weeks). So the
# contract is exercised here, through real stdin, with synthetic transcripts.
#
# HERMETIC: the transcripts are built in a temp dir. No live session transcript is
# read; the fable-discipline lint blocks a test that touches a live data path, and
# a real transcript is one.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE="$SCRIPT_DIR/../scheduling-claim-gate.py"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf 'PASS: %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf 'FAIL: %s\n' "$1"; }

[ -f "$GATE" ] || { echo "FAIL: $GATE missing"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- 1. the decision layer, via the script's own suite ----------------------
OUT="$(python3 "$GATE" --self-test 2>&1)"; RC=$?
[ "$RC" -eq 0 ] && ok "gate --self-test passes" || { bad "gate --self-test rc=$RC"; echo "$OUT"; }
printf '%s\n' "$OUT" | grep -q 'NEGATIVE' \
  && ok "the suite contains a negative case" \
  || bad "no negative case: a suite that cannot fail is not a suite"

# --- 2. build synthetic transcripts (producer-shaped rows) ------------------
# The row shape is the one code_claim_grounding_guard.py already parses from real
# Claude Code transcripts: {"message":{"role","content":[{type,...}]}} per line.
build() { # build <file> <python-list-expr>
  python3 - "$1" "$2" <<'PY'
import json, sys
rows = eval(sys.argv[2])          # test fixture, literal list built below
open(sys.argv[1], "w", encoding="utf-8").write(
    "\n".join(json.dumps({"message": r}) for r in rows))
PY
}
CLAIM='ASK-291 is queued and the loop will pick it up on the next run.'

build "$TMP/claim_nocheck.jsonl" "[
 {'role':'assistant','content':[{'type':'tool_use','input':{'command':'git status'}}]},
 {'role':'user','content':[{'type':'tool_result','content':'On branch main'}]},
 {'role':'assistant','content':[{'type':'text','text':'$CLAIM'}]}]"

build "$TMP/no_claim.jsonl" "[
 {'role':'assistant','content':[{'type':'tool_use','input':{'command':'ls'}}]},
 {'role':'assistant','content':[{'type':'text','text':'Read it. It does what you said.'}]}]"

build "$TMP/claim_checked.jsonl" "[
 {'role':'assistant','content':[{'type':'tool_use','input':{'command':'python3 will-it-run.py ASK-287'}}]},
 {'role':'user','content':[{'type':'tool_result','content':'ASK-287: TODAY'}]},
 {'role':'assistant','content':[{'type':'text','text':'ASK-287 is queued for today.'}]}]"

build "$TMP/contradiction.jsonl" "[
 {'role':'assistant','content':[{'type':'tool_use','input':{'command':'python3 will-it-run.py ASK-291'}}]},
 {'role':'user','content':[{'type':'tool_result','content':'ASK-291: NEVER'}]},
 {'role':'assistant','content':[{'type':'text','text':'ASK-291 is queued, the dispatcher will run it tonight.'}]}]"

build "$TMP/prose_only.jsonl" "[
 {'role':'assistant','content':[{'type':'tool_use','input':{'command':'ls'}}]},
 {'role':'assistant','content':[{'type':'text','text':'I ran will-it-run.py. ASK-291 is queued.'}]}]"

run_gate() { # run_gate <transcript> -> echoes rc
  printf '{"transcript_path":"%s","stop_hook_active":false}' "$1" \
    | python3 "$GATE" >/dev/null 2>"$TMP/err"
  echo $?
}
case_rc() { # case_rc <name> <transcript> <want>
  local got; got="$(run_gate "$2")"
  [ "$got" = "$3" ] && ok "$1" || bad "$1 (want rc=$3, got rc=$got)"
}

# --- 3. THE HOOK CONTRACT, through real stdin -------------------------------
case_rc "claim + no checker run -> exit 2 (BLOCK)"      "$TMP/claim_nocheck.jsonl"  2
case_rc "no claim at all -> exit 0 (ALLOW)"             "$TMP/no_claim.jsonl"       0
case_rc "claim + checker agreed -> exit 0"              "$TMP/claim_checked.jsonl"  0
case_rc "claim contradicting the checker -> exit 2"     "$TMP/contradiction.jsonl"  2
case_rc "naming the checker in PROSE only -> exit 2"    "$TMP/prose_only.jsonl"     2

# The blocked turn must TEACH, not just fail: the stderr is what Claude reads back.
run_gate "$TMP/claim_nocheck.jsonl" >/dev/null
grep -q 'will-it-run.py' "$TMP/err" \
  && ok "the block names the command to run" \
  || bad "block message does not name the fix"

# --- 4. degenerate inputs must never block a turn ---------------------------
[ "$(printf '{}' | python3 "$GATE" >/dev/null 2>&1; echo $?)" = "0" ] \
  && ok "empty payload passes (a broken hook must not wedge the session)" \
  || bad "empty payload did not pass"
[ "$(printf 'not json' | python3 "$GATE" >/dev/null 2>&1; echo $?)" = "0" ] \
  && ok "malformed stdin passes" || bad "malformed stdin did not pass"
printf '{"transcript_path":"%s/nope.jsonl","stop_hook_active":false}' "$TMP" \
  | python3 "$GATE" >/dev/null 2>&1
[ "$?" = "0" ] && ok "missing transcript passes" || bad "missing transcript blocked"
printf '{"transcript_path":"%s","stop_hook_active":true}' "$TMP/claim_nocheck.jsonl" \
  | python3 "$GATE" >/dev/null 2>&1
[ "$?" = "0" ] && ok "stop_hook_active short-circuits (no block loop)" \
  || bad "stop_hook_active did not short-circuit: risk of a block loop"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
