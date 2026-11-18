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
#   2. <head-sha> descends from <reviewed-sha> and every path that differs is a
#      receipt: .prd-os/receipts.jsonl, or a receipt fragment ADDED under
#      .prd-os/receipts.d/ (see receipt_paths_only). converge's receipt_only_ahead
#      asks this file rather than keeping its own copy of the rule. Any other path
#      is code no reviewer read, and stays red.
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
# `--delta-kind <tree> <reviewed-sha> <head-sha>` is another; see delta_kind.
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
# The exact name ledger_fragments.append_line gives a receipt (ASK-3829). Same regex
# as lefthook.yml's blocked-paths exception and receipts-ledger-check.py, so the one
# path a commit may add is the one path a push or a carry may add.
# test-receipt-carry-approval.sh pins the three copies equal.
RECEIPT_FRAGMENT_RE='^\.prd-os/receipts\.d/[0-9]{8}T[0-9]{12}Z-receipt-[0-9a-f]{16}\.jsonl$'
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

# receipt_paths_only: stdin is `git diff --name-status --no-renames` output. 0 when it
# names at least one path and every one is the ledger or an ADDED receipt fragment.
#
# WHY FRAGMENTS, AND WHY ONLY ADDED ONES (PR #621 round 2, finding 1). Since ASK-3829
# a close writes its receipt as a new file under .prd-os/receipts.d/, and this rule
# accepted the ledger file only, so a head carrying a fragment read as unreviewed
# code: converge refused to push the receipt and dropped the approval carry. A
# fragment is written once and never edited (receipts-ledger-check.py refuses any
# status but A), so a modified, deleted or renamed fragment is not a receipt being
# delivered, and stays `other`. --no-renames: with rename detection on, a source
# file renamed onto a receipt name would show only its new, harmless-looking path.
receipt_paths_only() {
  local status path n=0
  while IFS=$'\t' read -r status path; do
    [ -n "$status" ] || continue
    n=$((n + 1))
    [ "$path" = "$RECEIPT_LEDGER" ] && continue
    [ "$status" = "A" ] || return 1
    printf '%s\n' "$path" | grep -Eq "$RECEIPT_FRAGMENT_RE" || return 1
  done
  [ "$n" -gt 0 ]
}

