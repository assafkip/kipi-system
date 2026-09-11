#!/usr/bin/env bash
# The reviewer floor posts RED on absence and NEVER touches a real verdict (ASK-361).
#
# WHY THIS EXISTS. `kipi/reviewer-approved` is a required context whose only
# producer runs off a launchd poll keyed on a Linear issue, not on the PR. So the
# context is routinely ABSENT, and an absent required context is what made
# `enforce_admins` unsafe to enable. reviewer-floor.sh converts absent into
# failing. This test holds the two properties that make that safe.
#
# THE FIXTURES ARE REAL API PAYLOADS, captured 2026-08-03 from the producer
# (GitHub's own combined-status endpoint), not hand-written imitations:
#
#   absent.json          <- PR #88 head 345f84df, total_count 0   -> floor must POST
#   verdict-success.json <- PR #91 head bb81abd3, a real APPROVE  -> floor must STAND DOWN
#   verdict-failure.json <- PR #89 head f78159ec, a real red      -> floor must STAND DOWN
#
# THE NO-CLOBBER HALF IS THE POINT. A floor that overwrote a genuine APPROVE
# would wedge PRs the reviewer had actually cleared -- strictly worse than having
# no floor. verdict-success.json is that case, and the mutation harness at the
# bottom proves the check can actually fail by removing the guard and requiring
# this test to go RED.
#
# Isolation: `gh` is replaced by a recording stub via REVIEWER_FLOOR_GH, so no
# network call and no commit status is ever posted. The stub records argv to a
# file; nothing here reaches a live data path.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FX="$HERE/fixtures/reviewer-floor"

# REF HATCH. Defaults to the real script; the mutation harness re-invokes this
# same file pointed at a mutated copy. A test that has never been watched fail is
# not a test.
SCRIPT="${REVIEWER_FLOOR_SCRIPT:-$HERE/../reviewer-floor.sh}"

PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }

check_eq() {
  local label="$1" want="$2" got="$3"
  if [ "$want" = "$got" ]; then
    pass "$label"
  else
    fail "$label (want '$want', got '$got')"
  fi
}

# ---------------------------------------------------------------- decision half
# shellcheck source=/dev/null
. "$SCRIPT"

echo "decision (pure, fixtures only) -- script under test: $SCRIPT"

check_eq "absence yields a post" \
  "post" "$(floor_decision < "$FX/absent.json")"

check_eq "a real APPROVE is never clobbered" \
  "noop success" "$(floor_decision < "$FX/verdict-success.json")"

check_eq "a real red verdict is never clobbered" \
  "noop failure" "$(floor_decision < "$FX/verdict-failure.json")"

# ---- the clobber check (Codex major on PR #95: read and post are not atomic)
# These drive the PLURAL statuses list, which is the only payload where a buried
# verdict is still visible after the floor has posted over it.
check_eq "floor alone on the list is clean" \
  "clean" "$(clobber_decision < "$FX/list-floor-only.json")"

check_eq "our floor on top of a real APPROVE is a clobber" \
  "clobbered success" "$(clobber_decision < "$FX/list-clobbered.json")"

# LOSING the race is not clobbering it. If the reviewer posted AFTER us their
# verdict is the live one and we harmed nothing -- reporting that as a clobber
# would make the floor cry wolf on its own correct behaviour.
check_eq "a verdict posted after ours is clean" \
  "clean" "$(clobber_decision < "$FX/list-race-lost.json")"

check_eq "an empty list is clean" "clean" "$(printf '[]' | clobber_decision)"

# ASSERT THE LITERAL, not a value read back from the same script. A
# baseline-relative assertion ("same as FLOOR_STATE") cannot see a mutant that
# moves both sides.
check_eq "the floor's state is literally failure" "failure" "$FLOOR_STATE"
check_eq "the floor's context is literally kipi/reviewer-approved" \
  "kipi/reviewer-approved" "$REVIEWER_CONTEXT"

