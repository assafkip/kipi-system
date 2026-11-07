#!/usr/bin/env bash
# Review on ready, not per push (ASK-2542): pr-review-agent.sh spends at most
# ONE full review and ONE fix-only review per PR, and never reviews a draft.
#
# THE DEFECT. The round cap (KIPI_REVIEW_MAX_ROUNDS, 3) bounded rounds per PR but
# every round was a FULL review of the whole PR, and three of them could land on
# the same head. 35 reviews ran in one day, 7 on one PR (RCA 2026-10-06, root
# cause #5). Nothing distinguished "review this PR" from "review the fix".
#
# WHAT RED LOOKS LIKE. A stub `claude` appends one line per call and dumps its
# argv (the prompt). On the pre-fix script: a draft is reviewed (1 call), a
# second run on the same head calls the model again, the fix round carries no
# since-diff, and a third run on a new head calls the model again.
#
# THE FIX ROUND'S DIFF (PR #614 round 2). Cases 7 to 9. On 6ba06690: GitHub's
# compare body reached the fix-only prompt unfiltered, so main's file rode
# along (7); a compare body holding only main's code was dispatched as a
# fix-only review of main (8); and a same-tree push (reword, amend, empty
# commit) exited 1 with no review and no status (9). The stub's compare answer
# is a body real git produced, never `{}`: `{}` is 2 bytes of "diff" and made
# the empty-diff branch unreachable.
#
# Isolation: HOME, the repo, `gh` and `claude` are fixtures in a mktemp dir. No
# live PR is read and no model is spent. PATH is sealed: only the stub dir and
# the system dirs, so a real `claude` or `gh` elsewhere cannot answer.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SRC_DIR="$ROOT/q-system/.q-system/scripts"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$SRC_DIR/pr-review-agent.sh" ] || fail "pr-review-agent.sh missing at $SRC_DIR"
REAL_GIT="$(command -v git)" || fail "git not on PATH"
REAL_PY="$(command -v python3)" || fail "python3 not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_TARGET_REPO KIPI_REVIEW_ENGINE KIPI_REVIEW_PRIMARY_ENGINE KIPI_REVIEW_MAX_ROUNDS \
      KIPI_REVIEW_HUMAN_REREQUEST KIPI_REVIEW_EXPECT_HEAD 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB"
ln -s "$REAL_GIT" "$STUB/git"
ln -s "$REAL_PY" "$STUB/python3"

mkdir -p "$WORK/skel/q-system/.q-system/scripts"
git init -q "$WORK/skel"
cp "$SRC_DIR/pr-review-agent.sh" "$SRC_DIR/pr-verdict-lib.sh" "$SRC_DIR/repo-slug-lib.sh" \
   "$SRC_DIR/env-failure-lib.sh" "$SRC_DIR/reviewer-token-lib.sh" \
   "$WORK/skel/q-system/.q-system/scripts/"
G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "control code"
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "https://github.com/example-owner/example-repo.git"
# The PR's first commit. FIRST_MARKER is in the PR but NOT in the fix diff.
printf 'line one FIRST_MARKER\n' > "$WORK/skel/OTHER.txt"
printf 'line one\n' > "$WORK/skel/FILE.txt"
G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "the PR"
AGENT="$WORK/skel/q-system/.q-system/scripts/pr-review-agent.sh"
sha() { git -C "$WORK/skel" rev-parse HEAD; }

echo false > "$WORK/draft"
# GitHub's compare answers NOTHING for two identical trees. Cases 7 and 8 write
# a real git diff here; the default is that empty answer.
: > "$WORK/compare-body"
GH_LOG="$WORK/gh-calls.txt"; : > "$GH_LOG"
cat > "$STUB/gh" <<EOF
#!/bin/bash
printf '%s\n' "\$*" >> "$GH_LOG"
case "\$*" in
  *"pr view"*"isDraft"*)    cat "$WORK/draft" ;;
  *"pr view"*"headRefOid"*) printf '%s\t%s\n' "\$(git -C "$WORK/skel" rev-parse HEAD)" "a PR title" ;;
  *"pr view"*"files"*)      printf 'FILE.txt\nOTHER.txt\n' ;;
  *"pr diff"*)              echo "diff --git a/FILE.txt b/FILE.txt" ;;
  *"pr comment"*)           echo "https://github.com/example-owner/example-repo/pull/1#issuecomment-1" ;;
  *"commits/"*"/statuses"*) echo "" ;;
  *"compare/"*)             cat "$WORK/compare-body" ;;
  *"api"*)                  echo '{}' ;;
