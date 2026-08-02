#!/bin/bash
# Pairs with: slack-notify.sh (the founder-notification chokepoint) and
# notify-callsite-audit.py (the static half).
#
# ASK-294. The founder, twice in one session: "why do I keep getting slack
# messages I can't do anything about", then "I don't want to get slack messages
# that are useless to me. they should go to you or sana."
#
# MEASURED BEFORE THE CHANGE: 48 messages reached #general in 24h from 11
# producers, and ZERO consumers read the channel back. Every one terminated at
# the founder by construction.
#
# The contract this suite holds: a message reaches the founder's phone ONLY when
# it names a founder DECISION from a closed allowlist. Everything else is a
# receipt -- recorded to a machine-readable ledger an agent reads, never
# delivered. A closed enum is the point: a producer cannot reword its way into
# the founder's phone, it has to edit the allowlist in a reviewed diff.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$SCRIPTS/../../.." && pwd)"
# BASH_SOURCE-derived, never $PWD: this suite must test the copy it ships beside,
# not whatever checkout happened to be current when someone ran it.
NOTIFY="$SCRIPTS/slack-notify.sh"
AUDIT="$SCRIPTS/notify-callsite-audit.py"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Stub curl by prepending to PATH -- the shipped script takes no "where to post"
# knob, and adding one would be a documented way to aim a real page at /dev/null.
# Same posture kipi-dispatch.sh takes with its preflight path.
mkdir -p "$WORK/bin"
cat > "$WORK/bin/curl" <<'STUB'
#!/bin/bash
# Record the delivery attempt and its payload; never touch the network.
out="$KIPI_TEST_CURL_LOG"
prev=""
for a in "$@"; do
  if [ "$prev" = "--data" ]; then printf '%s\n' "$a" >> "$out"; fi
  prev="$a"
done
exit 0
STUB
chmod +x "$WORK/bin/curl"

