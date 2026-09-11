#!/usr/bin/env bash
# THE review agent for every PR in this fleet. Fresh eyes, adversarial, reproducer-or-it-didn't-happen.
#
# WHO IT IS
# ---------
# A senior staff engineer from Meta who has never seen this codebase. That
# persona is chosen for two specific properties, not for flavour:
#
#   FRESH EYES. It has no memory of why anything here is the way it is, so it
#   cannot be talked out of a finding by a comment that says "this is fine". The
#   author of this repo (and the agent that wrote the PR) share one mental model;
#   a reviewer inside that model re-derives the same blind spots. Measured on this
#   very fleet 2026-07-26: a hand-rolled test fixture used a JSON key no producer
#   emits, so a mutex's remote half never fired while its suite stayed green. Only
#   an outsider checking the real payload caught it.
#
#   OPERATIONAL BAR. Meta staff review is about what happens at 3am: blast
#   radius, failure modes, what pages a human, what cannot be rolled back. This
#   fleet runs unattended agents against permanent Linear objects and a public
#   repo. That is exactly the bar it needs.
#
# THE STANDING RULE
# -----------------
# EVERY finding must ship a RUNNABLE REPRODUCER that was actually executed. A
# finding with no repro is an opinion and is rejected at triage. This is not
# politeness: the substitute reviewer earned its keep on 2026-07-25 and 07-26 by
# producing repros, and the same discipline is what stops an adversarial reviewer
# from generating plausible-sounding noise.
#
# PROVENANCE
# ----------
# Reviews are recorded as `claude-adversarial`, which findings_writer.py accepts
# as a REVIEWER_SOURCE. It did not before 2026-07-26: a Claude reviewer had to
# either stamp `codex-adversarial` (a false record) or skip the stamp and never
# approve. In a repo whose thesis is receipts, the honest token had to exist first.
#
# TWO ENGINES, ONE SCRIPT -- CLAUDE IS THE ONE THAT GATES (founder-directed 2026-09-06)
# ---------------------------------------------------------------------------------
# THIS REVERSES the 2026-07-29 directive recorded below. Founder, 2026-09-06, said
# twice: "forget codex use claude for fallback" / "forget codex go with the claude
# fallback". So claude is now THE reviewer: it owns `kipi/reviewer-approved` and
# writes the ONE verdict record converge.sh and linear-worker.sh gate on. codex keeps
# the same script but posts an ADVISORY `kipi/codex-approved` out of the gate's way.
#
# THE COST IS REAL AND IS ACCEPTED, not overlooked. Sana (the PR author) is Claude, so
# a Claude reviewer shares her lab and model family and re-derives her blind spots;
# fresh context is not an independent mind. That was the whole argument for the
# 2026-07-29 directive, "codex with gpt-5.6 as a sr. staff swe at Meta is the agent
# that checks sana's work", and it is still true. What changed is availability, not
# the argument. Restoring independence is `KIPI_REVIEW_ENGINE=codex
# KIPI_REVIEW_PRIMARY_ENGINE=codex`, both together, or flipping the two defaults back.
#
# WHY IT CHANGED, measured 2026-09-06 as three stacked failures each masking the next:
# ~/.codex/config.toml asked for `gpt-6-astra` when the fleet is on Sol; codex-cli
# 0.147.0 was too old for that model and returned HTTP 400; and underneath both, the
# workspace is OUT OF CREDITS, which `gpt-5.6-sol` returns too. `codex exec` exits 0
# on all three, so two sessions reviewed for a full evening on the Opus fallback and
# nothing said so. An engine that fails silently cannot hold a required gate.
#
# BOTH DEFAULTS MOVE TOGETHER OR THE GATE WEDGES. The branch below posts
# `kipi/reviewer-approved` only when ENGINE equals PRIMARY_ENGINE. Setting
# KIPI_REVIEW_ENGINE=claude alone leaves PRIMARY_ENGINE=codex, so every review lands
# on the advisory context and every open PR waits forever on a status nobody posts.
#
# THERE IS NO FALLBACK IN THE NEW DIRECTION, and saying so plainly is the point.
# The Opus fallback and the whole DEGRADED apparatus hang off the codex branch:
# codex down -> claude fills the slot -> the status says DEGRADED. With claude
# PRIMARY that branch is only reachable on an advisory `--engine codex` hand-run,
# so a claude outage has nothing behind it. That is the SAFE direction and not an
# oversight: the primary path exits non-zero and posts NO status, and absent is
# not approved, so a claude outage holds PRs instead of greening them. It is not
# a second lab either way -- codex is out of credits, so a codex fallback would
# fail at exit 0, which is the outage this flip exists to end. Restoring a real
# fallback means restoring codex, which is the same act as restoring independence.
#
# It is a FLAG, not a second script, on purpose: sha capture (ASK-216), verdict
# derivation from labelled severities, the commit-status post (ASK-217) and
# spillover capture all stay shared and identical. A separate codex script would
# be a second writer with its own semantics -- the defect class this repo keeps
# finding. What the engine changes is exactly three things: which binary runs,
# which status context it posts, and which directory its artifacts land in.
#
# Usage:  pr-review-agent.sh <pr-number> [--issue ASK-nnn] [--post]
#                            [--engine claude|codex] [--force] [--queue]
#         --post also comments the review on the PR and the Linear issue.
#         --force runs even when this head already carries a verdict comment.
#         --queue waits for a concurrency slot instead of refusing immediately.
#
# EXIT CODES, and they are part of the contract because a queue script reads them:
#   0  reviewed (or dry-run surveyed); nothing further is advised
#   1  could not review: bad arguments, no PR, a moving head, no tree at the sha
#   2  refused at resolution: this copy does not live at a repo root
#   3  REFUSED TO START: this head already has a verdict, or two reviews are
#      already live. Nothing was dispatched and no status was posted.
#   4  ran and posted, AND the findings repeat a file from the previous
#      REQUEST CHANGES round. The post is complete; the next patch is the wrong
#      move (sp-46726f79). Advisory to the caller, never a block on the post.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKEL="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# REFUSE unless SKEL is actually a repo root. `../../..` encodes "this script
# lives exactly 3 levels below the root" and nothing ever asserted it. A copy
# dropped 2 levels deep (.pr28rev/scripts/) overshoots by one and lands OUTSIDE
# the repo: on 2026-08-04 one resolved to the checkout's PARENT directory (the
# one holding every project), which is
# not a git repo, so `gh pr diff` returned nothing and the model formed a
# verdict from the prompt alone -- then that empty review was posted as a
# passing commit status. Measured 2026-08-05: 79 of 102 copies on this box
# resolve SKEL to a non-repo.
#
# Every downstream check that could have caught it degrades to "warn and
# proceed" (a reviewer that cannot fetch should not wedge the loop), and codex's
# own repo check is disabled by --skip-git-repo-check. So the assertion has to
# be here, at the point of resolution, and it has to REFUSE. Reviewing nothing
# and reporting APPROVE is worse than not running: it manufactures evidence.
#
# Compares against the toplevel rather than just `rev-parse` succeeding, because
# a path merely INSIDE a repo would otherwise pass while reviewing a subtree.
#
# Both sides are resolved to PHYSICAL paths before comparing. `pwd` keeps
# symlinks while git reports the real path, so on macOS a repo under /var
# resolves to /var/... on one side and /private/var/... on the other and a naive
# string compare refuses a perfectly good canonical checkout. A guard that false
# -refuses gets switched off, and a gate that is off protects nothing. Caught by
# this guard's own test on first run (2026-08-05).
_SKEL_TOPLEVEL="$(git -C "$SKEL" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$_SKEL_TOPLEVEL" ]; then
  _SKEL_TOPLEVEL="$(cd "$_SKEL_TOPLEVEL" 2>/dev/null && pwd -P || echo "$_SKEL_TOPLEVEL")"
fi
_SKEL_PHYS="$(cd "$SKEL" && pwd -P)"
if [ -z "$_SKEL_TOPLEVEL" ] || [ "$_SKEL_TOPLEVEL" != "$_SKEL_PHYS" ]; then
  echo "REFUSING: resolved review root is not a git repository root." >&2
  echo "  script:        ${BASH_SOURCE[0]}" >&2
  echo "  resolved root: $SKEL" >&2
  echo "  git toplevel:  ${_SKEL_TOPLEVEL:-<not a git repository>}" >&2
  echo "This script must live exactly 3 levels below the repo root" >&2
  echo "(<repo>/q-system/.q-system/scripts/). Run the canonical copy, not a" >&2
  echo "copy inside a review-scratch tree." >&2
  exit 2
fi
unset _SKEL_TOPLEVEL _SKEL_PHYS
SYNC="$SCRIPT_DIR/linear-sync.py"
OUT_DIR="$HOME/.config/kipi/pr-reviews"
TIMEOUT_SECONDS=2400
NOTIFY="${KIPI_NOTIFY:-$SCRIPT_DIR/slack-notify.sh}"

# PIN THE REVIEWER'S IDENTITY. Before ASK-221 the claude engine passed no
# --model and silently inherited whatever the calling session defaulted to, so
# "the reviewer" was a different model depending on who woke it. A reviewer whose
# identity drifts cannot be reasoned about: the severity anchors are calibrated
# against a specific bar, and a weaker model drops exactly the subtle findings
# that earn this thing its keep. Env-overridable so a model bump is a config
# change, not an edit to a script that gates every PR in the repo.
CLAUDE_MODEL="${KIPI_REVIEW_CLAUDE_MODEL:-claude-opus-5}"
CODEX_MODEL="${KIPI_REVIEW_CODEX_MODEL:-gpt-5.6-sol}"
# Verdict semantics live in ONE place, shared with the worker. Two scripts each
# grepping the review prose with their own regex is two readers with different
# semantics -- the defect class review round 2 flagged on this very PR line.
. "$SCRIPT_DIR/pr-verdict-lib.sh"
# THE ONE SLUG DERIVATION (ASK-738).
. "$SCRIPT_DIR/repo-slug-lib.sh"



# CODEX BY DEFAULT. Env-overridable so a codex outage long enough to matter is a
# config change (`KIPI_REVIEW_ENGINE=claude`), not an edit to the script that
# gates every PR in the repo.
PR=""; ISSUE=""; POST=0; ENGINE="${KIPI_REVIEW_ENGINE:-claude}"; TARGET_REPO_ARG=""
# --force and --queue are the two documented ways past the two refusals added for
# sp-fa810306 and sp-0a09e013. Both are opt-in and neither has an env form: an
# env default would let a scheduled caller inherit the bypass without anyone
# having typed it, which is how a guard ends up permanently off.
FORCE=0; QUEUE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --issue)  shift; ISSUE="${1:-}" ;;
    --engine) shift; ENGINE="${1:-}" ;;
    --force)  FORCE=1 ;;
    --queue)  QUEUE=1 ;;
    # WHICH REPO THE WORK IS IN (ASK-738). $SKEL is where this CODE lives; it is
    # not where the PR lives. Before this argument the two were the same
    # variable, so a review of an external PR number resolved against the home
    # repo -- and if that number existed there, the wrong repository's code was
    # reviewed and got the verdict and the commit status.
    --repo)   shift; TARGET_REPO_ARG="${1:-}" ;;
    --post)   POST=1 ;;
    -*) echo "unknown arg: $1" >&2; exit 1 ;;
    *) PR="$1" ;;
  esac
  shift || true
done

# RESOLVED AFTER THE ARGUMENT LOOP, and that placement is the whole point.
# This block first sat above the loop, so it read TARGET_REPO_ARG before the
# loop had parsed it AND before line "PR=\"\"; ISSUE=..." reset it to empty --
# `--repo` was a DEAD FLAG that silently fell through to $SKEL. Caught by codex
# on PR #146; my own test missed it because it drove the env form
# (KIPI_TARGET_REPO), which resolves the same either way. A flag with no test
# that exercises the FLAG is an untested flag.
# REVIEW_REPO is the repo UNDER REVIEW. $SKEL stays what it always was: where the
# control code lives. Every git read that asks "does this tree hold the PR"
# targets REVIEW_REPO; every gh call is scoped to its slug. Defaults to $SKEL, so
# every existing caller behaves exactly as before.
# WHAT MODE THIS RUN IS IN, DERIVED ONCE (ASK-758). The OUTWARD side effects --
# the PR comment, the commit status, the Linear post -- are inside `if POST=1`,
# but the verdict line and the closing line are not, so a default invocation
# printed `verdict: APPROVE` and `done` with nothing a human or a required check
# could see. The dry transcript and the real approving transcript were the same
# text; the difference was only discoverable by going and proving zero statuses
# exist. One derivation, appended at both places a reader forms a belief, so the
# two can never disagree about the mode.
#
# THE NOTE SAYS WHAT IS AND IS NOT TRUE, and the first draft got the second half
# wrong: it read "no gate moved". A dry run DOES move a gate. The verdict record
# is written below at the `verdict_record_write_path` call, ~100 lines ABOVE the
# `if [ "$POST" = "1" ]` block -- so it is written on every run -- and that
# record is the one converge.sh:748 and linear-worker.sh:1054 read to decide
# approve-vs-rework. Telling a reader no gate moved is the same silent-dry-run
# defect aimed at the reader who did read the label, and worse, because they
# trusted it. So the note names both halves: what was withheld, and what landed.
DRY_NOTE=""
[ "$POST" = "1" ] || DRY_NOTE=" (DRY RUN -- nothing posted to GitHub or Linear; the verdict record WAS written and the loop still gates on it; re-run with --post)"

