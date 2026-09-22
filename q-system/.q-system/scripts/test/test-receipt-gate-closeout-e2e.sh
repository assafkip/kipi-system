#!/usr/bin/env bash
# End-to-end: does a REAL kipi-dsse closeout produce a receipt the PR receipt
# gate accepts? Pairs with q-system/.q-system/scripts/pr-receipt-gate.py.
#
# Why this file exists (ASK-210 review round 3). The gate shipped with a
# fixture-only suite. Every fixture was hand-written, so nothing checked the one
# thing that decides whether the gate is usable: that the ONLY receipt producer
# in the repo emits something the gate can match. It did not. The gate blocked
# 100% of the branches it targeted and the remediation it printed -- run the
# closeout -- could not clear it. Fixtures cannot catch that class; only running
# the real producer can. So this suite runs `issue_runner.py` for real, against
# a throwaway git repo, and asserts on what it actually wrote.
#
# It also pins the coverage rule: a receipt proves the commit it pinned, not
# every commit later pushed to the same branch (linear-worker.sh reuses the
# branch and the PR across REWORK rounds).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
GATE="$SCRIPT_DIR/../pr-receipt-gate.py"
RUNNER="$REPO_ROOT/plugins/kipi-dsse/scripts/issue_runner.py"
LEDGER_CHECK="$SCRIPT_DIR/../receipts-ledger-check.py"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0

