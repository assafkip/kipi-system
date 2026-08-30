#!/usr/bin/env bash
# Reproducer for PR #85 round 13 (BLOCKER).
#
# THE FINDING, in the reviewer's words: "An environment assignment before a
# re-baselining command hides the executable, allowing a same-call .claude tamper
# to be permanently recorded as trusted" (claude-path-write-guard.py:1109).
# Their measurement:
#
#     command=touch $UNSET/.claude/rules/pwn.md; KIPI_NOTIFY=/usr/bin/true python3 <trip> --baseline --quiet
#     voids_layer2=False
#     guard_reason=None
#     trusted_sha=pwned
#     next_enforce_rc=0
#
# CONFIRMED. `_program_names()` reads argv[0] literally, so `KIPI_NOTIFY=/usr/bin/true`
# IS the program as far as it is concerned (its basename is `true`, which is not
# an interpreter, so argv[1] is never consulted either). `_voids_layer2` therefore
# never sees the tripwire, hands the unanchorable `.claude/` write off to a
# backstop the same command erases, and the tamper is baselined as trusted.
#
# THE ASYMMETRY IS THE BUG. `_stage()` has stripped leading `VAR=value` tokens
# since round 2 (see its "Leading VAR=value assignments" loop). `_program_names`
# never did. One file, two answers to "what is argv[0]", which is the exact
# failure mode `_program_names`'s own docstring was written to prevent.
#
# WHAT DONE LOOKS LIKE (stated before the fix, per verification-loops):
#   phase 1  the reviewer's verbatim vector voids Layer 2 and is BLOCKED end to end
#   phase 2  the CLASS is caught, not the spelling: every prefix that can stand
#            between the shell and the executable -- assignments, `env` with its
#            own options and assignments, and the ordinary wrapper programs
#            (nice/timeout/command/nohup/stdbuf) that are real producer shapes
#            in this repo
#   phase 3  `_program_names` itself finds the executable behind each prefix, so
#            the two callers keep asking ONE question of ONE position
#   phase 4  THE FALSE BLOCKS STAY DEAD. `KIPI_NOTIFY=... <trip> --enforce` with
#            no `.claude/` write is a real shape in probe_update_interaction.sh:50
#            and must stay allowed; so must an env-prefixed sanctioned applier,
#            which today is falsely blocked for the same reason the hole exists.
#   phase 5  THE EXEMPTION DOES NOT WIDEN. A sanctioned name that is not in the
#            program position (an assignment VALUE, an argument, a comment) must
#            still not sanction anything -- that is round 2's blocker, and a fix
#            that skips tokens carelessly re-opens it.
#
# NEGATIVE SELF-TEST: phase 0 asserts a verdict that is wrong today and wrong
# after the fix, so a harness that cannot fail is visible as such.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
GUARD="$ROOT/q-system/.q-system/scripts/claude-path-write-guard.py"
TRIP="q-system/.q-system/scripts/claude-integrity-tripwire.py"
APPLY="q-system/.q-system/scripts/apply-claude-changes.sh"
PASS=0; FAIL=0

pass() { PASS=$((PASS+1)); printf 'ok    %s\n' "$1"; }
fail() { FAIL=$((FAIL+1)); printf 'FAIL  %s\n' "$1"; }

# --- unit probes: the parser itself, no filesystem, no hook envelope ----------
voids() { # cmd cwd -> True/False
  GUARD="$GUARD" python3 -c '
import importlib.util, os, sys
s = importlib.util.spec_from_file_location("g", os.environ["GUARD"])
g = importlib.util.module_from_spec(s); s.loader.exec_module(g)
print(g._voids_layer2(sys.argv[1], sys.argv[2]))
' "$1" "$2" 2>/dev/null
}

progs() { # cmd -> space-joined program-name candidates
  GUARD="$GUARD" python3 -c '
import importlib.util, os, shlex, sys
s = importlib.util.spec_from_file_location("g", os.environ["GUARD"])
g = importlib.util.module_from_spec(s); s.loader.exec_module(g)
print(" ".join(g._program_names(shlex.split(sys.argv[1]))))
' "$1" 2>/dev/null
}

