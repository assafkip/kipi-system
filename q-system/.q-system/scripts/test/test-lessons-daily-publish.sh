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
# The fixture: a real bare origin with main, and a skeleton clone in one of three
# states (on a stale feature branch, on main but behind origin, on main with a
# local commit). The distiller, gh, the reviewer, Notion and Slack are stubs; git
# is real, so "pushed" and "on main's history" are measured, not assumed.
#
# THE FAN-OUT IS THE REAL kipi-update.sh, run --dry-run. It was `touch` until
# codex's round-2 review of PR #551: the fixture rebuilt the stale-branch state
# and the stub reported a fan-out the real updater refuses. The seed now carries
# the updater, the gates it is fail-closed on, and one fixture instance, so its
# own branch preflight decides (same recipe as test-kipi-update-dry-final-state.sh).
#
#   1. the lesson reaches origin on an auto/lessons-* branch built on main;
#   2. the skeleton's own branch gets no commit and no stray lesson file;
#   3. a PR to main is opened, auto-merge is armed, the reviewer is run;
#   4. on a feature branch the real updater refuses: the run exits 1, the
#      alert names the branch, and the checkout is not switched or moved;
#   5. negative control: a failed PR create exits non-zero, says so, and keeps
#      the worktree; the pushed branch still holds the lesson;
#   6. negative control: a failed push exits non-zero and keeps the worktree
#      with the commit in it, named in the alert;
#   7. negative control: last week's lessons PR still open stops the run before
#      it distills, so the same sources cannot publish twice;
#  10. on main behind origin (the steady state): the run fast-forwards the
#      checkout, the real updater passes, exit 0; a quiet week stays silent;
#  11. on main with a local commit: left alone, the updater refuses, exit 1;
#  12. negative control: a failed ls-remote stops the run before it distills.
#  13. every way the lessons half can fail still runs the fleet update: no
#      claude CLI, fetch, worktree add, ls-remote, the merged check, the
#      distiller, its JSON, and a refused lessons commit. One alert names both
#      halves and the run exits 1. Rounds 3 and 4 of PR #551 each found an
#      early `fail` that skipped the fan-out; this case enumerates the class.
#  14. negative control: a non-lesson path on the lessons branch is refused by
#      lessons-push-guard.py and never pushed to this public repo.
#  15. the merged check is one gh call for any number of lessons branches, and
#      its match is exact (a merged wk10 does not clear an unmerged wk1).
#
# Case 10 also pins that a clean publish removes its worktree even though the
# reviewer dirtied a tracked file in it.
#
# Cases 5 to 9 run on the healthy main state, so each non-zero exit comes from
# the failure under test and not from a refused fan-out.
#
# SKELETON ONLY (capability/skeleton_only): the fixture copies kipi-update.sh and
# its root-level helpers, which `kipi update` never ships to an instance.
#
# Never touches the live repo, log, Slack, Linear, GitHub or the fleet.

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR \
      GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_PREFIX

SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "$SCRIPTS/../../.." && pwd)"
SUT="$SCRIPTS/lessons-daily.sh"
REAL_GIT="$(command -v git)"
PASS=0
FAIL=0
ok()  { echo "PASS  $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL  $1"; FAIL=$((FAIL + 1)); }

g() { git -c user.email=t@example.com -c user.name=t -c commit.gpgsign=false "$@"; }