esac
exit 0
EOF
chmod +x "$STUB/gh"

CLAUDE_LOG="$WORK/claude-calls.txt"; : > "$CLAUDE_LOG"
cat > "$STUB/claude" <<EOF
#!/bin/bash
echo call >> "$CLAUDE_LOG"
n=\$(wc -l < "$CLAUDE_LOG" | tr -d ' ')
printf '%s\n' "\$@" > "$WORK/prompt-\$n.txt"
# What the model could open from the fetched PR context, per call.
ls "$WORK"/home/.config/kipi/review-scratch/ctx.*/ > "$WORK/ctx-\$n.txt" 2>/dev/null
cat <<'REVIEW'
VERDICT: REQUEST CHANGES
FINDINGS:
major|still wrong|FILE.txt:1
major|a follow-up the reviewer released|OTHER.txt:1|nonblocking
END FINDINGS
REVIEW
exit 0
EOF
chmod +x "$STUB/claude"
printf '#!/bin/bash\nexit 0\n' > "$STUB/codex"; chmod +x "$STUB/codex"
printf '#!/bin/bash\nexit 0\n' > "$STUB/notify"; chmod +x "$STUB/notify"
SEALED_PATH="$STUB:/usr/bin:/bin:/usr/sbin:/sbin"

calls() { wc -l <"$CLAUDE_LOG" | tr -d ' '; }
run_reviewer() {  # [RPR=<pr>] run_reviewer <out-file> [extra args...]
  local out="$1"; shift
  ( cd "$WORK/skel" \
    && PATH="$SEALED_PATH" HOME="$WORK/home" KIPI_STATE_DIR="$WORK/state" KIPI_NOTIFY="$STUB/notify" \
       bash "$AGENT" "${RPR:-1}" --engine claude "$@" ) >"$out" 2>&1
  echo $? > "$out.rc"
}
new_commit() {  # new_commit <marker>
  printf '%s\n' "$1" >> "$WORK/skel/FILE.txt"
  G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "fix $1"
  sleep 1  # review files are named to the second
}

# 1. A draft is never reviewed.
echo true > "$WORK/draft"
run_reviewer "$WORK/d.out" --post
[ "$(calls)" = "0" ] || fail "a DRAFT PR reached the model ($(calls) call):
$(tail -15 "$WORK/d.out")"
[ "$(cat "$WORK/d.out.rc")" = "0" ] || fail "draft skip exited $(cat "$WORK/d.out.rc"), expected 0"
grep -q 'draft, skipped' "$WORK/d.out" || fail "draft skip did not log 'draft, skipped':
$(tail -15 "$WORK/d.out")"
ok "draft: 0 model calls, exit 0, logged 'draft, skipped'"
echo false > "$WORK/draft"

# 2. First run on a ready PR: ONE full review (positive control for the stub).
# A legacy un-keyed record (pr-1.verdict.json) belongs to the HOME repo's PR #1,
# not to example-owner/example-repo's. The seed must not read it, or this PR's
# first review becomes a fix-only round against a foreign sha (PR #614 review,
# major: exit 1, no model call, no status).
mkdir -p "$WORK/home/.config/kipi/pr-reviews"
printf '{"pr": 1, "usable": true, "head_sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"}\n' \
  > "$WORK/home/.config/kipi/pr-reviews/pr-1.verdict.json"
FULL_SHA="$(sha)"
run_reviewer "$WORK/r1.out" --post
grep -q 'seeded full review at deadbeef' "$WORK/r1.out" \
  && fail "the ready budget was seeded from another repo's legacy verdict record (pr-1.verdict.json):
$(grep 'ready budget' "$WORK/r1.out")"
[ "$(calls)" = "1" ] || fail "first ready run made $(calls) model calls, expected 1 (stub is not the dispatched engine?):
$(tail -20 "$WORK/r1.out")"
grep -q 'FIX-ONLY' "$WORK/prompt-1.txt" && fail "the first review was scoped as fix-only; it must be a full review"
grep -q 'pr diff 1' "$WORK/prompt-1.txt" || fail "the full-review prompt no longer tells the model to read the whole PR diff"
ok "first ready run: 1 full review"
STATE="$(find "$WORK/home" -name '.ready-review-*pr-1' | head -1)"
[ -n "$STATE" ] || fail "no per-PR ready-review state file was written"
grep -q "full_sha=$FULL_SHA" "$STATE" || fail "state does not record the reviewed head sha:
$(cat "$STATE")"
ok "state keyed on repo#PR records full_sha"