REVIEW_REPO="${TARGET_REPO_ARG:-${KIPI_TARGET_REPO:-$SKEL}}"
[ -d "$REVIEW_REPO" ] || { echo "--repo: no such directory: $REVIEW_REPO" >&2; exit 1; }
REVIEW_REPO="$(cd "$REVIEW_REPO" && pwd)"
REVIEW_SLUG="$(slug_for_repo "$REVIEW_REPO" "${KIPI_SLUG_REGISTRY:-$SKEL/instance-registry.json}")"
KIPI_GH_REPO_ARGS="$(gh_repo_args "$REVIEW_SLUG")"
export KIPI_GH_REPO_ARGS
# The prompt below tells the MODEL to run `gh pr view` / `gh pr diff` itself. An
# unscoped instruction there reads another repository's diff no matter what this
# script does, so the scope has to travel INTO the prompt text too.
GH_R_PROMPT=""
[ -n "$REVIEW_SLUG" ] && GH_R_PROMPT="-R $REVIEW_SLUG "
# `gh api` cannot take -R (see post_status). Empty slug keeps the placeholder
# form, which is what every pre-ASK-738 caller and fixture already relies on.
STATUS_REPO_PATH="{owner}/{repo}"
[ -n "$REVIEW_SLUG" ] && STATUS_REPO_PATH="$REVIEW_SLUG"
[ -n "$PR" ] || { echo "usage: pr-review-agent.sh <pr-number> [--issue ASK-nnn] [--post] [--engine claude|codex] [--force] [--queue]" >&2; exit 1; }

# ONE PID FILE PER (REPO, PR), AND NEVER A THIRD CONCURRENT REVIEW (sp-0a09e013).
#
# THE SCAR, measured: on the evening of 2026-09-05 five reviewers and watchers
# started as tracked tool calls were killed by the harness under memory pressure,
# and on 2026-09-07 at 00:35Z a process exit took a nohup'd reviewer with it,
# orphaning two tasks and losing a posted approval. Nothing on this box could
# answer "how many reviews are live right now", so the answer was always "start
# another one" -- and each one costs a full Opus review of a real diff.
#
# THE FILE IS THE ANSWER, not a process table scan. `pgrep -f pr-review-agent`
# matches its own grep and every editor buffer holding the name, which is the
# same class of miscount this fleet already recorded. A file written at start and
# removed by the EXIT trap is checkable by anyone, survives the session that
# spawned it, and self-heals: a pid the OS no longer knows is stale and is
# reclaimed, because an operator who must clear these by hand eventually clears
# one while a run is live.
#
# SAME DIRECTORY AS THE REVIEW TREES AND THEIR LOCKS, deliberately. That is the
# one place this script already owns per (repo, PR) state, so a reader looking
# for "what is this reviewer doing" finds the tree, the lock and the pid together
# instead of in three conventions.
#
# HONEST BOUNDARY: pid numbers are recycled. A stale file whose number has been
# handed to an unrelated process reads as live and costs one false refusal, which
# is the safe direction -- a false refusal names the file and exits 3, while a
# false start is the duplicate review this exists to stop.
REVIEW_PID_DIR="$(dirname "$(review_tree_path "$HOME/.config/kipi" "$REVIEW_SLUG" "$PR")")"
REVIEW_PID_FILE="$REVIEW_PID_DIR/$(artifact_key "$REVIEW_SLUG" "$PR").pid"
REVIEW_PID_WRITTEN=0
# CONCURRENCY CAP: at most 2 live runs, so this one is refused when 2 already are.
REVIEW_CONCURRENCY_CAP="${KIPI_REVIEW_CONCURRENCY_CAP:-2}"
REVIEW_QUEUE_SECONDS="${KIPI_REVIEW_QUEUE_SECONDS:-900}"

_pid_in_file() { tr -dc '0-9' < "${1:-}" 2>/dev/null | head -c 12; }

_review_pid_release() {
  # ONLY OUR OWN. Removing a pid file whose contents are someone else's pid would
  # release THEIR slot, which is the concurrent-reviewer defect wearing a cleanup
  # costume -- the same reasoning release_wt_lock already carries below.
  [ "$REVIEW_PID_WRITTEN" = "1" ] || return 0
  if [ "$(_pid_in_file "$REVIEW_PID_FILE")" = "$$" ]; then
    command rm -f "$REVIEW_PID_FILE" 2>/dev/null || true
  fi
  REVIEW_PID_WRITTEN=0
}

