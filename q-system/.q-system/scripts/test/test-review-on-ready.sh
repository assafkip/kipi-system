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
cat <<'REVIEW'
VERDICT: REQUEST CHANGES
FINDINGS:
major|still wrong|FILE.txt:1
END FINDINGS
REVIEW
exit 0
EOF
chmod +x "$STUB/claude"
printf '#!/bin/bash\nexit 0\n' > "$STUB/codex"; chmod +x "$STUB/codex"
printf '#!/bin/bash\nexit 0\n' > "$STUB/notify"; chmod +x "$STUB/notify"
SEALED_PATH="$STUB:/usr/bin:/bin:/usr/sbin:/sbin"

calls() { wc -l <"$CLAUDE_LOG" | tr -d ' '; }
run_reviewer() {  # run_reviewer <out-file> [extra args...]
  local out="$1"; shift
  ( cd "$WORK/skel" \
    && PATH="$SEALED_PATH" HOME="$WORK/home" KIPI_STATE_DIR="$WORK/state" KIPI_NOTIFY="$STUB/notify" \
       bash "$AGENT" 1 --engine claude "$@" ) >"$out" 2>&1
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
FULL_SHA="$(sha)"
run_reviewer "$WORK/r1.out" --post
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

echo "PASS ($PASS checks) test-review-on-ready.sh"
