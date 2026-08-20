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
#
# TWO checks, and only one of them can depend on the clone.
#
# Three of the four producing commits (5600ebab, fa74b1d2, 5495a9b) are NOT
# ancestors of origin/main -- they live only on the unmerged branches sana/ask-208
# and sana/ask-312. `git cat-file -e` against them therefore succeeds today and
# stops succeeding the moment those branches are deleted on merge, which is the
# normal end of a branch's life. The first version of this case called bad() on
# an absent object, so a routine branch cleanup would have turned this required
# test permanently red with nothing actually wrong (PR #230 review, major).
#
# So the ANTI-DRIFT gate -- the thing this case exists for, "a fixture cannot be
# quietly edited until it agrees with the lint" -- is the sha256 pin below. It
# needs no git history at all, so it runs identically in a shallow clone, a fork
# or a tarball, and it can never be unavailable. Case 4b mutates a fixture and
# requires it to go red, so this is a check that can fail.
#
# Re-deriving from the commit is a STRICTLY ADDITIONAL confirmation (it also
# catches a fixture edited together with its pin). It runs when the object is
# present and is REPORTED, never silently dropped, when it is not: an absent
# object leaves the anti-drift gate fully intact, so it is not "a gate that could
# not run passing" -- it is one confirmation of two being unavailable, said out
# loud and counted in the summary.
echo "[0] fixture provenance"
NOTE=0
note() { NOTE=$((NOTE+1)); printf '  note %s\n' "$1"; }

# sha256 of the vendored bytes, pinned at authoring time against the commits below.
pin_RED_fetch_guard=4f52ae07b069ce340de3be8e423fbfe0599674810d7f8f4752a29d2675daa141
pin_RED_reset_rounds=4506697d832b4eaa57a0b7d65c363e30926b07c8a1ddc12281c83720e70d0136
pin_RED_empty_approve=886952b2207cd5088e14df1074a96f69c4fa1f81f940ddc7f637923721c5e046
pin_GREEN_declared_approve=4cd387412f183775f133de06ec76cb881f22cfe2c14f8b86754ae0f88b008cd0
pin_GREEN_checked_swallow=81a1efe4c6530aff1f7d8656ce53cb05b86757d35d45133d635386b60d229b62

