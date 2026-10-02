#!/usr/bin/env bash
# The review round cap: past KIPI_REVIEW_MAX_ROUNDS (default 3) reviews of one
# PR, pr-review-agent.sh must refuse to call the model at all.
#
# THE DEFECT. Every call ran a full model review and nothing bounded the count
# per PR. Rounds of 4 to 7 were routine and one PR took 16, each a full paid
# run. A round counter already existed (review_round) but only fed a prompt
# hint, so the loop that kept re-invoking the reviewer had no brake.
#
# WHAT RED LOOKS LIKE. A stub `claude` appends one line per invocation to a
# log. Rounds 1-3 must each call it once (positive control: the stub really is
# the engine the script dispatches, so a 0 below is not a broken stub). The
# 4th run must add ZERO lines, exit 0, post one short comment and a pending
# status. Delete the cap block and the 4th run calls the stub again: red.
#
# Isolation: HOME, KIPI_STATE_DIR, the repo, `gh` and `claude` are fixtures in
# a mktemp dir. No live PR is read and no model is spent.
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
unset KIPI_TARGET_REPO KIPI_REVIEW_ENGINE KIPI_REVIEW_PRIMARY_ENGINE KIPI_REVIEW_MAX_ROUNDS 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB"

mkdir -p "$WORK/skel/q-system/.q-system/scripts"
git init -q "$WORK/skel"
echo "code" > "$WORK/skel/FILE.txt"
cp "$SRC_DIR/pr-review-agent.sh" "$SRC_DIR/pr-verdict-lib.sh" "$SRC_DIR/repo-slug-lib.sh" \
   "$SRC_DIR/env-failure-lib.sh" "$SRC_DIR/reviewer-token-lib.sh" \
   "$WORK/skel/q-system/.q-system/scripts/"
G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "control code"
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "https://github.com/example-owner/example-repo.git"
AGENT="$WORK/skel/q-system/.q-system/scripts/pr-review-agent.sh"
SHA="$(git -C "$WORK/skel" rev-parse HEAD)"

GH_LOG="$WORK/gh-calls.txt"; : > "$GH_LOG"
cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$GH_LOG"
case "\$*" in
  *"pr view"*"headRefOid"*) printf '%s\t%s\n' "$SHA" "a PR title" ;;
  *"pr diff"*)              echo "diff --git a/FILE.txt b/FILE.txt" ;;
  *"pr comment"*)           echo "https://github.com/example-owner/example-repo/pull/1#issuecomment-1" ;;
  *"commits/"*"/statuses"*) cat "$WORK/cur-state" 2>/dev/null ;;
  *"api"*)                  echo '{}' ;;
esac
exit 0
EOF
chmod +x "$STUB/gh"

# The engine under count. A REQUEST CHANGES review, so every round is the kind
# that would send the loop back for another one.
CLAUDE_LOG="$WORK/claude-calls.txt"; : > "$CLAUDE_LOG"
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
echo call >> "$CLAUDE_LOG"
# An environmental failure: output with no findings block, as a provider blip leaves.
[ -s "$WORK/blip" ] && { echo "API Error: 529 overloaded"; exit 0; }
cat <<'REVIEW'
VERDICT: REQUEST CHANGES
FINDINGS:
severity|file|line|what
major|FILE.txt|1|still wrong
END FINDINGS
REVIEW
exit 0
EOF
chmod +x "$STUB/claude"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/codex"; chmod +x "$STUB/codex"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub"

NOTIFY_LOG="$WORK/notify.txt"; : > "$NOTIFY_LOG"
cat > "$STUB/notify" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$NOTIFY_LOG"
EOF
chmod +x "$STUB/notify"
calls() { wc -l <"$CLAUDE_LOG" | tr -d ' '; }
run_reviewer() {  # run_reviewer <out-file> [extra args...]
  local out="$1"; shift
  ( cd "$WORK/skel" \
    && HOME="$WORK/home" KIPI_STATE_DIR="$WORK/state" KIPI_NOTIFY="$STUB/notify" \
       bash "$AGENT" 1 --engine claude "$@" ) >"$out" 2>&1
  echo $? > "$out.rc"
}

