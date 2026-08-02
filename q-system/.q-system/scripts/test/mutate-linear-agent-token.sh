#!/usr/bin/env bash
# Mutation harness for linear-agent-token.py. Proves the token suite can FAIL.
#
# Refuses to run a mutant that is byte-identical to the original -- a non-applying
# sed is a false green that reads as proof, which this harness's sibling learned by
# "passing" 11/11 on an unmodified file.
#
# Each mutant destroys ONE guarantee. Any mutant that stays GREEN names a guarantee
# nothing actually checks.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$DIR/../linear-agent-token.py"
SUITE="$DIR/test-linear-agent-token.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

run_mutant() {
  local name="$1" expr="$2" guarantee="$3"
  local mutant="$WORK/$name.py"

  sed "$expr" "$SRC" > "$mutant"

  if cmp -s "$SRC" "$mutant"; then
    echo "[BROKEN] $name: mutation did not apply -- pattern matched nothing."
    return 2
  fi

  local out rc
  out="$(KIPI_NOTIFY=/usr/bin/true KIPI_TOKEN_MODULE_UNDER_TEST="$mutant" \
         python3 "$SUITE" 2>&1)"
  rc=$?

  if [ $rc -ne 0 ]; then
    echo "[CAUGHT] $name -- suite went RED as it must ($guarantee)"
    echo "$out" | grep '^\[FAIL\]' | sed 's/^/           /'
    return 0
  fi
  echo "[ESCAPED] $name -- suite stayed GREEN. NOTHING CHECKS: $guarantee"
  return 1
}

echo "=== mutation testing linear-agent-token.py ==="
fails=0

# The rotation hazard: refresh works, persistence does not. In production this
# succeeds exactly ONCE and then locks us out of the workspace permanently.
run_mutant "rotation-not-persisted" \
  's/^    new = _normalize(resp, tokens)$/    new = _normalize(resp, tokens); return new/' \
  "the rotated refresh token must land on disk" || fails=$((fails+1))

run_mutant "refresh-every-call" \
  's/^    if tokens.get("expires_at", 0) - now > REFRESH_SKEW_SECONDS:$/    if False:/' \
  "a healthy token must not burn a rotation" || fails=$((fails+1))

run_mutant "silent-on-missing-token" \
  '/^    except ReauthRequired as exc:$/,/^        raise$/s/^        page(f"Linear agent: {exc}. Sana is OFFLINE -- delegations will sit unanswered "$/        _q = (f"/' \
  "a missing token file must PAGE, not fail quietly" || fails=$((fails+1))

run_mutant "silent-on-dead-refresh" \
  's/^        page(f"Linear agent: token refresh REJECTED ({exc}). Sana is offline until you "$/        _q = (f"/' \
  "a rejected refresh must PAGE the founder" || fails=$((fails+1))

run_mutant "reauth-treated-as-retryable" \
  's/^        if exc.code in (400, 401):$/        if False:/' \
  "a dead refresh token must be reported as reauth, not a generic error" || fails=$((fails+1))

run_mutant "clobber-on-rejected-refresh" \
  's/^    rt = tokens.get("refresh_token")$/    rt = tokens.get("refresh_token"); save({"access_token": "x", "refresh_token": "CLOBBERED"})/' \
  "a failed refresh must not destroy the stored credential" || fails=$((fails+1))

echo "==============================================="
if [ $fails -eq 0 ]; then
  echo "all mutants caught -- the token suite has teeth"
else
  echo "$fails mutant(s) escaped or broken -- see above"
fi
exit $fails
