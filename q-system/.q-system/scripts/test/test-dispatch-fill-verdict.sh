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

run_dispatch() {  # run_dispatch <mem reading> [ask for a verdict: 1|0]
  rm -rf "$WORK/home"; mkdir -p "$WORK/home/.config/kipi"
  : > "$WORK/kipi-calls.txt"; : > "$WORK/pages.log"; rm -f "$VERDICT"
  local vf=""; [ "${2:-1}" = "1" ] && vf="$VERDICT"
  ( cd "$HOMEREPO" \
    && PATH="$STUB:$PATH" HOME="$WORK/home" KIPI_REPO="$HOMEREPO" \
       KIPI_DISPATCH_MEM_READING="$1" KIPI_DISPATCH_PASS_FILE="$vf" \
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
if grep -q '^MAIN$' "$WORK/kipi-calls.txt" && grep -q '^entered=kipi-system repos=1 dispatched=$' "$VERDICT" 2>/dev/null; then
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

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" = "0" ]