# seed_updater <seed-dir> <tmp>: the real updater and every gate it is
# fail-closed on, an unarmed leak baseline, and a registry naming one instance.
seed_updater() {
  local s="$1" tmp="$2" f
  mkdir -p "$s/q-system/.q-system/scripts" "$s/q-system/.q-system/state" \
           "$s/.claude/rules" "$s/plugins/demo"
  for f in kipi-update.sh kipi-update-preserve-scan.py kipi-update-deletion-guard.py \
           kipi-settings-merge.py validate-separation.py; do cp "$ROOT/$f" "$s/$f"; done
  # skeleton-provenance.sh: the updater ABORTs without it since PR #555 moved
  # its origin proof there. Unseeded, every fan-out in this suite failed in CI
  # (24 of 70) while the branch alone, without #555, stayed green.
  for f in propagation-leak-gate.py fleet-replica-divergence.py containment-targets.py \
           skeleton-provenance.sh; do
    cp "$SCRIPTS/$f" "$s/q-system/.q-system/scripts/$f"
  done
  printf '{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}\n' \
    > "$s/q-system/.q-system/state/propagation-leak-baseline.json"
  printf 'raise SystemExit(0)\n' > "$s/q-system/.q-system/scripts/capability-gate.py"
  printf 'rule\n' > "$s/.claude/rules/example.md"
  printf 'plugin\n' > "$s/plugins/demo/content.txt"
  printf '{"permissions":{"allow":["Read"]},"hooks":{}}\n' > "$s/settings-template.json"
  mkdir -p "$tmp/inst/q-system" "$tmp/inst/.claude" "$tmp/inst/plugins/demo"
  printf 'old\n' > "$tmp/inst/q-system/tracked.md"
  printf '{"permissions":{"allow":["Write"]},"hooks":{}}\n' > "$tmp/inst/.claude/settings.json"
  printf 'plugin\n' > "$tmp/inst/plugins/demo/content.txt"
  g init -q -b main "$tmp/inst" && g -C "$tmp/inst" add -A && g -C "$tmp/inst" commit -qm inst
  printf '{"instances":[{"name":"fixture","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
    "$tmp/inst" > "$s/instance-registry.json"
}

# build_fixture <gh-mode: ok|fail-create|pending-branch|merged-branch>
#               <skel-state: feature|main-behind|main-ahead> -> echoes the temp root
build_fixture() {
  local mode="$1" state="${2:-main-behind}" tmp
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/bin" "$tmp/seed/q-system/lessons" "$tmp/seed/lesson-candidates"
  printf 'keep\n' > "$tmp/seed/q-system/lessons/existing-lesson.md"
  printf '{"seenkey": {"status": "published"}}\n' > "$tmp/seed/lesson-candidates/.processed.json"
  # Tracked in the real repo, and rewritten by a SessionStart hook whenever claude
  # starts in a checkout. The reviewer starts claude inside the lessons worktree.
  mkdir -p "$tmp/seed/q-system/memory"
  printf 'seed\n' > "$tmp/seed/q-system/memory/.sycophancy-monthly-stamp"
  seed_updater "$tmp/seed" "$tmp"
  g init -q -b main "$tmp/seed"
  g -C "$tmp/seed" add -A && g -C "$tmp/seed" commit -qm "seed [no-issue: fixture]"
  g clone -q --bare "$tmp/seed" "$tmp/origin.git"
  g clone -q "$tmp/origin.git" "$tmp/skel"
  case "$state" in
    feature)      # the scar: a feature branch carrying a local commit
      g -C "$tmp/skel" switch -q -c feature/stale
      printf 'wip\n' > "$tmp/skel/wip.txt"
      g -C "$tmp/skel" add wip.txt && g -C "$tmp/skel" commit -qm "wip [no-issue: fixture]" ;;
    main-ahead)   # on main, with a commit origin never saw
      g -C "$tmp/skel" commit -q --allow-empty -m "local only [no-issue: fixture]" ;;
  esac
  # main moves on after the checkout last pulled, in every state.
  g -C "$tmp/seed" commit -q --allow-empty -m "someone else's merge [no-issue: fixture]"
  g -C "$tmp/seed" push -q "$tmp/origin.git" main
  g -C "$tmp/skel" config user.email t@example.com
  g -C "$tmp/skel" config user.name t
  g -C "$tmp/skel" config commit.gpgsign false
  # Hooks run in the worktree too, through the shared config.
  mkdir -p "$tmp/hooks"
  printf '#!/bin/bash\ntouch "%s/pre-commit.ran"\nexit 0\n' "$tmp" > "$tmp/hooks/pre-commit"
  chmod +x "$tmp/hooks/pre-commit"
  # commit-msg records which bypass ledger the real linear-issue-ref-check.py
  # would append to (it honours LINEAR_BYPASS_LEDGER, else the repo toplevel).
  printf '#!/bin/bash\nprintf "%%s\\n" "${LINEAR_BYPASS_LEDGER:-$(git rev-parse --show-toplevel)/q-system/output/linear-bypass.jsonl}" > "%s/bypass-ledger.seen"\nexit 0\n' "$tmp" > "$tmp/hooks/commit-msg"
  chmod +x "$tmp/hooks/commit-msg"
  g -C "$tmp/skel" config core.hooksPath "$tmp/hooks"

  cp "$SUT" "$tmp/skel/q-system/.q-system/scripts/lessons-daily.sh"
  # The real streak helper; LESSONS_DIR unset (the pre-fix script) falls back
  # to the checkout's own lessons dir, which is the distiller's real default.
  cp "$SCRIPTS/lessons_streak.py" "$tmp/skel/q-system/.q-system/scripts/lessons_streak.py"
  cp "$SCRIPTS/lessons-push-guard.py" "$tmp/skel/q-system/.q-system/scripts/lessons-push-guard.py"
  printf '#!/bin/bash\nexit 0\n' > "$tmp/skel/q-system/.q-system/scripts/install-plist.sh"
  printf '#!/bin/bash\nexit 0\n' > "$tmp/bin/claude"
  # gh: records argv. `pr create` prints a PR URL unless gh.mode says fail.
  # `pr list --state merged --search head:P` prints the merged.txt names that
  # start with P, one per line, which is what gh's --jq '.[].headRefName' gives
  # (GitHub's head: qualifier is a prefix match, measured 2026-10-23). Without
  # --state merged it prints nothing, so a wrong query reads as "nothing merged"
  # and holds the run. `pr list --head B` (one call per branch, the old shape)
  # answers 1 when B is in merged.txt, else 0.
  # gh.mode is a file so one fixture can change behaviour between two runs.
  cat > "$tmp/bin/gh" <<GH
