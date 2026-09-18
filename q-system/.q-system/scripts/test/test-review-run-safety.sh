#!/usr/bin/env bash
# Reviewer run safety: the verdict survives a kill, a judged head is not
# re-reviewed, a third concurrent run is refused, and two rounds on one file say
# so out loud. sp-fa810306, sp-0a09e013, sp-46726f79.
#
# THE THREE SCARS, all measured on 2026-09-05 to 2026-09-07:
#
#   sp-fa810306  PR #314 round 3 posted APPROVE WITH NITS as a comment at
#                00:29:47Z on head adc29516, the process died before the commit
#                status call, `gh api statuses adc29516` came back empty, and the
#                next session re-ran the same head at 00:36:54Z. The re-run
#                returned REQUEST CHANGES and overturned the approval.
#   sp-0a09e013  five reviewers and watchers killed under memory pressure in one
#                evening, then a 00:35Z process exit orphaned two more. Nothing on
#                the box could answer how many reviews were live.
#   sp-46726f79  rounds 1 to 3 of PR #314 each named another unwaited index write.
#                Three patches, one class. The round cap came from the founder.
#
# HOW THIS DRIVES THE REAL SCRIPT. Same harness as
# test-review-dry-run-labelled.sh: the SHIPPING pr-review-agent.sh is copied into
# a fixture repo three levels down so its own root guard passes, and it runs
# against a `gh` stub, a fake engine, and a HOME under mktemp. No live PR is read,
# no model is spent, no commit status is posted anywhere real.
#
# EVERY REFUSAL CASE NAMES ITS RED-MAKING INPUT, because a check that cannot fail
# for the reason you care about is decoration (lessons:
# a-check-must-be-able-to-fail-for-the-reason-you-care-abou). Each one was run
# against the pre-fix script first and recorded RED; the comments say so per case.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SRC_DIR="$ROOT/q-system/.q-system/scripts"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$SRC_DIR/pr-review-agent.sh" ] || fail "pr-review-agent.sh missing at $SRC_DIR"
REAL_GIT="$(command -v git)" || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_TARGET_REPO KIPI_REVIEW_ENGINE KIPI_REVIEW_CONCURRENCY_CAP KIPI_REVIEW_QUEUE_SECONDS 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB"

# --- the repo under review, with the control code exactly 3 levels down --------
mkdir -p "$WORK/skel/q-system/.q-system/scripts"
git init -q "$WORK/skel"
echo "code" > "$WORK/skel/FILE.txt"
cp "$SRC_DIR/pr-review-agent.sh" "$SRC_DIR/pr-verdict-lib.sh" "$SRC_DIR/repo-slug-lib.sh" \
   "$WORK/skel/q-system/.q-system/scripts/"
G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "control code"
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "https://github.com/assafkip/homerepo.git"
AGENT="$WORK/skel/q-system/.q-system/scripts/pr-review-agent.sh"
SHA="$(git -C "$WORK/skel" rev-parse HEAD)"

# --- fake gh ------------------------------------------------------------------
# Appends every invocation to an ORDERED log, which is what makes "the status was
# posted before the comment" a measurable fact rather than a reading of the code.
# COMMENTS_FILE lets a case seed the PR's existing comments; absent means none.
GH_LOG="$WORK/gh-calls.txt"; : > "$GH_LOG"
COMMENTS_FILE="$WORK/pr-comments.txt"; : > "$COMMENTS_FILE"
# THE STUB APPENDS EVERY POSTED BODY TO COMMENTS_FILE, so the head marker really
# round-trips writer to reader: what the reviewer writes into a comment is what
# the next run reads back. A hand-seeded marker only tests the reader's parser;
# this tests that the two halves agree about the string.
cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$GH_LOG"
case "\$*" in
  *"pr view"*"headRefOid"*) printf '%s\t%s\n' "$SHA" "a PR title" ;;
  *"pr view"*"comments"*)   cat "$COMMENTS_FILE" ;;
  *"pr diff"*)              echo "diff --git a/FILE.txt b/FILE.txt" ;;
  *"pr comment"*)
    bf=""; prev=""
    for a in "\$@"; do [ "\$prev" = "--body-file" ] && bf="\$a"; prev="\$a"; done
    [ -n "\$bf" ] && [ -f "\$bf" ] && cat "\$bf" >> "$COMMENTS_FILE"
    echo "https://github.com/assafkip/homerepo/pull/1#issuecomment-1" ;;
  *"api"*)                  echo '{}' ;;
