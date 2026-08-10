#!/usr/bin/env bash
# probe_round7_findings.sh -- reproducer for the round-7 Codex finding on PR #85
# (ASK-291). Written BEFORE the fix; every blocker phase was observed RED first.
#
#   1 blocker  the sanctioned-command bypass is still live through PROCESS
#              substitution. Round 6 closed `$(...)` and backticks; `<(...)` and
#              `>(...)` run the same way, before the visible program is exec'd,
#              and the extractor never looked at them.
#
# The shape:  bash <sanctioned>.sh <(touch .claude/evil.txt)
# `_is_sanctioned` matches argv[0]/argv[1], `_stage` returns `ok` without reading
# an argument, and the process-substitution body was never extracted -- so the
# body mutates the tree and the sanctioned tool's own re-baseline then records
# the mutation as the trusted state. Exactly the round-6 defect through a second
# door.
#
# Ground truth for which shapes bash actually RUNS was measured, not assumed
# (see phase 3): `<(x)` and `>(x)` are live unquoted and ADJACENT to the previous
# word, and are inert inside BOTH single and double quotes -- unlike `$(x)`,
# which stays live inside double quotes. That asymmetry is the whole reason this
# scan is a separate branch and not a wider character class.
#
# Negative self-test: --self-test rebuilds the PRE-FIX guard (PROC_SUB_OPENERS
# emptied in a COPY) and asserts the blocker cases go THROUGH it. A probe whose
# self-test cannot fail pins nothing -- round 5 shipped one inert case.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
SCRIPTS="$REPO/q-system/.q-system/scripts"
# Switches are FLAGS, not `VAR=x bash probe.sh` env prefixes: this repo's other
# gates refuse an assignment-prefixed command line (measured, ASK-291 round 6).
#   --self-test      judge against the reconstructed PRE-FIX guard
#   --guard <path>   judge a COPY, so a bad patch never touches the live guard
SELF_TEST=0
GUARD="$SCRIPTS/claude-path-write-guard.py"
while [ $# -gt 0 ]; do
  case "$1" in
    --self-test) SELF_TEST=1; shift ;;
    --guard)     GUARD="$2"; shift 2 ;;
    *)           printf 'unknown flag: %s\n' "$1"; exit 2 ;;
  esac
done
TRIP="$SCRIPTS/claude-integrity-tripwire.py"
APPLY="$SCRIPTS/apply-claude-changes.sh"

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
# --self-test empties PROC_SUB_OPENERS in a COPY, which is exactly the pre-fix
# behaviour: `$(` and backticks still extracted, process substitutions not. The
# production file carries no test switch -- a guard with a "behave like the old
# version" flag is a hole, not a fixture.
if [ "$SELF_TEST" = "1" ]; then
  GUARD_COPY="$WORK/guard_prefix.py"
  python3 - "$GUARD" "$GUARD_COPY" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
pat = re.compile(r'^PROC_SUB_OPENERS = \([^)]*\)$', re.M)
if not pat.search(src):
    sys.exit("self-test cannot find PROC_SUB_OPENERS to empty")
src = pat.sub("PROC_SUB_OPENERS = ()", src, count=1)
open(sys.argv[2], "w").write(src)
PY
  [ -s "$GUARD_COPY" ] || { echo "self-test rebuild failed"; exit 1; }
  GUARD="$GUARD_COPY"
  printf 'SELF_TEST: judging against the reconstructed PRE-FIX guard\n'
fi

guard_rc() { # command, cwd -> exit code
  CMD="$1" CWD="$2" python3 - <<'PY' | python3 "$GUARD" >/dev/null 2>&1; echo $?
import json, os
print(json.dumps({"tool_name": "Bash",
                  "tool_input": {"command": os.environ["CMD"]},
                  "cwd": os.environ["CWD"]}))
PY
}
assert_block() { # desc, command, cwd  -- a BLOCKER case
  local rc; rc="$(guard_rc "$2" "$3")"
  [ "$rc" = "2" ] && pass "$1" || bfail "$1 (expected block=2, got $rc)"
}
assert_allow() { # desc, command, cwd  -- a false-block case
  local rc; rc="$(guard_rc "$2" "$3")"
  [ "$rc" = "0" ] && pass "$1" || fail "$1 (expected allow=0, got $rc)"
}

# ------------------------------------------------------------- tripwire fixture
make_repo() { # base -> prints the worktree path
  local base="$1" origin="$1/origin.git" work="$1/work"
  mkdir -p "$base"
  git init --bare -q -b main "$origin"
  git init -q -b main "$work"
  git -C "$work" config user.email probe@local
  git -C "$work" config user.name probe
  mkdir -p "$work/.claude/rules"
  printf '{"hooks":{}}\n'  > "$work/.claude/settings.json"
  printf 'original rule\n' > "$work/.claude/rules/r.md"
  git -C "$work" add -A >/dev/null
  git -C "$work" commit -qm init
  git -C "$work" remote add origin "$origin"
  git -C "$work" push -q -u origin main
  git -C "$work" remote set-head origin main >/dev/null 2>&1
  echo "$work"
}

CJ=".claude"           # assembled so this probe's own text carries no literal
RUL="$CJ/rules/r.md"   # guarded path in argument position when it is invoked