# 3. Same head again: nothing new to review, zero calls.
run_reviewer "$WORK/r2.out" --post
[ "$(calls)" = "1" ] || fail "a second run on the SAME head called the model again ($(calls) total):
$(tail -15 "$WORK/r2.out")"
[ "$(cat "$WORK/r2.out.rc")" = "0" ] || fail "same-head run exited $(cat "$WORK/r2.out.rc"), expected 0"
grep -q 'No model call made' "$WORK/r2.out" || fail "same-head run gave no one-line reason"
ok "same head: 0 model calls, exit 0, one-line reason"

# 4. A fix commit: ONE fix-only review whose prompt carries only the since-diff.
new_commit "SINCE_MARKER_FIX"
FIX_SHA="$(sha)"
run_reviewer "$WORK/r3.out" --post
[ "$(calls)" = "2" ] || fail "the fix round made $(( $(calls) - 1 )) model calls, expected 1:
$(tail -20 "$WORK/r3.out")"
P="$WORK/prompt-2.txt"
grep -q 'FIX-ONLY' "$P" || fail "the fix round prompt is not scoped as fix-only"
grep -q '+SINCE_MARKER_FIX' "$P" || fail "the fix round prompt does not carry the since-diff"
grep -q 'FIRST_MARKER' "$P" && fail "the fix round prompt carries code from BEFORE the recorded sha; it must pass only the since-diff"
grep -q 'pr diff 1' "$P" && fail "the fix round still tells the model to read the whole PR diff"
grep -q "fix_sha=$FIX_SHA" "$STATE" || fail "state does not record the fix-only sha"
# The fix-only verdict sets the PR's gate, so round 1's major must be re-checked
# even though the fix diff may not touch it (PR #532 review, major).
grep -q 'EARLIER BLOCKER AND MAJOR' "$P" && grep -q '^major|still wrong|FILE.txt:1$' "$P" \
  || fail "the fix round prompt does not carry round 1's major for a re-check"
# A major the reviewer marked nonblocking is a follow-up, not a gate (ASK-2422).
# Pasted into the re-check list, the fix round is told to raise it again at its
# original severity, and a re-raise without the mark turns it back into a gate.
grep -q 'a follow-up the reviewer released' "$P" \
  && fail "the fix round prompt asks for a re-check of a NONBLOCKING major; ASK-2422 made it a follow-up, not a gate"
# The whole-PR diff is fetched at review start (ASK-2648). Left in the context
# dir, the fix round can read the whole PR again, which this budget removes.
grep -qF 'pr.diff' "$WORK/ctx-1.txt" || fail "positive control: the full round's context has no pr.diff (stub cannot see the context dir?)"
grep -qF 'pr.diff' "$WORK/ctx-2.txt" && fail "the fix round's context still holds the whole-PR diff (pr.diff)"
grep -qF 'pr.diff' "$P" && fail "the fix round prompt still points the model at the whole-PR diff (pr.diff):
$(grep -nF 'pr.diff' "$P")"
ok "fix round: 1 call, prompt is the since-diff only"

# 5. Any further head: zero model calls, exit 0, one-line reason.
new_commit "THIRD_PUSH"
run_reviewer "$WORK/r4.out" --post
[ "$(calls)" = "2" ] || fail "a THIRD review was dispatched ($(calls) total calls):
$(tail -20 "$WORK/r4.out")"
[ "$(cat "$WORK/r4.out.rc")" = "0" ] || fail "budget-spent run exited $(cat "$WORK/r4.out.rc"), expected 0"
grep -q 'review budget spent' "$WORK/r4.out" || fail "budget-spent run gave no reason line:
$(tail -15 "$WORK/r4.out")"
grep -q 'No model call made' "$WORK/r4.out" || fail "budget-spent line does not say no model call was made"
ok "third head: 0 model calls, exit 0, 'review budget spent'"

