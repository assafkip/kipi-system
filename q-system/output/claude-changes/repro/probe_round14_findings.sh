#!/usr/bin/env bash
# Reproducer for PR #85 round 14 (2 majors + 3 minors).
#
# THE FINDINGS, in the reviewer's words:
#
#  1 major  "The updater registers only .claude/ paths but its own rsync rewrites
#           both EXTRA_WATCHED guard scripts, leaving every instance permanently
#           reporting SECURITY drift after an update" (kipi-update.sh:1433).
#  2 major  "A rebaseliner filename in a comment or quoted string sets
#           layer2_blind, so any glob argument on a non-read-only program is
#           blocked even when the command touches no .claude path"
#           (claude-path-write-guard.py:1217).
#  3 minor  "_could_name_baseline fnmatches q-system/* onto the baseline,
#           blocking `cp -r q-system/*` with stderr that falsely claims the
#           command re-baselines Layer 2" (:1119).
#  4 minor  "probe_update_interaction.sh omits the write-guard from its fixture,
#           never writes q-system/, and validates --baseline while the code ships
#           --register, so it cannot fail for the shipped fix" (:46).
#  5 minor  "A read-only `gh ... -- .claude/<path>` is refused with a message
#           asserting it would write inside .claude/" (:1403).
#
# ALL FIVE CONFIRMED. Findings 1 and 2 are the same defect wearing two coats:
# round 13 bought fail-closed security by widening a text match and priced the
# cost wrong in writing, and the updater's sanction list was written from the
# `.claude/` half of the watch set while the watch set has always had two members
# outside it.
#
# WHAT DONE LOOKS LIKE (stated before the fix, per verification-loops):
#   phase 1  the list kipi-update.sh ACTUALLY BUILDS -- extracted from the file
#            and executed, not grepped -- covers every EXTRA_WATCHED path the
#            tripwire declares, and an instance that took a full sync enforces
#            clean afterwards.
#   phase 2  a rebaseliner NAME in a comment or inside a prose argument does not
#            void Layer 2, while every real invocation shape round 13 closed
#            (env prefix, env(1), nice/timeout/command/nohup/stdbuf, an inline
#            code string) still does.
#   phase 3  `cp -r q-system/*` is allowed -- shell globs do not match a leading
#            dot, so `q-system/*` cannot name `q-system/.q-system/...` -- while
#            every real reach for the baseline still voids.
#   phase 4  a read-only `gh` subcommand with a `.claude/` pathspec is allowed;
#            a `gh` that can write there is still blocked.
#   phase 5  THE PINS THAT MUST SURVIVE. The round-13 vectors, the attack set,
#            and the benign shapes earlier rounds fought over.
#
# NEGATIVE SELF-TEST: phase 0 asserts a verdict that is wrong today and wrong
# after the fix, so a harness that cannot fail is visible as such.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
GUARD="$ROOT/q-system/.q-system/scripts/claude-path-write-guard.py"
TRIPWIRE="$ROOT/q-system/.q-system/scripts/claude-integrity-tripwire.py"
TRIP="q-system/.q-system/scripts/claude-integrity-tripwire.py"
UPDATER="$ROOT/kipi-update.sh"
PASS=0; FAIL=0

