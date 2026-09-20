#!/usr/bin/env bash
# Carry a reviewer approval across converge's own receipt commit (ASK-1888).
#
# WHY THIS EXISTS. Two required things collide on every approved PR. The receipt
# gate in `validate` wants a receipt COMMIT on the branch, bound to the reviewed
# sha. `kipi/reviewer-approved` is a commit STATUS, which is per-sha. converge
# satisfies the first by creating a head the second has never seen, 4 to 11
# seconds after the approval lands. Measured 2026-09-19: 31 approved PRs red on
# their current head, 25 behind exactly that commit, 30 with auto-merge armed and
# waiting forever; 9 days at 10 dispatches a day produced 1 merge. The loop
# cancelled its own approval every time it succeeded.
#
# WHAT IT MAY DO, AND NOTHING ELSE. It COPIES a success the reviewer already
# posted on <reviewed-sha> onto <head-sha>, when and only when all three hold:
#
#   1. the live reviewer verdict at <reviewed-sha> is `success`, read from GitHub,
#      never from the local verdict record. This script cannot approve anything
#      the reviewer did not; it has no verdict of its own to give.
#   2. <head-sha> descends from <reviewed-sha> and the ONLY path that differs is
#      .prd-os/receipts.jsonl. Same rule as converge's receipt_only_ahead and the
#      receipt gate's own ledger allowance: the one file converge may add to a
#      reviewed head. Any other path is code no reviewer read, and stays red.
#   3. no real verdict exists at <head-sha> yet. A head the reviewer already
#      judged is never overwritten, in either direction.
#
# WHY THIS IS NOT reviewer-floor.sh. The floor is deliberately incapable of
# posting success (ASK-312: a phantom approval merged unreviewed PRs, twice, on
# PR #74), and it stays that way. This is a separate file so that the set of
# things able to write `success` into this context is exactly two and greppable:
# pr-review-agent.sh's post_reviewer_status, and carry_post here.
#
# Decided by code on purpose. No model is asked whether the delta is safe: a gate
# has to give the same answer when it is re-run.
#
# Isolation: the only writer is carry_post, reached only from main. Sourcing this
# file runs nothing, so the test drives the pure halves against real captured
# payloads and a throwaway repo.

set -uo pipefail

REVIEWER_CONTEXT="kipi/reviewer-approved"
RECEIPT_LEDGER=".prd-os/receipts.jsonl"
# The floor's literal, restated because the two files must agree on what "the
# floor wrote this" means. test-receipt-carry-approval.sh feeds a real floor row
# through live_verdict, so a drift between the two strings turns that test red.
FLOOR_DESC="no reviewer verdict at this head (floor: absent is not approved)"
# How this script recognises its own success rows. A literal, written only by
# main below, so "starts with this" is exactly "the carry wrote it".
CARRY_PREFIX="carried from "

# Command-prefix seam, same reason as REVIEWER_FLOOR_GH: a stub that replaces
# `gh` sees exactly the argv production sends.
RECEIPT_CARRY_GH="${RECEIPT_CARRY_GH:-gh}"

