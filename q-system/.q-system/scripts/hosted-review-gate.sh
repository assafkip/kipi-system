#!/usr/bin/env bash
# hosted-review-gate.sh <pr-number> <head-sha> -- the CI entry point for a reviewer that
# runs when the dispatcher Mac is off (ASK-318, failure mode 2).
#
# WHY: pr-review-agent.sh, the only producer of a kipi/reviewer-approved verdict,
# ran only from com.kipi.dispatch on one Mac. With that Mac asleep, every PR sat
# on the floor's red with no verdict at all (measured 2026-09-23: 60 open PRs,
# 50 floor-red, 0 hosted reviewers in .github/workflows/, 0 repo secrets).
#
# WHAT IT DOES, and nothing else:
#   - no model credential in the environment -> say so, run NOTHING, exit 0.
#     The floor already posted red, so the PR stays blocked: the safe side.
#     Never a success, never a fallback to some other credential.
#   - a credential is present -> exec the SAME reviewer the Mac runs,
#     pr-review-agent.sh <pr> --post. One reviewer, two hosts; no second
#     verdict logic to drift.
#
# Run from a BASE checkout only (see reviewer-hosted.yml): this file and the
# agent it execs must be main's reviewed copies, never the PR's.
set -euo pipefail

PR="${1:-}" HEAD_SHA="${2:-}"
case "$PR" in
  ''|*[!0-9]*) echo "usage: hosted-review-gate.sh <pr-number> <head-sha>" >&2; exit 2 ;;
esac
case "$HEAD_SHA" in
  *[!0-9a-f]*|'') echo "usage: hosted-review-gate.sh <pr-number> <head-sha> (40 hex chars)" >&2; exit 2 ;;
esac
[ "${#HEAD_SHA}" = 40 ] || { echo "usage: head sha must be 40 hex chars, got '$HEAD_SHA'" >&2; exit 2; }

# Seam for the test, so it can prove which command runs without a model.
AGENT="${HOSTED_REVIEW_AGENT:-$(dirname "${BASH_SOURCE[0]}")/pr-review-agent.sh}"

if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  # ::warning:: so the off state shows on the PR's checks page, not only inside
  # a green job's log (PR #437 review minor).
  echo "::warning title=Hosted reviewer off::no model secret on this repo; PR #$PR was not reviewed here"
  echo "HOSTED REVIEWER OFF: no ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN secret on this repo."
  echo "Nothing was reviewed and no status was posted. kipi/reviewer-approved stays as the floor left it (red), so PR #$PR stays blocked until the dispatcher Mac reviews it."
  exit 0
fi

# THE HEAD MUST BE IN THIS TREE (PR #437 major). The job checks out BASE, and
# the agent reviews the tree it stands in, warns on an absent object, and still
# posts onto the head sha: a verdict on code it never read (sp-a72a9567). The
# workflow fetches the head; this refuses if that fetch ever goes missing.
if ! git cat-file -e "${HEAD_SHA}^{commit}" 2>/dev/null; then
  echo "REFUSED: head $HEAD_SHA of PR #$PR is not in this checkout, so a review here would read the base tree and post on the head. Nothing reviewed, nothing posted." >&2
  exit 1
fi

echo "hosted reviewer: running pr-review-agent.sh on PR #$PR at $HEAD_SHA"
exec bash "$AGENT" "$PR" --post
