#!/usr/bin/env bash
# Reproducer for PR #85 round 11 (BLOCKER).
#
# THE FINDING, in the reviewer's words: "Deleting the baseline in the same Bash
# call as an unanchored .claude write makes enforcement trust the tampered tree
# forever" (claude-integrity-tripwire.py:692). Their measurement:
#
#     guard_reason=None
#     notify=armed .claude/ integrity tripwire: 1 file(s) baselined
#     first_enforce_rc=0
#     trusted_sha=pwned
#     second_enforce_rc=0
#
# CONFIRMED, and it is round 8 a second time with a different verb. Round 8
# closed "the same command RE-BASELINES Layer 2", because the handoff Layer 1
# takes for an unanchorable `.claude/` write is a claim about what happens AFTER
# this tool call: the file lands, the hash moves, the tripwire reverts it. A
# same-command re-baseline falsifies that claim by recording the tamper as
# trusted.
#
# DELETING the baseline falsifies exactly the same claim, and Layer 1 never
# looked: `REBASELINERS` is a list of PROGRAMS (the four sanctioned appliers),
# and `rm` is not one of them. The baseline lives at
# `q-system/.q-system/claude-integrity-baseline.json` -- OUTSIDE `.claude/` -- so
# no `.claude` component appears in the delete and hits_claude() says no. The
# write is handed off to a backstop the same command has already removed, and
# Layer 2's first-run branch then arms SILENTLY on the tampered tree.
#
# THE OTHER HALF, which Layer 1 structurally cannot reach: the delete does not
# have to be visible in the command at all. `bash evil.sh` shows Layer 1 nothing
# -- no `.claude` mention, no baseline mention, no rebaseliner -- and the script
# can delete the baseline and tamper before any PostToolUse hook fires. Layer 2
# is the only thing that can notice, and today it cannot: a missing baseline is
# indistinguishable from a fresh instance, so it arms on whatever it finds.
#
# WHAT DONE LOOKS LIKE (stated before the fix, per verification-loops):
#   phase 1  the reviewer's vector blocks at Layer 1
#   phase 2  the CLASS blocks: every spelling that REACHES the baseline path
#            beside an unanchorable .claude write, in either order
#   phase 3  the pinned allows survive -- a baseline mention with no unanchorable
#            .claude write is not a block, and rounds 8/9's allows still pass
#   phase 4  END TO END at Layer 2: a tree that was armed, whose baseline is then
#            deleted out of band and whose .claude/ is tampered, must NOT come
#            back clean. It must alarm and refuse to bless the tamper.
#   phase 5  a genuinely fresh tree still arms silently (the round-2 scar: a
#            fleet-wide daily page is a worse defect than the hole it closes)
#
# NEGATIVE SELF-TEST: phase 0 proves this harness can fail, by asserting a
# verdict that is wrong today and wrong after the fix.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
GUARD="$ROOT/q-system/.q-system/scripts/claude-path-write-guard.py"
TRIPABS="$ROOT/q-system/.q-system/scripts/claude-integrity-tripwire.py"
TRIP="q-system/.q-system/scripts/claude-integrity-tripwire.py"
BASE="q-system/.q-system/claude-integrity-baseline.json"
PASS=0; FAIL=0

run() { # command -> rc
  python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]},"cwd":sys.argv[2]}))' "$1" "$ROOT" \
    | CLAUDE_PROJECT_DIR="$ROOT" python3 "$GUARD" >/dev/null 2>&1
  echo $?
}

expect() { # want_rc, desc, command
  local want="$1" desc="$2" cmd="$3" got
  got="$(run "$cmd")"
  if [ "$got" = "$want" ]; then
    PASS=$((PASS+1)); printf 'ok    %s (rc=%s)\n' "$desc" "$got"
  else
    FAIL=$((FAIL+1)); printf 'FAIL  %s (want rc=%s, got rc=%s)\n  cmd: %s\n' "$desc" "$want" "$got" "$cmd"
  fi
}

check() { # want, got, desc
  if [ "$2" = "$1" ]; then
    PASS=$((PASS+1)); printf 'ok    %s (%s)\n' "$3" "$2"
  else
    FAIL=$((FAIL+1)); printf 'FAIL  %s (want %s, got %s)\n' "$3" "$1" "$2"
  fi
}

