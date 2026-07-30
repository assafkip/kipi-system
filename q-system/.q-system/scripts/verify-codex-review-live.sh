#!/usr/bin/env bash
# Will codex actually review Sana's work on the next scheduled run? (ASK-221)
#
# WHY THIS EXISTS: on 2026-07-29 a guard was written, tested green, and reported as
# shipped. It had not shipped -- it sat uncommitted while four commits went past it,
# because shipped state was claimed from memory instead of read. This script is that
# claim, made executable.
#
# RETARGETED FROM ASK-253. The first version checked the Linear-agent DELEGATION
# path (`linear-sync.py delegate --agent Codex`). That path was rejected: its status
# was advisory, so it could not gate, and it added a third verdict reader. What ships
# is the ENGINE path -- linear-worker.sh calls pr-review-agent.sh --engine codex, and
# codex owns the REQUIRED `kipi/reviewer-approved` context. The load-path discipline
# below is the part worth keeping; only the assertions changed.
#
# THE CHECK THAT MATTERS MOST IS #3. The launchd job runs a FIXED PATH out of the
# plist, and that checkout sits on whatever branch it sits on. Wiring merged into a
# feature branch changes nothing about tomorrow. So this reads the ACTUAL FILES the
# scheduler will execute -- never a repo-relative path, never this branch's copy.
#
# WHAT IT CANNOT TELL YOU: that a review RAN. Wiring is a precondition, not a
# receipt. The receipt is a dispatch-log line showing a codex verdict on a real PR.
# Check 8 reads that log rather than asserting from the wiring.
#
# Exit 0 = codex is wired into the next run. Non-zero = it is not, with the reason.
set -uo pipefail

PLIST="$HOME/Library/LaunchAgents/com.kipi.dispatch.plist"
LABEL="com.kipi.dispatch"
FAILED=0
pass() { printf '  PASS %s\n' "$1"; }
fail() { printf '  FAIL %s\n' "$1"; FAILED=$((FAILED+1)); }
info() { printf '  ---- %s\n' "$1"; }

echo "codex-review live-wiring check ($(date -u +%Y-%m-%dT%H:%M:%SZ))"

# --- 1. the scheduler exists and is loaded -----------------------------------
# CAPTURE FIRST, then match. `launchctl list | grep -q "$LABEL"` under
# `set -o pipefail` reports FAILURE on a job that IS loaded: grep -q exits the
# instant it matches, launchctl dies on the closed pipe with SIGPIPE, and pipefail
# propagates that as the pipeline's status. This check gave a false NOT-LOADED the
# first time it ran, on a job `launchctl print` resolves fine.
LAUNCHCTL_LIST="$(launchctl list 2>/dev/null || true)"
if printf '%s\n' "$LAUNCHCTL_LIST" | grep -q "$LABEL"; then
  pass "launchd job $LABEL is loaded"
else
  fail "launchd job $LABEL is NOT loaded, so nothing runs on a schedule at all"
fi

[ -f "$PLIST" ] || { fail "no plist at $PLIST"; echo; echo "RESULT: NOT WIRED ($FAILED failed)"; exit 1; }

# --- 2. resolve the EXACT files the scheduler will execute -------------------
# Read the path out of the plist rather than assuming the conventional one: the
# whole point is to check the running system, not the one described in a doc.
DISPATCH="$(plutil -extract ProgramArguments.1 raw -o - "$PLIST" 2>/dev/null)"
if [ -n "$DISPATCH" ] && [ -f "$DISPATCH" ]; then
  pass "plist points at an existing dispatcher: $DISPATCH"
else
  fail "plist ProgramArguments.1 does not resolve to a file: '${DISPATCH:-<empty>}'"
  echo; echo "RESULT: NOT WIRED ($FAILED failed)"; exit 1
fi
LIVE_ROOT="$(cd "$(dirname "$DISPATCH")" && pwd)"
LIVE_SCRIPTS="$LIVE_ROOT/q-system/.q-system/scripts"
LIVE_WORKER="$LIVE_SCRIPTS/linear-worker.sh"
LIVE_REVIEWER="$LIVE_SCRIPTS/pr-review-agent.sh"
LIVE_LIB="$LIVE_SCRIPTS/pr-verdict-lib.sh"
info "live repo root: $LIVE_ROOT"
info "live branch:    $(git -C "$LIVE_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
info "live HEAD:      $(git -C "$LIVE_ROOT" rev-parse --short HEAD 2>/dev/null || echo '?')"

# --- 3. THE WIRING IS IN THE FILE THAT WILL RUN ------------------------------
if [ ! -f "$LIVE_WORKER" ]; then
  fail "no worker at $LIVE_WORKER"
else
  if grep -q -- '--engine codex' "$LIVE_WORKER"; then
    pass "the live worker dispatches the reviewer with --engine codex"
  else
    fail "the live worker never passes --engine codex. Tomorrow's run reviews with Claude only -- same lab as the author, so the blind spots stay correlated. If the wiring is on a branch, it has to reach $(git -C "$LIVE_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)."
  fi
  if grep -q 'pr-review-agent.sh' "$LIVE_WORKER"; then
    pass "the live worker routes review through pr-review-agent.sh"
  else
    fail "the live worker does not call pr-review-agent.sh at all, so no engine flag matters"
  fi
  bash -n "$LIVE_WORKER" 2>/dev/null && pass "the live worker parses" \
    || fail "the live worker does NOT parse; the whole run dies"
