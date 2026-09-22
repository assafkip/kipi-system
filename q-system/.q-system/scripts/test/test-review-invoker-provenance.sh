#!/usr/bin/env bash
# Reproducer for sp-53aad86f: the verdict record could not distinguish a
# DISPATCHER-driven review from a hand-run one.
#
# Pairs with: the invoker field written by pr-review-agent.sh, set by
# linear-worker.sh, and reported by verify-codex-review-live.sh check 8.
#
# WHY THIS IS THE PROOF THAT MATTERS. Every green check so far proves "a codex
# review ran". The founder asked for something stricter: that the DISPATCHER ran
# one, unattended, on a PR nobody reviewed by hand. Without provenance in the
# record, a hand-run review and an unattended one are byte-identical evidence, so
# no amount of green proves the thing he asked about.
#
# THE FAIL-SAFE DIRECTION IS THE WHOLE DESIGN. An unlabelled review must read as
# hand-run, never as dispatcher-driven. Absent is not approved -- the same posture
# the reviewer's commit status takes. Case 3 is that assertion, and it is the one
# a careless default would break.
# COST, AND WHY THIS ENTRY CARRIES timeout_s=240 IN THE CAPABILITY MANIFEST
# (ASK-505). Cases 4, 5 and 6 each drive verify-codex-review-live.sh, and that
# script shells `launchctl list` -- measured on the founder's box 2026-08-08 at
# 21.56s / 29.45s / 23.92s per invocation, so this suite costs ~65-90s wall
# against roughly 3s of CPU. It is waiting on launchd, not computing.
#
# The manifest gave this entry NO timeout_s, so it inherited the gate's
# DEFAULT_TIMEOUT_S of 60. Three ~25s calls cannot fit in 60s, so the test was
# killed mid-case-6 on every run: the capability gate reported a `test-timeout`
# that read like a broken test, while the test itself passes in 65s standalone.
# It had never passed under the gate. Do not "fix" a recurrence by shrinking the
# assertions -- measure launchctl first, because the cost scales with how many
# jobs are loaded on the machine and this box carries a lot of them.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$(cd "$HERE/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

AGENT="$SCRIPTS/pr-review-agent.sh"
WORKER="$SCRIPTS/linear-worker.sh"
VERIFIER="$SCRIPTS/verify-codex-review-live.sh"

echo "== 1. the reviewer records an invoker at all =="
if grep -q 'KIPI_REVIEW_INVOKER' "$AGENT"; then
  ok "pr-review-agent.sh reads KIPI_REVIEW_INVOKER"
else
  bad "THE DEFECT: pr-review-agent.sh has no invoker concept, so no record can name its caller"
fi
if grep -qE '"invoker"' "$AGENT"; then
  ok "the verdict record carries an invoker field"
else
  bad "THE DEFECT: the verdict record has no invoker field"
fi

echo
echo "== 2. the WORKER labels itself, so a dispatcher run is identifiable =="
# The label has to be on the worker's call, not merely available as an env var
# nobody sets -- an unset knob is the same as no feature.
if grep -nE 'KIPI_REVIEW_INVOKER=(worker|dispatcher)' "$WORKER" >/dev/null 2>&1; then
  ok "linear-worker.sh labels its reviewer invocation"
else
  bad "THE DEFECT: linear-worker.sh does not set KIPI_REVIEW_INVOKER, so its runs are indistinguishable from hand runs"
fi

echo
echo "== 3. THE FAIL-SAFE: an unlabelled run must NOT read as dispatcher-driven =="
# Drive the default straight out of the script rather than trusting a comment.
DEFAULT="$(bash -c 'unset KIPI_REVIEW_INVOKER; grep -oE "KIPI_REVIEW_INVOKER:-[a-z]+" '"'$AGENT'"' | head -1 | cut -d- -f2')"
case "$DEFAULT" in
  worker|dispatcher)
    bad "THE DEFECT: the default invoker is '$DEFAULT', so every hand-run review would count as dispatcher proof" ;;
  "")
    bad "could not read the default invoker out of $AGENT" ;;
  *)
    ok "the default invoker is '$DEFAULT', so an unlabelled run cannot pass as dispatcher-driven" ;;
esac


