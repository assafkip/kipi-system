#!/usr/bin/env bash
# A branch refusal costs one tick, not every tick (ASK-3993, sp-c0c71ad1).
#
# WHY THIS EXISTS. branch_guard (ASK-358) refuses a dispatch whose issue has an
# open PR on a branch converge would not commit into. It used to be
# `branch_guard || exit 0`, and nothing in the loop changed its condition, so the
# next tick picked the same thing and refused again. On 2026-11-08 from 15:02:43Z
# a stopped lane PR (#647, on sana/ask-3985-self-cap) was offered as reviewer
# rework every tick and the whole queue waited until a person closed the PR.
#
# WHAT IS PINNED:
#   U. the refusing tick, cut from the shipped script by its own lines: a fresh
#      pick is set aside for a day; a reviewer redrive and a red-CI redrive also
#      spend their attempt at that head through mark-dispatched; the one writer
#      keeps live entries, drops expired ones and never duplicates an issue;
#   F. through the REAL dispatcher: the next tick hands the set-aside list to the
#      worker pick as KIPI_PICK_EXCLUDE, and an entry older than a day is not
#      handed on, so the guard re-tests that issue.
# The worker side (KIPI_PICK_EXCLUDE leaves an issue out of the fresh pick, never
# an explicit --issue) is pinned in test-worker-priority-order.sh.
#
# REF HATCH: KIPI_DISPATCH_UNDER_TEST points at another copy of kipi-dispatch.sh,
# so the pre-fix dispatcher can be watched to FAIL.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DISPATCH="${KIPI_DISPATCH_UNDER_TEST:-$ROOT/kipi-dispatch.sh}"
PASS=0; FAIL=0
ok()  { PASS=$((PASS + 1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; [ -n "${2:-}" ] && printf '       %s\n' "$2"; }

[ -f "$DISPATCH" ] || { echo "FATAL: kipi-dispatch.sh not found at $DISPATCH"; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export KIPI_NOTIFY=/usr/bin/true

echo "== branch refusal exit (dispatcher under test: $DISPATCH)"

# --- U. the refusing tick, cut from the shipped script ----------------------
# Both pieces are cut by their own lines, never restated: the helper block by its
# markers, the refusal by `if ! branch_guard; then` to the first `fi` at column 0.
HELPERS="$WORK/helpers.sh"; REFUSAL="$WORK/refusal.sh"
sed -n '/^# --- BRANCH REFUSAL EXIT/,/^# --- END BRANCH REFUSAL EXIT ---$/p' "$DISPATCH" > "$HELPERS"
sed -n '/^if ! branch_guard; then$/,/^fi$/p' "$DISPATCH" > "$REFUSAL"
grep -q '^branch_refused_record()' "$HELPERS" && grep -q 'mark-dispatched' "$REFUSAL" || {
  bad "the shipped script carries the branch refusal exit" \
      "helpers: $(wc -l < "$HELPERS") lines, refusal: $(wc -l < "$REFUSAL") lines"
  echo; echo "-------- $PASS passed, $FAIL failed --------"; exit 1; }

# The two redrive ledgers, as recorders: argv is what the refusal DID.
printf '#!/usr/bin/env python3\nimport sys\nopen(sys.argv[0] + ".calls", "a").write(" ".join(sys.argv[1:]) + "\\n")\n' > "$WORK/ci-redrive.py"
cp "$WORK/ci-redrive.py" "$WORK/review-redrive.py"

refuse() {  # refuse <ci|review|fresh>: one refusing tick, in a subshell (it exits)
  ( HOME="$WORK/uhome"; LOG="$WORK/u.log"; export HOME
    say() { printf 'SAY %s\n' "$*" >> "$WORK/u.say"; }
    branch_guard() { return 1; }
    REDRIVE="$WORK/ci-redrive.py"; REVIEW_REDRIVE="$WORK/review-redrive.py"
    NEXT="ASK-7"
    REDRIVE_NEXT=""; REDRIVE_SIG=""; REDRIVE_SHA=""
    REVIEW_ACTION=""; REVIEW_NEXT=""; REVIEW_PR=""; REVIEW_SHA=""
    case "$1" in
      ci)     REDRIVE_NEXT="ASK-7"; REDRIVE_SIG="sig-1"; REDRIVE_SHA="cafe01" ;;
      review) REVIEW_ACTION="rework"; REVIEW_NEXT="ASK-7"; REVIEW_PR="647"; REVIEW_SHA="1fa746eb" ;;
    esac
    # shellcheck disable=SC1090
    . "$HELPERS"
    # shellcheck disable=SC1090
    . "$REFUSAL"
    echo "FELL THROUGH"
  ) > "$WORK/u.out" 2>&1
}
ledger() { cat "$WORK/uhome/.config/kipi/dispatch-branch-refused.tsv" 2>/dev/null; }
reset_u() { rm -rf "$WORK/uhome"; mkdir -p "$WORK/uhome/.config/kipi"; : > "$WORK/u.say"
            : > "$WORK/ci-redrive.py.calls"; : > "$WORK/review-redrive.py.calls"; }

reset_u; refuse fresh
if grep -q 'FELL THROUGH' "$WORK/u.out"; then
  bad "U1: a refusal ends the tick" "$(cat "$WORK/u.out")"
elif [ "$(ledger | cut -f1)" = "ASK-7" ] && [ ! -s "$WORK/ci-redrive.py.calls" ] && [ ! -s "$WORK/review-redrive.py.calls" ]; then
  ok "U1: a refused fresh pick is set aside for a day, ends the tick, and spends no redrive attempt"
else
  bad "U1: a refused fresh pick is set aside" "ledger: [$(ledger | tr '\n' '|')] ci: [$(cat "$WORK/ci-redrive.py.calls")] review: [$(cat "$WORK/review-redrive.py.calls")]"
fi
grep -q 'SAY branch refusal: ASK-7 is set aside for a day' "$WORK/u.say" \
  && ok "U1b: the log says the issue is set aside and why the queue moves" \
  || bad "U1b: the log names the set-aside" "$(cat "$WORK/u.say")"

reset_u; refuse review
[ "$(cat "$WORK/review-redrive.py.calls")" = "mark-dispatched --issue ASK-7 --action rework --pr 647 --head-sha 1fa746eb" ] \
  && [ "$(ledger | cut -f1)" = "ASK-7" ] \
  && ok "U2: a refused reviewer redrive spends that PR attempt at this head, and is set aside" \
  || bad "U2: a refused reviewer redrive spends its attempt" "calls: [$(cat "$WORK/review-redrive.py.calls")] ledger: [$(ledger | tr '\n' '|')]"

reset_u; refuse ci
[ "$(cat "$WORK/ci-redrive.py.calls")" = "mark-dispatched --issue ASK-7 --signature sig-1 --head-sha cafe01" ] \
  && [ "$(ledger | cut -f1)" = "ASK-7" ] \
  && ok "U3: a refused red-CI redrive spends its attempt at this head, and is set aside" \
  || bad "U3: a refused red-CI redrive spends its attempt" "calls: [$(cat "$WORK/ci-redrive.py.calls")] ledger: [$(ledger | tr '\n' '|')]"

# The one writer: keeps a live entry, drops an expired one, refreshes a repeat.
reset_u
NOW="$(date +%s)"
printf 'ASK-5\t%s\nASK-6\t%s\nASK-7\t%s\n' "$NOW" "$((NOW - 90000))" "$((NOW - 100))" \
  > "$WORK/uhome/.config/kipi/dispatch-branch-refused.tsv"
refuse fresh
L="$(ledger | cut -f1 | tr '\n' ' ')"
N7="$(ledger | grep -c '^ASK-7	')"
[ "$L" = "ASK-5 ASK-7 " ] && [ "$N7" = "1" ] \
  && ok "U4: the writer keeps a live entry, drops one older than a day, and never duplicates an issue" \
  || bad "U4: the writer keeps, drops and refreshes" "ledger ids: [$L], ASK-7 rows: $N7"

# --- F. through the real dispatcher -----------------------------------------
# The client-refusal fixture, reduced to the home repo: the fixture `kipi` records
# the set-aside list it was handed and answers "no ready issues", so no tick
# launches anything.
command -v git >/dev/null || { echo "FATAL: git not on PATH"; exit 1; }
G() { git -c user.email=t@t.t -c user.name=t "$@"; }
HOMEREPO="$WORK/kipi-system"
mkdir -p "$HOMEREPO"; git init -q "$HOMEREPO"
echo x > "$HOMEREPO/f.txt"; G -C "$HOMEREPO" add -A; G -C "$HOMEREPO" commit -q -m c1
git -C "$HOMEREPO" branch -M main
git -C "$HOMEREPO" remote add origin "https://github.com/assafkip/kipi-system.git"
git init -q --bare "$WORK/origin-kipi-system.git"
git -C "$WORK/origin-kipi-system.git" symbolic-ref HEAD refs/heads/main
git -C "$HOMEREPO" config "url.$WORK/origin-.insteadOf" "https://github.com/assafkip/"
git -C "$HOMEREPO" push -q -u origin main
cat > "$HOMEREPO/kipi" <<EOF
#!/usr/bin/env bash
if [ "\${KIPI_PICK_PRIORITY:-0}" != "1" ]; then
  printf 'MAIN excl=[%s]\n' "\${KIPI_PICK_EXCLUDE:-}" >> "$WORK/kipi-calls.txt"
fi
echo "no ready issues"
exit 0
EOF
chmod +x "$HOMEREPO/kipi"
mkdir -p "$HOMEREPO/q-system/.q-system/scripts" "$HOMEREPO/.claude"
cp "$ROOT/q-system/.q-system/scripts/repo-preflight.sh" "$ROOT/q-system/.q-system/scripts/linear-worker.sh" \
   "$HOMEREPO/q-system/.q-system/scripts/"
printf '{"hooks":{}}\n' > "$HOMEREPO/.claude/settings.json"
G -C "$HOMEREPO" add -A; G -C "$HOMEREPO" commit -q -m "control code"; git -C "$HOMEREPO" push -q origin main
STUB="$WORK/bin"; mkdir -p "$STUB"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/gh"; chmod +x "$STUB/gh"
REG="$WORK/registry.json"; printf '{"instances":[]}\n' > "$REG"

run_dispatch() {
  ( cd "$HOMEREPO" \
    && PATH="$STUB:$PATH" HOME="$WORK/home" KIPI_REPO="$HOMEREPO" \
       KIPI_DISPATCH_REGISTRY="$REG" KIPI_DISPATCH_CURSOR="$WORK/cursor" \
       KIPI_DISPATCH_TURNLOCK="$WORK/turn.lock" KIPI_NOTIFY="/usr/bin/true" \
       bash "$DISPATCH" ) >> "$WORK/stdout.txt" 2>&1
}
new_tick() {  # new_tick <ledger rows...>: fresh home state carrying this ledger
  rm -rf "$WORK/home"; mkdir -p "$WORK/home/.config/kipi"
  : > "$WORK/kipi-calls.txt"; : > "$WORK/stdout.txt"
  printf '%s\n' "$@" | sed '/^$/d' > "$WORK/home/.config/kipi/dispatch-branch-refused.tsv"
}
DLOG="$WORK/home/.config/kipi/dispatch.log"
NOW="$(date +%s)"

new_tick "$(printf 'ASK-7\t%s' "$((NOW - 60))")"
run_dispatch
if grep -q '^MAIN excl=\[ASK-7\]$' "$WORK/kipi-calls.txt"; then
  ok "F1: the next tick hands the set-aside issue to the worker pick as KIPI_PICK_EXCLUDE"
else
  bad "F1: the next tick passes the set-aside list" "calls: [$(tr '\n' '|' < "$WORK/kipi-calls.txt")] log: $(tail -5 "$DLOG" 2>/dev/null | tr '\n' '|' | cut -c1-400)"
fi
grep -q 'set aside for a day after a branch refusal, not picked: ASK-7' "$DLOG" 2>/dev/null \
  && ok "F1b: the tick says which issues it left out" \
  || bad "F1b: the tick names what it left out" "$(tail -5 "$DLOG" 2>/dev/null | tr '\n' '|' | cut -c1-400)"

new_tick "$(printf 'ASK-7\t%s' "$((NOW - 90000))")"
run_dispatch
if grep -q '^MAIN excl=\[\]$' "$WORK/kipi-calls.txt"; then
  ok "F2: an entry older than a day is not handed on, so the guard re-tests the issue"
else
  bad "F2: an expired entry is dropped" "calls: [$(tr '\n' '|' < "$WORK/kipi-calls.txt")]"
fi

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" = "0" ]
