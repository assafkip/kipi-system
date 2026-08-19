#!/usr/bin/env bash
# Reproducer + acceptance for ASK-351: a long-running bash driver corrupts itself
# when the repo it lives in is edited mid-run.
#
# THE DEFECT, measured 2026-08-03. bash does not load a script into memory. It
# reads a chunk, executes one command, then lseeks back to the byte offset just
# past that command for the next one. `converge.sh` runs for hours and
# `linear-worker.sh` for up to 1800s per round, inside a repo that agents edit the
# whole time. An edit shifts every later byte offset, bash resumes parsing mid
# string, and bare words inside quoted strings become commands:
#
#   converge.sh: line 872: of: command not found
#   converge.sh: line 872: not: command not found
#   converge.sh: line 876: syntax error near unexpected token `fi'
#
# Line 872 on disk is `fi`. The words `of` and `not` appear only INSIDE the
# double-quoted STALL_LOG/STALL_PAGE strings at 868 and 871, so no correct read
# can execute them. `bash -n` passes on every committed version -- the file was
# never syntactically wrong. Commit d142466 landed seven minutes into that run.
# ~/.config/kipi/linear-worker.log carries the same signature (`ial: command not
# found`), so this is a class across both drivers, not one bug.
#
# THE FIX UNDER TEST is a `{ ... }` compound command around the whole body with an
# unconditional `exit` as its last statement. bash must parse a compound command
# to completion before executing any of it, so the body is consumed at startup.
#
# WHY THE TRAILING `exit` IS NOT REDUNDANT, and why case 2 exists as its own case:
# a brace wrap ALONE still fails. The body runs and prints its result, then bash
# seeks past the closing brace looking for one more command, lands at a stale
# offset in a file that has grown, and re-executes leftovers. Measured here: the
# braces-only case prints the whole body TWICE and dies rc=2.
#
# HOW THE CASES ARE BUILT. Cases 0-3 are synthetic scripts, not the real drivers:
# the real ones need a live Linear, a gh token and hours of wall clock, and a test
# that drove them would be measuring the fleet rather than this property. What is
# synthetic is the BODY; the mechanism (in-place edit that shifts offsets under a
# running bash) is the real one. Case 0 is the negative self-test -- the same
# unwrapped script with NO edit must come out clean, or a harness that always
# reports red would look like a passing reproducer. Case 4 then holds the two real
# scripts to the shape, and case 5 mutates that structural check against an
# unwrapped copy so it is a check that can actually go red.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
CONVERGE="$ROOT/q-system/.q-system/scripts/converge.sh"
WORKER="$ROOT/q-system/.q-system/scripts/linear-worker.sh"
for f in "$CONVERGE" "$WORKER"; do
  [ -f "$f" ] || { echo "FATAL: missing $f" >&2; exit 1; }
done

WORK="$(mktemp -d)"
cleanup() { [ -n "${WORK:-}" ] && [ -d "$WORK" ] && find "$WORK" -mindepth 1 -delete && rmdir "$WORK"; }
trap cleanup EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

# The body every synthetic case runs. `sleep 3` is the window the edit lands in;
# the quoted line after it is the ASK-351 signature -- bare words that exist ONLY
# inside a string, so anything that executes them proves a slipped offset rather
# than a real syntax error.
EXPECTED='PHASE_TWO_RAN
the words alpha and beta live only inside this quoted string
MARKER_OK'

make_case() {
  # $1 = target path, $2 = plain | braces | bracesexit
  local f="$1" kind="$2"
  {
    echo '#!/usr/bin/env bash'
    [ "$kind" = plain ] || echo '{'
    echo 'set -uo pipefail'
    echo 'sleep 3'
    echo 'echo "PHASE_TWO_RAN"'
    echo 'echo "the words alpha and beta live only inside this quoted string"'
    echo 'echo "MARKER_OK"'
    [ "$kind" = bracesexit ] && echo 'exit 0'
    [ "$kind" = plain ] || echo '}'
  } > "$f"
}

# THE EDIT IS AN INSERT NEAR THE TOP, not an append, because that is what a commit
# does: d142466 changed lines in the middle of converge.sh and every byte after
# them moved. An append alone leaves earlier offsets valid and would under-report
# the defect.
edit_midrun() {
  python3 - "$1" <<'PY'
import sys
p = sys.argv[1]
d = open(p).read()
pad = "".join("# INSERTED PADDING LINE %d AAAAAAAAAAAAAAAAAAAAAAAAAAAA\n" % i for i in range(1, 9))
d = d.replace("set -uo pipefail\n", "set -uo pipefail\n" + pad, 1)
open(p, "w").write(d)
PY
}

# Runs one synthetic case and echoes "<rc>\n<combined output>".
run_case() {
  local f="$1" do_edit="$2" out rc
  if [ "$do_edit" = edit ]; then
    ( sleep 1; edit_midrun "$f" ) &
    local ed=$!
    out="$(bash "$f" 2>&1)"; rc=$?
    wait "$ed" 2>/dev/null || true
  else
    out="$(bash "$f" 2>&1)"; rc=$?
  fi
  printf '%s\n%s' "$rc" "$out"
}

echo "test-script-stable-under-self-edit"
echo

