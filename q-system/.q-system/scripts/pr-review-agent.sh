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
# TWO ENGINES, ONE SCRIPT -- CODEX IS THE ONE THAT GATES (ASK-221)
# ----------------------------------------------------------------
# Sana (the PR author) is Claude. A Claude reviewer is a different process with no
# shared memory, genuinely useful -- but the same lab and the same model family, so
# the blind spots stay CORRELATED. Fresh context is not an independent mind.
#
# So codex is THE reviewer, not a second opinion appended to a Claude one:
# founder directive 2026-07-29, "codex with gpt-5.6 as a sr. staff swe at Meta is
# the agent that checks sana's work". It owns `kipi/reviewer-approved` and writes
# the ONE verdict record converge.sh and linear-worker.sh gate on. Claude keeps
# the same script but posts an ADVISORY `kipi/claude-approved` and writes its
# record out of the gate's way.
#
# The Opus fallback below is what makes this safe: when codex is down, Claude
# fills the PRIMARY slot and the status says DEGRADED out loud, so an outage
# degrades the gate's independence instead of wedging every open PR.
#
# It is a FLAG, not a second script, on purpose: sha capture (ASK-216), verdict
# derivation from labelled severities, the commit-status post (ASK-217) and
# spillover capture all stay shared and identical. A separate codex script would
# be a second writer with its own semantics -- the defect class this repo keeps
# finding. What the engine changes is exactly three things: which binary runs,
# which status context it posts, and which directory its artifacts land in.
#
# Usage:  pr-review-agent.sh <pr-number> [--issue ASK-nnn] [--post]
#                            [--engine claude|codex]
#         --post also comments the review on the PR and the Linear issue.
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

# CODEX BY DEFAULT. Env-overridable so a codex outage long enough to matter is a
# config change (`KIPI_REVIEW_ENGINE=claude`), not an edit to the script that
# gates every PR in the repo.
PR=""; ISSUE=""; POST=0; ENGINE="${KIPI_REVIEW_ENGINE:-codex}"
while [ $# -gt 0 ]; do
  case "$1" in
    --issue)  shift; ISSUE="${1:-}" ;;
    --engine) shift; ENGINE="${1:-}" ;;
    --post)   POST=1 ;;
    -*) echo "unknown arg: $1" >&2; exit 1 ;;
    *) PR="$1" ;;
  esac
  shift || true
done
[ -n "$PR" ] || { echo "usage: pr-review-agent.sh <pr-number> [--issue ASK-nnn] [--post] [--engine claude|codex]" >&2; exit 1; }

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
#   the ROOT, not a subdir. So "codex is the gate" means codex writes THAT path,
#   and claude's record moves down into $OUT_DIR/claude to get out of its way.
#   Exactly one engine writes the gating record: single writer, preserved.
PRIMARY_ENGINE="${KIPI_REVIEW_PRIMARY_ENGINE:-codex}"

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
REVIEW="$ENGINE_DIR/pr-$PR-$(date +%Y%m%d-%H%M%S).md"

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
PR_META="$(gh pr view "$PR" --json headRefOid,title -q '.headRefOid + "\t" + .title' 2>/dev/null)" \
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
PR_META_CONFIRM="$(gh pr view "$PR" --json headRefOid,title -q '.headRefOid + "\t" + .title' 2>/dev/null || true)"
HEAD_SHA_CONFIRM="${PR_META_CONFIRM%%$'\t'*}"
if [ -n "$HEAD_SHA_CONFIRM" ] && [ "$HEAD_SHA_CONFIRM" != "$HEAD_SHA" ]; then
  echo "REFUSING: PR #$PR's head moved between two reads (${HEAD_SHA:0:8} then ${HEAD_SHA_CONFIRM:0:8})." >&2
  echo "  Something is pushing to this branch right now. Reviewing either sha risks a green status on code the reviewer did not read." >&2
  echo "  Re-run once the branch settles. No review was dispatched and NO status was posted." >&2
  exit 1
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
REVIEW_ROOT="$SKEL"

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
review_worktree() {  # review_worktree <sha> -> prints path, or nothing
  local sha="$1" wt="$HOME/.config/kipi/review-trees/pr-$PR"
  mkdir -p "$(dirname "$wt")" 2>/dev/null || return 1
  if [ -d "$wt/.git" ] || [ -f "$wt/.git" ]; then
    git -C "$wt" checkout --detach --force "$sha" >/dev/null 2>&1 || return 1
  else
    git -C "$SKEL" worktree add --detach "$wt" "$sha" >/dev/null 2>&1 || return 1
  fi
  # Prove it landed where we asked. A worktree silently sitting at the wrong sha
  # is the same false-provenance bug in a new costume.
  [ "$(git -C "$wt" rev-parse HEAD 2>/dev/null)" = "$sha" ] || return 1
  printf '%s' "$wt"
}