# SOURCING MUST BE CLEAN WHERE BASH_SOURCE DOES NOT EXIST. zsh is the founder's
# login shell and has no BASH_SOURCE at all, so under this script's own `set -u`
# a bare ${BASH_SOURCE[0]} emits "BASH_SOURCE[0]: parameter not set". Found live
# 2026-08-03 while running the decision by hand across all 20 open PRs.
#
# ASSERT STDERR, NOT THE DECISION. The first version of this check compared
# stdout and PASSED against the unfixed script -- the warning is non-fatal, so
# `post` still came out and the check was a no-op. The stderr stream is the only
# recorder that sees this defect. `bash -c` does NOT reproduce it (bash
# populates BASH_SOURCE when sourcing a file), which is why the shell is zsh.
if command -v zsh >/dev/null 2>&1; then
  src_err="$(zsh -c ". '$SCRIPT'; floor_decision < '$FX/absent.json'" 2>&1 >/dev/null)"
  check_eq "sourcing from zsh emits nothing on stderr" "" "$src_err"
else
  # Visible, not silent: a skipped check must never read as a passed one.
  echo "  SKIP no zsh on this host -- BASH_SOURCE-unset check not exercised here"
fi

# ------------------------------------------------------------- integration half
# Drives main() end to end with a recording stub in place of `gh`.
STUB_DIR="$(mktemp -d)"
trap 'rm -rf "$STUB_DIR"' EXIT

# TWO ENDPOINTS, TWO FIXTURES. main() reads the COMBINED status to decide, then
# the PLURAL statuses list to check whether it buried a verdict. A stub serving
# one payload to both would feed an object where an array is expected and the
# clobber check would pass for the wrong reason.
make_stub() {
  local fixture="$1" read_rc="${2:-0}" list="${3:-$FX/list-floor-only.json}"
  cat > "$STUB_DIR/gh" <<STUB
#!/usr/bin/env bash
# Records argv, serves a fixture per endpoint, records the POST.
for a in "\$@"; do
  if [ "\$a" = "POST" ]; then
    printf '%s\n' "\$*" >> "$STUB_DIR/posted.txt"
    echo '{}'
    exit 0
  fi
done
printf '%s\n' "\$*" >> "$STUB_DIR/read.txt"
[ "$read_rc" -ne 0 ] && exit "$read_rc"
case "\$*" in
  */statuses) cat "$list" ;;
  *)          cat "$fixture" ;;
esac
STUB
  chmod +x "$STUB_DIR/gh"
  : > "$STUB_DIR/posted.txt"
  : > "$STUB_DIR/read.txt"
}

run_main() {
  REVIEWER_FLOOR_GH="$STUB_DIR/gh" bash "$SCRIPT" "$1" >/dev/null 2>&1
  echo "$?"
}

echo "integration (stubbed gh, no network)"

# absence -> exactly one POST carrying the literal failure state
make_stub "$FX/absent.json"
rc="$(run_main deadbeef)"
check_eq "absence: exit 0" "0" "$rc"
check_eq "absence: exactly one status posted" "1" "$(wc -l < "$STUB_DIR/posted.txt" | tr -d ' ')"
posted="$(cat "$STUB_DIR/posted.txt")"
case "$posted" in
  *"state=failure"*) pass "absence: posted state=failure" ;;
  *) fail "absence: posted state=failure (got: $posted)" ;;
esac
case "$posted" in
  *"context=kipi/reviewer-approved"*) pass "absence: posted the reviewer context" ;;
  *) fail "absence: posted the reviewer context (got: $posted)" ;;
esac
case "$posted" in
  *"state=success"*) fail "absence: the floor posted SUCCESS -- phantom approval" ;;
  *) pass "absence: never posts success" ;;
esac

# a real verdict present -> zero POSTs
make_stub "$FX/verdict-success.json"
rc="$(run_main deadbeef)"
check_eq "real APPROVE: exit 0" "0" "$rc"
check_eq "real APPROVE: nothing posted" "0" "$(wc -l < "$STUB_DIR/posted.txt" | tr -d ' ')"

make_stub "$FX/verdict-failure.json"
rc="$(run_main deadbeef)"
check_eq "real red: nothing posted" "0" "$(wc -l < "$STUB_DIR/posted.txt" | tr -d ' ')"

