#!/usr/bin/env bash
# probe_round6_findings.sh -- reproducer for the round-6 Codex finding on PR #85
# (ASK-291). Written BEFORE the fix; every phase was observed RED first.
#
#   1 blocker  a sanctioned script name bypasses argument inspection, so a
#              command substitution inside that same call mutates .claude/ AND
#              the sanctioned tool then baselines the mutation as trusted --
#              both layers defeated in ONE Bash call.
#
# The shape:  bash <sanctioned>.sh "$(printf pwned > .claude/rules/r.md)"
# `_is_sanctioned` matches on argv[0]/argv[1], _stage returns `ok` immediately,
# and the substitution body is never parsed at all. Worse, the substitution runs
# FIRST (the shell expands before it execs), so the sanctioned tool's own
# re-baseline records the tampered content as the trusted state.
#
# Negative self-test: SELF_TEST=1 rebuilds the PRE-FIX guard (the substitution
# scan neutered to return nothing) and asserts the attack passes it with rc=0.
# A probe that cannot fail is not a probe -- round 5 shipped one inert case.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
SCRIPTS="$REPO/q-system/.q-system/scripts"
# Switches are FLAGS, not `VAR=x bash probe.sh` env prefixes: this repo's other
# gates refuse an assignment-prefixed command line, so the env form could not be
# run here at all (measured, ASK-291 round 6).
#   --self-test      judge against the reconstructed PRE-FIX guard
#   --guard <path>   judge a COPY, so a bad patch never touches the live guard
#                    (it is self-watched by Layer 2: a bad write there costs a
#                    revert-and-quarantine cycle, a copy costs nothing)
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
passed=0; failed=0
pass() { passed=$((passed+1)); printf '  PASS  %s\n' "$1"; }
fail() { failed=$((failed+1)); printf '  FAIL  %s\n' "$1"; }
phase() { printf '\n== %s ==\n' "$1"; }

# ------------------------------------------------------------- guard under test
# SELF_TEST=1 reconstructs the pre-fix guard by neutering the substitution
# extractor in a COPY. The production file carries no test switch: a guard with
# a "behave like the old version" flag is a hole, not a fixture.
if [ "$SELF_TEST" = "1" ]; then
  GUARD_COPY="$WORK/guard_prefix.py"
  python3 - "$GUARD" "$GUARD_COPY" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
pat = re.compile(r"^def extract_substitutions\(text\):\n(    .*\n|\n)*", re.M)
if not pat.search(src):
    sys.exit("self-test cannot find extract_substitutions to neuter")
src = pat.sub("def extract_substitutions(text):\n    return []\n\n\n", src, count=1)
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
assert_block() { # desc, command, cwd
  local rc; rc="$(guard_rc "$2" "$3")"
  [ "$rc" = "2" ] && pass "$1" || fail "$1 (expected block=2, got $rc)"
}
assert_allow() { # desc, command, cwd
  local rc; rc="$(guard_rc "$2" "$3")"
  [ "$rc" = "0" ] && pass "$1" || fail "$1 (expected allow=0, got $rc)"
}

# ------------------------------------------------------------- tripwire fixture
# A repo with a real remote whose default branch is known: head_is_reviewed() is
# defined against `<remote>/HEAD`, and phase 2 asserts on what the tripwire
# TRUSTS, so the provenance side has to be real (round-5 regression).
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

CJ=".claude"   # assembled so this probe's own text carries no literal guarded
RUL="$CJ/rules/r.md"   # path in argument position when it is invoked

phase "1 (blocker) a sanctioned argv must not exempt its substitutions"
W1="$WORK/p1"; mkdir -p "$W1/$CJ"
# NOTE on the shapes below: every one is redirect-FREE on purpose. The redirect
# scan at the top of _stage runs BEFORE `_is_sanctioned`, so `$(printf x >
# .claude/y)` was already blocked pre-fix and pins nothing. The bypass is the
# writes that need argument inspection to see -- touch, rm, cp, mv.
assert_block "sanctioned .sh + \$( ) creating a file" \
  "bash $APPLY \"\$(touch $CJ/evil.txt)\"" "$W1"
assert_block "sanctioned .py + \$( ) re-rooting through a write" \
  "python3 $TRIP --baseline --root \"\$(touch $CJ/evil.txt; pwd)\"" "$W1"
assert_block "backtick substitution, same bypass" \
  "bash $APPLY \`rm $RUL\`" "$W1"
