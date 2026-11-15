#!/usr/bin/env bash
# Delta review rounds for pr-review-agent.sh (ASK-3884, sp-ff374488).
#
# THE RULE. Founder, 2026-11-06, rule 11 in ~/.claude/rules/iteration-speed.md:
# "option 1. not all changes need a full cycle review". Round 1 reads the whole
# PR; every later round reads only the commits since the last reviewed sha.
#
# THE DEFECT. The reviewer had no way to do that: its flags were --issue,
# --engine, --repo and --post, so every round re-read `gh pr diff`. On 4 Points
# PR #23 the delta round went to a separate agent, and on kipi-system a delta
# review could not post the required kipi/reviewer-approved status at all.
#
# WHAT RED LOOKS LIKE. A stub `claude` copies the diff file its prompt points at.
# Round 1 (no receipt) must hand it the `gh pr diff` output (the whole PR). Round
# 2 with --delta must hand it `git diff <round-1 head> <new head>`: the new
# commit's change and NOT the round-1 change, and still post
# kipi/reviewer-approved on the NEW head. Without the delta code the round-2 copy
# is the whole-PR marker again: red.
#
# DELTA BY DEFAULT (ASK-5093). The first cut made the delta opt-in (--delta) and
# no caller ever passed it: linear-worker.sh called the reviewer bare, and
# consulting PR #578 got three whole-PR reviews on 2026-11-14. So the rounds
# below call it with NO flag. On the opt-in code round 2 reads the whole PR
# again: red. --full is the one way to force a whole read; --delta stays a
# no-op alias so an old caller does not break.
#
# Isolation: HOME, the repo, `gh` and `claude` are fixtures in a mktemp dir. No
# live PR is read and no model is spent.
set -uo pipefail
# NOT A BILLING TEST (ASK-4311). This suite stubs `claude` on PATH and tests its
# own subject, so its runs take the plan path: KIPI_FLEET_API_KEYS=0 makes the
# worker, the reviewer and the dispatcher call `env -u ANTHROPIC_API_KEY claude`
# exactly as before the fleet door. The door has its own suites
# (test_fleet_api_credit.py, test-dispatch-api-key-gate.sh, test-worker-usage-brake.sh).
export KIPI_FLEET_API_KEYS=0

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SRC_DIR="$ROOT/q-system/.q-system/scripts"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$SRC_DIR/pr-review-agent.sh" ] || fail "pr-review-agent.sh missing at $SRC_DIR"
REAL_GIT="$(command -v git)" || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_TARGET_REPO KIPI_REVIEW_ENGINE KIPI_REVIEW_PRIMARY_ENGINE KIPI_REVIEW_MAX_ROUNDS 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB"

mkdir -p "$WORK/skel/q-system/.q-system/scripts"
git init -q "$WORK/skel"
echo "base" > "$WORK/skel/FILE.txt"
cp "$SRC_DIR/pr-review-agent.sh" "$SRC_DIR/pr-verdict-lib.sh" "$SRC_DIR/repo-slug-lib.sh" \
   "$SRC_DIR/env-failure-lib.sh" "$SRC_DIR/reviewer-token-lib.sh" "$SRC_DIR/review-lean-lib.sh" \
   "$WORK/skel/q-system/.q-system/scripts/"
G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "control code"
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "https://github.com/example-owner/example-repo.git"
# The PR lives on its own branch off main, so main is a real base branch whose
# merge base with the PR can move (the base-merge cases at the end).
git -C "$WORK/skel" checkout -q -b pr-branch
AGENT="$WORK/skel/q-system/.q-system/scripts/pr-review-agent.sh"

# The PR's first pushed head: one change, ROUND1_LINE.
echo "ROUND1_LINE" >> "$WORK/skel/FILE.txt"
G -C "$WORK/skel" commit -q -am "round 1 work"
SHA1="$(git -C "$WORK/skel" rev-parse HEAD)"
echo "$SHA1" > "$WORK/head"