sanctioned() { # cmd -> True/False
  GUARD="$GUARD" python3 -c '
import importlib.util, os, shlex, sys
s = importlib.util.spec_from_file_location("g", os.environ["GUARD"])
g = importlib.util.module_from_spec(s); s.loader.exec_module(g)
print(g._is_sanctioned(shlex.split(sys.argv[1])))
' "$1" 2>/dev/null
}

# --- end-to-end probe: the real hook, real stdin envelope, real rc ------------
run_at() { # cmd cwd -> rc
  python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]},"cwd":sys.argv[2]}))' "$1" "$2" \
    | CLAUDE_PROJECT_DIR="$ROOT" python3 "$GUARD" >/dev/null 2>&1
  echo $?
}

expect_voids() { # want desc cmd
  local want="$1" desc="$2" got
  got="$(voids "$3" "$ROOT")"
  [ "$got" = "$want" ] && pass "$desc (voids=$got)" || fail "$desc (voids=$got want=$want)"
}

expect_rc() { # want desc cmd
  local want="$1" desc="$2" got
  got="$(run_at "$3" "$ROOT")"
  [ "$got" = "$want" ] && pass "$desc (rc=$got)" || fail "$desc (rc=$got want=$want)"
}

expect_prog() { # wanted-name desc cmd
  local want="$1" desc="$2" got
  got="$(progs "$3")"
  case " $got " in
    *" $want "*) pass "$desc (progs='$got')" ;;
    *)           fail "$desc (progs='$got' want to contain '$want')" ;;
  esac
}

expect_sanctioned() { # want desc cmd
  local want="$1" desc="$2" got
  got="$(sanctioned "$3")"
  [ "$got" = "$want" ] && pass "$desc (sanctioned=$got)" || fail "$desc (sanctioned=$got want=$want)"
}

# The unanchorable `.claude/` write the handoff is about: `resolve()` returns
# None, so Layer 1 lets it through ON THE GROUND that Layer 2 will revert it.
# Every vector below pairs it with a re-baseline in the SAME call, which is what
# falsifies that ground.
W='touch $UNSET/.claude/rules/pwn.md'

echo "=== phase 0: negative self-test (this harness must be able to fail) ==="
got="$(voids "echo hello" "$ROOT")"
if [ "$got" = "True" ]; then
  fail "negative self-test: a bare echo must NOT void Layer 2"
else
  pass "negative self-test asserted a false claim and the harness counted it"
  FAIL=$((FAIL+1)); PASS=$((PASS-1))
  printf '      (deliberate: one FAIL is injected here, expected total FAIL=1)\n'
fi

echo
echo "=== phase 1: the reviewer's verbatim vector ==="
VECTOR="$W; KIPI_NOTIFY=/usr/bin/true python3 $TRIP --baseline --quiet"
expect_voids True "reviewer's vector voids Layer 2" "$VECTOR"
expect_rc    2    "reviewer's vector is BLOCKED end to end" "$VECTOR"

echo
echo "=== phase 2: the class -- every prefix that can hide the executable ==="
expect_voids True "one leading assignment"        "$W; KIPI_NOTIFY=/usr/bin/true python3 $TRIP --baseline"
expect_voids True "two leading assignments"       "$W; A=1 B=2 python3 $TRIP --baseline"
expect_voids True "env with an assignment"        "$W; env KIPI_NOTIFY=/usr/bin/true python3 $TRIP --baseline"
expect_voids True "env -i"                        "$W; env -i python3 $TRIP --baseline"
expect_voids True "env -u NAME (separated value)" "$W; env -u KIPI_NOTIFY python3 $TRIP --baseline"
expect_voids True "env --unset=NAME"              "$W; env --unset=KIPI_NOTIFY python3 $TRIP --baseline"
expect_voids True "env -- after its options"      "$W; env -i -- python3 $TRIP --baseline"
expect_voids True "assignment in front of env"    "$W; A=1 env B=2 python3 $TRIP --baseline"
expect_voids True "--register, not --baseline"    "$W; KIPI_NOTIFY=/usr/bin/true python3 $TRIP --register .claude/rules/pwn.md"
expect_voids True "the applier behind a prefix"   "$W; KIPI_NOTIFY=x bash $APPLY p.json"
expect_voids True "nice"                          "$W; nice python3 $TRIP --baseline"
# `timeout` below is PARSER INPUT, never executed: the guard is a text classifier
# and this string is handed to it as data, so a portable rewrite would change the
# very shape under test.
expect_voids True "timeout with its duration"     "$W; timeout 20 python3 $TRIP --baseline"  # portability-lint-skip
expect_voids True "command"                       "$W; command python3 $TRIP --baseline"
expect_voids True "nohup"                         "$W; nohup python3 $TRIP --baseline"
expect_voids True "stdbuf with an option"         "$W; stdbuf -oL python3 $TRIP --baseline"

