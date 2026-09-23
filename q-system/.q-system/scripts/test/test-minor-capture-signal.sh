#!/usr/bin/env bash
# Pairs with the minors half of pr-review-agent.sh (ASK-1921).
#
# THE DEFECT THIS NOW PINS. The block used to call `prd_runner.py spillover add`
# with no --severity. That defaults to `minor`, which sits in
# SPILLOVER_REFUSED_SEVERITIES ("a minor is fixed in this change or rejected with
# a reason; it is never queued", founder 2026-09-12), so the call returned 2 on
# EVERY run. The captured count was 0 by construction, and the alarm built on that
# zero paged Sana on every approved PR carrying a nit -- an alert with nothing down
# and nothing to act on (claude review of PR #392, finding 1).
#
# An earlier version of this file drove that call through a stub returning 0, an
# exit code the real producer cannot return for those arguments, so its two
# negative cases asserted over a state production never reaches (same review,
# finding 2). The exit-code axis is gone with the call: the cases below assert the
# door is not knocked on at all, and that assertion is DERIVED from the shipped
# source rather than restated here.
#
# IT DRIVES THE SHIPPED BLOCK, NOT A COPY. The minors half is inline in
# pr-review-agent.sh, so this extracts it by awk range (anchored on the `if` line
# and the first `^fi$` after it) and executes it in a bare subshell with stubs for
# its two outside edges: the minor extractor and the notifier. A rewritten copy
# here would test this file's idea of the block.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$(cd "$HERE/.." && pwd)"
REVIEWER="$SCRIPTS/pr-review-agent.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
FAILED=0

fail() { echo "FAIL: $*" >&2; FAILED=1; }
ok()   { echo "PASS: $*"; }

[ -f "$REVIEWER" ] || { echo "FAIL: $REVIEWER is missing"; exit 1; }

# --- extract the shipped block ----------------------------------------------
extract_block() {
  awk '/^if \[ "\$VERDICT" = "APPROVE WITH NITS" \] && \[ -n "\$ISSUE" \]; then$/,/^fi$/' \
    "$1"
}
extract_block "$REVIEWER" > "$WORK/block.sh"
[ -s "$WORK/block.sh" ] || fail "could not extract the minors block -- its anchors moved"
grep -q 'extract_minor_findings' "$WORK/block.sh" \
  || fail "the extracted range is not the minors block (no 'extract_minor_findings' in it)"

# --- the harness the block runs inside ---------------------------------------
# $1 = the minor findings the extractor yields. There is deliberately no exit-code
# argument: the block calls no external producer any more, and a knob for one would
# reintroduce the unreachable fixture this file was rewritten to remove.
run_block() {
  local minors="$1" block="${2:-$WORK/block.sh}"
  local sandbox="$WORK/run"
  rm -rf "$sandbox"; mkdir -p "$sandbox/plugins/prd-os/scripts"
  # A prd_runner that ABORTS if anything calls it. The behavioural half of "the
  # refusing door is not knocked on": a reintroduced capture call fails loudly
  # here rather than passing through a friendly stub.
  printf '#!/usr/bin/env bash\nprintf "prd_runner was called: %%s\\n" "$*" >> "%s/runner-calls.txt"\nexit 2\n' \
    "$sandbox" > "$sandbox/plugins/prd-os/scripts/prd_runner.py"
  chmod +x "$sandbox/plugins/prd-os/scripts/prd_runner.py"
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$1" >> "%s/notified.txt"\n' "$sandbox" > "$sandbox/notify.sh"
  chmod +x "$sandbox/notify.sh"
  : > "$sandbox/notified.txt"
  : > "$sandbox/runner-calls.txt"

  {
    echo 'python3() { "$1" "${@:2}"; }'   # route the block's python3 at the stub runner
    echo "extract_minor_findings() { printf '%s' \"\$MINORS_FIXTURE\"; }"
    cat "$block"
  } > "$sandbox/harness.sh"

  # The page and the runner calls both land in FILES, never in shell variables:
  # every caller below reads run_block through a command substitution, which is a
  # subshell, so an assignment made in here would be discarded and every "paged
  # nobody" assertion would pass without measuring anything.
  VERDICT="APPROVE WITH NITS" ISSUE="ASK-9999" PR="392" REVIEW="$WORK/review.md" \
  MINOR_TAG="" SKEL="$sandbox" NOTIFY="$sandbox/notify.sh" MINORS_FIXTURE="$minors" \
    bash "$sandbox/harness.sh" 2>&1
}

