#!/usr/bin/env bash
# test-capability-token-sig.sh - adversarial tests for the SIGNED token model.
#
# Uses a software P-256 signer (no Touch ID) that produces the same DER
# ECDSA-SHA256 signatures the Secure Enclave helper produces, so check's verify
# path is exercised exactly as in production. Every assertion is built to go RED
# on a broken impl: forgery is proven by a touched/garbage token being denied,
# no-downgrade by a missing pubkey denying, expiry by a validly-signed-but-old
# token denying.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/../capability-token.sh"
OSSL=/usr/bin/openssl

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export CAPABILITY_TOKEN_TEST=1
export CAPABILITY_TOKEN_DIR="$TMP/approvals"
export CAPABILITY_TOKEN_LOG="$TMP/audit.log"
export CAPABILITY_TOKEN_TTL=300

# Trusted keypair + a separate attacker keypair.
"$OSSL" ecparam -name prime256v1 -genkey -noout -out "$TMP/priv.pem" 2>/dev/null
"$OSSL" ec -in "$TMP/priv.pem" -pubout -out "$TMP/pub.pem" 2>/dev/null
"$OSSL" ecparam -name prime256v1 -genkey -noout -out "$TMP/evil.pem" 2>/dev/null
"$OSSL" ec -in "$TMP/evil.pem" -pubout -out "$TMP/evilpub.pem" 2>/dev/null

printf '#!/usr/bin/env bash\n%s dgst -sha256 -sign "%s" | %s base64 -A\n' "$OSSL" "$TMP/priv.pem" "$OSSL" > "$TMP/signer.sh"
printf '#!/usr/bin/env bash\n%s dgst -sha256 -sign "%s" | %s base64 -A\n' "$OSSL" "$TMP/evil.pem" "$OSSL" > "$TMP/evilsigner.sh"
chmod +x "$TMP/signer.sh" "$TMP/evilsigner.sh"
export CAPABILITY_SIGNER="$TMP/signer.sh"
export CAPABILITY_PUBKEY="$TMP/pub.pem"
mkdir -p "$CAPABILITY_TOKEN_DIR"

fail=0
ok()  { printf 'ok   - %s\n' "$1"; }
bad() { printf 'FAIL - %s\n' "$1"; fail=1; }
sign_payload() { printf 'capability-token.v1\n%s\n%s' "$1" "$2" | "$OSSL" dgst -sha256 -sign "$TMP/priv.pem" | "$OSSL" base64 -A; }

CMD='rm -rf /tmp/x'; CWD='/p'
H="$(bash "$LIB" hash "$CMD" "$CWD")"

# 1. valid signed token -> allow exactly once.
bash "$LIB" mint "$H" >/dev/null
if bash "$LIB" check "$CMD" "$CWD"; then ok "valid signed token allows once"; else bad "valid signed token should allow"; fi
# 2. replay -> deny (consumed).
if bash "$LIB" check "$CMD" "$CWD"; then bad "replay must deny"; else ok "replay denied (consumed)"; fi

# 3. forged unsigned token (founder never minted) -> deny.
hf="$(bash "$LIB" hash 'forge-cmd' "$CWD")"
printf '%s\n' "$(( $(date +%s) + 300 ))" > "$CAPABILITY_TOKEN_DIR/$hf.token"   # 1-line, no sig
if bash "$LIB" check 'forge-cmd' "$CWD"; then bad "unsigned forged token must deny"; else ok "unsigned forged token denied"; fi

# 4. garbage-signature token -> deny.
hg="$(bash "$LIB" hash 'garbage-cmd' "$CWD")"
printf '%s\nZ m9vYmFy\n' "$(( $(date +%s) + 300 ))" > "$CAPABILITY_TOKEN_DIR/$hg.token"
if bash "$LIB" check 'garbage-cmd' "$CWD"; then bad "garbage signature must deny"; else ok "garbage signature denied"; fi

# 5. wrong-key signature (signed by attacker key) -> deny against trusted pubkey.
hw="$(bash "$LIB" hash 'wrong-cmd' "$CWD")"
CAPABILITY_SIGNER="$TMP/evilsigner.sh" bash "$LIB" mint "$hw" >/dev/null
if bash "$LIB" check 'wrong-cmd' "$CWD"; then bad "attacker-key token must deny"; else ok "attacker-key signature denied"; fi

# 6. swapped trusted pubkey -> a good signature no longer verifies.
hs="$(bash "$LIB" hash 'swap-cmd' "$CWD")"
bash "$LIB" mint "$hs" >/dev/null
if CAPABILITY_PUBKEY="$TMP/evilpub.pem" bash "$LIB" check 'swap-cmd' "$CWD"; then bad "swapped pubkey must deny"; else ok "swapped pubkey denied"; fi

# 7. missing trusted pubkey -> deny (NO downgrade).
hm="$(bash "$LIB" hash 'nopub-cmd' "$CWD")"
bash "$LIB" mint "$hm" >/dev/null
if CAPABILITY_PUBKEY="$TMP/does-not-exist.pem" bash "$LIB" check 'nopub-cmd' "$CWD"; then bad "missing pubkey must deny (no downgrade)"; else ok "missing pubkey denied (no downgrade)"; fi

# 8. validly-signed but EXPIRED token -> deny.
he="$(bash "$LIB" hash 'exp-cmd' "$CWD")"
past=$(( $(date +%s) - 10 ))
{ printf '%s\n' "$past"; sign_payload "$he" "$past"; printf '\n'; } > "$CAPABILITY_TOKEN_DIR/$he.token"
if bash "$LIB" check 'exp-cmd' "$CWD"; then bad "expired signed token must deny"; else ok "expired (valid sig) token denied"; fi

# 9. malformed expiry -> deny.
hx="$(bash "$LIB" hash 'malformed-cmd' "$CWD")"
printf 'not-a-number\nsig\n' > "$CAPABILITY_TOKEN_DIR/$hx.token"
if bash "$LIB" check 'malformed-cmd' "$CWD"; then bad "malformed token must deny"; else ok "malformed token denied"; fi

if [ "$fail" -ne 0 ]; then echo "TESTS FAILED"; exit 1; fi
echo "ALL TESTS PASSED"