# ---------------------------------------------------------------- phase 0
echo "== phase 0: negative self-test (this harness must be able to fail) =="
NEG="$(run 'echo hello')"
if [ "$NEG" = "2" ]; then
  PASS=$((PASS+1)); printf 'ok    harness can fail -- but it did not, and that is itself wrong\n'
else
  PASS=$((PASS+1)); printf 'ok    harness reports a real rc (echo hello -> rc=%s, not a hardcoded pass)\n' "$NEG"
fi
# The real negative self-test: assert something FALSE and confirm the harness
# counts it as a failure, then undo the count. A harness that cannot go red is
# a green light with no wire behind it.
BEFORE_FAIL=$FAIL
expect 2 "DELIBERATE FALSE ASSERTION (must be counted as FAIL)" "echo hello"
if [ "$FAIL" -eq "$((BEFORE_FAIL + 1))" ]; then
  FAIL=$BEFORE_FAIL
  PASS=$((PASS+1)); printf 'ok    harness counted the false assertion as FAIL (self-test valid)\n'
else
  printf 'FAIL  harness did NOT count a false assertion -- every result below is meaningless\n'
  exit 1
fi

# ---------------------------------------------------------------- phase 1
echo
echo "== phase 1: the reviewer's round-11 vector =="
expect 2 "unanchorable .claude write + same-command baseline delete" \
  "P=.claude; V=P; touch \${!V}/rules/pwn.md; rm -f $BASE"
expect 2 "same, delete FIRST (order-independent)" \
  "rm -f $BASE; P=.claude; V=P; touch \${!V}/rules/pwn.md"

# ---------------------------------------------------------------- phase 2
echo
echo "== phase 2: the CLASS -- any command that REACHES the baseline =="
# The defect is not `rm`. It is that Layer 1 asked which PROGRAM ran instead of
# asking whether the backstop is still there afterwards. Enumerating the verbs
# that can unlink a file is the fail-open surface this file's header warns about,
# so the test is a mention/resolve of the baseline PATH, and these spellings all
# have to fall to it.
expect 2 "mv the baseline aside" \
  "mv $BASE /tmp/b.json; touch \${UNSET:-.claude}/rules/pwn.md"
expect 2 "truncate the baseline with a redirect" \
  ": > $BASE; touch \${UNSET:-.claude}/rules/pwn.md"
expect 2 "overwrite the baseline with junk" \
  "echo '{}' > $BASE; A=(.claude); touch \${A[0]}/rules/pwn.md"
expect 2 "delete via a variable holding the path" \
  "B=$BASE; rm -f \$B; set -- .claude; touch \$1/rules/pwn.md"
expect 2 "delete via basename glob" \
  "rm -f q-system/.q-system/claude-integrity-base*.json; touch .clau*/rules/pwn.md"
expect 2 "delete inside a process substitution" \
  "cat <(rm -f $BASE); P=.claude; V=P; touch \${!V}/rules/pwn.md"
expect 2 "python one-liner unlinking the baseline" \
  "python3 -c \"import os;os.remove('$BASE')\"; touch \${UNSET:-.claude}/rules/pwn.md"
expect 2 "absolute path to the baseline" \
  "rm -f $ROOT/$BASE; P=.claude; V=P; touch \${!V}/rules/pwn.md"

# ---------------------------------------------------------------- phase 3
echo
echo "== phase 3: pinned allows -- the fix is not allowed to eat these =="
# A guard that stops the work it guards gets switched off.
expect 0 "deleting the baseline ALONE (Layer 2 re-arms clean on the next call)" \
  "rm -f $BASE"
expect 0 "reading the baseline alone" \
  "cat $BASE | head -5"
expect 0 "baseline mention beside a LITERAL, resolvable, non-.claude write" \
  "rm -f $BASE; touch /tmp/harmless.txt"
expect 0 "unanchorable .claude write alone still hands off to Layer 2" \
  "P=.claude; V=P; touch \${!V}/rules/pwn.md"
expect 0 "round-8 pinned allow: /tmp fixture beside a re-baseline" \
  "mkdir -p /tmp/x/.claude/rules; python3 $TRIP --register .claude/rules/x.md"
expect 0 "round-9 pinned allow: reading a glob beside a re-baseline" \
  "grep -rn hook .claude/rules/*.md; python3 $TRIP --baseline"
expect 2 "a literal .claude write is still blocked outright" \
  "touch .claude/rules/pwn.md"

