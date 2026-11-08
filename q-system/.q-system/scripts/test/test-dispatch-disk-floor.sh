#!/usr/bin/env bash
# The disk floor holds for the trees the fleet cuts from shell (ASK-3648).
#
# WHY THIS EXISTS. worktree-disk-floor.py was a PreToolUse hook only, so it saw
# `git worktree add` typed into Claude's Bash tool and nothing else. The trees the
# unattended fleet actually cuts come from kipi-dispatch.sh's children:
# linear-worker.sh and pr-review-agent.sh, from shell, with no tool call. On
# 2026-11-08 the disk reached 0 bytes free and every write on the Mac failed.
#
# WHAT IS PINNED, through the REAL scripts:
#   1. under the floor, dispatch runs the worktree reaper once, then dispatches
#      nothing: no `kipi` call, no count, and one page;
#   2. a second tick still under the floor pages nothing new (page_once);
#   3. a reaper that frees space lets the same tick dispatch, and the page clears;
#   4. over the floor, dispatch does not run the reaper and dispatches;
#   5. under the floor, the worker cuts no tree, starts no session, and says so;
#   6. over the floor, the same worker run cuts the tree and starts the session;
#   5c-5e. the worker's halt is an environmental halt: exit 9 and the env_halt
#      flag, so converge.sh exits 9, charges no attempt and pages nothing
#      (PR #656 review, finding 1: a bare break read as "no PR" and charged);
#   5f. the disk halt leaves the shared env-alert claim alone, so a usage-limit
#      page in the same window still goes out (review round 2, finding 3);
#   7. the reviewer cuts no NEW review tree under the floor, still re-detaches
#      an existing one, and cuts a new one over the floor;
#   7d. with no tree under the floor, the reviewer exits 9, the fleet's code for
#      a machine condition, so the worker sets env_halt instead of logging a
#      reviewer failure (review round 2, finding 1);
#   8. a malformed floor value keeps the floor on at the default (finding 2).
#
# The floor is set through worktree-reaper.json (refuse_worktree_below_gb), the
# same file the hook and the reaper read, so nothing here depends on how full the
# disk of the machine running the test is.
#
# REF HATCH: KIPI_DISPATCH_UNDER_TEST, KIPI_WORKER_UNDER_TEST and
# KIPI_REVIEWER_UNDER_TEST point at other copies, so the pre-fix scripts can be
# watched to FAIL. The worker copy runs from beside the real worker, so it keeps
# the sibling scripts it loads (PR #656 review, finding 3).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SCRIPTS="$ROOT/q-system/.q-system/scripts"
DISPATCH="${KIPI_DISPATCH_UNDER_TEST:-$ROOT/kipi-dispatch.sh}"
WORKER="${KIPI_WORKER_UNDER_TEST:-$SCRIPTS/linear-worker.sh}"
REVIEWER="${KIPI_REVIEWER_UNDER_TEST:-$SCRIPTS/pr-review-agent.sh}"
PASS=0; FAIL=0
ok()  { PASS=$((PASS + 1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; [ -n "${2:-}" ] && printf '       %s\n' "$2"; }

[ -f "$DISPATCH" ] || { echo "FATAL: kipi-dispatch.sh not found at $DISPATCH"; exit 1; }
[ -f "$WORKER" ]   || { echo "FATAL: linear-worker.sh not found at $WORKER"; exit 1; }
REAL_PY="$(command -v python3)" || { echo "FATAL: python3 not on PATH"; exit 1; }
command -v git >/dev/null || { echo "FATAL: git not on PATH"; exit 1; }
unset KIPI_LINEAR_CLAIMS KIPI_SESSION_ID CLAUDE_SESSION_ID KIPI_WORKTREE_REAPER_CONFIG 2>/dev/null || true

WORK="$(mktemp -d)"
UT_WORKER=""
trap 'rm -rf "$WORK"; [ -n "$UT_WORKER" ] && rm -f "$UT_WORKER"' EXIT
G() { git -c user.email=t@t.t -c user.name=t "$@"; }

floor_config() {  # floor_config <path> <gb>
  "$REAL_PY" - "$1" "$2" <<'PY'
import json, sys
json.dump({"roots": [], "min_idle_hours": 6, "alarm_below_gb": 0,
           "refuse_worktree_below_gb": int(sys.argv[2])}, open(sys.argv[1], "w"))
PY
}
UNDER=1000000   # GB: no disk is this big, so the measure is always under it
OVER=0          # GB: every disk is at or over it

# ============================== dispatch ====================================
HOMEREPO="$WORK/kipi-system"
mkdir -p "$HOMEREPO"
git init -q "$HOMEREPO"
echo x > "$HOMEREPO/f.txt"
git init -q --bare "$WORK/origin-kipi-system.git"
git -C "$WORK/origin-kipi-system.git" symbolic-ref HEAD refs/heads/main
mkdir -p "$HOMEREPO/q-system/.q-system/scripts" "$HOMEREPO/.claude"
cp "$SCRIPTS/repo-preflight.sh" "$SCRIPTS/linear-worker.sh" \
   "$SCRIPTS/worktree-disk-floor.py" "$SCRIPTS/worktree-reaper.py" \
   "$HOMEREPO/q-system/.q-system/scripts/"
printf '{"hooks":{}}\n' > "$HOMEREPO/.claude/settings.json"
FLOOR_CFG="$HOMEREPO/q-system/.q-system/worktree-reaper.json"
floor_config "$FLOOR_CFG" "$UNDER"
cat > "$HOMEREPO/kipi" <<EOF
#!/usr/bin/env bash
printf 'KIPI %s\n' "\$*" >> "$WORK/kipi-calls.txt"
echo "no ready issues"
exit 0
EOF
chmod +x "$HOMEREPO/kipi"
G -C "$HOMEREPO" add -A; G -C "$HOMEREPO" commit -q -m c1
git -C "$HOMEREPO" branch -M main
git -C "$HOMEREPO" remote add origin "https://github.com/assafkip/kipi-system.git"
git -C "$HOMEREPO" config "url.$WORK/origin-.insteadOf" "https://github.com/assafkip/"
git -C "$HOMEREPO" push -q -u origin main

# The reaper stand-in records each call. With FREE_ON_REAP=1 it "frees space" by
# lowering the floor, which is what a real reaper pass looks like from outside.
REAPER="$WORK/reaper-stub"
cat > "$REAPER" <<EOF
#!/usr/bin/env python3
import json, os, sys
open("$WORK/reaper-calls.txt", "a").write("REAPER %s\n" % " ".join(sys.argv[1:]))
if os.environ.get("FREE_ON_REAP") == "1":
    json.dump({"roots": [], "min_idle_hours": 6, "alarm_below_gb": 0,
               "refuse_worktree_below_gb": 0}, open("$FLOOR_CFG", "w"))
EOF
chmod +x "$REAPER"

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
cat > "$WORK/notify" <<EOF
#!/usr/bin/env bash
printf 'PAGE %s\n' "\$1" >> "$WORK/pages.txt"
EOF
chmod +x "$WORK/notify"

REG="$WORK/registry.json"
printf '{"instances":[]}\n' > "$REG"
DLOG="$WORK/home/.config/kipi/dispatch.log"
run_dispatch() {
  ( cd "$HOMEREPO" \
    && PATH="$STUB:$PATH" HOME="$WORK/home" KIPI_REPO="$HOMEREPO" \
       KIPI_DISPATCH_REGISTRY="$REG" \
       KIPI_DISPATCH_CURSOR="$WORK/cursor" \
       KIPI_DISPATCH_TURNLOCK="$WORK/turn.lock" \
       KIPI_WORKTREE_REAPER="$REAPER" \
       KIPI_NOTIFY="$WORK/notify" \
       KIPI_DISPATCH_LIVE_PATTERN="kipi-fixture-no-such-converge" \
       KIPI_DISPATCH_MEM_READING="free=90 procs=0" \
       bash "$DISPATCH" ) >>"$WORK/stdout.txt" 2>&1
  # THE FIXTURE NEVER READS THE MAC (ASK-4042). Since #660 the cap is derived (1
  # here) and the memory gate reads the real process table, so on a Mac with live
  # converges or 14 claude processes every case read "skip: 2 converge run(s)
  # live, cap 1" and 6 of 21 went red (green in CI, red locally, 2026-11-08).
}
new_tick_state() {  # new_tick_state <floor-gb>
  rm -rf "$WORK/home"; mkdir -p "$WORK/home/.config/kipi"
  : > "$WORK/kipi-calls.txt"; : > "$WORK/reaper-calls.txt"; : > "$WORK/pages.txt"; : > "$WORK/stdout.txt"
  floor_config "$FLOOR_CFG" "$1"
}
n() { { grep -c . "$1" 2>/dev/null || echo 0; } | head -1; }
# Disk-floor pages only: a fresh HOME is a first beat, and the liveness beacon
# pages "heartbeat: STARTED" on it, which is not what these cases are about.
floor_pages() { { grep -c "under the worktree floor" "$WORK/pages.txt" 2>/dev/null || echo 0; } | head -1; }
ctx() { printf 'kipi=%s reaper=%s floor-pages=%s log: %s' "$(n "$WORK/kipi-calls.txt")" "$(n "$WORK/reaper-calls.txt")" "$(floor_pages)" "$(grep -iE 'disk|FATAL|REFUSED' "$DLOG" 2>/dev/null | cut -c22- | tr '\n' '|' | cut -c1-400)"; }
BUDGET_DAY="$(date -v-7H +%Y-%m-%d 2>/dev/null || date -d '-7 hours' +%Y-%m-%d)"

echo "== disk floor, dispatch (under test: $DISPATCH)"

# --- 1: under the floor -----------------------------------------------------
new_tick_state "$UNDER"
run_dispatch
if [ "$(n "$WORK/kipi-calls.txt")" = "0" ] && [ "$(n "$WORK/reaper-calls.txt")" = "1" ]; then
  ok "case 1: under the floor, the reaper runs once and nothing is dispatched"
else
  bad "case 1: under the floor, reaper once and no dispatch" "$(ctx)"
fi
grep -q "REAPER --apply" "$WORK/reaper-calls.txt" \
  && ok "case 1b: the reaper is run with --apply" \
  || bad "case 1b: the reaper is run with --apply" "$(ctx)"
grep -q "DISK FLOOR: disk-floor: .* -> UNDER after the reaper ran" "$DLOG" 2>/dev/null \
  && ok "case 1c: the log says the tick held, with the numbers" \
  || bad "case 1c: the log says the tick held" "$(ctx)"
[ "$(floor_pages)" = "1" ] \
  && ok "case 1d: one page goes out" \
  || bad "case 1d: one page goes out" "$(ctx)"
[ ! -f "$WORK/home/.config/kipi/dispatch-count-$BUDGET_DAY" ] \
  && ok "case 1e: the held tick spends no daily budget" \
  || bad "case 1e: the held tick spends no daily budget" "count=$(cat "$WORK/home/.config/kipi/dispatch-count-$BUDGET_DAY")"

# --- 2: a second tick, still under ------------------------------------------
: > "$WORK/pages.txt"; : > "$WORK/reaper-calls.txt"
run_dispatch
if [ "$(floor_pages)" = "0" ] && [ "$(n "$WORK/kipi-calls.txt")" = "0" ]; then
  ok "case 2: the next tick under the floor holds again and pages nothing new"
else
  bad "case 2: the next tick holds and stays quiet" "$(ctx)"
fi

# --- 3: the reaper frees space ------------------------------------------------
: > "$WORK/reaper-calls.txt"
FREE_ON_REAP=1 run_dispatch
if [ "$(n "$WORK/reaper-calls.txt")" = "1" ] && [ "$(n "$WORK/kipi-calls.txt")" -ge 1 ]; then
  ok "case 3: a reaper pass that frees space lets the same tick dispatch"
else
  bad "case 3: space freed by the reaper means dispatch" "$(ctx)"
fi
[ ! -f "$WORK/home/.config/kipi/paged-disk-floor" ] \
  && ok "case 3b: the page clears once space is back" \
  || bad "case 3b: the page clears once space is back" "$(ctx)"

# --- 4: over the floor --------------------------------------------------------
new_tick_state "$OVER"
run_dispatch
if [ "$(n "$WORK/reaper-calls.txt")" = "0" ] && [ "$(n "$WORK/kipi-calls.txt")" -ge 1 ] && [ "$(floor_pages)" = "0" ]; then
  ok "case 4: over the floor, no reaper, no page, and the tick dispatches"
else
  bad "case 4: over the floor dispatches as before" "$(ctx)"
fi

# ============================== worker ======================================
echo "== disk floor, worker (under test: $WORKER)"
# The worker finds its sibling scripts through SCRIPT_DIR and the skeleton's
# guard settings through SCRIPT_DIR/../../.., so a copy anywhere else dies on a
# missing function or guard set, not on the floor (PR #656 review, finding 3).
# The copy under test sits beside the real worker, under a name the EXIT trap
# removes.
if [ -n "${KIPI_WORKER_UNDER_TEST:-}" ]; then
  UT_WORKER="$SCRIPTS/.worker-under-test-$$.sh"
  cp "$KIPI_WORKER_UNDER_TEST" "$UT_WORKER"
  WORKER="$UT_WORKER"
fi
WSCRIPTS="$(dirname "$WORKER")"
git init -q --bare "$WORK/w-origin" && git -C "$WORK/w-origin" symbolic-ref HEAD refs/heads/main
git init -q "$WORK/skel"
G -C "$WORK/skel" commit -q --allow-empty -m init
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "$WORK/w-origin"
git -C "$WORK/skel" push -q -u origin main

WSTUB="$WORK/wbin"; mkdir -p "$WSTUB"
# python3: the Linear calls are stubbed, everything else (the floor check among
# them) is the real interpreter running the real script. As in
# test-linear-worker-parallel.sh.
cat > "$WSTUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '{"ready":[{"id":"%s","title":"t","project":"p"}],"total_open":1}\n' "\${2:-ASK-AAA}"
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
printf '#!/usr/bin/env bash\nexit 0\n' > "$WSTUB/gh"
cat > "$WSTUB/claude" <<EOF
#!/usr/bin/env bash
echo "\$(pwd)" >> "$WORK/worked.txt"
exit 0
EOF
cat > "$WSTUB/reviewer-noop" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$WSTUB/python3" "$WSTUB/gh" "$WSTUB/claude" "$WSTUB/reviewer-noop"

run_worker() {  # run_worker <label> <floor-gb> <issue>
  floor_config "$WORK/wfloor-$1.json" "$2"
  ( cd "$WORK/skel" \
    && PATH="$WSTUB:$PATH" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state-$1" \
       KIPI_PR_REVIEWER="$WSTUB/reviewer-noop" KIPI_NOTIFY="/usr/bin/true" \
       KIPI_WORKTREE_REAPER_CONFIG="$WORK/wfloor-$1.json" \
       bash "$WORKER" --apply --issue "$3" --limit 1 ) >"$WORK/$1.out" 2>&1
  echo "$?" > "$WORK/$1.rc"
}
flag() {  # flag <state-label> <issue> <field>
  "$REAL_PY" "$WSCRIPTS/attempts-ledger.py" "$WORK/state-$1/linear-worker-attempts.json" get "$2" "$3" "" 2>/dev/null
}
worked() { { grep -c "$1" "$WORK/worked.txt" 2>/dev/null || echo 0; } | head -1; }

# --- 5: under the floor -------------------------------------------------------
: > "$WORK/worked.txt"
run_worker under "$UNDER" ASK-AAA
if [ ! -d "$WORK/state-under/worktrees/ask-aaa" ] && [ "$(worked ask-aaa)" = "0" ]; then
  ok "case 5: under the floor, the worker cuts no tree and starts no session"
else
  bad "case 5: under the floor, no tree and no session" "$(grep -iE 'INFRA|disk' "$WORK/under.out" | head -3)"
fi
grep -q "INFRA: disk-floor: .* -> UNDER; no worktree for ASK-AAA" "$WORK/under.out" \
  && ok "case 5b: the worker says why, and that the issue is not charged" \
  || bad "case 5b: the worker says why" "$(tail -5 "$WORK/under.out")"

[ "$(cat "$WORK/under.rc")" = "9" ] \
  && ok "case 5c: the halted run exits 9, the worker's infra code, not 0" \
  || bad "case 5c: the halted run exits 9" "rc=$(cat "$WORK/under.rc")"
[ "$(flag under ASK-AAA env_halt)" = "True" ] \
  && ok "case 5d: the issue carries the env_halt flag converge.sh reads" \
  || bad "case 5d: env_halt is set" "env_halt=[$(flag under ASK-AAA env_halt)]"

[ ! -e "$WORK/state-under/env-alert.claim" ] && grep -q "the page is kipi-dispatch.sh's" "$WORK/under.out" \
  && ok "case 5f: the disk halt takes no shared env-alert claim; dispatch owns the disk page" \
  || bad "case 5f: the disk halt leaves env-alert.claim alone" "claim=$([ -e "$WORK/state-under/env-alert.claim" ] && echo present || echo absent) $(grep -E 'HALTED|disk-floor halt' "$WORK/under.out" | head -2 | tr '\n' '|')"

# --- 5e: converge over a held worker charges nothing ---------------------------
floor_config "$WORK/wfloor-conv.json" "$UNDER"
mkdir -p "$WORK/state-conv"
: > "$WORK/conv-pages.txt"
cat > "$WORK/conv-notify" <<EOF
#!/usr/bin/env bash
printf 'PAGE %s\n' "\$1" >> "$WORK/conv-pages.txt"
EOF
chmod +x "$WORK/conv-notify"
( cd "$WORK/skel" \
  && PATH="$WSTUB:$PATH" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state-conv" \
     KIPI_PR_REVIEWER="$WSTUB/reviewer-noop" KIPI_NOTIFY="$WORK/conv-notify" \
     KIPI_WORKTREE_REAPER_CONFIG="$WORK/wfloor-conv.json" \
     KIPI_CONVERGE_WORKER="bash $WORKER" \
     bash "$WSCRIPTS/converge.sh" --issue ASK-CCC --max-rounds 1 ) >"$WORK/conv.out" 2>&1
CONV_RC=$?
CONV_COUNT="$(flag conv ASK-CCC count)"
if [ "$CONV_RC" = "9" ] && { [ -z "$CONV_COUNT" ] || [ "$CONV_COUNT" = "0" ] || [ "$CONV_COUNT" = "None" ]; } \
   && ! grep -q "could not open" "$WORK/conv-pages.txt"; then
  ok "case 5e: converge over a floor-held worker exits 9, charges no attempt, pages no 'could not open a PR'"
else
  bad "case 5e: converge charges nothing for a floor hold" "rc=$CONV_RC count=[$CONV_COUNT] pages: $(tr '\n' '|' < "$WORK/conv-pages.txt" | cut -c1-200) out: $(grep -E 'STOP|NOT ATTEMPTED|INFRA' "$WORK/conv.out" | head -2 | tr '\n' '|')"
fi

# --- 6: over the floor --------------------------------------------------------
# Its own issue: a pre-fix worker in case 5 leaves sana/ask-aaa checked out in
# case 5's tree, and git refuses that branch a second tree.
: > "$WORK/worked.txt"
run_worker over "$OVER" ASK-BBB
if [ -d "$WORK/state-over/worktrees/ask-bbb" ] && [ "$(worked ask-bbb)" -ge 1 ]; then
  ok "case 6: over the floor, the same run cuts the tree and starts the session"
else
  bad "case 6: over the floor, the worker works as before" "$(grep -iE 'INFRA|disk|skip' "$WORK/over.out" | head -3)"
fi

# ============================== reviewer ====================================
echo "== disk floor, reviewer tree (under test: $REVIEWER)"
RREPO="$WORK/rrepo"; mkdir -p "$RREPO"; git init -q "$RREPO"
echo r1 > "$RREPO/f.txt"; G -C "$RREPO" add -A; G -C "$RREPO" commit -q -m r1
RSHA="$(git -C "$RREPO" rev-parse HEAD)"
RT="$WORK/review-tree"
# The real function, lifted out by name as test-review-worktree-ref.sh does.
review_call() {  # review_call <floor-gb> -> prints what review_worktree printed
  floor_config "$WORK/rfloor.json" "$1"
  ( PR=77; REVIEW_REPO="$RREPO"; REVIEW_SLUG="t/t"
    DISK_FLOOR_PY="$SCRIPTS/worktree-disk-floor.py"
    export KIPI_WORKTREE_REAPER_CONFIG="$WORK/rfloor.json"
    for fn in _wt_bail acquire_wt_lock release_wt_lock review_worktree; do
      pat="/^${fn}() {/,/^}/p"
      eval "$(sed -n "$pat" "$REVIEWER")"
      declare -f "$fn" >/dev/null || { echo "EXTRACT-FAILED $fn"; exit 1; }
    done
    review_tree_path() { echo "$RT"; }
    review_worktree "$RSHA" 2>/dev/null )
}
R1="$(review_call "$UNDER")"
[ -z "$R1" ] && [ ! -d "$RT" ] \
  && ok "case 7: under the floor, the reviewer cuts no new review tree" \
  || bad "case 7: no new review tree under the floor" "printed=[$R1] tree-exists=$([ -d "$RT" ] && echo yes || echo no)"
R2="$(review_call "$OVER")"
[ "$R2" = "$RT" ] && [ -d "$RT" ] \
  && ok "case 7b: over the floor, the reviewer cuts its tree" \
  || bad "case 7b: a review tree over the floor" "printed=[$R2]"
R3="$(review_call "$UNDER")"
[ "$R3" = "$RT" ] \
  && ok "case 7c: under the floor, an existing review tree is still re-detached (it costs no disk)" \
  || bad "case 7c: re-detach under the floor" "printed=[$R3]"

# --- 7d: the shipped caller block, run with no tree --------------------------
# Extracted from the real reviewer by its own anchors, so the case follows the
# code. review_worktree is stubbed to "no tree", which is what it prints under
# the floor (case 7); the block must then exit 9 under the floor and fall
# through to the tree-search WARN over it.
CALLER="$WORK/caller.sh"
awk '/^if \[ -n "\$HEAD_SHA" \] && git -C "\$REVIEW_REPO" cat-file -e/{on=1} on && /^elif \[ -n "\$HEAD_SHA" \]; then/{exit} on' "$REVIEWER" > "$CALLER"
echo "fi" >> "$CALLER"
caller_rc() {  # caller_rc <floor-gb> -> exit code of the extracted block
  floor_config "$WORK/cfloor.json" "$1"
  ( HEAD_SHA="$RSHA"; REVIEW_REPO="$RREPO"; PR=77
    DISK_FLOOR_PY="$SCRIPTS/worktree-disk-floor.py"
    export KIPI_WORKTREE_REAPER_CONFIG="$WORK/cfloor.json"
    review_worktree() { return 1; }
    assert_pr_ref_not_stale() { return 0; }
    . "$CALLER" ) >/dev/null 2>&1
  echo "$?"
}
if [ "$(grep -c 'review_worktree' "$CALLER")" -ge 1 ]; then
  C_UNDER="$(caller_rc "$UNDER")"; C_OVER="$(caller_rc "$OVER")"
  [ "$C_UNDER" = "9" ] && [ "$C_OVER" = "0" ] \
    && ok "case 7d: with no tree, the reviewer exits 9 under the floor and falls through over it" \
    || bad "case 7d: reviewer exit 9 under the floor" "under=$C_UNDER over=$C_OVER"
else
  bad "case 7d: the caller block was not extracted (anchors moved in $REVIEWER)"
fi

# --- 8: a malformed floor value ------------------------------------------------
printf '{"refuse_worktree_below_gb": "%s GB"}' "$UNDER" > "$WORK/bad-floor.json"
M_LINE="$(KIPI_WORKTREE_REAPER_CONFIG="$WORK/bad-floor.json" "$REAL_PY" "$SCRIPTS/worktree-disk-floor.py" --check 2>/dev/null)"; M_RC=$?
[ "$M_RC" != "2" ] && printf '%s' "$M_LINE" | grep -q "is not a number; using the default" \
  && ok "case 8: a malformed floor value keeps the floor on at the default and says so" \
  || bad "case 8: a malformed floor keeps the floor on" "rc=$M_RC line=$M_LINE"

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" = "0" ]
