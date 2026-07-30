#!/usr/bin/env bash
# Reproducer for sp-c775b116: the dispatcher ran the founder's working tree with
# no freshness check, so a merge alone never reached the running loop.
#
# Pairs with: stale_check() in kipi-dispatch.sh.
#
# The four states that matter, and only ONE of them may refuse:
#   behind  -> REFUSE (would build on superseded code and auto-merge it)
#   ahead   -> RUN    (an agent commits locally before opening a PR)
#   equal   -> RUN
#   no answer (fetch fails / offline) -> RUN, because a network blip must not
#             wedge the loop. Fail closed on staleness, fail open on not knowing.
#
# The ahead and offline cases are the point. A check that refuses whenever HEAD
# differs from origin/main passes a naive behind-test and wedges the loop on its
# own unpushed work, which is a worse bug than the one being fixed.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Derive the repo from the SCRIPT, never from $PWD -- a test that asks the
# checkout it happens to run in proves nothing about the caller.
REPO="$(cd "$HERE" && git rev-parse --show-toplevel)"
DISPATCH="$REPO/kipi-dispatch.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

[ -f "$DISPATCH" ] || { echo "no kipi-dispatch.sh at $DISPATCH"; exit 1; }

if ! grep -q 'stale_check' "$DISPATCH"; then
  echo "  FAIL: THE DEFECT: kipi-dispatch.sh has no stale_check, so a merge never reaches the running loop"
  echo "-------- 0 passed, 1 failed --------"
  exit 1
fi

# Extract stale_check and drive it directly. Running the whole dispatcher would
# reach Linear and could dispatch REAL work -- never let a test touch a live
# data path (fable-discipline lint blocks it, and this is why).
HARNESS="$WORK/stale_check.sh"
{
  echo 'set -uo pipefail'
  echo 'REPO="$PWD"'
  echo 'say()  { printf "SAY %s\n"  "$*"; }'
  echo 'page() { printf "PAGE %s\n" "$*"; }'
  awk '/^stale_check\(\) \{/,/^\}/' "$DISPATCH"
  echo 'stale_check && echo "VERDICT=RUN" || echo "VERDICT=REFUSE"'
} > "$HARNESS"

# --- a real origin + clone, because stale_check asks git real questions ------
ORIGIN="$WORK/origin.git"; CLONE="$WORK/clone"
git init -q --bare -b main "$ORIGIN"
git init -q -b main "$WORK/seed"
( cd "$WORK/seed"
  git config user.email t@e.com; git config user.name t
  echo one > f.txt; git add -A; git commit -qm one
  git remote add origin "$ORIGIN"; git push -q origin main ) >/dev/null 2>&1
git clone -q "$ORIGIN" "$CLONE" >/dev/null 2>&1
( cd "$CLONE"; git config user.email t@e.com; git config user.name t )

run_check() { ( cd "$1" && bash "$HARNESS" 2>&1 ); }

echo "== 1. equal: HEAD == origin/main -> RUN =="
OUT="$(run_check "$CLONE")"
echo "$OUT" | grep -q 'VERDICT=RUN' \
  && ok "an up-to-date checkout runs" \
  || bad "an up-to-date checkout was refused: $(echo "$OUT" | tr '\n' ' ')"

echo
echo "== 2. THE DEFECT: behind -> REFUSE and PAGE =="
( cd "$WORK/seed"; echo two >> f.txt; git commit -qam two; git push -q origin main ) >/dev/null 2>&1
OUT="$(run_check "$CLONE")"
if echo "$OUT" | grep -q 'VERDICT=REFUSE'; then
  ok "a checkout behind origin/main refuses to dispatch"
else
  bad "THE DEFECT: a checkout 1 commit behind origin/main still dispatched"
fi
echo "$OUT" | grep -q '^PAGE ' \
  && ok "the refusal pages the founder" \
  || bad "refused silently: an unattended refusal nobody is told about is a dead loop"
echo "$OUT" | grep -q 'git merge --ff-only' \
  && ok "the page carries the fix command" \
  || bad "the page does not say what to do"

