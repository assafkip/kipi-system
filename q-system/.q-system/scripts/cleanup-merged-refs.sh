#!/usr/bin/env bash
# cleanup-merged-refs.sh: delete merged remote branches from a cleanup list, one batch
# at a time, re-checking every item at run time (ASK-4650).
#
# THE SCAR, 2026-11-12. A read-only census found 1,492 remote branches (585 merged,
# 40 of them plain ancestors of main). delete_branch_on_merge was false, so every
# squash-merged PR left its branch behind, and the destructive-op hook (rightly) lets no
# agent delete any of it. The list was measured hours before the founder runs a delete,
# and a list goes stale: a branch gets new commits, a PR reopens. So the LIST only
# nominates. This script decides, from live state, per item.
#
# Usage: cleanup-merged-refs.sh <list.md> --batch A|D [--apply] [--repo DIR]
#          [--remote origin] [--min-age-hours 24] [--chunk 25]
#   A  remote branches whose tip is an ancestor of <remote>/main.
#   D  remote branches whose PR is MERGED. Deleted only when the branch tip IS that PR's
#      head commit (or is an ancestor of main). A branch pushed to after the merge is
#      kept and named: it holds commits no PR carried to main.
# There is no tree batch, on purpose. Worktrees have ONE owner, worktree-reaper.py
# (com.kipi.worktree-reaper, daily), which holds the process census, the review-lock
# mutex and the index-refresh rule. A second remover in this file re-learned those
# one review round at a time (PR #773, rounds 1 to 3); `--batch B` is refused.
# The list file: a heading `## A.` or `## D.` at column 1, then one `- origin/<name>`
# bullet per line at column 1; any other spelling nominates nothing.
# Default is DRY: it prints and records what it WOULD delete. --apply deletes.
# Every run writes a JSONL receipt (tip sha per branch, so a delete is restorable with
# `git push <remote> <sha>:refs/heads/<name>`) under ~/.local/state/kipi/cleanup-merged-refs/.
#
# The destructive-op hook blocks `git push --delete` for every agent. The founder runs
# this from his own shell. This file carries no bypass and never will.
set -u

LIST="" ; BATCH="" ; APPLY=0 ; REPO="" ; REMOTE="origin" ; MIN_AGE_H=24 ; CHUNK=25
while [ $# -gt 0 ]; do
  case "$1" in
    --batch) [ $# -ge 2 ] || { echo "cleanup-merged-refs: --batch needs a value" >&2; exit 2; }; BATCH="$2"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    --repo) [ $# -ge 2 ] || { echo "cleanup-merged-refs: --repo needs a value" >&2; exit 2; }; REPO="$2"; shift 2 ;;
    --remote) [ $# -ge 2 ] || { echo "cleanup-merged-refs: --remote needs a value" >&2; exit 2; }; REMOTE="$2"; shift 2 ;;
    --min-age-hours) [ $# -ge 2 ] || { echo "cleanup-merged-refs: --min-age-hours needs a value" >&2; exit 2; }; MIN_AGE_H="$2"; shift 2 ;;
    --chunk) [ $# -ge 2 ] || { echo "cleanup-merged-refs: --chunk needs a value" >&2; exit 2; }; CHUNK="$2"; shift 2 ;;
    -h|--help) awk 'NR>1 && /^#/ {print; next} NR>1 {exit}' "$0"; exit 0 ;;
    -*) echo "cleanup-merged-refs: unknown flag $1" >&2; exit 2 ;;
    *) LIST="$1"; shift ;;
  esac
done
case "$BATCH" in
  A|D) ;;
  B) echo "cleanup-merged-refs: there is no tree batch; worktree-reaper.py (com.kipi.worktree-reaper) owns tree removal" >&2; exit 2 ;;
  *) echo "cleanup-merged-refs: --batch must be A or D" >&2; exit 2 ;;
esac
[ -f "$LIST" ] || { echo "cleanup-merged-refs: list file not found: $LIST" >&2; exit 2; }
for n in "$MIN_AGE_H" "$CHUNK"; do case "$n" in ""|*[!0-9]*) echo "cleanup-merged-refs: --min-age-hours and --chunk are whole numbers" >&2; exit 2 ;; esac; done
[ "$CHUNK" -ge 1 ] || { echo "cleanup-merged-refs: --chunk must be at least 1" >&2; exit 2; }
command -v jq >/dev/null || { echo "cleanup-merged-refs: jq is required" >&2; exit 2; }

[ -n "$REPO" ] || REPO="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "cleanup-merged-refs: not in a git repo; pass --repo" >&2; exit 2; }
G() { git -C "$REPO" "$@"; }

RECEIPT_DIR="${KIPI_CLEANUP_RECEIPT_DIR:-$HOME/.local/state/kipi/cleanup-merged-refs}"
mkdir -p "$RECEIPT_DIR" || { echo "cleanup-merged-refs: cannot create $RECEIPT_DIR" >&2; exit 2; }
MODE=dry; [ "$APPLY" = 1 ] && MODE=apply
RECEIPT="$RECEIPT_DIR/$BATCH-$(date -u +%Y%m%dT%H%M%SZ)-$MODE.jsonl"
: > "$RECEIPT"
NOW="$(date +%s)"
MIN_AGE_S=$((MIN_AGE_H * 3600))

