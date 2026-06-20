#!/usr/bin/env bash
# capability-token.sh - command-scoped, single-use, SIGNED destructive-op
# approval tokens (the "capability" in capability-based security).
#
# Phase 1 closed the approval window. Phase 2 (this version) closes forgery: a
# token is honored only if it carries a valid signature over a domain-separated
# payload from the trusted key. The signing key lives in the Secure Enclave,
# gated by Touch ID, so an agent that merely writes a token file cannot forge a
# valid one. Spec: .prd-os/prds/prd-capability-token-signing-2026-06-16.md
#
# Single-writer chokepoint: mint creates tokens (signing via the configured
# backend), check consumes them. Everything fails closed: any error, missing
# token, missing/altered public key, missing/invalid signature, expired or
# malformed token denies. There is NO downgrade to unsigned acceptance.

set -uo pipefail

# Pin PATH so security-critical externals (mv, cat, sed, openssl, base64) cannot
# be hijacked via a caller-controlled PATH. openssl here is the system LibreSSL
# at /usr/bin/openssl. (phase-1 codex-adversarial finding)
export PATH=/usr/bin:/bin:/usr/sbin:/sbin

# Trust root and backends are FIXED in production. Env overrides are honored
# only under CAPABILITY_TOKEN_TEST=1; the production hook never sets it.
if [ "${CAPABILITY_TOKEN_TEST:-0}" = "1" ]; then
  APPROVALS_DIR="${CAPABILITY_TOKEN_DIR:-$HOME/.claude/approvals}"
  AUDIT_LOG="${CAPABILITY_TOKEN_LOG:-$HOME/.claude/audit/destructive-op-deny.log}"
  TTL="${CAPABILITY_TOKEN_TTL:-300}"
  SIGNER="${CAPABILITY_SIGNER:-$HOME/.claude/bin/capability-signer sign}"
  PUBKEY="${CAPABILITY_PUBKEY:-$HOME/.claude/capability-token.pub}"
else
  APPROVALS_DIR="$HOME/.claude/approvals"
  AUDIT_LOG="$HOME/.claude/audit/destructive-op-deny.log"
  TTL=300
  SIGNER="$HOME/.claude/bin/capability-signer sign"
  PUBKEY="$HOME/.claude/capability-token.pub"
fi

_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum | awk '{print $1}'
  else shasum -a 256 | awk '{print $1}'; fi
}
_now() { date +%s; }

_log() {
  local event="$1" hash="$2" detail="$3" ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  { mkdir -p "$(dirname "$AUDIT_LOG")" 2>/dev/null \
      && printf '{"ts":"%s","event":"%s","hash":"%s","expiry":"%s"}\n' \
         "$ts" "$event" "$hash" "$detail" >> "$AUDIT_LOG"; } 2>/dev/null || true
}

cmd_hash() {
  # hash(command + LF + cwd), verbatim, full 64 hex. (phase-1 behavior, unchanged)
  local command="${1-}" cwd="${2-}" hc hd
  hc="$(printf '%s' "$command" | _sha256)" || return 1
  hd="$(printf '%s' "$cwd" | _sha256)" || return 1
  printf '%s:%s' "$hc" "$hd" | _sha256
}

# Domain-separated, versioned signed payload. Binding the version + both fields
# prevents cross-protocol signature reuse. (codex finding)
_payload() { printf 'capability-token.v1\n%s\n%s' "$1" "$2"; }   # hash, expiry

