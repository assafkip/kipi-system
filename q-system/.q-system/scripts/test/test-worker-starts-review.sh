#!/usr/bin/env bash
# The worker starts the review a PR with no verdict is waiting for (ASK-5846).
#
# WHY THIS EXISTS. Measured 2026-11-27: at the gate-20 skip the worker printed
# "run: kipi review N --issue ASK-n --post" and no script ran it. PR #903 sat 5h,
# #896 and #902 sat 7 to 11h, until the orchestrator ran the reviews by hand.
#
# WHAT IS PINNED, through review_unreviewed_pr lifted from linear-worker.sh and
# the real pr-verdict-lib.sh / repo-slug-lib.sh, with a stub reviewer:
#   1. a PR with no verdict record calls the reviewer exactly once, with --post;
#   2. a PR that already has a verdict does not call it;
#   3. a reviewer that writes no verdict (rc=5) is said, not reported as done;
#   4. the gate-20 branch calls it instead of printing the command.
# No network, no real reviewer: REVIEWS_DIR is a temp dir.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SCRIPTS="$ROOT/q-system/.q-system/scripts"
WORKER="${KIPI_WORKER_UNDER_TEST:-$SCRIPTS/linear-worker.sh}"
PASS=0; FAIL=0
ok()  { PASS=$((PASS + 1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; [ -n "${2:-}" ] && printf '       %s\n' "$2"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
FN="$(awk '/^review_unreviewed_pr\(\) \{/ {on=1} on {print} on && /^}/ {exit}' "$WORKER")"
[ -n "$FN" ] || { echo "FATAL: review_unreviewed_pr() is not in $WORKER" >&2; exit 1; }
# shellcheck disable=SC1090,SC1091
. "$SCRIPTS/repo-slug-lib.sh"
# shellcheck disable=SC1091
. "$SCRIPTS/pr-verdict-lib.sh"
eval "$FN"
LOG="$WORK/worker.log"; : > "$LOG"
say() { echo "$*" | tee -a "$LOG"; }
REVIEWS_DIR="$WORK/reviews"; mkdir -p "$REVIEWS_DIR"
TARGET_SLUG="example-owner/example-repo"
CALLS="$WORK/calls"; : > "$CALLS"
# The stub reviewer: logs its argv; in "write" mode it writes the verdict record
# the real reviewer would, in "refuse" mode it exits 5 and writes nothing.
cat > "$WORK/reviewer.sh" <<EOF
echo "\$*" >> "$CALLS"
[ "\$(cat "$WORK/mode")" = "refuse" ] && exit 5
printf '{"verdict": "APPROVE", "head_sha": "abc"}' > "\$(cd "$SCRIPTS" && . ./repo-slug-lib.sh && . ./pr-verdict-lib.sh && verdict_record_path "$REVIEWS_DIR" "$TARGET_SLUG" "\$1")"
EOF
REVIEWER_CMD="bash $WORK/reviewer.sh"
# The real attempts ledger, on a temp file: the brake is its locked claim-flag.
LEDGER="$SCRIPTS/attempts-ledger.py"
export KIPI_NOTIFY=/usr/bin/true   # the ledger can reach slack-notify.sh; never from a test
ATTEMPTS="$WORK/attempts.json"; echo '{}' > "$ATTEMPTS"
echo aaaaaaaaaaaa1111 > "$WORK/head"
pr_head_sha() { cat "$WORK/head"; }

# 1. No record: one call, with exactly the reviewer's scheduled argv.
echo write > "$WORK/mode"
review_unreviewed_pr 77 ASK-77 >/dev/null
[ "$(grep -c . "$CALLS")" = "1" ] && grep -qx '77 --issue ASK-77 --post --engine claude' "$CALLS" \
  && ok "a PR with no verdict calls the reviewer once: N --issue ASK-n --post --engine claude" \
  || bad "expected one reviewer call for PR 77 with the full argv" "$(cat "$CALLS")"
grep -q "review recorded 'APPROVE'" "$LOG" && ok "the recorded verdict is said" || bad "no verdict line" "$(cat "$LOG")"

# 2. A verdict already recorded: no call.
: > "$CALLS"
review_unreviewed_pr 77 ASK-77 >/dev/null
[ ! -s "$CALLS" ] && ok "a PR that already has a verdict does not call the reviewer" \
  || bad "the reviewer ran over an existing verdict" "$(cat "$CALLS")"

# 3. The reviewer writes no verdict (rc=5): one call, said as no verdict.
: > "$CALLS"; : > "$LOG"; echo refuse > "$WORK/mode"
review_unreviewed_pr 78 ASK-78 >/dev/null; rc=$?
[ "$(grep -c . "$CALLS")" = "1" ] && [ "$rc" = "5" ] \
  && ok "a refused reviewer is called once and its rc=5 comes back" \
  || bad "refused reviewer: calls=$(grep -c . "$CALLS") rc=$rc"
grep -q 'wrote no verdict (rc=5)' "$LOG" && ok "a run that wrote no verdict says so" || bad "no-verdict line missing" "$(cat "$LOG")"

# 3b. THE BRAKE: the same head is not reviewed again on the next tick.
: > "$CALLS"
review_unreviewed_pr 78 ASK-78 >/dev/null
[ ! -s "$CALLS" ] && ok "the next tick on the same head starts no second paid review" \
  || bad "a second review ran on the same head" "$(cat "$CALLS")"
# A push is new code and earns its own start.
echo bbbbbbbbbbbb2222 > "$WORK/head"
review_unreviewed_pr 78 ASK-78 >/dev/null
[ "$(grep -c . "$CALLS")" = "1" ] && ok "a new head earns one new review" \
  || bad "a new head: $(grep -c . "$CALLS") calls"

# 3c. rc=9 is the machine's code: env_halt is claimed, the way step 5 does it.
: > "$CALLS"; echo cccccccccccc3333 > "$WORK/head"
cat > "$WORK/reviewer.sh" <<EOF
echo "\$*" >> "$CALLS"; exit 9
EOF
review_unreviewed_pr 79 ASK-79 >/dev/null; rc=$?
[ "$rc" = "9" ] && [ "$(python3 "$LEDGER" "$ATTEMPTS" get ASK-79 env_halt "")" = "True" ] \
  && ok "a reviewer rc=9 claims env_halt (no 'no verdict' page for an exhausted account)" \
  || bad "rc=9: rc=$rc env_halt=$(python3 "$LEDGER" "$ATTEMPTS" get ASK-79 env_halt "")"
# A machine refusal does not spend the head's start: the next run tries again.
: > "$CALLS"
review_unreviewed_pr 79 ASK-79 >/dev/null
[ "$(grep -c . "$CALLS")" = "1" ] && ok "after rc=9 the same head is started again once the runner answers" \
  || bad "rc=9 spent the head's only start ($(grep -c . "$CALLS") calls on retry)"

# 3d. A review already running for this PR (review-redrive.py's): none started.
: > "$CALLS"; echo dddddddddddd4444 > "$WORK/head"
( exec -a "pr-review-agent.sh 80 --issue ASK-80 --post" sleep 30 ) &
live=$!
sleep 0.3
review_unreviewed_pr 80 ASK-80 >/dev/null
kill "$live" 2>/dev/null; wait "$live" 2>/dev/null
[ ! -s "$CALLS" ] && ok "a review already running for the PR is not started twice" \
  || bad "a second review started beside a live one" "$(cat "$CALLS")"
review_unreviewed_pr 80 ASK-80 >/dev/null
[ "$(grep -c . "$CALLS")" = "1" ] && ok "once that review is gone, the start is still available for the head" \
  || bad "the live-review skip spent the head's start"

# 4. The gate-20 branch runs it; the print-the-command line is gone.
G20="$(awk '/if \[ "\$GATE" = "20" \]; then/ {on=1} on {print} on && /^    fi$/ {exit}' "$WORKER")"
printf '%s' "$G20" | grep -q 'review_unreviewed_pr "\$EXISTING_PR" "\$ISSUE"' \
  && ok "the gate-20 branch starts the review" || bad "gate 20 does not call review_unreviewed_pr" "$G20"
grep -q -- '-- run: kipi review \$EXISTING_PR' "$WORKER" \
  && bad "the worker still prints the review command for nobody" || ok "the print-the-command skip is gone"

echo "PASS: $PASS  FAIL: $FAIL"
[ "$FAIL" = 0 ]