esac
exit 0
EOF
chmod +x "$STUB/gh"

# --- fake engine --------------------------------------------------------------
# ENGINE_OUT holds whatever review the current case wants the engine to produce,
# so one stub serves every case and the cases differ only in their review text.
ENGINE_OUT="$WORK/engine-out.md"
cat > "$STUB/codex" <<EOF
#!/usr/bin/env bash
cat "$ENGINE_OUT"
exit 0
EOF
chmod +x "$STUB/codex"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/claude"; chmod +x "$STUB/claude"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub"

set_review() {  # set_review <verdict> <severity|claim|file:line>...
  local verdict="$1"; shift
  { printf 'VERDICT: %s\n' "$verdict"
    printf 'FINDINGS:\n'
    local row; for row in "$@"; do printf '%s\n' "$row"; done
    printf 'END FINDINGS\n'; } > "$ENGINE_OUT"
}

run_reviewer() {  # run_reviewer <out-file> <home-tag> [extra args...]
  local out="$1" tag="$2"; shift 2
  ( cd "$WORK/skel" \
    && HOME="$WORK/home-$tag" KIPI_STATE_DIR="$WORK/state-$tag" KIPI_NOTIFY="/usr/bin/true" \
       bash "$AGENT" 1 --engine codex "$@" ) >"$out" 2>&1
  return $?
}

# ===========================================================================
# CASE 0 -- NEGATIVE SELF-TESTS for the instruments themselves.
#
# Every assertion below reads the gh log for an ORDER or an ABSENCE. If the log
# cannot record an order, "status came first" is vacuous; if it cannot record a
# call at all, "nothing was posted" is vacuous. Both are proven here first.
# ===========================================================================
( cd "$WORK/skel" && gh api -X POST "repos/assafkip/homerepo/statuses/$SHA" -f state=success >/dev/null 2>&1 )
( cd "$WORK/skel" && gh pr comment 1 --body-file /dev/null >/dev/null 2>&1 )
grep -q "statuses/$SHA" "$GH_LOG" \
  || fail "negative self-test: a real status POST was not recorded in the gh log"
grep -q "pr comment" "$GH_LOG" \
  || fail "negative self-test: a real pr comment was not recorded in the gh log"
FIRST_LINE="$(grep -n "statuses/$SHA" "$GH_LOG" | head -1 | cut -d: -f1)"
SECOND_LINE="$(grep -n "pr comment" "$GH_LOG" | head -1 | cut -d: -f1)"
[ "$FIRST_LINE" -lt "$SECOND_LINE" ] \
  || fail "negative self-test: the log did not preserve the order the two calls were made in; every ordering assertion below would be meaningless"
ok "negative self-test: the gh log records both call kinds and preserves their order"
: > "$GH_LOG"

# ===========================================================================
# CASE 1 -- sp-fa810306: the commit status is posted BEFORE the PR comment.
#
# RED-MAKING INPUT, run before the fix: the pre-fix script, whose POST block
# commented first and then called post_reviewer_status with the comment URL. Run
# against that script this case reported "pr comment at line 3, status at line 4"
# and exited 1 here.
# ===========================================================================
set_review "APPROVE WITH NITS" "nit|trailing whitespace|FILE.txt:1"
: > "$COMMENTS_FILE"
: > "$GH_LOG"
run_reviewer "$WORK/order.out" order --post
RC_ORDER=$?

STATUS_AT="$(grep -n "statuses/$SHA" "$GH_LOG" | head -1 | cut -d: -f1)"
COMMENT_AT="$(grep -n "pr comment" "$GH_LOG" | head -1 | cut -d: -f1)"
echo "  [ctx] --post run rc=$RC_ORDER  first status at line ${STATUS_AT:-<none>}  first comment at line ${COMMENT_AT:-<none>}"

[ -n "$STATUS_AT" ] \
  || fail "the --post run posted NO commit status at all:
$(sed 's/^/        /' "$GH_LOG")
$(tail -20 "$WORK/order.out")"
[ -n "$COMMENT_AT" ] \
  || fail "the --post run posted NO comment, so there is no ordering to check:
$(sed 's/^/        /' "$GH_LOG")"
ok "precondition: the --post run posted both a commit status and a comment"

