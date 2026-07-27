#!/usr/bin/env bash
# THE review agent for every PR in this fleet. Fresh eyes, adversarial, reproducer-or-it-didn't-happen.
#
# WHO IT IS
# ---------
# A senior staff engineer from Netflix who has never seen this codebase. That
# persona is chosen for two specific properties, not for flavour:
#
#   FRESH EYES. It has no memory of why anything here is the way it is, so it
#   cannot be talked out of a finding by a comment that says "this is fine". The
#   author of this repo (and the agent that wrote the PR) share one mental model;
#   a reviewer inside that model re-derives the same blind spots. Measured on this
#   very fleet 2026-07-26: a hand-rolled test fixture used a JSON key no producer
#   emits, so a mutex's remote half never fired while its suite stayed green. Only
#   an outsider checking the real payload caught it.
#
#   OPERATIONAL BAR. Netflix staff review is about what happens at 3am: blast
#   radius, failure modes, what pages a human, what cannot be rolled back. This
#   fleet runs unattended agents against permanent Linear objects and a public
#   repo. That is exactly the bar it needs.
#
# THE STANDING RULE
# -----------------
# EVERY finding must ship a RUNNABLE REPRODUCER that was actually executed. A
# finding with no repro is an opinion and is rejected at triage. This is not
# politeness: the substitute reviewer earned its keep on 2026-07-25 and 07-26 by
# producing repros, and the same discipline is what stops an adversarial reviewer
# from generating plausible-sounding noise.
#
# PROVENANCE
# ----------
# Reviews are recorded as `claude-adversarial`, which findings_writer.py accepts
# as a REVIEWER_SOURCE. It did not before 2026-07-26: a Claude reviewer had to
# either stamp `codex-adversarial` (a false record) or skip the stamp and never
# approve. In a repo whose thesis is receipts, the honest token had to exist first.
#
# Usage:  pr-review-agent.sh <pr-number> [--issue ASK-nnn] [--post]
#         --post also comments the review on the PR and the Linear issue.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKEL="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SYNC="$SCRIPT_DIR/linear-sync.py"
OUT_DIR="$HOME/.config/kipi/pr-reviews"
TIMEOUT_SECONDS=2400
# Verdict semantics live in ONE place, shared with the worker. Two scripts each
# grepping the review prose with their own regex is two readers with different
# semantics -- the defect class review round 2 flagged on this very PR line.
. "$SCRIPT_DIR/pr-verdict-lib.sh"

PR=""; ISSUE=""; POST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --issue) shift; ISSUE="${1:-}" ;;
    --post)  POST=1 ;;
    -*) echo "unknown arg: $1" >&2; exit 1 ;;
    *) PR="$1" ;;
  esac
  shift || true
done
[ -n "$PR" ] || { echo "usage: pr-review-agent.sh <pr-number> [--issue ASK-nnn] [--post]" >&2; exit 1; }

mkdir -p "$OUT_DIR"
TS() { date -u +%Y-%m-%dT%H:%M:%SZ; }
REVIEW="$OUT_DIR/pr-$PR-$(date +%Y%m%d-%H%M%S).md"

# Same bash wall clock as the worker: macOS ships no `timeout` without coreutils,
# and a review that never returns is worse than one that fails.
run_bounded() {
  local secs="$1"; shift
  "$@" & local job=$!
  ( sleep "$secs"; kill -0 "$job" 2>/dev/null && { kill -TERM "$job" 2>/dev/null; sleep 5; kill -KILL "$job" 2>/dev/null; } ) &
  local w=$!; wait "$job"; local rc=$?; kill "$w" 2>/dev/null; wait "$w" 2>/dev/null; return "$rc"
}

command -v gh >/dev/null 2>&1 || { echo "gh CLI required" >&2; exit 1; }
PR_TITLE="$(gh pr view "$PR" --json title -q .title 2>/dev/null)" || { echo "no PR #$PR" >&2; exit 1; }
[ -n "$ISSUE" ] || ISSUE="$(printf '%s' "$PR_TITLE" | grep -oE 'ASK-[0-9]+' | head -1)"

echo "$(TS) reviewing PR #$PR: $PR_TITLE"
[ -n "$ISSUE" ] && echo "  linked issue: $ISSUE"

PROMPT="You are a SENIOR STAFF ENGINEER at Netflix. You have NEVER seen this codebase before.
You were asked to review pull request #$PR in $SKEL, and you are ADVERSARIAL by default:
your job is to find what is wrong, not to be agreeable.

## Read the change

  gh pr view $PR
  gh pr diff $PR

## What your fresh eyes are FOR

You have no memory of why anything here is the way it is. That is the point. Do NOT
accept a comment, a commit message, or a doc as evidence — those are the author's
claims about the code, written by the same mind that wrote the bug. Read what the
code DOES. Where a comment and the code disagree, the code is the truth and the
comment is a finding.

Be specifically suspicious of:
- **Test fixtures the author invented.** A fixture built from the same mental model
  as the code tests nothing. Check that every fixture's SHAPE matches what the real
  producer actually emits. This fleet has already shipped a mutex whose remote half
  never fired because its fixture used a key no producer emits, while the suite was green.
- **Tests that could not fail.** For each new test ask: what would break to make this
  red? If nothing plausible would, it is decoration.
- **Claims of enforcement.** 'This ensures X' in a comment is not enforcement. Find
  the code path that refuses, or call it a finding.
