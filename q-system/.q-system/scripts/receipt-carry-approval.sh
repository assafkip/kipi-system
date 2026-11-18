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

# merge_only <tree> <reviewed-sha> <head-sha> <base-ref>: 0 when <head-sha> is a two-parent
# merge of <reviewed-sha> with a commit already on <base-ref>, and the PR's OWN change
# (its net diff against its base) is the same before and after the merge.
#
# WHY (PR #839, ASK-4969, 2026-11-18). Approved at 060b3038 with checks green; main then
# bumped the kipi-core plugin.json version, the PR went CONFLICTING, and the merge-from-
# main head 55e215b0 carried no verdict. kipi/reviewer-approved is per sha and the review
# cap (3) was spent, so the PR could not move. The PR's own files were byte-identical:
# only main's files and the plugin.json version line had moved. delta_kind called that
# `other`, so nothing picked it up.
#
# HOW IT TELLS "PR's own change unchanged": by tree entries (mode + object id), never by a
# patch hash. Review round 1 of the fix PR: `git patch-id --stable` ignores whitespace, so
# a merge that re-indents a reviewed Python line hashed equal and would have carried an
# approval onto code the reviewer never read. With P = the PR's own paths
# (merge-base(reviewed, other) -> reviewed), both directions must hold:
#   A) every path head differs from reviewed on is NOT in P and equals `other` (main's file)
#   B) every path head differs from `other` on IS in P and equals reviewed (the reviewed bytes)
# So a PR file edited, a file added, or a main change reverted all decline. A PR file that
# main also touched declines too: that is a merge needing a reviewer, not a carry.
# A moved .claude-plugin/plugin.json is exempt from A and B when, with "version" dropped,
# its parsed JSON is equal at reviewed and head (the parse, not the layout: pr-restack.py's
# json.dump reformats the file, which a line grep refused).
# Unknown is not carriable: every failed read returns 1.
_tree_entry() {  # _tree_entry <tree> <commit> <path>: "mode oid" or ABSENT
  local e; e="$(git -C "$1" ls-tree "$2" -- "$3" 2>/dev/null)" || { echo UNREADABLE; return; }
  [ -n "$e" ] || { echo ABSENT; return; }
  printf '%s\n' "$e" | awk '{print $1, $3}'
}
_json_same_sans_version() {  # _json_same_sans_version <tree> <sha-a> <sha-b> <path>
  python3 - "$@" <<'PY' 2>/dev/null
import json, subprocess, sys
tree, a, b, path = sys.argv[1:5]
def load(c):
    d = json.loads(subprocess.check_output(["git", "-C", tree, "show", f"{c}:{path}"]))
    d.pop("version", None)
    return d
sys.exit(0 if load(a) == load(b) else 1)
PY
}
merge_only() {
  local tree="$1" reviewed="$2" head="$3" ref="$4" rrev line other="" nparents=0 p
  local base_old own moved f vpaths="" a b
  rrev="$(git -C "$tree" rev-parse --verify "$reviewed^{commit}" 2>/dev/null)" || return 1
  line="$(git -C "$tree" rev-list --parents -n 1 "$head" 2>/dev/null)" || return 1
  for p in $line; do
    nparents=$((nparents + 1))
    [ "$nparents" -gt 1 ] && [ "$p" != "$rrev" ] && other="$p"
  done
  # head + exactly two parents, one of them the reviewed sha, the other a different commit.
  [ "$nparents" -eq 3 ] && [ -n "$other" ] || return 1
  case " $line " in *" $rrev "*) ;; *) return 1 ;; esac
  # The merged-in side must already be on main. A side branch is code no reviewer read.
  git -C "$tree" merge-base --is-ancestor "$other" "$ref" 2>/dev/null || return 1
  base_old="$(git -C "$tree" merge-base "$rrev" "$other" 2>/dev/null)" || return 1
  [ -n "$base_old" ] || return 1
  own="$(git -C "$tree" diff --name-only --no-renames "$base_old" "$rrev" 2>/dev/null)" || return 1
  [ -n "$own" ] || return 1   # nothing of the PR's own to hold equal: nothing proven
  moved="$(git -C "$tree" diff --name-only --no-renames "$rrev" "$head" -- ':(glob)**/.claude-plugin/plugin.json' 2>/dev/null)" || return 1
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    _json_same_sans_version "$tree" "$rrev" "$head" "$f" || return 1
    vpaths="$vpaths
