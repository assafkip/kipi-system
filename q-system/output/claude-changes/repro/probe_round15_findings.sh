#!/usr/bin/env bash
# Reproducer for PR #85 round 15 (1 major).
#
# THE FINDING, in the reviewer's words:
#
#   major  "An exact guard filename passed as ordinary argument data is still
#          classified as a re-baseliner invocation, falsely blocking unattended
#          commands containing globs"
#          (claude-path-write-guard.py:1289).
#
# CONFIRMED. Round 14 narrowed the round-13 raw substring match to "some token
# whose BASENAME is the name", which dropped a comment and a multi-word prose
# phrase. It did not drop a bare filename sitting in an option's VALUE:
#
#     git commit -m claude-integrity-tripwire.py -- q-system/*      BLOCKED
#     python3 build.py --label claude-integrity-tripwire.py --out dist/*.js
#                                                                  BLOCKED
#
# Both are one token whose basename IS the name, and neither executes anything.
# The quoted-phrase form of the same message is allowed, so the guard's answer
# depends on whether the operator happened to put quotes around a value -- which
# is the tell that the test is measuring spelling, not behaviour.
#
# WHAT DONE LOOKS LIKE (stated before the fix, per verification-loops):
#   phase 1  the two reviewer vectors do not void Layer 2 and are not blocked,
#            and neither is the same shape wearing other clothes.
#   phase 2  every invocation shape rounds 8-14 closed STILL voids: bare, behind
#            an assignment, behind env(1), behind nice/timeout/command/nohup/
#            stdbuf, inside an inline code string, inside a substitution, by
#            basename, by absolute path, and handed to a stdin sink over a pipe.
#   phase 3  the named cost of the narrowing, pinned as blocks so a later
#            round reads a decision rather than an accident.
#   phase 4  the round 8-14 pins that must survive, re-run here.
#
# NEGATIVE SELF-TEST: phase 0 asserts a verdict that is wrong today and wrong
# after the fix, so a harness that cannot fail is visible as such.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
GUARD="$ROOT/q-system/.q-system/scripts/claude-path-write-guard.py"
TRIP="q-system/.q-system/scripts/claude-integrity-tripwire.py"
BASE="q-system/.q-system/claude-integrity-baseline.json"
PASS=0; FAIL=0

pass() { PASS=$((PASS+1)); printf 'ok    %s\n' "$1"; }
fail() { FAIL=$((FAIL+1)); printf 'FAIL  %s\n' "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

rc_of() { # cmd [cwd] -> rc, stderr in $WORK/err
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
echo "=== phase 1: a filename in an option VALUE is data, not an invocation ==="
# The reviewer's two vectors, verbatim.
expect_voids False "commit message is a bare filename token" \
  "git commit -m claude-integrity-tripwire.py -- q-system/*"
expect_voids False "option value is a bare filename token" \
  "python3 build.py --label claude-integrity-tripwire.py --out dist/*.js"
expect_rc 0 "the commit is not blocked" \
  "git commit -m claude-integrity-tripwire.py -- q-system/*"
expect_rc 0 "the build is not blocked" \
  "python3 build.py --label claude-integrity-tripwire.py --out dist/*.js"

# The same shape with the other three rebaseliners and other data positions.
expect_voids False "a --file= value naming the applier" \
  "python3 build.py --manifest=apply_claude_changes.py --out dist/*.js"
expect_voids False "a filename as a plain operand of a non-executor" \
  "grep -n kipi-update.sh docs/*.md"
expect_voids False "a filename passed to a diff tool" \
  "git log --oneline -- kipi-update.sh q-system/*"
expect_voids False "the baseline named by a rebaseliner-free build" \
  "python3 build.py --label apply-claude-changes.sh --out dist/*.js"

echo
echo "=== phase 2: every invocation shape rounds 8-14 closed still voids ==="
expect_voids True "bare invocation"                  "python3 $TRIP --baseline"
expect_voids True "behind an environment assignment" "KIPI_NOTIFY=/usr/bin/true python3 $TRIP --baseline"
expect_voids True "behind env(1) with its own opts"  "env -i KIPI_NOTIFY=x python3 $TRIP --baseline"
expect_voids True "behind nice"                      "nice python3 $TRIP --baseline"
expect_voids True "behind timeout with a duration"   "timeout 20 python3 $TRIP --baseline"  # portability-lint-skip
expect_voids True "behind command"                   "command python3 $TRIP --baseline"
expect_voids True "behind nohup"                     "nohup python3 $TRIP --baseline"
expect_voids True "behind stdbuf -oL"                "stdbuf -oL python3 $TRIP --baseline"
expect_voids True "inside an inline code string"     "python3 -c \"import runpy; runpy.run_path('$TRIP')\""
expect_voids True "inside a command substitution"    "echo \$(python3 $TRIP --baseline)"
expect_voids True "the applier, by basename only"    "bash apply-claude-changes.sh p.json"
expect_voids True "an absolute path to the tripwire" "python3 $ROOT/$TRIP --baseline"
expect_voids True "an assignment VALUE names one"    "TOOL=$TRIP sh -c 'true'"
expect_voids True "direct exec, no interpreter"      "./$TRIP --register .claude/settings.json"
expect_voids True "direct exec behind a wrapper"     "nice ./$TRIP --register .claude/settings.json"
# The name never sits in an executable slot here: it is echo's argument. The
# stage that RUNS it reads its program from stdin, which this parser cannot
# follow, so a sink downstream of a pipe restores the any-position test.
expect_voids True "handed to a stdin sink over a pipe" \
  "echo $TRIP | xargs python3"
expect_voids True "handed to a sink over a pipe, other order" \
  "printf '%s' $TRIP | xargs -I{} python3 {} --baseline"
# Reach for the baseline FILE is not an invocation question -- rm, mv and a
# redirect all reach it from argument position -- so that test is unchanged.
expect_voids True "the baseline named as rm's operand"  "rm -f $BASE"
expect_voids True "the baseline named in a data slot"   "git commit -m $BASE -- q-system/plugins"

echo
echo "=== phase 3: the named cost of this narrowing ==="
# A pipeline whose other stage is a sink cannot be read further, so any
# path-shaped mention in it still voids. Charged where it is written.
expect_voids True "a mention in a pipeline that feeds a sink" \
  "git log --oneline -- kipi-update.sh | tee /tmp/out.log"
# ...and the same pipeline WITHOUT a sink does not pay it.
expect_voids False "the same mention in a sink-free pipeline" \
  "git log --oneline -- kipi-update.sh | grep fix"

echo
echo "=== phase 4: the round 8-14 pins that must survive ==="
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
expect_rc 2 "a plain .claude write is still blocked" \
  "printf pwned > .claude/rules/pwn.md"
expect_rc 2 "round 8: unanchorable write plus a same-call re-baseline" \
  "touch \$UNSET/.claude/rules/pwn.md; python3 $TRIP --register .claude/rules/pwn.md"
expect_voids True "round 11: the baseline deleted by a variable" \
  "B=$BASE; rm -f \$B"
expect_rc 0 "round 14: a read-only gh with a .claude pathspec" \
  "gh pr diff 85 -- .claude/settings.json"
expect_rc 0 "round 14: a glob does not cross a leading dot" \
  "cp -r q-system/* /tmp/backup/"

echo
printf 'passed=%d failed=%d\n' "$PASS" "$FAIL"
[ "$FAIL" -le 1 ]
