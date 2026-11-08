#!/usr/bin/env bash
# One dispatch a day goes to an Urgent ticket, ahead of the repo rotation
# (ASK-3996, D25 of the stuck-work synthesis 2026-11-07).
#
# WHY THIS EXISTS. On 2026-11-08 the rotation (home plus 7 opted-in repos, one per
# tick) spent all 3 daily dispatches on ktlyst, consulting and Alice while the
# Urgent ASK-3824 waited in kipi-system, about 2 days from its turn. Priority
# ordered the pool inside a repo and counted for nothing across repos.
#
# WHAT IS PINNED, through the REAL dispatcher:
#   1. the first tick of a budget day enters the first repo, in rotation order,
#      whose dry pick is Urgent, and the rotation cursor does NOT move;
#   2. the next tick that day runs the plain rotation from the unmoved cursor and
#      scans nothing (the D23 scar: a decision that repeats every tick);
#   3. a day with no Urgent pick anywhere runs the plain rotation;
#   4. a day that already dispatched does not scan;
#   5. the slot reaches a non-home repo with --repo pointing at it.
#
# THE ASSERTION IS ON WHAT `kipi work` WAS CALLED WITH, as in
# test-dispatch-client-refusal-after-hold.sh, whose fixture this reuses: the
# fixture `kipi` is a recorder, so what the dispatcher DID is answered by a file.
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

# --- three repos, the same shapes as the client-refusal fixture -------------
HOMEREPO="$WORK/kipi-system"
CLIENT="$WORK/consulting/projects/client_d"
PLAIN="$WORK/otherorg/projects/plainrepo"
mkrepo() {  # mkrepo <dir> <name> <rewrite:0|1>
  mkdir -p "$1"
  git init -q "$1"
  echo x > "$1/f.txt"
  G -C "$1" add -A; G -C "$1" commit -q -m c1
  git -C "$1" branch -M main
  git -C "$1" remote add origin "https://github.com/assafkip/$2.git"
  if [ "$3" = "1" ]; then
    git init -q --bare "$WORK/origin-$2.git"
    git -C "$WORK/origin-$2.git" symbolic-ref HEAD refs/heads/main
    git -C "$1" config "url.$WORK/origin-.insteadOf" "https://github.com/assafkip/"
    git -C "$1" push -q -u origin main
  fi
}
mkrepo "$HOMEREPO" kipi-system 1
mkrepo "$CLIENT"   client_d    0
mkrepo "$PLAIN"    plainrepo   0

# The fixture `kipi`: a recorder. A scan call (KIPI_PICK_PRIORITY=1) answers from
# a per-repo board file, "ASK-<n> <priority>" or empty. The dispatcher's own pick
# answers "no ready issues", so no tick ever launches a converge.
cat > "$HOMEREPO/kipi" <<EOF
#!/usr/bin/env bash
case "\$*" in
  *"--repo $PLAIN"*)  r=plainrepo ;;
  *"--repo $CLIENT"*) r=client_d ;;
  *)                  r=home ;;
esac
if [ "\${KIPI_PICK_PRIORITY:-0}" = "1" ]; then
  printf 'SCAN %s\n' "\$r" >> "$WORK/kipi-calls.txt"
  read -r id pri < "$WORK/board-\$r" 2>/dev/null || exit 0
  [ -n "\$id" ] || exit 0
  echo "2026-11-09T15:00:00Z [dry] would work \$id (attempt 1/3)"
  echo "2026-11-09T15:00:00Z [dry] pick priority \$id \$pri"
else
  printf 'MAIN %s\n' "\$r" >> "$WORK/kipi-calls.txt"
  echo "no ready issues"
fi
exit 0
EOF
chmod +x "$HOMEREPO/kipi"

seed_control_code() {  # seed_control_code <repo>
  mkdir -p "$1/q-system/.q-system/scripts" "$1/.claude"
  cp "$ROOT/q-system/.q-system/scripts/repo-preflight.sh" \
     "$ROOT/q-system/.q-system/scripts/linear-worker.sh" "$1/q-system/.q-system/scripts/"
  printf '{"hooks":{}}\n' > "$1/.claude/settings.json"
  G -C "$1" add -A; G -C "$1" commit -q -m "control code"
  git -C "$1" push -q origin main 2>/dev/null || true
}
seed_control_code "$HOMEREPO"
seed_control_code "$PLAIN"
seed_control_code "$CLIENT"

STUB="$WORK/bin"; mkdir -p "$STUB"
cat > "$STUB/gh" <<'GHEOF'
#!/usr/bin/env bash
case "$*" in
  "auth status"*)            exit 0 ;;
  "repo view"*)              echo "ok"; exit 0 ;;
  *"/branches/"*"/protection") echo '{"required_pull_request_reviews":{},"required_status_checks":{"contexts":["kipi/reviewer-approved"]}}'; exit 0 ;;
  "api repos/"*)             echo "main"; exit 0 ;;
esac
exit 0
GHEOF
chmod +x "$STUB/gh"
export PATH="$STUB:$PATH"

REG="$WORK/registry.json"
cat > "$REG" <<JSON
{"instances":[
  {"name":"client_d","path":"$CLIENT","has_git":true,
   "dispatch":{"enabled":true,"expected_remote":"https://github.com/assafkip/client_d.git"}},
  {"name":"plainrepo","path":"$PLAIN","has_git":true,
   "dispatch":{"enabled":true,"expected_remote":"https://github.com/assafkip/plainrepo.git"}}
]}
JSON

