#!/usr/bin/env bash
# cleanup-merged-refs.sh: delete merged remote branches and finished worktrees from a
# cleanup list, one batch at a time, re-checking every item at run time (ASK-4650).
#
# THE SCAR, 2026-11-12. A read-only census found 1,492 remote branches (585 merged,
# 40 of them plain ancestors of main) and 31 worktrees whose HEAD was already on main.
# delete_branch_on_merge was false, so every squash-merged PR left its branch behind,
# and the destructive-op hook (rightly) lets no agent delete any of it. The list was
# measured hours before the founder runs a delete, and a list goes stale: a branch gets
# new commits, a PR reopens, a "merged" tree is a launchd job's pinned checkout. So the
# LIST only nominates. This script decides, from live state, per item.
#
# Usage: cleanup-merged-refs.sh <list.md> --batch A|D|B [--apply] [--repo DIR]
#          [--remote origin] [--min-age-hours 24] [--chunk 25]
#   A  remote branches whose tip is an ancestor of <remote>/main.
#   D  remote branches whose PR is MERGED. Deleted only when the branch tip IS that PR's
#      head commit (or is an ancestor of main). A branch pushed to after the merge is
#      kept and named: it holds commits no PR carried to main.
#   B  worktrees. Removed with plain `git worktree remove` (no force flag): git itself
#      refuses a dirty tree. Also kept: locked, a pinned machine checkout, a process
#      working inside, touched inside min-age, HEAD at the remote main tip, branch of an
#      open PR.
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
    --batch) BATCH="${2:-}"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    --repo) REPO="${2:-}"; shift 2 ;;
    --remote) REMOTE="${2:-}"; shift 2 ;;
    --min-age-hours) MIN_AGE_H="${2:-}"; shift 2 ;;
    --chunk) CHUNK="${2:-}"; shift 2 ;;
    -h|--help) sed -n 2,31p "$0"; exit 0 ;;
    -*) echo "cleanup-merged-refs: unknown flag $1" >&2; exit 2 ;;
    *) LIST="$1"; shift ;;
  esac
done
case "$BATCH" in A|D|B) ;; *) echo "cleanup-merged-refs: --batch must be A, D or B" >&2; exit 2 ;; esac
[ -f "$LIST" ] || { echo "cleanup-merged-refs: list file not found: $LIST" >&2; exit 2; }
case "$MIN_AGE_H$CHUNK" in *[!0-9]*) echo "cleanup-merged-refs: --min-age-hours and --chunk are whole numbers" >&2; exit 2 ;; esac
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

if [ "$BATCH" = B ]; then
  # ---------------------------------------------------------------- worktrees
  PRS="[]"
  if command -v gh >/dev/null && P="$(cd "$REPO" && gh pr list --state open --limit 500 --json headRefName 2>/dev/null)"; then PRS="$P"
  else echo "cleanup-merged-refs: gh open-PR lookup failed; no tree is removed" >&2; exit 3; fi
  # Process census once: a failed census removes nothing (same rule as worktree-reaper.py).
  CWDS="$(lsof -a -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')" ; [ -n "$CWDS" ] || { echo "cleanup-merged-refs: lsof census empty; no tree is removed" >&2; exit 3; }
  MAINTIP="$(G rev-parse "refs/remotes/$REMOTE/main" 2>/dev/null)" || { echo "cleanup-merged-refs: no $REMOTE/main" >&2; exit 2; }
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    case "$path" in
      */.local/state/kipi/*|*/projects/kipi-scheduled|*/projects/kipi-scheduled/*) keep "$path" "pinned machine checkout, never removed"; continue ;;
    esac
    [ -f "$path/.git" ] || { keep "$path" "not a linked worktree (missing or primary checkout)"; continue; }
    gd="$(git -C "$path" rev-parse --absolute-git-dir 2>/dev/null)" || { keep "$path" "git cannot read it"; continue; }
    # Read the mtimes BEFORE `git status`: status refreshes the index and would make every
    # idle tree look touched a moment ago (the same trap worktree-reaper.py pins).
    newest=0; for f in "$gd/HEAD" "$gd/index"; do [ -e "$f" ] && { m="$(perl -e 'print((stat $ARGV[0])[9])' "$f")"; [ "$m" -gt "$newest" ] && newest="$m"; }; done
    [ $((NOW - newest)) -ge "$MIN_AGE_S" ] || { keep "$path" "touched inside the last $MIN_AGE_H h"; continue; }
    main_repo="$(cd "$path" && cd "$(git rev-parse --git-common-dir)/.." && pwd)"
    git -C "$main_repo" worktree list --porcelain | awk -v p="$path" '$1=="worktree"{cur=$2} $1=="locked"&&cur==p{f=1} END{exit !f}' && { keep "$path" "locked"; continue; }
    [ -z "$(git -C "$path" status --porcelain 2>/dev/null)" ] || { keep "$path" "has uncommitted or untracked files"; continue; }
    head="$(git -C "$path" rev-parse HEAD)"
    [ "$head" != "$MAINTIP" ] || { keep "$path" "HEAD is the $REMOTE/main tip: a fresh or pinned tree" "$head"; continue; }
    git -C "$path" merge-base --is-ancestor "$head" "refs/remotes/$REMOTE/main" 2>/dev/null || { keep "$path" "HEAD not contained in $REMOTE/main" "$head"; continue; }
    br="$(git -C "$path" symbolic-ref --short -q HEAD || true)"
    if [ -n "$br" ] && printf '%s' "$PRS" | jq -e --arg b "$br" 'any(.[]; .headRefName == $b)' >/dev/null; then keep "$path" "branch $br is the head of an open PR" "$head"; continue; fi
    printf '%s\n' "$CWDS" | awk -v p="$path" 'index($0, p) == 1 { f = 1 } END { exit !f }' && { keep "$path" "a process is working in it"; continue; }
    if [ "$APPLY" = 1 ]; then
      if git -C "$main_repo" worktree remove "$path" 2>/dev/null; then COUNT_DELETE=$((COUNT_DELETE + 1)); echo "removed $path"; rec "$path" removed "clean, merged, idle" "$head"
      else COUNT_FAIL=$((COUNT_FAIL + 1)); echo "FAILED  $path"; rec "$path" failed "git worktree remove refused" "$head"; fi
    else COUNT_DELETE=$((COUNT_DELETE + 1)); echo "would remove $path"; rec "$path" would-remove "clean, merged, idle" "$head"; fi
  done < <(nominees)
else
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
    tip="$(G ls-remote --heads "$REMOTE" "refs/heads/$name" | awk 'NR==1{print $1}')"
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
fi

echo "cleanup-merged-refs: batch=$BATCH mode=$MODE $([ "$APPLY" = 1 ] && echo deleted || echo would_delete)=$COUNT_DELETE kept=$COUNT_KEEP failed=$COUNT_FAIL receipt=$RECEIPT"
[ "$COUNT_FAIL" -eq 0 ]