phase "1 (blocker) a process substitution is a command, not an argument"
W1="$WORK/p1"; mkdir -p "$W1/$CJ"
# Every shape below is redirect-FREE where it matters: the redirect scan at the
# top of _stage runs BEFORE `_is_sanctioned`, so a `$(printf x > .claude/y)`
# shape was already blocked pre-fix and pins nothing. `> >(rm ...)` is included
# precisely because the redirect regex CANNOT read it -- `[^\s;&|<>]+` refuses
# the `>` that opens the substitution, so the target it captures is `(rm`.
assert_block "sanctioned .sh + <( ) creating a file" \
  "bash $APPLY <(touch $CJ/evil.txt)" "$W1"
assert_block "sanctioned .py + <( ) in a --root argument" \
  "python3 $TRIP --baseline --root <(touch $CJ/evil.txt)" "$W1"
assert_block ">( ) output substitution behind a sanctioned argv" \
  "bash $APPLY p.json > >(rm $RUL)" "$W1"
assert_block "process substitution nested inside a command substitution" \
  "bash $APPLY \"\$(cat <(touch $CJ/evil.txt))\"" "$W1"
assert_block "unsanctioned reader, substitution still judged" \
  "cat <(rm $RUL)" "$W1"
assert_block "two substitutions, the second one writes" \
  "diff <(cat $CJ/settings.json) <(cp $CJ/settings.json $RUL)" "$W1"

phase "2 (blocker) end-to-end: the tamper must never reach the baseline"
W2="$(make_repo "$WORK/p2")"
python3 "$TRIP" --root "$W2" --baseline --quiet
# `cat <(cp A B)` is deterministic: cat blocks on the fd until cp exits, so the
# tamper is complete before `pwd` is read and before the tripwire re-baselines.
ATTACK="python3 $TRIP --root \"\$(cat <(cp $CJ/settings.json $RUL); pwd)\" --baseline --quiet"
RC2="$(guard_rc "$ATTACK" "$W2")"
if [ "$RC2" = "2" ]; then
  pass "guard refuses the compose-and-baseline attack"
else
  # Guard allowed it. Run it for real and show what that buys the attacker: the
  # tampered rule becomes the trusted baseline, so Layer 2 reports clean.
  ( cd "$W2" && eval "$ATTACK" ) >/dev/null 2>&1
  CHECK="$(python3 "$TRIP" --root "$W2" --check 2>&1)"
  printf '    tampered rule now reads: %s\n' "$(tr '\n' ' ' < "$W2/$RUL")"
  printf '    tripwire --check says:   %s\n' "$CHECK"
  bfail "guard allowed it (rc=$RC2) and the tamper was baselined as trusted"
fi

phase "3 (no false block) the shapes bash does NOT run stay allowed"
W3="$(make_repo "$WORK/p3")"
# Measured, not assumed: `bash -c 'echo "<(touch f)"'` prints the text and
# creates nothing, and the single-quoted form likewise. Judging an inert body is
# the false-block class this issue has already hit five times -- it would refuse
# the very comment reporting this fix.
assert_allow "double-quoted <( ) is inert text" \
  "echo \"<(touch $CJ/evil.txt)\"" "$W3"
assert_allow "single-quoted <( ) is inert text" \
  "echo 'the <(rm $RUL) shape'" "$W3"
assert_allow "prose in a commit message naming the shape" \
  "git commit -m \"round 7: judge <(touch $CJ/evil.txt) as a command\"" "$W3"
assert_allow "legitimate diff of two substitutions" \
  "diff <(git show HEAD:.gitignore) <(pwd)" "$W3"
# Arithmetic `$((a>(b)))` re-enters the extractor as the body `(a>(b))`, where
# `>(` is a comparison, not a substitution. The over-extraction is named in the
# guard and costs nothing: the body is judged as the statement `1`.
assert_allow "arithmetic comparison is not an output substitution" \
  "bash $APPLY p.json --retries \"\$((3>(1)))\"" "$W3"

phase "4 (extractor) the scan's own boundaries, asserted directly"
python3 - "$GUARD" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("guard", sys.argv[1])
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
ok = fails = 0
def eq(desc, got, want):
    global ok, fails
    if got == want:
        ok += 1; print("  PASS  %s" % desc)
    else:
        fails += 1; print("  FAIL  %s (got %r, want %r)" % (desc, got, want))

eq("input substitution extracted",
   g.extract_substitutions("bash a.sh <(touch x)"), ["touch x"])
eq("output substitution extracted",
   g.extract_substitutions("tee >(cat > y)"), ["cat > y"])
eq("two on one line, both extracted",
   g.extract_substitutions("diff <(a) <(b)"), ["a", "b"])
# Unlike `$(`, a process substitution is inert inside DOUBLE quotes too.
eq("double-quoted body is inert",
   g.extract_substitutions('echo "<(touch x)"'), [])
eq("single-quoted body is inert",
   g.extract_substitutions("echo 'the <(touch x) shape'"), [])
eq("nested inside a command substitution, flat",
   g.extract_substitutions("$(cat <(touch x))"), ["cat <(touch x)", "touch x"])
eq("command substitution nested inside a process one",
   g.extract_substitutions('cat <(echo "$(touch x)")'),
   ['echo "$(touch x)"', "touch x"])
eq("unterminated <( fails closed onto the tail",
   g.extract_substitutions("bash a.sh <(touch x"), ["touch x"])
print("EXTRACTOR: %d passed, %d failed" % (ok, fails))
sys.exit(1 if fails else 0)
PY
if [ $? -eq 0 ]; then pass "extractor boundaries"; else fail "extractor boundaries"; fi

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