COUNT_DELETE=0 ; COUNT_KEEP=0 ; COUNT_FAIL=0
# rec <name> <action> <reason> [sha]
rec() {
  jq -cn --arg b "$BATCH" --arg n "$1" --arg a "$2" --arg r "$3" --arg s "${4:-}" --arg m "$MODE" \
    '{batch:$b,name:$n,action:$a,reason:$r,sha:$s,mode:$m}' >> "$RECEIPT"
}
keep() { COUNT_KEEP=$((COUNT_KEEP + 1)); echo "keep    $1  ($2)"; rec "$1" kept "$2" "${3:-}"; }

# The list nominates: names under the "## <BATCH>." heading only.
nominees() {
  awk -v b="$BATCH" '
    /^## / { on = (substr($0, 4, 2) == b ".") ; next }
    on && /^- / { sub(/^- /, ""); sub(/ \|.*$/, ""); print }' "$LIST"
}

# ----------------------------------------------------------- remote branches
G fetch -q --prune "$REMOTE" || { echo "cleanup-merged-refs: fetch failed; nothing deleted" >&2; exit 3; }
MAINTIP="$(G rev-parse "refs/remotes/$REMOTE/main" 2>/dev/null)" || { echo "cleanup-merged-refs: no $REMOTE/main" >&2; exit 2; }
# One PR table for the whole run. A truncated table would read "no open PR" for a
# branch it never listed, so a full page is a refusal, not a result.
PRS="$(cd "$REPO" && gh pr list --state all --limit 5000 --json number,headRefName,headRefOid,state 2>/dev/null)" || { echo "cleanup-merged-refs: gh PR lookup failed; nothing deleted" >&2; exit 3; }
[ "$(printf '%s' "$PRS" | jq 'length')" -lt 5000 ] || { echo "cleanup-merged-refs: PR table hit its 5000 cap; nothing deleted" >&2; exit 3; }
TODEL=()
while IFS= read -r ref; do
  [ -n "$ref" ] || continue
  name="${ref#"$REMOTE"/}"
  case "$name" in main|master|HEAD|release/*|backup/*) keep "$name" "protected name"; continue ;; esac
  lsr="$(G ls-remote --heads "$REMOTE" "refs/heads/$name")" || { COUNT_FAIL=$((COUNT_FAIL + 1)); echo "FAILED  $name  (ls-remote failed)"; rec "$name" failed "ls-remote failed"; continue; }
  tip="$(printf '%s\n' "$lsr" | awk 'NR==1{print $1}')"
  [ -n "$tip" ] || { keep "$name" "already gone from $REMOTE"; continue; }
  if printf '%s' "$PRS" | jq -e --arg b "$name" 'any(.[]; .headRefName == $b and .state == "OPEN")' >/dev/null; then keep "$name" "head of an open PR" "$tip"; continue; fi
  G cat-file -e "$tip^{commit}" 2>/dev/null || G fetch -q "$REMOTE" "refs/heads/$name" 2>/dev/null
  ct="$(G log -1 --format=%ct "$tip" 2>/dev/null)" || ct=""
  [ -n "$ct" ] || { keep "$name" "tip commit unreadable" "$tip"; continue; }
  [ $((NOW - ct)) -ge "$MIN_AGE_S" ] || { keep "$name" "tip younger than $MIN_AGE_H h" "$tip"; continue; }
  if G merge-base --is-ancestor "$tip" "$MAINTIP" 2>/dev/null; then why="tip is an ancestor of $REMOTE/main"
  elif [ "$BATCH" = D ] && printf '%s' "$PRS" | jq -e --arg b "$name" --arg t "$tip" 'any(.[]; .headRefName == $b and .state == "MERGED" and .headRefOid == $t)' >/dev/null; then why="tip is the head commit of a merged PR"
  else keep "$name" "tip is not in $REMOTE/main and not a merged PR head: pushed to after the merge, or never merged" "$tip"; continue; fi
  COUNT_DELETE=$((COUNT_DELETE + 1)); TODEL+=("$name"); echo "$([ "$APPLY" = 1 ] && echo delete || echo 'would delete')  $name  ($why)"
  if [ "$APPLY" = 1 ]; then rec "$name" queued "$why" "$tip"; else rec "$name" would-delete "$why" "$tip"; fi
done < <(nominees)

if [ "$APPLY" = 1 ] && [ "${#TODEL[@]}" -gt 0 ]; then
  i=0
  while [ "$i" -lt "${#TODEL[@]}" ]; do
    chunk=("${TODEL[@]:$i:$CHUNK}"); i=$((i + CHUNK))
    if G push -q "$REMOTE" --delete "${chunk[@]}" 2>/dev/null; then
      for n in "${chunk[@]}"; do rec "$n" deleted "chunk delete ok"; done
    else
      # One refused ref fails the whole push. Retry singly so one bad name costs one name.
      for n in "${chunk[@]}"; do
        if G push -q "$REMOTE" --delete "$n" 2>/dev/null; then rec "$n" deleted "single delete ok"
        else COUNT_FAIL=$((COUNT_FAIL + 1)); COUNT_DELETE=$((COUNT_DELETE - 1)); echo "FAILED  $n"; rec "$n" failed "push --delete refused"; fi
      done
    fi
    echo "chunk done: $i of ${#TODEL[@]}"
  done
fi

echo "cleanup-merged-refs: batch=$BATCH mode=$MODE $([ "$APPLY" = 1 ] && echo deleted || echo would_delete)=$COUNT_DELETE kept=$COUNT_KEEP failed=$COUNT_FAIL receipt=$RECEIPT"
[ "$COUNT_FAIL" -eq 0 ]
