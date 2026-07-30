#!/usr/bin/env bash
# Will codex actually review Sana's work on the next scheduled run? (ASK-253)
#
# WHY THIS EXISTS: on 2026-07-29 I wrote a guard, tested it green, and then told the
# reviewer it had shipped. It had not -- it sat uncommitted while four commits went
# past it, because I claimed shipped state from memory instead of reading it. This
# script is that claim, made executable.
#
# THE CHECK THAT MATTERS MOST IS #3. The launchd job runs a FIXED PATH out of the
# plist, and that checkout sits on whatever branch it sits on. Wiring merged into a
# feature branch changes nothing about tomorrow. So this reads the ACTUAL FILE the
# scheduler will execute, not a repo-relative path and not this branch's copy.
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

# --- 2. resolve the EXACT script the scheduler will execute ------------------
# Read it out of the plist rather than assuming the conventional path: the whole
# point is to check the running system, not the one described in a doc.
DISPATCH="$(plutil -extract ProgramArguments.1 raw -o - "$PLIST" 2>/dev/null)"
if [ -n "$DISPATCH" ] && [ -f "$DISPATCH" ]; then
  pass "plist points at an existing dispatcher: $DISPATCH"
else
  fail "plist ProgramArguments.1 does not resolve to a file: '${DISPATCH:-<empty>}'"
  echo; echo "RESULT: NOT WIRED ($FAILED failed)"; exit 1
fi
LIVE_ROOT="$(cd "$(dirname "$DISPATCH")" && pwd)"
LIVE_WORKER="$LIVE_ROOT/q-system/.q-system/scripts/linear-worker.sh"
LIVE_SYNC="$LIVE_ROOT/q-system/.q-system/scripts/linear-sync.py"
info "live repo root: $LIVE_ROOT"
info "live branch:    $(git -C "$LIVE_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
info "live HEAD:      $(git -C "$LIVE_ROOT" rev-parse --short HEAD 2>/dev/null || echo '?')"

# --- 3. THE WIRING IS IN THE FILE THAT WILL RUN ------------------------------
if [ ! -f "$LIVE_WORKER" ]; then
  fail "no worker at $LIVE_WORKER"
else
  if grep -q 'delegate "\$ISSUE" --agent Codex' "$LIVE_WORKER"; then
    pass "the live worker delegates to Codex"
  else
    fail "the live worker does NOT delegate to Codex. Tomorrow's run reviews with Claude only. If the wiring is on a branch, it has to reach $(git -C "$LIVE_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)."
  fi
  if grep -q 'agent-verdict "\$ISSUE"' "$LIVE_WORKER"; then
    pass "the live worker reads codex's verdict back"
  else
    fail "the live worker never reads agent-verdict, so codex's answer reaches no gate"
  fi
  if grep -q 'context=kipi/codex-approved' "$LIVE_WORKER"; then
    pass "the live worker posts kipi/codex-approved"
  else
    fail "the live worker posts no codex commit status, so the verdict is invisible to GitHub"
  fi
  if grep -q 'CODEX_MARK' "$LIVE_WORKER"; then
    pass "the delegation is bounded (once per PR head sha)"
  else
    fail "NO once-per-sha bound in the live worker. It runs every 900s and each delegation starts a PAID codex session, so this is a runaway bill, not a cosmetic gap."
  fi
  bash -n "$LIVE_WORKER" 2>/dev/null && pass "the live worker parses" \
    || fail "the live worker does NOT parse; the whole run dies"
fi

# --- 4. the verbs it calls exist IN THE LIVE COPY ----------------------------
if [ ! -f "$LIVE_SYNC" ]; then
  fail "no linear-sync.py at $LIVE_SYNC"
else
  for verb in delegate agent-verdict; do
    if python3 "$LIVE_SYNC" "$verb" --help >/dev/null 2>&1; then
      pass "live linear-sync.py implements '$verb'"
    else
      fail "live linear-sync.py has NO '$verb' verb, so the worker's call fails at runtime"
    fi
  done
fi

# --- 5. the agent actually resolves in Linear (live, one cheap query) --------
# Wiring that points at an agent name Linear does not know is a silent no-op, which
# is why cmd_delegate refuses an unknown name instead of leaving it undelegated.
if [ -f "$LIVE_SYNC" ] && [ "${SKIP_LIVE:-0}" != "1" ]; then
  if python3 - "$LIVE_SYNC" <<'PY' 2>/dev/null
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ls", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
q = 'query($q: String!) { users(filter: { name: { eqIgnoreCase: $q } }) { nodes { id name } } }'
sys.exit(0 if (m.graphql(q, {"q": "Codex"}).get("users", {}).get("nodes")) else 1)
PY
  then pass "Linear resolves an agent named 'Codex'"
  else fail "Linear does NOT resolve an agent named 'Codex'; delegation would BLOCK every run"
  fi
else
  info "skipped the live Linear check (SKIP_LIVE=1)"
fi

# --- 6. when does it next get a chance, and is the budget spent? -------------
INTERVAL="$(plutil -extract StartInterval raw -o - "$PLIST" 2>/dev/null || echo '?')"
info "StartInterval: ${INTERVAL}s"
LOG="$HOME/.config/kipi/dispatch.log"
if [ -f "$LOG" ]; then
  info "last dispatch line: $(tail -1 "$LOG")"
  if tail -5 "$LOG" | grep -q "DAILY CAP"; then
    info "daily cap is spent; the next real dispatch is after the 07:00 local reset"
  fi
else
  info "no dispatch log yet at $LOG"
fi

echo
if [ "$FAILED" -eq 0 ]; then
  echo "RESULT: WIRED -- codex reviews the next issue the dispatcher picks up."
  exit 0
fi
echo "RESULT: NOT WIRED ($FAILED check(s) failed). Codex will NOT review tomorrow."
exit 1