GH_LOG="$WORK/gh-calls.txt"; : > "$GH_LOG"
cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$GH_LOG"
case "\$*" in
  *"pr view"*"headRefOid"*) printf '%s\t%s\n' "\$(cat "$WORK/head")" "a PR title" ;;
  *"pr view"*"baseRefName"*) echo main ;;
  *"pr diff"*)              echo "WHOLE_PR_DIFF_MARKER"; echo "+ROUND1_LINE"; echo "+ROUND2_LINE" ;;
  *"pr comment"*)           echo "https://github.com/example-owner/example-repo/pull/1#issuecomment-1" ;;
  *"commits/"*"/statuses"*) echo "" ;;
  *"api"*)                  echo '{}' ;;
esac
exit 0
EOF
chmod +x "$STUB/gh"

# The engine. It copies the diff file and the prompt it was handed, then
# approves, so a delta round has a verdict to post.
SEEN="$WORK/seen"; mkdir -p "$SEEN"
CLAUDE_LOG="$WORK/claude-calls.txt"; : > "$CLAUDE_LOG"
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
echo call >> "$CLAUDE_LOG"
n="\$(wc -l < "$CLAUDE_LOG" | tr -d ' ')"
for a in "\$@"; do
  p="\$(printf '%s' "\$a" | grep -o '/[^ ]*/pr\.diff' | head -1)"
  if [ -n "\$p" ]; then
    cp "\$p" "$SEEN/call-\$n.diff"
    printf '%s' "\$a" > "$SEEN/call-\$n.prompt"
    break
  fi
done
cat <<'REVIEW'
VERDICT: APPROVE
FINDINGS:
END FINDINGS
REVIEW
exit 0
EOF
chmod +x "$STUB/claude"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/codex"; chmod +x "$STUB/codex"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/notify"; chmod +x "$STUB/notify"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub"

calls() { wc -l <"$CLAUDE_LOG" | tr -d ' '; }
run_reviewer() {  # run_reviewer <out-file> [extra args...]
  local out="$1"; shift
  # The round cap (3) has its own suite, test-review-round-cap.sh. Raised here so
  # the later cases reach the code under test instead of the cap's early exit 0,
  # which is what the first run of this file measured.
  ( cd "$WORK/skel" \
    && HOME="$WORK/home" KIPI_STATE_DIR="$WORK/state" KIPI_NOTIFY="$STUB/notify" \
       KIPI_REVIEW_MAX_ROUNDS=20 bash "$AGENT" 1 --engine claude "$@" ) >"$out" 2>&1
  echo $? > "$out.rc"
}
REC="$WORK/home/.config/kipi/pr-reviews/example-owner_example-repo__pr-1.verdict.json"
rec_field() { python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get(sys.argv[2],""))' "$REC" "$1"; }

# --- round 1: no flag, no prior receipt: reads the WHOLE PR ----------------------
# The negative half of the default: with nothing on record, the default must
# not shrink round 1 to anything less than the whole PR.
run_reviewer "$WORK/r1.out" --post
[ "$(calls)" = "1" ] || fail "round 1 did not reach the stub ($(calls) calls), so every check below is vacuous:
$(tail -20 "$WORK/r1.out")"
[ -f "$SEEN/call-1.diff" ] || fail "the stub found no pr.diff path in the prompt; the capture is broken:
$(tail -20 "$WORK/r1.out")"
grep -q WHOLE_PR_DIFF_MARKER "$SEEN/call-1.diff" \
  || fail "round 1 (no receipt) was not handed the whole PR diff:
$(cat "$SEEN/call-1.diff")"
grep -q 'THIS IS A DELTA ROUND' "$SEEN/call-1.prompt" && fail "round 1 was told it is a delta round"
[ "$(rec_field head_sha)" = "$SHA1" ] || fail "round 1 receipt head_sha is '$(rec_field head_sha)', expected $SHA1"
grep -q "no usable earlier review" "$WORK/r1.out" || fail "round 1 did not log why it read the whole PR:
$(tail -10 "$WORK/r1.out")"
ok "round 1 with no flag and no receipt read the whole PR, said why, and recorded head $SHA1"
sleep 1  # review files are named to the second