cmd_check() {
  # check <command> <cwd>: exit 0 (allow) iff a token exists whose signature
  # over the v1 payload verifies against the trusted pubkey AND is unexpired.
  # Atomically claim first (single-winner), then VERIFY before allowing.
  local command="${1-}" cwd="${2-}"
  local hash tokenfile claim expiry sig payload now sigder payfile rc
  hash="$(cmd_hash "$command" "$cwd")" || return 1
  tokenfile="$APPROVALS_DIR/$hash.token"
  claim="$tokenfile.consuming.$$"
  mv "$tokenfile" "$claim" 2>/dev/null || return 1     # atomic claim (consume)
  expiry="$(sed -n '1p' "$claim" 2>/dev/null)"
  sig="$(sed -n '2p' "$claim" 2>/dev/null)"
  rm -f "$claim" 2>/dev/null || true
  case "$expiry" in ''|*[!0-9]*) _log consume "$hash" malformed; return 1 ;; esac
  [ -n "$sig" ] || { _log consume "$hash" no-sig; return 1; }
  # NO DOWNGRADE: a missing or unreadable trusted pubkey denies.
  [ -r "$PUBKEY" ] || { _log consume "$hash" no-pubkey; return 1; }
  payload="$(_payload "$hash" "$expiry")"
  sigder="$(mktemp)" || return 1
  payfile="$(mktemp)" || { rm -f "$sigder"; return 1; }
  printf '%s' "$sig" | openssl base64 -d -A > "$sigder" 2>/dev/null
  printf '%s' "$payload" > "$payfile"
  openssl dgst -sha256 -verify "$PUBKEY" -signature "$sigder" "$payfile" >/dev/null 2>&1
  rc=$?
  rm -f "$sigder" "$payfile" 2>/dev/null || true
  if [ "$rc" -ne 0 ]; then _log consume "$hash" bad-sig; return 1; fi
  now="$(_now)"
  if [ "$expiry" -gt "$now" ]; then _log consume "$hash" "$expiry"; return 0; fi
  _log consume "$hash" "expired:$expiry"
  return 1
}

cmd_mint() {
  # mint <hash>: sign the v1 payload and write a two-line token (expiry, sig-b64).
  local hash="${1-}"
  case "$hash" in ''|*[!0-9a-f]*) echo "mint: hash must be 64 lowercase hex chars" >&2; return 2 ;; esac
  [ "${#hash}" -eq 64 ] || { echo "mint: hash must be 64 lowercase hex chars" >&2; return 2; }
  mkdir -p "$APPROVALS_DIR" 2>/dev/null || { echo "mint: cannot create $APPROVALS_DIR" >&2; return 1; }
  chmod 0700 "$APPROVALS_DIR" || { echo "mint: cannot secure $APPROVALS_DIR (0700)" >&2; return 1; }
  local now f exp
  now="$(_now)"
  for f in "$APPROVALS_DIR"/*.token; do
    [ -e "$f" ] || continue
    exp="$(sed -n '1p' "$f" 2>/dev/null)"
    case "$exp" in ''|*[!0-9]*) rm -f "$f" 2>/dev/null || true; continue ;; esac
    [ "$exp" -gt "$now" ] || rm -f "$f" 2>/dev/null || true
  done
  local expiry payload sig tmp
  expiry=$(( now + TTL ))
  payload="$(_payload "$hash" "$expiry")"
  # shellcheck disable=SC2086 -- SIGNER is a trusted command line (word-split intentional)
  sig="$(printf '%s' "$payload" | $SIGNER 2>/dev/null)" || { echo "mint: signing failed" >&2; return 1; }
  [ -n "$sig" ] || { echo "mint: signer produced no signature" >&2; return 1; }
  tmp="$APPROVALS_DIR/$hash.token.minting.$$"
  printf '%s\n%s\n' "$expiry" "$sig" > "$tmp" || { echo "mint: write failed" >&2; return 1; }
  mv "$tmp" "$APPROVALS_DIR/$hash.token" || { rm -f "$tmp" 2>/dev/null || true; echo "mint: install failed" >&2; return 1; }
  _log grant "$hash" "$expiry"
  echo "approved one command (hash ${hash:0:12}...), expires in ${TTL}s"
  return 0
}

main() {
  local sub="${1-}"; shift 2>/dev/null || true
  case "$sub" in
    hash)  cmd_hash "${1-}" "${2-}" ;;
    check) cmd_check "${1-}" "${2-}" ;;
    mint)  cmd_mint "${1-}" ;;
    *) echo "usage: capability-token.sh {hash|check|mint} ..." >&2; return 2 ;;
  esac
}

main "$@"
