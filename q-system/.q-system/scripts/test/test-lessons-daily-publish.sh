#!/bin/bash
# Pins that lessons-daily.sh lands lessons on main through a PR and can never
# strand them on whatever branch the skeleton checkout happens to be on (ASK-2736).
#
# THE SCAR. From 2026-09-07 to 2026-10-19 the live skeleton checkout sat on a
# feature branch. Every weekly run committed its lessons onto that branch and
# then kipi-update.sh refused to fan them out, because the checkout was not at
# origin/main. Six runs, 29 lessons, three commits that never left the machine,
# and the weekly alert only ever said "propagate FAILED".
#
# The fixture reproduces that state: a real bare origin with main, and a
# skeleton clone parked on a stale feature branch carrying a local commit. The
# distiller, gh, the reviewer, the fan-out, Notion and Slack are stubs; git is
# real, so "pushed" and "on main's history" are measured, not assumed.
#
#   1. the lesson reaches origin on an auto/lessons-* branch built on main;
#   2. the skeleton's own branch gets no commit and no stray lesson file;
#   3. a PR to main is opened, auto-merge is armed, the reviewer is run;
#   4. the run exits 0 and removes its worktree;
#   5. negative control: a failed PR create exits non-zero, says so, and keeps
#      the worktree; the pushed branch still holds the lesson;
#   6. negative control: a failed push exits non-zero and keeps the worktree
#      with the commit in it, named in the alert;
#   7. negative control: last week's lessons PR still open stops the run before
#      it distills, so the same sources cannot publish twice.
#
# Never touches the live repo, log, Slack, Linear, GitHub or the fleet.

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR \
      GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_PREFIX

SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$SCRIPTS/lessons-daily.sh"
PASS=0
FAIL=0
ok()  { echo "PASS  $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL  $1"; FAIL=$((FAIL + 1)); }

g() { git -c user.email=t@example.com -c user.name=t -c commit.gpgsign=false "$@"; }

# build_fixture <gh-mode: ok|fail-create> -> echoes the temp root
build_fixture() {
  local mode="$1" tmp
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/bin" "$tmp/seed/q-system/lessons" "$tmp/seed/lesson-candidates"
  printf 'keep\n' > "$tmp/seed/q-system/lessons/existing-lesson.md"
  printf '{"seenkey": {"status": "published"}}\n' > "$tmp/seed/lesson-candidates/.processed.json"
  g init -q -b main "$tmp/seed"
  g -C "$tmp/seed" add -A && g -C "$tmp/seed" commit -qm "seed [no-issue: fixture]"
  g clone -q --bare "$tmp/seed" "$tmp/origin.git"
  g clone -q "$tmp/origin.git" "$tmp/skel"
  # The live state: the checkout is on a feature branch with a local commit.
  g -C "$tmp/skel" switch -q -c feature/stale
  printf 'wip\n' > "$tmp/skel/wip.txt"
  g -C "$tmp/skel" add wip.txt && g -C "$tmp/skel" commit -qm "wip [no-issue: fixture]"
  g -C "$tmp/skel" config user.email t@example.com
  g -C "$tmp/skel" config user.name t
  g -C "$tmp/skel" config commit.gpgsign false
  # Hooks run in the worktree too, through the shared config.
  mkdir -p "$tmp/hooks"
  printf '#!/bin/bash\ntouch "%s/pre-commit.ran"\nexit 0\n' "$tmp" > "$tmp/hooks/pre-commit"
  chmod +x "$tmp/hooks/pre-commit"
  g -C "$tmp/skel" config core.hooksPath "$tmp/hooks"

  mkdir -p "$tmp/skel/q-system/.q-system/scripts"
  cp "$SUT" "$tmp/skel/q-system/.q-system/scripts/lessons-daily.sh"
  # The real streak helper; LESSONS_DIR unset (the pre-fix script) falls back
  # to the checkout's own lessons dir, which is the distiller's real default.
  cp "$SCRIPTS/lessons_streak.py" "$tmp/skel/q-system/.q-system/scripts/lessons_streak.py"
  printf '#!/bin/bash\nexit 0\n' > "$tmp/skel/q-system/.q-system/scripts/install-plist.sh"
  printf '#!/bin/bash\nexit 0\n' > "$tmp/bin/claude"
  # gh: records argv; `pr create` prints a PR URL unless told to fail.
  cat > "$tmp/bin/gh" <<GH
#!/bin/bash
echo "\$*" >> "$tmp/gh.calls"
case "\$1 \$2" in
  "pr create") [ "$mode" = "fail-create" ] && { echo "gh: create refused" >&2; exit 1; }
               echo "https://github.com/fixture/repo/pull/77" ;;
  "pr list")   [ "$mode" = "open-pr" ] && echo "https://github.com/fixture/repo/pull/76" ;;