# The author pushes a fix on top: ROUND2_LINE.
echo "ROUND2_LINE" >> "$WORK/skel/FILE.txt"
G -C "$WORK/skel" commit -q -am "round 2 fix"
SHA2="$(git -C "$WORK/skel" rev-parse HEAD)"
echo "$SHA2" > "$WORK/head"

# --- round 2: NO flag reads only git diff SHA1 SHA2 -------------------------------
: > "$GH_LOG"
run_reviewer "$WORK/r2.out" --post
[ "$(calls)" = "2" ] || fail "round 2 did not reach the stub:
$(tail -20 "$WORK/r2.out")"
D2="$SEEN/call-2.diff"
grep -q '^+ROUND2_LINE' "$D2" || fail "round 2 diff lacks the new commit's change:
$(cat "$D2")"
grep -q WHOLE_PR_DIFF_MARKER "$D2" && fail "THE DEFECT: round 2 was handed the whole PR diff again:
$(cat "$D2")"
grep -q '^+ROUND1_LINE' "$D2" && fail "round 2 diff re-includes the round-1 change; it must be the delta only:
$(cat "$D2")"
grep -q 'THIS IS A DELTA ROUND' "$SEEN/call-2.prompt" || fail "round 2 prompt does not say it is a delta round"
grep -q "${SHA1:0:12}" "$SEEN/call-2.prompt" || fail "round 2 prompt does not name the base it diffs from"
grep -q "delta: reviewing only ${SHA1:0:12}" "$WORK/r2.out" || fail "round 2 did not log the delta line:
$(tail -10 "$WORK/r2.out")"
ok "round 2 read only git diff ${SHA1:0:8}..${SHA2:0:8}"

grep "statuses/$SHA2" "$GH_LOG" | grep 'context=kipi/reviewer-approved' | grep -q 'state=success' \
  || fail "round 2 did not post kipi/reviewer-approved=success on the NEW head $SHA2:
$(cat "$GH_LOG")"
grep "statuses/$SHA2" "$GH_LOG" | grep 'state=success' | grep -q "delta ${SHA1:0:8}" \
  || fail "the delta status does not say what it covered:
$(grep statuses "$GH_LOG")"
ok "round 2 posted kipi/reviewer-approved=success on the new head, labelled as a delta"
[ "$(rec_field head_sha)" = "$SHA2" ] || fail "round 2 receipt head_sha is '$(rec_field head_sha)', expected $SHA2"
[ "$(rec_field review_base)" = "$SHA1" ] || fail "round 2 receipt review_base is '$(rec_field review_base)', expected $SHA1"
ok "round 2 receipt records head $SHA2 and review_base $SHA1"
sleep 1

# --- no flag on the head already reviewed: a whole read, logged, never a refusal --
# A dry run writes a usable record too, so a refusal here would leave a --post
# run on the same head unable to put a status on it at all.
before="$(calls)"
run_reviewer "$WORK/r3a.out"
[ "$(calls)" = "$((before + 1))" ] || fail "no flag on the reviewed head did not run a review:
$(tail -10 "$WORK/r3a.out")"
[ "$(cat "$WORK/r3a.out.rc")" = "0" ] || fail "no flag on the reviewed head exited $(cat "$WORK/r3a.out.rc")"
grep -q WHOLE_PR_DIFF_MARKER "$SEEN/call-$(calls).diff" || fail "no flag on the reviewed head did not read the whole PR"
grep -q 'reading the whole PR' "$WORK/r3a.out" || fail "the same-head fallback is silent"
ok "no flag on the already-reviewed head: whole PR, logged, exit 0"
sleep 1

# --- --full: the whole PR even with a usable record ------------------------------
# On a NEW head, so the default would have read a delta: on the reviewed head the
# same-head fallback reads the whole PR anyway and this check could not fail.
echo "FULL_LINE" >> "$WORK/skel/FILE.txt"
G -C "$WORK/skel" commit -q -am "full-read case"
git -C "$WORK/skel" rev-parse HEAD > "$WORK/head"
before="$(calls)"
run_reviewer "$WORK/r3.out" --full
[ "$(calls)" = "$((before + 1))" ] || fail "the --full run did not reach the stub"
grep -q WHOLE_PR_DIFF_MARKER "$SEEN/call-$(calls).diff" || fail "--full did not read the whole PR"
grep -q 'THIS IS A DELTA ROUND' "$SEEN/call-$(calls).prompt" && fail "the --full run's prompt says delta"
python3 -c 'import json,sys;sys.exit("review_base" in json.load(open(sys.argv[1])))' "$REC" \
  || fail "the --full run wrote a review_base key"
