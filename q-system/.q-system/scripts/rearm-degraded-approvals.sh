#!/usr/bin/env bash
# rearm-degraded-approvals.sh [--dry | --apply]
#
# ONE-SHOT SWEEP FOR ASK-3832. Gate 50 (ASK-2036) took auto-merge OFF every PR
# whose only review was the degraded Opus fallback and skipped it, and nothing
# ever re-ran those reviews: 39 degraded records between 2026-09-16 and
# 2026-10-23. RULE-2026-11-06-C removed the gate ("A degraded (Opus) approval
# is an approval"). Removing it fixes the next run of each issue, but only if
# the worker reaches that issue again, and a parked approved PR is not in the
# ready queue. This puts the arm back on the ones that are still mergeable.
#
# DRY BY DEFAULT. --apply is the only thing that writes, and it writes one
# thing per PR: `gh pr merge --auto --squash` through automerge_arm, the one
# arm call the worker and converge.sh share. No local state is written (the
# .automerge records keep their two writers; converge re-arms or re-reads).
#
# A PR IS SELECTED ONLY WHEN ALL FOUR HOLD, each read through the reader the
# worker uses, so this sweep and the worker cannot disagree about a PR:
#   1. its verdict record says degraded (degraded_from_record = 1)
#   2. rework_gate answers 10 with BOTH shas present AND GitHub's
#      mergeStateStatus as argument 2, exactly the inputs linear-worker.sh
#      passes: an approving verdict, pinned to the PR's head right now, on a
#      PR that is not DIRTY or BEHIND. A moved head is a re-review (40) and a
#      PR behind its base is a rebase round (30), never an arm. PR #607 review
#      round 1 (major): the first cut passed an empty merge state, so a PR six
#      weeks behind main read 10 here while the worker read 30.
#   3. GitHub says mergeable == MERGEABLE, and it is not a draft
#   4. the checkout gh binds to from cwd (automerge_arm cds there) resolves PR
#      N to the same head. gh can pick an `upstream` remote over `origin`; a
#      head match is the only cheap proof the arm lands on the PR we read.
#
# WHICH REPOS: every dispatch-enabled repo, which means the dispatcher's own
# fleet_candidates(), cut from kipi-dispatch.sh and run here. A second reader
# of "dispatch-enabled" is the drift this repo keeps paying for, so there is no
# copy of that rule in this file. Client repos are in it (RULE-2026-10-30-A).
#
# THE ARCHIVED ENGAGEMENT IS NEVER TOUCHED (RULE-2026-10-23-B). The only code
# that identifies it is the founder's PreToolUse hook ps-archive-deny.sh, so
# each repo's path and slug go through that hook BEFORE anything reads the
# repo, and a deny excludes it. No pattern is copied here: a copy would drift
# from the hook, and this repo is public. ALLOW_PS_ARCHIVE is stripped from the
# hook's environment, so a founder bypass in the calling shell does not open
# the archive to a sweep. A missing hook refuses the whole run (exit 3): a
# sweep that cannot tell the archive apart must not run.
#
# Exit: 0 clean, 2 a repo could not be read or an arm failed, 3 refused, 64 usage.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# KIPI_REPO, the dispatcher's own name for the home checkout, so a test points
# both at one fixture with one variable.
REPO="${KIPI_REPO:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
DISPATCH="$REPO/kipi-dispatch.sh"
REGISTRY="${KIPI_DISPATCH_REGISTRY:-$REPO/instance-registry.json}"
STATE_DIR="${KIPI_STATE_DIR:-$HOME/.config/kipi}"
REVIEWS_DIR="$STATE_DIR/pr-reviews"
# HOME is the seam, not a KIPI_* knob: a variable here would be a documented
# way to aim the archive guard at /bin/true (kipi-dispatch.sh refuses the same
# knob for its preflight, same reason).
ARCHIVE_GUARD="$HOME/.claude/hooks/ps-archive-deny.sh"

MODE="dry"
while [ $# -gt 0 ]; do
  case "$1" in
    --dry)   MODE="dry" ;;
    --apply) MODE="apply" ;;
    -h|--help) sed -n '2,3p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1 (use --dry or --apply)" >&2; exit 64 ;;
  esac
  shift
