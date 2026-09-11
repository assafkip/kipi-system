#!/usr/bin/env python3
"""Adds the round-8 cases to test-claude-write-path.sh (ASK-291).

probe_round8_findings.sh is the reproducer and carries the negative self-test,
but nothing runs a per-round probe on its own. The DURABLE cases belong in the
suite the capability manifest actually runs, which is this one -- same reason
rounds 5 and 6 landed their parity and substitution cases here.

Same write-then-register constraint as patch_round8_guard.py: the test suite is
a watched file, so a plain Edit is reverted one tool call later.

Usage: python3 patch_round8_tests.py <path-to-test-claude-write-path.sh>
"""
import io
import sys

TARGET = sys.argv[1]
src = io.open(TARGET, encoding="utf-8").read()

ANCHOR = '''assert_block "watched subtree still protected under a scratch NAME" \\
  'touch .claude/rules/worktrees.md'
'''

NEW = ANCHOR + '''
# --- round 8: a re-baseline in the same command voids the handoff to Layer 2 ---
# Layer 1 hands an UNANCHORABLE `.claude/` write to Layer 2 because the file
# lands and the hash moves. `--register` / `--baseline` in the SAME tool call
# records the tamper as trusted before any PostToolUse hook runs, so the backstop
# reports clean. Both layers defeated, no alarm (review finding, PR #85 round 8).
TRIP=q-system/.q-system/scripts/claude-integrity-tripwire.py
APPLY=q-system/.q-system/scripts/apply-claude-changes.sh

assert_block "unanchorable write + --register in one command" \\
  "touch \\$UNSET/.claude/rules/pwn.md; python3 $TRIP --register .claude/rules/pwn.md"
assert_block "same pair, re-baseline first (order-independent)" \\
  "python3 $TRIP --register .claude/rules/pwn.md; touch \\$UNSET/.claude/rules/pwn.md"
assert_block "unanchorable redirect + blanket --baseline" \\
  "printf pwned > \\$UNSET/.claude/rules/pwn.md; python3 $TRIP --baseline"
assert_block "unanchorable write inside <( ), re-baseline outside" \\
  "python3 $TRIP --register .claude/rules/pwn.md <(touch \\$UNSET/.claude/rules/pwn.md)"
assert_block "unanchorable write && the applier, which re-baselines" \\
  "touch \\$UNSET/.claude/agents/pwn.md && bash $APPLY proposal.json"

# The void reaches ONLY tokens that took the handoff. Everything below kept
# working, and each line is one of the false blocks that has nearly killed this
# guard: the handoff itself when nothing erases the backstop, the temp-dir
# fixture, and any path this parser CAN anchor.
assert_allow "unanchorable write alone still hands off to Layer 2" \\
  'touch $UNSET/.claude/rules/pwn.md'
assert_allow "re-baseline alone" \\
  "python3 $TRIP --register .claude/rules/x.md"
assert_allow "temp-dir fixture tree beside nothing" \\
  'D=$(mktemp -d); mkdir -p "$D/.claude/rules"'
assert_allow "resolvable /tmp fixture beside a re-baseline" \\
  "mkdir -p /tmp/x/.claude/rules; python3 $TRIP --register .claude/rules/x.md"
'''

if src.count(ANCHOR) != 1:
    sys.exit("ANCHOR NOT UNIQUE (%d hits)" % src.count(ANCHOR))
src = src.replace(ANCHOR, NEW)
io.open(TARGET, "w", encoding="utf-8").write(src)
print("patched %s (9 cases added)" % TARGET)