esac
exit 0
GH
  chmod +x "$tmp/bin/claude" "$tmp/bin/gh" "$tmp/skel/q-system/.q-system/scripts/install-plist.sh"
  printf '%s' "$tmp"
}

PUBLISHED='{"scanned": 1, "published": ["a fixture lesson"], "held": []}'
# run_job <tmp>; sets JOB_RC. The distill stub writes where the job tells it to.
run_job() {
  local tmp="$1"
  printf '%s' "$PUBLISHED" > "$tmp/summary.json"
  PATH="$tmp/bin:$PATH" \
  KIPI_DISTILL_CMD="printf '# a fixture lesson\n' > \"\${LESSONS_DIR:-$tmp/skel/q-system/lessons}/fixture-lesson.md\"; cat '$tmp/summary.json'" \
  KIPI_REVIEW_CMD="echo \"\$PR_NUMBER\" >> '$tmp/review.calls'" \
  KIPI_PROPAGATE_CMD="touch '$tmp/propagated'" \
  KIPI_NOTION_SYNC_CMD="true" \
  KIPI_NOTIFY_CMD="printf '%s\\n' \"\$1\" >> '$tmp/notify.txt'" \
  KIPI_LESSONS_LOG="$tmp/lessons-daily.log" \
  KIPI_LESSONS_WT_ROOT="$tmp/state" \
  KIPI_STREAK_FILE="$tmp/streak.json" KIPI_ESCALATIONS_FILE="$tmp/esc.jsonl" \
    bash "$tmp/skel/q-system/.q-system/scripts/lessons-daily.sh" >/dev/null 2>&1
  JOB_RC=$?
}

auto_branch() { g -C "$1/origin.git" for-each-ref --format='%(refname:short)' 'refs/heads/auto/lessons-*' | head -1; }
worktrees_left() { find "$1/state" -maxdepth 1 -name 'wt-*' -type d 2>/dev/null | wc -l | tr -d ' '; }

# --- 1-4. the happy path ---------------------------------------------------
T="$(build_fixture ok)"
SKEL_HEAD_BEFORE="$(g -C "$T/skel" rev-parse HEAD)"
run_job "$T"
BR="$(auto_branch "$T")"
echo "      fixture: $T (exit=$JOB_RC, branch=${BR:-none})"
if [ -n "$BR" ] && g -C "$T/origin.git" cat-file -e "$BR:q-system/lessons/fixture-lesson.md" 2>/dev/null; then
  ok "the lesson reached origin on $BR"
else
  bad "the lesson never reached origin; log: $(tail -3 "$T/lessons-daily.log" 2>/dev/null | tr '\n' ' ')"
fi
if [ -n "$BR" ] && g -C "$T/origin.git" merge-base --is-ancestor main "$BR" 2>/dev/null \
   && ! g -C "$T/origin.git" cat-file -e "$BR:wip.txt" 2>/dev/null; then
  ok "the lesson branch is built on main, not on the checkout's feature branch"
else
  bad "the lesson branch is not a clean child of main"
fi
[ "$(g -C "$T/skel" rev-parse HEAD)" = "$SKEL_HEAD_BEFORE" ] \
  && ok "the skeleton's feature branch got no commit" \
  || bad "a lesson commit landed on the skeleton's feature branch (the stranding)"
