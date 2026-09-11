#!/usr/bin/env bash
# Reproducer for PR #85 round 9 (BLOCKER).
#
# THE FINDING, in the reviewer's words: "Indirect Bash expansion bypasses Layer 1
# and same-command --baseline permanently sanctions the guarded write."
#
#     P=.claude; V=P; touch ${!V}/rules/pwn.md; <tripwire> --baseline     -> rc=0
#
# WHY it walked past round 8's fix. `layer2_blind` DID fire -- the tripwire is in
# the command. The hole is one layer down, in resolve(): UNRESOLVED enumerated
# the expansion SHAPES it knew (`$(`, backtick, `${?<letter>`). `${!V}` is `$`
# then `{` then `!`, which none of them match, so the token was never called
# unanchorable. It was ANCHORED -- joined to the cwd verbatim -- producing the
# fabricated path `<cwd>/${!V}/rules/pwn.md`, which carries no `.claude`
# component. hits_claude() said no, literal_claude_tail() said none, and the
# round-8 fail-closed branch is only reachable from `resolve() is None`.
#
# So this is the round-3 scar a second time (comparing a REPRESENTATION instead
# of the thing), and the reviewer is right that patching one more shape is not a
# fix. Phase 2 proves the class is wider than the one shape they sent.
#
# WHAT DONE LOOKS LIKE (stated before the fix, per verification-loops):
#   phase 1  the reviewer's verbatim command blocks
#   phase 2  every other expansion/glob spelling of the same class blocks
#   phase 3  a plain literal path beside a re-baseline is STILL allowed
#            (this is the pinned round-8 allow; the fix must not eat it)
#   phase 4  without a re-baseline in the command, nothing over-blocks
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
GUARD="$ROOT/q-system/.q-system/scripts/claude-path-write-guard.py"
TRIP="q-system/.q-system/scripts/claude-integrity-tripwire.py"
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

echo "== phase 1: the reviewer's verbatim round-9 command =="
expect 2 "indirect expansion + same-command --baseline" \
  "P=.claude; V=P; touch \${!V}/rules/pwn.md; python3 $TRIP --baseline"

echo
echo "== phase 2: the CLASS, not the one spelling =="
# Every one of these hides the `.claude` component behind an expansion or a glob
# that the parser cannot evaluate, in a command that erases Layer 2's baseline.
expect 2 "default-value expansion" \
  "touch \${UNSET:-.claude}/rules/pwn.md; python3 $TRIP --baseline"
expect 2 "substring-replacement expansion" \
  "P=xclaude; touch \${P/x/.}/rules/pwn.md; python3 $TRIP --baseline"
expect 2 "array-subscript expansion" \
  "A=(.claude); touch \${A[0]}/rules/pwn.md; python3 $TRIP --baseline"
expect 2 "ANSI-C quoting" \
  "touch \$'.clau''de'/rules/pwn.md; python3 $TRIP --baseline"
expect 2 "positional parameter" \
  "set -- .claude; touch \$1/rules/pwn.md; python3 $TRIP --baseline"
expect 2 "glob that expands to .claude" \
  "touch .clau*/rules/pwn.md; python3 $TRIP --baseline"
expect 2 "brace expansion" \
  "touch .{claude}/rules/pwn.md; python3 $TRIP --baseline"
expect 2 "character class" \
  "touch .clau[d]e/rules/pwn.md; python3 $TRIP --baseline"
expect 2 "indirect expansion inside a process substitution" \
  "python3 $TRIP --baseline <(P=.claude; V=P; touch \${!V}/rules/pwn.md)"
expect 2 "indirect expansion, re-baseline FIRST (order-independent)" \
  "python3 $TRIP --baseline; P=.claude; V=P; touch \${!V}/rules/pwn.md"

echo
echo "== phase 3: the pinned round-8 allows must survive =="
# A guard that stops the work it guards gets switched off. These are the shapes
# that have nearly killed this guard, and the fix is not allowed to eat them.
expect 0 "plain literal /tmp fixture beside a re-baseline" \
  "mkdir -p /tmp/x/.claude/rules; python3 $TRIP --register .claude/rules/x.md"
expect 0 "re-baseline alone" \
  "python3 $TRIP --register .claude/rules/x.md"
expect 0 "reading a glob beside a re-baseline (read-only allowlist holds)" \
  "grep -rn hook .claude/rules/*.md; python3 $TRIP --baseline"

echo
echo "== phase 4: no re-baseline in the command -> unchanged behaviour =="
# Without a re-baseline the handoff to Layer 2 is real: the file lands, the hash
# moves, the tripwire reverts it. Layer 1 does not over-block these.
expect 0 "indirect expansion alone still hands off to Layer 2" \
  "P=.claude; V=P; touch \${!V}/rules/pwn.md"
expect 0 "temp-dir fixture tree beside nothing" \
  'D=$(mktemp -d); mkdir -p "$D/.claude/rules"'
expect 2 "a literal .claude write is still blocked outright" \
  "touch .claude/rules/pwn.md"

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
