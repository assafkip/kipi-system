#!/usr/bin/env bash
# test-capability-token.sh - adversarial tests for capability-token.sh.
#
# Every assertion is written so a broken implementation goes RED:
#  - consume is proven by a SECOND check failing (if delete were skipped, green)
#  - expiry is proven by an expired token being rejected (if ignored, green)
#  - atomicity is proven by exactly ONE of two racing consumers winning
#  - hash binding is proven by newline-shifted command/cwd pairs differing
#  - trust-root gating is proven by the env override being ignored without the flag
# This is the fable-discipline rule: a check you have never seen fail is not a
# check. These have been seen to fail against deliberately broken inputs.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/../capability-token.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# CAPABILITY_TOKEN_TEST=1 is required to honor the dir/log/ttl overrides; the
# production hook never sets it, so the trust root is fixed in production.
export CAPABILITY_TOKEN_TEST=1
export CAPABILITY_TOKEN_DIR="$TMP/approvals"
export CAPABILITY_TOKEN_LOG="$TMP/audit.log"
export CAPABILITY_TOKEN_TTL=300
# Phase 2: provision a software P-256 signer + trusted pubkey so signed
# mint/check work without Touch ID. (signing is now required; no downgrade)
OSSL=/usr/bin/openssl
"$OSSL" ecparam -name prime256v1 -genkey -noout -out "$TMP/priv.pem" 2>/dev/null
"$OSSL" ec -in "$TMP/priv.pem" -pubout -out "$TMP/pub.pem" 2>/dev/null
printf '#!/usr/bin/env bash\n%s dgst -sha256 -sign "%s" | %s base64 -A\n' "$OSSL" "$TMP/priv.pem" "$OSSL" > "$TMP/signer.sh"
chmod +x "$TMP/signer.sh"
export CAPABILITY_SIGNER="$TMP/signer.sh"
export CAPABILITY_PUBKEY="$TMP/pub.pem"
mkdir -p "$CAPABILITY_TOKEN_DIR"

fail=0
ok()  { printf 'ok   - %s\n' "$1"; }
bad() { printf 'FAIL - %s\n' "$1"; fail=1; }

CMD='rm -rf /tmp/whatever'
CWD='/Users/x/project'

# 1. No token -> deny (the default posture).
if bash "$LIB" check "$CMD" "$CWD"; then bad "check with no token must deny"; else ok "no token denies"; fi

# 2. hash deterministic, 64 hex, binds both command and cwd.
h1="$(bash "$LIB" hash "$CMD" "$CWD")"
h2="$(bash "$LIB" hash "$CMD" "$CWD")"
if [ "$h1" = "$h2" ] && [ "${#h1}" -eq 64 ]; then ok "hash deterministic, 64 hex"; else bad "hash not deterministic/64-hex ($h1)"; fi
h3="$(bash "$LIB" hash "$CMD x" "$CWD")"
h4="$(bash "$LIB" hash "$CMD" "$CWD/other")"
if [ "$h1" != "$h3" ] && [ "$h1" != "$h4" ]; then ok "hash differs on any command or cwd change"; else bad "hash collided on a change"; fi

# 3. mint -> allow exactly once; second check denies (proves consume).
bash "$LIB" mint "$h1" >/dev/null
if bash "$LIB" check "$CMD" "$CWD"; then ok "minted token allows once"; else bad "minted token should allow"; fi
if bash "$LIB" check "$CMD" "$CWD"; then bad "second check must deny (consumed)"; else ok "token consumed, second denies"; fi

# 4. expired token denied (proves expiry is enforced).
hx="$(bash "$LIB" hash 'expired-cmd' "$CWD")"
mkdir -p "$CAPABILITY_TOKEN_DIR"
printf '%s' "$(( $(date +%s) - 10 ))" > "$CAPABILITY_TOKEN_DIR/$hx.token"
if bash "$LIB" check 'expired-cmd' "$CWD"; then bad "expired token must deny"; else ok "expired token denies"; fi

# 5. malformed expiry denied (fail closed on garbage).
hm="$(bash "$LIB" hash 'malformed-cmd' "$CWD")"
printf 'not-a-number' > "$CAPABILITY_TOKEN_DIR/$hm.token"
if bash "$LIB" check 'malformed-cmd' "$CWD"; then bad "malformed token must deny"; else ok "malformed token denies"; fi

# 6. atomic consume: two racing checks on one grant, exactly one wins.
hr="$(bash "$LIB" hash 'race-cmd' "$CWD")"
bash "$LIB" mint "$hr" >/dev/null
bash "$LIB" check 'race-cmd' "$CWD" & p1=$!
bash "$LIB" check 'race-cmd' "$CWD" & p2=$!
wait "$p1"; r1=$?
wait "$p2"; r2=$?
wins=0
[ "$r1" -eq 0 ] && wins=$((wins+1))
[ "$r2" -eq 0 ] && wins=$((wins+1))
if [ "$wins" -eq 1 ]; then ok "atomic consume: exactly one racer wins"; else bad "atomic consume broken: $wins winners"; fi

# 7. invalid mint input rejected (no token written, non-zero exit).
if bash "$LIB" mint "not-a-hash" 2>/dev/null; then bad "mint must reject a non-hex hash"; else ok "mint rejects invalid hash"; fi

# 8. audit log recorded a grant and a consume (JSON lines).
grants=$(grep -c '"event":"grant"' "$CAPABILITY_TOKEN_LOG" 2>/dev/null || true); grants=${grants:-0}
consumes=$(grep -c '"event":"consume"' "$CAPABILITY_TOKEN_LOG" 2>/dev/null || true); consumes=${consumes:-0}
if [ "$grants" -ge 1 ] && [ "$consumes" -ge 1 ]; then ok "audit log records grant and consume"; else bad "audit log missing events (grant=$grants consume=$consumes)"; fi

# 9. hash is unambiguous across newline-shifted command/cwd pairs (finding-2).
ha="$(bash "$LIB" hash 'a' "$(printf 'b\nc')")"
hb="$(bash "$LIB" hash "$(printf 'a\nb')" 'c')"
if [ "$ha" != "$hb" ]; then ok "hash unambiguous across newline-shifted pairs"; else bad "hash ambiguous: ('a','b\\nc') collides with ('a\\nb','c')"; fi

# 10. env override is IGNORED without the test flag (production trust root fixed; finding-1).
hg="$(bash "$LIB" hash 'gate-cmd' "$CWD")"
bash "$LIB" mint "$hg" >/dev/null   # token written into the temp override dir
if env -u CAPABILITY_TOKEN_TEST bash "$LIB" check 'gate-cmd' "$CWD"; then
  bad "override honored without test flag (trust root not fixed)"
else
  ok "env override ignored without test flag (fixed trust root)"
fi

if [ "$fail" -ne 0 ]; then echo "TESTS FAILED"; exit 1; fi
echo "ALL TESTS PASSED"