assert_block "nested substitution inside a benign outer one" \
  "bash $APPLY \"\$(echo \"\$(touch $CJ/evil.txt)\")\"" "$W1"
assert_block "leading assignment carries the payload" \
  "X=\"\$(touch $CJ/evil.txt)\" bash $APPLY p.json" "$W1"
assert_block "sanctioned stage disarms the pipeline rule too" \
  "bash $APPLY p.json | grep \"\$(touch $CJ/evil.txt)\"" "$W1"
# The same shapes must block with NO sanctioned name in sight, or the fix is
# only patching the one entrypoint the finding happened to name.
assert_block "unsanctioned outer, substitution still judged" \
  "echo \"\$(rm $RUL)\"" "$W1"

phase "2 (blocker) end-to-end: the tamper must never reach the baseline"
W2="$(make_repo "$WORK/p2")"
python3 "$TRIP" --root "$W2" --baseline --quiet
# Redirect-free (see the note in phase 1): `cp` rewrites the watched rule with
# other content, which is a tamper Layer 2 would catch -- if the same call did
# not then re-baseline it as the trusted state.
ATTACK="python3 $TRIP --root \"\$(cp $CJ/settings.json $RUL; pwd)\" --baseline --quiet"
RC2="$(guard_rc "$ATTACK" "$W2")"
if [ "$RC2" = "2" ]; then
  pass "guard refuses the compose-and-baseline attack"
else
  # Guard allowed it. Run it for real and show what that buys the attacker:
  # the tampered rule is now the trusted baseline, so Layer 2 reports clean.
  ( cd "$W2" && eval "$ATTACK" ) >/dev/null 2>&1
  CHECK="$(python3 "$TRIP" --root "$W2" --check 2>&1)"
  printf '    tampered rule now reads: %s\n' "$(cat "$W2/$RUL" | tr '\n' ' ')"
  printf '    tripwire --check says:   %s\n' "$CHECK"
  fail "guard allowed it (rc=$RC2) and the tamper was baselined as trusted"
fi

phase "3 (no false block) legitimate substitutions stay allowed"
W3="$(make_repo "$WORK/p3")"
assert_allow "sanctioned apply with a \$(pwd) proposal path" \
  "bash $APPLY \"\$(pwd)/proposal.json\"" "$W3"
assert_allow "tripwire --check rooted at \$(git rev-parse ...)" \
  "python3 $TRIP --check --root \"\$(git rev-parse --show-toplevel)\"" "$W3"
assert_allow "substitution whose body only READS a guarded file" \
  "bash $APPLY \"\$(cat $CJ/settings.json)\"" "$W3"
assert_allow "arithmetic expansion is not a command substitution" \
  "bash $APPLY p.json --retries \"\$((1 + 2))\"" "$W3"

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

eq("plain $( ) body extracted",
   g.extract_substitutions('a "$(touch x)" b'), ["touch x"])
eq("live inside double quotes, and nested bodies come out flat",
   g.extract_substitutions('"$(echo "$(touch x)")"'), ['echo "$(touch x)"', "touch x"])
eq("backticks extracted",
   g.extract_substitutions("a `touch x` b"), ["touch x"])
# Single quotes make a substitution INERT. Judging it would be the sixth false
# block of the class this issue keeps hitting: prose that merely QUOTES the
# attack shape (this probe's own report, for one) is not the attack.
eq("single-quoted body is inert",
   g.extract_substitutions("git commit -m 'text about $(touch x)'"), [])
eq("escaped dollar is inert",
   g.extract_substitutions('echo "\\$(touch x)"'), [])
# Fail closed: an opener with no closer still hands the tail over to be judged,
# rather than being dropped the way round-2's heredoc code dropped its tail.
eq("unterminated $( fails closed onto the tail",
   g.extract_substitutions('bash a.sh "$(touch x'), ["touch x"])
eq("a quoted-delimiter heredoc body does not expand",
   g.extract_substitutions("cat <<'EOF'\n$(touch x)\nEOF\n"), [])
eq("an unquoted heredoc body DOES expand",
   g.extract_substitutions("cat <<EOF\n$(touch x)\nEOF\n"), ["touch x"])
print("EXTRACTOR: %d passed, %d failed" % (ok, fails))
sys.exit(1 if fails else 0)
PY
if [ $? -eq 0 ]; then pass "extractor boundaries"; else fail "extractor boundaries"; fi

printf '\nRESULT: %d passed, %d failed\n' "$passed" "$failed"
[ "$failed" -eq 0 ] || exit 1
