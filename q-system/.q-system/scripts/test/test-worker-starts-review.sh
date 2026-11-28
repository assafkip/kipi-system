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

# 1. No record: one call, with --post and the issue.
echo write > "$WORK/mode"
review_unreviewed_pr 77 ASK-77 >/dev/null
[ "$(grep -c . "$CALLS")" = "1" ] && grep -q '^77 --issue ASK-77 --post' "$CALLS" \
  && ok "a PR with no verdict calls the reviewer once, with --issue and --post" \
  || bad "expected one reviewer call for PR 77" "$(cat "$CALLS")"
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

# 4. The gate-20 branch runs it; the print-the-command line is gone.
G20="$(awk '/if \[ "\$GATE" = "20" \]; then/ {on=1} on {print} on && /^    fi$/ {exit}' "$WORKER")"
printf '%s' "$G20" | grep -q 'review_unreviewed_pr "\$EXISTING_PR" "\$ISSUE"' \
  && ok "the gate-20 branch starts the review" || bad "gate 20 does not call review_unreviewed_pr" "$G20"
grep -q -- '-- run: kipi review \$EXISTING_PR' "$WORKER" \
  && bad "the worker still prints the review command for nobody" || ok "the print-the-command skip is gone"

echo "PASS: $PASS  FAIL: $FAIL"
[ "$FAIL" = 0 ]