echo
echo "== 3. ahead: local commits not yet pushed -> RUN (must not wedge) =="
( cd "$CLONE"; git merge -q --ff-only origin/main; echo three >> f.txt; git commit -qam three ) >/dev/null 2>&1
OUT="$(run_check "$CLONE")"
echo "$OUT" | grep -q 'VERDICT=RUN' \
  && ok "a checkout AHEAD of origin/main still runs" \
  || bad "being ahead was treated as stale, which wedges the loop on its own unpushed work"

echo
echo "== 4. no answer: fetch fails -> RUN (fail open on not knowing) =="
# A repo with no reachable remote is the offline case without needing the network.
BROKEN="$WORK/broken"
git init -q -b main "$BROKEN"
( cd "$BROKEN"; git config user.email t@e.com; git config user.name t
  echo x > f.txt; git add -A; git commit -qm x
  git remote add origin "$WORK/does-not-exist.git" ) >/dev/null 2>&1
OUT="$(run_check "$BROKEN")"
if echo "$OUT" | grep -q 'VERDICT=RUN'; then
  ok "an unanswerable freshness check proceeds instead of wedging"
else
  bad "a failed fetch refused to dispatch, so an offline machine kills the loop"
fi
echo "$OUT" | grep -q 'SAY stale-check' \
  && ok "the unanswered check is logged, not silent" \
  || bad "the check failed with no log line, so the blind spot is invisible"

echo
echo "== 5. DIVERGED must REFUSE (codex round 2, major 1) =="
# The case the first cut got wrong, and the one a merge of this very branch
# produces: origin/main gains a commit while this tree keeps local commits of its
# own. --is-ancestor is FALSE here, so an ancestry test runs on a checkout missing
# origin/main's newest control code. This is the LIKELY divergence, not an edge.
DIV="$WORK/diverged"
git clone -q "$ORIGIN" "$DIV" >/dev/null 2>&1
( cd "$DIV"; git config user.email t@e.com; git config user.name t
  echo local-only >> f.txt; git commit -qam "local only" ) >/dev/null 2>&1
( cd "$WORK/seed"; echo remote-only >> f.txt; git commit -qam "remote only"; git push -q origin main ) >/dev/null 2>&1
OUT="$(run_check "$DIV")"
if echo "$OUT" | grep -q 'VERDICT=REFUSE'; then
  ok "a DIVERGED checkout refuses (origin/main holds commits it lacks)"
else
  bad "THE DEFECT: a diverged checkout dispatched, so superseded control code runs after a concurrent merge"
fi

echo
echo "== 6. the page is deduped per remote sha (codex round 2, major 2) =="
# At a 900s interval an unrepaired checkout paged 96 times a day with the
# identical message, which trains the founder to ignore the channel.
STATE="$WORK/pagestate"; mkdir -p "$STATE"
# Point the function's state dir at a scratch dir by overriding $LOG, which is
# what the marker path is derived from.
run_dedupe() { ( cd "$1" && LOG="$STATE/dispatch.log" bash "$HARNESS" 2>&1 ); }
P1="$(run_dedupe "$DIV" | grep -c '^PAGE ' || true)"
P2="$(run_dedupe "$DIV" | grep -c '^PAGE ' || true)"
if [ "${P1:-0}" -ge 1 ] && [ "${P2:-0}" -eq 0 ]; then
  ok "pages once for a given origin/main sha, silent on the repeat ($P1 then $P2)"
else
  bad "THE DEFECT: paged $P1 then $P2 for the same remote sha -- 96 identical pages a day"
fi
# A NEW divergence must page again, or a second, different staleness goes unreported.
( cd "$WORK/seed"; echo remote-two >> f.txt; git commit -qam "remote two"; git push -q origin main ) >/dev/null 2>&1
P3="$(run_dedupe "$DIV" | grep -c '^PAGE ' || true)"
if [ "${P3:-0}" -ge 1 ]; then
  ok "a NEW origin/main sha pages again (dedupe is per-sha, not permanent)"
else
  bad "dedupe is permanent: a second, different divergence would never be reported"
fi
# The refusal itself must still be logged every time, even when the page is muted.
echo "$(run_dedupe "$DIV")" | grep -q 'SAY REFUSING' \
  && ok "the refusal is logged on every heartbeat even when the page is deduped" \
  || bad "a deduped page also silenced the log line, so the refusal is invisible"

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: stale_check refuses whenever origin/main holds commits this tree lacks, and pages once per sha"