# 6. The human override reaches the model, and is logged and counted.
KIPI_REVIEW_HUMAN_REREQUEST=1 run_reviewer "$WORK/r5.out" --post
[ "$(calls)" = "3" ] || fail "KIPI_REVIEW_HUMAN_REREQUEST=1 did not reach the model:
$(tail -20 "$WORK/r5.out")"
grep -q 'human re-request' "$WORK/r5.out" || fail "the override was not logged in the run output"
grep -q '^overrides=1$' "$STATE" || fail "the override was not counted in state:
$(cat "$STATE")"
ok "override: 1 call, logged, counted (overrides=1)"

# FULL REVIEW IN THE FIX SLOT: what cases 8 and 9 expect. One model call, a
# prompt that reads the whole PR (not FIX-ONLY), exit 0, the fix slot spent at
# the head, and a commit status POSTED there. Exit 1 with nothing posted is the
# wedge round 2 found: the floor's red stands and nobody reads the PR.
expect_full_in_fix_slot() {  # expect_full_in_fix_slot <case> <pr> <out> <calls-before> <state-file>
  local c="$1" pr="$2" out="$3" before="$4" st="$5" head; head="$(sha)"
  [ "$(cat "$out.rc")" = "0" ] || fail "$c: exited $(cat "$out.rc"), expected 0 (statuses posted on the head: $(grep -c "statuses/$head" "$GH_LOG")):
$(tail -6 "$out")"
  [ "$(calls)" = "$((before + 1))" ] || fail "$c: made $(( $(calls) - before )) model calls, expected 1:
$(tail -8 "$out")"
  local p="$WORK/prompt-$(calls).txt"
  grep -q 'FIX-ONLY' "$p" && fail "$c: dispatched as a FIX-ONLY review; with no change to the PR's files to show it must be one full review:
$(grep -n -A3 '^## The change since' "$p" | head -8)"
  grep -q "pr diff $pr" "$p" || fail "$c: the prompt does not point the model at the whole-PR diff"
  grep -qF 'pr.diff' "$WORK/ctx-$(calls).txt" || fail "$c: the whole-PR diff (pr.diff) was removed from a FULL review's context"
  grep -q "^fix_sha=$head$" "$st" || fail "$c: the full review did not spend the fix-only slot at the head:
$(cat "$st")"
  grep -q -- "-X POST repos/example-owner/example-repo/statuses/$head" "$GH_LOG" \
    || fail "$c: no commit status was posted on the head"
  grep -q 'One FULL review instead' "$out" || fail "$c: the run does not say why the fix round became a full review"
}

# 7. The old sha is not in the review tree (the hosted runner fetches the head
# at depth 1), so the since-diff comes from GitHub's compare, and that body is
# NOT limited to the PR: this push also merged main. The side repo stands in for
# GitHub: it holds the old sha, the review tree does not, and real git writes
# the compare body. main's path has a space and a " b/" in it, so a header
# split on " b/" would mis-name it.
ENGINE_DIR_T="$(dirname "$STATE")"
SIDE="$WORK/side"; git init -q "$SIDE"; mkdir -p "$SIDE/docs/main notes b"
GD() { G -C "$SIDE" -c diff.noprefix=false -c diff.mnemonicPrefix=false -c color.ui=never "$@"; }
printf 'line one\n' > "$SIDE/FILE.txt"
G -C "$SIDE" add -A; G -C "$SIDE" commit -q -m "the full-review head"
OLD7="$(git -C "$SIDE" rev-parse HEAD)"
git -C "$WORK/skel" cat-file -e "$OLD7^{commit}" 2>/dev/null && fail "fixture: the old sha must be absent from the review tree"
printf 'line one\nPR_FIX_MARKER\n' > "$SIDE/FILE.txt"
printf 'MAIN_ONLY_MARKER\n' > "$SIDE/docs/main notes b/x.txt"
G -C "$SIDE" add -A; G -C "$SIDE" commit -q -m "the fix, plus a merge of main"
GD diff "$OLD7" HEAD > "$WORK/compare-body"
grep -q '+PR_FIX_MARKER' "$WORK/compare-body" && grep -q '+MAIN_ONLY_MARKER' "$WORK/compare-body" \
  || fail "fixture: the compare body must carry the PR's file AND main's"