done

. "$SCRIPT_DIR/pr-verdict-lib.sh"   # sources repo-slug-lib.sh beside it

say() { printf '%s\n' "$*" >&2; }

if [ ! -f "$ARCHIVE_GUARD" ]; then
  echo "REFUSED: the archive guard $ARCHIVE_GUARD is missing, so the archived engagement (RULE-2026-10-23-B) cannot be told apart from a client repo. Not sweeping." >&2
  exit 3
fi
[ -f "$DISPATCH" ] || { echo "REFUSED: no kipi-dispatch.sh at $DISPATCH, so the dispatch-enabled set is unknown." >&2; exit 3; }

# THE CUT. Same shape test-repo-preflight.sh uses to run shipped code instead
# of a copy: from the `name() {` line to the first line that is exactly `}`.
# Both functions keep their heredocs indented or column-0 non-brace, so the
# first bare `}` is the function's own. An empty cut refuses rather than
# sweeping "no repos" and reading clean.
for fn in dispatch_targets_default fleet_candidates; do
  body="$(awk -v head="$fn() {" 'index($0, head) == 1 { on = 1 } on { print } on && $0 == "}" { exit }' "$DISPATCH")"
  if [ -z "$body" ]; then
    echo "REFUSED: kipi-dispatch.sh has no $fn(), so the dispatch-enabled set cannot be read the way the dispatcher reads it." >&2
    exit 3
  fi
  eval "$body"
done
KIPI_DISPATCH_TARGETS="$(dispatch_targets_default)"
export KIPI_DISPATCH_TARGETS

# archived <path> <slug> -> 0 when ps-archive-deny.sh refuses a call naming it
archived() {
  local payload out
  payload="$(python3 - "$1" "$2" <<'PY'
import json, sys
print(json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls %s %s" % (sys.argv[1], sys.argv[2])}}))
PY
)"
  out="$(printf '%s' "$payload" | env -u ALLOW_PS_ARCHIVE bash "$ARCHIVE_GUARD" 2>/dev/null)"
  case "$out" in *'"permissionDecision":"deny"'*) return 0 ;; esac
  return 1
}

short() { printf '%s' "${1:0:7}"; }