# --- case 0: negative self-test -----------------------------------------------
# The unwrapped script with NO edit. If this is not clean the harness is broken,
# not the scripts, and every red below would be meaningless.
echo "case 0: unwrapped, no mid-run edit (negative self-test -- must be GREEN)"
make_case "$WORK/c0.sh" plain
R="$(run_case "$WORK/c0.sh" noedit)"
RC="${R%%$'\n'*}"; OUT="${R#*$'\n'}"
if [ "$RC" = 0 ] && [ "$OUT" = "$EXPECTED" ]; then
  ok "unedited unwrapped run is rc=0 and clean -- the harness can produce a green"
else
  bad "unedited unwrapped run should be clean; rc=$RC output:"; printf '%s\n' "$OUT" | sed 's/^/         /'
fi

# --- case 1: the defect --------------------------------------------------------
echo "case 1: unwrapped + mid-run edit (the ASK-351 defect -- must reproduce)"
make_case "$WORK/c1.sh" plain
R="$(run_case "$WORK/c1.sh" edit)"
RC="${R%%$'\n'*}"; OUT="${R#*$'\n'}"
if [ "$RC" != 0 ] || [ "$OUT" != "$EXPECTED" ]; then
  ok "unwrapped run corrupts under a mid-run edit (rc=$RC, output not clean)"
  printf '%s\n' "$OUT" | sed 's/^/         | /'
else
  bad "unwrapped run survived the edit -- the reproducer no longer reproduces, so nothing below proves a fix"
fi

# --- case 2: the half fix ------------------------------------------------------
echo "case 2: braces WITHOUT a trailing exit + mid-run edit (half fix -- must still fail)"
make_case "$WORK/c2.sh" braces
R="$(run_case "$WORK/c2.sh" edit)"
RC="${R%%$'\n'*}"; OUT="${R#*$'\n'}"
if [ "$RC" != 0 ] || [ "$OUT" != "$EXPECTED" ]; then
  ok "braces alone still fail (rc=$RC) -- the trailing exit is load-bearing, not decoration"
  printf '%s\n' "$OUT" | sed 's/^/         | /'
else
  bad "braces alone survived; if that is real the trailing exit is unjustified and this fix is half noise"
fi

# --- case 3: the fix -----------------------------------------------------------
echo "case 3: braces PLUS a trailing exit + mid-run edit (the fix -- must be GREEN)"
make_case "$WORK/c3.sh" bracesexit
R="$(run_case "$WORK/c3.sh" edit)"
RC="${R%%$'\n'*}"; OUT="${R#*$'\n'}"
if [ "$RC" = 0 ] && [ "$OUT" = "$EXPECTED" ]; then
  ok "brace-wrapped body with a trailing exit is rc=0 and clean under the same edit"
else
  bad "the fix did not hold; rc=$RC output:"; printf '%s\n' "$OUT" | sed 's/^/         /'
fi

# --- the structural predicate --------------------------------------------------
# Reports the first violation on stdout and returns non-zero, so case 5 can assert
# it goes red rather than assuming it would.
assert_wrapped() {
  local f="$1"
  # First line that is neither the shebang, nor blank, nor a comment must be `{`.
  local first
  first="$(awk 'NR==1 && /^#!/ {next} /^[[:space:]]*$/ {next} /^[[:space:]]*#/ {next} {print; exit}' "$f")"
  [ "$first" = "{" ] || { echo "body does not open with a bare { (found: ${first:-<empty>})"; return 1; }
  # Last non-blank line must be the closing brace.
  local last
  last="$(awk 'NF {l=$0} END {print l}' "$f")"
  [ "$last" = "}" ] || { echo "file does not end with a bare } (found: ${last:-<empty>})"; return 1; }
  # The statement before it must be an unconditional top-level exit. Column 0
  # matters: an indented `exit` sits inside an if or a loop and may not be reached.
  local penult
  penult="$(awk 'NF {p=l; l=$0} END {print p}' "$f")"
  case "$penult" in
    exit|exit\ [0-9]*) ;;
    *) echo "last statement inside the brace is not an unconditional exit (found: ${penult:-<empty>})"; return 1 ;;
  esac
  bash -n "$f" 2>&1 || { echo "bash -n rejects $f"; return 1; }
  return 0
}

# --- case 4: the real drivers --------------------------------------------------
echo "case 4: the two real drivers carry the shape and still parse"
for f in "$CONVERGE" "$WORKER"; do
  if why="$(assert_wrapped "$f")"; then
    ok "$(basename "$f") is brace-wrapped, exits unconditionally inside the brace, and passes bash -n"
  else
    bad "$(basename "$f"): $why"
  fi
done

# --- case 5: mutate the structural check ---------------------------------------
# A check nobody has watched fail is decoration. Strip the wrapper off a COPY of
# the real converge.sh and the same predicate must reject it.
echo "case 5: the case-4 predicate goes red on an unwrapped copy (mutation)"
MUT="$WORK/converge-unwrapped.sh"
awk 'NF && $0=="{" && !seen {seen=1; next} {print}' "$CONVERGE" | awk 'NF && $0=="}" {last=NR} {a[NR]=$0} END {for(i=1;i<=NR;i++) if (i!=last) print a[i]}' > "$MUT"
if why="$(assert_wrapped "$MUT")"; then
  bad "the predicate accepted an unwrapped copy of converge.sh -- it cannot detect the defect it exists for"
else
  ok "predicate rejects the unwrapped copy ($why)"
fi

echo
echo "passed: $PASS  failed: $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