[ "$STATUS_AT" -lt "$COMMENT_AT" ] \
  || fail "THE COMMENT WENT FIRST (status line $STATUS_AT, comment line $COMMENT_AT). A kill between the two loses the verdict and keeps the prose, which is exactly what cost PR #314 an earned approval on 2026-09-07:
$(sed 's/^/        /' "$GH_LOG")"
ok "the commit status is posted BEFORE the PR comment"

# CASE 1b -- the link is still attached, so ordering did not cost the target_url.
grep "statuses/$SHA" "$GH_LOG" | grep -q "target_url" \
  || fail "no status call carries a target_url; posting first must not lose the link to the comment:
$(sed 's/^/        /' "$GH_LOG")"
ok "a later status post attaches target_url, so the link survives the reordering"

# The marker the duplicate guard reads has to actually be in what was posted.
grep -q -- "kipi-reviewer: head=$SHA" "$WORK/order.out" \
  || echo "  [ctx] marker not echoed to stdout (it is in the body file, not the log)"

# ===========================================================================
# CASE 2 -- sp-fa810306: a head that already carries a verdict comment refuses.
#
# RED-MAKING INPUT, run before the fix: the pre-fix script with the same seeded
# comment exited 0 and dispatched a full review.
# ===========================================================================
printf '<!-- kipi-reviewer: head=%s -->\n## Verdict: APPROVE WITH NITS\n' "$SHA" > "$COMMENTS_FILE"
: > "$GH_LOG"
run_reviewer "$WORK/dup.out" dup --post
RC_DUP=$?
echo "  [ctx] duplicate-head run rc=$RC_DUP"

[ "$RC_DUP" = "3" ] \
  || fail "a head that already carries a verdict comment was re-reviewed (rc=$RC_DUP, expected 3):
$(tail -20 "$WORK/dup.out")"
ok "a head already carrying a verdict comment refuses with exit 3"

grep -q "statuses/$SHA" "$GH_LOG" \
  && fail "the refused run still posted a commit status; a refusal must move no gate:
$(sed 's/^/        /' "$GH_LOG")"
ok "the refused run posted no commit status"

# CASE 2b -- the bypass is EXERCISED, not merely documented. Without this the
# refusal could be unconditional and this suite would not notice.
: > "$GH_LOG"
run_reviewer "$WORK/dupforce.out" dupforce --post --force
RC_FORCE=$?
echo "  [ctx] --force run rc=$RC_FORCE"
[ "$RC_FORCE" != "3" ] \
  || fail "--force did not bypass the duplicate-head refusal (rc=$RC_FORCE):
$(tail -20 "$WORK/dupforce.out")"
grep -q "statuses/$SHA" "$GH_LOG" \
  || fail "--force returned $RC_FORCE but posted no status, so it did not actually run the review"
ok "--force runs the review anyway and posts a status"

# CASE 2c -- the refusal is not universal: no marker, no refusal.
: > "$COMMENTS_FILE"
printf 'just a human comment about %s\n' "$SHA" > "$COMMENTS_FILE"
: > "$GH_LOG"
run_reviewer "$WORK/nodup.out" nodup --post
RC_NODUP=$?
echo "  [ctx] head-mentioned-but-no-marker run rc=$RC_NODUP"
[ "$RC_NODUP" != "3" ] \
  || fail "a comment that merely MENTIONS the sha triggered the duplicate refusal (rc=3). The guard must key on the reviewer's own marker, not on the sha appearing in prose:
$(tail -20 "$WORK/nodup.out")"
ok "a non-verdict comment naming the sha does not trigger the refusal"

# ===========================================================================
# CASE 3 -- sp-0a09e013: two live pid files refuse a third run.
#
# RED-MAKING INPUT, run before the fix: the pre-fix script with the same two live
# pid files exited 0 and ran a third concurrent review.
#
# THE LIVE PIDS ARE REAL PROCESSES. Writing $$ into both files would make them
# the same pid as nothing, and a fabricated number could be reused by anything on
# the box; two backgrounded sleeps are pids the OS genuinely reports as alive.
# ===========================================================================
: > "$COMMENTS_FILE"
PIDDIR="$WORK/home-conc/.config/kipi/review-trees"; mkdir -p "$PIDDIR"
# NOT THIS PR'S OWN FILE. pr-7 and pr-8 are OTHER PRs, so this case measures the
# numeric cap. The same-PR collision is its own case further down, because the cap
# cannot express it: one incumbent on this PR is under the cap and still fatal.
sleep 120 & LIVE1=$!
sleep 120 & LIVE2=$!
printf '%s' "$LIVE1" > "$PIDDIR/assafkip_homerepo__pr-7.pid"
printf '%s' "$LIVE2" > "$PIDDIR/assafkip_homerepo__pr-8.pid"
: > "$GH_LOG"
run_reviewer "$WORK/conc.out" conc --post
RC_CONC=$?
echo "  [ctx] two-live-pids run rc=$RC_CONC (live pids $LIVE1 $LIVE2)"