# delta_kind <tree> <reviewed-sha> <head-sha>  ->  same | receipt-only | other
# Every failure to answer is `other`: unknown is not carriable.
delta_kind() {
  local tree="$1" reviewed="$2" head="$3" changes
  [ "$reviewed" = "$head" ] && { echo same; return 0; }
  git -C "$tree" merge-base --is-ancestor "$reviewed" "$head" 2>/dev/null || { echo other; return 0; }
  changes="$(git -C "$tree" diff --name-status --no-renames "$reviewed" "$head" 2>/dev/null)" || { echo other; return 0; }
  if printf '%s\n' "$changes" | receipt_paths_only; then echo receipt-only; else echo other; fi
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

# ---------------------------------------------------------------- version re-attest
# `--reattest-version <tree> <reviewed-sha> <head-sha> <owner/repo> [main-ref]`
# (ASK-4969, ruling 2026-11-18 22:20 UTC). A SECOND accepted shape, beside the
# receipt-only delta, for one case: the PR merged origin/main and had to resolve a
# plugin.json "version" conflict upward.
#
# WHY. PR #839 was approved on 060b3038. A sibling PR bumped the same plugin
# version, so merging main conflicted on that one line and the resolved head
# (1.13.72, main had 1.13.71) carried no approval. The round cap refused a 4th
# review and no path carried the approval. A version bump carries no behavior, so
# a review of it buys nothing, and the cap was blocking a merge on bookkeeping.
#
# WHAT IT ACCEPTS, AND NOTHING ELSE. The head's tree must equal the tree git
# merges main and the reviewed sha to (`git merge-tree --write-tree`), except at
# plugin.json paths whose ONLY difference from the reviewed file is the "version"
# field (all other fields compared after `jq -S del(.version)`), a plain x.y.z
# version, strictly greater than main's version of that file. Anything else that
# differs, including a main change the merge dropped, is `other`.
# Every failure to answer is `other`: unknown is not carriable.
#
# PRECONDITION, same as the hand-run carve-out in WHEN IT MAY RUN above: this is
# run against a head that IS the PR branch tip, so run it only when no reviewer is
# running on that head. The mode prints that warning on stderr when it carries.
VERSION_RE='^[0-9]+\.[0-9]+\.[0-9]+$'

# version_gt <a> <b>: 0 when a > b, both plain x.y.z. Numeric, never lexical.
version_gt() {
  [[ "$1" =~ $VERSION_RE && "$2" =~ $VERSION_RE ]] || return 1
  local IFS=. i; local -a a b
  read -r -a a <<< "$1"; read -r -a b <<< "$2"
  for i in 0 1 2; do
    [ "$((10#${a[$i]}))" -gt "$((10#${b[$i]}))" ] && return 0
    [ "$((10#${a[$i]}))" -lt "$((10#${b[$i]}))" ] && return 1
  done
  return 1
}

# reattest_path_ok <tree> <reviewed> <head> <main-ref> <path>: 0 when this one
# differing path is an allowed version-only plugin.json change.
reattest_path_ok() {
  local tree="$1" reviewed="$2" head="$3" mainref="$4" path="$5"
  local rj hj mj bj hv mv rrest hrest mrest brest base
  case "$path" in plugin.json|*/plugin.json) ;; *) return 1 ;; esac
  rj="$(git -C "$tree" show "$reviewed:$path" 2>/dev/null)" || return 1
  hj="$(git -C "$tree" show "$head:$path" 2>/dev/null)" || return 1
  mj="$(git -C "$tree" show "$mainref:$path" 2>/dev/null)" || return 1
  hv="$(printf '%s' "$hj" | jq -r '.version // empty' 2>/dev/null)" || return 1
  mv="$(printf '%s' "$mj" | jq -r '.version // empty' 2>/dev/null)" || return 1
  [ -n "$hv" ] && [ -n "$mv" ] || return 1
  rrest="$(printf '%s' "$rj" | jq -S -c 'del(.version)' 2>/dev/null)" || return 1
  hrest="$(printf '%s' "$hj" | jq -S -c 'del(.version)' 2>/dev/null)" || return 1
  mrest="$(printf '%s' "$mj" | jq -S -c 'del(.version)' 2>/dev/null)" || return 1
  # The other fields must be what a 3-way merge gives (PR #846 round 2: comparing
  # to the reviewed sha alone let a head revert main's own non-version edit).
  # Main left them alone: the head keeps the reviewed fields. Main changed them and
  # the PR did not: the head takes main's. Both changed them: not a version-only
  # conflict, so refuse.
  base="$(git -C "$tree" merge-base "$mainref" "$reviewed" 2>/dev/null)" || return 1
  bj="$(git -C "$tree" show "$base:$path" 2>/dev/null)" || return 1
  brest="$(printf '%s' "$bj" | jq -S -c 'del(.version)' 2>/dev/null)" || return 1
  if [ "$mrest" = "$brest" ]; then
    [ "$hrest" = "$rrest" ] || return 1
  elif [ "$rrest" = "$brest" ]; then
    [ "$hrest" = "$mrest" ] || return 1
  else
    return 1
  fi
  version_gt "$hv" "$mv"
}