ok "--full: whole PR, no delta text, no review_base key"
G -C "$WORK/skel" checkout -q "$SHA2"
echo "$SHA2" > "$WORK/head"
sleep 1

# --- --full with --base contradicts itself: refuse --------------------------------
before="$(calls)"
run_reviewer "$WORK/r3b.out" --full --base "$SHA1"
[ "$(calls)" = "$before" ] || fail "--full --base still called the model"
[ "$(cat "$WORK/r3b.out.rc")" != "0" ] || fail "--full --base exited 0"
ok "--full with --base: refused, no model call"

# --- an explicit --base, nothing new since it: refuse, no model call -------------
before="$(calls)"; : > "$GH_LOG"
run_reviewer "$WORK/r4.out" --base "$SHA2" --post
[ "$(calls)" = "$before" ] || fail "--base equal to head still called the model"
[ "$(cat "$WORK/r4.out.rc")" != "0" ] || fail "--base equal to head exited 0; nothing was reviewed"
grep -q 'statuses/' "$GH_LOG" && grep 'statuses/' "$GH_LOG" | grep -q 'state=success' \
  && fail "--base equal to head posted a success status"
grep -q 'nothing to review' "$WORK/r4.out" || fail "the refusal does not say why:
$(tail -10 "$WORK/r4.out")"
ok "--base equal to head: refused, no model call, no status"

# --- an EMPTY delta: refuse, no model call, no status (PR #619 review round 2) ----
# A push whose tree equals the last reviewed tree (an empty commit to re-trigger
# CI, a revert and reapply) is not the same sha, so the sha check above passes
# it. The first cut then handed the engine a 0-byte pr.diff and posted green.
G -C "$WORK/skel" commit -q --allow-empty -m "re-trigger CI"
EMPTY="$(git -C "$WORK/skel" rev-parse HEAD)"
echo "$EMPTY" > "$WORK/head"
before="$(calls)"; : > "$GH_LOG"
run_reviewer "$WORK/r4b.out" --base "$SHA2" --post
[ "$(calls)" = "$before" ] || fail "THE DEFECT: an empty delta still called the model:
$(tail -10 "$WORK/r4b.out")"
[ "$(cat "$WORK/r4b.out.rc")" != "0" ] || fail "an empty delta exited 0; nothing was reviewed"
grep 'statuses/' "$GH_LOG" | grep -q 'state=success' && fail "an empty delta posted a success status:
$(grep statuses "$GH_LOG")"
grep -q 'nothing to review' "$WORK/r4b.out" || fail "the empty-delta refusal does not say why:
$(tail -10 "$WORK/r4b.out")"
ok "an empty delta: refused, no model call, no status"
G -C "$WORK/skel" checkout -q "$SHA2"
echo "$SHA2" > "$WORK/head"

# --- --base with no value: refuse, never a silent full review ---------------------
before="$(calls)"
run_reviewer "$WORK/r4c.out" --base
[ "$(calls)" = "$before" ] || fail "--base with no value still called the model"
[ "$(cat "$WORK/r4c.out.rc")" != "0" ] || fail "--base with no value exited 0"
ok "--base with no value: refused, no model call"

# --- an explicit --base that is not a commit: refuse ------------------------------
before="$(calls)"
run_reviewer "$WORK/r5.out" --base deadbeefdeadbeefdeadbeefdeadbeefdeadbeef
[ "$(calls)" = "$before" ] || fail "an unknown --base still called the model"
[ "$(cat "$WORK/r5.out.rc")" != "0" ] || fail "an unknown --base exited 0"
ok "--base that is not a commit: refused, no model call"

