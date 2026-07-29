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
# Set when codex answered with nothing parseable. It is a SEPARATE flag from the
# derived verdict because verdict_from_findings reads an unclosed FINDINGS block
# as an EMPTY one and returns APPROVE -- so "the derivation produced something"
# is not evidence that the review said anything. Caught by the truncated-stream
# case in test-severity-floor.sh, which passed the first cut of this fix.
CODEX_UNUSABLE=0

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
[ -n "$ISSUE" ] || ISSUE="$(printf '%s' "$PR_TITLE" | grep -oE 'ASK-[0-9]+' | head -1)"

echo "$(TS) reviewing PR #$PR: $PR_TITLE"
echo "  head sha under review: ${HEAD_SHA:-unknown}"
[ -n "$ISSUE" ] && echo "  linked issue: $ISSUE"

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
You were asked to review pull request #$PR in $SKEL, and you are ADVERSARIAL by default:
your job is to find what is wrong, not to be agreeable.$ROUND_RULE

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
              "cd '$SKEL' && claude -p --model '$CLAUDE_MODEL' \"\$1\" </dev/null > '$2' 2>&1" _ "$PROMPT" ;;
    codex)  run_bounded "$TIMEOUT_SECONDS" bash -c \
              "codex exec --skip-git-repo-check --model '$CODEX_MODEL' -C '$SKEL' \"\$1\" </dev/null > '$2' 2>&1" _ "$PROMPT" ;;
  esac
}

# A codex answer is usable only if it carries a COMPLETE machine-readable block.
# The closing line is what makes this a real check: verdict_from_findings uses
# `sed -n '/^FINDINGS:/,/^END FINDINGS/p'`, which prints to EOF when the range
# never closes -- so a stream that died right after opening the block yields an
# EMPTY findings list, and an empty list derives APPROVE. A truncated review that
# green-lights a PR nobody read is the worst outcome available in this script.
review_has_complete_findings_block() {
  local f="$1"
  [ -s "$f" ] || return 1
  grep -q '^FINDINGS:'    "$f" 2>/dev/null || return 1
  grep -q '^END FINDINGS' "$f" 2>/dev/null || return 1
}

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
    echo "$(TS) review written: $REVIEW"
  else
    rc=$?
    echo "$(TS) reviewer failed or timed out (rc=$rc). Partial output: $REVIEW" >&2
    exit "$rc"
  fi
elif run_engine codex "$REVIEW"; then
  if review_has_complete_findings_block "$REVIEW"; then
    note_degraded_transition 0
    echo "$(TS) review written: $REVIEW"
  else
    # Codex ANSWERED and said nothing parseable. Deliberately NOT the fallback
    # path: an outage leaves no review to trust, but this is an attempted review
    # whose CONTENT cannot be trusted, and filling the slot with an Opus approval
    # over it would invent a verdict for a review that said nothing. It falls
    # through UNSTATED, and unstated posts state=failure a few lines below.
    CODEX_UNUSABLE=1
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
    echo "$(TS) DEGRADED review written by the Opus fallback: $REVIEW"
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
if [ "$CODEX_UNUSABLE" = "1" ]; then
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
  VERDICT="$DERIVED_VERDICT"
  if [ "$STATED_VERDICT" != "$DERIVED_VERDICT" ]; then
    echo "  NOTE: reviewer stated '${STATED_VERDICT:-none}' but its own findings imply '$DERIVED_VERDICT'; using the findings"
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
python3 - "$PR" "$ISSUE" "$VERDICT" "$REVIEW" "$(TS)" "$STATED_VERDICT" "$DERIVED_VERDICT" "$ROUND" "$HEAD_SHA" "$VERDICT_DIR" "$ENGINE" <<'PY'
import json, sys
pr, issue, verdict, review, ts, stated, derived, rnd, head_sha, verdict_dir, engine = sys.argv[1:12]
out = f"{verdict_dir}/pr-{pr}.verdict.json"
json.dump({"pr": int(pr), "issue": issue, "verdict": verdict,
           "stated": stated, "derived": derived,
           "source": "findings" if derived else "prose",
           "engine": engine,
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
  COMMENT_URL="$(gh pr comment "$PR" --body-file "$REVIEW" 2>/dev/null)" \
    && echo "  posted to PR #$PR" \
    || { COMMENT_URL=""; echo "  WARN: could not comment on PR" >&2; }
  # No sha, no status. A status on a guessed commit is worse than none because
  # it looks authoritative -- the same reason ASK-216 captured the sha before
  # dispatch instead of looking it up afterwards.
  if [ -n "$HEAD_SHA" ]; then
    post_reviewer_status "$HEAD_SHA" "$VERDICT" "$COMMENT_URL"
  else
    echo "  no head sha for PR #$PR: posting NO commit status (a status on a guessed sha looks authoritative)"
  fi
  if [ -n "$ISSUE" ]; then
    python3 "$SYNC" progress "$ISSUE" \
      "Adversarial review of PR #$PR complete ($ENGINE engine$([ "$DEGRADED" = "1" ] && printf ', DEGRADED: codex down, Opus fallback')). Verdict: ${VERDICT:-unstated}. Reviewer: Meta senior-staff persona, fresh eyes, every finding required to ship an executed reproducer." \
      --agent "reviewer" >/dev/null 2>&1 \
      && echo "  progress noted on $ISSUE" || true
  fi
fi

echo "$(TS) done"
exit 0