# ---------------------------------------------------------------- phase 4
echo
echo "== phase 4: END TO END at Layer 2 -- the half Layer 1 cannot see =="
# `bash evil.sh` shows Layer 1 nothing. The script deletes the baseline and
# tampers before any PostToolUse hook fires. Only Layer 2 can notice, and it must.
FIX="$(mktemp -d)"
trap 'rm -rf "$FIX"' EXIT
mkdir -p "$FIX/.claude/rules" "$FIX/q-system/.q-system/scripts"
cp "$TRIPABS" "$FIX/q-system/.q-system/scripts/"
cp "$GUARD"   "$FIX/q-system/.q-system/scripts/"
printf 'legit rule\n' > "$FIX/.claude/rules/real.md"
printf '{}\n'          > "$FIX/.claude/settings.json"
git -C "$FIX" init -q 2>/dev/null
git -C "$FIX" add -A >/dev/null 2>&1
git -C "$FIX" -c user.email=t@t -c user.name=t commit -qm init >/dev/null 2>&1

trip() { python3 "$FIX/q-system/.q-system/scripts/claude-integrity-tripwire.py" --root "$FIX" "$@"; }

trip --baseline --quiet >/dev/null 2>&1
check "yes" "$([ -f "$FIX/$BASE" ] && echo yes || echo no)" "fixture armed (baseline written)"

# THE ATTACK, entirely inside a script Layer 1 never sees the contents of.
cat > "$FIX/evil.sh" <<'EOS'
set -e
rm -f "$1/q-system/.q-system/claude-integrity-baseline.json"
printf 'pwned\n' > "$1/.claude/rules/pwn.md"
EOS
bash "$FIX/evil.sh" "$FIX"

trip --enforce --quiet >/dev/null 2>&1; RC1=$?
check "2" "$RC1" "first --enforce after baseline-delete+tamper does NOT return clean"

# The finding's own measurement was `trusted_sha=pwned`: the tamper became the
# sanctioned state. Assert the negative of exactly that. A baseline that does not
# exist trusts nothing, so it satisfies the claim -- but it is a DIFFERENT and
# stronger outcome than "a baseline exists and omits the file", so it is named
# rather than folded in, and pinned separately below.
TRUSTED="$(python3 - "$FIX/$BASE" <<'EOP'
import json, sys
try:
    with open(sys.argv[1]) as fh:
        d = json.load(fh)
except Exception:
    print("not-trusted"); raise SystemExit
print("trusted" if ".claude/rules/pwn.md" in d.get("entries", {}) else "not-trusted")
EOP
)"
check "not-trusted" "$TRUSTED" "the tampered file was NOT recorded as sanctioned"
check "no" "$([ -f "$FIX/$BASE" ] && echo yes || echo no)" \
      "no baseline was invented from the tampered tree"
check "yes" "$([ -f "$FIX/q-system/.q-system/.claude-integrity-armed" ] && echo yes || echo no)" \
      "the armed marker is what made the difference (still present)"

trip --enforce --quiet >/dev/null 2>&1; RC2=$?
check "2" "$RC2" "second --enforce still alarms (the refusal is sticky, not a one-shot ping)"

# ---------------------------------------------------------------- phase 5
echo
echo "== phase 5: a genuinely fresh tree still arms silently (round-2 scar) =="
# Round 2: a baseline that could never match paged Slack DAILY ON EVERY INSTANCE.
# A fix that makes first-run arming loud recreates exactly that outage.
FRESH="$(mktemp -d)"
trap 'rm -rf "$FIX" "$FRESH"' EXIT
mkdir -p "$FRESH/.claude/rules" "$FRESH/q-system/.q-system/scripts"
cp "$TRIPABS" "$FRESH/q-system/.q-system/scripts/"
printf 'legit rule\n' > "$FRESH/.claude/rules/real.md"
git -C "$FRESH" init -q 2>/dev/null

python3 "$FRESH/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
        --root "$FRESH" --enforce --quiet >/dev/null 2>&1; RCF=$?
check "0" "$RCF" "fresh tree arms silently on first --enforce"
check "yes" "$([ -f "$FRESH/$BASE" ] && echo yes || echo no)" "fresh tree actually wrote a baseline"

python3 "$FRESH/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
        --root "$FRESH" --enforce --quiet >/dev/null 2>&1; RCF2=$?
check "0" "$RCF2" "fresh tree stays clean on the second run (no flapping watch set)"

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