if [ -n "$HEAD_SHA" ] && git -C "$SKEL" cat-file -e "${HEAD_SHA}^{commit}" 2>/dev/null; then
  ISOLATED="$(review_worktree "$HEAD_SHA" || true)"
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
  if ! git -C "$SKEL" cat-file -e "${HEAD_SHA}^{commit}" 2>/dev/null; then
    echo "  WARN: $SKEL does not have commit $HEAD_SHA, so the tree/PR match cannot be proven (stale or partial clone?). Proceeding; a review of the wrong tree would report findings absent from this diff." >&2
  elif ! git -C "$SKEL" merge-base --is-ancestor "$HEAD_SHA" HEAD 2>/dev/null; then
    # SKEL does not contain the PR. Find a worktree that does. `worktree list
    # --porcelain` emits a `worktree <path>` line per tree, SKEL included; testing
    # SKEL again is harmless and keeps the loop free of a special case.
    FOUND_ROOT=""
    while IFS= read -r wt; do
      [ -n "$wt" ] || continue
      [ -d "$wt" ] || continue
      if git -C "$wt" merge-base --is-ancestor "$HEAD_SHA" HEAD 2>/dev/null; then
        FOUND_ROOT="$wt"; break
      fi
    done < <(git -C "$SKEL" worktree list --porcelain 2>/dev/null | awk '/^worktree /{print substr($0,10)}')

    if [ -n "$FOUND_ROOT" ]; then
      REVIEW_ROOT="$FOUND_ROOT"
      echo "  tree: $REVIEW_ROOT (holds PR #$PR at ${HEAD_SHA:0:8}; the script itself lives in $SKEL)"
    else
      echo "REFUSING: PR #$PR is at $HEAD_SHA, which is not in the history of $SKEL (HEAD $(git -C "$SKEL" rev-parse --short HEAD 2>/dev/null)) or of any worktree it lists." >&2
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

