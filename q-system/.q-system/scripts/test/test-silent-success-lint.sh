#!/usr/bin/env bash
# Paired test for silent-success-lint.py (ASK-213).
#
# FIXTURES COME FROM PRODUCERS, NOT FROM ME. The three positive fixtures are the
# real files at the commit where each defect was LIVE, extracted with `git show`
# and vendored under test/fixtures/silent-success/. Case 0 re-derives them from
# the pinned SHAs and refuses on any drift, so a fixture cannot be quietly
# edited until it agrees with the lint. Vendored rather than fetched at run time
# because a shallow CI clone would not have the objects, and "a gate that cannot
# run must not pass" -- a skip here would be the exact defect under test.
#
# The two negatives that matter are also real code, not inventions: the same
# pr-verdict-lib function one commit later (where the permissive branch is
# DELIBERATE and pinned by name in test-severity-floor.sh), and converge.sh's
# release_stale_claim_for_issue (best-effort cleanup whose value IS checked).
# Only the python fixtures and the plain no-op are constructed, and they are
# labelled as such.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
LINT="$ROOT/q-system/.q-system/scripts/silent-success-lint.py"
FIX="$HERE/fixtures/silent-success"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0

ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

# run <file> -> writes findings to $OUT, sets $RC. Never aborts the suite: the
# lint exits 1 by contract on findings and `set -e` would eat the assertion.
OUT=""
RC=0
run() {
  OUT="$(python3 "$LINT" --root "$ROOT" "$1" 2>&1)" && RC=0 || RC=$?
}

# expects a finding CODE anchored at LINE
flags() {
  local file="$1" code="$2" line="$3" name="$4"
  run "$file"
  if printf '%s' "$OUT" | grep -qE ":$line: $code\b"; then
    ok "$name"
  else
    bad "$name" "expected $code at line $line; got: $(printf '%s' "$OUT" | head -3 | tr '\n' ' ')"
  fi
}

# expects NO finding of CODE anywhere in the file
quiet_for() {
  local file="$1" code="$2" name="$3"
  run "$file"
  if printf '%s' "$OUT" | grep -qE ": $code\b"; then
    bad "$name" "$code fired: $(printf '%s' "$OUT" | grep -E ": $code\b" | head -2 | tr '\n' ' ')"
  else
    ok "$name"
  fi
}

echo "test-silent-success-lint"

# --- case 0: provenance -- every vendored fixture IS its producing commit -----
echo "[0] fixture provenance"
check_provenance() {
  local sha="$1" path="$2" fixture="$3"
  if ! git -C "$ROOT" cat-file -e "$sha" 2>/dev/null; then
    bad "provenance $fixture" "commit $sha not in this clone -- fixture unverifiable"
    return
  fi
  if git -C "$ROOT" show "$sha:$path" 2>/dev/null | diff -q - "$FIX/$fixture" >/dev/null; then
    ok "provenance $fixture == $sha:$path"
  else
    bad "provenance $fixture" "drifted from $sha:$path"
  fi
}
check_provenance '5600ebab^' q-system/.q-system/scripts/linear-worker.sh   RED-fetch-guard.linear-worker.sh
check_provenance 'fa74b1d2^' q-system/.q-system/scripts/linear-worker.sh   RED-reset-rounds.linear-worker.sh
check_provenance '4b4dd3e'   q-system/.q-system/scripts/pr-verdict-lib.sh  RED-empty-approve.pr-verdict-lib.sh
check_provenance '5495a9b'   q-system/.q-system/scripts/pr-verdict-lib.sh  GREEN-declared-approve.pr-verdict-lib.sh

# --- case 1-3: the three known defects, each at its real line ----------------
echo "[1] the known defects are found"
# 5600ebab^ : `if ! git fetch ...; then say ...; exit 0` -- ASK-208 PR #22 r3 f1
flags "$FIX/RED-fetch-guard.linear-worker.sh"  SS001 248 "fetch guard exits 0 (line 248)"
# fa74b1d2^ : `python3 -c ... >/dev/null 2>&1 || true` then an unconditional say
flags "$FIX/RED-reset-rounds.linear-worker.sh" SS002 141 "reset-rounds reports an unread write (line 141)"
# 4b4dd3e   : `else printf 'APPROVE'` at the foot of the severity ladder
flags "$FIX/RED-empty-approve.pr-verdict-lib.sh" SS003 136 "empty findings block releases the PR (line 136)"

# --- case 4-5: the legitimate instances of the SAME shapes stay quiet --------
echo "[2] the deliberate instances are not flagged"
quiet_for "$FIX/GREEN-declared-approve.pr-verdict-lib.sh" SS003 \
  "5495a9b: the same else, explained, is quiet"