[ "$RC_CONC" = "3" ] \
  || fail "a third concurrent review started while two were live (rc=$RC_CONC, expected 3):
$(tail -20 "$WORK/conc.out")"
ok "two live pid files refuse a third run with exit 3"
grep -q "statuses/$SHA" "$GH_LOG" \
  && fail "the concurrency-refused run still posted a commit status"
ok "the concurrency-refused run posted no commit status"

# ===========================================================================
# CASE 4 -- sp-0a09e013: a stale pid file is reclaimed and the run proceeds.
#
# THE PID IS GENUINELY DEAD, not invented: the two sleeps above are killed and
# reaped first, so `kill -0` reports gone for a number that really was a process.
# ===========================================================================
kill "$LIVE1" "$LIVE2" 2>/dev/null || true
wait "$LIVE1" 2>/dev/null || true
wait "$LIVE2" 2>/dev/null || true
[ -f "$PIDDIR/assafkip_homerepo__pr-7.pid" ] \
  || fail "precondition: the stale pid file vanished before the run that is supposed to reclaim it"
: > "$GH_LOG"
run_reviewer "$WORK/stale.out" conc --post
RC_STALE=$?
echo "  [ctx] stale-pids run rc=$RC_STALE"

[ "$RC_STALE" != "3" ] \
  || fail "a run was refused by pid files whose processes are dead (rc=3). A stale file must be reclaimed, or one killed reviewer wedges the loop forever:
$(tail -20 "$WORK/stale.out")"
ok "a run with only stale pid files is not refused"
[ -f "$PIDDIR/assafkip_homerepo__pr-7.pid" ] \
  && fail "the stale pid file was left on disk; nothing else ever runs to clean it up"
ok "the stale pid file was removed"
grep -q "statuses/$SHA" "$GH_LOG" \
  || fail "the stale-pid run exited $RC_STALE but posted no status, so it did not actually review"
ok "the stale-pid run really did review and post"

# ===========================================================================
# CASE 5 -- sp-46726f79: two consecutive REQUEST CHANGES rounds sharing a file
# print STRUCTURAL, put it in the comment, and exit 4.
#
# RED-MAKING INPUT, run before the fix: the pre-fix script produced two REQUEST
# CHANGES rounds on FILE.txt, printed no STRUCTURAL line, and exited 0.
#
# THE POST IS NOT BLOCKED, and that half is asserted too: a warning that costs
# the review its comment would be a worse trade than the loop it warns about.
# ===========================================================================
# CLEARED BETWEEN ROUNDS, and the reason is a fixture limit worth naming. This
# repo has one commit, so both "rounds" run against the SAME head sha -- while a
# real round 2 reviews a new head the author just pushed. Left uncleared, round 2
# would hit the duplicate-head refusal (correctly), and this case would measure
# that guard instead of the structural one.
: > "$COMMENTS_FILE"
set_review "REQUEST CHANGES" "major|first unwaited write|FILE.txt:10"
: > "$GH_LOG"
run_reviewer "$WORK/rc1.out" struct --post
RC_R1=$?
echo "  [ctx] structural round 1 rc=$RC_R1"
[ "$RC_R1" = "0" ] \
  || fail "the FIRST REQUEST CHANGES round exited $RC_R1; with no earlier round there is nothing structural to report:
$(tail -20 "$WORK/rc1.out")"
ok "a single REQUEST CHANGES round exits 0 (nothing to compare against yet)"

set_review "REQUEST CHANGES" "major|second unwaited write in the same file|FILE.txt:42"
: > "$GH_LOG"
: > "$COMMENTS_FILE"   # see the note above round 1: one fixture sha serves both rounds
run_reviewer "$WORK/rc2.out" struct --post
RC_R2=$?
echo "  [ctx] structural round 2 rc=$RC_R2"

grep -q "^  STRUCTURAL: " "$WORK/rc2.out" \
  || fail "two REQUEST CHANGES rounds both citing FILE.txt produced no STRUCTURAL line:
$(tail -25 "$WORK/rc2.out")"
ok "two rounds sharing a file print a STRUCTURAL line"

grep "^  STRUCTURAL: " "$WORK/rc2.out" | grep -q "FILE.txt" \
  || fail "the STRUCTURAL line does not name the shared file:
$(grep '^  STRUCTURAL: ' "$WORK/rc2.out")"
ok "the STRUCTURAL line names the shared file"

grep "^  STRUCTURAL: " "$WORK/rc2.out" | grep -qE "round [0-9]+ and round [0-9]+" \
  || fail "the STRUCTURAL line does not name the two rounds:
$(grep '^  STRUCTURAL: ' "$WORK/rc2.out")"
ok "the STRUCTURAL line names both rounds"

[ "$RC_R2" = "4" ] \
  || fail "the structural round exited $RC_R2, expected 4 so a queue script can stop:
$(tail -20 "$WORK/rc2.out")"
ok "the structural round exits 4"

grep -q "pr comment" "$GH_LOG" \
  || fail "the structural round did not post its comment; the warning must never cost the review its post:
$(sed 's/^/        /' "$GH_LOG")"
ok "the structural round still posted its PR comment"
grep -q "statuses/$SHA" "$GH_LOG" \
  || fail "the structural round posted no commit status"
ok "the structural round still posted its commit status"

# ===========================================================================
# CASE 6 -- sp-46726f79: disjoint files do NOT produce a STRUCTURAL line.
#
# Without this the fix could be "print STRUCTURAL on every second REQUEST CHANGES
# round", which is a warning that fires always and therefore says nothing.
# ===========================================================================
set_review "REQUEST CHANGES" "major|a different defect elsewhere|OTHER.txt:3"
: > "$GH_LOG"
: > "$COMMENTS_FILE"
run_reviewer "$WORK/rc3.out" disjoint --post
RC_D1=$?
set_review "REQUEST CHANGES" "major|another different defect|THIRD.txt:9"
: > "$GH_LOG"
: > "$COMMENTS_FILE"
run_reviewer "$WORK/rc4.out" disjoint --post
RC_D2=$?
echo "  [ctx] disjoint rounds rc=$RC_D1 then rc=$RC_D2"

grep -q "^  STRUCTURAL: " "$WORK/rc4.out" \
  && fail "two REQUEST CHANGES rounds citing DIFFERENT files produced a STRUCTURAL line. A warning that fires on every repeat round trains the reader to ignore it:
$(grep '^  STRUCTURAL: ' "$WORK/rc4.out")"
ok "two rounds on different files print no STRUCTURAL line"

[ "$RC_D2" = "0" ] \
  || fail "the disjoint second round exited $RC_D2, expected 0:
$(tail -20 "$WORK/rc4.out")"
ok "the disjoint second round exits 0"

# ===========================================================================
# CASE 7 -- the same-PR collision the numeric cap cannot see (round 1 major).
#
# THE DEFECT the first cut shipped: _live_review_pids skipped the scan entry
# whose PATH equalled our own pid file. Two runs on ONE PR write that same path,
# so the one collision that matters most was the one collision the scan was blind
# to -- and the second run then overwrote the incumbent's pid, silently taking
# over its slot while both read and re-checked-out the same detached worktree.
#
# RED-MAKING INPUT: one live pid file for THIS PR (assafkip_homerepo__pr-1) and
# nothing else. Against the path-skipping version the run exits 0 and reviews.
# The numeric cap cannot catch it: one incumbent is under a cap of two.
# ===========================================================================
: > "$COMMENTS_FILE"
PIDDIR2="$WORK/home-samepr/.config/kipi/review-trees"; mkdir -p "$PIDDIR2"
sleep 120 & SAME_PR_LIVE=$!
printf '%s' "$SAME_PR_LIVE" > "$PIDDIR2/assafkip_homerepo__pr-1.pid"
: > "$GH_LOG"
run_reviewer "$WORK/samepr.out" samepr --post
RC_SAMEPR=$?
echo "  [ctx] same-PR incumbent run rc=$RC_SAMEPR (live pid $SAME_PR_LIVE)"

[ "$RC_SAMEPR" = "3" ] \
  || fail "a second review of PR #1 started while one was already live (rc=$RC_SAMEPR, expected 3). Both share one detached worktree and one pid file, so the second re-checkouts the tree under the first:
