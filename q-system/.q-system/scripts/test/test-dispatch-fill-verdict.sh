#!/usr/bin/env bash
# The dispatcher's side of "fill every free repo" (ASK-4008, D29), through the
# REAL kipi-dispatch.sh:
#   1. asked for a verdict (KIPI_DISPATCH_PASS_FILE), a pass that took the turn
#      writes the repo it entered and the rotation size; the fill loop in
#      kipi-dispatch-pinned.sh reads it (pinned in test-dispatch-pinned.sh T10);
#   2. not asked, it writes nothing, so a run by hand changes nothing;
#   3. the memory gate holds a new run when memory is short or claude processes
#      are at their ceiling, writes no verdict (the loop stops), and pages once;
#      with room, the pass reaches the worker pick.
# WHY THE MEMORY GATE: on 2026-11-08 about 16 parallel claude processes pushed
# swap to about 10 GB and filled the disk. Filling every repo without it would
# rebuild that.
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
command -v git >/dev/null || { echo "FATAL: git not on PATH"; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
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
[ "\${KIPI_PICK_PRIORITY:-0}" = "1" ] || echo MAIN >> "$WORK/kipi-calls.txt"
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
printf '#!/usr/bin/env bash\nprintf "PAGE %%s\\n" "$*" >> "%s/pages.log"\nexit 0\n' "$WORK" > "$WORK/notify.sh"
chmod +x "$WORK/notify.sh"
REG="$WORK/registry.json"; printf '{"instances":[]}\n' > "$REG"
VERDICT="$WORK/pass.verdict"

run_dispatch() {  # run_dispatch <mem reading> [ask for a verdict: 1|0] [reserved runs] [keep home and pages: 1]
  # Keeping HOME keeps the page markers, so the pages of a run of ticks are kept
  # too (ASK-4042 item 5: truncating pages.log per tick made test 5 read one tick).
  if [ "${4:-0}" != "1" ]; then rm -rf "$WORK/home"; : > "$WORK/pages.log"; fi
  mkdir -p "$WORK/home/.config/kipi"
  : > "$WORK/kipi-calls.txt"; rm -f "$VERDICT"
  local vf=""; [ "${2:-1}" = "1" ] && vf="$VERDICT"
  ( cd "$HOMEREPO" \
    && PATH="$STUB:$PATH" HOME="$WORK/home" KIPI_REPO="$HOMEREPO" \
       KIPI_DISPATCH_MEM_READING="$1" KIPI_DISPATCH_PASS_FILE="$vf" \
       KIPI_DISPATCH_RESERVED_RUNS="${3:-0}" KIPI_DISPATCH_RESERVED_PIDS="${RES_PIDS:-}" \
       KIPI_DISPATCH_PS_TABLE="${PS_TABLE:-}" \
       KIPI_DISPATCH_REGISTRY="$REG" KIPI_DISPATCH_CURSOR="$WORK/cursor" \
       KIPI_DISPATCH_TURNLOCK="$WORK/turn.lock" KIPI_DISPATCH_LIVE_PATTERN="kipi-fixture-no-such-converge" KIPI_DISPATCH_LIVE_LEDGER="$WORK/live.tsv" KIPI_NOTIFY="$WORK/notify.sh" \
       bash "$DISPATCH" ) > "$WORK/stdout.txt" 2>&1
}
DLOG="$WORK/home/.config/kipi/dispatch.log"
ctx() { printf 'verdict: [%s] calls: [%s] pages: [%s] log: %s' "$(cat "$VERDICT" 2>/dev/null)" \
          "$(tr '\n' ' ' < "$WORK/kipi-calls.txt")" "$(tr '\n' '|' < "$WORK/pages.log" | cut -c1-160)" \
          "$(tail -3 "$DLOG" 2>/dev/null | tr '\n' '|' | cut -c1-300)"; }

echo "== fill verdict and memory gate (under test: $DISPATCH)"

run_dispatch "free=60 procs=2"
if grep -q '^MAIN$' "$WORK/kipi-calls.txt" && grep -q '^entered=kipi-system repos=1 dispatched= pid=$' "$VERDICT" 2>/dev/null; then
  ok "1: a pass that took the turn writes the repo it entered and the rotation size"
else
  bad "1: the pass verdict names the entered repo" "$(ctx)"
fi

run_dispatch "free=60 procs=2" 0
[ ! -e "$VERDICT" ] && grep -q '^MAIN$' "$WORK/kipi-calls.txt" \
  && ok "2: not asked for a verdict, the pass writes none and still works" \
  || bad "2: no verdict unless asked" "$(ctx)"

run_dispatch "free=10 procs=2"
if [ ! -s "$WORK/kipi-calls.txt" ] && [ ! -e "$VERDICT" ] && grep -q 'memory gate: not filling a slot' "$DLOG" 2>/dev/null \
   && [ "$(grep -c 'short of memory' "$WORK/pages.log")" = "1" ]; then
  ok "3a: memory free under the floor holds the pass: no pick, no verdict (the loop stops), one page"
else
  bad "3a: short memory holds the pass" "$(ctx)"
fi

run_dispatch "free=60 procs=20"
[ ! -s "$WORK/kipi-calls.txt" ] && [ ! -e "$VERDICT" ] && grep -q 'memory gate: not filling a slot' "$DLOG" 2>/dev/null \
  && ok "3b: claude processes at the ceiling hold the pass" \
  || bad "3b: the process ceiling holds the pass" "$(ctx)"

# 4. PR #660 round 1, major: runs this tick already started count before ps can
# see them. 10 processes plus 2 reserved runs (4 processes) reach the ceiling of 14.
run_dispatch "free=60 procs=10" 1 2
[ ! -s "$WORK/kipi-calls.txt" ] && grep -q 'for 2 unseen run(s) of the 2 this tick started' "$DLOG" 2>/dev/null \
  && ok "4a: reserved runs count toward the process ceiling (10 + 2 runs x 2 = 14 holds)" \
  || bad "4a: reserved runs count toward the ceiling" "$(ctx)"
run_dispatch "free=60 procs=10" 1 0
grep -q '^MAIN$' "$WORK/kipi-calls.txt" \
  && ok "4b: the same reading with nothing reserved still fills (the reservation is what held 4a)" \
  || bad "4b: no reservation, no hold" "$(ctx)"
run_dispatch "free=30 procs=2" 1 3
[ ! -s "$WORK/kipi-calls.txt" ] \
  && ok "4c: reserved runs count against free memory too (30 - 3 runs x 5 = 15, under 20)" \
  || bad "4c: reserved runs count against free memory" "$(ctx)"

# 5. PR #660 round 1, minor: the page carries no reading, so a reading that moves
# between holding ticks pages once, with HOME and the pages kept across ticks as in
# production (ASK-4042 item 5: the old harness truncated pages.log every tick).
run_dispatch "free=10 procs=2" 1 0
run_dispatch "free=11 procs=2" 1 0 1
run_dispatch "free=12 procs=2" 1 0 1
[ "$(grep -c 'short of memory' "$WORK/pages.log")" = "1" ] \
  && ok "5: three holding ticks with a moving reading page once, not once a tick" \
  || bad "5: the memory page dedupes across a moving reading" "pages over three ticks: $(grep -c 'short of memory' "$WORK/pages.log")"

# 6. ASK-4042 item 1: A RESERVED RUN COUNTS ONCE. A run this tick started is
# reserved only while ps shows no claude under it; once its claude is visible, ps
# counts it. Two runs this tick: pid 111 has a claude child, 222 not yet.
printf '  111     1 bash\n  112   111 claude\n  222     1 bash\n  223   222 python3\n' > "$WORK/ps-one-seen.txt"
printf '  111     1 bash\n  112   111 python3\n  222     1 bash\n' > "$WORK/ps-none-seen.txt"
RES_PIDS="111 222" PS_TABLE="$WORK/ps-one-seen.txt" run_dispatch "free=60 procs=10" 1 2
grep -q '^MAIN$' "$WORK/kipi-calls.txt" \
  && ok "6a: a reserved run whose claude ps already sees is not counted twice (10 + 1 unseen x 2 = 12 fills)" \
  || bad "6a: no double count" "$(ctx)"
RES_PIDS="111 222" PS_TABLE="$WORK/ps-none-seen.txt" run_dispatch "free=60 procs=10" 1 2
[ ! -s "$WORK/kipi-calls.txt" ] \
  && ok "6b (negative): with no claude visible under either run, both are reserved and 14 holds" \
  || bad "6b: unseen runs are reserved" "$(ctx)"
RES_PIDS="111 999" PS_TABLE="$WORK/ps-one-seen.txt" run_dispatch "free=60 procs=12" 1 2
grep -q '^MAIN$' "$WORK/kipi-calls.txt" \
  && ok "6c: a reserved run that already exited is not reserved (its memory is back)" \
  || bad "6c: a dead reserved pid" "$(ctx)"
RES_PIDS="" PS_TABLE="$WORK/ps-one-seen.txt" run_dispatch "free=60 procs=10" 1 2
[ ! -s "$WORK/kipi-calls.txt" ] \
  && ok "6d: runs with no known pid are reserved, as before (fail safe)" \
  || bad "6d: runs with no pid" "$(ctx)"

# 6e. PR #672 round 1, major: a run ps already sees keeps its MEMORY reservation for
# the tick, since its claude has not spent its memory yet. 28 free, two runs this
# tick, one seen: 28 - 2 x 5 = 18, under the floor of 20, holds.
RES_PIDS="111 222" PS_TABLE="$WORK/ps-one-seen.txt" run_dispatch "free=28 procs=2" 1 2
[ ! -s "$WORK/kipi-calls.txt" ] && grep -q 'adjusted free=18 procs=4' "$DLOG" 2>/dev/null \
  && ok "6e: a visible run keeps its memory reservation for the tick (28 - 2 runs x 5 = 18 holds)" \
  || bad "6e: memory reserved for every run this tick started" "$(ctx)"
# 6f. PR #672 round 1, minor: an unreadable process table is said, and every run is
# reserved as before.
RES_PIDS="111 222" PS_TABLE="$WORK/no-such-ps-table.txt" run_dispatch "free=60 procs=10" 1 2
[ ! -s "$WORK/kipi-calls.txt" ] && grep -q 'could not read the process table, so all 2 run(s)' "$DLOG" 2>/dev/null \
  && ok "6f: an unreadable process table is logged and every run is reserved (14 holds)" \
  || bad "6f: the fallback is said" "$(ctx)"

# 7. ASK-4042 item 2: the hold line prints the adjusted reading next to the raw one.
RES_PIDS="111 222" PS_TABLE="$WORK/ps-none-seen.txt" run_dispatch "free=60 procs=10" 1 2
grep -q 'reading free=60 procs=10; adjusted free=50 procs=14 for 2 unseen run(s)' "$DLOG" 2>/dev/null \
  && ok "7: the hold line shows the adjusted values that made the decision" \
  || bad "7: honest hold line" "$(tail -2 "$DLOG" 2>/dev/null | cut -c1-300)"

# 8. ASK-4042 items 3 and 4: THE PAGE CLEARS ONLY WITH HEADROOM. Hold (page), then a
# tick in the 20 to 29 band (fills, keeps the marker), then hold again: still one
# page, the same episode. Then a tick at 30 or more clears it, and the next hold
# pages again.
run_dispatch "free=10 procs=2" 1 0
run_dispatch "free=25 procs=2" 1 0 1
B_FILLED="$(grep -c '^MAIN$' "$WORK/kipi-calls.txt")"
run_dispatch "free=10 procs=2" 1 0 1
[ "$B_FILLED" = "1" ] && [ "$(grep -c 'short of memory' "$WORK/pages.log")" = "1" ] \
  && ok "8a: a fill in the 20 to 29 band keeps the episode open: hold, band, hold pages once" \
  || bad "8a: band keeps the episode" "band filled=$B_FILLED pages=$(grep -c 'short of memory' "$WORK/pages.log")"
run_dispatch "free=35 procs=2" 1 0 1
run_dispatch "free=10 procs=2" 1 0 1
[ "$(grep -c 'short of memory' "$WORK/pages.log")" = "2" ] \
  && ok "8b: a tick with headroom (30 or more) clears it, so the next hold pages again" \
  || bad "8b: headroom clears the episode" "pages=$(grep -c 'short of memory' "$WORK/pages.log")"

# MUTANTS: each check above must be able to go red.
REAL_DISPATCH="$DISPATCH"
DISPATCH="$WORK/dispatch-doublecount.sh"
sed 's/MEM_PROCS=$((MEM_PROCS + 2 \* UNSEEN_RUNS))/MEM_PROCS=$((MEM_PROCS + 2 * RESERVED_RUNS))/' "$REAL_DISPATCH" > "$DISPATCH"
if cmp -s "$REAL_DISPATCH" "$DISPATCH"; then
  bad "mutant 6a: anchor" "the reservation line moved"
else
  RES_PIDS="111 222" PS_TABLE="$WORK/ps-one-seen.txt" run_dispatch "free=60 procs=10" 1 2
  grep -q 'memory gate: not filling a slot' "$DLOG" 2>/dev/null && [ ! -s "$WORK/kipi-calls.txt" ] \
    && ok "mutant killed: reserving every run on top of ps holds at 14, so 6a can go red" \
    || bad "mutant 6a survived" "$(ctx)"
fi
DISPATCH="$WORK/dispatch-noclear.sh"
sed 's/^  page_clear memory-gate$/  : page_clear cut/' "$REAL_DISPATCH" > "$DISPATCH"
if cmp -s "$REAL_DISPATCH" "$DISPATCH"; then
  bad "mutant 8b: anchor" "the memory-gate page_clear line moved"
else
  run_dispatch "free=10 procs=2" 1 0
  run_dispatch "free=35 procs=2" 1 0 1
  run_dispatch "free=10 procs=2" 1 0 1
  [ "$(grep -c 'short of memory' "$WORK/pages.log")" = "1" ] \
    && ok "mutant killed: without the page_clear the second episode never pages, so 8b can go red" \
    || bad "mutant 8b survived" "pages=$(grep -c 'short of memory' "$WORK/pages.log")"
fi
DISPATCH="$REAL_DISPATCH"

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" = "0" ]