quiet_for "$FIX/GREEN-checked-swallow.converge.sh" SS002 \
  "converge.sh release_stale_claim: || true whose value is checked"

# --- case 6: a plain no-op exit 0 (constructed) ------------------------------
echo "[3] constructed negatives"
cat > "$TMP/noop.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
# Nothing queued is not a failure: no work is a legitimate outcome here.
if [ ! -s "$QUEUE" ]; then
  echo "nothing queued"
  exit 0
fi
# Best-effort cleanup. A missing scratch dir must not fail the run.
rm -rf "$SCRATCH" 2>/dev/null || true
process "$QUEUE"
EOF
quiet_for "$TMP/noop.sh" SS001 "an emptiness test that exits 0 is not a failure guard"
quiet_for "$TMP/noop.sh" SS002 "cleanup || true with no success report is quiet"

# --- case 7: the mutation -- the discriminator can actually fail -------------
# Strip the explaining comment from 5495a9b's else and it MUST go red. Without
# this the negative above proves nothing: a lint that never fires on that file
# for any reason would pass case 4 too.
echo "[4] mutation: the explanation is what makes it quiet"
python3 - "$FIX/GREEN-declared-approve.pr-verdict-lib.sh" "$TMP/mutant.sh" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
lines = open(src, encoding="utf-8").read().splitlines(True)
# lines 148-152 (1-indexed) are the DELIBERATE-contract comment above the else
del lines[147:152]
open(dst, "w", encoding="utf-8").writelines(lines)
PY
flags "$TMP/mutant.sh" SS003 148 "un-commented, the same else is flagged again"

# --- case 8: the suppression marker ------------------------------------------
echo "[5] suppression"
cat > "$TMP/declared.sh" <<'EOF'
#!/usr/bin/env bash
if ! probe_upstream; then
  # silent-success-ok: the probe is advisory; the real gate runs downstream
  exit 0
fi
EOF
quiet_for "$TMP/declared.sh" SS001 "an explicit silent-success-ok marker clears SS001"

# --- case 9: python detectors (constructed) ----------------------------------
echo "[6] python shapes"
cat > "$TMP/py_red.py" <<'EOF'
import json, sys

def a(p):
    try:
        return json.load(open(p))
    except Exception:
        pass

def b(p):
    try:
        d = json.load(open(p))
    except Exception:
        d = {}
    return d

def c(p):
    try:
        return json.load(open(p))
    except Exception:
        sys.exit(0)
EOF
flags "$TMP/py_red.py" SS101 6  "SS101 except: pass"
flags "$TMP/py_red.py" SS102 12 "SS102 handler rebuilds state from {}"
flags "$TMP/py_red.py" SS103 20 "SS103 error handler exits 0"

cat > "$TMP/py_green.py" <<'EOF'
import json, logging, sys

def a(p):
    try:
        return json.load(open(p))
    except Exception as exc:
        logging.error("unreadable %s: %s", p, exc)
        raise

def b(p):
    try:
        return json.load(open(p))
    except FileNotFoundError:
        sys.stderr.write("missing %s\n" % p)
        sys.exit(3)

def c(p):
    try:
        return json.load(open(p))
    except Exception:
        # silent-success-ok: an absent cache is the cold-start case, not a failure
        return {}
EOF
quiet_for "$TMP/py_green.py" SS101 "a loud handler is not SS101"
quiet_for "$TMP/py_green.py" SS102 "a declared empty default is not SS102"
quiet_for "$TMP/py_green.py" SS103 "an error branch exiting non-zero is not SS103"

# --- case 10: exit-code contract ---------------------------------------------
echo "[7] exit codes"
run "$FIX/RED-fetch-guard.linear-worker.sh"
[ "$RC" -eq 1 ] && ok "findings -> exit 1" || bad "findings -> exit 1" "got rc=$RC"
run "$TMP/py_green.py"
[ "$RC" -eq 0 ] && ok "clean -> exit 0" || bad "clean -> exit 0" "got rc=$RC"
python3 "$LINT" --root "$ROOT" --report "$FIX/RED-fetch-guard.linear-worker.sh" >/dev/null \
  && ok "--report -> exit 0 even with findings" \
  || bad "--report -> exit 0 even with findings" "non-zero rc"

# --- case 11: fixtures are excluded from the repo-wide scan ------------------
# Otherwise arming the gate would permanently flag this test's own inputs.
echo "[8] scan scope"
if python3 "$LINT" --root "$ROOT" --report 2>/dev/null | grep -q 'fixtures/silent-success'; then
  bad "repo-wide scan skips fixtures" "the fixture dir was scanned"
else
  ok "repo-wide scan skips fixtures"
fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS test-silent-success-lint"