#!/bin/bash
echo "\$*" >> "$tmp/gh.calls"
mode="\$(cat "$tmp/gh.mode" 2>/dev/null)"
case "\$1 \$2" in
  "pr create") [ "\$mode" = "fail-create" ] && { echo "gh: create refused" >&2; exit 1; }
               echo "https://github.com/fixture/repo/pull/77" ;;
  "pr list")   [ "\$mode" = "fail-list" ] && { echo "gh: auth expired" >&2; exit 1; }
               head=""; search=""; merged=""
               while [ \$# -gt 0 ]; do
                 case "\$1" in --head) head="\$2" ;; --search) search="\$2" ;; esac
                 [ "\$1" = "--state" ] && [ "\$2" = "merged" ] && merged=1
                 shift
               done
               if [ -n "\$search" ]; then
                 case "\$search" in head:*)
                   [ -n "\$merged" ] && awk -v p="\${search#head:}" 'index(\$0, p) == 1' "$tmp/merged.txt" 2>/dev/null ;;
                 esac
               else
                 grep -qx "\$head" "$tmp/merged.txt" 2>/dev/null && echo 1 || echo 0
               fi ;;
esac
exit 0
GH
  printf '%s' "$mode" > "$tmp/gh.mode"
  # An earlier run's branch already on origin: unmerged, or merged.
  case "$mode" in pending-branch|merged-branch|fail-list)
    g -C "$tmp/seed" push -q "$tmp/origin.git" main:refs/heads/auto/lessons-old ;;
  esac
  [ "$mode" = "merged-branch" ] && echo "auto/lessons-old" > "$tmp/merged.txt"
  chmod +x "$tmp/bin/claude" "$tmp/bin/gh" "$tmp/skel/q-system/.q-system/scripts/install-plist.sh"
  printf '%s' "$tmp"
}