ST7="$ENGINE_DIR_T/.ready-review-example-owner_example-repo__pr-7"
printf 'full_sha=%s\n' "$OLD7" > "$ST7"
: > "$GH_LOG"; B7="$(calls)"
RPR=7 run_reviewer "$WORK/r7.out" --post
grep -q "compare/$OLD7" "$GH_LOG" || fail "7: positive control: GitHub's compare was never asked (the git path answered?)"
[ "$(calls)" = "$((B7 + 1))" ] || fail "7: made $(( $(calls) - B7 )) model calls, expected 1:
$(tail -8 "$WORK/r7.out")"
P7="$WORK/prompt-$(calls).txt"
grep -q 'FIX-ONLY' "$P7" || fail "7: not scoped as a fix-only review"
grep -q '+PR_FIX_MARKER' "$P7" || fail "7: the PR's own change is missing from the fix-only diff"
grep -q 'MAIN_ONLY_MARKER' "$P7" && fail "7: the fix-only prompt carries code that is NOT in this PR (main's file from GitHub's compare):
$(grep -n 'main notes\|MAIN_ONLY' "$P7" | head -4)"
ok "7: GitHub's compare is limited to the PR's files (main's file dropped, the fix kept)"

# 8. A push that ONLY merged main, on the same compare path. Limited to the
# PR's files, the since-diff is empty: one full review in the fix slot, never a
# fix-only review of main and never exit 1.
OLD8="$(git -C "$SIDE" rev-parse HEAD)"
printf 'MAIN_ONLY_MARKER_2\n' >> "$SIDE/docs/main notes b/x.txt"
G -C "$SIDE" add -A; G -C "$SIDE" commit -q -m "merge main only"
GD diff "$OLD8" HEAD > "$WORK/compare-body"
grep -q '+MAIN_ONLY_MARKER_2' "$WORK/compare-body" || fail "fixture: case 8's compare body is empty"
ST8="$ENGINE_DIR_T/.ready-review-example-owner_example-repo__pr-8"
printf 'full_sha=%s\n' "$OLD8" > "$ST8"
: > "$GH_LOG"; B8="$(calls)"
RPR=8 run_reviewer "$WORK/r8.out" --post
grep -q 'MAIN_ONLY_MARKER_2' "$WORK/prompt-$(calls).txt" && fail "8: main's code reached the prompt of a push that only merged main:
$(grep -n 'FIX-ONLY\|MAIN_ONLY' "$WORK/prompt-$(calls).txt" | head -4)"
expect_full_in_fix_slot 8 8 "$WORK/r8.out" "$B8" "$ST8"
ok "8: a merge-main-only push is one full review in the fix slot, status posted"

# 9. A same-tree push (reword, amend, empty commit) on the git path. Both git
# and GitHub's compare correctly answer an empty diff. That is "nothing in the
# PR changed", not an outage: one full review in the fix slot, status posted.
ST9="$ENGINE_DIR_T/.ready-review-example-owner_example-repo__pr-9"
printf 'full_sha=%s\n' "$(sha)" > "$ST9"
G -C "$WORK/skel" commit -q --allow-empty -m "reword only"
[ "$(git -C "$WORK/skel" rev-parse 'HEAD^{tree}')" = "$(git -C "$WORK/skel" rev-parse 'HEAD~1^{tree}')" ] \
  || fail "fixture: case 9's push must keep the tree identical"
: > "$WORK/compare-body"
: > "$GH_LOG"; B9="$(calls)"
RPR=9 run_reviewer "$WORK/r9.out" --post
expect_full_in_fix_slot 9 9 "$WORK/r9.out" "$B9" "$ST9"
ok "9: a same-tree push is one full review in the fix slot, exit 0, status posted"

# 10. A fix too big to paste whole. The old shape cut it at 200000 characters
# and told the model to "read the rest with git diff", which cannot run on the
# compare path. Now it is one full review in the fix slot, read from pr.diff.
ST10="$ENGINE_DIR_T/.ready-review-example-owner_example-repo__pr-10"
printf 'full_sha=%s\n' "$(sha)" > "$ST10"
"$REAL_PY" -c 'print("BIG_FIX_MARKER " * 14000)' >> "$WORK/skel/FILE.txt"
G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "a fix bigger than the prompt carries"
: > "$GH_LOG"; B10="$(calls)"
RPR=10 run_reviewer "$WORK/r10.out" --post
grep -q 'BIG_FIX_MARKER' "$WORK/prompt-$(calls).txt" && fail "10: a since-diff over the cap was pasted (cut) into the prompt"
expect_full_in_fix_slot 10 10 "$WORK/r10.out" "$B10" "$ST10"
ok "10: a since-diff over the cap is one full review in the fix slot, nothing cut"

echo "PASS ($PASS checks) test-review-on-ready.sh"
