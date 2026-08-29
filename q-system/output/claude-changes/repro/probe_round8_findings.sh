#!/usr/bin/env bash
# probe_round8_findings.sh -- reproducer for the round-8 Codex finding on PR #85
# (ASK-291). Written BEFORE the fix; every blocker phase was observed RED first.
#
#   1 blocker  the sanctioned-command bypass is live through a COMPOUND command.
#              Layer 1 waves an UNANCHORABLE `.claude/` write through on the
#              stated grounds that Layer 2 will catch it. A sanctioned
#              re-baseline in the SAME command falsifies that: the shell runs
#              both operations, then the re-baseline records the tamper as the
#              trusted state, and the PostToolUse tripwire that was supposed to
#              be the backstop sees no drift.
#
# The shape:  touch $UNSET/.claude/rules/pwn.md; <tripwire> --register .claude/rules/pwn.md
#
# Rounds 6 and 7 closed the same underlying hole for `$(...)`/backticks and then
# for `<(...)`/`>(...)`: an exemption handed to the outer program reached inside
# a substitution. This is the third door, and it does not need a substitution at
# all -- a bare `;` is enough, because the exemption that matters here is not
# `_is_sanctioned` returning `ok` for a statement, it is the HANDOFF TO LAYER 2
# taken by a DIFFERENT statement whose backstop the sanctioned one then erases.
#
# So the fix is not another opener in the extractor. It is: the handoff to
# Layer 2 is void when the same command re-baselines Layer 2. Order-independent
# on purpose -- `&&`, `||`, `;` and subshells do not give this parser a reliable
# execution order, and reasoning about one is a new failure surface.
#
# THE ESCAPE HATCH, and why the false-block cost is affordable: split the
# command into TWO Bash tool calls. Layer 2 then runs BETWEEN them, which is the
# exact property the handoff assumes. Phase 2 pins the cost honestly rather than
# claiming there is none.
#
# Negative self-test: --self-test rebuilds the PRE-FIX guard (REBASELINERS
# emptied in a COPY) and asserts the blocker cases go THROUGH it. A probe whose
# self-test cannot fail pins nothing -- round 5 shipped one inert case.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
SCRIPTS="$REPO/q-system/.q-system/scripts"
# Switches are FLAGS, not `VAR=x bash probe.sh` env prefixes: this repo's other
# gates refuse an assignment-prefixed command line (measured, ASK-291 round 6).
SELF_TEST=0
GUARD="$SCRIPTS/claude-path-write-guard.py"
while [ $# -gt 0 ]; do
  case "$1" in
    --self-test) SELF_TEST=1; shift ;;
    --guard)     GUARD="$2"; shift 2 ;;
    *)           printf 'unknown flag: %s\n' "$1"; exit 2 ;;
  esac
done
TRIP="q-system/.q-system/scripts/claude-integrity-tripwire.py"
APPLY="q-system/.q-system/scripts/apply-claude-changes.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
passed=0; failed=0; blocker_failed=0
pass() { passed=$((passed+1)); printf '  PASS  %s\n' "$1"; }
fail() { failed=$((failed+1)); printf '  FAIL  %s\n' "$1"; }
# A blocker case that does not block is the vulnerability itself. Counted apart
# so --self-test can ASSERT the pre-fix guard is vulnerable instead of asking a
# human to eyeball a failure count.
bfail() { blocker_failed=$((blocker_failed+1)); fail "$1"; }
phase() { printf '\n== %s ==\n' "$1"; }

# ------------------------------------------------------------- guard under test
# --self-test empties REBASELINERS in a COPY. That is exactly the pre-fix
# behaviour: `_is_sanctioned` unchanged, substitutions still extracted, but no
# command is ever recognised as erasing Layer 2's baseline, so the handoff to
# Layer 2 is taken unconditionally.
if [ "$SELF_TEST" = "1" ]; then
  PREFIX_GUARD="$WORK/prefix-guard.py"
  sed 's/^REBASELINERS = SANCTIONED$/REBASELINERS = ()/' "$GUARD" > "$PREFIX_GUARD"
  if ! grep -q '^REBASELINERS = ()$' "$PREFIX_GUARD"; then
    printf 'SELF_TEST BROKEN: could not neutralise REBASELINERS in the copy\n'
    exit 2
  fi
  GUARD="$PREFIX_GUARD"
fi
printf 'guard under test: %s\n' "$GUARD"

# judge <label> <BLOCK|ALLOW> <blocker|minor> <command>
# Feeds the real hook payload on stdin, exactly as Claude Code does.
judge() {
  local label="$1" want="$2" sev="$3" cmd="$4" rc
  printf '%s' "$cmd" | python3 -c '
import json, sys
print(json.dumps({"tool_name": "Bash",
                  "tool_input": {"command": sys.stdin.read()},
                  "cwd": sys.argv[1]}))' "$REPO" \
    | python3 "$GUARD" >/dev/null 2>&1
  rc=$?
  local got="ALLOW"; [ "$rc" -eq 2 ] && got="BLOCK"
  if [ "$got" = "$want" ]; then
    pass "$label ($got)"
  elif [ "$sev" = "blocker" ]; then
    bfail "$label: got $got, want $want"
  else
    fail "$label: got $got, want $want"
  fi
}

# ---------------------------------------------------------------------- phase 1
phase "phase 1: the round-8 blocker -- unanchorable write + sanctioned re-baseline"