PUBLISHED='{"scanned": 1, "published": ["a fixture lesson"], "held": []}'
QUIET_RUN='{"scanned": 0, "published": [], "held": []}'
# run_job <tmp> [summary]; sets JOB_RC. The distill stub writes where the job
# tells it to. The fan-out is the real updater, dry, from the skeleton checkout,
# exactly where production runs it; its sweep history goes to a fixture file.
# Fault switches, all files in <tmp> so a case sets one without a new runner:
# distill.fail (the distiller exits 3), stray.on (it also writes a non-lesson
# file into lesson-candidates/), claude.bin (the CLI path the job checks).
# The review stub rewrites a tracked file inside the worktree, as the real
# reviewer's SessionStart hook does. It used to write only outside it, so the
# suite stayed green while every clean publish leaked its worktree (PR #551
# round 4).
run_job() {
  local tmp="$1" summary="${2:-$PUBLISHED}"
  printf '%s' "$summary" > "$tmp/summary.json"
  rm -f "$tmp/notify.txt"
  PATH="$tmp/bin:$PATH" \
  KIPI_CLAUDE_BIN="$(cat "$tmp/claude.bin" 2>/dev/null || echo claude)" \
  KIPI_DISTILL_CMD="[ -e '$tmp/distill.fail' ] && exit 3; if [ -e '$tmp/stray.on' ]; then printf 'not a lesson\n' > \"\${LESSONS_DIR%/q-system/lessons}/lesson-candidates/stray.txt\"; fi; if grep -q 'a fixture lesson' '$tmp/summary.json'; then printf '# a fixture lesson\n' > \"\${LESSONS_DIR:-$tmp/skel/q-system/lessons}/fixture-lesson.md\"; fi; cat '$tmp/summary.json'" \
  KIPI_REVIEW_CMD="echo \"\$PR_NUMBER\" >> '$tmp/review.calls'; mkdir -p q-system/memory && date > q-system/memory/.sycophancy-monthly-stamp" \
  KIPI_PROPAGATE_CMD="cd '$tmp/skel' && TMPDIR='$tmp' KIPI_FLEET_SWEEP_HISTORY='$tmp/sweep.jsonl' bash kipi-update.sh --dry-run" \
  KIPI_NOTION_SYNC_CMD="true" \
  KIPI_NOTIFY_CMD="printf '%s\\n' \"\$1\" >> '$tmp/notify.txt'" \
  KIPI_LESSONS_LOG="$tmp/lessons-daily.log" \
  KIPI_LESSONS_WT_ROOT="$tmp/state" \
  KIPI_STREAK_FILE="$tmp/streak.json" KIPI_ESCALATIONS_FILE="$tmp/esc.jsonl" \
    bash "$tmp/skel/q-system/.q-system/scripts/lessons-daily.sh" >/dev/null 2>&1
  JOB_RC=$?
}

# Lessons branches this run pushed (an earlier run's auto/lessons-old excluded).
auto_branch() { g -C "$1/origin.git" for-each-ref --format='%(refname:short)' 'refs/heads/auto/lessons-*' | grep -vx 'auto/lessons-old' | head -1; }
auto_count() { g -C "$1/origin.git" for-each-ref --format='%(refname:short)' 'refs/heads/auto/lessons-*' | grep -vx 'auto/lessons-old' | wc -l | tr -d ' '; }
worktrees_left() { find "$1/state" -maxdepth 1 -name 'wt-*' -type d 2>/dev/null | wc -l | tr -d ' '; }
origin_main() { g -C "$1/origin.git" rev-parse main; }

# --- 1-4. the scar: the checkout is on a stale feature branch ---------------
T="$(build_fixture ok feature)"
SKEL_HEAD_BEFORE="$(g -C "$T/skel" rev-parse HEAD)"
run_job "$T"
BR="$(auto_branch "$T")"
echo "      fixture (feature): $T (exit=$JOB_RC, branch=${BR:-none})"
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
  && [ "$(g -C "$T/skel" symbolic-ref --short HEAD)" = "feature/stale" ] \
  && ok "the skeleton's feature branch got no commit and was not switched" \
  || bad "the skeleton checkout was committed to or switched (HEAD $(g -C "$T/skel" rev-parse --short HEAD))"
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
[ "$(worktrees_left "$T")" = "0" ] && ok "the worktree was removed after a clean publish" \
                                   || bad "the worktree was left behind"
# What `touch` hid: the real updater refuses this checkout. The run must say so.
grep -q 'ABORT: the skeleton is not on main' "$T/lessons-daily.log" 2>/dev/null \
  && ok "feature: the real updater refused the feature branch" \
  || bad "feature: the real updater did not refuse; log: $(grep ABORT "$T/lessons-daily.log" | head -2)"
[ "$JOB_RC" -ne 0 ] && ok "feature: a refused fan-out exits non-zero" \
                    || bad "feature: a refused fan-out exits 0"
grep -q 'the skeleton checkout is on feature/stale, not main' "$T/notify.txt" 2>/dev/null \
  && ok "feature: the alert names the branch" \
  || bad "feature: the alert does not name the branch: $(cat "$T/notify.txt" 2>/dev/null)"
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

