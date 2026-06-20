#!/usr/bin/env bash
# test-capability-signer.sh - automated tests for the Secure-Enclave signer.
#
# The Touch-ID-gated production signing path is not automatable; it is covered by
# the standalone SE probe and a manual install check. What IS automated here:
#   1. capability-signer.swift compiles with swiftc.
#   2. `selftest` (ephemeral SE key, no Touch ID) produces a signature that
#      verifies under openssl with the exported SPKI PEM public key. This proves
#      the exact encoding capability-token.sh's check relies on.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$(cd "$HERE/.." && pwd)"
SWIFT="$SCRIPTS/capability-signer.swift"
OSSL=/usr/bin/openssl

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail=0
ok()  { printf 'ok   - %s\n' "$1"; }
bad() { printf 'FAIL - %s\n' "$1"; fail=1; }

# 1. compile
if swiftc "$SWIFT" -o "$TMP/capability-signer" 2>"$TMP/build.log"; then
  ok "swiftc compiles capability-signer.swift"
else
  bad "compile failed: $(tail -3 "$TMP/build.log")"
  echo "TESTS FAILED"; exit 1
fi

# 2. selftest -> openssl verify (SE sign + SPKI export + DER encoding compat)
if out="$("$TMP/capability-signer" selftest 2>"$TMP/st.err")"; then
  awk '/-----BEGIN/{p=1} p{print} /-----END/{p=0}' <<<"$out" > "$TMP/pub.pem"
  sig="$(awk 'f{print} /^---SIG---$/{f=1}' <<<"$out" | tail -1)"
  printf 'capability-signer-selftest' > "$TMP/msg"
  printf '%s' "$sig" | "$OSSL" base64 -d -A > "$TMP/sig.der" 2>/dev/null
  if [ -s "$TMP/pub.pem" ] && [ -s "$TMP/sig.der" ] \
     && "$OSSL" dgst -sha256 -verify "$TMP/pub.pem" -signature "$TMP/sig.der" "$TMP/msg" >/dev/null 2>&1; then
    ok "Secure-Enclave signature verifies under openssl (SPKI + DER compat)"
  else
    bad "SE signature did not verify under openssl"
  fi
else
  bad "selftest failed: $(tail -3 "$TMP/st.err")"
fi

if [ "$fail" -ne 0 ]; then echo "TESTS FAILED"; exit 1; fi
echo "ALL TESTS PASSED"