# THE RACE, END TO END. The floor posts, and the reviewer's real APPROVE landed
# in the window. It must exit nonzero and say so: a wrongly BLOCKED PR that is
# loudly reported, never a silently buried approval.
make_stub "$FX/absent.json" 0 "$FX/list-clobbered.json"
rc="$(run_main deadbeef)"
check_eq "buried verdict: exits 3" "3" "$rc"
check_eq "buried verdict: still posted exactly one status" \
  "1" "$(wc -l < "$STUB_DIR/posted.txt" | tr -d ' ')"
# The repair it must NOT attempt. Restoring the approval would make this script
# capable of posting success -- the ASK-312 phantom-approval hole.
case "$(cat "$STUB_DIR/posted.txt")" in
  *"state=success"*) fail "buried verdict: re-posted SUCCESS -- phantom approval" ;;
  *) pass "buried verdict: never re-posts the approval" ;;
esac

# Losing the race is a clean outcome, not an error.
make_stub "$FX/absent.json" 0 "$FX/list-race-lost.json"
rc="$(run_main deadbeef)"
check_eq "verdict posted after ours: exit 0" "0" "$rc"

# A FAILED READ MUST NOT LOOK LIKE ABSENCE. If the API read fails and the script
# fell through, it would post over a verdict it simply could not see.
make_stub "$FX/verdict-success.json" 1
rc="$(run_main deadbeef)"
check_eq "failed read: exits nonzero" "1" "$rc"
check_eq "failed read: posts nothing" "0" "$(wc -l < "$STUB_DIR/posted.txt" | tr -d ' ')"

echo
echo "pass=$PASS fail=$FAIL"

# ------------------------------------------------------------ mutation harness
# Skipped inside the child run, otherwise it would recurse.
if [ -n "${REVIEWER_FLOOR_MUTANT_RUN:-}" ]; then
  [ "$FAIL" -eq 0 ] || exit 1
  exit 0
fi

echo
echo "mutation harness (each mutant must make this test go RED)"
MUT_DIR="$(mktemp -d)"
trap 'rm -rf "$STUB_DIR" "$MUT_DIR"' EXIT

# name | sed expression | the property it removes
run_mutant() {
  local name="$1" expr="$2"
  local mut="$MUT_DIR/$name.sh"
  sed "$expr" "$SCRIPT" > "$mut"
  chmod +x "$mut"

  # VALIDATE THE MUTANT ACTUALLY APPLIED. A sed that matched nothing yields a
  # byte-identical copy, and the test below would report a false KILL.
  if cmp -s "$SCRIPT" "$mut"; then
    echo "  FAIL $name: mutant never applied (sed matched nothing) -- not a kill"
    return 1
  fi

  local out rc
  out="$(REVIEWER_FLOOR_MUTANT_RUN=1 REVIEWER_FLOOR_SCRIPT="$mut" bash "${BASH_SOURCE[0]}" 2>&1)"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "  ok   $name KILLED (test went red as required)"
    return 0
  fi
  echo "  FAIL $name SURVIVED -- the test cannot see this defect"
  printf '%s\n' "$out" | sed 's/^/      /'
  return 1
}

MUT_FAIL=0
# The clobber check: let a buried verdict report clean.
run_mutant "clobber-check-blinded" \
  's/^    echo "clobbered \$buried"$/    echo "clean"/' || MUT_FAIL=1
# The no-clobber guard: make every payload look absent.
run_mutant "no-clobber-removed" \
  's/if \[ "\$existing" = "none" \]; then/if true; then/' || MUT_FAIL=1
# The red-only guarantee: let the floor post success.
run_mutant "floor-posts-success" \
  's/^FLOOR_STATE="failure"$/FLOOR_STATE="success"/' || MUT_FAIL=1

echo
if [ "$FAIL" -eq 0 ] && [ "$MUT_FAIL" -eq 0 ]; then
  echo "PASS: $PASS checks green, all mutants killed"
  exit 0
fi
echo "FAILED: checks_failed=$FAIL mutants_survived_or_unapplied=$MUT_FAIL"
exit 1
