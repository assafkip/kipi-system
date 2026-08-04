#!/usr/bin/env bash
# The reviewer floor: turn an ABSENT verdict into a FAILING one (ASK-361).
#
# WHY THIS EXISTS. `kipi/reviewer-approved` is a REQUIRED context on main, but the
# only thing that posts it (pr-review-agent.sh) runs off a 15-minute launchd poll
# on ONE Mac, keyed on a Linear issue -- not on the PR. `validate` runs on
# `pull_request`; the reviewer does not. So the two required contexts have totally
# different liveness, and the reviewer's is routinely ABSENT. Measured 2026-08-03:
# PRs #88, #69, #50 and #23 each carried exactly ZERO `kipi/reviewer-approved`
# statuses at their head.
#
# That absence is why `enforce_admins` could not be turned on. Under branch
# protection an absent required context is indistinguishable from a pending one,
# and with no human merger on this repo every agent merge was riding the admin
# bypass instead. Proven on a probe branch, main untouched:
#
#   enforce_admins=false + required check failing -> merge ACCEPTED
#   enforce_admins=true  + required check failing -> merge REFUSED (405)
#   enforce_admins=true  + required check success -> merge ACCEPTED
#
# THE FLOOR ONLY EVER POSTS RED. It converts "missing" into "failing", which is
# answerable; it never converts anything into passing. A floor that could post
# success would recreate the exact phantom-approval hole that let unreviewed PRs
# merge (ASK-312: a reviewer that declined to start still yielded
# `kipi/reviewer-approved=success`, twice, on PR #74). `STATE` below is a literal
# for that reason -- it is never derived from a verdict, a review file, or an arg.
#
# IT MUST NEVER CLOBBER A REAL VERDICT. If any `kipi/reviewer-approved` status
# already exists at that head -- success OR failure -- the floor is a no-op. A
# floor that overwrote a genuine APPROVE would be worse than no floor at all: it
# would wedge PRs the reviewer had actually cleared. That is the mutation the
# paired test kills specifically (test-reviewer-floor.sh).
#
# Isolation: the ONLY writer here is post_floor, and it is reached only from main.
# Sourcing this file runs nothing, so the test drives floor_decision directly
# against real captured API payloads and never touches the network.

set -euo pipefail

REVIEWER_CONTEXT="kipi/reviewer-approved"

# The verdict slot only ever gets RED from this script. Not a parameter, not an
# argv flag, not read from a review. See the ASK-312 scar above.
FLOOR_STATE="failure"
FLOOR_DESC="no reviewer verdict at this head (floor: absent is not approved)"

# COMMAND-PREFIX INDIRECTION, NOT AN ARGV FLAG. The test needs to stand in for
# `gh`, and a stub that records "$1" versus "$*" breaks on whichever end a new
# flag lands. A command prefix moves the seam outside the argument list entirely,
# so the stub sees exactly the argv production sends.
REVIEWER_FLOOR_GH="${REVIEWER_FLOOR_GH:-gh}"

# Pure decision. Reads a GitHub combined-status payload on stdin, writes one of
# `post` / `noop <state>` on stdout. No I/O, so the test feeds it fixtures.
#
# READS THE COMBINED-STATUS ENDPOINT, NOT check-runs, on purpose. The reviewer
# verdict is a commit STATUS. The other required context, `validate`, is an
# Actions CHECK RUN and does not appear in this payload at all -- confirmed live
# 2026-08-03, where a PR mid-CI reported total_count 0 with validate running. So
# an empty payload here means "no reviewer verdict", never "no CI".
floor_decision() {
  local payload existing
  payload="$(cat)"
  # `.statuses[]?` tolerates a null/absent array. GitHub already collapses the
  # combined endpoint to the latest status per context, so [0] is the live one.
  existing="$(printf '%s' "$payload" | jq -r --arg ctx "$REVIEWER_CONTEXT" \
    '[.statuses[]? | select(.context == $ctx)] | if length == 0 then "none" else .[0].state end')"

  if [ "$existing" = "none" ]; then
    echo "post"
  else
    echo "noop $existing"
  fi
}

post_floor() {
  local sha="$1"
  local gh_cmd
  read -r -a gh_cmd <<< "$REVIEWER_FLOOR_GH"
  "${gh_cmd[@]}" api -X POST "repos/{owner}/{repo}/statuses/$sha" \
    -f "state=$FLOOR_STATE" \
    -f "context=$REVIEWER_CONTEXT" \
    -f "description=$FLOOR_DESC"
}

read_combined_status() {
  local sha="$1"
  local gh_cmd
  read -r -a gh_cmd <<< "$REVIEWER_FLOOR_GH"
  "${gh_cmd[@]}" api "repos/{owner}/{repo}/commits/$sha/status"
}

main() {
  local sha="${1:-}"
  if [ -z "$sha" ]; then
    echo "usage: reviewer-floor.sh <head-sha>" >&2
    exit 2
  fi

  local payload decision
  # NO `|| true` HERE. If the read fails we must NOT fall through to posting: a
  # failed read looks identical to an empty payload, and treating it as absence
  # would let the floor overwrite a real verdict it simply could not see.
  if ! payload="$(read_combined_status "$sha")"; then
    echo "ERROR: could not read combined status for $sha; posting nothing" >&2
    exit 1
  fi

  decision="$(printf '%s' "$payload" | floor_decision)"

  case "$decision" in
    post)
      echo "no reviewer verdict at $sha -- posting floor $REVIEWER_CONTEXT=$FLOOR_STATE"
      post_floor "$sha" >/dev/null
      echo "floor posted"
      ;;
    noop*)
      echo "reviewer verdict already present at $sha (${decision#noop }) -- floor stands down"
      ;;
  esac
}

# Sourcing must run nothing: the test sources this file to drive floor_decision.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  main "$@"
fi
