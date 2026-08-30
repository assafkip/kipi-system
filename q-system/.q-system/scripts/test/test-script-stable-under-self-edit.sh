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
# reports red would look like a passing reproducer. Case 4 then holds the real
# drivers to the shape, cases 5 and 6 mutate the two checks case 4 is built from so
# each is one that can actually go red, and case 7 pins the exception ledger.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SCRIPTS_DIR="$ROOT/q-system/.q-system/scripts"
CONVERGE="$SCRIPTS_DIR/converge.sh"
WORKER="$SCRIPTS_DIR/linear-worker.sh"
for f in "$CONVERGE" "$WORKER"; do
  [ -f "$f" ] || { echo "FATAL: missing $f" >&2; exit 1; }
done

# --- who is at risk, DISCOVERED rather than listed ------------------------------
# The first version of this file looped over exactly $CONVERGE and $WORKER. That
# list can only ever see the drivers somebody remembered, which is how
# pr-review-agent.sh sat unwrapped at a 2400s timeout -- launched by this very
# pipeline at linear-worker.sh:93 -- while a case named "the real drivers" reported
# green (PR #223 review, codex major). The issue calls this defect "a class across
# both drivers"; a hardcoded pair cannot hold a class.
#
# A driver is at risk when a commit can land inside its run. Two objective markers,
# unioned, so no judgement call sits between a new driver and this check:
#   1. it invokes `claude -p`  -- one model call is minutes, a loop of them is hours
#   2. it declares a *TIMEOUT*= of >= 600 seconds
# Running it found open-loops-heartbeat.sh too (headless `claude -p` per instance,
# open-loops-heartbeat.sh:92), which the review did not name. That is the argument
# for discovery in one line.
DISCOVERY_MIN_SECONDS=600
discover_drivers() {
  local dir="$1" f secs
  for f in "$dir"/*.sh; do
    [ -f "$f" ] || continue
    secs="$(sed -n 's/^[A-Z_]*TIMEOUT[A-Z_]*=\([0-9][0-9]*\).*/\1/p' "$f" | sort -rn | head -1)"
    if grep -q 'claude -p' "$f" || { [ -n "$secs" ] && [ "$secs" -ge "$DISCOVERY_MIN_SECONDS" ]; }; then
      echo "$f"
    fi
  done
}

# converge.sh matches NEITHER marker and is the original scar: it spends its hours
# inside linear-worker.sh, which it launches at converge.sh:94, so the model call is
# never in its own text. Seeded explicitly rather than by loosening the predicate,
# because a marker broad enough to catch it catches every wrapper script here.
DRIVER_SEED="$CONVERGE"

# --- the exception ledger -------------------------------------------------------
# `basename|spillover-id|why`. An entry here is a gap that is TRACKED, not one that
# is forgiven: case 4 still reports it, case 7 refuses to let it rot, and each id is
# an open item in .prd-os/spillover.jsonl that holds `prd_runner.py gates run` red
# until a real issue closes it (no-orphan-findings.md).
#
# Both are unwrapped for the same reason and it is not that they are safe: ASK-351's
# DoR ends "not auditing or wrapping the other long-running bash drivers", and
# neither file is in its allowed_files. Wrapping them here would be the scope
# expansion the DoR forbids; leaving them undeclared would be the silent drop the
# review correctly caught. Declaring them is the third option.
KNOWN_UNWRAPPED='pr-review-agent.sh|sp-3bcc9e16|2400s reviewer, launched by linear-worker.sh:93
open-loops-heartbeat.sh|sp-c2dcebad|headless claude -p per instance, open-loops-heartbeat.sh:92'

declared_gap() { printf '%s\n' "$KNOWN_UNWRAPPED" | grep "^$1|" || true; }

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

# --- case 4: every discovered driver is wrapped, or is a DECLARED gap -----------
# The pass condition is "wrapped OR declared", never "wrapped OR unlisted". A
# long-running driver that nobody wrapped and nobody captured is the failure this
# case exists for, so it is the one combination that goes red.
echo "case 4: every long-running driver is brace-wrapped, or is a declared+captured gap"
DRIVERS="$(printf '%s\n%s\n' "$DRIVER_SEED" "$(discover_drivers "$SCRIPTS_DIR")" | awk 'NF && !seen[$0]++')"
echo "       population (discovered + seed): $(printf '%s\n' "$DRIVERS" | xargs -n1 basename | tr '\n' ' ')"
while IFS= read -r f; do
  [ -n "$f" ] || continue
  base="$(basename "$f")"
  gap="$(declared_gap "$base")"
  if why="$(assert_wrapped "$f")"; then
    if [ -n "$gap" ]; then
      bad "$base IS wrapped but is still listed KNOWN_UNWRAPPED -- delete its line and resolve ${gap%|*} so the ledger stops describing a gap that closed"
    else
      ok "$base is brace-wrapped, exits unconditionally inside the brace, and passes bash -n"
    fi
  elif [ -n "$gap" ]; then
    ok "$base is unwrapped and DECLARED (${gap#*|}) -- a tracked gap, not a silent one"
  else
    bad "$base: $why -- an undeclared long-running driver. Wrap it, or capture it (prd_runner.py spillover add) and add its line to KNOWN_UNWRAPPED"
  fi