# --- 7. negative control: an earlier lessons branch is not merged ----------
# The ledger travels with the lessons, so distilling from a main without an
# earlier run's unmerged rows would publish the same sources twice.
T="$(build_fixture pending-branch)"
run_job "$T"
echo "      fixture (pending-branch): $T (exit=$JOB_RC)"
[ "$JOB_RC" -ne 0 ] && ok "pending-branch: job exits non-zero" || bad "pending-branch: job exits 0"
[ "$(auto_count "$T")" = "0" ] && ! find "$T" -name fixture-lesson.md | grep -q . \
  && ok "pending-branch: nothing was distilled or pushed" \
  || bad "pending-branch: the run distilled while a lessons branch was unmerged"
grep -q 'auto/lessons-old' "$T/notify.txt" 2>/dev/null \
  && ok "pending-branch: the alert names the branch" || bad "pending-branch: the alert does not name the branch"
# The guard holds back distilling, not the fleet. This job is the fleet's only
# unattended updater, so one stuck lessons PR used to stop every weekly update
# while the alert only said "not distilling" (review of PR #551, round 3).
[ "$(g -C "$T/skel" rev-parse HEAD)" = "$(origin_main "$T")" ] \
  && ! grep -q 'ABORT' "$T/lessons-daily.log" 2>/dev/null \
  && grep -q 'fleet updated from main' "$T/notify.txt" 2>/dev/null \
  && ok "pending-branch: the fleet was still updated from main, and the alert says so" \
  || bad "pending-branch: no fan-out behind the guard; alert: $(cat "$T/notify.txt" 2>/dev/null)"
rm -rf "$T"

# --- 8. the reviewer's reproducer: PR create fails, then a healthy week ----
# Run 1 pushes a branch and opens no PR. Checking open PRs only, run 2 saw
# nothing in flight and pushed the same lesson a second time.
T="$(build_fixture fail-create)"
run_job "$T"
printf 'ok' > "$T/gh.mode"
run_job "$T"
echo "      fixture (create-then-healthy): $T (exit=$JOB_RC, branches=$(auto_count "$T"))"
[ "$JOB_RC" -ne 0 ] && [ "$(auto_count "$T")" = "1" ] \
  && ok "create-then-healthy: run 2 refuses, one lessons branch on origin" \
  || bad "create-then-healthy: run 2 exit=$JOB_RC, $(auto_count "$T") lessons branches (same sources twice)"
rm -rf "$T"

# --- 9. control: a MERGED earlier branch does not block --------------------
# The repo keeps merged branches, so the guard must not read "exists" as "open".
T="$(build_fixture merged-branch)"
run_job "$T"
echo "      fixture (merged-branch): $T (exit=$JOB_RC, branches=$(auto_count "$T"))"
[ "$JOB_RC" -eq 0 ] && [ "$(auto_count "$T")" = "1" ] \
  && ok "merged-branch: the run proceeds and publishes" \
  || bad "merged-branch: a merged branch blocked the run (exit=$JOB_RC)"
rm -rf "$T"

# --- 10. the steady state: on main, behind origin --------------------------
# Main moves several times a day and nothing else pulls this checkout, so this
# is the state every week after the checkout is switched to main.
T="$(build_fixture ok main-behind)"
run_job "$T"
echo "      fixture (main-behind): $T (exit=$JOB_RC)"
# The checkout's main must equal origin/main as it stood when the fan-out ran,
# which is the commit before this run's lessons (they are on their own branch).
[ "$(g -C "$T/skel" rev-parse HEAD)" = "$(origin_main "$T")" ] \
  && ok "main-behind: the checkout was fast-forwarded to origin/main" \
  || bad "main-behind: the checkout is still behind origin/main"
! grep -q 'ABORT' "$T/lessons-daily.log" 2>/dev/null && [ "$JOB_RC" -eq 0 ] \
  && ok "main-behind: the real updater passed and the run exits 0" \
  || bad "main-behind: exit=$JOB_RC; $(grep -m2 ABORT "$T/lessons-daily.log")"
