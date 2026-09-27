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
# WHEN IT MAY RUN: BEFORE THE SHA IS ANYBODY'S HEAD (codex, PR #376 rounds 1+2).
# GitHub's status API has no compare-and-swap. Run against a commit that is
# already a PR head, a reviewer can land a REQUEST CHANGES between guard 3 and
# the post, and the copied green buries it. Round 1's answer was a compensating
# red after the fact; round 2 showed three ways that still loses (auto-merge can
# fire in the gap, the red can fail to post, the caller can swallow both). Same
# class twice, so the fix is the ORDER, not a fourth patch: converge pushes the
# receipt commit to a staging ref first, carries onto that sha while no branch
# points at it and nobody can be reviewing it, and only then moves the branch.
#
# WHAT THE ORDER ACTUALLY GUARANTEES, AND WHAT IT DOES NOT (ASK-1905 nit 3). It
# guarantees exactly one thing, on the NEW sha: every reviewer verdict there is
# NEWER than the copy, GitHub shows the newest status per context, so no verdict
# on that sha can predate the copy and be hidden under it. That is the whole of
# it. It does NOT close the window on the REVIEWED sha. A refusal landing on the reviewed sha
# after guard 1 read it is invisible to this script, and converge's branch move
# then puts a different sha in front of the PR, so that refusal stops being the
# head's verdict. This script never buries that refusal -- the branch
# move does, exactly as any push would -- but the gap is not gone, it is moved to
# a place where the reviewer's next run sees the new head and posts on it. Run by
# hand against a live head, this script IS racy; do that only when no reviewer is
# running.
#
# `--head-state <owner/repo> <sha>` is a READ-ONLY mode; see head_state.
#
# EXIT: 0 carried, 10 declined (a guard said no), 1 could not read or post,
# 2 usage. The caller tells "did nothing, by design" from "tried and failed".
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
CARRY_PREFIX="carried from "

# Command-prefix seam, same reason as REVIEWER_FLOOR_GH: a stub that replaces
# `gh` sees exactly the argv production sends.
RECEIPT_CARRY_GH="${RECEIPT_CARRY_GH:-gh}"
# The one identity rule for this context. REVIEWER_TOKEN_LIB is a seam for the
# test's mutant copies, which live away from this directory. A missing lib leaves
# reviewer_status_run undefined, so carry_post fails and nothing is posted.
# shellcheck source=reviewer-token-lib.sh
. "${REVIEWER_TOKEN_LIB:-$(dirname "${BASH_SOURCE[0]}")/reviewer-token-lib.sh}" 2>/dev/null \
  || echo "carry: reviewer-token-lib.sh not found; the carry will post nothing" >&2
EXIT_DECLINED=10

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

# carry_post <repo-path> <head-sha> <description>
# `state=success` is a literal, written from exactly one call site in main, after
# all three guards. This script has no way to write anything else.
carry_post() {
  local gh_cmd; read -r -a gh_cmd <<< "$RECEIPT_CARRY_GH"
  # WHICH IDENTITY (ASK-362): the same rule as the reviewer's own POST, from the
  # one shared helper. PR #431 round 1 found this writer still on the ambient
  # admin login after the reviewer's had moved. A refusal (configured, empty)
  # returns non-zero, so main pages "the status post FAILED" and posts nothing.
  reviewer_status_run "${gh_cmd[@]}" api -X POST "repos/$1/statuses/$2" \
    -f "state=success" -f "context=$REVIEWER_CONTEXT" -f "description=$3"
}

# head_state <owner/repo> <sha>: READ ONLY. Prints the state of the live reviewer
# verdict at <sha> (`success`, `failure`, `none`). Exit 1 when GitHub could not
# be read, so "could not ask" is never printed as `none`. converge uses it to let
# origin, not this run, decide whether the head is approved.
head_state() {
  local payload state
  payload="$(read_statuses "$1" "$2")" || { echo "carry: could not read statuses at $2" >&2; return 1; }
  state="$(printf '%s' "$payload" | live_verdict)"
  printf '%s\n' "${state%% *}"
}

main() {
  if [ "${1:-}" = "--head-state" ]; then
    [ -n "${2:-}" ] && [ -n "${3:-}" ] || { echo "usage: receipt-carry-approval.sh --head-state <owner/repo> <sha>" >&2; exit 2; }
    head_state "$2" "$3"; exit $?
  fi
  local tree="${1:-}" reviewed="${2:-}" head="${3:-}" repo="${4:-}"
  if [ -z "$tree" ] || [ -z "$reviewed" ] || [ -z "$head" ] || [ -z "$repo" ]; then
    echo "usage: receipt-carry-approval.sh <tree> <reviewed-sha> <head-sha> <owner/repo>" >&2
    exit 2
  fi

  local kind payload verdict state desc head_payload head_state
  kind="$(delta_kind "$tree" "$reviewed" "$head")"
  if ! [ "$kind" = "receipt-only" ]; then
    echo "carry: not carrying to $head -- beyond $reviewed it is '$kind', and only a receipt-only delta carries"
    exit "$EXIT_DECLINED"
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
    exit "$EXIT_DECLINED"
  fi

  if ! head_payload="$(read_statuses "$repo" "$head")"; then
    echo "carry: could not read statuses at $head; posting nothing" >&2
    exit 1
  fi
  head_state="$(printf '%s' "$head_payload" | live_verdict)"; head_state="${head_state%% *}"
  if ! [ "$head_state" = "none" ]; then
    echo "carry: $head already carries a real reviewer verdict ($head_state); leaving it alone"
    exit "$EXIT_DECLINED"
  fi

  desc="$(printf '%.140s' "$CARRY_PREFIX$(printf '%.12s' "$reviewed") (receipt-only delta): $desc")"
  if ! carry_post "$repo" "$head" "$desc" >/dev/null; then
    echo "carry: the status post on $head FAILED; the approval is still only on $reviewed" >&2
    exit 1
  fi

  echo "carry: $REVIEWER_CONTEXT=success carried from $reviewed to $head"
}

# `:-` is load-bearing under `set -u` when sourced from `bash -c` (see the same
# line in reviewer-floor.sh).
if [ "${BASH_SOURCE[0]:-}" = "${0}" ]; then
  main "$@"
fi