echo
echo "=== phase 3: _program_names finds the executable behind the prefix ==="
expect_prog "claude-integrity-tripwire.py" "assignment prefix"  "KIPI_NOTIFY=/usr/bin/true python3 $TRIP --baseline"
expect_prog "claude-integrity-tripwire.py" "env + assignment"   "env KIPI_NOTIFY=/usr/bin/true python3 $TRIP --baseline"
expect_prog "claude-integrity-tripwire.py" "env -u NAME"        "env -u KIPI_NOTIFY python3 $TRIP --baseline"
expect_prog "python3"                      "argv[0] after strip" "A=1 B=2 python3 $TRIP --baseline"
expect_prog "touch"                        "plain command still read" "touch .claude/x"

echo
echo "=== phase 4: the false blocks stay dead ==="
# probe_update_interaction.sh:50 is exactly this shape. It re-baselines, but with
# no `.claude/` write beside it there is nothing being handed off, so it is
# allowed -- round 8 priced the cost as "only ever charged alongside an
# unanchorable .claude/ write" and that price must not go up.
expect_rc 0 "env-prefixed --enforce alone"     "KIPI_NOTIFY=/usr/bin/true python3 $TRIP --enforce --quiet"
expect_rc 0 "env-prefixed --baseline alone"    "KIPI_NOTIFY=/usr/bin/true python3 $TRIP --baseline --quiet"
expect_rc 0 "an ordinary env-prefixed command" "FOO=bar echo hello"
expect_rc 0 "PATH prefix on a build"           "PATH=/usr/local/bin:\$PATH make test"
expect_rc 0 "reading .claude is not writing"   "cat .claude/settings.json"
# The applier is the SANCTIONED write path. Prefixing it with an environment
# variable must not cost it that status: before this fix `_is_sanctioned` read
# `KIPI_NOTIFY=x` as argv[0] and the sanctioned route was blocked from a shell
# that sets one, which is a different outage of the same acceptance criterion.
expect_sanctioned True "applier behind an assignment" "KIPI_NOTIFY=x bash $APPLY p.json"
expect_sanctioned True "applier behind env"           "env KIPI_NOTIFY=x bash $APPLY p.json"
expect_sanctioned True "bare applier (unchanged)"     "bash $APPLY p.json"

echo
echo "=== phase 5: the exemption does not widen (round 2's blocker stays shut) ==="
# Round 2: `any(s in seg for s in SANCTIONED)` let the NAME anywhere in the text
# disable Layer 1. Skipping tokens to find argv[0] must not become a way to walk
# past a write and land on a sanctioned name further along.
expect_sanctioned False "sanctioned name as an assignment VALUE" "FOO=$APPLY touch .claude/x"
expect_sanctioned False "sanctioned name as an ARGUMENT"         "touch .claude/x $APPLY"
expect_sanctioned False "sanctioned name after env's real cmd"   "env -i touch .claude/x $APPLY"
expect_rc 2 "assignment VALUE naming the applier is still blocked" "FOO=$APPLY touch .claude/x"
expect_rc 2 "sanctioned name as an argument is still blocked"      "touch .claude/x $APPLY"
expect_rc 2 "sanctioned name in a comment is still blocked"        "touch .claude/evil.txt  # $APPLY"

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -le 1 ] || exit 1