judge "codex reproducer verbatim (touch \$UNSET then --register)" BLOCK blocker \
  "touch \$UNSET/.claude/rules/pwn.md; python3 $TRIP --register .claude/rules/pwn.md --quiet"

judge "same pair, re-baseline FIRST (order-independent)" BLOCK blocker \
  "python3 $TRIP --register .claude/rules/pwn.md --quiet; touch \$UNSET/.claude/rules/pwn.md"

judge "&& chain into the applier, which re-baselines what it wrote" BLOCK blocker \
  "touch \$UNSET/.claude/agents/pwn.md && bash $APPLY proposal.json"

judge "blanket --baseline erases the backstop for a redirect" BLOCK blocker \
  "printf pwned > \$UNSET/.claude/rules/pwn.md; python3 $TRIP --baseline"

# The write hides in a process-substitution body while the OUTER command is the
# sanctioned re-baseliner. Pins that the void is computed from the WHOLE command
# and threaded into the substitution walk, not recomputed per body (a body alone
# names no sanctioned program, so a per-body flag would read False here).
judge "unanchorable write inside <( ), sanctioned re-baseline outside" BLOCK blocker \
  "python3 $TRIP --register .claude/rules/pwn.md <(touch \$UNSET/.claude/rules/pwn.md)"

judge "kipi-update.sh counts: it re-baselines after rewriting .claude/" BLOCK blocker \
  "touch \$UNSET/.claude/hooks/pwn.sh; bash $APPLY p"

# ---------------------------------------------------------------------- phase 2
phase "phase 2: what must NOT change -- the four false-block scars, still ALLOW"

# The NAMED GAP stands on its own: with no re-baseline in the command, Layer 2
# is a real backstop and Layer 1 still hands off. Narrowing here would be the
# fifth false block of the class that has nearly killed this guard.
judge "unanchorable write ALONE still hands off to Layer 2" ALLOW blocker \
  "touch \$UNSET/.claude/rules/pwn.md"

judge "sanctioned re-baseline ALONE" ALLOW blocker \
  "python3 $TRIP --register .claude/rules/x.md --quiet"

judge "temp-dir fixture tree (round-2 scar, blocked the reviewer verbatim)" ALLOW blocker \
  "D=\$(mktemp -d); mkdir -p \"\$D/.claude/rules\""

judge "the applier alone" ALLOW blocker \
  "bash $APPLY proposal.json"

judge "cd into an unrelated tree, then the applier" ALLOW blocker \
  "cd /tmp && bash $APPLY proposal.json"

# ANCHORABLE paths are unaffected: they never took the handoff, so the void
# cannot reach them. An unrelated /tmp fixture next to a re-baseline stays legal.
judge "resolvable /tmp fixture beside a re-baseline" ALLOW blocker \
  "mkdir -p /tmp/x/.claude/rules; python3 $TRIP --register .claude/rules/x.md"

# A commit message QUOTING a .claude/ path beside a re-baseline. The newline /
# text-payload gap is deliberately NOT voided: voiding it re-opens the
# false block that refused the commit of this guard's own arming, measured live
# 2026-08-03. The exotic `touch $'.claude/x\ny'` shape stays inside that named
# gap, which Layer 2 owns.
judge "multi-line commit message beside a re-baseline" ALLOW blocker \
  "$(printf 'git commit -m "arm the guards\n\nBLOCKED ... .claude/settings.json\n"; python3 %s --register .claude/settings.json' "$TRIP")"

# ---------------------------------------------------------------------- phase 3
phase "phase 3: the accepted cost, pinned so it is a decision and not a surprise"

# This one BLOCKS and is a false block. It is the price of the fix and it is
# named here rather than in prose: a fixture tree built in the same command as a
# re-baseline cannot be told apart from the attack by this parser -- both are an
# unanchorable `.claude/` token next to a baseline rewrite.
#
# The remedy costs one tool call: run the fixture and the re-baseline as TWO
# Bash calls. Layer 2 then runs between them, which is the property the handoff
# assumed all along. A wedged session would be unaffordable; an extra tool call
# is not.
judge "fixture tree + re-baseline in ONE command (accepted false block)" BLOCK minor \
  "D=\$(mktemp -d); mkdir -p \"\$D/.claude/rules\"; python3 $TRIP --register .claude/rules/x.md"

# ---------------------------------------------------------------------- phase 4
phase "phase 4: the earlier rounds' doors are still shut"

judge "round-6: command substitution behind a sanctioned program" BLOCK blocker \
  "bash $APPLY \"\$(touch .claude/evil.txt)\""

judge "round-7: process substitution behind a sanctioned program" BLOCK blocker \
  "bash $APPLY <(touch .claude/evil.txt)"

judge "round-2: direct redirect, no leading space" BLOCK blocker \
  "printf pwned>.claude/settings.json"

judge "round-7: quoted process substitution is inert text" ALLOW blocker \
  "echo \"<(touch .claude/rules/pwn.md)\""

printf '\nRESULT: %d passed, %d failed (blocker cases failed: %d)\n' \
  "$passed" "$failed" "$blocker_failed"

if [ "$SELF_TEST" = "1" ]; then
  # The self-test PASSES when the reconstructed pre-fix guard is vulnerable.
  if [ "$blocker_failed" -gt 0 ]; then
    printf 'SELF_TEST OK: pre-fix guard let %d blocker case(s) through\n' "$blocker_failed"
    exit 0
  fi
  printf 'SELF_TEST INERT: pre-fix guard blocked everything -- this probe pins nothing\n'
  exit 1
fi
[ "$failed" -eq 0 ] || exit 1