# Exit 0 and a clean alert must mean the worktree is gone, from disk and from the
# skeleton's worktree registry. The reviewer dirties a tracked file in it, and a
# plain `worktree remove` refused that every week (PR #551 round 4).
[ "$(worktrees_left "$T")" = "0" ] \
  && [ "$(g -C "$T/skel" worktree list --porcelain | grep -c '^worktree ')" = "1" ] \
  && ok "main-behind: a clean publish leaves no worktree on disk or registered" \
  || bad "main-behind: a clean publish leaked a worktree (on disk: $(worktrees_left "$T"), exit=$JOB_RC)"
if grep -q 'fleet updated from main' "$T/notify.txt" 2>/dev/null \
   && ! grep -q 'propagated to fleet' "$T/notify.txt" 2>/dev/null; then
  ok "main-behind: the alert says main went out, not this run's lessons"
else
  bad "main-behind: the alert claims these lessons were propagated: $(cat "$T/notify.txt" 2>/dev/null)"
fi
# The [no-issue:] bypass row must reach the skeleton's countable ledger, not the
# worktree that a clean publish deletes (review of PR #551, round 3).
[ "$(cat "$T/bypass-ledger.seen" 2>/dev/null)" = "$T/skel/q-system/output/linear-bypass.jsonl" ] \
  && ok "main-behind: the commit's bypass row goes to the skeleton's ledger" \
  || bad "main-behind: the bypass row goes to $(cat "$T/bypass-ledger.seen" 2>/dev/null || echo nowhere)"
# 10b. a quiet week still carries last week's merged lessons.
auto_branch "$T" >> "$T/merged.txt"     # last week's PR has merged
g -C "$T/seed" commit -q --allow-empty -m "another merge [no-issue: fixture]"
g -C "$T/seed" push -q "$T/origin.git" main
run_job "$T" "$QUIET_RUN"
[ "$JOB_RC" -eq 0 ] && grep -q 'quiet week: fleet updated from main' "$T/lessons-daily.log" \
  && [ "$(g -C "$T/skel" rev-parse HEAD)" = "$(origin_main "$T")" ] \
  && ok "quiet week: main is fast-forwarded and fanned out (exit 0)" \
  || bad "quiet week: no fan-out (exit=$JOB_RC); merged lessons would never ship"
[ ! -s "$T/notify.txt" ] && ok "quiet week: nothing slacked" \
                         || bad "quiet week: slacked on a quiet week: $(cat "$T/notify.txt")"
[ "$(auto_count "$T")" = "1" ] && ok "quiet week: no lessons branch pushed" \
                               || bad "quiet week: a quiet run pushed a lessons branch"
rm -rf "$T"

# --- 11. on main with a commit origin never saw: left alone ---------------
T="$(build_fixture ok main-ahead)"
SKEL_HEAD_BEFORE="$(g -C "$T/skel" rev-parse HEAD)"
run_job "$T"
echo "      fixture (main-ahead): $T (exit=$JOB_RC)"
[ "$(g -C "$T/skel" rev-parse HEAD)" = "$SKEL_HEAD_BEFORE" ] \
  && ok "main-ahead: the checkout's local commit was left alone" \
  || bad "main-ahead: the checkout was moved off its local commit"
grep -q 'is on main but not AT ' "$T/lessons-daily.log" 2>/dev/null && [ "$JOB_RC" -ne 0 ] \
  && ok "main-ahead: the real updater refused and the run exits non-zero" \
  || bad "main-ahead: exit=$JOB_RC without the updater's refusal"
rm -rf "$T"

# --- 12. negative control: the remote branch list cannot be read -----------
# An ls-remote that fails yields no refs. Read as "nothing pending", the run
# distilled past the one-branch guard (codex, PR #551 round 2).
T="$(build_fixture pending-branch)"
cat > "$T/bin/git" <<GIT
#!/bin/bash
case " \$* " in *" ls-remote "*) echo "fatal: unable to access origin" >&2; exit 128 ;; esac
exec "$REAL_GIT" "\$@"
GIT
chmod +x "$T/bin/git"
run_job "$T"
echo "      fixture (ls-remote-fails): $T (exit=$JOB_RC)"
[ "$JOB_RC" -ne 0 ] && ok "ls-remote-fails: job exits non-zero" || bad "ls-remote-fails: job exits 0"
[ "$(auto_count "$T")" = "0" ] && ! find "$T" -name fixture-lesson.md | grep -q . \
  && ok "ls-remote-fails: nothing was distilled or pushed" \
  || bad "ls-remote-fails: the run distilled with the remote unread"
