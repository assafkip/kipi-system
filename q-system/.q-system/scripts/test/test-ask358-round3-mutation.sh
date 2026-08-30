#!/usr/bin/env bash
# THE NEGATIVE SELF-TESTS FOR PR #211 ROUND 3 (ASK-358). Two majors, two
# mutations, one file.
#
# Both findings are refusals, and a refusal is the easiest kind of assertion to
# fake: anything that drops the input satisfies it. A typo in a regex, an
# exception, an absent fixture file -- each of those makes the suite green while
# the check under test does nothing. So each fix gets its own mutation here, and
# each mutation must flip a green case red. A check whose removal changes
# nothing was never the thing doing the work.
#
#   1. THE FORK GATE (ci-redrive.py). Deleting `if provenance == FORK` must make
#      a hostile fork PR be offered as machine work for a real Linear issue.
#   2. THE CARRIED BRANCH (kipi-dispatch.sh). Blanking REDRIVE_BRANCH must make
#      the dispatcher re-query gh, see the PR closed, take the fail-OPEN arm and
#      dispatch onto the branch the guard exists to reject. Note this mutates the
#      WIRING, not the arm: a green case can pass on an arm that is never fed.
#
# NEVER AGAINST THE REPO'S OWN FILES. Every mutant is written into a temp dir and
# the originals are only ever read -- undoing a mutation with a git restore has
# already destroyed a whole uncommitted fix once in this repo.
#
# EVERY MUTATION IS VALIDATED BEFORE IT IS TRUSTED. A patch that silently fails
# to apply produces a "mutant" identical to the original, and the case then
# reports a false KILL: the suite looks like it caught something and caught
# nothing. Hence the applied / differs / original-untouched trio per mutation,
# and a CONTROL run of the shipped code beside every mutant run.
set -uo pipefail