pass() { PASS=$((PASS+1)); printf 'ok    %s\n' "$1"; }
fail() { FAIL=$((FAIL+1)); printf 'FAIL  %s\n' "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# --- the guard, through its real hook envelope --------------------------------
rc_of() { # cmd [cwd] -> rc, stderr on fd 3
  local cwd="${2:-$ROOT}"
  python3 -c '
import json, sys
print(json.dumps({"tool_name": "Bash",
                  "tool_input": {"command": sys.argv[1]},
                  "cwd": sys.argv[2]}))
' "$1" "$cwd" | python3 "$GUARD" 2>"$WORK/err"; echo $?
}

expect_rc() { # want name cmd [cwd]
  local want="$1" name="$2" cmd="$3" cwd="${4:-$ROOT}"
  local got; got="$(rc_of "$cmd" "$cwd" | tail -1)"
  if [ "$got" = "$want" ]; then pass "$name (rc=$got)"
  else fail "$name: want rc=$want got rc=$got -- $(head -1 "$WORK/err")"; fi
}

voids() { # cmd [cwd] -> True/False
  GUARD="$GUARD" python3 -c '
import importlib.util, os, sys
s = importlib.util.spec_from_file_location("g", os.environ["GUARD"])
g = importlib.util.module_from_spec(s); s.loader.exec_module(g)
print(g._voids_layer2(sys.argv[1], sys.argv[2]))
' "$1" "${2:-$ROOT}" 2>/dev/null
}

expect_voids() { # want name cmd [cwd]
  local want="$1" name="$2" cmd="$3"
  local got; got="$(voids "$cmd" "${4:-$ROOT}")"
  if [ "$got" = "$want" ]; then pass "$name (voids=$got)"
  else fail "$name: want voids=$want got voids=$got"; fi
}

echo "=== phase 0: negative self-test (this harness can fail) ==="
expect_rc 7 "a verdict no version of the guard returns" "cat .claude/settings.json"

echo
echo "=== phase 1: the updater sanctions everything its own sync rewrote ==="
# Producer-derived, not transcribed: the TRIPWIRE_WROTE block is CUT OUT of
# kipi-update.sh and executed here with the same two variables the updater binds.
# Editing that block changes this test's answer, which is the whole point --
# round 14's finding 4 was that the old probe validated a regex over a 9-line
# window and so could not fail for the list the code actually ships.
awk '/^ *TRIPWIRE_WROTE=\(\)/{on=1} on&&/KIPI_NOTIFY=/{on=0} on' "$UPDATER" \
  > "$WORK/wrote-block.sh"
if [ -s "$WORK/wrote-block.sh" ]; then
  pass "extracted the register-list block from kipi-update.sh"
else
  fail "could not find the TRIPWIRE_WROTE block in kipi-update.sh"
fi

# A stand-in instance that took a FULL sync: .claude/ rewritten AND both guard
# scripts rewritten, which is what rsync of q-system/ does (kipi-update.sh:1295).
INST="$WORK/inst"
mkdir -p "$INST/q-system/.q-system/scripts" "$INST/.claude/rules"
cp "$TRIPWIRE" "$GUARD" "$INST/q-system/.q-system/scripts/"
printf 'rule v1\n' > "$INST/.claude/rules/coding-standards.md"
printf '{"hooks":{}}\n' > "$INST/.claude/settings.json"
git -C "$INST" init -q
git -C "$INST" add -A >/dev/null 2>&1
git -C "$INST" -c user.email=t@t -c user.name=t commit -qm base >/dev/null 2>&1
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$INST" --enforce --quiet >/dev/null 2>&1

# The sync: q-system/ first (both guard scripts), then .claude/.
printf '\n# skeleton v2\n' >> "$INST/q-system/.q-system/scripts/claude-path-write-guard.py"
printf '\n# skeleton v2\n' >> "$INST/q-system/.q-system/scripts/claude-integrity-tripwire.py"
printf 'rule v2\n' > "$INST/.claude/rules/coding-standards.md"
printf '{"hooks":{},"_marker":1}\n' > "$INST/.claude/settings.json"
git -C "$INST" add -A >/dev/null 2>&1
git -C "$INST" -c user.email=t@t -c user.name=t commit -qm sync >/dev/null 2>&1

# Run the updater's own list-building code, then its own register call.
(
  set -u
  path="$INST"; SCRIPT_DIR="$ROOT"
  # shellcheck disable=SC1090
  . "$WORK/wrote-block.sh"
  printf '%s\n' "${TRIPWIRE_WROTE[@]}" > "$WORK/register-list"
) 2>/dev/null

DECLARED="$(python3 -c '
import importlib.util, os, sys
s = importlib.util.spec_from_file_location("t", sys.argv[1])
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
print("\n".join(m.EXTRA_WATCHED))
' "$TRIPWIRE")"
MISSING=""
while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  grep -qxF "$rel" "$WORK/register-list" 2>/dev/null || MISSING="$MISSING $rel"
done <<< "$DECLARED"
if [ -z "$MISSING" ]; then
  pass "the register list covers every EXTRA_WATCHED path the tripwire declares"
else
  fail "register list omits EXTRA_WATCHED:$MISSING"
fi

# End to end: register exactly that list, then enforce twice. A watched file the
# updater rewrote but did not sanction reports SECURITY forever.
# shellcheck disable=SC2046
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$INST" --quiet \
  --register $(tr '\n' ' ' < "$WORK/register-list") >/dev/null 2>&1
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$INST" --enforce --quiet >/dev/null 2>&1
RC1=$?
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$INST" --enforce --quiet >/dev/null 2>&1
RC2=$?
[ "$RC1" -eq 0 ] && pass "first tool call after a full sync is clean (rc=0)" \
                 || fail "first tool call after a full sync reports drift (rc=$RC1)"
[ "$RC2" -eq 0 ] && pass "and it stays clean (rc=0), not a permanent SECURITY banner" \
                 || fail "SECURITY drift is permanent (rc=$RC2) -- 23 machines"

echo
echo "=== phase 2: a rebaseliner NAME in prose is not an invocation ==="
# The cost round 13 wrote down was "a command that BOTH makes an unanchorable
# .claude/ write AND names one of the four files". The `.claude` half was never
# required: the raw-text match fired on a comment and on a quoted message.
expect_voids False "name in a trailing COMMENT" \
  "python3 build.py --out dist/*.js  # see kipi-update.sh"
expect_voids False "name inside a quoted PROSE argument" \
  "python3 build.py --out dist/*.js --note 'see kipi-update.sh'"
expect_voids False "name inside a commit MESSAGE" \
  "git commit -m 'fix apply_claude_changes.py' -- q-system/plugins"
expect_rc 0 "the build command is not blocked" \
  "python3 build.py --out dist/*.js  # see kipi-update.sh"
expect_rc 0 "the commit shape this PR's own commits use is not blocked" \
  "git commit -m 'fix apply_claude_changes.py' -- q-system/plugins"

# Every real invocation shape round 13 closed must still void. These are the
# regressions a narrowing buys if it is done by POSITION instead of by NAMING.
expect_voids True "bare invocation"                 "python3 $TRIP --baseline"
expect_voids True "behind an environment assignment" "KIPI_NOTIFY=/usr/bin/true python3 $TRIP --baseline"
expect_voids True "behind env(1) with its own opts"  "env -i KIPI_NOTIFY=x python3 $TRIP --baseline"
expect_voids True "behind nice"                      "nice python3 $TRIP --baseline"
# `timeout 20 ...` below is a STRING handed to the parser under test, never
# executed. The wrapper is exactly what the guard has to see.
expect_voids True "behind timeout with a duration"   "timeout 20 python3 $TRIP --baseline"  # portability-lint-skip
expect_voids True "behind command"                   "command python3 $TRIP --baseline"
expect_voids True "behind nohup"                     "nohup python3 $TRIP --baseline"
expect_voids True "behind stdbuf -oL"                "stdbuf -oL python3 $TRIP --baseline"
expect_voids True "inside an inline code string"     "python3 -c \"import runpy; runpy.run_path('$TRIP')\""
expect_voids True "inside a command substitution"    "echo \$(python3 $TRIP --baseline)"
expect_voids True "the applier, by basename only"    "bash apply-claude-changes.sh p.json"
expect_voids True "an absolute path to the tripwire" "python3 $ROOT/$TRIP --baseline"

echo
echo "=== phase 3: reach needs a component a glob could actually match ==="
# `q-system/*` cannot expand to `q-system/.q-system`: no shell glob matches a
# leading dot unless the pattern writes one. fnmatch does not know that.
expect_voids False "cp with a q-system glob"   "cp -r q-system/* /tmp/backup/"
expect_rc 0     "and it is not blocked"        "cp -r q-system/* /tmp/backup/"
expect_voids False "tar of a q-system glob"    "tar -cf /tmp/b.tar q-system/*"
# Real reach still voids -- these are the round-11/12 pins.
expect_voids True "the baseline by name"       "rm q-system/.q-system/claude-integrity-baseline.json"
expect_voids True "a containing directory"     "rm -rf q-system"
expect_voids True "a DOTTED glob that can match" "rm -rf q-system/.q-*"
expect_voids True "a glob on the last component" "rm q-system/.q-system/claude-integrity-*.json"

echo
echo "=== phase 4: a read-only gh subcommand is a read ==="
expect_rc 0 "gh pr diff with a .claude pathspec"  "gh pr diff 85 -- .claude/settings.json"
expect_rc 0 "gh pr view with a .claude pathspec"  "gh pr view 85 -- .claude/settings.json"
# A gh that CAN write there is still refused: the allowlist is subcommands with
# no file-writing channel, the same claim READ_ONLY makes (round 10).
expect_rc 2 "gh release download into .claude"    "gh release download v1 -D .claude"
expect_rc 2 "an unknown gh subcommand"            "gh frobnicate .claude/settings.json"

echo
echo "=== phase 5: the pins that must survive ==="
expect_rc 2 "round 13: env prefix + unanchorable write" \
  "touch \$UNSET/.claude/rules/pwn.md; KIPI_NOTIFY=/usr/bin/true python3 $TRIP --baseline"
expect_rc 2 "round 8: plain re-baseline + unanchorable write" \
  "touch \$UNSET/.claude/rules/pwn.md; python3 $TRIP --baseline"
expect_rc 2 "round 11: baseline deletion + unanchorable write" \
  "touch \$UNSET/.claude/rules/pwn.md; rm q-system/.q-system/claude-integrity-baseline.json"
expect_rc 2 "direct redirect into .claude/"        "printf x > .claude/settings.json"
expect_rc 2 "process substitution into sanctioned" \
  "bash q-system/.q-system/scripts/apply-claude-changes.sh <(touch .claude/evil.txt)"
expect_rc 2 "awk system() write"                   "awk 'BEGIN{system(\"touch .claude/x\")}'"
expect_rc 2 "sanctioned name in a comment beside a real write" \
  "touch .claude/evil.txt  # apply-claude-changes.sh"
expect_rc 0 "reading a rule"                       "cat .claude/rules/security.md"
expect_rc 0 "piping a file into awk"               "cat .claude/settings.json | awk '{print \$1}'"
expect_rc 0 "an ordinary commit"                   "git commit -m 'ordinary message'"

echo
echo "passed=$PASS failed=$FAIL"
# phase 0 is the negative self-test and is expected to fail, always.
[ "$FAIL" -le 1 ] || exit 1
exit 0