# HOME, registry, cursor and turn lock all live in the temp dir, so nothing here
# can touch the live dispatch state.
DLOG="$WORK/home/.config/kipi/dispatch.log"
run_dispatch() {
  ( cd "$HOMEREPO" \
    && HOME="$WORK/home" KIPI_REPO="$HOMEREPO" \
       KIPI_DISPATCH_REGISTRY="$REG" \
       KIPI_DISPATCH_CURSOR="$WORK/cursor" \
       KIPI_DISPATCH_TURNLOCK="$WORK/turn.lock" \
       KIPI_NOTIFY="/usr/bin/true" \
       bash "$DISPATCH" ) >>"$WORK/stdout.txt" 2>&1
}
# A fresh budget day: no count, no slot file, no log. The cursor sits on
# client_d, so the rotation order is plainrepo, kipi-system, client_d.
new_day() {  # new_day <home board> <client_d board> <plainrepo board>
  rm -rf "$WORK/home"; mkdir -p "$WORK/home/.config/kipi"
  printf '%s' client_d > "$WORK/cursor"
  : > "$WORK/kipi-calls.txt"; : > "$WORK/stdout.txt"
  printf '%s\n' "$1" > "$WORK/board-home"
  printf '%s\n' "$2" > "$WORK/board-client_d"
  printf '%s\n' "$3" > "$WORK/board-plainrepo"
}
calls() { tr '\n' ' ' < "$WORK/kipi-calls.txt"; }
cursor() { cat "$WORK/cursor" 2>/dev/null; }
ctx() { printf 'calls: [%s] cursor: [%s] log: %s' "$(calls)" "$(cursor)" "$(grep -E 'urgent slot|entering|nothing|REFUSED' "$DLOG" 2>/dev/null | cut -c22- | tr '\n' '|' | cut -c1-400)"; }

echo "== urgent slot (dispatcher under test: $DISPATCH)"

# --- 1 and 2: Urgent at home, a Low pick in the repo whose turn is next ------
new_day "ASK-1 1" "ASK-3 4" "ASK-2 4"
run_dispatch
C1="$(calls)"; K1="$(cursor)"
if [ "$C1" = "SCAN plainrepo SCAN home MAIN home " ] && [ "$K1" = "client_d" ]; then
  ok "case 1: the day's first tick scans in rotation order, enters the repo whose pick is Urgent, and leaves the cursor"
else
  bad "case 1: the first tick takes the Urgent slot and leaves the cursor" "$(ctx)"
fi
grep -q 'urgent slot: ASK-1 in kipi-system goes first today' "$DLOG" 2>/dev/null \
  && ok "case 1b: the log names the slot, the ticket and its repo" \
  || bad "case 1b: the log names the slot" "$(ctx)"
: > "$WORK/kipi-calls.txt"
run_dispatch
C2="$(calls)"; K2="$(cursor)"
if [ "$C2" = "MAIN plainrepo " ] && [ "$K2" = "plainrepo" ]; then
  ok "case 2: the next tick scans nothing and runs the rotation from the unmoved cursor"
else
  bad "case 2: the next tick runs the plain rotation, once" "$(ctx)"
fi

# --- 3: no Urgent pick anywhere ----------------------------------------------
new_day "ASK-1 2" "ASK-3 4" ""
run_dispatch
C3="$(calls)"; K3="$(cursor)"
if [ "$C3" = "SCAN plainrepo SCAN home SCAN client_d MAIN plainrepo " ] && [ "$K3" = "plainrepo" ]; then
  ok "case 3: with no Urgent pick, the tick runs the plain rotation and the cursor moves"
else
  bad "case 3: no Urgent means the plain rotation" "$(ctx)"
fi
: > "$WORK/kipi-calls.txt"
run_dispatch
[ "$(calls)" = "MAIN kipi-system " ] || [ "$(calls)" = "MAIN home " ] \
  && ok "case 3b: a day whose scan found nothing does not scan again" \
  || bad "case 3b: a scan that found nothing does not repeat" "$(ctx)"

# --- 4: the day already dispatched ------------------------------------------
new_day "ASK-1 1" "" ""
BUDGET_DAY="$(date -v-7H +%Y-%m-%d 2>/dev/null || date -d '-7 hours' +%Y-%m-%d)"
printf '1' > "$WORK/home/.config/kipi/dispatch-count-$BUDGET_DAY"
run_dispatch
C4="$(calls)"
case "$C4" in
  *SCAN*) bad "case 4: a day that already dispatched does not scan" "$(ctx)" ;;
  "MAIN plainrepo ") ok "case 4: a day that already dispatched does not scan; the rotation runs" ;;
  *) bad "case 4: a day that already dispatched runs the plain rotation" "$(ctx)" ;;
esac

# --- 5: the Urgent pick is in a non-home repo -------------------------------
new_day "ASK-1 3" "ASK-3 1" ""
run_dispatch
C5="$(calls)"; K5="$(cursor)"
if [ "$C5" = "SCAN plainrepo SCAN home SCAN client_d MAIN client_d " ] && [ "$K5" = "client_d" ]; then
  ok "case 5: the slot reaches a non-home repo, entered with --repo, and the cursor stays"
else
  bad "case 5: the slot reaches a non-home repo" "$(ctx)"
fi

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" = "0" ]