PASS=0; FAIL=0
ok()  { printf '  PASS %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; FAIL=$((FAIL + 1)); }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expected [$3] got [$2]"; fi; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
SCRIPTS_SRC="$REPO_ROOT/q-system/.q-system/scripts"
SRC="$SCRIPTS_SRC/ci-redrive.py"
DISPATCH_SRC="$REPO_ROOT/kipi-dispatch.sh"
for f in "$SRC" "$SCRIPTS_SRC/attempts-ledger.py" "$SCRIPTS_SRC/review-redrive.py" \
         "$DISPATCH_SRC"; do
  [ -f "$f" ] || { echo "FATAL: $f not found" >&2; exit 1; }
done

TMP="$(mktemp -d)"
cleanup() { [ -n "${TMP:-}" ] && [ -d "$TMP" ] && /bin/rm -r -f "$TMP"; }
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

# mutate <file> <needle> <replacement> ; prints APPLIED / NOT-FOUND / NO-OP
mutate() {
  python3 - "$1" "$2" "$3" <<'PY'
import io, sys
p, needle, repl = sys.argv[1], sys.argv[2], sys.argv[3]
s = io.open(p, encoding="utf-8").read()
if needle not in s:
    print("NOT-FOUND"); raise SystemExit(0)
s2 = s.replace(needle, repl, 1)
if s2 == s:
    print("NO-OP"); raise SystemExit(0)
io.open(p, "w", encoding="utf-8").write(s2)
print("APPLIED")
PY
}

# validate <label> <mutant> <pristine> <original>
validate() {
  if ! cmp -s "$2" "$3"; then ok "$1: mutant and control differ on disk"
  else bad "$1: mutant and control differ on disk" "identical -- any KILL is false"; fi
  if cmp -s "$4" "$3"; then ok "$1: the repo's own file was not touched"
  else bad "$1: the repo's own file was not touched" "$4 differs from the control copy"; fi
}

# =============================================================================
echo "== 1. the fork gate (ci-redrive.py) =="
# =============================================================================
mkdir -p "$TMP/f-control" "$TMP/f-mutant"
for d in f-control f-mutant; do
  cp "$SRC" "$TMP/$d/ci-redrive.py"
  cp "$SCRIPTS_SRC/attempts-ledger.py" "$TMP/$d/attempts-ledger.py"
done
check "the fork-gate mutation applied to the copy" \
  "$(mutate "$TMP/f-mutant/ci-redrive.py" \
            "        if provenance == FORK:" \
            "        if False:  # MUTANT: the fork gate, removed")" "APPLIED"
validate "fork gate" "$TMP/f-mutant/ci-redrive.py" "$TMP/f-control/ci-redrive.py" "$SRC"

cat > "$TMP/gh" <<'SH'
#!/usr/bin/env bash
cat "$GH_FIXTURE"
[ -n "${GH_THEN:-}" ] && cp "$GH_THEN" "$GH_FIXTURE"
exit 0
SH
chmod +x "$TMP/gh"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "$NOTIFY_LOG"\n' > "$TMP/notify.sh"
chmod +x "$TMP/notify.sh"
printf '#!/bin/sh\ncat /dev/null\n' > "$TMP/ps"; chmod +x "$TMP/ps"

# The hostile fixture from test-ci-redrive.sh section 13b: a fork PR wearing the
# exact branch converge would build and the same issue id in its title. Every
# fact here is its author's to choose, except isCrossRepository.
cat > "$TMP/prs.json" <<'JSON'
[{"number":900,"headRefName":"sana/ask-358","isDraft":false,
  "isCrossRepository":true,
  "headRefOid":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  "url":"https://x/900","title":"totally legitimate work (ASK-358)",
  "statusCheckRollup":[{"__typename":"CheckRun","name":"validate",
   "status":"COMPLETED","conclusion":"FAILURE",
   "workflowName":"Skeleton Validation"}]}]
JSON

offer_rc() {  # offer_rc <dir> ; rc of `redrive`, offer left in $TMP/offer.txt
  /bin/rm -f "$TMP/attempts.json"; : > "$TMP/notify.log"
  KIPI_GH="$TMP/gh" KIPI_PS="$TMP/ps" KIPI_NOTIFY="$TMP/notify.sh" \
  KIPI_ATTEMPTS="$TMP/attempts.json" GH_FIXTURE="$TMP/prs.json" \
  NOTIFY_LOG="$TMP/notify.log" \
  python3 "$1/ci-redrive.py" --repo-dir "$TMP" redrive >"$TMP/offer.txt" 2>/dev/null
  printf '%s' "$?"
}

check "CONTROL: the shipped fork gate refuses the hostile PR (rc 1)" \
  "$(offer_rc "$TMP/f-control")" "1"
MRC="$(offer_rc "$TMP/f-mutant")"
check "MUTANT: with the fork gate removed, the fork IS offered (rc 0)" "$MRC" "0"
if [ "$MRC" = "0" ]; then
  check "MUTANT: and it is offered as work for the real issue it named" \
    "$(cut -f1 "$TMP/offer.txt")" "ASK-358"
fi

# =============================================================================
echo
echo "== 2. the carried branch (kipi-dispatch.sh) =="
# =============================================================================
# Driven through the REAL dispatcher, because the thing under mutation is the
# wiring. test-dispatch-stale-checkout.sh section 15 drives branch_guard pulled
# out into a harness and hands it REDRIVE_BRANCH by hand; that can never show
# whether kipi-dispatch.sh fills it from the offer line.
D_ISS="ASK-8$$"
EXPECT_BRANCH="sana/$(printf '%s' "$D_ISS" | tr 'A-Z' 'a-z')"
ROOT="$TMP/d"
FAKE="$ROOT/repo"
FSCRIPTS="$FAKE/q-system/.q-system/scripts"
mkdir -p "$FSCRIPTS" "$ROOT/home/.config/kipi" "$ROOT/bin"
cp "$SRC" "$FSCRIPTS/ci-redrive.py"
cp "$SCRIPTS_SRC/attempts-ledger.py" "$FSCRIPTS/attempts-ledger.py"
# PRESENT ON PURPOSE: it is the file that makes the fail-open re-query reachable.
# Without it branch_guard's fallback arm never runs and the mutant looks fixed.
cp "$SCRIPTS_SRC/review-redrive.py" "$FSCRIPTS/review-redrive.py"
cp "$TMP/gh" "$ROOT/bin/gh"
printf '#!/bin/sh\ncat "${PS_FIXTURE:-/dev/null}"\n' > "$ROOT/bin/ps-stub"
chmod +x "$ROOT/bin/ps-stub"
: > "$TMP/ps-empty"
printf '#!/usr/bin/env bash\nsleep 30\n' > "$ROOT/converge.sh"; chmod +x "$ROOT/converge.sh"

cat > "$FAKE/kipi" <<SH
#!/usr/bin/env bash
case "\$1" in
  work) printf '0 ready issues\n' ;;
  converge)
    printf '%s\n' "\$3" >> "$ROOT/dispatched"
    exec bash "$ROOT/converge.sh" --issue "\$3" --max-rounds 3
    ;;