$(tail -20 "$WORK/samepr.out")"
ok "a live run on the SAME PR refuses a second run with exit 3, below the numeric cap"

grep -q "statuses/$SHA" "$GH_LOG" \
  && fail "the same-PR refusal still posted a commit status"
ok "the same-PR refusal posted no commit status"

# The incumbent's pid file must survive untouched. A refusal that clears the
# file it refused on would hand the slot to the next arrival and defeat itself.
[ "$(cat "$PIDDIR2/assafkip_homerepo__pr-1.pid" 2>/dev/null)" = "$SAME_PR_LIVE" ] \
  || fail "the refused run overwrote or removed the incumbent's pid file; the slot was taken over by the run that was supposed to back off"
ok "the incumbent's pid file is left exactly as it was"

kill "$SAME_PR_LIVE" 2>/dev/null || true
wait "$SAME_PR_LIVE" 2>/dev/null || true

# ===========================================================================
# CASE 8 -- an UNUSABLE review must not claim the head (round 1 major).
#
# THE DEFECT the first cut shipped: the head marker went into EVERY posted
# comment. An unusable review posts state=failure and states no verdict, so that
# head then carried a red required check AND a marker that made every later
# automated re-review exit 3. Nothing unattended could clear it, because --force
# is a flag a human types. The guard exists to protect an EARNED verdict; a
# review nobody could read earned nothing.
#
# RED-MAKING INPUT: an engine stream with an unclosed FINDINGS block (exactly
# what review_is_usable refuses), followed by a second run on the same head.
# Against the first cut the second run exits 3. It must proceed.
# ===========================================================================
: > "$COMMENTS_FILE"
printf 'VERDICT: APPROVE\nFINDINGS:\n' > "$ENGINE_OUT"   # never closed: unusable
: > "$GH_LOG"
run_reviewer "$WORK/unusable1.out" unusable --post
RC_U1=$?
echo "  [ctx] unusable review rc=$RC_U1"

grep -q "pr comment" "$GH_LOG" \
  || fail "the unusable review posted no comment at all, so this case cannot test what the comment carried:
$(sed 's/^/        /' "$GH_LOG")"
ok "precondition: the unusable review still posted its comment"

grep -q -- "kipi-reviewer: head=$SHA" "$COMMENTS_FILE" \
  && fail "an UNUSABLE review stamped the head marker. That head now carries a failing required status AND a marker that makes every automated re-review exit 3 -- a wedge no unattended run can clear:
$(head -3 "$COMMENTS_FILE")"
ok "an unusable review posts NO head marker"

: > "$GH_LOG"
run_reviewer "$WORK/unusable2.out" unusable2 --post
RC_U2=$?
echo "  [ctx] re-review after an unusable round rc=$RC_U2"
[ "$RC_U2" != "3" ] \
  || fail "a head whose only review was UNUSABLE refused a re-review (rc=3). Nothing unattended could ever clear that PR:
$(tail -20 "$WORK/unusable2.out")"
ok "a head whose only review was unusable can still be re-reviewed"

# THE POSITIVE CONTROL for the same mechanism, and it is what makes case 8
# non-vacuous: without it, "never stamp the marker" would pass this suite. A
# USABLE review must stamp it, and the next run must then refuse.
: > "$COMMENTS_FILE"
set_review "APPROVE WITH NITS" "nit|trailing whitespace|FILE.txt:1"
: > "$GH_LOG"
run_reviewer "$WORK/roundtrip1.out" roundtrip --post
grep -q -- "kipi-reviewer: head=$SHA" "$COMMENTS_FILE" \
  || fail "a USABLE approving review did not stamp the head marker, so the duplicate guard is disarmed on exactly the verdicts it exists to protect:
$(head -3 "$COMMENTS_FILE")"
ok "a usable review DOES stamp the head marker"

: > "$GH_LOG"
run_reviewer "$WORK/roundtrip2.out" roundtrip2 --post
RC_RT2=$?
echo "  [ctx] re-review after a usable round rc=$RC_RT2"
[ "$RC_RT2" = "3" ] \
  || fail "the marker written by a real run did not make the next run refuse (rc=$RC_RT2). The writer and the reader disagree about the string:
$(tail -20 "$WORK/roundtrip2.out")"
ok "the marker round-trips: a real run's comment refuses the next run on that head"

echo "PASS ($PASS checks) test-review-run-safety.sh"