- **Error paths, retries, partial failure.** What is left behind when this dies
  halfway? What does the operator see?

## The operational bar (this is the Netflix part)

This fleet runs UNATTENDED agents on a schedule, against Linear objects that CANNOT
BE DELETED, in a PUBLIC repo. So judge it that way:
- What happens at 3am when this fires and nobody is watching?
- What is the blast radius of it being wrong? What is permanent and unrecoverable?
- What pages a human, and is that signal or noise? A checker that cries wolf trains
  the operator to ignore it, which costs the real alert later.
- Can this be rolled back? If not, say so loudly.
- Concurrency: two of these running at once. What breaks?

## THE STANDING RULE — non-negotiable

EVERY finding MUST ship a RUNNABLE REPRODUCER that you ACTUALLY RAN, with its real
output pasted. A finding with no executed repro is an opinion and will be rejected.
Write repros to \$TMPDIR and run them. If you cannot make it fail, DROP the finding
and say you tried. Dropping a finding you could not reproduce is a SUCCESS of this
process, not a failure of it.

Never modify the repo. Read-only review. Do not commit, do not push.

## Output

For each finding: SEVERITY (blocker|major|minor|nit), a one-sentence claim, the exact
file:line, the reproducer command, and its REAL output.

Then:
- **What is sound** — attacks you tried that the code survived. Name them. A review
  that only lists faults is not calibrated and cannot be trusted on the faults.
- **VERDICT:** decided by THIS RULE, not by feel:
    - any blocker or major finding      => REQUEST CHANGES (BLOCK only if merging
      as-is would cause permanent or unrecoverable damage)
    - only minor/nit findings           => APPROVE WITH NITS
    - no finding survived reproduction  => APPROVE
  A bar this high ALWAYS finds something; that is what APPROVE WITH NITS is for.
  On APPROVE WITH NITS the pipeline captures every minor as a tracked follow-up,
  so approving with nits does NOT lose them. Using REQUEST CHANGES to log minors
  wedges the PR forever and is itself a review defect.
  State the verdict and the single most important thing to fix first.
- **Last, a machine-readable findings block**, EXACTLY this shape, one line per
  finding, empty block if none. The pipeline parses it; keep prose out of it:

FINDINGS:
severity|one-sentence claim|file:line
END FINDINGS"

echo "$(TS) running the reviewer (bounded at ${TIMEOUT_SECONDS}s)..."
if run_bounded "$TIMEOUT_SECONDS" bash -c "cd '$SKEL' && claude -p \"\$1\" </dev/null > '$REVIEW' 2>&1" _ "$PROMPT"; then
  echo "$(TS) review written: $REVIEW"
else
  rc=$?
  echo "$(TS) reviewer failed or timed out (rc=$rc). Partial output: $REVIEW" >&2
  exit "$rc"
fi

VERDICT="$(extract_verdict "$REVIEW")"
echo "  verdict: ${VERDICT:-unstated}"

# Single writer for verdict state. The worker's rework gate reads THIS record,
# never the review prose. Keyed by PR number, latest round wins; history stays
# in the timestamped .md files.
python3 - "$PR" "$ISSUE" "$VERDICT" "$REVIEW" "$(TS)" <<'PY'
import json, sys
pr, issue, verdict, review, ts = sys.argv[1:6]
out = review.rsplit("/", 1)[0] + f"/pr-{pr}.verdict.json"
json.dump({"pr": int(pr), "issue": issue, "verdict": verdict,
           "review": review, "ts": ts}, open(out, "w"), indent=2)
PY

# Severity floor, capture half: APPROVE WITH NITS is a TERMINAL state -- the
# loop stops reworking -- so each minor must land in the spillover ledger or it
# evaporates (no-orphan-findings.md). On REQUEST CHANGES the minors ride along
# in the review, which is the spec for the next rework pass; capturing them
# there too would double-file them.
if [ "$VERDICT" = "APPROVE WITH NITS" ] && [ -n "$ISSUE" ]; then
  CAPTURED=0
  MINOR_COUNT=0
  while IFS='|' read -r _sev claim loc; do
    [ -n "$claim" ] || continue
    MINOR_COUNT=$((MINOR_COUNT+1))
    python3 "$SKEL/plugins/prd-os/scripts/prd_runner.py" spillover add \
      --source "$ISSUE" --desc "PR #$PR review minor: $claim ($loc)" >/dev/null 2>&1 \
      && CAPTURED=$((CAPTURED+1))
  done <<EOF
$(extract_minor_findings "$REVIEW")
EOF
  echo "  minors captured as spillover: $CAPTURED of $MINOR_COUNT"
fi

if [ "$POST" = "1" ]; then
  gh pr comment "$PR" --body-file "$REVIEW" >/dev/null 2>&1 \
    && echo "  posted to PR #$PR" || echo "  WARN: could not comment on PR" >&2
  if [ -n "$ISSUE" ]; then
    python3 "$SYNC" progress "$ISSUE" \
      "Adversarial review of PR #$PR complete. Verdict: ${VERDICT:-unstated}. Reviewer: Netflix-staff persona, fresh eyes, every finding required to ship an executed reproducer." \
      --agent "reviewer" >/dev/null 2>&1 \
      && echo "  progress noted on $ISSUE" || true
  fi
fi

echo "$(TS) done"
exit 0