# _live_review_pids -> one "<pidfile> <pid>" line per LIVE run that is not US.
# Reaps stale files as it goes: the scan is the only thing that ever runs after a
# killed reviewer, so if it does not clean up, nothing does.
#
# SKIPS BY PID, NEVER BY PATH (round 1 major, 2026-09-07). The first cut skipped
# `$REVIEW_PID_FILE` by name, which is exactly the file a SECOND RUN ON THE SAME
# PR writes -- so the one collision that matters most was the one collision the
# scan could not see, and the second run then overwrote the incumbent's pid,
# silently taking over its slot while both read the same detached worktree.
# Identity is the pid, so that is what the skip compares.
_live_review_pids() {
  local f pid
  for f in "$REVIEW_PID_DIR"/*.pid; do
    [ -f "$f" ] || continue
    pid="$(_pid_in_file "$f")"
    [ "$pid" = "$$" ] && continue
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      printf '%s %s\n' "$f" "$pid"
    else
      echo "  reclaimed a stale reviewer pid file (pid ${pid:-<empty>} is gone): $f" >&2
      command rm -f "$f" 2>/dev/null || true
    fi
  done
}

mkdir -p "$REVIEW_PID_DIR" 2>/dev/null || true
_REVIEW_WAITED=0
while :; do
  # The scan runs first because it is what reclaims stale files, including this
  # PR's own -- so anything still on disk afterwards holds a pid that is alive.
  _LIVE="$(_live_review_pids)"
  _LIVE_N="$(printf '%s' "$_LIVE" | grep -c . || true)"
  _MINE="$(_pid_in_file "$REVIEW_PID_FILE")"
  _BLOCK=""
  if [ -n "$_MINE" ] && [ "$_MINE" != "$$" ]; then
    # A SECOND RUN ON THE SAME PR IS REFUSED BELOW THE CAP, and that is not the
    # cap being strict. Two runs on one PR share ONE detached review tree and ONE
    # pid file: the second re-checkouts the tree while the first is reading files
    # out of it, and both stamp verdicts with the sha they think they read. The
    # numeric cap cannot express that, because one incumbent is under it.
    _BLOCK="a review of PR #$PR is already live (pid $_MINE). Two runs on one PR share one detached worktree and one pid file, so the second would re-checkout that tree under the first."
  elif [ "${_LIVE_N:-0}" -ge "$REVIEW_CONCURRENCY_CAP" ]; then
    _BLOCK="$_LIVE_N reviews are already live (cap $REVIEW_CONCURRENCY_CAP)."
  fi
  [ -z "$_BLOCK" ] && break
  if [ "$QUEUE" != "1" ]; then
    echo "REFUSING: $_BLOCK No review was dispatched and NO status was posted." >&2
    printf '%s\n' "$_LIVE" | sed 's/^/  live: /' >&2
    echo "  Wait for it to finish, or re-run with --queue to wait up to ${REVIEW_QUEUE_SECONDS}s for a slot." >&2
    exit 3
  fi
  # BOUNDED WAIT, NOT AN OPEN ONE. An unbounded queue turns a stuck reviewer into
  # a pile of blocked reviewers that all wake at once when it dies.
  if [ "$_REVIEW_WAITED" -ge "$REVIEW_QUEUE_SECONDS" ]; then
    echo "REFUSING: waited ${_REVIEW_WAITED}s for a slot and it is still blocked: $_BLOCK No review was dispatched and NO status was posted." >&2
    exit 3
  fi
  [ "$_REVIEW_WAITED" = "0" ] && echo "blocked: $_BLOCK --queue given, waiting up to ${REVIEW_QUEUE_SECONDS}s for a slot..."
  sleep 10
  _REVIEW_WAITED=$(( _REVIEW_WAITED + 10 ))
done
printf '%s' "$$" > "$REVIEW_PID_FILE" 2>/dev/null && REVIEW_PID_WRITTEN=1
# ARMED BEFORE THE FIRST THING THAT CAN EXIT. Every refusal below this line is a
# path the pid file has to survive, and the worktree lock's own trap further down
# REPLACES this one, so that line clears both. A trap set after the first exit
# path is a trap that leaks on exactly the failures it exists for.
trap '_review_pid_release' EXIT

# WHAT THE ENGINE CHANGES. Everything else below this block is shared, which is
# the whole reason this is a flag and not a second script.
#
# TWO SEPARATE DIRECTORY QUESTIONS, deliberately decoupled -- conflating them is
# what made codex non-gating before the founder directive, and naively swapping
# the pair would have introduced a fresh defect in the other direction:
#
#   ENGINE_DIR (reviews + ROUND COUNTER). review_round() globs `pr-<N>-*.md`, so
#   an engine reading another engine's review files counts their rounds as its own
#   and arms the anti-re-litigation rule early. Each engine therefore KEEPS its
#   historical directory across this change -- claude's rounds stay in $OUT_DIR,
#   codex's in $OUT_DIR/codex. Nothing about the counters moves.
#
#   VERDICT_DIR (the ONE record the loop gates on). converge.sh:36 and
#   linear-worker.sh:76 both read `$STATE_DIR/pr-reviews/pr-<N>.verdict.json` --
#   the ROOT, not a subdir. So "claude is the gate" means claude writes THAT path,
#   and codex's record moves down into $OUT_DIR/codex to get out of its way.
#   Exactly one engine writes the gating record: single writer, preserved.
#
#   THIS SENTENCE READ THE OTHER WAY ROUND UNTIL 2026-09-06 and is the map people
#   read to understand the contract, so it flips with the defaults rather than
#   being left as an artifact of the previous direction. Note the asymmetry it
#   creates: for the PRIMARY engine ENGINE_DIR and VERDICT_DIR are now the SAME
#   directory ($OUT_DIR). That is safe because review_round globs `pr-<N>-*.md`
#   and the record is `..._pr-<N>.verdict.json`, so neither ever counts the other
#   -- measured on the live store, 88 .md at the root and 993 under codex/.
PRIMARY_ENGINE="${KIPI_REVIEW_PRIMARY_ENGINE:-claude}"

# WHO ASKED FOR THIS REVIEW (sp-53aad86f). The verdict record proved that A CODEX
# REVIEW RAN; it could not prove THE DISPATCHER RAN ONE UNATTENDED, which is the
# only thing that actually closes the loop. A hand-run review and a scheduled one
# wrote byte-identical evidence, so no number of green checks answered the
# question -- every proof shown to the founder had this hole in it.
#
# DEFAULT IS `manual`, AND THAT IS THE WHOLE SAFETY PROPERTY. An unlabelled run
# must never pass as dispatcher-driven, or the field manufactures exactly the
# evidence it exists to supply. Same posture as the commit status: absent is not
# approved. Records written before this field existed carry no key at all, and the
# verifier treats a missing key as not-dispatcher for the same reason.
#
# Set by linear-worker.sh at its single reviewer call site, so the label follows
# the real invocation path rather than being something a human remembers to pass.
INVOKER="${KIPI_REVIEW_INVOKER:-manual}"
case "$ENGINE" in
  claude) ENGINE_DIR="$OUT_DIR" ;;
  codex)  ENGINE_DIR="$OUT_DIR/codex" ;;
  *) echo "unknown engine: '$ENGINE' (expected claude|codex)" >&2; exit 1 ;;
esac
# The gate belongs to the PRIMARY engine; the other engine is advisory. Naming the
# advisory context per-engine (never `kipi/reviewer-approved`) is what stops two
# writers from ever answering for the same slot.
if [ "$ENGINE" = "$PRIMARY_ENGINE" ]; then
  VERDICT_DIR="$OUT_DIR";              STATUS_CONTEXT="kipi/reviewer-approved"; MINOR_TAG=""
else
  VERDICT_DIR="$OUT_DIR/$ENGINE";      STATUS_CONTEXT="kipi/$ENGINE-approved";  MINOR_TAG="$ENGINE "
fi
# Degraded is a property of the ENGINE, not of a PR: codex being down is one
# fact, and paging per-PR would turn one outage into a page per open PR.
DEGRADED_STATE="$OUT_DIR/codex/degraded.state"
DEGRADED=0
# Set when THE REVIEW IN THE PRIMARY SLOT is not parseable, whichever engine
# produced it. It is a SEPARATE flag from the derived verdict because
# verdict_from_findings reads an unclosed FINDINGS block as an EMPTY one and
# returns APPROVE -- so "the derivation produced something" is not evidence that
# the review said anything. Caught by the truncated-stream case in
# test-severity-floor.sh, which passed the first cut of this fix.
#
# It was CODEX_UNUSABLE and checked only on the codex path. Codex itself found the
# hole on 2026-07-29 reviewing this branch (major, pr-review-agent.sh:403): the
# Opus FALLBACK path had no such check, so a fallback that exited 0 with truncated
# output would derive APPROVE and post state=success on the REQUIRED context --
# a green gate for a review nobody read, which is the worst outcome in this script.
# The flag is a property of the SLOT, not of the engine.
REVIEW_UNUSABLE=0

mkdir -p "$ENGINE_DIR" "$VERDICT_DIR"
TS() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# THE ONE DEFINITION of the marker that says "this head already has a verdict"
# (sp-fa810306). Written into every posted comment, read back before every run.
# An HTML comment because GitHub does not render it: the marker is for machines,
# and a visible one would be the first thing a human asked to have removed.
#
# WHY A MARKER AND NOT THE SHA IN PROSE. A sha appears inside a diff, inside a
# quoted earlier comment, and inside anything a person pastes, so grepping the
# comment text for the sha fires on comments that are not verdicts. WHY NOT THE
# LOCAL VERDICT RECORD: the whole scar is a local record disagreeing with what
# GitHub holds, so the check has to read GitHub.
review_head_marker() { printf '<!-- kipi-reviewer: head=%s -->' "${1:-}"; }
REVIEW="$ENGINE_DIR/$(artifact_key "$REVIEW_SLUG" "$PR")-$(date +%Y%m%d-%H%M%S).md"

# Same bash wall clock as the worker: macOS ships no `timeout` without coreutils,
# and a review that never returns is worse than one that fails.
run_bounded() {
  local secs="$1"; shift
  "$@" & local job=$!
  ( sleep "$secs"; kill -0 "$job" 2>/dev/null && { kill -TERM "$job" 2>/dev/null; sleep 5; kill -KILL "$job" 2>/dev/null; } ) &
  local w=$!; wait "$job"; local rc=$?; kill "$w" 2>/dev/null; wait "$w" 2>/dev/null; return "$rc"
}

command -v gh >/dev/null 2>&1 || { echo "gh CLI required" >&2; exit 1; }
# ONE read of the PR's state, and the head sha comes out of it (ASK-216).
# Capturing it here -- before the reviewer is dispatched, in the same API read
# that proves the PR exists -- is the whole point: looked up AFTER the review,
# a push landing mid-review would make the record claim a commit the reviewer
# never saw, which is worse than no sha because it looks authoritative. Erring
# the other way (a push between here and the reviewer's own `gh pr diff`) pins
# the OLDER sha, which reads as drift and routes to a re-review. Safe direction.
# The sha is first in the tuple so a tab inside a PR title cannot displace it.
PR_META="$(gh pr view "$PR" $KIPI_GH_REPO_ARGS --json headRefOid,title -q '.headRefOid + "\t" + .title' 2>/dev/null)" \
  || { echo "no PR #$PR" >&2; exit 1; }
HEAD_SHA="${PR_META%%$'\t'*}"
PR_TITLE="${PR_META#*$'\t'}"

# CONFIRM THE HEAD HAS SETTLED (sp-f8edcdeb). The comment above reasons that
# pinning an OLDER sha is the safe direction because it reads as drift and routes
# to a re-review. That is true of the GATE, and it was still wrong in practice:
# on 2026-07-30 a push and a review ran in the same command, `gh pr view` returned
# the PRE-PUSH sha, and the run posted kipi/reviewer-approved=SUCCESS on it. The
# newest commits went unreviewed while a green required check sat on the branch.
# Drift catches it on the next worker pass; a human reading the PR in between sees
# a green codex check that does not cover the top commits.
#
# A second read a few seconds later is enough, because the failure is propagation
# delay, not a persistent disagreement. Refuse rather than adopt the newer value:
# if the head is moving RIGHT NOW, whatever we pick may be stale again by the time
# the model finishes, and a review nobody ran is cheaper than a green check on the
# wrong code. Also catches a concurrent push by anyone, which the caller cannot.
#
# The confirm read uses the IDENTICAL query and the IDENTICAL extraction as the
# first one. A differently-shaped second query is a second reader of one fact:
# my first cut asked for `--json headRefOid -q .headRefOid` while the first read
# asked for the sha+title tuple, so the two strings never matched and the check
# refused every review. Caught by test-review-tree-guard going 1/23.
sleep 3
PR_META_CONFIRM="$(gh pr view "$PR" $KIPI_GH_REPO_ARGS --json headRefOid,title -q '.headRefOid + "\t" + .title' 2>/dev/null || true)"
HEAD_SHA_CONFIRM="${PR_META_CONFIRM%%$'\t'*}"
if [ -n "$HEAD_SHA_CONFIRM" ] && [ "$HEAD_SHA_CONFIRM" != "$HEAD_SHA" ]; then
  echo "REFUSING: PR #$PR's head moved between two reads (${HEAD_SHA:0:8} then ${HEAD_SHA_CONFIRM:0:8})." >&2
  echo "  Something is pushing to this branch right now. Reviewing either sha risks a green status on code the reviewer did not read." >&2
  echo "  Re-run once the branch settles. No review was dispatched and NO status was posted." >&2
  exit 1
fi
# A HEAD THAT ALREADY CARRIES A VERDICT IS NOT RE-REVIEWED (sp-fa810306).
#
# THE SCAR, exact: on 2026-09-07 round 3 of PR #314 posted APPROVE WITH NITS as a
# comment at 00:29:47Z on head adc29516, the process died before the commit status
# landed, and the next session read `gh api statuses adc29516` as empty. Empty
# looked like "never reviewed", so the same head was re-run at 00:36:54Z -- and
# that re-run returned REQUEST CHANGES, overturning an approval that had already
# been earned. Two more rounds and about 90 minutes.
#
# THE COMMENT IS THE DURABLE RECORD, NOT THE STATUS, and that is the whole point
# of checking it here. The status post is the thing that was lost; the comment is
# the thing that survived. So this asks the question the re-running session should
# have asked: has a reviewer already published a verdict on THIS EXACT COMMIT?
# Posting the status BEFORE the comment (further down) closes the other half.
#
# FAILS OPEN. A gh outage, a network error, or a PR with no comments all yield
# zero hits and the review proceeds. Refusing on an unreadable comment list would
# wedge every review on a GitHub blip, which is worse than one duplicate round --
# and the duplicate round is what the caller asked for in the first place.
if [ -n "$HEAD_SHA" ]; then
  DUP_MARKER="$(review_head_marker "$HEAD_SHA")"
  DUP_HITS="$(gh pr view "$PR" $KIPI_GH_REPO_ARGS --json comments -q '.comments[].body' 2>/dev/null | grep -F -c -- "$DUP_MARKER" || true)"
  DUP_HITS="$(printf '%s' "${DUP_HITS:-0}" | tr -dc '0-9')"
  [ -n "$DUP_HITS" ] || DUP_HITS=0
  if [ "$DUP_HITS" -gt 0 ] && [ "$FORCE" != "1" ]; then
    echo "REFUSING: PR #$PR head ${HEAD_SHA:0:8} already carries $DUP_HITS reviewer verdict comment(s). Re-reviewing a head that has already been judged can only overturn a verdict that was already earned (sp-fa810306). No review was dispatched and NO status was posted." >&2
    echo "  Read the existing verdict on the PR, or pass --force if a second opinion on the same commit is what you actually want." >&2
    exit 3
  fi
  [ "$DUP_HITS" -gt 0 ] && echo "  NOTE: ${HEAD_SHA:0:8} already carries $DUP_HITS verdict comment(s); --force given, reviewing it again."
fi

[ -n "$ISSUE" ] || ISSUE="$(printf '%s' "$PR_TITLE" | grep -oE 'ASK-[0-9]+' | head -1)"

echo "$(TS) reviewing PR #$PR: $PR_TITLE"
echo "  head sha under review: ${HEAD_SHA:-unknown}"
[ -n "$ISSUE" ] && echo "  linked issue: $ISSUE"

# THE TREE MUST ACTUALLY CONTAIN THE PR (sp-a72a9567). $SKEL comes from this
# script's own location, and the diff comes from `gh pr diff <N>` -- two
# independent sources that nothing was checking against each other. Run from
# worktree A against a PR on branch B and the reviewer reads A's files off disk
# while B's diff scrolls past, then writes a verdict record and a commit status
# attributing its findings to B's head sha.
#
# Not hypothetical. 2026-07-29, run from the ask-221 worktree against PR #35: it
# returned three findings in linear-sync.py, a file PR #35's diff does not touch at
# all. The findings were real bugs in ask-221; the PROVENANCE was false. That is
# worse than a wrong verdict, because the record looks authoritative.
#
# TWO TIERS, because a flat equality check would be wrong twice over. The PR's head
# may legitimately be BEHIND local HEAD (a push landing after the `gh pr view`
# above), so equality would refuse healthy runs -- ancestry is the real question.
# And an UNKNOWN object is not evidence of a mismatch: a stale or partial clone
# cannot prove ancestry either way, and inventing a refusal there would wedge the
# loop on a fetch problem. Unknown warns; known-but-unrelated refuses.
#
# WHY THIS RESOLVES INSTEAD OF REFUSING (codex review round 1 of PR #34, major).
# The first cut of this guard compared $HEAD_SHA against $SKEL's HEAD and exited 1
# on a mismatch. That reads correctly and is still wrong, because $SKEL is derived
# from BASH_SOURCE -- the script's own location -- and the autonomous caller is
# `linear-worker.sh:1133`, which runs `bash $SCRIPT_DIR/pr-review-agent.sh` out of
# the MAIN checkout while the PR's commits live in a worktree it cut at
# $STATE_DIR/worktrees/<issue>. cwd is irrelevant; BASH_SOURCE wins. So the PR head
# is never an ancestor of main's HEAD, the guard refuses EVERY autonomous review,
# and the worker's call site swallows it as `|| say WARN ... (the PR stands,
# unreviewed)`. A guard whose success case is "the loop silently reviews nothing"
# is worse than the hole it closed.
#
# The question the scar actually asks is not "is SKEL right?" but "which tree on
# this machine holds the code this PR's diff describes?" Worktrees share one object
# database, so the answer is discoverable: ask each worktree. Refusal is kept for
# the case where NO tree holds the commit -- that is the sp-a72a9567 shape, and it
# still must never be reviewed.
# THE DEFAULT IS THE REPO UNDER REVIEW, NOT THE SCRIPT'S OWN (PR #265 major).
#
# This defaulted to $SKEL, the tree this script lives in. For an EXTERNAL target
# (--target / KIPI_TARGET_REPO) that is a different repository entirely, and the
# WARN-and-proceed branch below leaves the default in place -- so the reviewer
# read files out of the skeleton and stamped the verdict with another repo's PR
# sha. Findings about a repository nobody asked about, with provenance saying
# otherwise. When no target is given REVIEW_REPO already IS $SKEL, so this
# changes nothing for the common case and fixes the case that was wrong.
REVIEW_ROOT="$REVIEW_REPO"

# REVIEW IN A DEDICATED DETACHED WORKTREE, NEVER IN A CHECKOUT SOMEONE IS USING
# (sp-8f95bba0). The search below correctly finds A tree holding the PR head --
# but when the live checkout happens to sit at that sha, "a tree that holds it"
# IS the founder's working directory, and that is where the review ran. Both
# PR #47 rounds recorded `workdir: <the founder's live checkout>` with
# `sandbox: workspace-write`.
#
# Two failures at once, and the second is the worse one:
#   READ  -- an edit during a 7-13 minute review means the reviewer judged a tree
#            state that never existed as a commit, while the verdict is stamped on
#            a head_sha whose content it did not read. The provenance is false in
#            exactly the way the tree guard exists to prevent.
#   WRITE -- workspace-write lets the reviewer modify the founder's live checkout.
#
# The workaround was "everyone holds still for 13 minutes", which is not a control.
# A detached worktree pinned to the exact sha is: it cannot drift while the review
# runs, nobody else is editing it, and the tree/PR match becomes true by
# construction rather than by search.
#
# One tree per PR, reused across rounds by re-detaching rather than removing --
# removal is a destructive op on a path this script does not own, and re-checkout
# reaches the same state.
# EVERY bail out of review_worktree clears the ref, not just the last one.
#
# CODEX MAJOR ON PR #265, round 2 -- this change reviewing itself, twice. The
# first cut deleted the ref only on the update-ref failure at the bottom. The
# four EARLIER bails (mkdir, checkout, worktree add, sha mismatch) returned
# without touching it, so a round that failed to materialise its tree left
# whatever the PREVIOUS round wrote. assert_pr_ref_not_stale then found a ref
# pointing at an old sha and `exit 1`s -- with no self-heal, on every subsequent
# round, until a human runs update-ref -d by hand. A guard whose only recovery
# is a human is an outage with a good error message.
#
# CLEARS BOTH TREES, and that is not belt-and-braces. refs/remotes/* lives in the
# common ref store for a real `git worktree`, so one clear would be enough THERE
# -- but the review tree is not always that. The suite's fixture builds it as an
# independent checkout with its OWN ref store, and clearing only through
# $REVIEW_REPO left the stale ref exactly where it was. Two cases went red
# immediately. That is the whole reason to run the test instead of trusting the
# reasoning about how git stores refs.
#
# $wt may not exist yet on the earliest bail; `git -C` on a missing directory
# just fails, and the redirect absorbs it, so passing it unconditionally is safe.
#
# Clearing is the safe direction, for the reason the bottom of this function
# already records: absent fails CLOSED (`git show pr/<N>:<file>` errors, which is
# answerable), stale fails OPEN (the same command silently returns old content).
_wt_bail() {  # _wt_bail <worktree-path>
  local wt="${1:-}"
  [ -n "$wt" ] && git -C "$wt" update-ref -d "refs/remotes/pr/$PR" >/dev/null 2>&1
  # AND THROUGH $REVIEW_REPO (PR #265 codex major, round 2). The earliest bail
  # is mkdir, and when THAT fails there is no review tree to clear through, so
  # clearing only $wt left the previous round's ref exactly where it was and
  # assert_pr_ref_not_stale wedged every later unattended review. For a real
  # `git worktree` the two share one ref store and the second clear is a no-op;
  # where they do not, it is the only one that runs.
  git -C "$REVIEW_REPO" update-ref -d "refs/remotes/pr/$PR" >/dev/null 2>&1
  return 1
}

# ONE RUN PER REVIEW TREE (PR #265 major). review_worktree re-detaches a SHARED
# path (review-trees/<slug>__pr-<N>) rather than making a fresh one, so two
# concurrent reviews of the same repo and PR point at one mutable checkout: run A
# is reading files while run B re-checkouts it to a different sha. Neither run
# can tell, and both stamp their verdicts with the sha they THINK they read.
#
# Same primitive as mutation-sweep's sweep lock (ASK-1147) and for the same
# reason: O_CREAT|O_EXCL is atomic everywhere and needs no daemon. A stale lock
# whose holder is gone is reclaimed, because an operator who must clear locks by
# hand eventually clears one while a run is live.
_wt_lock_path=""
# Exit codes are THREE-VALUED on purpose (PR #265 major, round 2). The caller
# has to tell "nobody has a tree, so clear the stale ref" apart from "somebody
# else owns this tree RIGHT NOW", because the cleanup that is correct for the
# first is destructive for the second: the ref belongs to the live holder, and
# this run never wrote it.
#   0 = held by us   1 = could not lock (our problem)   2 = busy (their tree)
acquire_wt_lock() {  # acquire_wt_lock <worktree-path>
  local wt="$1" lock="$1.lock" holder
  mkdir -p "$(dirname "$wt")" 2>/dev/null || return 1
  if ( set -o noclobber; printf '%s' "$$" > "$lock" ) 2>/dev/null; then
    _wt_lock_path="$lock"; return 0
  fi
  holder="$(cat "$lock" 2>/dev/null || true)"
  # RE-ENTRANT for this run. review_worktree is called more than once per review,
  # and the lock exists to keep OTHER processes out, not this one. Without this
  # the second call in a single run refuses on a lock it placed itself -- caught
  # immediately by the existing suites, which went 5 and 2 red.
  if [ "$holder" = "$$" ]; then
    _wt_lock_path="$lock"; return 0
  fi
  if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
    return 2
  fi
  # Stale: reclaim once.
  command rm -f "$lock" 2>/dev/null || true
  if ( set -o noclobber; printf '%s' "$$" > "$lock" ) 2>/dev/null; then
    _wt_lock_path="$lock"; return 0
  fi
  return 1
}
release_wt_lock() {
  [ -n "$_wt_lock_path" ] || return 0
  if [ "$(cat "$_wt_lock_path" 2>/dev/null || true)" = "$$" ]; then
    command rm -f "$_wt_lock_path" 2>/dev/null || true
  fi
  _wt_lock_path=""
}
# REPLACES the pid-only trap armed above; bash keeps one EXIT trap, so this line
# has to clear BOTH or the pid file leaks from here on.
trap 'release_wt_lock; _review_pid_release' EXIT

review_worktree() {  # review_worktree <sha> -> prints path, or nothing
  # KEYED BY REPO AND PR (ASK-738). One shared review-trees/pr-<N> path meant
  # two repos' PR #42 shared a single detached worktree, re-checked out to
  # whichever repo asked last -- a review reading the wrong repository's files.
  local sha="$1" wt; wt="$(review_tree_path "$HOME/.config/kipi" "$REVIEW_SLUG" "$PR")"
  # Refuse rather than share. A second run returning empty here degrades to the
  # fallback search, which now demands a tree AT the sha and refuses if none --
  # so a concurrent review says so instead of silently reading a moving tree.
  # A failure to materialise clears the stale ref -- EXCEPT when the reason is
  # that another run owns the tree.
  #
  # The first cut cleared on every failure, and codex caught the consequence: a
  # concurrent reviewer that LOST the lock deleted refs/remotes/pr/<N> out from
  # under the reviewer that WON it, invalidating a live review's evidence. My own
  # two fixes colliding -- the ref cleanup is right when nobody has a tree and
  # destructive when somebody does.
  acquire_wt_lock "$wt"
  case "$?" in
    0) : ;;
    2) echo "  WARN: another review holds $wt; leaving its ref alone and falling back." >&2
       return 1 ;;
    *) echo "  WARN: could not lock $wt; not reusing a tree a live run can re-checkout under us." >&2
       _wt_bail "$wt"
       return 1 ;;
  esac
  mkdir -p "$(dirname "$wt")" 2>/dev/null || _wt_bail "$wt" || return 1
  if [ -d "$wt/.git" ] || [ -f "$wt/.git" ]; then
    git -C "$wt" checkout --detach --force "$sha" >/dev/null 2>&1 || _wt_bail "$wt" || return 1
  else
    git -C "$REVIEW_REPO" worktree add --detach "$wt" "$sha" >/dev/null 2>&1 || _wt_bail "$wt" || return 1
  fi
  # Prove it landed where we asked. A worktree silently sitting at the wrong sha
  # is the same false-provenance bug in a new costume.
  [ "$(git -C "$wt" rev-parse HEAD 2>/dev/null)" = "$sha" ] || _wt_bail "$wt" || return 1

  # REFRESH refs/remotes/pr/<N> TOO. Re-detaching moved HEAD but left this ref
  # wherever the FIRST round put it, and the reviewer's reproducers read the PR
  # through it (`git show pr/<N>:<file>`). So from round 2 onward the tree was
  # correct and the ref was stale, and the reviewer re-raised findings against
  # code the author had already fixed.
  #
  # Measured 2026-08-29: pr/253 sat at the pre-fix sha while the PR head had
  # moved, and that round's verdict was issued without the fix in view. On
  # ASK-353 it cost two whole rounds of re-raised findings before anyone looked
  # at the ref rather than at the code.
  #
  # This is a gate reading the wrong input, which is worse than a gate that
  # fails: it produces a confident verdict about a file that is not there.
  # Anchored here because this is the single place that pins tree-to-sha, so the
  # ref cannot drift from HEAD without this line drifting too.
  #
  # AND IF IT CANNOT BE MADE CORRECT, DELETE IT (Codex major on PR #265, which is
  # this change reviewing itself). The first cut just returned 1 here. But the
  # caller wraps this in `|| true` and degrades to reviewing the live tree, so a
  # swallowed failure left the tree re-detached, the ref stale, and the review
  # running anyway -- the exact state this function exists to prevent, reached
  # through its own error path.
  #
  # Deleting fails CLOSED: `git show pr/<N>:<file>` then errors on a missing ref,
  # which is answerable. Leaving it fails OPEN: the same command silently returns
  # round-1 content and the reviewer never knows it read the wrong file. No answer
  # beats a confident wrong one.
  if ! git -C "$wt" update-ref "refs/remotes/pr/$PR" "$sha" >/dev/null 2>&1 ||
     [ "$(git -C "$wt" rev-parse "refs/remotes/pr/$PR" 2>/dev/null)" != "$sha" ]; then
    git -C "$wt" update-ref -d "refs/remotes/pr/$PR" >/dev/null 2>&1 || true
    git -C "$REVIEW_REPO" update-ref -d "refs/remotes/pr/$PR" >/dev/null 2>&1 || true
    return 1
  fi
  printf '%s' "$wt"
}

# NO REVIEW MAY START WHILE A STALE pr/<N> REF EXISTS. Checked HERE, at the
# caller, because nothing review_worktree returns can enforce it: it is invoked
# inside `$( )`, so it runs in a SUBSHELL -- `return 1` is swallowed by the
# `|| true` below, and even `exit` would only leave the subshell. A guard whose
# every failure signal is discarded by its own call site is not a guard.
#
# So the invariant is asserted independently of the function's result: after the
# call, the ref is either absent or equal to the sha under review. Anything else
# and the reproducers would read another commit's files while reporting this sha
# (sp-690ba60b / ASK-1120), which is a confident wrong answer rather than a
# failure, so this refuses instead of degrading.
#
# Codex found this twice on PR #265, both times correctly. Round 1: returning 1
# left the ref stale because the caller degrades. Round 2: the cleanup's own
# `|| true` meant a failed DELETE was swallowed too. Both are the same shape --
# an error path that lands in the exact state the guard exists to prevent.
assert_pr_ref_not_stale() {  # assert_pr_ref_not_stale <dir> <sha>
  local dir="$1" sha="$2" now
  # --verify --quiet IS LOAD-BEARING. Bare `rev-parse <missing-ref>` prints the
  # REF NAME on stdout and exits non-zero, so `now` came back as the literal
  # string "refs/remotes/pr/<N>" -- non-empty, not equal to the sha, and the
  # assertion refused every FIRST-round review, where absent is the normal state.
  # Caught by the absent-ref case below, which is why that case exists.
  now="$(git -C "$dir" rev-parse --verify --quiet "refs/remotes/pr/$PR" 2>/dev/null || true)"
  [ -z "$now" ] && return 0          # absent is safe: a reproducer errors loudly
  [ "$now" = "$sha" ] && return 0
  echo "FATAL: refs/remotes/pr/$PR is stale (${now:0:8}, reviewing ${sha:0:8}) and could not be corrected or removed." >&2
  echo "       Refusing to review: the reproducers read the PR through that ref and would report on the wrong commit." >&2
  echo "       Clear it by hand:  git -C $dir update-ref -d refs/remotes/pr/$PR" >&2
  exit 1
}

if [ -n "$HEAD_SHA" ] && git -C "$REVIEW_REPO" cat-file -e "${HEAD_SHA}^{commit}" 2>/dev/null; then
  ISOLATED="$(review_worktree "$HEAD_SHA" || true)"
  assert_pr_ref_not_stale "${ISOLATED:-$REVIEW_REPO}" "$HEAD_SHA"
  if [ -n "$ISOLATED" ]; then
    REVIEW_ROOT="$ISOLATED"
    echo "  tree: $REVIEW_ROOT (detached at ${HEAD_SHA:0:8}; isolated from any checkout in use)"
    HEAD_SHA_ISOLATED=1
  else
    # Say it out loud rather than quietly reviewing the live tree. A degraded run
    # that nobody knows is degraded is how the original defect stayed invisible.
    echo "  WARN: could not materialise an isolated worktree at ${HEAD_SHA:0:8}; falling back to tree search. A concurrent edit during this review would corrupt its provenance (sp-8f95bba0)." >&2
    HEAD_SHA_ISOLATED=0
  fi
elif [ -n "$HEAD_SHA" ]; then
  # OBJECT ABSENT -> fall through to the ORIGINAL tier-1 path (warn, proceed).
  # I briefly made this refuse, on the reasoning that no tree can be built at a
  # missing object so the provenance must be false. The tree-guard suite refused
  # the change and was right: a stale or partial clone cannot prove ancestry
  # EITHER WAY, so refusing wedges the loop on a fetch problem, and every reviewer
  # case in test-severity-floor.sh reports a fabricated sha and takes exactly this
  # branch. Isolation raises the floor for the case that actually occurs (the
  # object is present); it does not get to redefine the case it cannot serve.
  HEAD_SHA_ISOLATED=0
else
  HEAD_SHA_ISOLATED=0
fi

if [ "$HEAD_SHA_ISOLATED" != "1" ] && [ -n "$HEAD_SHA" ]; then
  if ! git -C "$REVIEW_REPO" cat-file -e "${HEAD_SHA}^{commit}" 2>/dev/null; then
    echo "  WARN: $REVIEW_REPO does not have commit $HEAD_SHA, so the tree/PR match cannot be proven (stale or partial clone?). Proceeding; a review of the wrong tree would report findings absent from this diff." >&2
  elif [ "$(git -C "$REVIEW_REPO" rev-parse HEAD 2>/dev/null)" != "$HEAD_SHA" ]; then
    # THE TRIGGER HAD THE SAME BUG AS THE SELECTION, and my own reproducer for
    # the selection is what found it. This asked whether $REVIEW_REPO CONTAINS
    # the PR head, and short-circuited to reviewing $REVIEW_REPO when it did --
    # so a checkout ten commits past the PR was used directly, with no check at
    # all. Fixing only the loop below would have left the commoner path open.
    #
    # Now: $REVIEW_REPO qualifies only when it is checked out AT the sha.
    # Anything else falls into the search, which also demands exact equality and
    # refuses if nothing matches.
    #
    # Blast radius is small by construction: the PRIMARY path is an isolated
    # worktree materialised AT the sha, and this whole branch runs only when that
    # materialisation failed. Tightening a degraded path costs refusals that name
    # the commit; leaving it costs confident reviews of code the PR does not have.
    #
    # SKEL does not hold the PR at its head. Find a worktree that does.
    # `worktree list --porcelain` emits a `worktree <path>` line per tree, SKEL
    # included; testing SKEL again is harmless and keeps the loop free of a
    # special case.
    # EXACTLY AT THE SHA, not merely containing it (PR #265 codex major).
    #
    # This asked `--is-ancestor "$HEAD_SHA" HEAD`, which is true for every
    # DESCENDANT. A worktree ten commits past the PR head satisfied it, so the
    # reviewer read FILES from newer code and the verdict was stamped with the
    # captured older sha -- findings cited lines the PR does not contain, and the
    # provenance said otherwise. That is the same false-provenance defect the
    # isolated-worktree path above exists to prevent, reached through its
    # fallback.
    #
    # Tightening this means MORE refusals, and that is the correct direction: the
    # refusal below names the commit and how to get it, while a descendant tree
    # produces a confident review of the wrong code with nothing saying so. No
    # answer beats a wrong one, and this is the degraded path, not the normal one.
    FOUND_ROOT=""
    while IFS= read -r wt; do
      [ -n "$wt" ] || continue
      [ -d "$wt" ] || continue
      if [ "$(git -C "$wt" rev-parse HEAD 2>/dev/null)" = "$HEAD_SHA" ]; then
        FOUND_ROOT="$wt"; break
      fi
    done < <(git -C "$REVIEW_REPO" worktree list --porcelain 2>/dev/null | awk '/^worktree /{print substr($0,10)}')

    if [ -n "$FOUND_ROOT" ]; then
      REVIEW_ROOT="$FOUND_ROOT"
      echo "  tree: $REVIEW_ROOT (holds PR #$PR at ${HEAD_SHA:0:8}; the script itself lives in $SKEL, the code under review in $REVIEW_REPO)"
    else
      echo "REFUSING: PR #$PR is at $HEAD_SHA, and no worktree of $REVIEW_REPO (HEAD $(git -C "$REVIEW_REPO" rev-parse --short HEAD 2>/dev/null)) is checked out AT that commit. A tree that merely CONTAINS it holds newer files, which would be reviewed and then stamped with this sha." >&2
      echo "  The reviewer reads FILES from a tree and the DIFF from the PR. With no tree holding this commit, every finding would cite code that is not in this PR, stamped with this PR's sha." >&2
      echo "  Fetch the PR's head, or run it from a tree that has it. No review was dispatched and NO status was posted -- absent is not approved." >&2
      exit 1
    fi
  fi
fi

# $REVIEW is only a variable at this point -- the file is not created until the
# reviewer's stdout redirect at the bottom -- so review_round's "existing + 1" is
# exactly this run's round number. (Counting after the redirect would double it.)
ROUND="$(review_round "$ENGINE_DIR" "$PR")"
echo "  round: $ROUND (engine: $ENGINE)"

# A repeat review must not re-litigate. Fresh eyes on the CODE is the point;
# fresh eyes on the ARGUMENT is how a PR grinds forever (PR #11 reached round 4
# with findings still arriving). So from round 2 on, the reviewer is told the
# round and is required to re-prove any finding it wants to raise again.
ROUND_RULE=""
if [ "$ROUND" -gt 1 ]; then
  ROUND_RULE="

## THIS IS REVIEW ROUND $ROUND OF THIS PR

Earlier rounds are in the PR comments (\`gh ${GH_R_PROMPT}pr view $PR --comments\`). Read them
AFTER you have formed your own read of the code, never before -- your value is
that you did not inherit anyone's frame.

Then apply this rule, which is binding:

- A finding raised in an earlier round may be raised AGAIN only if your own
  reproducer shows it is STILL LIVE. Paste that repro. 'They did not fix it
  properly' without an executed repro is re-litigation, and it is dropped.
- A finding the author ANSWERED with a code citation is settled unless you can
  falsify the citation. Say which citation you falsified and how.
- Do not escalate severity across rounds on the same underlying issue. If it was
  a minor in round $((ROUND-1)), it is a minor now, unless new evidence shows a
  consequence nobody had seen. Name that new consequence explicitly.
- By round 3+, a PR that keeps producing NEW blockers on UNCHANGED code means the
  earlier rounds were miscalibrated. Say so in your review if you see it. That is
  a finding about the review process, and it is worth more than another nit."
fi

PROMPT="You are a SENIOR STAFF ENGINEER at Meta. You have NEVER seen this codebase before.
You were asked to review pull request #$PR in $REVIEW_ROOT, and you are ADVERSARIAL by default:
your job is to find what is wrong, not to be agreeable.$ROUND_RULE

## YOU ARE ALONE. THERE IS NOBODY TO ASK.

This run is HEADLESS: no human is reading your output while it happens, and
nothing you write can be answered. Do not state a plan and wait for approval,
do not ask to begin, do not ask which files to look at. Begin immediately and
finish in one pass, ending with the verdict and the machine-readable findings
block.

This is not a style preference. Measured 2026-08-04 on PR #97 round 4: this
reviewer replied \"Ready for your OK to begin the read-only review\", spent 15k
tokens, produced no findings block, and the run scored the PR unstated. The
repo-wide skills you inherit (founder-voice, AUDHD executive-function) carry an
INTERACTIVE rule -- state your approach and wait for OK before multi-file work
-- which is correct when a founder is present and wrong here. In this run that
rule does not apply: you have no interlocutor, so waiting is the same as
producing nothing.

An empty or truncated review never derives APPROVE, so stopping to ask does not
fail safe for the author -- it just burns a round.

## Read the change

  gh ${GH_R_PROMPT}pr view $PR
  gh ${GH_R_PROMPT}pr diff $PR

## What your fresh eyes are FOR

You have no memory of why anything here is the way it is. That is the point. Do NOT
accept a comment, a commit message, or a doc as evidence — those are the author's
claims about the code, written by the same mind that wrote the bug. Read what the
code DOES. Where a comment and the code disagree, the code is the truth and the
comment is a finding.

Be specifically suspicious of:
- **Test fixtures the author invented.** A fixture built from the same mental model
  as the code tests nothing. Check that every fixture's SHAPE matches what the real
  producer actually emits. This fleet has already shipped a mutex whose remote half
  never fired because its fixture used a key no producer emits, while the suite was green.
- **Tests that could not fail.** For each new test ask: what would break to make this
  red? If nothing plausible would, it is decoration.
- **Claims of enforcement.** 'This ensures X' in a comment is not enforcement. Find
  the code path that refuses, or call it a finding.
- **Error paths, retries, partial failure.** What is left behind when this dies
  halfway? What does the operator see?

## The operational bar (this is the Meta staff part)

This fleet runs UNATTENDED agents on a schedule, against Linear objects that CANNOT
BE DELETED, in a PUBLIC repo. So judge it that way:
- What happens at 3am when this fires and nobody is watching?
- What is the blast radius of it being wrong? What is permanent and unrecoverable?
- What pages a human, and is that signal or noise? A checker that cries wolf trains
  the operator to ignore it, which costs the real alert later.
- Can this be rolled back? If not, say so loudly.
- Concurrency: two of these running at once. What breaks?

## WHAT EACH SEVERITY MEANS — use these anchors, not your feel for it

Severity is BLAST RADIUS and RECOVERABILITY. It is not how clever the finding is,
how long it took you to find, or how much the code annoyed you. Every one of these
anchors is a real event on this fleet, so calibrate against them directly:

- **blocker** — permanent or unrecoverable if it merges. Publishes a credential to
  a Linear object that cannot be deleted. Destroys or overwrites founder work.
  Silently disables the very detector the change adds, forever. If the honest
  answer to 'can we undo this after it fires?' is no, it is a blocker.
- **major** — wrong behavior unattended that a human must clean up, but CAN clean
  up. Files duplicate permanent issues. Cries wolf on every run (a checker the
  operator learns to ignore costs the real alert later, which is why false alarms
  rank here and not below). Reports success for work that did not happen.
- **minor** — real, reproducible, and bounded. Log or help text that misstates
  what the code does. A narrow false negative on an input shape nobody hits yet.
  A docstring that contradicts the code. It should be fixed; it does not gate.
- **nit** — style, naming, formatting, preference. Never gates anything.

Two calibration checks before you assign a severity:
1. If you cannot name what a human has to DO about it at 3am, it is not a blocker
   or a major.
2. If your reproducer only fails under inputs you had to construct and no producer
   in this repo emits, drop the severity a level and say so.

Inflating a minor to a major to make a review feel substantial is itself a defect:
it wedges a PR that should have shipped, and it burns the author's next round on
work that did not need doing.

## THE STANDING RULE — non-negotiable

EVERY finding MUST ship a RUNNABLE REPRODUCER that you ACTUALLY RAN, with its real
output pasted. A finding with no executed repro is an opinion and will be rejected.
Write repros to \$TMPDIR and run them. If you cannot make it fail, DROP the finding
and say you tried. Dropping a finding you could not reproduce is a SUCCESS of this
process, not a failure of it.

Never modify the repo. Read-only review. Do not commit, do not push.

## Output

For each finding: SEVERITY (blocker|major|minor|nit), a one-sentence claim, the exact
file:line, the reproducer command, and its REAL output.

Then:
- **What is sound** — attacks you tried that the code survived. Name them. A review
  that only lists faults is not calibrated and cannot be trusted on the faults.
- **VERDICT:** decided by THIS RULE, not by feel:
    - any blocker or major finding      => REQUEST CHANGES (BLOCK only if merging
      as-is would cause permanent or unrecoverable damage)
    - only minor/nit findings           => APPROVE WITH NITS
    - no finding survived reproduction  => APPROVE
  A bar this high ALWAYS finds something; that is what APPROVE WITH NITS is for.
  On APPROVE WITH NITS the pipeline captures every minor as a tracked follow-up,
  so approving with nits does NOT lose them. Using REQUEST CHANGES to log minors
  wedges the PR forever and is itself a review defect.
  State the verdict and the single most important thing to fix first.
- **Last, a machine-readable findings block**, EXACTLY this shape, one line per
  finding, empty block if none. The pipeline parses it; keep prose out of it:

FINDINGS:
severity|one-sentence claim|file:line
END FINDINGS"

# ONE ATTEMPT PER ENGINE, and the fallback is one more. Codex costs real tokens
# per PR (~26k on a trivial prompt, far more on a real diff), so a retry loop
# here is a runaway bill on every scheduled run against every open PR. Bounded
# exactly as the existing reviewer already is: the same wall clock, no retries.
#
# `codex exec` READS STDIN and hangs without a redirect (observed: "Reading
# additional input from stdin..."), and outside a trusted directory it refuses
# with "Not inside a trusted directory". Both are load-bearing, not decoration.
run_engine() {   # run_engine <claude|codex> <destination-file>
  case "$1" in
    claude) run_bounded "$TIMEOUT_SECONDS" bash -c \
              "cd '$REVIEW_ROOT' && claude -p --model '$CLAUDE_MODEL' \"\$1\" </dev/null > '$2' 2>&1" _ "$PROMPT" ;;
    codex)  run_bounded "$TIMEOUT_SECONDS" bash -c \
              "codex exec --ignore-user-config --skip-git-repo-check --model '$CODEX_MODEL' -C '$REVIEW_ROOT' \"\$1\" </dev/null > '$2' 2>&1" _ "$PROMPT" ;;
  esac
}

# --ignore-user-config KEEPS OUR OWN AGENT CONFIG OUT OF THE REVIEWER (sp-cc9955db).
# Without it, `codex exec` loads THIS FLEET'S config into the reviewer's session.
# The 2026-08-03 artifact shows it announcing "I'm using the assaf-voice,
# audhd-executive-function, and fable-discipline skills", firing SessionStart and
# UserPromptSubmit hooks, and then applying the founder's own "state your planned
# approach and wait for OK before executing" rule TO ITS OWN REVIEW. It answered
# with a plan in 12 seconds and reviewed nothing. sp-df1a458f is what that did to
# the gate downstream: the echoed prompt template became the findings block.
#
# THE REVIEWER'S WHOLE VALUE IS THAT IT IS NOT US. A reviewer wearing the author's
# skills, voice rules and hooks is not the independent second opinion this engine
# exists to buy -- it is the same mental model with a different model id, which is
# the correlated-blind-spot problem the codex engine was chosen to escape.
#
# THE CWD ISOLATION DOES NOT COVER IT. `-C $REVIEW_ROOT` already runs the review in
# a detached worktree and the round-1 artifact shows the same config loading anyway:
# it resolves from the USER HOME, not from the project directory, so no amount of
# cwd isolation reaches it.
#
# WHAT THIS FLAG ACTUALLY BUYS, MEASURED, NOT ASSUMED (2026-08-03, same prompt run
# twice against codex v0.146.0 from a neutral cwd):
#     without the flag:  12 `hook: ` lines   -- SessionStart/UserPromptSubmit/Stop
#     with the flag:      0 `hook: ` lines
# The hooks are the layer that injected the plan-and-await instruction, and they
# are gone. It is NOT total isolation: the "Skill descriptions were shortened to
# fit the 2% skills context budget" warning appears in BOTH runs, so codex can
# still SEE the skill catalogue with the flag set. Claiming this severs skills
# would be an overclaim; captured separately rather than asserted here.
#
# NOT `--disable skills`: that flag does not exist on this codex build and errors
# with "Unknown feature flag: skills", which would send every review down the Opus
# fallback and mark the gate DEGRADED fleet-wide.
#
# sp-df1a458f's guard is the backstop either way: if a future codex build finds a
# new road to the same behaviour, review_is_usable refuses the stream instead of
# letting it fill a required check.


# A codex answer is usable only if it carries a COMPLETE machine-readable block
# AND is actually a review. A truncated -- or unstarted -- stream that green-lights
# a PR nobody read is the worst outcome available in this script.
#
# THE PREDICATE LIVES IN THE LIB, next to the reader that defines it
# (sp-c0a9dac3). Its own two-marker grep here was a SECOND definition of
# "complete": both markers, anywhere, in any order. That passes a review whose
# only complete block is a quoted prior round while the real trailing block is
# truncated -- unusable stays off, the gate goes green, and the verdict comes from
# findings the review itself withdrew. One definition, one reader.
#
# IT NOW ASKS review_is_usable, WHICH IS A WIDER QUESTION (sp-df1a458f). Block
# completeness alone said YES to a stream where the model answered "Reply `OK`
# and I'll execute exactly that plan" and the only complete block was the
# PROMPT'S OWN echoed template. Both dispatch sites below call this, and the
# second one -- the Opus fallback -- is where this exact class hid last time.
# No local wrapper: both sites call review_is_usable directly. The wrapper existed
# only to forward to the lib, and a forwarder is one more place the two dispatch
# paths can be made to disagree about the same file.

# PAGE ON THE TRANSITION ONLY. A ping every run while codex stays down is the
# cry-wolf failure: it trains the operator to skim, which costs the real alert
# later. Both edges earn their one line -- going degraded means the two statuses
# stopped being independent, and an operator who never hears the recovery cannot
# tell a live second opinion from an Opus stand-in wearing its context.
note_degraded_transition() {   # note_degraded_transition <0|1> [reason]
  local now="$1" reason="${2:-}" prev="" msg
  [ -f "$DEGRADED_STATE" ] && prev="$(tr -dc '01' < "$DEGRADED_STATE" 2>/dev/null | head -c1)"
  [ -n "$prev" ] || prev=0
  mkdir -p "$(dirname "$DEGRADED_STATE")"
  printf '%s\n' "$now" > "$DEGRADED_STATE"
  [ "$now" = "$prev" ] && return 0
  if [ "$now" = "1" ]; then
    msg="reviewer: codex is not producing an independent review (PR #$PR): $reason. $STATUS_CONTEXT stops being a second lab's opinion until codex is back."
  else
    msg="reviewer: codex is BACK (PR #$PR) -- $STATUS_CONTEXT is an independent second opinion again."
  fi
  bash "$NOTIFY" "$msg" 2>/dev/null || true
}

echo "$(TS) running the $ENGINE reviewer (bounded at ${TIMEOUT_SECONDS}s)..."
if [ "$ENGINE" != "codex" ]; then
  if run_engine claude "$REVIEW"; then
    # THE CLAUDE PATH GETS THE SAME PARSEABILITY BAR AS THE OTHER TWO, and this
    # line is the whole reason it is here (review of PR #319). Until the
    # 2026-09-06 flip this branch was ADVISORY ONLY, so an unread review landed
    # on kipi/claude-approved and gated nothing; the bar lived on the codex path
    # and, after codex found the same hole in it on 2026-07-29, on the Opus
    # fallback. The flip moved the REQUIRED kipi/reviewer-approved onto the one
    # path in this script that never asked the question.
    #
    # REPRODUCED, not reasoned about, before this line existed: the suite's own
    # CODEX_TRUNCATED fixture (harness noise, prose "VERDICT: APPROVE", a
    # FINDINGS: block that is never closed, exit 0) posted
    #   state=success -f context=kipi/reviewer-approved -f description=APPROVE
    # on the default path, while the verdict record it wrote beside it said
    # "usable": false. The identical stream through the codex path correctly
    # posted state=failure. Nothing paged. An unclosed FINDINGS block parses as
    # an EMPTY findings list and an empty list derives APPROVE, so exiting 0 is
    # not evidence the reviewer said anything -- and a green required gate over
    # a review nobody read is the worst outcome available in this script.
    if review_is_usable "$REVIEW"; then
      echo "$(TS) review written: $REVIEW"
    else
      REVIEW_UNUSABLE=1
      echo "$(TS) the $ENGINE reviewer answered with no complete FINDINGS block (empty or truncated); verdict stays UNSTATED. Output kept at: $REVIEW" >&2
    fi
  else
    rc=$?
    echo "$(TS) reviewer failed or timed out (rc=$rc). Partial output: $REVIEW" >&2
    exit "$rc"
  fi
elif run_engine codex "$REVIEW"; then
  if review_is_usable "$REVIEW"; then
    note_degraded_transition 0
    echo "$(TS) review written: $REVIEW"
  else
    # Codex ANSWERED and said nothing parseable. Deliberately NOT the fallback
    # path: an outage leaves no review to trust, but this is an attempted review
    # whose CONTENT cannot be trusted, and filling the slot with an Opus approval
    # over it would invent a verdict for a review that said nothing. It falls
    # through UNSTATED, and unstated posts state=failure a few lines below.
    REVIEW_UNUSABLE=1
    note_degraded_transition 1 \
      "it answered with no complete FINDINGS block (empty or truncated), so the status is UNSTATED rather than a fabricated APPROVE"
    echo "$(TS) codex answered with no complete FINDINGS block (empty or truncated); verdict stays UNSTATED. Output kept at: $REVIEW" >&2
  fi
else
  # Codex is DOWN. If nothing filled $STATUS_CONTEXT and it were a required
  # check, every PR in the repo would wedge forever -- so the Opus reviewer fills
  # the slot, and the status says DEGRADED out loud. A SILENT fallback is the
  # real hazard: both statuses would come from one model family and nobody would
  # know the independence this engine exists to buy had been lost.
  rc=$?
  DEGRADED=1
  mv -f "$REVIEW" "$REVIEW.codex-failed" 2>/dev/null || true
  echo "$(TS) codex failed or timed out (rc=$rc); running the Opus fallback so $STATUS_CONTEXT does not wedge. Partial codex output: $REVIEW.codex-failed" >&2
  note_degraded_transition 1 \
    "it exited $rc, so the Opus fallback filled the slot and the status is marked DEGRADED"
  if run_engine claude "$REVIEW"; then
    # THE FALLBACK GETS THE SAME PARSEABILITY BAR AS CODEX. Exiting 0 is not
    # evidence it said anything: a truncated stream leaves an unclosed FINDINGS
    # block, which derives APPROVE and would post state=success on the REQUIRED
    # context. Filling the gate with an unread approval is worse than leaving it
    # unstated, because unstated holds the PR and green releases it.
    if review_is_usable "$REVIEW"; then
      echo "$(TS) DEGRADED review written by the Opus fallback: $REVIEW"
    else
      REVIEW_UNUSABLE=1
      echo "$(TS) the Opus fallback answered with no complete FINDINGS block (empty or truncated); verdict stays UNSTATED. Output kept at: $REVIEW" >&2
    fi
  else
    rc=$?
    echo "$(TS) the Opus fallback ALSO failed (rc=$rc). No status is posted at all; absent is not approved." >&2
    exit "$rc"
  fi
fi

# The verdict is COMPUTED from the labelled severities when the reviewer emitted
# a findings block, and only read from prose when it did not. The prompt's
# grading rule is guidance; this is the enforcement. Both are recorded so a
# reviewer that grades against its own labels stays visible instead of silently
# setting the gate.
STATED_VERDICT="$(extract_verdict "$REVIEW")"
DERIVED_VERDICT="$(verdict_from_findings "$REVIEW")"
if [ "$REVIEW_UNUSABLE" = "1" ]; then
  # UNUSABLE WINS OVER THE DERIVATION, and this ordering is the whole fix. An
  # unclosed `FINDINGS:` block parses as an EMPTY findings list, and an empty
  # list derives APPROVE -- so a stream that died one line into the block would
  # otherwise green-light the PR, with the truncated prose "VERDICT: APPROVE"
  # above it agreeing. There is also no prose fallback on this slot: codex stdout
  # carries harness noise (`hook: Stop`, `tokens used`, a repeated final line)
  # that a whole-file token grep reads an APPROVE out of. Unstated posts
  # state=failure, which is the safe direction -- absent evidence is not consent.
  VERDICT=""
  echo "  NOTE: no complete FINDINGS block from codex; verdict UNSTATED. An empty or truncated review never derives APPROVE."
elif [ -n "$DERIVED_VERDICT" ]; then
  # A DISAGREEMENT MAY NEVER RESOLVE TOWARD APPROVAL (ASK-312). This used to read
  # VERDICT="$DERIVED_VERDICT" unconditionally, printing a NOTE and proceeding --
  # which twice turned a reviewer's own "REQUEST CHANGES" into APPROVE and posted
  # kipi/reviewer-approved=success on a PR nobody had read. resolve_verdict takes
  # the harsher of the two, so the severity floor still overrides a reviewer that
  # logged a blocker and then said APPROVE, while silence can no longer overrule a
  # reviewer that said stop.
  VERDICT="$(resolve_verdict "$STATED_VERDICT" "$DERIVED_VERDICT")"
  if [ "$STATED_VERDICT" != "$DERIVED_VERDICT" ]; then
    echo "  NOTE: reviewer stated '${STATED_VERDICT:-none}' but its own findings imply '$DERIVED_VERDICT'; taking the harsher: '$VERDICT'"
  fi
else
  VERDICT="$STATED_VERDICT"
  echo "  NOTE: no FINDINGS block; verdict read from prose (weaker)"
fi
echo "  verdict: ${VERDICT:-unstated}$DRY_NOTE"

# TWO CONSECUTIVE REQUEST CHANGES ROUNDS THAT SHARE A FILE MEAN THE FIX SHAPE IS
# WRONG (sp-46726f79).
#
# THE SCAR, measured: rounds 1, 2 and 3 of PR #314 each named ANOTHER unwaited
# index write. Three patches, one class, and nothing in the tooling said so -- the
# round cap came from the founder at 01:09Z. The same shape burned seven rounds on
# 2026-09-03. A reviewer that can see it and does not say it is the cheapest
# possible miss, because it already holds both rounds' findings.
#
# WHAT IT COMPARES AND WHY THAT SOURCE. The `.verdict.json` record is ONE file per
# PR, overwritten every round, so it cannot answer a question about two rounds.
# The per-round history that does exist is this engine's own review artifacts,
# `$ENGINE_DIR/<artifact_key>-<stamp>.md`, which is what review_round already
# counts. Sorted by name is sorted by time: the stamp is %Y%m%d-%H%M%S.
#
# THROUGH THE ONE READER. Both findings blocks come from `findings_block`
# (sp-c0a9dac3), never a fresh sed range here -- a second extractor is how the
# comment, the gate and this check end up disagreeing about what a review said.
#
# ADVISORY, NEVER A BLOCK. It exits 4 AFTER the post completes, so a queue script
# can stop while the human-readable verdict still reaches the PR. Blocking the
# post would trade a wrong-shape warning for a lost review, which is the trade
# this whole file exists to refuse.
#
# HONEST BOUNDARY: it matches on the file path a finding cites, so two genuinely
# different defects in one long file read as the same class, and one defect that
# moved to a different file reads as two classes. It is a prompt to think, not a
# proof, which is why it advises and does not gate.
STRUCTURAL_LINE=""
FINAL_EXIT=0

# _finding_files <review-file> -> the deduped, sorted file paths its findings cite.
# Rows are `severity|claim|file:line`; the line number is dropped because a fix
# that moves a defect down three lines is the same defect.
#
# `cut`, NOT awk, and that is not a style preference (CI red, 2026-09-07). The
# first cut read the third field as awk's `$3`, and validate-separation's
# propagation-leak classifier reads `$` followed by a digit as a CURRENCY token:
# the line landed in test-propagation-leak-baseline.py as a new `pricing` fact
# the committed baseline did not account for, and turned `validate` red on a
# change that has nothing to do with pricing. A shell field split says the same
# thing with no character the fleet's own detectors read as money.
#
# THE `grep -E` IS LOAD-BEARING, and the disjoint-files control is what caught it.
# `cut -d'|' -f3` returns the WHOLE LINE when the line has no delimiter, and
# findings_block's output carries the `FINDINGS:` / `END FINDINGS` markers. So the
# first cut compared those two marker strings as if they were file paths, found
# them in both rounds, and printed STRUCTURAL on two rounds that shared nothing.
# awk's `NF>=3` had been doing this filtering implicitly; moving off awk moved the
# guard too. Two pipes required first, then the third field means something.
_finding_files() {
  findings_block "${1:-}" \
    | grep -E '^[^|]*\|[^|]*\|' \
    | cut -d'|' -f3 \
    | sed -e 's/:[0-9-]*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e '/^$/d' \
    | sort -u
}

case "$VERDICT" in
  "REQUEST CHANGES"|"BLOCK")
    PREV_REVIEW=""; PREV_ROUND=0; CUR_ROUND=0; _sr_n=0
    while IFS= read -r _sr_f; do
      [ -n "$_sr_f" ] || continue
      _sr_n=$(( _sr_n + 1 ))
      if [ "$_sr_f" = "$REVIEW" ]; then CUR_ROUND="$_sr_n"; continue; fi
      _sr_v="$(resolve_verdict "$(extract_verdict "$_sr_f")" "$(verdict_from_findings "$_sr_f")")"
      case "$_sr_v" in
        "REQUEST CHANGES"|"BLOCK") PREV_REVIEW="$_sr_f"; PREV_ROUND="$_sr_n" ;;
      esac
    done <<EOF
$(ls -1 "$ENGINE_DIR/$(artifact_key "$REVIEW_SLUG" "$PR")-"*.md 2>/dev/null | sort)
EOF
    if [ -n "$PREV_REVIEW" ]; then
      _sr_prev="$(mktemp "${TMPDIR:-/tmp}/pr-review-prev.XXXXXX" 2>/dev/null)" || _sr_prev=""
      _sr_cur="$(mktemp "${TMPDIR:-/tmp}/pr-review-cur.XXXXXX" 2>/dev/null)" || _sr_cur=""
      if [ -n "$_sr_prev" ] && [ -n "$_sr_cur" ]; then
        _finding_files "$PREV_REVIEW" > "$_sr_prev"
        _finding_files "$REVIEW"      > "$_sr_cur"
        # `comm -12` needs both sides sorted, which _finding_files guarantees.
        _sr_shared="$(comm -12 "$_sr_prev" "$_sr_cur" 2>/dev/null | tr '\n' ' ' | sed 's/ *$//')"
        command rm -f "$_sr_prev" "$_sr_cur" 2>/dev/null || true
        if [ -n "$_sr_shared" ]; then
          STRUCTURAL_LINE="STRUCTURAL: round $CUR_ROUND and round $PREV_ROUND both request changes in the same file(s): $_sr_shared. Two rounds naming one file is a wrong fix SHAPE, not two bugs. Sweep the whole class in one pass or park the PR; a third patch on the same file is the loop this warning exists to stop (sp-46726f79)."
          FINAL_EXIT=4
          echo "  $STRUCTURAL_LINE"
        fi
      else
        echo "  WARN: could not create temp files for the structural comparison; skipping it. Two rounds on one file will not be flagged on this run." >&2
      fi
    fi
    ;;
esac

# Single writer for verdict state. The worker's rework gate reads THIS record,
# never the review prose. Keyed by PR number, latest round wins; history stays
# in the timestamped .md files.
#
# head_sha is the commit this review actually examined, captured before the
# reviewer ran (ASK-216). Without it the record binds an approval to a PR
# NUMBER, and the worker reuses one PR across rounds, so any later push inherits
# the approval. The key is ALWAYS written -- empty when `gh` could not answer --
# because rework_gate reads empty as "unknown, fall back and say so", and a
# key that sometimes vanishes is a shape the reader would have to guess at.
#
# The record lands in $VERDICT_DIR, NOT next to the review. Those are the same
# directory only for a non-primary engine; for the gating engine the reviews live
# in $OUT_DIR/codex (its own round counter) while the record must land in $OUT_DIR
# where converge.sh and linear-worker.sh actually read it.
# DID A REVIEW ACTUALLY HAPPEN, PERSISTED (sp-2a832233, ASK-352). The record used
# to store only a PATH to the review, and the review files rotate, so every
# consumer downstream had to re-derive usability from a file it does not own --
# or, in practice, guess from the verdict.
#
# THE VERDICT DOES NOT ANSWER IT. Measured across all 79 records on 2026-08-03:
# 13 were unusable and they carry the whole range of verdicts. `APPROVE` on 11 of
# them (all merged); `REQUEST CHANGES` on #80 and #83; empty on #89. The
# REQUEST CHANGES pair is the expensive one: the reviewer's `stated` verdict was
# read out of the PROMPT'S OWN echoed grading rule, so a record that says an
# objection was raised is indistinguishable from one where nobody read the code.
# Both post `state: failure`, and a selector that sees only `failure` sends a
# never-reviewed PR to REWORK with no findings to work from.
#
# ASKED HERE, NOT REUSED FROM $REVIEW_UNUSABLE. All three dispatch paths now set
# that flag (the `ENGINE != codex` path joined them in the review of PR #319; it
# previously never evaluated usability at all, which is what let a truncated
# claude stream green the required gate once claude became primary). It is still
# asked again here rather than reused, because $REVIEW_UNUSABLE is the flag the
# VERDICT was computed from and this key is a claim about the FILE -- deriving one
# from the other would make the record unable to disagree with the gate, and that
# disagreement is exactly the signal this key exists to preserve.
#
# RECORD-ONLY, DELIBERATELY. This changes no gate. $VERDICT is computed above and
# is not touched here, so no PR's outcome moves on this commit; the consumer that
# acts on the key is the selector (review-redrive.py), which is a separate change
# with its own cap. Widening a gate as a side effect of adding a field is how a
# fleet-wide refusal ships unannounced.
if review_is_usable "$REVIEW"; then REVIEW_USABLE=1; else REVIEW_USABLE=0; fi

# WHICH MODEL ACTUALLY WROTE THIS REVIEW (sp-8379cd52). `engine` is the FLAG the
# run was invoked with, not the author. On the DEGRADED path codex never answered
# and Opus wrote the review, yet the record still said `"engine": "codex"` -- so
# the human-facing surfaces told the truth (the status description and the Linear
# comment both say DEGRADED out loud) while the MACHINE-READABLE record that
# converge.sh:36 and linear-worker.sh:76 gate on claimed a second lab reviewed
# code that second lab never saw. Measured 2026-08-02 on PR #66 and #67 during a
# codex out-of-credits outage: both records read `engine: codex`, both reviews
# were Opus. That is the sp-a72a9567 false-provenance shape aimed at the gating
# reader instead of the human one, which is the worse direction.
#
# DERIVED, NEVER BRANCHED. This reads existing state and adds nothing to the
# control flow above -- deliberately. The fallback trigger is the one path in this
# script where a wrong edit posts an unearned green, so the provenance fix is not
# allowed to touch it. $DEGRADED is set at exactly one place (the outage branch),
# so deriving from it cannot disagree with what actually ran.
REVIEWED_BY="$CODEX_MODEL"
[ "$ENGINE" = "claude" ] && REVIEWED_BY="$CLAUDE_MODEL"
[ "$DEGRADED" = "1" ] && REVIEWED_BY="$CLAUDE_MODEL"
# `set -e` IS OFF IN THIS SCRIPT (line 64 is `set -uo pipefail`) and these two
# lines depend on that. Under `set -e` a false `[ ... ] && assign` is an AND-list
# whose final status is 1, which exits the shell -- so turning on -e here would
# abort every healthy codex review right before its record is written. If -e is
# ever added, these become if/fi first.
#
# IT SITS BELOW review_is_usable ON PURPOSE. test-review-degraded-provenance.sh
# extracts this block by awk range, anchored `^REVIEWED_BY="\$CODEX_MODEL"$` ..
# `^PY$`, and executes it in a bare subshell to drive the SHIPPED writer instead
# of a copy. Moving this above the `if review_is_usable` line pulls that function
# call into the extracted range, where it is undefined -- the writer would die,
# no record would be written, and the suite would report a break in the test
# rather than the defect. Keep the derivation adjacent to the python3 call.

# The record path comes from the ONE resolver (repo-slug-lib.sh), passed in as
# argv 16 rather than rebuilt in python -- a second place that knows the naming
# rule is a second writer, which is the defect class this repo keeps finding.
python3 - "$PR" "$ISSUE" "$VERDICT" "$REVIEW" "$(TS)" "$STATED_VERDICT" "$DERIVED_VERDICT" "$ROUND" "$HEAD_SHA" "$VERDICT_DIR" "$ENGINE" "$INVOKER" "$REVIEW_USABLE" "$REVIEWED_BY" "$DEGRADED" "$(verdict_record_write_path "$VERDICT_DIR" "$REVIEW_SLUG" "$PR")" <<'PY'
import json, sys
(pr, issue, verdict, review, ts, stated, derived, rnd, head_sha, verdict_dir,
 engine, invoker, usable, reviewed_by, degraded) = sys.argv[1:16]
out = sys.argv[16]
json.dump({"pr": int(pr), "issue": issue, "verdict": verdict,
           "stated": stated, "derived": derived,
           "source": "findings" if derived else "prose",
           "engine": engine,
           # reviewed_by is the model that produced the prose; engine is the flag
           # the run was asked for. On the fallback those disagree, and that
           # disagreement IS the record of the outage.
           "reviewed_by": reviewed_by,
           "degraded": degraded == "1",
           "invoker": invoker,
           # A real boolean, not "1"/"0". A JSON string "0" is TRUTHY in every
           # consumer language here, so a truthiness read of the wrong shape
           # would call every phantom review usable -- the exact inversion this
           # key exists to prevent.
           "usable": usable == "1",
           "round": int(rnd), "review": review, "head_sha": head_sha,
           "ts": ts}, open(out, "w"), indent=2)
PY

# Severity floor, capture half: APPROVE WITH NITS is a TERMINAL state -- the
# loop stops reworking -- so each minor must land in the spillover ledger or it
# evaporates (no-orphan-findings.md). On REQUEST CHANGES the minors ride along
# in the review, which is the spec for the next rework pass; capturing them
# there too would double-file them.
if [ "$VERDICT" = "APPROVE WITH NITS" ] && [ -n "$ISSUE" ]; then
  CAPTURED=0
  MINOR_COUNT=0
  while IFS='|' read -r _sev claim loc; do
    [ -n "$claim" ] || continue
    MINOR_COUNT=$((MINOR_COUNT+1))
    python3 "$SKEL/plugins/prd-os/scripts/prd_runner.py" spillover add \
      --source "$ISSUE" --desc "PR #$PR ${MINOR_TAG}review minor: $claim ($loc)" >/dev/null 2>&1 \
      && CAPTURED=$((CAPTURED+1))
  done <<EOF
$(extract_minor_findings "$REVIEW")
EOF
  echo "  minors captured as spillover: $CAPTURED of $MINOR_COUNT"
fi

# The verdict as a COMMIT STATUS on the sha the reviewer read (ASK-217).
#
# WHY THIS EXISTS: the verdict record above is a LOCAL file. GitHub cannot see
# it, so no platform mechanism can gate on it, so every approved PR ends its
# life waiting on a human. Every prior-art integrator (merge queue, Bors,
# Mergify, Kodiak) has one shape: every precondition is a required status check
# and the platform does the merging. pr-receipt-gate.py is already a CI step;
# this was the one piece still stuck on disk.
#
# WHY A STATUS AND NOT A PR REVIEW: a commit status needs no second identity. A
# PR *review* would deadlock -- this agent runs as the account that authors
# these PRs, and GitHub forbids self-approval. Proven live on PR #23, 2026-07-27.
#
# ABSENT IS NOT APPROVED, and that is the point. A reviewer that fails or times
# out exits well above this, before the verdict is even computed, so no status is
# posted at all. Once this context becomes a REQUIRED check, "absent" is what
# holds the PR -- the safe direction. Nothing on an error path here invents one.
post_reviewer_status() {
  local sha="$1" verdict="$2" target="$3"
  # The context is the ENGINE's slot: kipi/reviewer-approved for claude,
  # kipi/codex-approved for the independent second opinion. Two contexts, one
  # writer each, so a gate can require either or both without either engine
  # being able to answer for the other.
  local context="$STATUS_CONTEXT" state="failure" desc
  # ONE reader of the verdict. $VERDICT is the derived-over-stated value already
  # written to the record; re-grepping the review prose here would be a second
  # reader with its own semantics, which is the defect class this repo keeps
  # finding. Anything that is not an approval -- including an unstated verdict --
  # is a failure, so an unparseable review cannot pass a gate by accident.
  case "$verdict" in
    "APPROVE"|"APPROVE WITH NITS") state="success" ;;
  esac
  desc="${verdict:-unstated: no verdict parsed from the review}"
  # SAY IT IN THE SLOT ITSELF. The page fires once on the transition and is gone;
  # the status description is what a human reads on the PR weeks later. Without
  # this marker a green kipi/codex-approved is indistinguishable from a real
  # second opinion, and the whole point of this engine is that it is not Claude.
  [ "$DEGRADED" = "1" ] && desc="DEGRADED (codex down, Opus fallback): $desc"
  desc="$(printf '%.140s' "$desc")"
  # STATUS_REPO_PATH, not {owner}/{repo}: `gh api` resolves those placeholders
  # from the CWD repo and accepts no -R, so an unattended run posted
  # kipi/reviewer-approved onto the home repo for a review of another one.
  local args=(api -X POST "repos/$STATUS_REPO_PATH/statuses/$sha"
              -f "state=$state" -f "context=$context" -f "description=$desc")
  # Link only a real URL. The PR comment just above is what --post creates; when
  # that failed there is nothing to link, and a local file path is not a URL.
  case "$target" in https://*) args+=(-f "target_url=$target") ;; esac
  if gh "${args[@]}" >/dev/null 2>&1; then
    echo "  commit status posted: $context=$state on $sha"
  else
    echo "  WARN: could not post commit status '$context' (state=$state) on sha $sha; the review is recorded but NO gate moved" >&2
  fi
}

if [ "$POST" = "1" ]; then
  COMMENT_URL=""
  # THE STATUS GOES FIRST, BEFORE THE COMMENT (sp-fa810306). This ordering is the
  # fix, and it is the whole reason this block moved.
  #
  # THE SCAR, exact: on 2026-09-07 round 3 of PR #314 posted its APPROVE WITH NITS
  # comment at 00:29:47Z and the process died before the commit status call. The
  # approval existed as prose and did not exist as a gate, so the next session read
  # `gh api statuses adc29516` as empty, re-ran the same head, and the re-run
  # returned REQUEST CHANGES. An earned approval was overturned by a kill.
  #
  # WHICH HALF TO LOSE. A kill can land between any two calls; the only choice is
  # which one survives it. The comment is 60 KB of prose a human reads later; the
  # status is the one thing a required check, converge.sh and the next session all
  # read. Losing prose costs a re-read of the review file on disk. Losing the
  # status costs a whole re-review that can overturn the verdict. So the status
  # goes first, unconditionally.
  #
  # POSTED TWICE, ON PURPOSE, AND NOT A SECOND WRITER. Commit statuses append and
  # the latest wins, so the second call below re-posts the SAME context with the
  # SAME $VERDICT and adds only target_url once the comment URL exists. The value
  # a gate reads cannot differ between the two calls, because both read $VERDICT,
  # which was computed once, above. If the run dies between them the first post
  # stands, missing only its link.
  if [ -n "$HEAD_SHA" ]; then
    post_reviewer_status "$HEAD_SHA" "$VERDICT" ""
  else
    echo "  no head sha for PR #$PR: posting NO commit status (a status on a guessed sha looks authoritative)"
  fi
  # POST THE RENDERED REVIEW, NEVER THE RAW FILE (sp-48688b24). `--body-file
  # "$REVIEW"` sent the codex agent's entire stdout. Measured on disk 2026-07-30,
  # four real rounds: 435,280 / 519,377 / 278,439 / 197,279 bytes. Three were
  # rejected; only the 197,279-byte round landed (as a 197,208-character comment
  # on PR #46). So the old failure was SIZE-DEPENDENT, not universal -- worth
  # stating because the first two write-ups of this defect, mine included, both
  # claimed it failed every time and were wrong.
  #
  # THE CAP IS DELIBERATELY CONSERVATIVE, NOT TUNED. The observed ceiling sits
  # somewhere between 197,279 and 278,439 bytes, while a reproduced rejection
  # reported `Body is too long (maximum is 65536 characters) (addComment)`. Those
  # two facts do not agree, so the limit is path-dependent and I do not know which
  # path a future gh version takes. 60,000 is under BOTH, which makes the comment
  # succeed regardless of which limit applies. Tuning it upward would trade a
  # guaranteed delivery for a longer transcript nobody reads.
  # EXPLICIT XXXXXX TEMPLATE, because `mktemp -t name` is not portable. BSD
  # mktemp (macOS) appends the random suffix itself; GNU mktemp (the Linux CI
  # runner) rejects a template with fewer than three X's. My first cut used the
  # BSD form, passed 14/14 locally, and turned `validate` red on the PR -- the
  # body file was never created, so --body-file got an empty path. Nothing on
  # this machine could have caught it; the runner is the other OS.
  # NEVER FALL BACK TO $REVIEW ITSELF (codex round 4, minor). My first fallback was
  # `|| REVIEW_BODY="$REVIEW"`, which then ran
  # `review_comment_body "$REVIEW" > "$REVIEW_BODY"` -- the same path as input and
  # output. The `>` truncates the review before the renderer reads it, so a mktemp
  # failure would DESTROY the only copy of a review that cost 8-13 minutes of codex
  # time, and post a self-copy of the wreckage. A degraded path may post something
  # worse; it may never eat the artifact.
  REVIEW_BODY="$(mktemp "${TMPDIR:-/tmp}/pr-review-comment.XXXXXX" 2>/dev/null)" || REVIEW_BODY=""
  # POST_FILE is what gh sends; REVIEW_BODY is only ever a file WE created. Keeping
  # them separate is what makes the degraded path safe: with no temp file we post
  # the raw review unchanged and write nothing, instead of redirecting into the
  # artifact we are trying to read.
  # THE MARKER MEANS "A VERDICT WAS PUBLISHED ON THIS HEAD", NOT "A RUN HAPPENED"
  # (round 1 major, 2026-09-07). The first cut stamped it on every posted comment,
  # UNUSABLE reviews included. An unusable review posts state=failure and states no
  # verdict, so that head then carried a red required check AND a marker that made
  # every automated re-review exit 3 -- a wedge no unattended path could clear,
  # because --force is a hand-typed flag. The guard exists to stop a re-review from
  # overturning an EARNED verdict; a review nobody could read earned nothing, so it
  # must not claim the head.
  MARK_HEAD=0
  if [ "$REVIEW_USABLE" = "1" ] && [ -n "$VERDICT" ]; then MARK_HEAD=1; fi
  [ "$MARK_HEAD" = "1" ] \
    || echo "  NOTE: this review is unusable or states no verdict, so the comment carries NO head marker and a later run may re-review ${HEAD_SHA:0:8} without --force."
  if [ -n "$REVIEW_BODY" ]; then
    # THE MARKER LEADS THE BODY, and the position is load-bearing. It is what the
    # duplicate-run refusal at the top of this script greps for, and
    # review_comment_body truncates from the END, so a marker appended after the
    # body would be the first thing a long review dropped -- the guard would then
    # be silently disarmed on exactly the reviews that run longest.
    {
      [ "$MARK_HEAD" = "1" ] && { review_head_marker "$HEAD_SHA"; printf '\n\n'; }
      review_comment_body "$REVIEW" "$VERDICT" "$ENGINE" "$DEGRADED"
      # The structural warning rides INSIDE the comment rather than only in this
      # log, because the log belongs to whoever ran the reviewer and the PR is
      # where the next person decides whether to patch again.
      [ -n "$STRUCTURAL_LINE" ] && printf '\n**%s**\n' "$STRUCTURAL_LINE"
    } >"$REVIEW_BODY"
    POST_FILE="$REVIEW_BODY"
  else
    POST_FILE="$REVIEW"
    echo "  WARN: could not create a temp file; posting the RAW review, which GitHub may reject on size. The head marker is NOT in this body, so a later run will not see this verdict and may re-review the same head (sp-fa810306). Erring toward a duplicate round is the safe direction here: the other way is a wedge no unattended run can clear." >&2
  fi
  # Keep the reason. A bare "could not comment" sent the maintainer to guess
  # between a size rejection, an auth failure and a closed PR -- the same
  # discard-the-reason defect PR #46 fixed one call lower down.
  COMMENT_ERR="$(mktemp "${TMPDIR:-/tmp}/pr-review-comment-err.XXXXXX" 2>/dev/null)" || COMMENT_ERR=/dev/null
  if COMMENT_URL="$(gh pr comment "$PR" $KIPI_GH_REPO_ARGS --body-file "$POST_FILE" 2>"$COMMENT_ERR")"; then
    echo "  posted to PR #$PR ($(wc -c <"$POST_FILE" | tr -d ' ') bytes rendered from $(wc -c <"$REVIEW" | tr -d ' '))"
  else
    COMMENT_URL=""
    echo "  WARN: could not comment on PR #$PR: $(tr '\n' ' ' <"$COMMENT_ERR" | cut -c1-300)" >&2
    echo "  WARN: the review is on disk at $REVIEW but NO human-readable copy reached the PR" >&2
  fi
  rm -f "$REVIEW_BODY" "$COMMENT_ERR"
  # THE SECOND POST IS AN ENRICHMENT, NOT THE POST. The gate already moved above,
  # before the comment, so this call exists only to attach target_url to a status
  # that is already correct. It is skipped when there is no URL to attach: a
  # re-post carrying nothing new would be two writes for one fact, and the first
  # one already said everything a gate reads.
  #
  # No sha, no status -- the same rule as above. A status on a guessed commit is
  # worse than none because it looks authoritative (ASK-216).
  if [ -n "$HEAD_SHA" ] && [ -n "$COMMENT_URL" ]; then
    post_reviewer_status "$HEAD_SHA" "$VERDICT" "$COMMENT_URL"
  fi
  if [ -n "$ISSUE" ]; then
    # THE REVIEWER'S HALF OF THE CONVERSATION (ASK-221, founder directive
    # 2026-07-29: Sana and codex talk to each other in the issue's comments).
    #
    # This used to post a one-line summary, which is a NOTIFICATION, not a turn in
    # a conversation: Sana had nothing to answer because the findings themselves
    # only ever landed on the PR. Carrying the actual findings block onto the issue
    # is what makes a reply possible, and the issue is the one surface both agents
    # can see (the worker reads PR comments; the founder reads Linear).
    #
    # Attributed to "$ENGINE-reviewer", never a bare "reviewer": the whole point of
    # the flip is that the checker is not Claude, so a thread that cannot tell you
    # WHICH engine spoke loses the only fact that matters. It also gives Sana a
    # string to filter on (`linear-sync.py comments --agent codex-reviewer`).
    # Through the ONE reader (sp-c0a9dac3). Its own sed range here was the third
    # copy of that extraction, so the Linear comment could carry a DIFFERENT set of
    # findings than the verdict was derived from -- Sana would be answering findings
    # that never set the gate, on a review whose gate came from findings she never saw.
    REVIEW_FINDINGS="$(findings_block "$REVIEW")"
    [ -n "$REVIEW_FINDINGS" ] || REVIEW_FINDINGS="(no findings block parsed from this review)"
    # `|| true` HERE WAS A SILENT DROP (codex round 2 of PR #34, minor;
    # sp-583dc1a0). Every other failure on this path says so out loud -- the PR
    # comment warns, and a failed commit status warns that NO gate moved -- but a
    # failed Linear post printed nothing, discarded the reason down /dev/null, and
    # the run still exited 0 and printed `done`. Linear is the ONE surface Sana
    # reads, so losing it silently means she never answers findings she was never
    # shown, and the loop looks healthy while the conversation never happens. Not
    # hypothetical: the round-2 run on 2026-07-30 lost its PR comment
    # (`WARN: could not comment on PR`) and only the loud branch revealed it.
    #
    # STILL EXIT 0, deliberately. The gate above is already correctly set from a
    # review that really ran; making the run fail here would make the worker log
    # `codex reviewer failed` for a review that succeeded, which trades a silent
    # drop for a false alarm. Loud plus a page is the fix, not a non-zero exit.
    SYNC_ERR="$(python3 "$SYNC" progress "$ISSUE" \
      "Review of PR #$PR complete ($ENGINE engine$([ "$DEGRADED" = "1" ] && printf ', DEGRADED: codex down, Opus fallback')). Verdict: ${VERDICT:-unstated}. Reviewer: Meta senior-staff persona, fresh eyes, every finding required to ship an executed reproducer.

Sana: reply to this comment on THIS issue. For each finding, either the file:line that already handles it, or what you changed. Findings below." \
      --agent "$ENGINE-reviewer" --evidence "$REVIEW_FINDINGS" 2>&1 >/dev/null)"
    if [ $? -eq 0 ]; then
      echo "  review posted to $ISSUE as $ENGINE-reviewer (findings included)"
    else
      echo "  WARN: could not post the review to $ISSUE as $ENGINE-reviewer. The gate is set from a review nobody on the issue can see, so Sana has no findings to answer. Reason: ${SYNC_ERR:-(no output)}" >&2
      # THE PAGE IS BEST-EFFORT AND SAYS SO (codex round 1 of PR #46, major 2).
      # slack-notify.sh no-ops silently when no webhook is configured -- that is
      # deliberate per founder-notifications.md, so callers never break -- which
      # means a zero exit here does NOT prove delivery. Claiming "paged" would be
      # the same overclaim this commit is removing one layer down. So: attempt it,
      # record what came back, and leave the stderr WARN above as the one record
      # that is always written.
      NOTIFY_OUT="$(bash "$NOTIFY" "reviewer: PR #$PR review did NOT reach $ISSUE ($ENGINE engine, verdict ${VERDICT:-unstated}). The gate moved but the findings are not on the issue, so the rework conversation cannot start." 2>&1)"
      NOTIFY_RC=$?
      if [ "$NOTIFY_RC" -ne 0 ]; then
        echo "  WARN: the page about that loss ALSO failed (rc=$NOTIFY_RC${NOTIFY_OUT:+: $NOTIFY_OUT}). This loss is recorded ONLY in this log." >&2
      else
        echo "  page attempted for the lost review (delivery not confirmable: the notifier no-ops silently when unconfigured)" >&2
      fi
    fi
  fi
fi

echo "$(TS) done$DRY_NOTE"
# EXIT 4 MEANS "IT ALL WORKED AND THE NEXT PATCH IS THE WRONG MOVE" (sp-46726f79).
# It is reached only AFTER the post, so a caller that treats non-zero as failure
# still has its comment and its commit status. Callers that care read the code;
# callers that do not are no worse off than before, because the outward side
# effects are identical either way.
exit "${FINAL_EXIT:-0}"