N_REPOS=0; N_EXCLUDED=0; N_UNREADABLE=0; N_PRS=0; N_DEGRADED=0
N_SELECTED=0; N_ALREADY=0; N_ARM=0; N_FAILED=0
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# FD 3 AND FD 4, NOT STDIN. Every command in these loops (gh, git, python3, the
# guard) inherits stdin, and one that reads it would silently eat the rest of
# the repo or PR list, and the sweep would report a short fleet as clean.
while IFS=$'\t' read -r -u 3 name path remote; do
  [ -n "$name" ] || continue
  N_REPOS=$((N_REPOS+1))
  # Guard FIRST: slug_for_repo below runs `git -C <path>`, which is a read.
  if archived "$path" "$name"; then
    N_EXCLUDED=$((N_EXCLUDED+1))
    echo "EXCLUDED $name: the archive guard refuses it (RULE-2026-10-23-B); not read"
    continue
  fi
  slug="$(KIPI_SLUG_REGISTRY="$REGISTRY" slug_for_repo "$path")"
  if [ -z "$slug" ]; then
    N_UNREADABLE=$((N_UNREADABLE+1))
    echo "UNREADABLE $name: no GitHub slug for $path (missing checkout or no remote)"
    continue
  fi
  if archived "$path" "$slug"; then
    N_EXCLUDED=$((N_EXCLUDED+1))
    echo "EXCLUDED $name ($slug): the archive guard refuses it (RULE-2026-10-23-B); not read"
    continue
  fi
  if ! gh pr list -R "$slug" --state open --limit 200 \
        --json number,headRefOid,mergeable,mergeStateStatus,isDraft \
        -q '.[] | [.number, .headRefOid, .mergeable, .mergeStateStatus, (.isDraft|tostring)] | @tsv' \
        > "$TMP/prs" 2> "$TMP/err"; then
    N_UNREADABLE=$((N_UNREADABLE+1))
    echo "UNREADABLE $name ($slug): gh pr list failed: $(tr '\n' ' ' < "$TMP/err" | cut -c1-200)"
    continue
  fi
  while IFS=$'\t' read -r -u 4 num head mergeable mstate draft; do
    [ -n "$num" ] || continue
    N_PRS=$((N_PRS+1))
    rec="$(verdict_record_path "$REVIEWS_DIR" "$slug" "$num")"
    [ "$(degraded_from_record "$rec")" = "1" ] || continue
    N_DEGRADED=$((N_DEGRADED+1))
    verdict="$(verdict_from_record "$rec")"
    rsha="$(head_sha_from_record "$rec")"
    rework_gate "$verdict" "$mstate" "$rsha" "$head" >/dev/null 2>&1; gate=$?
    tag="$slug#$num ($name)"
    if [ -z "$rsha" ] || [ -z "$head" ]; then
      echo "skip $tag: the approval cannot be pinned to the head (record sha '${rsha:-none}', head '${head:-unreadable}')"
      continue
    fi
    case "$gate" in
      10) : ;;
      40) echo "skip $tag: the degraded approval is for $(short "$rsha"), the head is now $(short "$head"); that needs a fresh review, not an arm"; continue ;;
      30) echo "skip $tag: degraded approval at the head, but GitHub says mergeStateStatus=$mstate; the worker gives that a rebase round (gate 30), not an arm"; continue ;;
      *)  echo "skip $tag: the degraded record reads '${verdict:-no verdict}', not an approval"; continue ;;
    esac
    if [ "$draft" = "true" ]; then
      echo "skip $tag: degraded approval at the head, but it is a draft and GitHub will not auto-merge a draft"
      continue
    fi
    if [ "$mergeable" != "MERGEABLE" ]; then
      echo "skip $tag: degraded approval at the head, but GitHub says mergeable=${mergeable:-unreadable}"
      continue
    fi
    cwd_head="$( cd "$path" 2>/dev/null && gh pr view "$num" --json headRefOid -q .headRefOid 2>/dev/null | tr -d '[:space:]' )"
    if [ "$(_sha_norm "$cwd_head")" != "$(_sha_norm "$head")" ]; then
      N_FAILED=$((N_FAILED+1))
      echo "FAILED $tag: gh run from $path resolves PR $num to head '${cwd_head:-unreadable}', not $(short "$head"); arming from there could hit another repo's PR"
      continue
    fi
    N_SELECTED=$((N_SELECTED+1))
    armed_now="$( cd "$path" 2>/dev/null && gh pr view "$num" --json autoMergeRequest -q '.autoMergeRequest != null' 2>/dev/null )"
    if [ "$armed_now" = "true" ]; then
      N_ALREADY=$((N_ALREADY+1))
      echo "ok $tag: already armed"
      continue
    fi
    if [ "$MODE" = "dry" ]; then
      N_ARM=$((N_ARM+1))
      echo "[dry] would arm $tag: degraded approval at $(short "$head"), MERGEABLE"
      continue
    fi
    automerge_arm "$num" "$path" "$TMP/arm.err"
    if [ "$AUTOMERGE_ARM_STATE" = "armed" ]; then
      N_ARM=$((N_ARM+1))
      echo "ARMED $tag: degraded approval at $(short "$head")"
    else
      N_FAILED=$((N_FAILED+1))
      echo "FAILED $tag: arm state '$AUTOMERGE_ARM_STATE': ${AUTOMERGE_ARM_ERR:-gh printed no reason}"
    fi
  done 4< "$TMP/prs"
done 3< <(fleet_candidates)

VERB="armed now"; [ "$MODE" = "dry" ] && VERB="would arm"
echo "-- $MODE: $N_REPOS dispatch-enabled repo(s), $N_EXCLUDED excluded as archived, $N_UNREADABLE unreadable; $N_PRS open PR(s), $N_DEGRADED with a degraded record; $N_SELECTED selected ($N_ALREADY already armed, $N_ARM $VERB); $N_FAILED failed"
if [ "$N_REPOS" -eq 0 ]; then
  echo "REFUSED: fleet_candidates returned no repo at all, not even home; nothing was swept" >&2
  exit 3
fi
[ "$N_UNREADABLE" -eq 0 ] && [ "$N_FAILED" -eq 0 ] || exit 2
exit 0
