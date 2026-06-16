#!/usr/bin/env bash
# install-capability-token.sh - idempotent install of the capability-token
# system:
#   - copies capability-token.sh and kipi-approve to ~/.claude/bin (0755)
#   - creates ~/.claude/approvals locked to the owner (0700)
#   - replaces the destructive-op-deny hook's emit_deny chokepoint with a version
#     that consults a single-use capability token before denying
#
# emit_deny is the ONE function every denial (bash patterns + MCP) flows through,
# so patching it there covers all paths with a single edit. Fail closed: a
# missing or failing token script means deny. Safe to re-run.
#
# Sources are always taken from this script's own directory (never an env
# override), so the installer cannot be pointed at a forged checker.
set -uo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/.claude/bin"
HOOK="$HOME/.claude/hooks/destructive-op-deny.sh"
APPROVALS="$HOME/.claude/approvals"
# Idempotency is keyed on the actual functional integration line, not a comment
# marker (a stale/spoofed comment must not make us skip a real patch).
INTEG_SIG='"$_ct" check "$COMMAND"'

die() { echo "install: $1" >&2; exit 1; }

mkdir -p "$BIN_DIR" || die "cannot create $BIN_DIR"
install -m 0755 "$SRC_DIR/capability-token.sh" "$BIN_DIR/capability-token.sh" || die "failed to install capability-token.sh"
install -m 0755 "$SRC_DIR/kipi-approve"        "$BIN_DIR/kipi-approve"        || die "failed to install kipi-approve"
[ -x "$BIN_DIR/capability-token.sh" ] || die "capability-token.sh not executable after install"
[ -x "$BIN_DIR/kipi-approve" ]        || die "kipi-approve not executable after install"

mkdir -p "$APPROVALS" || die "cannot create $APPROVALS"
chmod 0700 "$APPROVALS" || die "cannot secure $APPROVALS (0700)"

if [ ! -f "$HOOK" ]; then
  echo "install: hook not found at $HOOK; scripts installed, hook left unpatched" >&2
  exit 0
fi

if grep -qF "$INTEG_SIG" "$HOOK"; then
  echo "install: hook already integrated (idempotent no-op)"
  exit 0
fi

tmp="$HOOK.capabilitytmp.$$"
python3 - "$HOOK" "$tmp" <<'PY'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src).read()
# Count ALL plausible emit_deny definition spellings (with/without `function`,
# with/without spaces). There must be exactly one, or a later redefinition could
# be the one bash actually honors at call time. (codex-adversarial finding)
defs = len(re.findall(r'(?m)^\s*(?:function\s+)?emit_deny\b\s*(?:\(\s*\))?\s*\{', text))
if defs != 1:
    sys.stderr.write("install: expected exactly one emit_deny definition, found %d\n" % defs)
    sys.exit(4)
new_func = r'''emit_deny() {
  # capability-token-integration: a single-use, command-scoped approval minted
  # out-of-band by the founder (kipi-approve <hash>) allows exactly this command
  # once. Fail closed: a missing or failing token script denies.
  local reason="$1"
  local _ct="$HOME/.claude/bin/capability-token.sh"
  if [ -x "$_ct" ] && "$_ct" check "$COMMAND" "$CWD"; then
    log_decision "allow" "capability token consumed"
    exit 0
  fi
  local _hash=""
  [ -x "$_ct" ] && _hash="$("$_ct" hash "$COMMAND" "$CWD" 2>/dev/null || true)"
  log_decision "deny" "$reason"
  jq -nc --arg reason "$reason" --arg hash "$_hash" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: ("destructive-op-deny: " + $reason + ". Approve THIS command out-of-band: kipi-approve " + $hash + "  (or set ALLOW_DESTRUCTIVE=1 to bypass all).")
    }
  }'
  exit 0
}'''
# Replace the canonical definition only (anchored, line start). If the single
# definition is some non-canonical spelling, this matches 0 -> abort.
new, n = re.subn(r'(?ms)^emit_deny\(\) \{.*?\n\}', lambda m: new_func, text, count=1)
if n != 1:
    sys.stderr.write("install: could not locate the canonical emit_deny() to replace (matched %d)\n" % n)
    sys.exit(3)
open(dst, "w").write(new)
PY
rc=$?
if [ "$rc" -ne 0 ]; then echo "install: hook patch failed (rc=$rc)" >&2; rm -f "$tmp"; exit 1; fi
grep -qF "$INTEG_SIG" "$tmp" || { echo "install: integration line missing after patch" >&2; rm -f "$tmp"; exit 1; }
# Never install a syntactically broken hook (that would disable enforcement).
bash -n "$tmp" || { echo "install: patched hook failed syntax check, not installing" >&2; rm -f "$tmp"; exit 1; }
# Explicit, umask-independent permissions on the enforcement hook.
chmod 0755 "$tmp" || { echo "install: cannot set hook permissions" >&2; rm -f "$tmp"; exit 1; }
mv "$tmp" "$HOOK" || { echo "install: cannot replace hook" >&2; rm -f "$tmp"; exit 1; }
echo "install: hook integrated"
