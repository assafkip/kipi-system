#!/usr/bin/env bash
# test-capability-token-wiring.sh - integration test for install + hook patch.
#
# Verified against a COPY of the real destructive-op-deny hook in a throwaway
# HOME (fable-discipline: verify against a copy, never the live file). Proves:
#   - install is idempotent and sets the right permissions
#   - a destructive command is denied with no token
#   - it is allowed exactly once after kipi-approve, then denied again
#   - it fails closed (denies) when the token script is absent
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$(cd "$HERE/.." && pwd)"
REAL_HOOK="$HOME/.claude/hooks/destructive-op-deny.sh"

fail=0
ok()  { printf 'ok   - %s\n' "$1"; }
bad() { printf 'FAIL - %s\n' "$1"; fail=1; }

if [ ! -f "$REAL_HOOK" ]; then
  echo "FAIL - real hook not found at $REAL_HOOK (integration target missing)"
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"
mkdir -p "$HOME/.claude/hooks"
cp "$REAL_HOOK" "$HOME/.claude/hooks/destructive-op-deny.sh"

HOOK="$HOME/.claude/hooks/destructive-op-deny.sh"
CT="$HOME/.claude/bin/capability-token.sh"
KA="$HOME/.claude/bin/kipi-approve"

# Install against the throwaway HOME (patches the copied hook, installs scripts).
if SRC_DIR="$SCRIPTS" bash "$SCRIPTS/install-capability-token.sh" >/dev/null 2>&1; then ok "install ran"; else bad "install failed"; fi
[ -x "$CT" ] && ok "capability-token.sh installed executable" || bad "lib not installed"
[ -x "$KA" ] && ok "kipi-approve installed executable" || bad "kipi-approve not installed"
perm="$(stat -f '%Lp' "$HOME/.claude/approvals" 2>/dev/null || stat -c '%a' "$HOME/.claude/approvals" 2>/dev/null)"
[ "$perm" = "700" ] && ok "approvals dir is 0700" || bad "approvals dir perm=$perm (want 700)"

# Idempotent: a second install must not double-patch emit_deny.
SRC_DIR="$SCRIPTS" bash "$SCRIPTS/install-capability-token.sh" >/dev/null 2>&1
defs="$(grep -c '^emit_deny() {' "$HOOK")"
[ "$defs" -eq 1 ] && ok "idempotent: single emit_deny after re-install" || bad "emit_deny defined $defs times"
grep -q 'capability-token-integration' "$HOOK" && ok "hook patched (marker present)" || bad "hook not patched"

CMD='rm -rf /tmp/integration-x'
CWD='/Users/x/project'
decision() {
  printf '{"tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"%s"}' "$1" "$2" \
    | bash "$HOOK" 2>/dev/null | grep -o '"permissionDecision":"[a-z]*"' | head -1
}

# 1. destructive command, no token -> deny.
d="$(decision "$CMD" "$CWD")"
[ "$d" = '"permissionDecision":"deny"' ] && ok "no token -> deny" || bad "no token expected deny, got [$d]"

# 2. founder approves via kipi-approve -> allow exactly once (no deny emitted).
H="$(bash "$CT" hash "$CMD" "$CWD")"
bash "$KA" "$H" >/dev/null
d="$(decision "$CMD" "$CWD")"
[ -z "$d" ] && ok "approved command -> allow" || bad "approved expected allow, got [$d]"

# 3. second attempt -> deny (token consumed).
d="$(decision "$CMD" "$CWD")"
[ "$d" = '"permissionDecision":"deny"' ] && ok "consumed -> second attempt denies" || bad "second expected deny, got [$d]"

# 4. fail closed: with a fresh grant but the token script removed, deny.
bash "$KA" "$H" >/dev/null
rm -f "$CT"
d="$(decision "$CMD" "$CWD")"
[ "$d" = '"permissionDecision":"deny"' ] && ok "missing token script -> deny (fail closed)" || bad "absent script expected deny, got [$d]"

if [ "$fail" -ne 0 ]; then echo "TESTS FAILED"; exit 1; fi
echo "ALL TESTS PASSED"