# Two provider blips first. They reach the model but produce no usable review,
# so they must NOT count toward the cap (PR review round 1, major 1).
echo 1 > "$WORK/blip"
for n in a b; do run_reviewer "$WORK/blip$n.out" --post; sleep 1; done
: > "$WORK/blip"
[ "$(calls)" = "2" ] || fail "blip runs did not reach the stub ($(calls) calls)"
: > "$CLAUDE_LOG"
ok "two unusable (blip) rounds ran"

# Rounds 1-3: each one must reach the model exactly once.
for n in 1 2 3; do
  before="$(calls)"
  run_reviewer "$WORK/r$n.out" --post; sleep 1  # review files are named to the second
  after="$(calls)"
  [ "$after" = "$((before + 1))" ] \
    || fail "round $n made $((after - before)) model calls, expected 1 (the stub is not the dispatched engine, so every count below is vacuous):
$(tail -20 "$WORK/r$n.out")"
done
ok "positive control: rounds 1-3 each called the model once ($(calls) calls)"

# Round 4: the cap.
: > "$GH_LOG"
before="$(calls)"
run_reviewer "$WORK/r4.out" --post
after="$(calls)"
echo "  [ctx] round 4 rc=$(cat "$WORK/r4.out.rc") model calls=$((after - before))"
[ "$after" = "$before" ] \
  || fail "round 4 called the model $((after - before)) time(s); past the cap it must make 0:
$(tail -20 "$WORK/r4.out")"
ok "round 4 made 0 model calls"

[ "$(cat "$WORK/r4.out.rc")" = "0" ] || fail "round 4 exited $(cat "$WORK/r4.out.rc"); the cap refusal must exit 0"
ok "round 4 exited 0"

grep -q 'pr comment' "$GH_LOG" || fail "round 4 posted no PR comment:
$(cat "$GH_LOG")"
grep -q 'review cap reached (3); needs a human decision' "$WORK/r4.out" \
  || fail "round 4 output does not carry the cap message:
$(tail -20 "$WORK/r4.out")"
ok "round 4 posted the cap comment"

grep "statuses/$SHA" "$GH_LOG" | grep -q 'state=pending' \
  || fail "round 4 did not set a pending status on the head sha:
$(cat "$GH_LOG")"
grep "statuses/$SHA" "$GH_LOG" | grep -q 'context=kipi/reviewer-approved' \
  || fail "the pending status is not on kipi/reviewer-approved"
ok "round 4 set kipi/reviewer-approved=pending on the head sha"

[ "$(grep -c 'review round cap' "$NOTIFY_LOG")" = "1" ] \
  || fail "the cap did not alert the engineering queue exactly once:
$(cat "$NOTIFY_LOG")"
ok "round 4 alerted the engineering queue once"

# Round 5: still capped, still 0 calls, and the comment is not repeated.
: > "$GH_LOG"
before="$(calls)"
run_reviewer "$WORK/r5.out" --post
[ "$(calls)" = "$before" ] || fail "round 5 called the model past the cap"
grep -q 'pr comment' "$GH_LOG" && fail "round 5 posted the cap comment again; it must be posted once per PR"
[ "$(grep -c 'review round cap' "$NOTIFY_LOG")" = "1" ] || fail "round 5 alerted again"
ok "round 5: 0 model calls, no repeat comment or alert"

# An approved sha is never downgraded by the cap (PR review round 1, major 2).
echo success > "$WORK/cur-state"; : > "$GH_LOG"
run_reviewer "$WORK/r5b.out" --post
grep -q 'state=pending' "$GH_LOG" && fail "the cap posted pending over an existing success status:
$(cat "$GH_LOG")"
grep -q 'commits/.*/statuses' "$GH_LOG" || fail "the cap never read the current status, so the no-downgrade check is vacuous"
: > "$WORK/cur-state"
ok "an existing success status is left alone"

# The env var moves the cap: at 5, the next run reaches the model again.
before="$(calls)"
KIPI_REVIEW_MAX_ROUNDS=5 run_reviewer "$WORK/r6.out" --post
[ "$(calls)" = "$((before + 1))" ] \
  || fail "KIPI_REVIEW_MAX_ROUNDS=5 did not lift the cap for round 4:
$(tail -20 "$WORK/r6.out")"
ok "KIPI_REVIEW_MAX_ROUNDS raises the cap"

echo "PASS ($PASS checks) test-review-round-cap.sh"