done <<EOF
$DRIVERS
EOF

# --- case 5: mutate the structural check ---------------------------------------
# A check nobody has watched fail is decoration. Strip the wrapper off a COPY of
# the real converge.sh and the same predicate must reject it.
echo "case 5: the shape predicate goes red on an unwrapped copy (mutation)"
MUT="$WORK/converge-unwrapped.sh"
awk 'NF && $0=="{" && !seen {seen=1; next} {print}' "$CONVERGE" | awk 'NF && $0=="}" {last=NR} {a[NR]=$0} END {for(i=1;i<=NR;i++) if (i!=last) print a[i]}' > "$MUT"
if why="$(assert_wrapped "$MUT")"; then
  bad "the predicate accepted an unwrapped copy of converge.sh -- it cannot detect the defect it exists for"
else
  ok "predicate rejects the unwrapped copy ($why)"
fi

# --- case 6: mutate the DISCOVERY ----------------------------------------------
# Case 5 proves the shape check can go red. It says nothing about whether the
# population reaches the file at all -- and an empty population passes case 4
# vacuously, which is exactly the hole the hardcoded pair had. So: plant a driver
# in a synthetic scripts dir and require discovery to reach it by each marker on
# its own, and require an ordinary short script NOT to be swept in.
echo "case 6: discovery finds a planted driver by each marker, and skips a non-driver (mutation)"
SYN="$WORK/syn-scripts"; mkdir -p "$SYN"
printf '#!/usr/bin/env bash\nset -uo pipefail\nclaude -p "review this" </dev/null\n' > "$SYN/planted-model-caller.sh"
printf '#!/usr/bin/env bash\nset -uo pipefail\nTIMEOUT_SECONDS=%s\nsleep 1\n' "$DISCOVERY_MIN_SECONDS" > "$SYN/planted-long-timeout.sh"
printf '#!/usr/bin/env bash\nset -uo pipefail\nTIMEOUT_SECONDS=5\necho hi\n' > "$SYN/planted-quick-helper.sh"
FOUND="$(discover_drivers "$SYN" | xargs -n1 basename | sort | tr '\n' ' ')"
if [ "$FOUND" = "planted-long-timeout.sh planted-model-caller.sh " ]; then
  ok "discovery caught both planted drivers and left the quick helper alone (found: $FOUND)"
else
  bad "discovery is wrong; expected the two planted drivers only, got: ${FOUND:-<nothing>}"
fi
# ...and the planted driver, being undeclared and unwrapped, must be the red case.
if why="$(assert_wrapped "$SYN/planted-model-caller.sh")" || [ -n "$(declared_gap planted-model-caller.sh)" ]; then
  bad "a freshly planted unwrapped driver would pass case 4 -- the population reaches it but the verdict does not"
else
  ok "a discovered, unwrapped, undeclared driver lands on case 4's red branch ($why)"
fi

# --- case 7: the exception ledger cannot rot ------------------------------------
# A ledger naming a file that no longer exists is worse than no ledger: it reads as
# coverage. Every KNOWN_UNWRAPPED line must point at a real file that discovery
# actually reaches, or the entry is stale and case 4's green for it is a lie.
echo "case 7: every KNOWN_UNWRAPPED entry names a real, still-discovered driver"
while IFS='|' read -r base sp _why; do
  [ -n "$base" ] || continue
  if [ ! -f "$SCRIPTS_DIR/$base" ]; then
    bad "KNOWN_UNWRAPPED names $base ($sp) but that file does not exist -- stale entry granting silent coverage"
  elif ! printf '%s\n' "$DRIVERS" | grep -q "/$base\$"; then
    bad "KNOWN_UNWRAPPED names $base ($sp) but discovery no longer reaches it -- either it stopped being long-running (drop the line) or the predicate regressed"
  else
    ok "$base ($sp) is a real file discovery still reaches"
  fi
done <<EOF
$KNOWN_UNWRAPPED
EOF

echo
echo "passed: $PASS  failed: $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