# --- cases 1-3 are static and run anywhere. 4-6 drive the VERIFIER, which reads a
# launchd plist with `plutil` and `launchctl` -- both macOS-only. On the Linux CI
# runner those do not exist, so the verifier cannot answer and the assertions below
# would fail for a reason that has nothing to do with the invoker field. That is the
# same caller's-environment class as the mktemp defect, one level up: the test itself
# was only ever runnable on the machine it was written on.
#
# SKIPPED LOUDLY, never silently. A quiet skip is how a suite reports green about
# checks it did not run, which is the defect this repo keeps finding. The skip prints,
# and it does NOT count as a pass.
# GUARD ON THE REAL PRECONDITION, not on the binaries. My first guard checked
# `command -v plutil/launchctl`, which is true on any Mac -- including a CI-shaped
# run with a sandbox $HOME. But the verifier reads
# $HOME/Library/LaunchAgents/com.kipi.dispatch.plist, so what it actually needs is
# THAT FILE, and a clean $HOME does not have it. The binary check passed and the
# cases still failed. Found by ci-shaped-run.sh in seconds, having survived a full
# CI round that only reported rc=1.
if ! command -v plutil >/dev/null 2>&1 || ! command -v launchctl >/dev/null 2>&1 \
   || [ ! -f "$HOME/Library/LaunchAgents/com.kipi.dispatch.plist" ]; then
  echo
  echo "== 4-6 SKIPPED: no launchd plist at \$HOME/Library/LaunchAgents/com.kipi.dispatch.plist, so the verifier cannot run =="
  echo "   (cases 1-3 above are static and DID run; the invoker wiring is still asserted)"
  echo
  echo "-------- $PASS passed, $FAIL failed, 3 case(s) skipped --------"
  [ "$FAIL" -eq 0 ] || exit 1
  echo "PASS (partial): invoker wiring asserted; verifier-dependent cases need macOS"
  exit 0
fi
echo
# THE `engine` VALUE IN EVERY FIXTURE BELOW IS THE PRIMARY ENGINE, and it must
# move with the two defaults in pr-review-agent.sh. The verifier's receipt scan
# filters on it (verify-codex-review-live.sh, the RECEIPT block) so an ADVISORY
# engine's record cannot pass as proof the gating loop ran unattended -- which is
# the whole question this file asks. These said "codex" until 2026-09-06 and the
# flip to claude turned cases 5 and 6 RED while the nine suites the change ran
# stayed green: this suite drives the verifier and was not among them.
echo "== 4. a record with NO invoker key reads as not-dispatcher =="
# Every record written before this change lacks the key entirely. Those must not
# be counted either -- a missing field is the same unknown as a manual label.
STATE="$WORK/state"; mkdir -p "$STATE/pr-reviews"
cat > "$STATE/pr-reviews/pr-900.verdict.json" <<'JSON'
{"pr":900,"issue":"ASK-900","verdict":"APPROVE","engine":"claude",
 "round":1,"head_sha":"deadbeefdeadbeef","ts":"2026-07-30T00:00:00Z"}
JSON
OUT="$(KIPI_STATE_DIR="$STATE" bash "$VERIFIER" 2>&1 | grep -E 'RECEIPT|dispatcher' || true)"
if echo "$OUT" | grep -qi 'dispatcher-driven'; then
  # It may legitimately report "no dispatcher-driven receipt"; only a positive claim is wrong.
  if echo "$OUT" | grep -qiE 'no dispatcher-driven|not dispatcher-driven|hand-run'; then
    ok "a legacy record without an invoker is not claimed as dispatcher-driven"
  else
    bad "THE DEFECT: a legacy record with no invoker was reported as dispatcher-driven proof"
  fi
else
  ok "the verifier makes no dispatcher claim for a record without an invoker"
fi

echo
echo "== 5. a worker-labelled record IS reported as dispatcher-driven =="
cat > "$STATE/pr-reviews/pr-901.verdict.json" <<'JSON'
{"pr":901,"issue":"ASK-901","verdict":"APPROVE","engine":"claude","invoker":"worker",
 "round":1,"head_sha":"cafebabecafebabe","ts":"2026-07-30T01:00:00Z"}
JSON
OUT="$(KIPI_STATE_DIR="$STATE" bash "$VERIFIER" 2>&1 | grep -E 'RECEIPT|dispatcher' || true)"
# Require the PR NUMBER, not just the phrase. The phrase also appears in the
# NO-receipt message, so the loose form passed against a crashed verifier.
if echo "$OUT" | grep -qi 'DISPATCHER-DRIVEN RECEIPT FOUND' && echo "$OUT" | grep -q '901'; then
  ok "a worker-labelled record is reported as the dispatcher-driven receipt"
else
  bad "a worker-labelled record was NOT reported as dispatcher-driven, so the proof stays invisible"
fi

echo
echo "== 6. the newest worker record wins, not the newest record overall =="
# A later HAND run must not displace the dispatcher receipt in the report: the
# question "has the dispatcher ever done this" is not answered by recency.
cat > "$STATE/pr-reviews/pr-902.verdict.json" <<'JSON'
{"pr":902,"issue":"ASK-902","verdict":"APPROVE","engine":"claude","invoker":"manual",
 "round":1,"head_sha":"0123456789abcdef","ts":"2026-07-30T02:00:00Z"}
JSON
OUT="$(KIPI_STATE_DIR="$STATE" bash "$VERIFIER" 2>&1 | grep -iE 'dispatcher-driven' || true)"
if echo "$OUT" | grep -q '901'; then
  ok "a newer hand run does not hide the dispatcher receipt (PR #901 still named)"
else
  bad "a newer manual review displaced the dispatcher receipt in the report"
fi

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: the record distinguishes a dispatcher-driven review from a hand run"