# reattest_kind <tree> <reviewed> <head> <main-ref>  ->  version-reattest | other
#
# WHY THE HEAD IS COMPARED TO THE EXPECTED MERGE, NOT TO THE REVIEWED SHA (PR #846
# round 1, major). A first draft compared owned paths to the reviewed sha. That
# passes `git merge -X ours main` plus a hand version bump: main's own commit is
# silently unlanded and a green rides on it. The invariant is "the only hand edit
# is the version line", so the reference is what git merges to: merge-tree of main
# and the reviewed sha. A path where the head equals that tree is git's work; a
# path where it differs must be a version-only plugin.json, strictly above main's.
# Absent-on-both-sides is equal here, so a PR that deletes a file is not refused.
reattest_kind() {
  local tree="$1" reviewed="$2" head="$3" mainref="$4" expected htree path
  git -C "$tree" merge-base --is-ancestor "$reviewed" "$head" 2>/dev/null || { echo other; return 0; }
  # exit 1 = conflicts, still prints the tree (conflicted text in the conflicting
  # paths). Anything else, or no tree on line 1, is not an answer.
  expected="$(git -C "$tree" merge-tree --write-tree --no-messages "$mainref" "$reviewed" 2>/dev/null | head -n 1)"
  if ! [[ "$expected" =~ ^[0-9a-f]{40,64}$ ]]; then
    echo "carry: git merge-tree could not compute the expected merge (needs git 2.38+); nothing established, refusing" >&2
    echo other; return 0
  fi
  htree="$(git -C "$tree" rev-parse -q --verify "$head^{tree}" 2>/dev/null)" || { echo other; return 0; }
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    reattest_path_ok "$tree" "$reviewed" "$head" "$mainref" "$path" || { echo "carry: re-attest refused at '$path'" >&2; echo other; return 0; }
  done < <(git -C "$tree" diff --name-only --no-renames "$expected" "$htree" 2>/dev/null || echo "?diff-failed")
  # PR #846 round 2, minor: a head equal to the merge result skips the loop above,
  # so the version floor is checked on its own. Every plugin.json the head differs
  # from main on must be strictly above main's version, whatever shape the merge took.
  local hv mv
  while IFS= read -r path; do
    case "$path" in plugin.json|*/plugin.json) ;; *) continue ;; esac
    hv="$(git -C "$tree" show "$head:$path" 2>/dev/null | jq -r '.version // empty' 2>/dev/null)"
    mv="$(git -C "$tree" show "$mainref:$path" 2>/dev/null | jq -r '.version // empty' 2>/dev/null)"
    [ -n "$mv" ] || continue
    version_gt "$hv" "$mv" || { echo "carry: re-attest refused: '$path' version '$hv' is not above main's '$mv'" >&2; echo other; return 0; }
  done < <(git -C "$tree" diff --name-only --no-renames "$mainref" "$head" 2>/dev/null)
  echo version-reattest
}

main() {
  if [ "${1:-}" = "--head-state" ]; then
    [ -n "${2:-}" ] && [ -n "${3:-}" ] || { echo "usage: receipt-carry-approval.sh --head-state <owner/repo> <sha>" >&2; exit 2; }
    head_state "$2" "$3"; exit $?
  fi
  # READ ONLY, for converge's receipt_only_ahead: one rule for "this head adds only
  # a receipt", so the push guard and the carry cannot disagree about a path.
  if [ "${1:-}" = "--delta-kind" ]; then
    [ -n "${2:-}" ] && [ -n "${3:-}" ] && [ -n "${4:-}" ] || { echo "usage: receipt-carry-approval.sh --delta-kind <tree> <reviewed-sha> <head-sha>" >&2; exit 2; }
    delta_kind "$2" "$3" "$4"; exit 0
  fi
  local reattest=0 mainref="origin/main"
  if [ "${1:-}" = "--reattest-version" ]; then reattest=1; mainref="${6:-origin/main}"; shift; fi
  local tree="${1:-}" reviewed="${2:-}" head="${3:-}" repo="${4:-}"
  if [ -z "$tree" ] || [ -z "$reviewed" ] || [ -z "$head" ] || [ -z "$repo" ]; then
    echo "usage: receipt-carry-approval.sh <tree> <reviewed-sha> <head-sha> <owner/repo>" >&2
    exit 2
  fi

  local kind payload verdict state desc head_payload head_state
  local want="receipt-only" label="receipt-only delta"
  if [ "$reattest" = 1 ]; then
    kind="$(reattest_kind "$tree" "$reviewed" "$head" "$mainref")"
    want="version-reattest"; label="version-only re-attest"
  else
    kind="$(delta_kind "$tree" "$reviewed" "$head")"
  fi
  if ! [ "$kind" = "$want" ]; then
    echo "carry: not carrying to $head -- beyond $reviewed it is '$kind', and only a $want delta carries in this mode"
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

  # Before the POST (PR #846 round 2, nit): a warning after an irreversible write informs nobody.
  [ "$reattest" = 1 ] && echo "carry: warning: $head is a live PR tip; safe only while no reviewer runs on it" >&2
  desc="$(printf '%.140s' "$CARRY_PREFIX$(printf '%.12s' "$reviewed") ($label): $desc")"
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
