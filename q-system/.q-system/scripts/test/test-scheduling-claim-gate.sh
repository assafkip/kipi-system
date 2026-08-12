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

# SINGLE-quoted, so `\n` (one backslash) is what reaches the Python literal and
# becomes a real newline there. `\\n` would survive as a literal backslash-n and
# the verdict line would never start a line -- invisible to VERDICT_RE's `^`.
ANSWER='OBSERVED 2026-08-02T11:32:16  lane=production  cap=3  spent=2  budget_day=2026-08-02\nASK-287: TODAY'
build "$TMP/claim_checked.jsonl" "[
 {'role':'assistant','content':[{'type':'tool_use','input':{'command':'python3 will-it-run.py ASK-287'}}]},
 {'role':'user','content':[{'type':'tool_result','content':'$ANSWER'}]},
 {'role':'assistant','content':[{'type':'text','text':'ASK-287 is queued for today.'}]}]"

build "$TMP/contradiction.jsonl" "[
 {'role':'assistant','content':[{'type':'tool_use','input':{'command':'python3 will-it-run.py ASK-291'}}]},
 {'role':'user','content':[{'type':'tool_result','content':'OBSERVED 2026-08-02T11:32:16  lane=production  cap=3  spent=3  budget_day=2026-08-02\\nASK-291: NEVER'}]},
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

# codex round 1, major 2: an `ls` that merely LISTS the filename must not arm the
# gate. Artifact presence accepted as proof of behaviour is the substitution this
# whole PR exists to stop, and the gate committed it.
build "$TMP/ls_only.jsonl" "[
 {'role':'assistant','content':[{'type':'tool_use','input':{'command':'ls q-system/.q-system/scripts'}}]},
 {'role':'user','content':[{'type':'tool_result','content':'linear_pick.py\\nwill-it-run.py\\ncapability-gate.py'}]},
 {'role':'assistant','content':[{'type':'text','text':'ASK-291 is queued and the loop will pick it up on the next run.'}]}]"
case_rc "an ls listing the filename does NOT arm the gate" "$TMP/ls_only.jsonl"       2

# codex round 2, major 1: evidence is PER ISSUE. A rendered answer about ASK-287
# says nothing about ASK-291 -- pickability, project and pool position differ per
# issue, which is why one run printed TODAY and NEVER on the same day.
build "$TMP/other_issue.jsonl" "[
 {'role':'assistant','content':[{'type':'tool_use','input':{'command':'python3 will-it-run.py ASK-287'}}]},
 {'role':'user','content':[{'type':'tool_result','content':'$ANSWER'}]},
 {'role':'assistant','content':[{'type':'text','text':'ASK-291 is queued and goes out today.'}]}]"
case_rc "an answer about ASK-287 does NOT back a claim about ASK-291" "$TMP/other_issue.jsonl" 2
run_gate "$TMP/other_issue.jsonl" >/dev/null
grep -q 'ASK-291' "$TMP/err" \
  && ok "the block names the issue the checker never covered" \
  || bad "block message does not name the unanswered issue"

# codex round 2, major 2: a wiring FILENAME is not an opened wiring surface. The
# grep below merely SEARCHES for settings.json; nothing was read.
build "$TMP/wiring_name_only.jsonl" "[
 {'role':'assistant','content':[{'type':'tool_use','input':{'pattern':'scheduling-claim-gate','path':'.claude/settings.json'}}]},
 {'role':'user','content':[{'type':'tool_result','content':'.claude/settings.json'}]},
 {'role':'assistant','content':[{'type':'text','text':'The Stop hook is now wired and the gate is enforced.'}]}]"
case_rc "naming a wiring surface without opening it -> exit 2" "$TMP/wiring_name_only.jsonl" 2

# ...and the real registration body DOES satisfy it. Split so this fixture file
# cannot itself become a universal arming key when read.
BODY='{\"hoo'
BODY="$BODY"'ks\": {\"St'
BODY="$BODY"'op\": [{\"ty'
BODY="$BODY"'pe\": \"command\", \"command\": \"scheduling-claim-gate.py\"}]}}'
build "$TMP/wiring_body.jsonl" "[
 {'role':'assistant','content':[{'type':'tool_use','input':{'file_path':'.claude/settings.json'}}]},
 {'role':'user','content':[{'type':'tool_result','content':'$BODY'}]},
 {'role':'assistant','content':[{'type':'text','text':'The Stop hook is now wired in settings.json.'}]}]"
case_rc "reading the real hook registration -> exit 0" "$TMP/wiring_body.jsonl" 0

# THE SELF-ARMING CASE: reading the gate's own source must not arm a wiring claim.
# Its remedy text names every wiring surface, so under the old substring rule this
# file was a skeleton key to the check it implements.
python3 - "$GATE" "$TMP" <<'PY'
import json, sys
src = open(sys.argv[1], encoding="utf-8").read()
rows = [{"role": "assistant", "content": [{"type": "tool_use", "input": {"file_path": sys.argv[1]}}]},
        {"role": "user", "content": [{"type": "tool_result", "content": src}]},
        {"role": "assistant", "content": [{"type": "text", "text": "The Stop hook is now wired and armed."}]}]
open(sys.argv[2] + "/read_self.jsonl", "w", encoding="utf-8").write(
    "\n".join(json.dumps({"message": r}) for r in rows))
PY
case_rc "reading the gate's OWN source does not arm a wiring claim" "$TMP/read_self.jsonl" 2

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