$f"
  done <<< "$moved"
  _in() { printf '%s\n' "$2" | grep -Fxq -- "$1"; }   # exact whole-line match
  # A) head vs reviewed
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    [ "$f" = __FAIL__ ] && return 1   # a failed diff must not read as "no differing path"
    _in "$f" "$vpaths" && continue
    _in "$f" "$own" && return 1
    a="$(_tree_entry "$tree" "$head" "$f")"; b="$(_tree_entry "$tree" "$other" "$f")"
    [ "$a" != UNREADABLE ] && [ "$a" = "$b" ] || return 1
  done < <(git -C "$tree" diff --name-only --no-renames "$rrev" "$head" 2>/dev/null || echo __FAIL__)
  # B) head vs the main side
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    [ "$f" = __FAIL__ ] && return 1
    _in "$f" "$vpaths" && continue
    _in "$f" "$own" || return 1
    a="$(_tree_entry "$tree" "$head" "$f")"; b="$(_tree_entry "$tree" "$rrev" "$f")"
    [ "$a" != UNREADABLE ] && [ "$a" = "$b" ] || return 1
  done < <(git -C "$tree" diff --name-only --no-renames "$other" "$head" 2>/dev/null || echo __FAIL__)
  return 0
}

# delta_kind <tree> <reviewed-sha> <head-sha> [base-ref]  ->  same | receipt-only | merge-only | other
# base-ref defaults to $RECEIPT_CARRY_BASE_REF, then origin/main. Only merge-only reads it.
# Every failure to answer is `other`: unknown is not carriable. converge's
# receipt_only_ahead matches "receipt-only" exactly, so a merge-only head is never
# pushed as a receipt; only the carry below accepts it.
delta_kind() {
  local tree="$1" reviewed="$2" head="$3" ref="${4:-${RECEIPT_CARRY_BASE_REF:-origin/main}}" changes
  [ "$reviewed" = "$head" ] && { echo same; return 0; }
  git -C "$tree" merge-base --is-ancestor "$reviewed" "$head" 2>/dev/null || { echo other; return 0; }
  changes="$(git -C "$tree" diff --name-status --no-renames "$reviewed" "$head" 2>/dev/null)" || { echo other; return 0; }
  if printf '%s\n' "$changes" | receipt_paths_only; then echo receipt-only
  elif merge_only "$tree" "$reviewed" "$head" "$ref"; then echo merge-only
  else echo other; fi
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
  # READ ONLY, for converge's receipt_only_ahead: one rule for "this head adds only
  # a receipt", so the push guard and the carry cannot disagree about a path.
  if [ "${1:-}" = "--delta-kind" ]; then
    [ -n "${2:-}" ] && [ -n "${3:-}" ] && [ -n "${4:-}" ] || { echo "usage: receipt-carry-approval.sh --delta-kind <tree> <reviewed-sha> <head-sha>" >&2; exit 2; }
    delta_kind "$2" "$3" "$4"; exit 0
  fi
  local tree="${1:-}" reviewed="${2:-}" head="${3:-}" repo="${4:-}"
  if [ -z "$tree" ] || [ -z "$reviewed" ] || [ -z "$head" ] || [ -z "$repo" ]; then
    echo "usage: receipt-carry-approval.sh <tree> <reviewed-sha> <head-sha> <owner/repo>" >&2
    exit 2
  fi

  local kind payload verdict state desc head_payload head_state
  kind="$(delta_kind "$tree" "$reviewed" "$head")"
  if ! { [ "$kind" = "receipt-only" ] || [ "$kind" = "merge-only" ]; }; then
    echo "carry: not carrying to $head -- beyond $reviewed it is '$kind', and only a receipt-only or merge-only delta carries"
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

  desc="$(printf '%.140s' "$CARRY_PREFIX$(printf '%.12s' "$reviewed") ($kind delta): $desc")"
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