# One invocation shape for every case, so a case can never accidentally test a
# different caller than the others.
run_notify() {
  local dir="$1"; shift
  rm -rf "$dir"; mkdir -p "$dir"
  # `-u` BEFORE the assignments: BSD env (macOS) parses options only until the
  # first operand, so `KEY=v -u NAME` reads -u as a utility name and dies 127.
  # That cost three FALSE PASSES on the first run of this suite -- "curl was
  # never called" is true when the script never ran at all, so every
  # not-delivered assertion passed for the wrong reason. Hence assert_ran below.
  env -u KIPI_LINEAR_API_URL \
      PATH="$WORK/bin:$PATH" \
      KIPI_TEST_CURL_LOG="$dir/curl.log" \
      KIPI_SLACK_WEBHOOK="https://hooks.example.invalid/T/B/X" \
      KIPI_NOTIFY_RECEIPTS="$dir/receipts.jsonl" \
      KIPI_INSTANCE_NAME="testinst" \
      bash "$NOTIFY" "$@" >"$dir/out" 2>"$dir/err"   # notify-kind-skip: kind comes from each case
  echo $? > "$dir/rc"
  assert_ran "$dir"
}
# A not-delivered assertion is only meaningful if the sink actually executed.
assert_ran() {
  local rc; rc="$(cat "$1/rc")"
  if [ "$rc" = "127" ] || grep -q '^env: \|No such file or directory' "$1/err" 2>/dev/null; then
    bad "harness: sink actually ran" "rc=$rc err=$(head -2 "$1/err")"
  fi
}
delivered() { [ -s "$1/curl.log" ]; }
recorded()  { [ -s "$1/receipts.jsonl" ]; }
field() { python3 -c "
import json,sys
rows=[json.loads(l) for l in open(sys.argv[1]) if l.strip()]
print(rows[-1].get(sys.argv[2]))" "$1/receipts.jsonl" "$2" 2>/dev/null; }

echo "== ASK-294 founder-notification decision gate =="

# --- 1. a receipt never reaches the phone, but is never lost either -----------
D="$WORK/c1"; run_notify "$D" --kind receipt "converge ASK-289: stopped, no PR after round 4"
if delivered "$D"; then bad "receipt is NOT delivered" "curl was called: $(cat "$D/curl.log")"
else ok "receipt is NOT delivered"; fi
if recorded "$D"; then ok "receipt IS recorded to the machine ledger"
else bad "receipt IS recorded to the machine ledger" "receipts.jsonl empty/missing"; fi
[ "$(field "$D" kind)" = "receipt" ] && ok "receipt row carries kind=receipt" \
  || bad "receipt row carries kind=receipt" "got '$(field "$D" kind)'"
[ "$(field "$D" delivered)" = "False" ] && ok "receipt row records delivered=false" \
  || bad "receipt row records delivered=false" "got '$(field "$D" delivered)'"
[ "$(cat "$D/rc")" = "0" ] && ok "receipt exits 0 (a receipt is not a failure)" \
  || bad "receipt exits 0" "rc=$(cat "$D/rc")"

# --- 1b. THE MESSAGE MUST STAY IN $1 -----------------------------------------
# Not a style preference; it is a fleet compatibility contract. Notify stubs
# across this repo record "$1" (test-dispatch-liveness, test-severity-floor,
# test-linear-dor-failure-reporting all do), and so do stubs in repos not
# checked out here. The first cut of this gate took `--kind receipt "$msg"`,
# which moved the message out of $1 and turned three untouched suites red at
# once. The parser accepts flags in ANY position so that call sites can keep the
# message first; this case is what stops someone "tidying" that back into a
# flags-only-first parser and breaking every such stub silently.
D="$WORK/c1b"; run_notify "$D" "message first, flags after" --kind receipt
if delivered "$D"; then bad "message-first receipt is NOT delivered" "curl was called"
else ok "message-first receipt parses (not delivered)"; fi
[ "$(field "$D" message)" = "[testinst] message first, flags after" ] \
  && ok "message-first: the MESSAGE is recorded, not the flag" \
  || bad "message-first records the message" "got '$(field "$D" message)'"

D="$WORK/c1c"; run_notify "$D" --kind receipt "flags first, message after"
[ "$(field "$D" message)" = "[testinst] flags first, message after" ] \
  && ok "flags-first still parses identically (both orders supported)" \
  || bad "flags-first records the message" "got '$(field "$D" message)'"

D="$WORK/c1d"; run_notify "$D" "a decision, message first" --kind decision --class spend
delivered "$D" && ok "message-first decision+class IS delivered" \
  || bad "message-first decision delivered" "curl never called; err=$(cat "$D/err")"

# --- 2. an allowlisted founder decision DOES get through ---------------------
# This is the half that matters most. A gate that silences a real alert is a
# worse outage than the noise it was built to stop, so this case is asserted
# against the delivery recorder itself, not against "no error was printed".
D="$WORK/c2"; run_notify "$D" --kind decision --class irreversible-git \
  "kipi dispatch: paused -- this checkout is behind origin/main. Do: git merge --ff-only origin/main"
if delivered "$D"; then ok "decision + allowlisted class IS delivered"
else bad "decision + allowlisted class IS delivered" "curl never called; err=$(cat "$D/err")"; fi
[ "$(field "$D" delivered)" = "True" ] && ok "decision row records delivered=true" \
  || bad "decision row records delivered=true" "got '$(field "$D" delivered)'"

D="$WORK/c2b"; run_notify "$D" --kind decision --class out-of-tree-write \
  "wrote 3 files outside the canonical tree, needs sign-off"
delivered "$D" && ok "second allowlisted class (out-of-tree-write) IS delivered" \
  || bad "second allowlisted class delivered" "curl never called"

# --- 3. the closed enum is what stops rewording -------------------------------
D="$WORK/c3"; run_notify "$D" --kind decision --class needs-a-human \
  "worker: ASK-1 is STUCK. Needs a human."
if delivered "$D"; then bad "unknown decision class is REFUSED" "curl was called"
else ok "unknown decision class is REFUSED"; fi
[ "$(cat "$D/rc")" = "2" ] && ok "refusal exits 2" || bad "refusal exits 2" "rc=$(cat "$D/rc")"
grep -qi 'refus' "$D/err" && ok "refusal is loud on stderr" \
  || bad "refusal is loud on stderr" "err=$(cat "$D/err")"
[ "$(field "$D" refused)" = "True" ] && ok "refused row is still recorded (nothing is lost)" \
  || bad "refused row is still recorded" "got '$(field "$D" refused)'"

D="$WORK/c4"; run_notify "$D" --kind decision "no class at all"
delivered "$D" && bad "decision with NO class is REFUSED" "curl was called" \
  || ok "decision with NO class is REFUSED"

D="$WORK/c5"; run_notify "$D" --kind chatter "a fourth kind someone invented"
delivered "$D" && bad "unknown kind is REFUSED" "curl was called" || ok "unknown kind is REFUSED"

# --- 4. legacy one-arg callers FAIL OPEN, loudly ------------------------------
# Fleet instances carry producers this repo does not, and kipi update ships this
# script to them. Refusing an unclassified message would silence an instance-local
# alert nobody has migrated yet -- the exact "gate that silences a real alert"
# failure. So it is delivered, marked, and recorded for the migration to find.
D="$WORK/c6"; run_notify "$D" "a producer that has not been migrated yet"
delivered "$D" && ok "unclassified legacy call still DELIVERS (fail-open)" \
  || bad "unclassified legacy call still delivers" "curl never called"
grep -q 'unclassified' "$D/curl.log" && ok "unclassified delivery is MARKED in the text" \
  || bad "unclassified delivery is marked" "payload=$(cat "$D/curl.log")"
[ "$(field "$D" kind)" = "unclassified" ] && ok "unclassified row is recorded as such" \
  || bad "unclassified row recorded" "got '$(field "$D" kind)'"

# --- 5. the fixture guard still outranks everything ---------------------------
# A decision-class page from a fixture run must STILL not reach a human. The
# 2026-08-01 scar (three tests paging the founder live) outranks this issue.
D="$WORK/c7"; rm -rf "$D"; mkdir -p "$D"
env PATH="$WORK/bin:$PATH" KIPI_TEST_CURL_LOG="$D/curl.log" \
    KIPI_SLACK_WEBHOOK="https://hooks.example.invalid/T/B/X" \
    KIPI_NOTIFY_RECEIPTS="$D/receipts.jsonl" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:8123/graphql" \
    bash "$NOTIFY" --kind decision --class irreversible-git "fixture must never page" \
    >"$D/out" 2>"$D/err"
delivered "$D" && bad "fixture guard outranks the decision gate" "curl was called" \
  || ok "fixture guard outranks the decision gate"

# --- 6. the static half: no producer may call the sink without a kind ---------
if [ ! -f "$AUDIT" ]; then
  bad "notify-callsite-audit.py exists" "missing at $AUDIT"
else
  if python3 "$AUDIT" --repo "$REPO" >"$WORK/audit.out" 2>&1; then
    ok "every notifier call site in this repo declares a --kind"
  else
    bad "every notifier call site declares a --kind" "$(head -20 "$WORK/audit.out")"
  fi
  # NEGATIVE SELF-TEST. A checker that cannot fail is not a checker. Plant a
  # producer that calls the sink bare and prove the audit catches it.
  PLANT="$WORK/plant"; rm -rf "$PLANT"; mkdir -p "$PLANT/q-system/.q-system/scripts"
  cp "$AUDIT" "$PLANT/q-system/.q-system/scripts/" 2>/dev/null || true
  # ASSEMBLED, NOT HEREDOC'd. A heredoc puts the literal `bash "$NOTIFY" ...` in
  # THIS file, where the audit flags it -- and the obvious fix, adding a
  # notify-kind-skip marker to that line, silently lands the marker INSIDE the
  # generated fixture. That is exactly what happened: the planted rogue arrived
  # pre-exempted, the audit correctly ignored it, and the negative self-test
  # reported the guard as broken when the guard was fine. Building the call from a
  # placeholder keeps this source clean and the generated file genuinely bare.
  {
    echo '#!/bin/bash'
    echo 'NOTIFY="$SCRIPT_DIR/slack-notify.sh"'
    printf 'bash "$%s" "a bare page with no kind at all"\n' NOTIFY
  } > "$PLANT/q-system/.q-system/scripts/rogue-producer.sh"
  # The planted fixture must actually be bare, or the assertion below proves nothing.
  grep -q 'notify-kind-skip' "$PLANT/q-system/.q-system/scripts/rogue-producer.sh" \
    && bad "harness: the planted rogue is pre-exempted" "it carries a skip marker"
  ( cd "$PLANT" && git init -q . && git add -A && git -c user.email=t@t -c user.name=t commit -qm t ) >/dev/null 2>&1
  if python3 "$AUDIT" --repo "$PLANT" >"$WORK/plant.out" 2>&1; then
    bad "audit CATCHES a bare call site (negative self-test)" "planted rogue producer passed"
  else
    grep -q 'rogue-producer.sh' "$WORK/plant.out" \
      && ok "audit CATCHES a bare call site and names the file" \
      || bad "audit names the offending file" "$(head -10 "$WORK/plant.out")"
  fi
fi

echo
printf 'passed %d, failed %d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