[ ! -e "$T/skel/q-system/lessons/fixture-lesson.md" ] \
  && ok "no lesson file was left in the skeleton checkout" \
  || bad "a lesson file was written into the skeleton checkout"
grep -q -- "pr create --base main --head $BR" "$T/gh.calls" 2>/dev/null \
  && ok "a PR to main was opened" || bad "no PR to main was opened"
grep -q -- "pr merge .*--auto --squash" "$T/gh.calls" 2>/dev/null \
  && ok "auto-merge was armed" || bad "auto-merge was not armed"
grep -qx "77" "$T/review.calls" 2>/dev/null \
  && ok "the reviewer was run on the PR" || bad "the reviewer was never run"
[ -e "$T/pre-commit.ran" ] && ok "the commit went through the repo's hooks" \
                           || bad "the commit skipped the repo's hooks"
[ "$JOB_RC" -eq 0 ] && ok "a published run exits 0" || bad "a published run exits $JOB_RC"
[ "$(worktrees_left "$T")" = "0" ] && ok "the worktree was removed" \
                                   || bad "the worktree was left behind"
rm -rf "$T"

# --- 5. negative control: PR create fails ----------------------------------
T="$(build_fixture fail-create)"
run_job "$T"
BR="$(auto_branch "$T")"
echo "      fixture (fail-create): $T (exit=$JOB_RC, branch=${BR:-none})"
[ "$JOB_RC" -ne 0 ] && ok "fail-create: job exits non-zero" || bad "fail-create: job exits 0"
grep -q 'publish FAILED' "$T/notify.txt" 2>/dev/null \
  && ok "fail-create: the alert says the publish failed" \
  || bad "fail-create: the alert is silent about the publish"
[ -n "$BR" ] && ok "fail-create: the lesson is still safe on origin ($BR)" \
             || bad "fail-create: the lesson was not pushed"
[ "$(worktrees_left "$T")" = "1" ] && ok "fail-create: the worktree is kept for recovery" \
                                   || bad "fail-create: the worktree was removed"
rm -rf "$T"

# --- 6. negative control: push fails ---------------------------------------
T="$(build_fixture ok)"
g -C "$T/skel" remote set-url --push origin "$T/no-such-remote.git"
run_job "$T"
echo "      fixture (push-fail): $T (exit=$JOB_RC)"
[ "$JOB_RC" -ne 0 ] && ok "push-fail: job exits non-zero" || bad "push-fail: job exits 0"
WT="$(find "$T/state" -maxdepth 1 -name 'wt-*' -type d | head -1)"
if [ -n "$WT" ] && g -C "$WT" cat-file -e HEAD:q-system/lessons/fixture-lesson.md 2>/dev/null; then
  ok "push-fail: the commit is kept in its worktree"
else
  bad "push-fail: the committed lesson is gone"
fi
[ -n "$WT" ] && grep -q "$WT" "$T/notify.txt" 2>/dev/null \
  && ok "push-fail: the alert names where the lessons are" \
  || bad "push-fail: the alert does not name the worktree"
rm -rf "$T"

# --- 7. negative control: last week's lessons PR is still open -------------
# The ledger travels with the lessons, so distilling from a main without last
# week's unmerged rows would publish the same sources twice.
T="$(build_fixture open-pr)"
run_job "$T"
echo "      fixture (open-pr): $T (exit=$JOB_RC)"
[ "$JOB_RC" -ne 0 ] && ok "open-pr: job exits non-zero" || bad "open-pr: job exits 0"
[ -z "$(auto_branch "$T")" ] && ! find "$T" -name fixture-lesson.md | grep -q . \
  && ok "open-pr: nothing was distilled or pushed" \
  || bad "open-pr: the run distilled while a lessons PR was open"
grep -q 'pull/76' "$T/notify.txt" 2>/dev/null \
  && ok "open-pr: the alert names the open PR" || bad "open-pr: the alert does not name the open PR"
rm -rf "$T"

echo "---"
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