# Pure. Plural statuses list (newest first) on stdin. Prints
# `<state> <description>` of the newest entry in the reviewer's context that the
# floor did not write, or `none`. The floor routinely lands on top of a real
# approval, so "newest" alone would read a cleared PR as refused.
live_verdict() {
  jq -r --arg ctx "$REVIEWER_CONTEXT" --arg fd "$FLOOR_DESC" '
    [.[]? | select(.context == $ctx) | select(.description != $fd)]
    | if length == 0 then "none" else (.[0].state + " " + (.[0].description // "")) end' 2>/dev/null \
    || echo "none"
}

# delta_kind <tree> <reviewed-sha> <head-sha>  ->  same | receipt-only | other
# Every failure to answer is `other`: unknown is not carriable.
delta_kind() {
  local tree="$1" reviewed="$2" head="$3" gained
  [ "$reviewed" = "$head" ] && { echo same; return 0; }
  git -C "$tree" merge-base --is-ancestor "$reviewed" "$head" 2>/dev/null || { echo other; return 0; }
  gained="$(git -C "$tree" diff --name-only "$reviewed" "$head" 2>/dev/null)" || { echo other; return 0; }
  if [ "$gained" = "$RECEIPT_LEDGER" ]; then echo receipt-only; else echo other; fi
}

read_statuses() {  # read_statuses <repo-path> <sha>
  local gh_cmd; read -r -a gh_cmd <<< "$RECEIPT_CARRY_GH"
  "${gh_cmd[@]}" api "repos/$1/commits/$2/statuses"
}

# Pure. Same list on stdin. The newest entry in the reviewer's context that is
# neither the floor's nor this script's own, as `<state>`, or `none`. This is
# "did somebody who actually read the head speak", and it is what the post-write
# race check asks.
foreign_verdict() {
  jq -r --arg ctx "$REVIEWER_CONTEXT" --arg fd "$FLOOR_DESC" --arg cp "$CARRY_PREFIX" '
    [.[]? | select(.context == $ctx) | select(.description != $fd)
          | select(((.description // "") | startswith($cp) or startswith("carry withdrawn")) | not)]
    | if length == 0 then "none" else .[0].state end' 2>/dev/null || echo "unreadable"
}

# carry_post <repo-path> <head-sha> <success|failure> <description>
# `success` is written from exactly one call site in main, after all three
# guards; `failure` only ever withdraws a success this script just wrote.
carry_post() {
  local gh_cmd; read -r -a gh_cmd <<< "$RECEIPT_CARRY_GH"
  "${gh_cmd[@]}" api -X POST "repos/$1/statuses/$2" \
    -f "state=$3" -f "context=$REVIEWER_CONTEXT" -f "description=$4"
}

main() {
  local tree="${1:-}" reviewed="${2:-}" head="${3:-}" repo="${4:-}"
  if [ -z "$tree" ] || [ -z "$reviewed" ] || [ -z "$head" ] || [ -z "$repo" ]; then
    echo "usage: receipt-carry-approval.sh <tree> <reviewed-sha> <head-sha> <owner/repo>" >&2
    exit 2
  fi

  local kind payload verdict state desc head_payload head_state
  kind="$(delta_kind "$tree" "$reviewed" "$head")"
  if ! [ "$kind" = "receipt-only" ]; then
    echo "carry: not carrying to $head -- beyond $reviewed it is '$kind', and only a receipt-only delta carries"
    exit 0
  fi

  # A failed read is NOT an empty list. Post nothing rather than guess.
  if ! payload="$(read_statuses "$repo" "$reviewed")"; then
    echo "carry: could not read statuses at $reviewed; posting nothing" >&2
    exit 1
  fi
  verdict="$(printf '%s' "$payload" | live_verdict)"
  state="${verdict%% *}"; desc="${verdict#* }"
  if ! [ "$state" = "success" ]; then
    echo "carry: the live reviewer verdict at $reviewed is '$state', not an approval; posting nothing"
    exit 0
  fi

  if ! head_payload="$(read_statuses "$repo" "$head")"; then
    echo "carry: could not read statuses at $head; posting nothing" >&2
    exit 1
  fi
  head_state="$(printf '%s' "$head_payload" | live_verdict)"; head_state="${head_state%% *}"
  if ! [ "$head_state" = "none" ]; then
    echo "carry: $head already carries a real reviewer verdict ($head_state); leaving it alone"
    exit 0
  fi

  desc="$(printf '%.140s' "$CARRY_PREFIX$(printf '%.12s' "$reviewed") (receipt-only delta): $desc")"
  if ! carry_post "$repo" "$head" success "$desc" >/dev/null; then
    echo "carry: the status post on $head FAILED; the approval is still only on $reviewed" >&2
    exit 1
  fi

  # THE RACE (codex major, PR #376 round 1). The head read and the post are two
  # API calls and GitHub has no compare-and-swap, so the reviewer can land a
  # verdict on this head between them. The floor has the same window and only
  # OBSERVES it, because its write is red. This write is GREEN, so a buried
  # REQUEST CHANGES here would make a refused head mergeable -- the dangerous
  # direction. So it is steered instead: if anything that is neither the floor's
  # nor ours is in the list after the post, withdraw with a red on top. That can
  # bury a real approval too, which is wrongly BLOCKED and loud, never wrongly
  # MERGED. Red is answerable; a phantom green is not.
  local after foreign
  if ! after="$(read_statuses "$repo" "$head")"; then
    carry_post "$repo" "$head" failure "carry withdrawn: could not confirm no reviewer verdict raced it" >/dev/null || true
    echo "carry: posted, then could NOT re-read $head to check for a raced verdict; withdrew with a red. Re-run the reviewer on $head." >&2
    exit 3
  fi
  foreign="$(printf '%s' "$after" | foreign_verdict)"
  if ! [ "$foreign" = "none" ]; then
    carry_post "$repo" "$head" failure "carry withdrawn: a reviewer verdict ($foreign) landed on this head" >/dev/null || true
    echo "carry: a real reviewer verdict ($foreign) landed on $head during the carry; withdrew with a red so it cannot merge on the copy. Re-run the reviewer on $head." >&2
    exit 3
  fi
  echo "carry: $REVIEWER_CONTEXT=success carried from $reviewed to $head"
}

# `:-` is load-bearing under `set -u` when sourced from `bash -c` (see the same
# line in reviewer-floor.sh).
if [ "${BASH_SOURCE[0]:-}" = "${0}" ]; then
  main "$@"
fi