Earlier rounds are in the PR comments (\`gh pr view $PR --comments\`). Read them
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

  gh pr view $PR
  gh pr diff $PR

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

# AN ENGINE THAT PRODUCED NOTHING NEVER RAN (ASK-287).
# ----------------------------------------------------
# `codex exec` OUT OF CREDITS EXITS 0. Measured 2026-08-02 with a real billed
# call: it printed `ERROR: Your workspace is out of credits.` and returned rc=0.
# So `run_engine codex` reported SUCCESS, control took the "answered with nothing
# parseable" branch -- which by design does NOT fall back -- and the Opus fallback
# promised at the top of this file never fired. Not "fired and failed": never
# once since it was written. On disk: unusable reviews for PRs #66 and #67 (7,724
# bytes of transcript each, not one token of model output -- see the correction
# below; "0-byte" was this comment's original guess and it was wrong),
# degraded.state=1 (the system NOTICED), and no pr-reviews/claude/ directory at
# all. Both PRs sat CI-green on kipi/reviewer-approved=failure and nothing merged.
#
# Same defect class this repo hit repeatedly on 2026-08-01: two failure modes
# genuinely different IN THE WORLD, identical in the SIGNAL being read. An outage
# and a garbage answer cannot be told apart by an exit code, so this stops asking
# the exit code and asks the artifact instead:
#
#   NO CONTENT AT ALL          -> the engine never reviewed  -> OUTAGE, fall back
#   CONTENT THAT DOES NOT PARSE -> an attempted review        -> GARBAGE, no fallback
#
# The second rule is deliberately untouched and must stay that way. An outage
# leaves no review to trust; garbage IS a review whose content cannot be trusted,
# and filling the gate with an Opus approval over it invents a verdict for a
# review that said nothing. A fabricated green is worse than a blocked merge.
#
# EMPTINESS WAS THE WRONG SHAPE, and a fixture nobody grounded is why (found by
# codex reviewing PR #86, 2026-08-03). The first cut of this predicate read "zero
# bytes", on the belief that an out-of-credits run leaves an empty file. It does
# not. `codex exec ... > "$2" 2>&1` captures the WHOLE transcript, so every run --
# success, garbage, or dead-at-the-API -- writes the version banner, the workdir
# block, the echoed prompt and the hook chatter before anything else. The real
# PR #66 / #67 outage artifacts are 7,724 bytes each. A zero-byte codex review is
# not a thing that happens, so the predicate could never fire on the very payload
# this issue was opened about, and the fallback still never ran.
#
# WHAT THE ARTIFACT ACTUALLY DISTINGUISHES. Captured live 2026-08-03 from the
# same invocation run_engine makes, one failing run and one succeeding run:
#
#   ...hook: UserPromptSubmit Completed        ...hook: UserPromptSubmit Completed
#   ERROR: <the 400 from the API>              codex            <- assistant turn
#   ERROR: <repeated>                          ALIVE
#                                              hook: Stop / tokens used
#
# `codex` alone on a line is the turn marker printed before the model's first
# token. Its ABSENCE means no token was ever emitted: the engine never reviewed,
# whatever the exit code said. That is the outage, and it is a structural
# property of the producer rather than a list of error strings to keep chasing.
#
# The garbage rule is UNCHANGED and still must not move: a review that took its
# turn and then said something unparseable has the marker, so it keeps the
# no-fallback path. An outage leaves no review to trust; garbage IS a review
# whose content cannot be trusted, and an Opus approval laid over it invents a
# verdict for a review that said nothing.
#
# The terminal-ERROR arm is a second, independent proof for the same conclusion,
# kept because the out-of-credits banner was measured (2026-08-02) while its
# turn-marker absence is inferred from the sibling 400 above. It is anchored at
# line start and only consulted at the END of the transcript, after the trailing
# `hook:` / `tokens used` noise, so a review that merely QUOTES an error line
# cannot trip it. Both arms sit behind "no complete FINDINGS block" in the caller,
# so a parseable review is never routed to the fallback by either one.
engine_never_answered() {   # engine_never_answered <review-file>
  local f="${1:-/dev/null}"
  [ -s "$f" ] || return 0
  [ -z "$(tr -d '[:space:]' < "$f" 2>/dev/null)" ] && return 0
  grep -q '^codex[[:space:]]*$' "$f" 2>/dev/null || return 0
  grep -v -e '^hook: ' -e '^tokens used' -e '^[0-9,]*$' -e '^[[:space:]]*$' "$f" 2>/dev/null \
    | tail -1 | grep -q '^ERROR: '
}

# PAGE ON THE TRANSITION ONLY. A ping every run while codex stays down is the
# cry-wolf failure: it trains the operator to skim, which costs the real alert
# later. Both edges earn their one line -- going degraded means the two statuses
# stopped being independent, and an operator who never hears the recovery cannot
# tell a live second opinion from an Opus stand-in wearing its context.
#
# ONE WRITER PER TRANSITION (codex round 3 on PR #86, major). The read and the
# write used to sit next to each other with nothing holding them together, so
# two reviewers hitting the same outage -- which is what an outage IS, every PR
# on the board failing at once -- both read prev=0, both wrote 1, and both paged.
# Two pings for one transition is precisely the cry-wolf failure the transition
# check exists to prevent, so the check has to be atomic or it is decoration.
# Reproduced at 100/100 trials before this lock (codex), 0/100 after.
#
# `mkdir` is the test-and-set: it is atomic on every filesystem this runs on and
# needs no `flock`, which macOS does not ship. The whole read-compare-write sits
# inside it; the PAGE deliberately does not, because by then the winner is
# already decided and holding a lock across a network call is how one slow
# notifier stalls every reviewer behind it.
#
# THE LOCK EXPIRES RATHER THAN WEDGING. A run killed between mkdir and rmdir
# would otherwise silence the notifier forever, and a notifier that never fires
# again is a worse failure than the duplicate page this lock exists to stop. So
# after ~10s the waiter takes the lock anyway and accepts that risk explicitly.
note_degraded_transition() {   # note_degraded_transition <0|1> [reason]
  local now="$1" reason="${2:-}" prev="" msg lock waited=0
  mkdir -p "$(dirname "$DEGRADED_STATE")"
  lock="$DEGRADED_STATE.lock"
  until mkdir "$lock" 2>/dev/null; do
    waited=$((waited + 1))
    [ "$waited" -ge 100 ] && break
    sleep 0.1
  done
  [ -f "$DEGRADED_STATE" ] && prev="$(tr -dc '01' < "$DEGRADED_STATE" 2>/dev/null | head -c1)"
  [ -n "$prev" ] || prev=0
  printf '%s\n' "$now" > "$DEGRADED_STATE"
  rmdir "$lock" 2>/dev/null || true
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
    echo "$(TS) review written: $REVIEW"
  else
    rc=$?
    echo "$(TS) reviewer failed or timed out (rc=$rc). Partial output: $REVIEW" >&2
    exit "$rc"
  fi
else
  # THE RC IS CAPTURED, NOT BRANCHED ON DIRECTLY (ASK-287). `if run_engine codex`
  # made the exit code the whole classifier, and an out-of-credits codex can exit
  # 0. The artifact decides now; the rc is only one of the two things that can
  # prove an outage, and it is the weaker one.
  # USABILITY IS TESTED FIRST, and that ordering is deliberate. It means no
  # widening of the outage predicate can ever route a parseable review into the
  # fallback: the only inputs the classifier below sees are ones that carry no
  # usable verdict either way.
  #
  # THE QUESTION IS review_is_usable, NOT BLOCK-COMPLETENESS (the #86/#87 merge).
  # ASK-287 was written against `review_has_complete_findings_block`, a local
  # forwarder that sp-df1a458f then DELETED on purpose -- a forwarder is one more
  # place the two dispatch sites can be made to disagree about the same file.
  # Completeness alone also says YES to a stream that answered "Reply `OK` and
  # I'll execute exactly that plan" wrapped around a real prior-round block.
  # review_is_usable is that check AND the decline guard, so resolving here to the
  # wider predicate keeps both fixes; resolving to the narrower one would have
  # called a function main no longer defines.
  run_engine codex "$REVIEW"; CODEX_RC=$?
  if review_is_usable "$REVIEW" && [ "$CODEX_RC" = "0" ]; then
    # A usable review. Nothing to classify.
    note_degraded_transition 0
    echo "$(TS) review written: $REVIEW"
  elif [ "$CODEX_RC" = "0" ] && ! engine_never_answered "$REVIEW"; then
    # Codex ANSWERED and said nothing parseable. Deliberately NOT the fallback
    # path: an outage leaves no review to trust, but this is an attempted review
    # whose CONTENT cannot be trusted, and filling the slot with an Opus approval
    # over it would invent a verdict for a review that said nothing. It falls
    # through UNSTATED, and unstated posts state=failure a few lines below.
    #
    # A DECLINE-TO-START LANDS HERE, NOT IN THE OUTAGE ARM, and that is correct:
    # the model took its turn to write the plan, so the turn marker is present and
    # engine_never_answered is false. A review that stopped to ask permission is a
    # garbage answer, not an outage -- UNSTATED holds the PR either way, and no
    # Opus verdict is invented over it.
    REVIEW_UNUSABLE=1
    note_degraded_transition 1 \
      "it took its turn and then emitted no complete FINDINGS block (truncated or unreadable), or it stopped to ask permission instead of reviewing, so the status is UNSTATED rather than a fabricated APPROVE"
    echo "$(TS) codex answered but the review is not usable (truncated, unreadable, or a plan awaiting confirmation); verdict stays UNSTATED. Output kept at: $REVIEW" >&2
  else
    # Codex is DOWN. If nothing filled $STATUS_CONTEXT and it were a required
    # check, every PR in the repo would wedge forever -- so the Opus reviewer fills
    # the slot, and the status says DEGRADED out loud. A SILENT fallback is the
    # real hazard: both statuses would come from one model family and nobody would
    # know the independence this engine exists to buy had been lost.
    DEGRADED=1
    # NAME WHICH PROOF FIRED. "exited non-zero" and "exited 0 and emitted nothing"
    # are different outages to whoever reads this log at 3am -- the second one is
    # billing or auth, and telling them apart is the whole point of ASK-287.
    if [ "$CODEX_RC" = "0" ]; then
      CODEX_DOWN_WHY="it exited 0 but never took an assistant turn -- no output, or a transcript that ends on an ERROR banner -- so it never actually reviewed. That is out of credits, unauthenticated, or a rejected model; all three exit 0 (ASK-287)"
    else
      CODEX_DOWN_WHY="it exited $CODEX_RC"
    fi
    mv -f "$REVIEW" "$REVIEW.codex-failed" 2>/dev/null || true
    echo "$(TS) codex is unusable: $CODEX_DOWN_WHY. Running the Opus fallback so $STATUS_CONTEXT does not wedge. Codex output kept at: $REVIEW.codex-failed" >&2
    # THE PAGE REPORTS THE OUTCOME, SO IT IS SENT AFTER THERE IS ONE (codex round 4
    # on PR #86, major). It used to fire HERE, one line above `run_engine claude`,
    # saying "the Opus fallback filled the slot and the status is marked DEGRADED"
    # -- a claim about work that had not started. Three outcomes are reachable from
    # this branch and only one of them fills anything:
    #
    #   fallback writes a complete review -> $STATUS_CONTEXT goes green, DEGRADED
    #   fallback answers unparseably      -> UNSTATED (failure): the gate is HELD
    #   fallback dies                     -> the script exits: NO status is posted
    #
    # In the last two the page was the operator's only artifact and it announced a
    # filled gate over a PR nothing was holding, which reads as "handled" and sends
    # them past the one PR that needs them. The page fires exactly once either way
    # -- including on the death path, BEFORE the exit, because a both-engines-down
    # run that says nothing at all is the silence this whole notifier exists to end.
    #
    # $FALLBACK_OUTCOME is assembled per branch and the page is sent from ONE place
    # per branch rather than once at the bottom: the death path has to exit with the
    # fallback's rc, and threading that around a shared tail is how a page gets
    # skipped on the branch that most needs it.
    if run_engine claude "$REVIEW"; then
      # THE FALLBACK GETS THE SAME PARSEABILITY BAR AS CODEX. Exiting 0 is not
      # evidence it said anything: a truncated stream leaves an unclosed FINDINGS
      # block, which derives APPROVE and would post state=success on the REQUIRED
      # context. Filling the gate with an unread approval is worse than leaving it
      # unstated, because unstated holds the PR and green releases it.
      if review_is_usable "$REVIEW"; then
        FALLBACK_OUTCOME="so the Opus fallback filled the slot and the status is marked DEGRADED"
        echo "$(TS) DEGRADED review written by the Opus fallback: $REVIEW"
      else
        REVIEW_UNUSABLE=1
        FALLBACK_OUTCOME="and the Opus fallback ALSO produced no usable review, so nothing filled the slot: the verdict is UNSTATED and the PR is HELD, not released"
        echo "$(TS) the Opus fallback answered with no complete FINDINGS block (empty or truncated); verdict stays UNSTATED. Output kept at: $REVIEW" >&2
      fi
      note_degraded_transition 1 "$CODEX_DOWN_WHY, $FALLBACK_OUTCOME"
    else
      rc=$?
      echo "$(TS) the Opus fallback ALSO failed (rc=$rc). No status is posted at all; absent is not approved." >&2
      note_degraded_transition 1 \
        "$CODEX_DOWN_WHY, and the Opus fallback ALSO failed (rc=$rc), so nothing filled the slot and NO status is posted at all -- this PR is waiting on a human"
      exit "$rc"
    fi
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
echo "  verdict: ${VERDICT:-unstated}"

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
# ASKED HERE, NOT REUSED FROM $REVIEW_UNUSABLE. That flag is set on the codex and
# fallback paths only -- the `ENGINE != codex` primary path never evaluates
# usability at all -- so reading it would record `usable: true` for a path that
# never checked, which is the fabricated-evidence direction. One call, the same
# predicate on the same file the verdict came from, covering all three paths.
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

python3 - "$PR" "$ISSUE" "$VERDICT" "$REVIEW" "$(TS)" "$STATED_VERDICT" "$DERIVED_VERDICT" "$ROUND" "$HEAD_SHA" "$VERDICT_DIR" "$ENGINE" "$INVOKER" "$REVIEW_USABLE" "$REVIEWED_BY" "$DEGRADED" <<'PY'
import json, sys
(pr, issue, verdict, review, ts, stated, derived, rnd, head_sha, verdict_dir,
 engine, invoker, usable, reviewed_by, degraded) = sys.argv[1:16]
out = f"{verdict_dir}/pr-{pr}.verdict.json"
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
  local args=(api -X POST "repos/{owner}/{repo}/statuses/$sha"
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
  if [ -n "$REVIEW_BODY" ]; then
    review_comment_body "$REVIEW" "$VERDICT" "$ENGINE" "$DEGRADED" >"$REVIEW_BODY"
    POST_FILE="$REVIEW_BODY"
  else
    POST_FILE="$REVIEW"
    echo "  WARN: could not create a temp file; posting the RAW review, which GitHub may reject on size" >&2
  fi
  # Keep the reason. A bare "could not comment" sent the maintainer to guess
  # between a size rejection, an auth failure and a closed PR -- the same
  # discard-the-reason defect PR #46 fixed one call lower down.
  COMMENT_ERR="$(mktemp "${TMPDIR:-/tmp}/pr-review-comment-err.XXXXXX" 2>/dev/null)" || COMMENT_ERR=/dev/null
  if COMMENT_URL="$(gh pr comment "$PR" --body-file "$POST_FILE" 2>"$COMMENT_ERR")"; then
    echo "  posted to PR #$PR ($(wc -c <"$POST_FILE" | tr -d ' ') bytes rendered from $(wc -c <"$REVIEW" | tr -d ' '))"
  else
    COMMENT_URL=""
    echo "  WARN: could not comment on PR #$PR: $(tr '\n' ' ' <"$COMMENT_ERR" | cut -c1-300)" >&2
    echo "  WARN: the review is on disk at $REVIEW but NO human-readable copy reached the PR" >&2
  fi
  rm -f "$REVIEW_BODY" "$COMMENT_ERR"
  # No sha, no status. A status on a guessed commit is worse than none because
  # it looks authoritative -- the same reason ASK-216 captured the sha before
  # dispatch instead of looking it up afterwards.
  if [ -n "$HEAD_SHA" ]; then
    post_reviewer_status "$HEAD_SHA" "$VERDICT" "$COMMENT_URL"
  else
    echo "  no head sha for PR #$PR: posting NO commit status (a status on a guessed sha looks authoritative)"
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

echo "$(TS) done"
exit 0
