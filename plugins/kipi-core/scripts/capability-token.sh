#!/usr/bin/env bash
# capability-token.sh - single-source logic for command-scoped, single-use
# destructive-op approval tokens (the "capability" in capability-based security).
#
# Why this exists: the destructive-op-deny hook's only bypass was
# ALLOW_DESTRUCTIVE=1, ambient authority that approves EVERY destructive op for
# the whole session window. PocketOS 2026-05-17: an agent deleted a production
# volume while a broad approval was open. A capability token authorizes exactly
# one command (hash of command+cwd), once, then is consumed. Spec:
# .prd-os/prds/prd-capability-approval-token-2026-06-16.md
#
# Single-writer chokepoint: `mint` is the only creator of tokens, `check` is the
# only consumer. The hook only ever calls `check`; the founder only ever calls
# `mint` (via kipi-approve), out of band. Everything fails closed.

set -uo pipefail

# Pin PATH so the security-critical externals (mv, cat, date, sha256, awk)
# cannot be hijacked by a caller-controlled PATH. (codex-adversarial finding-4)
export PATH=/usr/bin:/bin:/usr/sbin:/sbin

# Trust root is FIXED in production. The env overrides are honored only when
# CAPABILITY_TOKEN_TEST=1, so a stray or poisoned CAPABILITY_TOKEN_DIR in the
# environment cannot redirect `check` at a forged token directory. The hook
# never sets the test flag. (codex finding-1)
if [ "${CAPABILITY_TOKEN_TEST:-0}" = "1" ]; then
  APPROVALS_DIR="${CAPABILITY_TOKEN_DIR:-$HOME/.claude/approvals}"
  AUDIT_LOG="${CAPABILITY_TOKEN_LOG:-$HOME/.claude/audit/destructive-op-deny.log}"
  TTL="${CAPABILITY_TOKEN_TTL:-300}"
else
  APPROVALS_DIR="$HOME/.claude/approvals"
  AUDIT_LOG="$HOME/.claude/audit/destructive-op-deny.log"
  TTL=300   # seconds; 5 minutes
fi

_sha256() {
  # Portable sha256 -> 64 lowercase hex chars (Linux sha256sum / macOS shasum).
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
  else
    shasum -a 256 | awk '{print $1}'
  fi
}

_now() { date +%s; }

_log() {
  # Best-effort audit append. A logging failure must never change the security
  # decision, so all failures here are swallowed.
  local event="$1" hash="$2" detail="$3" ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  { mkdir -p "$(dirname "$AUDIT_LOG")" 2>/dev/null \
      && printf '{"ts":"%s","event":"%s","hash":"%s","expiry":"%s"}\n' \
         "$ts" "$event" "$hash" "$detail" >> "$AUDIT_LOG"; } 2>/dev/null || true
}

cmd_hash() {
  # hash <command> <cwd>. Unambiguous binding: hash each part separately, then
  # hash the two fixed-length hex digests together. (command + LF + cwd was
  # ambiguous when a value contained a newline; codex finding-2.) Verbatim, no
  # normalization: any byte difference yields a different hash, failing closed.
  local command="${1-}" cwd="${2-}" hc hd
  hc="$(printf '%s' "$command" | _sha256)" || return 1
  hd="$(printf '%s' "$cwd" | _sha256)" || return 1
  printf '%s:%s' "$hc" "$hd" | _sha256
}

cmd_check() {
  # check <command> <cwd>: exit 0 (allow) iff a valid unexpired token exists,
  # consuming it atomically. Exit 1 (deny) otherwise.
  local command="${1-}" cwd="${2-}"
  local hash tokenfile claim now expiry
  hash="$(cmd_hash "$command" "$cwd")" || return 1
  tokenfile="$APPROVALS_DIR/$hash.token"
  claim="$tokenfile.consuming.$$"
  # Atomic claim: rename is atomic within a filesystem, so two concurrent
  # checks cannot both win the same grant. The loser's mv fails -> deny.
  mv "$tokenfile" "$claim" 2>/dev/null || return 1
  expiry="$(cat "$claim" 2>/dev/null || true)"
  rm -f "$claim" 2>/dev/null || true
  # A non-integer expiry is treated as expired (fail closed).
  case "$expiry" in
    ''|*[!0-9]*) _log "consume" "$hash" "malformed"; return 1 ;;
  esac
  now="$(_now)"
  if [ "$expiry" -gt "$now" ]; then
    _log "consume" "$hash" "$expiry"
    return 0
  fi
  _log "consume" "$hash" "expired:$expiry"
  return 1
}

cmd_mint() {
  # mint <hash>: write a single-use token for <hash> with now+TTL expiry, prune
  # already-expired tokens, log the grant. <hash> is the value the hook printed.
  local hash="${1-}"
  case "$hash" in
    ''|*[!0-9a-f]*) echo "mint: hash must be 64 lowercase hex chars" >&2; return 2 ;;
  esac
  [ "${#hash}" -eq 64 ] || { echo "mint: hash must be 64 lowercase hex chars" >&2; return 2; }
  mkdir -p "$APPROVALS_DIR" 2>/dev/null || { echo "mint: cannot create $APPROVALS_DIR" >&2; return 1; }
  # Fail closed if the dir cannot be locked to the owner only. (codex finding-3)
  chmod 0700 "$APPROVALS_DIR" || { echo "mint: cannot secure $APPROVALS_DIR (0700)" >&2; return 1; }
  local now f exp
  now="$(_now)"
  # Prune so the dir does not accumulate stale grants.
  for f in "$APPROVALS_DIR"/*.token; do
    [ -e "$f" ] || continue
    exp="$(cat "$f" 2>/dev/null || true)"
    case "$exp" in
      ''|*[!0-9]*) rm -f "$f" 2>/dev/null || true; continue ;;
    esac
    [ "$exp" -gt "$now" ] || rm -f "$f" 2>/dev/null || true
  done
  local expiry tmp
  expiry=$(( now + TTL ))
  tmp="$APPROVALS_DIR/$hash.token.minting.$$"
  printf '%s' "$expiry" > "$tmp" || { echo "mint: write failed" >&2; return 1; }
  mv "$tmp" "$APPROVALS_DIR/$hash.token" || { rm -f "$tmp" 2>/dev/null || true; echo "mint: install failed" >&2; return 1; }
  _log "grant" "$hash" "$expiry"
  echo "approved one command (hash ${hash:0:12}...), expires in ${TTL}s"
  return 0
}

main() {
  local sub="${1-}"
  shift 2>/dev/null || true
  case "$sub" in
    hash)  cmd_hash "${1-}" "${2-}" ;;
    check) cmd_check "${1-}" "${2-}" ;;
    mint)  cmd_mint "${1-}" ;;
    *) echo "usage: capability-token.sh {hash|check|mint} ..." >&2; return 2 ;;
  esac
}

main "$@"