fi

# --- 4. the live reviewer makes codex THE GATE, not a second opinion ---------
if [ ! -f "$LIVE_REVIEWER" ]; then
  fail "no reviewer at $LIVE_REVIEWER"
else
  if grep -qE 'KIPI_REVIEW_ENGINE:-codex' "$LIVE_REVIEWER"; then
    pass "the live reviewer defaults to the codex engine"
  else
    fail "the live reviewer's default engine is not codex, so a bare invocation reviews with Claude"
  fi
  if grep -qE 'KIPI_REVIEW_PRIMARY_ENGINE:-codex' "$LIVE_REVIEWER"; then
    pass "codex is the PRIMARY engine, so it owns kipi/reviewer-approved"
  else
    fail "codex is not the primary engine in the live copy, so its verdict lands on an ADVISORY context and gates nothing"
  fi
  if grep -q 'kipi/reviewer-approved' "$LIVE_REVIEWER"; then
    pass "the live reviewer posts the required context kipi/reviewer-approved"
  else
    fail "the live reviewer posts no kipi/reviewer-approved status, so the verdict is invisible to GitHub and every PR waits on a human"
  fi
  # The ASK-221 provenance guard. A reviewer that reads one tree and diffs another
  # writes findings with false provenance, which is worse than a wrong verdict.
  if grep -q 'merge-base --is-ancestor' "$LIVE_REVIEWER"; then
    pass "the live reviewer has the tree-vs-PR-head guard"
  else
    fail "the LIVE reviewer has NO tree-vs-head guard. A scheduled run from the wrong worktree would review this tree's files against another PR's diff and stamp the findings with that PR's sha."
  fi
  bash -n "$LIVE_REVIEWER" 2>/dev/null && pass "the live reviewer parses" \
    || fail "the live reviewer does NOT parse"
fi

# --- 5. ONE findings-block reader in the LIVE lib ----------------------------
# sp-c0a9dac3. Comments are stripped first because findings_block's own comment
# QUOTES the sed expression it replaced -- assert on code, not on prose about code.
if [ ! -f "$LIVE_LIB" ]; then
  fail "no verdict lib at $LIVE_LIB"
else
  SEDS="$(grep -v '^[[:space:]]*#' "$LIVE_LIB" | grep -c 'FINDINGS:/,/' | tr -d ' ')"
  if [ "$SEDS" = "0" ] && grep -q '^findings_block()' "$LIVE_LIB"; then
    pass "the live lib has one findings_block reader and no sed findings-ranges in code"
  else
    fail "the live lib still has $SEDS sed findings-range extraction(s) / no findings_block. A quoted prior-round block concatenates onto the real one, so a refuted finding can set the gate."
  fi
  bash -n "$LIVE_LIB" 2>/dev/null && pass "the live lib parses" \
    || fail "the live lib does NOT parse, so every review dies at the source line"
fi

# --- 6. the engine binary the live reviewer will shell actually exists -------
# Wiring that names a binary the PATH does not have degrades to the Opus fallback
# on every run: the gate stays green and stops being a second lab's opinion.
if command -v codex >/dev/null 2>&1; then
  pass "codex is on PATH ($(command -v codex))"
else
  fail "codex is NOT on PATH. Every scheduled review falls back to Opus and the gate is DEGRADED, which is exactly the independence this engine exists to buy."
fi

# --- 7. the live copy's OWN tests pass against the live copy ------------------
# The load-path proof with teeth: run the test files that ship in the LIVE tree, so
# they resolve their target from their own location. Greping the live file for a
# string proves the text is there; this proves the behaviour is.
for t in test-review-tree-guard.sh test-findings-block-reader.sh; do
  if [ -f "$LIVE_SCRIPTS/test/$t" ]; then
    if bash "$LIVE_SCRIPTS/test/$t" >/dev/null 2>&1; then
      pass "live $t passes against the live tree"
    else
      fail "live $t FAILS against the live tree. Run it directly for the reason: bash $LIVE_SCRIPTS/test/$t"
    fi
  else
    fail "no $t in the live tree, so the guard it covers is unproven where it matters"
  fi
done

# --- 8. when does it next get a chance, and has it ever actually run? --------
# The receipt, as opposed to the wiring. A codex verdict line in the dispatch log is
# the only thing here that proves a review HAPPENED.
INTERVAL="$(plutil -extract StartInterval raw -o - "$PLIST" 2>/dev/null || echo '?')"
info "StartInterval: ${INTERVAL}s"
LOG="$HOME/.config/kipi/dispatch.log"
if [ -f "$LOG" ]; then
  info "last dispatch line: $(tail -1 "$LOG")"
  if grep -q 'engine: codex' "$LOG" 2>/dev/null; then
    info "RECEIPT FOUND: the log records at least one codex-engine review run"
  else
    info "NO RECEIPT YET: the log has no codex-engine review line. Wiring is green; a real run has not been observed."
  fi
  if tail -5 "$LOG" | grep -q "DAILY CAP"; then
    info "daily cap is spent; the next real dispatch is after the 07:00 local reset"
  fi
else
  info "no dispatch log yet at $LOG"
fi

echo
if [ "$FAILED" -eq 0 ]; then
  echo "RESULT: WIRED -- codex reviews the next PR the dispatcher picks up."
  exit 0
fi
echo "RESULT: NOT WIRED ($FAILED check(s) failed). Codex will NOT review on the next run."
exit 1