# --- a base that is not an ancestor (a rebase): the safe direction is a full read --
G -C "$WORK/skel" checkout -q -b side main
echo "SIDE" > "$WORK/skel/SIDE.txt"; G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m side
SIDE="$(git -C "$WORK/skel" rev-parse HEAD)"
G -C "$WORK/skel" checkout -q "$SHA2"
run_reviewer "$WORK/r6.out" --base "$SIDE"
n="$(calls)"
grep -q WHOLE_PR_DIFF_MARKER "$SEEN/call-$n.diff" \
  || fail "a non-ancestor base did not fall back to the whole PR:
$(cat "$SEEN/call-$n.diff")"
grep -q 'not an ancestor' "$WORK/r6.out" || fail "the fallback is silent; it must say why"
ok "a non-ancestor base falls back to the whole PR and says so"
sleep 1

# --- an unusable last receipt cannot be a base -----------------------------------
python3 - "$REC" <<'PY'
import json, sys
r = json.load(open(sys.argv[1])); r["usable"] = False
json.dump(r, open(sys.argv[1], "w"))
PY
echo "ROUND3_LINE" >> "$WORK/skel/FILE.txt"
G -C "$WORK/skel" commit -q -am "round 3"
echo "$(git -C "$WORK/skel" rev-parse HEAD)" > "$WORK/head"
before="$(calls)"
run_reviewer "$WORK/r7.out" --delta
n="$(calls)"
[ "$n" = "$((before + 1))" ] || fail "--delta did not reach the model; the alias is dead:
$(tail -5 "$WORK/r7.out")"
grep -q WHOLE_PR_DIFF_MARKER "$SEEN/call-$n.diff" \
  || fail "an unusable receipt was used as a delta base; nobody reviewed that sha:
$(cat "$SEEN/call-$n.diff")"
ok "an unusable last receipt falls back to the whole PR (and --delta is still accepted)"

sleep 1

# --- a range that crosses a merge of the base branch: whole PR (PR #821 r1) ------
# pr-owner.py's `gh pr update-branch` writes a merge of main onto the branch. A
# two-dot delta over it carries main's own commits into pr.diff. Shape 1: the
# new head is ONLY that merge. Shape 2: the merge plus a fix commit.
PRHEAD="$(git -C "$WORK/skel" rev-parse HEAD)"
set_record() {  # set_record <head_sha>: a usable record whose head is the given sha
  python3 - "$REC" "$1" <<'PYX'
import json, sys
r = json.load(open(sys.argv[1])); r["head_sha"] = sys.argv[2]; r["usable"] = True
json.dump(r, open(sys.argv[1], "w"))
PYX
}
G -C "$WORK/skel" checkout -q main
echo "MAIN_ONLY" > "$WORK/skel/MAIN_ONLY.txt"; G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "main moves on"
G -C "$WORK/skel" checkout -q "$PRHEAD"
G -C "$WORK/skel" merge -q --no-edit main
git -C "$WORK/skel" rev-parse HEAD > "$WORK/head"
for shape in merge-only merge-plus-fix; do
  if [ "$shape" = "merge-plus-fix" ]; then
    echo "FIX_AFTER_MERGE" >> "$WORK/skel/FILE.txt"; G -C "$WORK/skel" commit -q -am "fix after merge"
    git -C "$WORK/skel" rev-parse HEAD > "$WORK/head"
  fi
  set_record "$PRHEAD"
  before="$(calls)"
  run_reviewer "$WORK/r8-$shape.out"
  n="$(calls)"
  [ "$n" = "$((before + 1))" ] || fail "$shape: the review did not run:
$(tail -5 "$WORK/r8-$shape.out")"
  grep -q MAIN_ONLY "$SEEN/call-$n.diff" && fail "THE DEFECT ($shape): base-branch code is in pr.diff:
$(cat "$SEEN/call-$n.diff")"
  grep -q WHOLE_PR_DIFF_MARKER "$SEEN/call-$n.diff" || fail "$shape: a range across a base merge did not read the whole PR"
  grep -q 'crosses a merge of base branch' "$WORK/r8-$shape.out" || fail "$shape: the fallback is silent"
  ok "$shape: a range across a merge of main reads the whole PR and says why"
  sleep 1
done

echo "PASS ($PASS checks) test-review-delta-round.sh"
