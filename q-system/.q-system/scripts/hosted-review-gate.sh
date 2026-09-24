#!/usr/bin/env bash
# hosted-review-gate.sh <pr-number> -- the CI entry point for a reviewer that
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

PR="${1:-}"
case "$PR" in
  ''|*[!0-9]*) echo "usage: hosted-review-gate.sh <pr-number>" >&2; exit 2 ;;
esac

# Seam for the test, so it can prove which command runs without a model.
AGENT="${HOSTED_REVIEW_AGENT:-$(dirname "${BASH_SOURCE[0]}")/pr-review-agent.sh}"

if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  echo "HOSTED REVIEWER OFF: no ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN secret on this repo."
  echo "Nothing was reviewed and no status was posted. kipi/reviewer-approved stays as the floor left it (red), so PR #$PR stays blocked until the dispatcher Mac reviews it."
  exit 0
fi

echo "hosted reviewer: running pr-review-agent.sh on PR #$PR"
exec bash "$AGENT" "$PR" --post