grep -q 'could not list lessons branches' "$T/notify.txt" 2>/dev/null \
  && ok "ls-remote-fails: the alert says the list could not be read" \
  || bad "ls-remote-fails: the alert is silent: $(cat "$T/notify.txt" 2>/dev/null)"
rm -rf "$T"

# --- 13. a failed lessons half never skips the fleet update ------------------
# This job is the fleet's only unattended caller of kipi-update.sh. Review
# rounds 3 and 4 of PR #551 each found an early `fail` that exited before the
# fan-out, so a broken gh login or an unreadable origin would have stopped
# every weekly fleet update while the alert talked only about lessons. Same
# failure class twice, so this case enumerates every site instead of pinning
# the next one found. Each runs on the healthy main-behind state: the only
# thing wrong is the lessons half.
# fail_git <tmp> <ls-remote|worktree-add|first-fetch>: a git that fails one call.
fail_git() {
  local tmp="$1" what="$2" pat
  case "$what" in
    ls-remote)    pat='*" ls-remote "*) echo "fatal: unable to access origin" >&2; exit 128 ;;' ;;
    worktree-add) pat='*" worktree add "*) echo "fatal: could not create work tree" >&2; exit 128 ;;' ;;
    first-fetch)  pat="*\" fetch \"*) [ -e \"$tmp/fetch.failed\" ] || { touch \"$tmp/fetch.failed\"; echo \"fatal: unable to access origin\" >&2; exit 128; } ;;" ;;
  esac
  printf '#!/bin/bash\ncase " $* " in %s esac\nexec "%s" "$@"\n' "$pat" "$REAL_GIT" > "$tmp/bin/git"
  chmod +x "$tmp/bin/git"
}
# check_fleet_ran <label> <tmp> <reason in the alert>
check_fleet_ran() {
  local label="$1" tmp="$2" reason="$3" alert lines
  alert="$(cat "$tmp/notify.txt" 2>/dev/null)"
  lines="$({ grep -c . "$tmp/notify.txt" 2>/dev/null || echo 0; } | head -1)"
  echo "      fixture ($label): $tmp (exit=$JOB_RC)"
  [ "$JOB_RC" -ne 0 ] && ok "$label: exits non-zero" || bad "$label: exits 0"
  [ "$(g -C "$tmp/skel" rev-parse HEAD)" = "$(origin_main "$tmp")" ] \
    && ! grep -q 'ABORT' "$tmp/lessons-daily.log" 2>/dev/null \
    && ok "$label: the fleet update still ran from a fast-forwarded main" \
    || bad "$label: the lessons failure skipped the fleet update; log: $(tail -2 "$tmp/lessons-daily.log" | tr '\n' ' ')"
  [ "$lines" = "1" ] && printf '%s' "$alert" | grep -q -- "$reason" \
    && printf '%s' "$alert" | grep -q 'fleet updated from main' \
    && ok "$label: one alert names the lessons failure and the fleet result" \
    || bad "$label: alert ($lines line(s)) does not name both halves: $alert"
}
T="$(build_fixture ok)"; printf '%s' "$T/no-such-claude" > "$T/claude.bin"; run_job "$T"
check_fleet_ran "no-claude" "$T" "no claude CLI"; rm -rf "$T"
T="$(build_fixture ok)"; fail_git "$T" first-fetch; run_job "$T"
check_fleet_ran "fetch-fails" "$T" "could not fetch origin/main"; rm -rf "$T"
T="$(build_fixture ok)"; fail_git "$T" worktree-add; run_job "$T"
check_fleet_ran "worktree-fails" "$T" "could not open a worktree"; rm -rf "$T"
T="$(build_fixture ok)"; fail_git "$T" ls-remote; run_job "$T"
check_fleet_ran "ls-remote-fails" "$T" "could not list lessons branches"; rm -rf "$T"
T="$(build_fixture fail-list)"; run_job "$T"
check_fleet_ran "gh-list-fails" "$T" "could not ask GitHub which lessons branches merged"; rm -rf "$T"
T="$(build_fixture ok)"; touch "$T/distill.fail"; run_job "$T"
check_fleet_ran "distill-fails" "$T" "lessons-distill.py exited non-zero"; rm -rf "$T"
T="$(build_fixture ok)"; run_job "$T" "not json"
check_fleet_ran "distill-no-json" "$T" "no parseable JSON"; rm -rf "$T"
# A refused lessons commit. In PR mode the lessons sit in a worktree outside the
# checkout, so fanning out main cannot ship what the gate stopped.
T="$(build_fixture ok)"; printf '#!/bin/bash\necho "gate: refused" >&2\nexit 1\n' > "$T/hooks/pre-commit"; run_job "$T"
check_fleet_ran "commit-refused" "$T" "lessons commit FAILED"
[ "$(auto_count "$T")" = "0" ] && ok "commit-refused: nothing was pushed" \
                               || bad "commit-refused: a refused commit reached origin"