sha256_of() { python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$1"; }

# check_pin <fixture> <expected-sha256>  -- always runs, no git required
check_pin() {
  local fixture="$1" want="$2" got
  if [ ! -f "$FIX/$fixture" ]; then
    bad "pin $fixture" "vendored fixture is missing"
    return
  fi
  got="$(sha256_of "$FIX/$fixture")"
  if [ "$got" = "$want" ]; then
    ok "pin $fixture sha256 matches"
  else
    bad "pin $fixture" "content drifted: want $want got $got"
  fi
}

# check_provenance <sha> <path-at-that-sha> <fixture> -- extra, when available
check_provenance() {
  local sha="$1" path="$2" fixture="$3"
  if ! git -C "$ROOT" cat-file -e "$sha" 2>/dev/null; then
    note "provenance $fixture: $sha not in this clone (branch merged/pruned); sha256 pin carried it"
    return
  fi
  if git -C "$ROOT" show "$sha:$path" 2>/dev/null | diff -q - "$FIX/$fixture" >/dev/null; then
    ok "provenance $fixture == $sha:$path"
  else
    bad "provenance $fixture" "drifted from $sha:$path"
  fi
}

check_pin RED-fetch-guard.linear-worker.sh        "$pin_RED_fetch_guard"
check_pin RED-reset-rounds.linear-worker.sh       "$pin_RED_reset_rounds"
check_pin RED-empty-approve.pr-verdict-lib.sh     "$pin_RED_empty_approve"
check_pin GREEN-declared-approve.pr-verdict-lib.sh "$pin_GREEN_declared_approve"
check_pin GREEN-checked-swallow.converge.sh       "$pin_GREEN_checked_swallow"

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

# --- case 7b: the sha256 pin is itself a check that can fail ------------------
# Without this, "pin matches" proves only that two strings were compared. Edit a
# fixture's bytes and check_pin MUST call bad(). Run against a copy so the real
# fixture is never touched.
echo "[4b] mutation: the sha256 pin catches an edited fixture"
FIX_REAL="$FIX"
mkdir -p "$TMP/fixdrift"
cp "$FIX/RED-fetch-guard.linear-worker.sh" "$TMP/fixdrift/"
printf '\n# a quiet edit to make the lint agree\n' >> "$TMP/fixdrift/RED-fetch-guard.linear-worker.sh"
PIN_PASS_BEFORE=$PASS PIN_FAIL_BEFORE=$FAIL
# Redirected, not sub-shelled: the deliberate bad() must not print as a real
# failure, but its PASS/FAIL side effect has to survive for the delta below.
FIX="$TMP/fixdrift"
check_pin RED-fetch-guard.linear-worker.sh "$pin_RED_fetch_guard" > "$TMP/mut-pin.log" 2>&1
FIX="$FIX_REAL"
if [ "$FAIL" -gt "$PIN_FAIL_BEFORE" ]; then
  FAIL=$PIN_FAIL_BEFORE; ok "an edited fixture fails the sha256 pin"
else
  PASS=$PIN_PASS_BEFORE; bad "an edited fixture fails the sha256 pin" "pin stayed green on drifted bytes"
fi

# --- case 7c: an absent producing commit is a note, never a failure ----------
# Simulates the branch-deletion case directly: a well-formed sha that is not in
# this clone must NOT turn the suite red, because the sha256 pin above already
# holds the anti-drift line. This is the finding from PR #230 review (major).
echo "[4c] a pruned producing commit does not break the suite"
NOTE_BEFORE=$NOTE FAIL_BEFORE=$FAIL
check_provenance '0000000000000000000000000000000000000000' some/path RED-fetch-guard.linear-worker.sh
if [ "$FAIL" -eq "$FAIL_BEFORE" ] && [ "$NOTE" -gt "$NOTE_BEFORE" ]; then
  ok "an unavailable commit reports a note and keeps the suite green"
else
  bad "an unavailable commit reports a note and keeps the suite green" \
      "fail delta=$((FAIL-FAIL_BEFORE)) note delta=$((NOTE-NOTE_BEFORE))"
fi

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

# --- case 6b: the three round-4 review findings, each observed RED first ------
#
# Constructed, and labelled as such: these are shapes the detectors MISSED, so
# no producing commit in this repo carries them as a live defect to extract.
# Each was run against the pre-fix lint and came back unflagged before the fix
# landed, and the two negatives below are what keep the fix from over-firing.
echo "[6b] round-4 findings"

cat > "$TMP/r4_empty_return.py" <<'EOF'
def load(path):
    try:
        return json.load(open(path))
    except Exception:
        return {}
EOF
# anchored on the `except` line, same as the empty-assign form: SS102 is a
# statement about the handler, not about the one line inside it.
flags "$TMP/r4_empty_return.py" SS102 4 \
  "an empty RETURN out of a handler is SS102, not only an empty assign"

cat > "$TMP/r4_none_return.py" <<'EOF'
def find(path):
    try:
        return index[path]
    except KeyError:
        return None
EOF
quiet_for "$TMP/r4_none_return.py" SS102 \
  "a None sentinel is distinguishable, so it is not SS102"

cat > "$TMP/r4_comment_notify.sh" <<'EOF'
if ! git fetch origin; then
    # nothing here will notify anyone, which is the bug
    echo "no upstream"
    exit 0
fi
EOF
flags "$TMP/r4_comment_notify.sh" SS001 4 \
  "a comment saying notify does not vouch for the branch"

cat > "$TMP/r4_catalog_exit.py" <<'EOF'
def run():
    try:
        work()
    except Exception:
        catalog()
        sys.exit(0)
EOF
flags "$TMP/r4_catalog_exit.py" SS103 6 \
  "catalog() does not certify a handler as loud"

cat > "$TMP/r4_logger_exit.py" <<'EOF'
def run():
    try:
        work()
    except Exception:
        logger.warning("failed")
        sys.exit(0)
EOF
quiet_for "$TMP/r4_logger_exit.py" SS103 \
  "logger.warning still certifies a handler as loud"

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

# --- case 12: the lint does not commit its own defect on a named path --------
# A path the caller NAMED that could not be opened used to return [] -- printed
# "0 finding(s)", rc=0, a clean bill of health for a file nothing ever read. That
# is SS002 in the scanner itself (PR #230 review, minor). rc=2, not 1, so a
# broken invocation is distinguishable from a real result.
echo "[9] an unreadable requested path is not a clean scan"
# `&& RC=0 || RC=$?` throughout: these calls exit non-zero by contract and a bare
# `; RC=$?` would let `set -e` abort the suite before the assertion runs.
python3 "$LINT" --root "$ROOT" "$TMP/definitely-not-here.sh" >/dev/null 2>"$TMP/unread.err" \
  && RC=0 || RC=$?
if [ "$RC" -eq 2 ] && grep -q 'NOT a clean scan' "$TMP/unread.err"; then
  ok "a missing named path exits 2 and says so"
else
  bad "a missing named path exits 2 and says so" "rc=$RC err=$(tr '\n' ' ' < "$TMP/unread.err")"
fi
# A directory is unreadable in the same way and must not read as clean either.
mkdir -p "$TMP/adir.sh"
python3 "$LINT" --root "$ROOT" "$TMP/adir.sh" >/dev/null 2>&1 && RC=0 || RC=$?
[ "$RC" -eq 2 ] && ok "a directory argument exits 2" || bad "a directory argument exits 2" "rc=$RC"
# And the sweep still tolerates what it legitimately cannot open.
python3 "$LINT" --root "$ROOT" --report >/dev/null 2>&1 && RC=0 || RC=$?
[ "$RC" -eq 0 ] && ok "the repo-wide sweep is unaffected" || bad "the repo-wide sweep is unaffected" "rc=$RC"

# --- case 13: the ratchet -- this is what makes the repo-wide result ENFORCED -
#
# Everything above this line tests the DETECTOR against fixtures. None of it can
# fail because of the repository. Measured, not assumed: a brand-new SS001 added
# to a tracked file moved the sweep 173 -> 174 and this suite still reported
# "33 passed, 0 failed", exit 0 -- 173 findings that nothing could fail on
# (PR #230 review round 3, major).
#
# Demanding zero is not on the table (the DoR arms CI "only if the baseline is
# clean", and it is 173). So the enforcement is directional: BASELINE pins what
# each file already carries, and the check goes red when a file GAINS a finding.
# Because this test is a required capability, a new silent-success defect now
# fails a required check.
echo "[10] ratchet: a NEW finding fails the required check"
BASE="$ROOT/q-system/.q-system/scripts/silent-success-baseline.json"

# (a) the live repository against its committed baseline. THIS is the enforcing
# assertion; every other case in this block exists to prove it can fail.
python3 "$LINT" --root "$ROOT" --baseline "$BASE" >"$TMP/rat.out" 2>"$TMP/rat.err" \
  && RC=0 || RC=$?
if [ "$RC" -eq 0 ]; then
  ok "the repo holds its baseline"
else
  bad "the repo holds its baseline" "rc=$RC $(grep GAINED "$TMP/rat.out" | head -3 | tr '\n' ' ')"
fi

# (b) MUTATION. A throwaway git repo, because the ratchet reads `git ls-files`
# and the assertion has to be that a genuinely new defect turns it red -- not
# that a hand-edited JSON does. Pin, then add the real 2026-07-27 fetch-guard
# shape, and require rc=2.
REPO="$TMP/ratchet-repo"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" config user.email t@t; git -C "$REPO" config user.name t
printf '#!/usr/bin/env bash\necho hello\n' > "$REPO/ok.sh"
git -C "$REPO" add -A; git -C "$REPO" commit -qm base
python3 "$LINT" --root "$REPO" --baseline-write "$REPO/base.json" >/dev/null
python3 "$LINT" --root "$REPO" --baseline "$REPO/base.json" >/dev/null 2>&1 \
  && RC=0 || RC=$?
[ "$RC" -eq 0 ] && ok "a clean pinned repo holds" || bad "a clean pinned repo holds" "rc=$RC"

printf '#!/usr/bin/env bash\nif ! git fetch origin; then\n  exit 0\nfi\n' > "$REPO/new.sh"
git -C "$REPO" add -A
python3 "$LINT" --root "$REPO" --baseline "$REPO/base.json" >"$TMP/mut.out" 2>&1 \
  && RC=0 || RC=$?
if [ "$RC" -eq 2 ] && grep -q 'GAINED new.sh: SS001' "$TMP/mut.out"; then
  ok "a new SS001 in a tracked file exits 2 and names the file"
else
  bad "a new SS001 in a tracked file exits 2 and names the file" \
      "rc=$RC out=$(tr '\n' ' ' < "$TMP/mut.out" | head -c 200)"
fi

# (c) the declared escape hatch clears the ratchet in place, so the gate is
# satisfiable without editing the baseline. Otherwise every legitimate
# best-effort path forces a re-pin, and re-pinning becomes the reflex that
# turns the baseline back into decoration.
# The marker goes ON the guard or INSIDE its block, which is where SS001 reads
# it -- a line above the guard is outside the block and does not suppress.
printf '#!/usr/bin/env bash\nif ! git fetch origin; then\n  # silent-success-ok: probe only, the caller retries and reports\n  exit 0\nfi\n' > "$REPO/new.sh"
python3 "$LINT" --root "$REPO" --baseline "$REPO/base.json" >/dev/null 2>&1 \
  && RC=0 || RC=$?
[ "$RC" -eq 0 ] && ok "a declared finding clears the ratchet" \
                || bad "a declared finding clears the ratchet" "rc=$RC"

# (d) an unreadable baseline must be an error, never "nothing regressed" -- that
# would be this script committing SS002 against itself, the same defect the
# named-path fix already closed once.
python3 "$LINT" --root "$REPO" --baseline "$REPO/no-such-baseline.json" \
  >/dev/null 2>"$TMP/nb.err" && RC=0 || RC=$?
if [ "$RC" -eq 2 ] && grep -q 'cannot read baseline' "$TMP/nb.err"; then
  ok "an absent baseline exits 2, not 'held'"
else
  bad "an absent baseline exits 2, not 'held'" "rc=$RC"
fi

# (e) a path-scoped ratchet would read every unscanned file as fixed -- a
# releasing outcome from an absent input. Refused rather than narrowed.
python3 "$LINT" --root "$REPO" --baseline "$REPO/base.json" "$REPO/ok.sh" \
  >/dev/null 2>&1 && RC=0 || RC=$?
[ "$RC" -eq 2 ] && ok "--baseline refuses path arguments" \
                || bad "--baseline refuses path arguments" "rc=$RC"

# (f) THE MUTABLE-BASELINE HOLE. The ratchet reads the baseline from the working
# tree, which on a PR is the PR's OWN copy -- so a branch that adds a defect and
# raises its own allowance in the same commit clears the required check. The
# allowance and the thing it constrains travel together, which means the gate
# certifies itself (codex major, PR #230 r4, .github/workflows/validate.yml:74).
#
# --baseline-ref pins the allowance to the BASE commit, which the PR cannot edit.
REPO2="$TMP/selfcert-repo"
mkdir -p "$REPO2"
git -C "$REPO2" init -q -b main
git -C "$REPO2" config user.email t@t; git -C "$REPO2" config user.name t
printf '#!/usr/bin/env bash\necho hello\n' > "$REPO2/ok.sh"
git -C "$REPO2" add -A; git -C "$REPO2" commit -qm base
python3 "$LINT" --root "$REPO2" --baseline-write "$REPO2/base.json" >/dev/null
git -C "$REPO2" add -A; git -C "$REPO2" commit -qm pin
BASE_SHA="$(git -C "$REPO2" rev-parse HEAD)"

# the attacking branch: one new defect, plus a re-pin that allows it.
git -C "$REPO2" checkout -q -b pr
printf '#!/usr/bin/env bash\nif ! git fetch origin; then\n  exit 0\nfi\n' > "$REPO2/new.sh"
git -C "$REPO2" add -A
python3 "$LINT" --root "$REPO2" --baseline-write "$REPO2/base.json" >/dev/null
git -C "$REPO2" add -A; git -C "$REPO2" commit -qm "defect + raised allowance"

python3 "$LINT" --root "$REPO2" --baseline "$REPO2/base.json" >/dev/null 2>&1 \
  && RC=0 || RC=$?
[ "$RC" -eq 0 ] && ok "the working-tree baseline is self-certifying (the hole)" \
                || bad "the working-tree baseline is self-certifying (the hole)" "rc=$RC"

python3 "$LINT" --root "$REPO2" --baseline "$REPO2/base.json" \
  --baseline-ref "$BASE_SHA" >"$TMP/self.out" 2>&1 && RC=0 || RC=$?
if [ "$RC" -eq 2 ] && grep -q 'GAINED new.sh: SS001' "$TMP/self.out"; then
  ok "--baseline-ref reads the BASE allowance and refuses the same commit"
else
  bad "--baseline-ref reads the BASE allowance and refuses the same commit" \
      "rc=$RC out=$(tr '\n' ' ' < "$TMP/self.out" | head -c 200)"
fi

# A ref that does not resolve is a broken invocation, never "nothing regressed".
python3 "$LINT" --root "$REPO2" --baseline "$REPO2/base.json" \
  --baseline-ref "no-such-ref-abcdef" >/dev/null 2>"$TMP/badref.err" && RC=0 || RC=$?
if [ "$RC" -eq 2 ] && grep -q 'cannot resolve' "$TMP/badref.err"; then
  ok "an unresolvable --baseline-ref exits 2"
else
  bad "an unresolvable --baseline-ref exits 2" "rc=$RC"
fi

# The one case that must NOT be an error: the PR that INTRODUCES the baseline.
# The file is genuinely absent at base, which is distinguishable from a broken
# ref, so it degrades to the working-tree copy and SAYS SO on stdout rather than
# passing quietly -- the same declared-not-silent posture this linter enforces.
git -C "$REPO2" checkout -q -b intro main
git -C "$REPO2" rm -q base.json; git -C "$REPO2" commit -qm "unpin"
INTRO_SHA="$(git -C "$REPO2" rev-parse HEAD)"
git -C "$REPO2" checkout -q pr
python3 "$LINT" --root "$REPO2" --baseline "$REPO2/base.json" \
  --baseline-ref "$INTRO_SHA" >"$TMP/intro.out" 2>&1 && RC=0 || RC=$?
if [ "$RC" -eq 0 ] && grep -q 'absent at' "$TMP/intro.out"; then
  ok "a baseline absent at base degrades to the working tree and declares it"
else
  bad "a baseline absent at base degrades to the working tree and declares it" \
      "rc=$RC out=$(tr '\n' ' ' < "$TMP/intro.out" | head -c 200)"
fi

printf '\n%d passed, %d failed' "$PASS" "$FAIL"
[ "$NOTE" -eq 0 ] || printf ', %d note(s) (provenance unavailable, pin held)' "$NOTE"
printf '\n'
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS test-silent-success-lint"