notified()     { cat "$WORK/run/notified.txt" 2>/dev/null; }
runner_calls() { cat "$WORK/run/runner-calls.txt" 2>/dev/null; }

TWO_MINORS='minor|the help text omits --repo-root|a.py:10
minor|the comment misstates the code|b.yml:72'

# --- the refusing door is not knocked on --------------------------------------
# Structural: read off the SHIPPED source, so re-adding the call anywhere in the
# block fails this whether or not the harness happens to execute that branch.
if grep -q 'spillover add' "$WORK/block.sh"; then
  fail "the block calls 'spillover add' again. prd_runner refuses a minor by policy (rc=2), so the capture cannot succeed and any count built on it reads as an outage."
else
  ok "the shipped block does not call 'spillover add' (the door that refuses a minor by policy)"
fi

# --- two minors: named, counted, and nobody paged ------------------------------
OUT="$(run_block "$TWO_MINORS")"
case "$OUT" in
  *": 2"*) ok "the count is printed (2 minors)" ;;
  *) fail "expected a count of 2 in the output, got: $OUT" ;;
esac
MISSING=""
for claim in "the help text omits --repo-root" "a.py:10" "the comment misstates the code" "b.yml:72"; do
  case "$OUT" in *"$claim"*) : ;; *) MISSING="$MISSING [$claim]" ;; esac
done
[ -z "$MISSING" ] \
  && ok "each minor is NAMED with its location, not only tallied" \
  || fail "the output tallies the minors without naming them; absent:$MISSING"
case "$OUT" in
  *UNROUTED*) ok "a terminal verdict with minors says so out loud (UNROUTED)" ;;
  *) fail "2 minors on a terminal APPROVE WITH NITS produced no loud signal. Output was: $OUT" ;;
esac
[ -z "$(runner_calls)" ] \
  && ok "no external producer was invoked at all" \
  || fail "the block called prd_runner: $(runner_calls)"
[ -z "$(notified)" ] \
  && ok "a policy refusal pages nobody (no 100%-rate alert)" \
  || fail "an ordinary APPROVE WITH NITS with minors paged the alert path: $(notified)"

# --- the negative: zero minors is quiet ----------------------------------------
# An LLM that drifts from the FINDINGS format yields zero lines, and zero minors is
# a review with no nits -- the ordinary healthy case.
OUT="$(run_block "")"
case "$OUT" in
  *UNROUTED*) fail "zero minors extracted was reported as unrouted: $OUT" ;;
  *) ok "zero minors raises nothing" ;;
esac
[ -z "$(notified)" ] || fail "zero minors paged the alert path: $(notified)"

# --- mutant: the assertion above can actually go red ---------------------------
# Put the capture call back into a COPY of the block and confirm both halves fail.
# A check that cannot be made to fail is decoration.
sed 's#^  done <<EOF#    python3 "$SKEL/plugins/prd-os/scripts/prd_runner.py" spillover add --source "$ISSUE" --desc "x"\n  done <<EOF#' \
  "$WORK/block.sh" > "$WORK/mutant.sh"
if grep -q 'spillover add' "$WORK/mutant.sh"; then
  ok "mutant built (capture call re-added to a copy)"
  run_block "$TWO_MINORS" "$WORK/mutant.sh" >/dev/null
  [ -n "$(runner_calls)" ] \
    && ok "mutant killed: the runner-call check sees the re-added capture" \
    || fail "mutant SURVIVED: the capture call was re-added and nothing noticed"
else
  fail "could not build the mutant -- the block's shape moved, so the check above is unproven"
fi

[ "$FAILED" = "0" ] && echo "ALL PASS" || echo "SOME FAILED"
exit "$FAILED"
