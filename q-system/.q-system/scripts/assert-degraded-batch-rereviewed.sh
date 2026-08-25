#!/usr/bin/env bash
# Pairs with: ASK-445, the re-review of the 2026-08-06 degraded batch.
#
# WHY THIS EXISTS. ASK-445's Definition of Ready says, in its own words: "No
# script exists that asserts this across the whole batch at once; a one-off jq
# pass over the verdict records would have to be written if you want a single
# green/red." This is that script, kept rather than thrown away, because the
# batch's done-condition is otherwise eight separate eyeball checks and an
# eyeball check is not a gate.
#
# WHAT IT ASSERTS, per batch item: a verdict record exists, `degraded` is false,
# and `reviewed_by` names a Codex model rather than a Claude one. That last
# clause is the whole point of the issue -- everything in this batch was reviewed
# by the Claude fallback on 2026-08-06, same model family as the author, so the
# blind spots correlated. A record that is present but still reviewed_by a claude
# model is a re-review that did not happen.
#
# IT READS THROUGH repo-slug-lib.sh's RESOLVER, never its own copy of the naming
# rule. A second place that knows where verdict records live is a second reader
# that drifts from the writer -- the defect class this repo keeps finding, and the
# reason verdict_record_path exists as one function in the first place.
#
# HONEST BOUNDARY, read the green narrowly:
#   - It checks a record EXISTS and what it says. It cannot check the review was
#     any good, or that its findings were triaged. That is a human/triage step.
#   - `reviewed_by` is matched against a claude-model denylist, not a codex
#     allowlist, so a future engine name it has never heard of reads as PASS.
#     Deliberate: an allowlist here goes stale into a false RED on the day a
#     model id changes, and a gate that is red for the wrong reason gets switched
#     off. The engine field is printed on every row so the drift is visible.
#   - Items with no PR number (a bare branch) cannot be checked here at all and
#     are reported SKIP with their reason, never silently dropped.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
. "$HERE/repo-slug-lib.sh"

OUT_DIR="${KIPI_PR_REVIEW_DIR:-$HOME/.config/kipi/pr-reviews}"
SLUG="${KIPI_REVIEW_SLUG:-assafkip_kipi-system}"

# WHICH DIRECTORY THE RECORD IS IN IS DERIVED, NOT ASSUMED. pr-review-agent.sh
# puts the verdict record for the PRIMARY engine at $OUT_DIR and the advisory
# engine's at $OUT_DIR/<engine>; the per-engine `codex/` subdirectory holds the
# review MARKDOWN and round counter either way. The first version of this script
# hardcoded $OUT_DIR/codex and reported all seven items missing while seven
# non-degraded codex records sat one directory up -- a false RED, and exactly the
# second-reader drift the header above warns about. Read the same two env vars
# the writer reads.
PRIMARY_ENGINE="${KIPI_REVIEW_PRIMARY_ENGINE:-codex}"
if [ "$PRIMARY_ENGINE" = "codex" ]; then
  CODEX_DIR="$OUT_DIR"
else
  CODEX_DIR="$OUT_DIR/codex"
fi

# The 2026-08-06 degraded batch, exactly as ASK-445 scopes it.
BATCH_PRS="114 115 116 117 118 123 112"

fails=0
skips=0

echo "ASK-445 degraded-batch re-review assertion"
echo "  records dir: $CODEX_DIR"
echo "  repo slug:   $SLUG"
echo

for pr in $BATCH_PRS; do
  rec="$(verdict_record_path "$CODEX_DIR" "$SLUG" "$pr")"
  if [ ! -f "$rec" ]; then
    echo "  FAIL #$pr: no codex verdict record at $rec"
    fails=$((fails + 1))
    continue
  fi
  read -r degraded reviewed_by engine verdict <<<"$(
    python3 - "$rec" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print(d.get("degraded"), d.get("reviewed_by") or "-",
      d.get("engine") or "-", (d.get("verdict") or "-").replace(" ", "_"))
PY
  )"
  row="#$pr degraded=$degraded reviewed_by=$reviewed_by engine=$engine verdict=${verdict//_/ }"
  if [ "$degraded" != "False" ]; then
    echo "  FAIL $row  <- still degraded"
    fails=$((fails + 1))
  elif printf '%s' "$reviewed_by" | grep -qiE 'claude|opus|sonnet|haiku'; then
    echo "  FAIL $row  <- reviewed by a Claude model, which is what this batch is re-reviewing"
    fails=$((fails + 1))
  else
    echo "  PASS $row"
  fi
done

# sana/scs-validated-event-fold has no PR number, so pr-review-agent.sh -- which
# takes a PR number and checks out that PR's head -- has nothing to address it
# by. Reported, never silently dropped (no-orphan-findings.md).
echo "  SKIP sana/scs-validated-event-fold: no PR exists for this branch, and"
echo "       pr-review-agent.sh addresses work by PR number only."
skips=$((skips + 1))

echo
echo "batch: $(printf '%s' "$BATCH_PRS" | wc -w | tr -d ' ') PRs checked, $fails failing, $skips skipped"

# A SKIP MUST NOT BE ABLE TO PRODUCE EXIT 0, and this is a fix, not a nicety.
# The first version returned 0 whenever `fails` was 0, so it exited successfully
# while announcing that one of its eight scoped items had never been re-reviewed
# -- a caller reading only the exit code was told the batch was complete when it
# was not (codex major, PR #255). "Every PR passed" and "the batch is covered"
# are different claims and this script makes both, so it needs more than two
# outcomes to say which one holds.
#
# THREE STATES, so the exit code carries the same truth as the prose:
#   0 = every scoped item checked and passing. The batch really is covered.
#   1 = a scoped PR lacks a non-degraded Codex re-review. Actionable: re-run it.
#   2 = every PR checked passes, but coverage is INCOMPLETE because an item
#       could not be addressed at all. Not actionable by re-running anything.
#
# 2 rather than 1 on purpose: an item with no PR number cannot be fixed by
# running the reviewer again, so collapsing it into the failure code would tell
# an operator to retry something that has no retry. It also keeps this script
# out of any pass/fail gate by construction, which is the posture the commit
# that added it already argued for -- it is red on its own population until that
# branch gets a PR, and a gate red for a reason nobody can clear gets ignored.
if [ "$fails" -eq 0 ] && [ "$skips" -eq 0 ]; then
  echo "RESULT: every item in the 2026-08-06 degraded batch has a non-degraded Codex re-review on record."
  exit 0
fi
if [ "$fails" -eq 0 ]; then
  echo "RESULT: all $(printf '%s' "$BATCH_PRS" | wc -w | tr -d ' ') PRs checked have a non-degraded Codex re-review, but batch coverage is INCOMPLETE: $skips item(s) could not be checked at all (see SKIP above). Do not read this run as the batch being done." >&2
  exit 2
fi
echo "RESULT: $fails item(s) still lack a non-degraded Codex re-review." >&2
exit 1