esac
SH
chmod +x "$FAKE/kipi"

mkdir -p "$TMP/d-control" "$TMP/d-mutant"
cp "$DISPATCH_SRC" "$TMP/d-control/kipi-dispatch.sh"
cp "$DISPATCH_SRC" "$TMP/d-mutant/kipi-dispatch.sh"
# THE FINDING, RESTORED: the selector reads the branch and the dispatcher throws
# it away, so branch_guard falls through and asks gh a second time.
check "the carried-branch mutation applied to the copy" \
  "$(mutate "$TMP/d-mutant/kipi-dispatch.sh" \
            '    REDRIVE_BRANCH="$(printf '"'"'%s'"'"' "$REDRIVE_LINE" | cut -f4)"' \
            '    REDRIVE_BRANCH=""  # MUTANT: the selector observation, dropped')" \
  "APPLIED"
validate "carried branch" "$TMP/d-mutant/kipi-dispatch.sh" \
  "$TMP/d-control/kipi-dispatch.sh" "$DISPATCH_SRC"

# A red PR whose head branch is NOT what converge would build. ci-redrive picks
# it (the issue id is in the title), reads sana/wrong-name -- and then the PR
# closes, which is what GH_THEN does to the board after the first read.
cat > "$ROOT/prs.json" <<JSON
[{"number":91,"headRefName":"sana/wrong-name","isDraft":false,
  "isCrossRepository":false,
  "headRefOid":"9999999999999999999999999999999999999999",
  "url":"https://x/91","title":"t ($D_ISS)",
  "statusCheckRollup":[{"__typename":"CheckRun","name":"validate",
   "status":"COMPLETED","conclusion":"FAILURE",
   "workflowName":"Skeleton Validation"}]}]
JSON
cp "$ROOT/prs.json" "$ROOT/prs-open.json"
printf '[]' > "$ROOT/prs-closed.json"

race() {  # race <dispatcher> ; prints the issue converge was handed, or nothing
  /bin/rm -r -f "$ROOT/home/.config/kipi"; mkdir -p "$ROOT/home/.config/kipi"
  date -u +%s > "$ROOT/home/.config/kipi/dispatch-lastbeat"
  : > "$ROOT/dispatched"; : > "$ROOT/pages.txt"
  /bin/rm -f "$ROOT/attempts.json"
  cp "$ROOT/prs-open.json" "$ROOT/prs.json"
  ( cd "$FAKE" && HOME="$ROOT/home" PATH="$ROOT/bin:$PATH" \
      KIPI_REPO="$FAKE" KIPI_NOTIFY="$TMP/notify.sh" \
      KIPI_DISPATCH_DAILY_MAX=9 KIPI_DISPATCH_MAX=999 \
      KIPI_ATTEMPTS="$ROOT/attempts.json" KIPI_GH="$ROOT/bin/gh" \
      KIPI_PS="$ROOT/bin/ps-stub" \
      GH_FIXTURE="$ROOT/prs.json" GH_THEN="$ROOT/prs-closed.json" \
      PS_FIXTURE="$TMP/ps-empty" NOTIFY_LOG="$ROOT/pages.txt" \
      bash "$1/kipi-dispatch.sh" >/dev/null 2>&1 )
  pkill -f "$ROOT/converge.sh" 2>/dev/null
  tail -1 "$ROOT/dispatched" 2>/dev/null
}

# THE HARNESS'S OWN CONTROL. If the selector never picked the PR at all, both
# runs below dispatch nothing and the mutation would read as killed. This line
# is what separates "the guard refused" from "nothing ever happened".
race "$TMP/d-control" >/dev/null
if grep -q "handing $D_ISS back" "$ROOT/home/.config/kipi/dispatch.log" 2>/dev/null; then
  ok "SETUP: the selector did pick the red PR, so there is a dispatch to refuse"
else
  bad "SETUP: the selector did pick the red PR, so there is a dispatch to refuse" \
      "$(cat "$ROOT/home/.config/kipi/dispatch.log" 2>/dev/null)"
fi

check "CONTROL: the shipped dispatcher refuses -- nothing is launched" \
  "$(race "$TMP/d-control")" ""
check "MUTANT: with the branch dropped, the closed PR re-opens the fail-OPEN arm" \
  "$(race "$TMP/d-mutant")" "$D_ISS"
if [ -s "$ROOT/dispatched" ]; then
  printf '     (the mutant committed %s onto %s, where no PR and no reviewer see it)\n' \
    "$D_ISS" "$EXPECT_BRANCH"
fi

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