rm -rf "$T"

# --- 14. negative control: a non-lesson path on the lessons branch ----------
# The weekly cloud routine runs lessons-push-guard.py before its push because a
# Stop hook once committed a non-lesson file that reached PR #515 on this public
# repo. This push path must run the same guard (review of PR #551, round 4).
T="$(build_fixture ok)"; touch "$T/stray.on"; run_job "$T"
echo "      fixture (stray-path): $T (exit=$JOB_RC, branches=$(auto_count "$T"))"
[ "$JOB_RC" -ne 0 ] && ok "stray-path: exits non-zero" || bad "stray-path: exits 0"
[ "$(auto_count "$T")" = "0" ] && ok "stray-path: the branch was never pushed" \
                               || bad "stray-path: a non-lesson file was pushed to origin"
grep -q 'lessons-push-guard refused' "$T/notify.txt" 2>/dev/null \
  && ok "stray-path: the alert names the push guard" \
  || bad "stray-path: the alert does not name the guard: $(cat "$T/notify.txt" 2>/dev/null)"
[ "$(worktrees_left "$T")" = "1" ] && ok "stray-path: the worktree is kept for recovery" \
                                   || bad "stray-path: the worktree was removed"
rm -rf "$T"

# --- 15. the merged check is one GitHub call, however many branches exist ----
# The repo keeps merged branches, so one auto/lessons-* branch is added every
# week and never removed. One `gh pr list` per branch grew by a call a week, and
# any one failing cost that week's distilling (PR #551 round 4: 53 calls in one
# run after a year).
T="$(build_fixture merged-branch)"
for i in 1 2 3 4 5; do
  g -C "$T/seed" push -q "$T/origin.git" "main:refs/heads/auto/lessons-wk$i"
  echo "auto/lessons-wk$i" >> "$T/merged.txt"
done
run_job "$T"
CALLS="$(grep -c '^pr list' "$T/gh.calls" 2>/dev/null | head -1)"
echo "      fixture (six-merged): $T (exit=$JOB_RC, pr list calls=$CALLS)"
[ "$JOB_RC" -eq 0 ] && grep -q 'lessons published' "$T/lessons-daily.log" 2>/dev/null \
  && ok "six-merged: six merged branches do not hold the run" \
  || bad "six-merged: merged branches held the run (exit=$JOB_RC)"
[ "$CALLS" = "1" ] && ok "six-merged: one gh pr list call for six branches" \
                   || bad "six-merged: $CALLS gh pr list calls for six branches"
rm -rf "$T"
# 15b. The local match is exact: wk1 is not merged just because wk10 is. A
# substring match reads the merged name "auto/lessons-wk10" as containing wk1.
T="$(build_fixture merged-branch)"
g -C "$T/seed" push -q "$T/origin.git" "main:refs/heads/auto/lessons-wk1"
g -C "$T/seed" push -q "$T/origin.git" "main:refs/heads/auto/lessons-wk10"
echo "auto/lessons-wk10" >> "$T/merged.txt"
run_job "$T"
echo "      fixture (prefix-unmerged): $T (exit=$JOB_RC)"
[ "$JOB_RC" -ne 0 ] && ! find "$T" -name fixture-lesson.md | grep -q . \
  && grep -q 'not merged yet: auto/lessons-wk1\.' "$T/notify.txt" 2>/dev/null \
  && ok "prefix-unmerged: only the unmerged wk1 holds the run, and the alert names it" \
  || bad "prefix-unmerged: exit=$JOB_RC, alert: $(cat "$T/notify.txt" 2>/dev/null)"
rm -rf "$T"

echo "---"
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