ok() { echo "  PASS: $1"; pass=$((pass + 1)); }
no() { echo "  FAIL: $1"; [ $# -gt 1 ] && echo "        $2"; fail=$((fail + 1)); }

# --- a throwaway repo on the branch linear-worker.sh would have created ------
REPO="$TMP/repo"
mkdir -p "$REPO/.prd-os/issues"
git -C "$REPO" init -q -b sana/ask-999
git -C "$REPO" config user.email "test@kipi.invalid"
git -C "$REPO" config user.name "kipi-test"

# Mirror the real repo: .gitignore:98 keeps the runner's active-issue state out
# of every commit. Without this the tmp repo commits .claude/state/ and the
# coverage check reads it as post-receipt work, which the real repo never sees.
printf '.claude/state/\n' > "$REPO/.gitignore"
echo "the shipped work" > "$REPO/work.txt"
cat > "$REPO/.prd-os/issues/receipt-gate-e2e.md" <<'SPEC'
---
id: receipt-gate-e2e
title: end-to-end closeout for the receipt gate
status: in-progress
priority: p1
parent_prd: prd-e2e
allowed_files:
  - work.txt
required_checks:
  - "true"
---

<!-- generated-by: prd_split.py prd=prd-e2e finding=finding-1 at=2026-07-27T00:00:00Z -->

# end-to-end closeout for the receipt gate
SPEC
git -C "$REPO" add -A
git -C "$REPO" commit -qm "work + spec (ASK-999)"
WORK_SHA="$(git -C "$REPO" rev-parse HEAD)"

# --- the real closeout, run to completion -----------------------------------
run() { python3 "$RUNNER" --repo-root "$REPO" "$@"; }

CLOSE_LOG="$TMP/close.log"
{
  run load receipt-gate-e2e
  run mark verified
  run mark reviewed
  run mark findings_triaged
  run close
} > "$CLOSE_LOG" 2>&1
CLOSE_RC=$?

LEDGER="$REPO/.prd-os/receipts.jsonl"
if [ "$CLOSE_RC" -eq 0 ] && [ -s "$LEDGER" ]; then
  ok "the real producer ran a full closeout and wrote a receipt"
else
  no "the real producer ran a full closeout and wrote a receipt" \
     "close rc=$CLOSE_RC; log: $(tail -5 "$CLOSE_LOG" | tr '\n' ' ')"
fi

echo "=== the receipt the REAL producer wrote ==="
cat "$LEDGER" 2>/dev/null || echo "(no ledger)"

# --- 1. the id the gate looks for must be reachable in that receipt ----------
if grep -qiE '\bASK-999\b' "$LEDGER" 2>/dev/null; then
  ok "the receipt carries the Linear issue id the gate resolves from the branch"
else
  no "the receipt carries the Linear issue id the gate resolves from the branch" \
     "no ASK-999 token in $(cat "$LEDGER" 2>/dev/null)"
fi

# --- 2. and the gate must actually accept it --------------------------------
if python3 "$GATE" --branch sana/ask-999 --receipts "$LEDGER" >/dev/null 2>&1; then
  ok "the gate accepts a receipt written by a complete real closeout"
else
  no "the gate accepts a receipt written by a complete real closeout" \
     "$(python3 "$GATE" --branch sana/ask-999 --receipts "$LEDGER" 2>&1 | head -3 | tr '\n' ' ')"
fi

# --- 3. the ledger the producer wrote must survive the repo's own checker ----
# The gate matches ANY string field. That is only safe because
# receipts-ledger-check.py is a closed allowlist at pre-commit, so no field the
# gate can see reached the ledger unreviewed. If the producer emits a key the
# checker refuses, closeout becomes uncommittable and CI can never go green --
# the two readers of this file must agree.
CHECK_REPO="$TMP/ledgercheck"
mkdir -p "$CHECK_REPO/.prd-os"
git -C "$CHECK_REPO" init -q
git -C "$CHECK_REPO" config user.email "test@kipi.invalid"
git -C "$CHECK_REPO" config user.name "kipi-test"
cp "$LEDGER" "$CHECK_REPO/.prd-os/receipts.jsonl" 2>/dev/null || true
git -C "$CHECK_REPO" add -f .prd-os/receipts.jsonl >/dev/null 2>&1
if (cd "$CHECK_REPO" && python3 "$LEDGER_CHECK") >/dev/null 2>&1; then
  ok "the producer's receipt passes receipts-ledger-check.py (committable)"
else
  no "the producer's receipt passes receipts-ledger-check.py (committable)" \
     "$( (cd "$CHECK_REPO" && python3 "$LEDGER_CHECK") 2>&1 | head -4 | tr '\n' ' ')"
fi

# --- 4. coverage: the receipt commit must cover the pushed head -------------
# The operator commits the ledger after closeout; that commit touches .prd-os/
# only, so the receipt still covers the head.
git -C "$REPO" add -A
git -C "$REPO" commit -qm "closeout receipt (ASK-999)"
RECEIPT_HEAD="$(git -C "$REPO" rev-parse HEAD)"

if (cd "$REPO" && python3 "$GATE" --branch sana/ask-999 --receipts "$LEDGER" \
      --head-sha "$RECEIPT_HEAD") >/dev/null 2>&1; then
  ok "gate passes when only the ledger commit sits on top of the receipt"
else
  no "gate passes when only the ledger commit sits on top of the receipt" \
     "$( (cd "$REPO" && python3 "$GATE" --branch sana/ask-999 --receipts "$LEDGER" \
           --head-sha "$RECEIPT_HEAD") 2>&1 | head -4 | tr '\n' ' ')"
fi

# --- 5. a REWORK round pushes source on top; the old receipt must NOT cover --
echo "rework fix after review" >> "$REPO/work.txt"
git -C "$REPO" add -A
git -C "$REPO" commit -qm "rework: address review finding (ASK-999)"
REWORK_HEAD="$(git -C "$REPO" rev-parse HEAD)"

(cd "$REPO" && python3 "$GATE" --branch sana/ask-999 --receipts "$LEDGER" \
   --head-sha "$REWORK_HEAD") >/dev/null 2>&1
if [ $? -ne 0 ]; then
  ok "gate refuses a REWORK push that landed source after the receipt"
else
  no "gate refuses a REWORK push that landed source after the receipt" \
     "receipt pinned $WORK_SHA but head $REWORK_HEAD carries newer source"
fi

# --- 6. the refusal must say WHY it is stale, not 'no receipt' --------------
STALE_OUT="$( (cd "$REPO" && python3 "$GATE" --branch sana/ask-999 \
  --receipts "$LEDGER" --head-sha "$REWORK_HEAD") 2>&1 )"
if printf '%s' "$STALE_OUT" | grep -qF "does not cover"; then
  ok "the stale refusal is distinguishable from 'no receipt at all'"
else
  no "the stale refusal is distinguishable from 'no receipt at all'" \
     "got: $(printf '%s' "$STALE_OUT" | head -4 | tr '\n' ' ')"
fi

# --- 7. a second closeout on the rework head clears it ----------------------
# The remediation the stale message prints has to be real. cmd_load does not
# refuse a spec whose status is already closed, so the whole flow can be run
# again -- this asserts that, rather than trusting the read.
{
  run load receipt-gate-e2e
  run mark verified
  run mark reviewed
  run mark findings_triaged
  run close
} >> "$CLOSE_LOG" 2>&1
git -C "$REPO" add -A
git -C "$REPO" commit -qm "second closeout receipt (ASK-999)"
SECOND_HEAD="$(git -C "$REPO" rev-parse HEAD)"

if (cd "$REPO" && python3 "$GATE" --branch sana/ask-999 --receipts "$LEDGER" \
      --head-sha "$SECOND_HEAD") >/dev/null 2>&1; then
  ok "re-running closeout after REWORK clears the gate (remediation is real)"
else
  no "re-running closeout after REWORK clears the gate (remediation is real)" \
     "$( (cd "$REPO" && python3 "$GATE" --branch sana/ask-999 --receipts "$LEDGER" \
           --head-sha "$SECOND_HEAD") 2>&1 | head -4 | tr '\n' ' ')"
fi

echo
echo "passed: $pass  failed: $fail"
[ "$fail" -eq 0 ] || exit 1
echo "OK"
