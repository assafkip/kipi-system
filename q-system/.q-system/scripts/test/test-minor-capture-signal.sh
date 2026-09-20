#!/usr/bin/env bash
# Pairs with the capture half of pr-review-agent.sh (ASK-1921, claude review of
# PR #377, item 4).
#
# THE DEFECT. `minors captured as spillover: 0 of 2` was printed on PR #377 and
# nothing else happened. Downstream, a run that extracted 2 minors and captured
# none is indistinguishable from a run that found none: same terminal verdict,
# same status, same silence. APPROVE WITH NITS stops the rework loop, so those
# two findings existed only in a PR comment -- the silent drop
# `no-orphan-findings.md` exists to prevent.
#
# IT DRIVES THE SHIPPED BLOCK, NOT A COPY. The capture half is inline in
# pr-review-agent.sh, so this extracts it by awk range (anchored on the `if` line
# and the first `^fi$` after it) and executes it in a bare subshell with stubs for
# its three outside edges: the minor extractor, prd_runner.py and the notifier. A
# rewritten copy here would test this file's idea of the block.
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
awk '/^if \[ "\$VERDICT" = "APPROVE WITH NITS" \] && \[ -n "\$ISSUE" \]; then$/,/^fi$/' \
  "$REVIEWER" > "$WORK/block.sh"
[ -s "$WORK/block.sh" ] || fail "could not extract the capture block -- its anchors moved"
grep -q 'spillover add' "$WORK/block.sh" \
  || fail "the extracted range is not the capture block (no 'spillover add' in it)"

# --- the harness the block runs inside ---------------------------------------
# $1 = the exit code the stub prd_runner.py returns (0 captures, 2 refuses).
run_block() {
  local runner_rc="$1" minors="$2"
  local sandbox="$WORK/run"
  rm -rf "$sandbox"; mkdir -p "$sandbox/plugins/prd-os/scripts"
  printf '#!/usr/bin/env bash\nexit %s\n' "$runner_rc" > "$sandbox/plugins/prd-os/scripts/prd_runner.py"
  chmod +x "$sandbox/plugins/prd-os/scripts/prd_runner.py"
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$1" >> "%s/notified.txt"\n' "$sandbox" > "$sandbox/notify.sh"
  chmod +x "$sandbox/notify.sh"
  : > "$sandbox/notified.txt"

  {
    echo 'python3() { "$1"; }'                      # the stub runner IS the exit code
    echo "extract_minor_findings() { printf '%s' \"\$MINORS_FIXTURE\"; }"
    cat "$WORK/block.sh"
  } > "$sandbox/harness.sh"

  # The output and the page both land in FILES, never in shell variables: every
  # caller below reads run_block through a command substitution, which is a
  # subshell, so an assignment made in here would be discarded and every "paged
  # nobody" assertion would pass without measuring anything.
  VERDICT="APPROVE WITH NITS" ISSUE="ASK-9999" PR="377" REVIEW="$WORK/review.md" \
  MINOR_TAG="" SKEL="$sandbox" NOTIFY="$sandbox/notify.sh" MINORS_FIXTURE="$minors" \
    bash "$sandbox/harness.sh" 2>&1
}

notified() { cat "$WORK/run/notified.txt" 2>/dev/null; }

TWO_MINORS='minor|the help text omits --repo-root|a.py:10
minor|the comment misstates the code|b.yml:72'

# --- the case this issue is about --------------------------------------------
OUT="$(run_block 2 "$TWO_MINORS")"
case "$OUT" in
  *"0 of 2"*) ok "the count itself is still printed (0 of 2)" ;;
  *) fail "expected the '0 of 2' count in the output, got: $OUT" ;;
esac
case "$OUT" in
  *LOST*|*"captured NONE"*|*"went nowhere"*)
     ok "2 found + 0 captured says so loudly, not only as a count" ;;
  *) fail "2 minors found and 0 captured produced no loud signal. Output was: $OUT" ;;
esac
[ -n "$(notified)" ] \
  && ok "2 found + 0 captured reaches the alert path (Sana's queue)" \
  || fail "2 minors found and 0 captured paged nobody: the notifier was never called"

# --- the negative: a healthy capture stays quiet ------------------------------
OUT="$(run_block 0 "$TWO_MINORS")"
case "$OUT" in
  *"2 of 2"*) ok "a healthy run still reports its count (2 of 2)" ;;
  *) fail "expected '2 of 2' on the healthy path, got: $OUT" ;;
esac
case "$OUT" in
  *LOST*|*"captured NONE"*|*"went nowhere"*)
     fail "a run that captured everything raised the loss signal anyway: $OUT" ;;
  *) ok "a run that captured everything raises nothing" ;;
esac
[ -z "$(notified)" ] \
  && ok "a healthy capture pages nobody" \
  || fail "a healthy capture paged the alert path: $(notified)"

# --- the other negative: zero found is not a loss -----------------------------
# An LLM that drifts from the FINDINGS format yields zero lines, and zero of zero
# is a review with no minors. The signal is about findings that were EXTRACTED and
# then lost, never about a reviewer that reported none.
OUT="$(run_block 2 "")"
case "$OUT" in
  *LOST*|*"captured NONE"*|*"went nowhere"*)
     fail "zero minors extracted was reported as a loss: $OUT" ;;
  *) ok "zero found is zero lost (0 of 0 raises nothing)" ;;
esac
[ -z "$(notified)" ] || fail "0 of 0 paged the alert path: $(notified)"

[ "$FAILED" = "0" ] && echo "ALL PASS" || echo "SOME FAILED"
exit "$FAILED"
