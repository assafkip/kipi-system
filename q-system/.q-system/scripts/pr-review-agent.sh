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
#                            [--engine claude|codex] [--delta | --base <sha>]
#         --post also comments the review on the PR and the Linear issue.
#         --delta reviews only `git diff <last reviewed sha> <head>`, the sha
#         read from this engine's verdict record; with no usable record it
#         reads the whole PR (round 1). --base <sha> names the base directly;
#         it is trusted as the caller's last reviewed sha and wins over --delta.
#         Either way the verdict and kipi/reviewer-approved land on the head.
#         An empty delta, or a base equal to the head, refuses: no review runs.
#         On a PUBLIC repo the PR comment is the verdict and finding counts
#         only, never the review text or the diff (ASK-2893).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISK_FLOOR_PY="$SCRIPT_DIR/worktree-disk-floor.py"   # ASK-3648, read by review_worktree
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
#
# THE PIN IS THE ROUTING TABLE NOW (ASK-4013, founder 2026-11-08: "make that a
# rule in code"). It was an env var the dispatch plist set to Sonnet and the
# hosted workflow copied, so the table could not have decided anything. Nothing
# reads that var any more. This first read is the table's answer for a PR whose
# files are not known yet (class unknown, Opus); the class pick after pr.diff
# below replaces it. Empty only if python itself is broken: the opus alias then.
CLAUDE_MODEL="$(python3 "$SCRIPT_DIR/model_route.py" pick --job review 2>/dev/null)"
CLAUDE_MODEL="${CLAUDE_MODEL:-opus}"
CODEX_MODEL="${KIPI_REVIEW_CODEX_MODEL:-gpt-5.6-sol}"
# Verdict semantics live in ONE place, shared with the worker. Two scripts each
# grepping the review prose with their own regex is two readers with different
# semantics -- the defect class review round 2 flagged on this very PR line.
. "$SCRIPT_DIR/pr-verdict-lib.sh"
# THE ONE SLUG DERIVATION (ASK-738).
. "$SCRIPT_DIR/repo-slug-lib.sh"
# The outage classifier the worker uses (PR #421 round 16): a limit refusal here
# is the machine's, not an unusable review. See the claude dispatch below.
. "$SCRIPT_DIR/env-failure-lib.sh"
# THE ONE REVIEWER CHAIN (ASK-3831). The chain order (codex primary, codex on the
# other account, Opus), the stamps, the only `codex exec` construction in this
# directory, and the once-per-account-per-day outage ledger. This script used to
# own its own two-rung version of all four; three other call sites owned theirs.
. "$SCRIPT_DIR/reviewer-resolve.sh"
. "$SCRIPT_DIR/reviewer-token-lib.sh"

# THE ROLE THIS SCRIPT STAMPS, in one place (PR #701 review, minor 4). It is
# `adversarial`, which is what this script is: line 2 calls it adversarial, the
# prompt tells the reviewer it is "ADVERSARIAL by default", and the provenance
# block above records reviews as `claude-adversarial`. Every call site passed
# `review` instead, so `reviewer_stamp`'s refusal of an UNKNOWN role was
# protecting a value that was always the wrong KNOWN one -- and the stamp is what
# tells a later reader which bar the code was held to. Both
# `plugins/prd-os/scripts/findings_writer.py` REVIEWER_SOURCES and
# `plugins/kipi-dsse/scripts/issue_findings.py` SOURCES accept
# codex-adversarial / claude-adversarial, so the honest token already existed.
REVIEWER_ROLE="adversarial"



# CODEX BY DEFAULT. Env-overridable so a codex outage long enough to matter is a
# config change (`KIPI_REVIEW_ENGINE=claude`), not an edit to the script that
# gates every PR in the repo.
PR=""; ISSUE=""; POST=0; ENGINE="${KIPI_REVIEW_ENGINE:-claude}"; TARGET_REPO_ARG=""
REVIEW_BASE_ARG=""; DELTA=0; BASE_FLAG=0
while [ $# -gt 0 ]; do
  case "$1" in
    --issue)  shift; ISSUE="${1:-}" ;;
    # DELTA ROUNDS (ASK-3884). --base names the last reviewed sha; --delta reads
    # it from this engine's own verdict record. Neither given is a full review,
    # exactly as before. Resolved below, next to the PR fetch.
    --base)   shift; REVIEW_BASE_ARG="${1:-}"; BASE_FLAG=1 ;;
    --delta)  DELTA=1 ;;
    --engine) shift; ENGINE="${1:-}" ;;
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
[ -n "$PR" ] || { echo "usage: pr-review-agent.sh <pr-number> [--issue ASK-nnn] [--post] [--engine claude|codex] [--delta | --base <sha>]" >&2; exit 1; }

# WHAT THE ENGINE CHANGES. Everything else below this block is shared, which is
# the whole reason this is a flag and not a second script.
#
# TWO SEPARATE DIRECTORY QUESTIONS, deliberately decoupled -- conflating them is
# what made codex non-gating before the founder directive, and naively swapping
# the pair would have introduced a fresh defect in the other direction:
#
#   ENGINE_DIR (reviews + ROUND COUNTER). review_round() globs this repo's own
#   `<owner>_<repo>__pr-<N>-*.md` (ASK-1957; it globbed the legacy `pr-<N>-*.md`
#   and therefore counted nothing at all until then), so
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
#   directory ($OUT_DIR). That is safe because the round counter matches
#   `<key>-*.md` and the record is `<key>.verdict.json` -- the `-` after the key
#   is required, so the record's name can never satisfy the counter's pattern.
#   (Before ASK-1957 the counter's pattern was the legacy `pr-<N>-*.md`, which
#   could not match either, for the different and much worse reason that it
#   matched none of the repo-keyed files the writer has produced since ASK-738.)
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
# WHO ACTUALLY ANSWERED, from the resolver's chain (ASK-3831). `$ENGINE` is the
# FLAG this run was invoked with and deliberately stays that; these three are the
# rung of the chain that produced the review. Before this they did not exist, so
# the record's `engine` key said `codex` on every degraded round -- measured on
# PR #66 and #67 during the 2026-08-02 outage, and on EVERY round since
# 2026-09-16, when codex ran out of credits and 24 cap tickets each recorded the
# same fleet-wide outage privately.
RESOLVED_ENGINE=""
RESOLVED_ACCOUNT="-"
RESOLVED_STAMP=""
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
# Through the shared convention (repo-slug-lib.sh), never assembled here: the
# round counter reads these files back with review_md_name_glob, and the last
# time this line spelled the shape itself the two drifted for good (ASK-1957).
REVIEW="$(review_md_path "$ENGINE_DIR" "$REVIEW_SLUG" "$PR" "$(date +%Y%m%d-%H%M%S)")"

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
# THE CALLER'S HEAD, WHEN IT HAS ONE (ASK-318, PR #437 round 2). The hosted
# reviewer verifies that ITS event's head sha is in the checkout, but the head
# this script reviews and posts on is resolved above through gh. A push landing
# between the event and this read gives a head the checkout does not hold: the
# agent would read the base tree and post on a sha it never opened. So a caller
# that knows which head it verified pins it, and any other head is refused. The
# newer push triggers its own run.
if [ -n "${KIPI_REVIEW_EXPECT_HEAD:-}" ] && [ "$HEAD_SHA" != "$KIPI_REVIEW_EXPECT_HEAD" ]; then
  echo "REFUSING: PR #$PR's head is ${HEAD_SHA:0:12}, but the caller verified ${KIPI_REVIEW_EXPECT_HEAD:0:12} (KIPI_REVIEW_EXPECT_HEAD)." >&2
  echo "  The checkout holds the caller's head, not this one. No review was dispatched and NO status was posted." >&2
  exit 1
fi
[ -n "$ISSUE" ] || ISSUE="$(printf '%s' "$PR_TITLE" | grep -oE 'ASK-[0-9]+' | head -1)"

echo "$(TS) reviewing PR #$PR: $PR_TITLE"
echo "  head sha under review: ${HEAD_SHA:-unknown}"
[ -n "$ISSUE" ] && echo "  linked issue: $ISSUE"

# THE ROUND CAP. Every call below is a full paid model run, and nothing bounded
# how many one PR could take: 4 to 7 rounds was routine and one PR took 16. The
# round counter already existed but only fed a prompt hint, so the loop that
# re-invokes this script had no brake. Past the cap this refuses BEFORE any tree
# or model work, posts one comment and a PENDING status (never success: a cap is
# not an approval, and never failure: it is not a finding), and exits 0 so the
# caller stops instead of retrying. Raising KIPI_REVIEW_MAX_ROUNDS is the
# deliberate way past it.
MAX_ROUNDS="${KIPI_REVIEW_MAX_ROUNDS:-3}"
case "$MAX_ROUNDS" in ''|*[!0-9]*) MAX_ROUNDS=3 ;; esac
# Count only USABLE rounds. A provider blip or auth failure still leaves a
# review .md on disk, and counting those would cap a PR nobody ever reviewed
# (PR review round 1, major). review_is_usable is the same predicate that
# decides whether a round may set the gate, so "a round" means one thing.
PRIOR_ROUNDS=0
for _f in $(review_md_glob "$ENGINE_DIR" "$REVIEW_SLUG" "$PR"); do
  [ -f "$_f" ] && review_is_usable "$_f" && PRIOR_ROUNDS=$((PRIOR_ROUNDS + 1))
done
if [ "$PRIOR_ROUNDS" -ge "$MAX_ROUNDS" ]; then
  CAP_MSG="review cap reached ($MAX_ROUNDS); cap-ladder.py takes this PR at its next nightly run"
  echo "  REFUSING: PR #$PR already has $PRIOR_ROUNDS $ENGINE review round(s). $CAP_MSG. No model call made."
  if [ "$POST" = "1" ]; then
    # One comment per PR, not one per refused call: the loop may keep calling.
    # THE MARKER IS THE HAND-OFF (ASK-3824). cap-ladder.py reads this marker on
    # an open PR, writes a fresh RCA, closes the PR (branch kept) and opens a new
    # one on the same branch, so the round count starts again under the ladder's
    # own count. The ticket this used to file went into a 1054-deep alert lane
    # asking a person to "decide merge, rework or close", and the pending status
    # below takes the PR out of review-redrive, so nothing else read it.
    # The marker goes down BEFORE the comment: when it waited on the comment, a
    # failed comment re-fired the send on every later call (PR #501 review).
    CAP_MARK="$ENGINE_DIR/.round-cap-${REVIEW_SLUG//\//_}-pr-$PR"
    if [ ! -f "$CAP_MARK" ] && : > "$CAP_MARK"; then
      gh pr comment "$PR" $KIPI_GH_REPO_ARGS --body "$CAP_MSG" >/dev/null 2>&1 \
        || echo "  WARN: could not post the cap comment on PR #$PR" >&2
    fi
    # Never downgrade an approval. A cap is not a finding, so a sha that is
    # already green stays green; pending goes only over a non-success state.
    # A FAILED read is not "no status": treating it as empty posted pending over
    # a live success (PR review round 2, major). Unknown means hands off.
    CUR_STATE=""; READ_OK=0
    if [ -n "$HEAD_SHA" ] && CUR_STATE="$(gh api "repos/$STATUS_REPO_PATH/commits/$HEAD_SHA/statuses" \
        --jq "[.[] | select(.context==\"$STATUS_CONTEXT\")][0].state" 2>/dev/null)"; then
      READ_OK=1
    fi
    [ -n "$HEAD_SHA" ] && [ "$READ_OK" = 0 ] \
      && echo "  WARN: could not read $STATUS_CONTEXT on $HEAD_SHA; status left untouched" >&2
    if [ "$READ_OK" = 1 ] && [ "$CUR_STATE" != "success" ]; then
      reviewer_status_run gh api -X POST "repos/$STATUS_REPO_PATH/statuses/$HEAD_SHA" \
          -f state=pending -f "context=$STATUS_CONTEXT" -f "description=$CAP_MSG" >/dev/null 2>&1 \
        || echo "  WARN: could not set $STATUS_CONTEXT=pending on $HEAD_SHA" >&2
    fi
  fi
  exit 0
fi

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
# The lock is a PID file, written atomically and decided under a kernel flock
# (ASK-3930 round 3, see acquire_wt_lock). A stale lock whose holder is gone is
# reclaimed, because an operator who must clear locks by hand eventually clears
# one while a run is live.
_wt_lock_path=""
# Exit codes are FOUR-VALUED, and only 1 lets a caller treat the tree as nobody's.
# PR #265 round 2 split "could not lock" from "busy" because the stale-ref cleanup
# that is right when nobody has a tree deletes a live owner's evidence when
# somebody does. But "could not lock" stayed the DEFAULT, so python3 failing to
# launch, an unopenable mutex, a mutex timeout or an unreadable lock file each
# read as "nobody has it" and sent review_worktree to _wt_bail. Rounds 4 and 5 of
# ASK-3930 found two of those, one per round. So 1 is now earned, never defaulted:
# it is returned only on proof, and every outcome nobody planned for is 3.
#   0 = held by us: the helper said so AND the lock file names this run
#   1 = nobody owns it and the claim could not be written: an absent or dead
#       holder read inside the mutex. With clear-stale-ref, _wt_bail has already
#       run, inside the mutex. No other path returns 1.
#   2 = busy: a live holder that is not this run, read inside the mutex
#   3 = ownership unknown: anything else. Nothing may clear a ref on it.
acquire_wt_lock() {  # acquire_wt_lock <worktree-path> [clear-stale-ref]
  # EVERY CLAIM IS ONE KERNEL-LOCKED CRITICAL SECTION (ASK-3930 round 3). The PID
  # file is still the ownership record every reader uses, but deciding who gets it
  # (first claim, re-entry, stale reclaim, the reaper's claim) happens only while
  # holding an flock on one mutex file per review-trees directory. Rounds 1 to 3
  # each patched a userspace version: noclobber plus a stale reclaim let two
  # callers that read one dead PID both win; a mkdir mutex fixed that but needed
  # its own reclaim for a killed holder, an age check then rmdir by pathname, which
  # let a delayed contender delete a fresh mutex and both win again. Any userspace
  # lock that must survive a crashed holder needs that reclaim. The kernel drops an
  # flock when its holder dies, so this one has none, and the mutex file is never
  # unlinked, so no path can be swapped under a holder.
  # macOS ships no flock(1), so python3 takes it (the kipi-promote.sh take_lock
  # idiom); -I keeps a review tree's own files off its import path. The PID goes in
  # by link(), so the lock file is never seen empty. An empty one can only come
  # from a pre-round-3 run mid-create, so it gets a moment before it counts as stale.
  # RE-ENTRANT for this run: review_worktree is called more than once per review.
  local wt="$1" lock="$1.lock" clear="${2:-}" dir mutex rc
  dir="$(dirname "$wt")"; mutex="$dir/.tree-lock.mutex"
  # A failed mkdir proves nothing about the tree, so it is unknown (3) and clears
  # nothing. Round 6 first called it "no directory, so no owner" and cleared the
  # ref outside any mutex; Codex showed EACCES on a parent fails mkdir while the
  # tree exists and a live run owns it, and that run's ref was deleted.
  mkdir -p "$dir" 2>/dev/null || return 3
  # THIS SHELL HOLDS THE MUTEX, on fd 8, until the verdict AND any ref cleanup are
  # done. python3 flocks the inherited fd (the kipi-promote.sh take_lock idiom),
  # and an flock lives on the open file description, so it outlasts the python
  # child and is dropped only by the close below or by this shell dying. Round 5
  # named the gap: a cleanup run after the mutex is let go lets another run claim
  # the tree in between, and the cleanup then deletes that run's fresh ref.
  # The braces matter: a bare `exec 8>>f 2>/dev/null` silences this shell's stderr
  # for the rest of the run. Children started inside this window (cat, and git in
  # _wt_bail) inherit fd 8 too; bash 3.2 cannot hide it from them. A child that
  # outlived the window would hold the mutex, and every later claim then times out
  # as unknown (3), which keeps refs, so that leak fails closed.
  [ -e "$mutex" ] || (umask 077; : >> "$mutex") 2>/dev/null
  { exec 8>>"$mutex"; } 2>/dev/null || return 3
  python3 -I - "$lock" "$$" 8 <<'PYLOCK' 2>/dev/null
import fcntl, os, sys, time
lock, me, fd = sys.argv[1], sys.argv[2], int(sys.argv[3])
# 0, BUSY and UNOWNED are the only verdicts. Every other exit, an uncaught
# exception's 1 and a signal's 128+n included, reaches the shell as unknown (3).
BUSY, UNOWNED, TIMEOUT = 20, 21, 22

def holder():
    try:
        with open(lock, encoding="ascii", errors="replace") as fh:
            return fh.read().strip()
    except FileNotFoundError:
        return None

def proven_dead(text):
    # Only ESRCH proves a PID has no process. Until round 6 ANY kill() error read
    # as dead, so a liveness check that merely failed reclaimed a live owner's lock.
    try:
        pid = int(text)
    except ValueError:
        return True   # not a PID: no writer of this file names an owner this way
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OverflowError:
        return True   # past pid_t: no process can hold it
    except PermissionError:
        return False  # another user's live process
    return False

deadline = time.monotonic() + 5
while True:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        break
    except BlockingIOError:
        # Another process is inside the mutex, which covers the whole directory,
        # so a timeout says nothing about who owns THIS tree: unknown, never busy
        # and never unowned (ASK-3930 rounds 4 and 6).
        if time.monotonic() > deadline:
            sys.exit(TIMEOUT)
        time.sleep(0.02)
h = holder()
if h == "":
    time.sleep(0.2)
    h = holder()
if h == me:
    sys.exit(0)
if h is not None and not proven_dead(h):
    sys.exit(BUSY)
# PROOF IN HAND: inside the mutex, the holder is absent or dead. Only from here
# may a failure report UNOWNED, the one verdict that lets a ref be cleared.
tmp = "%s.%s.tmp" % (lock, me)
code = UNOWNED
try:
    if h is not None:
        try:
            os.unlink(lock)
        except FileNotFoundError:
            pass
    with open(tmp, "w") as fh:
        fh.write(me)
    os.link(tmp, lock)
    code = 0
except FileExistsError:
    code = BUSY   # a pre-round-3 run created it outside the mutex
except OSError:
    pass
finally:
    # Best effort. The link decides the claim, so failing to tidy the tmp name must
    # not turn a lock this run holds into a reported failure.
    try:
        os.unlink(tmp)
    except OSError:
        pass
sys.exit(code)
PYLOCK
  rc=$?
  case "$rc" in
    0)  [ "$(cat "$lock" 2>/dev/null)" = "$$" ] || rc=3 ;;
    20) rc=2 ;;
    21) rc=1; [ "$clear" = clear-stale-ref ] && _wt_bail "$wt" ;;
    *)  rc=3 ;;
  esac
  exec 8>&-
  [ "$rc" = 0 ] && _wt_lock_path="$lock"
  return "$rc"
}
release_wt_lock() {
  [ -n "$_wt_lock_path" ] || return 0
  if [ "$(cat "$_wt_lock_path" 2>/dev/null || true)" = "$$" ]; then
    command rm -f "$_wt_lock_path" 2>/dev/null || true
  fi
  _wt_lock_path=""
}
trap 'release_wt_lock' EXIT

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
  #
  # This arm never calls _wt_bail itself (ASK-3930 round 6). acquire_wt_lock clears
  # the ref only when it has proven nobody owns the tree, and while it still holds
  # the claim mutex, so no run can claim the tree between the proof and the clear.
  # Unknown ownership leaves the ref: if it is stale, assert_pr_ref_not_stale
  # refuses this run, a refusal and never a review of the wrong commit, and the
  # next run that can lock refreshes it.
  acquire_wt_lock "$wt" clear-stale-ref
  case "$?" in
    0) : ;;
    2) echo "  WARN: another review holds $wt; leaving its ref alone and falling back." >&2
       return 1 ;;
    1) echo "  WARN: could not lock $wt, which nobody owns; its stale ref was cleared under the claim mutex." >&2
       return 1 ;;
    *) echo "  WARN: could not tell who owns $wt; leaving its ref alone and falling back." >&2
       return 1 ;;
  esac
  mkdir -p "$(dirname "$wt")" 2>/dev/null || _wt_bail "$wt" || return 1
  if [ -d "$wt/.git" ] || [ -f "$wt/.git" ]; then
    git -C "$wt" checkout --detach --force "$sha" >/dev/null 2>&1 || _wt_bail "$wt" || return 1
  else
    # DISK FLOOR (ASK-3648, PR #656 review). A NEW tree is cut from shell, so the
    # PreToolUse floor never sees it. Under the floor this bails like any failed
    # add, and the caller's documented fallback (tree search, with its WARN)
    # reviews without allocating. Re-detaching an existing tree, above, costs no
    # disk and is never refused. ${DISK_FLOOR_PY:-} is empty when a test lifts
    # this function out alone; empty or missing means proceed, as does exit 2.
    if [ -n "${DISK_FLOOR_PY:-}" ] && [ -f "$DISK_FLOOR_PY" ]; then
      local floor_line
      floor_line="$(python3 "$DISK_FLOOR_PY" --check </dev/null 2>/dev/null)"
      case "$?" in
        1) echo "  WARN: $floor_line; no new review tree for PR #$PR." >&2
           _wt_bail "$wt" || return 1
           return 1 ;;
        2) echo "  WARN: $floor_line; proceeding without the floor." >&2 ;;
      esac
    fi
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
    # UNDER THE DISK FLOOR IS THE MACHINE, NOT THE REVIEW (ASK-3648, PR #656
    # review round 2, finding 1). review_worktree refused a new tree; that runs in
    # a subshell, so the floor is read again here. Exit 9 is this script's code
    # for a machine condition (see the runner-unavailable exits below), and
    # linear-worker.sh reads 9 as env_halt: no charge, no "reviewer failed" line.
    # The fallback below would refuse anyway, with no tree at this sha, and blame
    # the clone.
    if [ -n "${DISK_FLOOR_PY:-}" ] && [ -f "$DISK_FLOOR_PY" ]; then
      FLOOR_LINE="$(python3 "$DISK_FLOOR_PY" --check </dev/null 2>/dev/null)"
      if [ "$?" -eq 1 ]; then
        echo "  ENV: $FLOOR_LINE; no review tree for PR #$PR, so no review this run. A condition of the machine (exit 9), not of the PR; the next run reviews it once space is back." >&2
        exit 9
      fi
    fi
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
# The SLUG is passed because the counter keys on it exactly as this script's
# writer does. Without it the counter globs the legacy `pr-<N>-*.md`, matches
# none of the repo-keyed files written since ASK-738, and reports round 1 on
# every run -- which is how ROUND_RULE below sat unarmed (ASK-1957).
ROUND="$(review_round "$ENGINE_DIR" "$PR" "$REVIEW_SLUG")"
echo "  round: $ROUND (engine: $ENGINE)"

# DELTA ROUNDS (ASK-3884, sp-ff374488). Founder rule 11, 2026-11-06: "option 1.
# not all changes need a full cycle review". Round 1 reads the whole PR; a later
# round reads only `git diff <last reviewed sha> <head>`. Before this the only
# flags were --issue, --engine, --repo and --post, so every round re-read the
# whole PR, and on 4 Points PR #23 the delta round had to go to a separate agent
# that could not post kipi/reviewer-approved.
#
# Every doubtful case falls back to a FULL read, never to a smaller one: a full
# review of a delta is wasted tokens, a delta review standing in for an unread
# change is an unearned green. So:
#   - the receipt's head_sha is a base only when that record says usable. A
#     provider blip writes a record too, and nobody read the sha it names.
#   - a base that is not an ancestor of the head (a rebase, a force-push) has no
#     meaningful delta, so the whole PR is read and the log says why.
# Two explicit-input mistakes REFUSE instead, because guessing what the caller
# meant is worse than saying no: a --base that is not a commit here, and a base
# equal to the head (nothing new; the verdict on that sha already stands).
REVIEW_BASE=""
# `--base` with no value is a caller mistake, not a request for a full review;
# reading it as one would hide the mistake behind a run that looks fine.
if [ "$BASE_FLAG" = "1" ] && [ -z "$REVIEW_BASE_ARG" ]; then
  echo "REFUSING: --base needs a sha. No review ran; no verdict posted." >&2
  exit 1
fi
if [ -n "$REVIEW_BASE_ARG" ]; then
  REVIEW_BASE="$(git -C "$REVIEW_REPO" rev-parse --verify --quiet "${REVIEW_BASE_ARG}^{commit}" 2>/dev/null || true)"
  if [ -z "$REVIEW_BASE" ]; then
    echo "REFUSING: --base $REVIEW_BASE_ARG is not a commit in $REVIEW_REPO. No review ran; no verdict posted." >&2
    exit 1
  fi
  BASE_SOURCE="--base"
elif [ "$DELTA" = "1" ]; then
  _rec="$(verdict_record_path "$VERDICT_DIR" "$REVIEW_SLUG" "$PR")"
  _usable="$(python3 -c 'import json,sys
try: print("1" if json.load(open(sys.argv[1])).get("usable") is True else "0")
except Exception: print("0")' "$_rec" 2>/dev/null || echo 0)"
  _prev="$(head_sha_from_record "$_rec")"
  if [ "$_usable" = "1" ] && [ -n "$_prev" ]; then
    REVIEW_BASE="$(git -C "$REVIEW_REPO" rev-parse --verify --quiet "${_prev}^{commit}" 2>/dev/null || true)"
    [ -n "$REVIEW_BASE" ] || echo "  WARN: delta: last reviewed sha ${_prev:0:12} is not in $REVIEW_REPO; reading the whole PR." >&2
  else
    echo "  delta: no usable earlier review of PR #$PR on record; reading the whole PR (round 1)."
  fi
  BASE_SOURCE="this engine's verdict record"
fi
if [ -n "$REVIEW_BASE" ]; then
  if [ "$REVIEW_BASE" = "$HEAD_SHA" ]; then
    echo "REFUSING: nothing to review since ${REVIEW_BASE:0:12}, which is the head of PR #$PR. The verdict on that sha stands. No review ran; no verdict posted." >&2
    exit 1
  fi
  if [ -z "$HEAD_SHA" ] || ! git -C "$REVIEW_REPO" merge-base --is-ancestor "$REVIEW_BASE" "$HEAD_SHA" 2>/dev/null; then
    echo "  WARN: delta base ${REVIEW_BASE:0:12} is not an ancestor of head ${HEAD_SHA:0:12} (rebase or force-push?); reading the whole PR." >&2
    REVIEW_BASE=""
  elif git -C "$REVIEW_REPO" diff --quiet "$REVIEW_BASE" "$HEAD_SHA" 2>/dev/null; then
    # An EMPTY delta: a new sha whose tree equals the reviewed one (an empty
    # commit to re-trigger CI, a revert and reapply). The sha check above lets it
    # through, and the first cut handed the engine a 0-byte diff and posted green
    # on the head (PR #619 review round 2, major, repro'd). A round that reads
    # nothing must not move the gate. A full review (no flag) is the way to put a
    # verdict on this head.
    echo "REFUSING: nothing to review: the tree at head ${HEAD_SHA:0:12} is identical to the tree at ${REVIEW_BASE:0:12}. No review ran; no verdict posted. Run without --delta/--base for a full review of this head." >&2
    exit 1
  else
    echo "  delta: reviewing only ${REVIEW_BASE:0:12}..${HEAD_SHA:0:12} (base from $BASE_SOURCE)"
  fi
fi

# A repeat review must not re-litigate. Fresh eyes on the CODE is the point;
# fresh eyes on the ARGUMENT is how a PR grinds forever (PR #11 reached round 4
# with findings still arriving). So from round 2 on, the reviewer is told the
# round and is required to re-prove any finding it wants to raise again.
# FETCH THE PR FRESH, OUTSIDE THE SANDBOX (2026-10-13). The reviewer is offline
# on purpose (CODEX_SANDBOX), so the script reads GitHub at review start and the
# prompt points at these files. A failed fetch is the machine's failure, not a
# review: exit 9, no status posted (absent is not approved).
SCRATCH_BASE="${KIPI_REVIEW_SCRATCH_BASE:-$HOME/.config/kipi/review-scratch}"
PR_CONTEXT_DIR="$(mkdir -p "$SCRATCH_BASE" && mktemp -d "$SCRATCH_BASE/ctx.XXXXXX")" || {
  echo "REFUSING: cannot create a PR context dir under $SCRATCH_BASE. No review ran; no verdict posted." >&2
  exit 4; }
# A delta round's pr.diff is the local `git diff <base> <head>`; both shas were
# proven present and ordered above. The PR view is still fetched, so the PR's
# title, body and state come from GitHub either way.
fetch_pr_diff() {
  if [ -n "$REVIEW_BASE" ]; then
    git -C "$REVIEW_REPO" diff "$REVIEW_BASE" "$HEAD_SHA"
  else
    gh pr diff "$PR" $KIPI_GH_REPO_ARGS
  fi
}
if ! gh pr view "$PR" $KIPI_GH_REPO_ARGS > "$PR_CONTEXT_DIR/pr.txt" 2>"$PR_CONTEXT_DIR/err" \
   || ! fetch_pr_diff > "$PR_CONTEXT_DIR/pr.diff" 2>>"$PR_CONTEXT_DIR/err"; then
  echo "$(TS) could not fetch PR #$PR from GitHub ($(head -c 200 "$PR_CONTEXT_DIR/err")); no review, no status. Exit 9." >&2
  command rm -rf -- "$PR_CONTEXT_DIR"   # the EXIT trap is not installed yet
  exit 9
fi
# THE REVIEWER'S MODEL, BY THE PR'S CLASS (ASK-4013). The WHOLE PR's file list,
# not pr.diff: a delta round's diff holds only the new commits, and a test-only
# delta on a dispatcher PR is still a dispatcher review. A failed list leaves the
# class unknown, which the table routes to Opus.
gh pr diff "$PR" $KIPI_GH_REPO_ARGS --name-only > "$PR_CONTEXT_DIR/pr.files" 2>>"$PR_CONTEXT_DIR/err" || : > "$PR_CONTEXT_DIR/pr.files"
_ROUTED="$(python3 "$SCRIPT_DIR/model_route.py" pick --job review --files-from "$PR_CONTEXT_DIR/pr.files" --repo "$REVIEW_SLUG" --tree "$REVIEW_REPO" 2>>"$PR_CONTEXT_DIR/err")"
[ -n "$_ROUTED" ] && CLAUDE_MODEL="$_ROUTED"
if [ "$ROUND" -gt 1 ]; then
  gh pr view "$PR" $KIPI_GH_REPO_ARGS --comments > "$PR_CONTEXT_DIR/comments.txt" 2>/dev/null || true
  # A PUBLIC PR CARRIES ONLY COUNTS (ASK-2893, the post block below), so the
  # earlier rounds' findings are not in its comments any more. Without this the
  # round rule below points the reviewer at a file with no findings in it, and
  # the anti-re-litigation rule has nothing to apply to. The findings come from
  # the review files on this machine, through findings_block, the one reader.
  # The header goes down only over at least one usable round (PR #557 round 1,
  # minor): a header with nothing under it says earlier findings exist and then
  # shows none.
  if [ "$(repo_visibility "$REVIEW_SLUG")" != "PRIVATE" ]; then
    _EARLIER=""
    for _f in $(review_md_glob "$ENGINE_DIR" "$REVIEW_SLUG" "$PR"); do
      [ -f "$_f" ] && review_is_usable "$_f" || continue
      _EARLIER="$_EARLIER
$(basename "$_f")
$(findings_block "$_f")
"
    done
    [ -z "$_EARLIER" ] || printf '\n\n--- Earlier rounds of this review, from the review files on this machine. The repository is public, so they are not in the PR comments above. ---\n%s' \
      "$_EARLIER" >> "$PR_CONTEXT_DIR/comments.txt"
  fi
fi

ROUND_RULE=""
if [ "$ROUND" -gt 1 ]; then
  ROUND_RULE="

## THIS IS REVIEW ROUND $ROUND OF THIS PR

Earlier rounds are in the PR comments, fetched for you: $PR_CONTEXT_DIR/comments.txt. Read them
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

# The delta round's instructions. Empty on a full review, so the full-review
# prompt stays byte-identical to what every earlier round was given.
DELTA_RULE=""
PR_DIFF_LABEL="(gh ${GH_R_PROMPT}pr diff $PR)"
if [ -n "$REVIEW_BASE" ]; then
  PR_DIFF_LABEL="(git diff ${REVIEW_BASE:0:12} ${HEAD_SHA:0:12}: ONLY the commits since the last reviewed round)"
  DELTA_RULE="

## THIS IS A DELTA ROUND

An earlier round of this review read this PR up to commit ${REVIEW_BASE:0:12}. Rounds
after the first read only what changed since the last reviewed sha (founder rule,
2026-11-06), so pr.diff below holds \`git diff ${REVIEW_BASE:0:12} ${HEAD_SHA:0:12}\`, not the
whole PR. Review that delta. Code outside it was reviewed already: raise a finding
there only when the delta changes how that code behaves, and say how. An earlier
blocking finding counts as fixed only if the tree at the head shows it fixed, and
the whole tree at the head is in front of you to check that."
fi

PROMPT="You are a SENIOR STAFF ENGINEER at Meta. You have NEVER seen this codebase before.
You were asked to review pull request #$PR in $REVIEW_ROOT, and you are ADVERSARIAL by default:
your job is to find what is wrong, not to be agreeable.$ROUND_RULE$DELTA_RULE

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

The PR was fetched from GitHub when this review started. Under codex the
sandbox is read-only with no network (CODEX_SANDBOX in pr-review-agent.sh), so
gh cannot reach GitHub there. The fetched copies:

  $PR_CONTEXT_DIR/pr.txt     (gh ${GH_R_PROMPT}pr view $PR)
  $PR_CONTEXT_DIR/pr.diff    $PR_DIFF_LABEL

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
  halfway? What does Sana's alert triage see?

## The operational bar (this is the Meta staff part)

This fleet runs UNATTENDED agents on a schedule, against Linear objects that CANNOT
BE DELETED, in a PUBLIC repo. So judge it that way:
- What happens at 3am when this fires and nobody is watching?
- What is the blast radius of it being wrong? What is permanent and unrecoverable?
- What pages a human, and is that signal or noise? A checker that cries wolf trains
  the alert triage to ignore it, which costs the real alert later.
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
- **major** — wrong behavior unattended that leaves a cleanup behind, and the cleanup
  is possible. Files duplicate permanent issues. Cries wolf on every run (a checker the
  alert triage learns to ignore costs the real alert later, which is why false alarms
  rank here and not below). Reports success for work that did not happen.
- **minor** — real, reproducible, and bounded. Log or help text that misstates
  what the code does. A narrow false negative on an input shape nobody hits yet.
  A docstring that contradicts the code. It should be fixed; it does not gate.
- **nit** — style, naming, formatting, preference. Never gates anything.

Two calibration checks before you assign a severity:
1. If you cannot name what has to be DONE about it at 3am, it is not a blocker
   or a major.
2. If your reproducer only fails under inputs you had to construct and no producer
   in this repo emits, drop the severity a level and say so.

Inflating a minor to a major to make a review feel substantial is itself a defect:
it wedges a PR that should have shipped, and it burns the author's next round on
work that did not need doing.

## THE STANDING RULE — non-negotiable

EVERY finding MUST ship a RUNNABLE REPRODUCER that you ACTUALLY RAN, with its real
output pasted. A finding with no executed repro is an opinion and will be rejected.
Write repros to \$TMPDIR and run them. Need a copy of the tree to mutate? Use
\`git worktree add --detach \"\$TMPDIR/copy\" HEAD\` from the tree you are in. Never
\`git clone\`, and never write outside \$TMPDIR: it is deleted when you finish, and
a copy anywhere else outlives the review and fills the disk. If you cannot make it fail, DROP the finding
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
    - EXCEPT a major you mark nonblocking (below): it does not gate, it is a
      follow-up. Mark a major nonblocking when you would say it is not a blocker
      for THIS merge, or when it only bites in code the PR states is report-only,
      dry-run or not yet enforced. Never mark a blocker; a blocker always blocks.
    - only minor/nit findings, or majors all marked nonblocking => APPROVE WITH NITS
    - no finding survived reproduction  => APPROVE
  A bar this high ALWAYS finds something; that is what APPROVE WITH NITS is for.
  On APPROVE WITH NITS the pipeline names every minor in the run log and files
  every nonblocking major to the spillover ledger as a tracked follow-up with a
  Linear issue, so approving with nits does NOT lose them. Using REQUEST CHANGES
  to log minors wedges the PR forever and is itself a review defect.
  State the verdict and the single most important thing to fix first.
- **Last, a machine-readable findings block**, EXACTLY this shape, one line per
  finding, empty block if none. The pipeline parses it; keep prose out of it.
  To mark a major nonblocking, end its line with the word nonblocking after
  file:line (the mark is the trailing |nonblocking, nothing else):

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
#
# ONE SCRATCH DIR PER RUN, REMOVED ON EXIT (2026-10-01). The Opus fallback built
# its reproducers in /tmp/pr16head (a 1.4G worktree) and /tmp/pr16rev (a 1.8G FULL
# clone) on cole-gtm PR #16, kept them across rounds, and filled the disk mid-review:
# the verdict came back empty and posted kipi/reviewer-approved=failure on a sha
# nothing had found fault with. So the engine gets $TMPDIR pointed at a dir this
# script owns and deletes, any worktree the model cut from the review tree is
# pruned with it, and the claude engine cannot run `git clone` at all.
REVIEW_SCRATCH=""
SCRATCH_BASE="${KIPI_REVIEW_SCRATCH_BASE:-$HOME/.config/kipi/review-scratch}"
WT_BEFORE=""
# Worktrees of the review repo as "<path> <sha> <detached>" lines.
_wt_rows() {
  git -C "$REVIEW_REPO" worktree list --porcelain 2>/dev/null | awk '
    /^worktree /{p=substr($0,10); h=""; d=0}
    /^HEAD /{h=$2}
    /^detached/{d=1}
    /^$/{if(p!="")print p" "h" "d; p=""}
    END{if(p!="")print p" "h" "d}'
}
review_scratch_cleanup() {
  # Empty would make "$own"/* read as /*, claiming every path: use a sentinel.
  local own="${REVIEW_SCRATCH:-/nonexistent-review-scratch}"
  # git lists PHYSICAL paths (macOS: /var/folders is /private/var/folders), so
  # both prefixes are resolved the same way before any comparison.
  local own_p base_p
  own_p="$(cd "$own" 2>/dev/null && pwd -P)" || own_p="$own"
  base_p="$(cd "$SCRATCH_BASE" 2>/dev/null && pwd -P)" || base_p="$SCRATCH_BASE"
  case "$REVIEW_SCRATCH" in
    "$SCRATCH_BASE"/run.*) command rm -rf -- "$REVIEW_SCRATCH" 2>/dev/null || true ;;
  esac
  case "${PR_CONTEXT_DIR:-}" in
    "$SCRATCH_BASE"/ctx.*) command rm -rf -- "$PR_CONTEXT_DIR" 2>/dev/null || true ;;
  esac
  REVIEW_SCRATCH=""
  # ONLY THIS RUN'S OWN DIR IS DELETED; everything else new is REPORTED.
  # PR #495 took four rounds to rule out each wrong owner of a worktree found by
  # location: a base-revision copy (round 2), a concurrent review's scratch
  # (round 3), verify.sh's mktemp -d snapshot (round 4). Nothing outside our own
  # dir can be proven ours, so nothing outside it is removed. A new worktree
  # under a temp root (the scar's /tmp/pr16head shape) is printed with its size,
  # so a run that ignored the prompt's $TMPDIR rule is visible, not silent.
  if [ -n "$WT_BEFORE" ]; then
    _wt_rows | while read -r path sha det; do
      grep -qxF "$path" <<<"$WT_BEFORE" && continue
      case "$path" in
        "$own"/*|"$own_p"/*) git -C "$REVIEW_REPO" worktree remove --force "$path" 2>/dev/null || true ;;
        "$SCRATCH_BASE"/*|"$base_p"/*|*/review-trees/*) ;;
        /tmp/*|/private/tmp/*|/var/folders/*|/private/var/folders/*)
          echo "  WARN: a worktree appeared at $path during this review ($(du -sh "$path" 2>/dev/null | cut -f1)); not removed, its owner cannot be proven. If it is this engine's, it broke the \$TMPDIR rule." >&2 ;;
      esac
    done
  fi
  git -C "$REVIEW_REPO" worktree prune 2>/dev/null || true
}
trap 'release_wt_lock; review_scratch_cleanup' EXIT

# Reap scratch a SIGKILLed run left behind: the EXIT trap does not fire on
# SIGKILL, and nothing else deletes under SCRATCH_BASE (PR #495 review).
for _old in "$SCRATCH_BASE"/run.* "$SCRATCH_BASE"/ctx.*; do
  [ -d "$_old" ] || continue
  [ -n "$(find "$_old" -maxdepth 0 -mmin +720 2>/dev/null)" ] && command rm -rf -- "$_old"
done

# reap-merged-trees-begin
# REVIEW TREES OF MERGED OR CLOSED PRs ARE REMOVED AT THE START OF EVERY RUN (ASK-3506).
# review_worktree keeps one detached tree per (repo, PR) and nothing ever removed
# one. Measured 2026-10-30: 22 merged consulting PRs each held a 450-500 MB tree
# (12 GB) and the disk fell to 313 MiB free, which is also how a review dies
# mid-run with an empty verdict. Only trees whose key this repo's own
# review_tree_path would produce are candidates, so another repo's tree is never
# named. FAIL CLOSED: a gh error, an OPEN state, the PR under review, or a live
# lock holder all leave the tree alone, because a wrongly kept tree costs disk
# and a wrongly removed one costs a live review its evidence.
# Temp worktrees under $TMPDIR/tmp.*/wt are only REPORTED: no marker proves which
# run made them (the PR #495 lesson recorded in review_scratch_cleanup above).

# ASK-3930: keep a finished review tree's unique files before the tree goes.
# Args: tree path, PR number, list file (NUL-separated untracked paths that are NOT
# byte-identical to the main checkout copy), 1 when tracked files differ from HEAD,
# and the number of list records the caller counted on its own: a list cut short
# (a full TMPDIR mid-append drops the last record) is caught by that count, not
# trusted. Tracked changes go in as TWO binary patches, the index against HEAD and
# the worktree against the index, so a staged version that differs from both ends
# survives; textconv and external diff drivers are off, because their output need
# not restore the bytes. Prints the archive path and returns 0 only when the
# archive lists back every member. Returns 2 (printing the payload in KB) over KIPI_REVIEW_ARCHIVE_MAX_KB,
# and 1 on any other failure, leaving no archive behind: the caller then KEEPS the
# tree. An untracked directory (a nested repo) is not copied, so it fails closed
# here instead of being measured as zero bytes and copied whole.
_archive_review_tree() {
  local path="$1" n="$2" list="$3" tracked="$4" expect_n="$5" name dir stage arch rel
  local bytes=0 kb want=1 got seen=0 side
  local cap="${KIPI_REVIEW_ARCHIVE_MAX_KB:-51200}"
  [ -n "$list" ] && [ -f "$list" ] || return 1
  name="${path##*/}"; dir="$HOME/.config/kipi/review-tree-archive"
  while IFS= read -r -d '' rel; do
    seen=$((seen+1))
    [ -L "$path/$rel" ] && continue
    [ -f "$path/$rel" ] || return 1
    bytes=$(( bytes + $(wc -c < "$path/$rel") )) || return 1
  done < "$list"
  [ "$seen" = "$expect_n" ] || return 1
  stage="$(mktemp -d "${TMPDIR:-/tmp}/review-archive.XXXXXX")" || return 1
  if ! mkdir -p "$stage/$name/untracked"; then command rm -rf -- "$stage"; return 1; fi
  if [ "$tracked" = 1 ]; then
    for side in staged unstaged; do
      if [ "$side" = staged ]; then set -- --cached; else set --; fi
      if ! git -C "$path" diff "$@" --binary --no-textconv --no-ext-diff --no-color \
           > "$stage/$name/$side.patch" 2>/dev/null; then
        command rm -rf -- "$stage"; return 1
      fi
      want=$((want+1)); bytes=$(( bytes + $(wc -c < "$stage/$name/$side.patch") ))
    done
  fi
  kb=$(( (bytes + 1023) / 1024 ))
  if [ "$kb" -gt "$cap" ]; then command rm -rf -- "$stage"; echo "$kb"; return 2; fi
  while IFS= read -r -d '' rel; do
    if ! { mkdir -p "$stage/$name/untracked/$(dirname "$rel")" && cp -pP "$path/$rel" "$stage/$name/untracked/$rel"; }; then
      command rm -rf -- "$stage"; return 1
    fi
    want=$((want+1))
  done < "$list"
  {
    printf 'tree: %s\npr: %s\nhead: %s\nmain_checkout: %s\narchived_utc: %s\nstatus:\n' \
      "$name" "$n" "$(git -C "$path" rev-parse HEAD 2>/dev/null)" "$REVIEW_REPO" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git -C "$path" status --porcelain=v1 -uall --no-renames 2>/dev/null | sed 's/^/  /'
  } > "$stage/$name/MANIFEST.txt"
  mkdir -p "$dir" || { command rm -rf -- "$stage"; return 1; }
  arch="$dir/$name-$(date -u +%Y%m%dT%H%M%SZ)-$$.tar.gz"
  if ! tar -czf "$arch" -C "$stage" "$name" 2>/dev/null; then
    command rm -f -- "$arch"; command rm -rf -- "$stage"; return 1
  fi
  command rm -rf -- "$stage"
  got="$(tar -tzf "$arch" 2>/dev/null </dev/null | grep -vc '/$')" || got=0
  if [ "$got" != "$want" ]; then command rm -f -- "$arch"; return 1; fi
  echo "$arch"
}

# ASK-3930: the reaper HOLDS a finished tree's lock from inventory to removal, so a
# review that starts after the holder check cannot write into a tree that is being
# archived and removed. Round 2: it claims through acquire_wt_lock itself, so there
# is ONE claim protocol and one reclaim mutex for reviews and the reaper. The
# review's own _wt_lock_path is saved and put back, so its EXIT trap still releases
# the review's tree and never one the reaper handled.
# 0 = held by this process, nonzero = another live run holds it or it could not be taken.
_reap_take_lock() {  # <tree path>
  local saved="${_wt_lock_path:-}" rc
  acquire_wt_lock "$1"; rc=$?
  _wt_lock_path="$saved"
  [ "$rc" = 0 ]
}
_reap_release_lock() {
  if [ -n "$1" ] && [ "$(cat "$1" 2>/dev/null || true)" = "$$" ]; then
    command rm -f "$1" 2>/dev/null || true
  fi
  return 0
}

reap_finished_review_trees() {
  local path sha det n state lock holder expect kept=0 gone=0 forced=0 unk=0 archived=0
  local list arch arc any unreadable tracked nondup code rel rec cwds force held="" listbad
  list="$(mktemp "${TMPDIR:-/tmp}/review-archive.list.XXXXXX" 2>/dev/null)" || list=""
  while read -r path sha det; do
    # Every `continue` below lands here, so a held lock is always given back.
    _reap_release_lock "$held"; held=""
    case "$path" in
      */review-trees/*__pr-*)
        n="${path##*__pr-}"
        case "$n" in ''|*[!0-9]*) continue ;; esac
        expect="$(review_tree_path "$HOME/.config/kipi" "$REVIEW_SLUG" "$n")"
        # basename compare: git lists PHYSICAL paths (macOS /var is /private/var).
        [ "${path##*/}" = "${expect##*/}" ] || continue
        [ "$n" = "$PR" ] && { kept=$((kept+1)); continue; }
        lock="$path.lock"; holder="$(cat "$lock" 2>/dev/null || true)"
        if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then kept=$((kept+1)); continue; fi
        state="$(gh pr view "$n" $KIPI_GH_REPO_ARGS --json state -q .state 2>/dev/null || true)"
        case "$state" in
          MERGED|CLOSED)
            # ASK-3508: `--force` below discards untracked files and removes the
            # tree under any process standing in it (PR 568 shipped without
            # either check). A merged PR is not proof the tree is idle: skip a
            # dirty tree and a tree that is a live process's cwd, say why, and
            # FAIL CLOSED when lsof is missing or the status read fails.
            # ASK-3621 (disk 98%, 2026-10-31): 22 of 36 finished consulting trees
            # (11 GB) were skipped HERE for one reason: untracked q-consult/output/rca
            # files, byte-identical to files in the repo's own main checkout, appear in
            # every tree seconds after it is created. So the dirty skip kept every
            # tree for good and the reaper above freed nothing. A tree is still dirty
            # when ANY entry is not a plain untracked file, or when an untracked file
            # is absent from or differs from the main checkout copy: that is work
            # nobody else holds. Only a provable duplicate may be removed with --force.
            # NUL records must never pass through $(...), which drops them: the
            # first cut did, saw one fused record, and removed every dirty tree.
            # The sentinel makes a failed status read keep the tree.
            # ASK-3930 (disk 99%, 2026-11-07): the dirty skip still kept 22 finished
            # trees (3.4 GB) for good, because review sessions write into their own
            # trees (.active-case, the sycophancy stamp, last-handoff.md, reproducer
            # scratch). Nothing in a review tree is anyone's only copy for long, but
            # "for long" is not proof, so a tree's unique files (the tracked diff and
            # every untracked file that is not a main-checkout duplicate) are ARCHIVED
            # and verified first, and the tree goes only when that archive lists back.
            # --no-renames keeps every record a single path.
            if ! _reap_take_lock "$path"; then
              echo "  review-tree skip: PR $n tree lock is held by another run"
              kept=$((kept+1)); continue
            fi
            held="$lock"
            force=""; any=0; unreadable=0; tracked=0; nondup=0; listbad=0
            if [ -z "$list" ] || ! : > "$list"; then listbad=1; fi
            while IFS= read -r -d '' rec; do
              [ -n "$rec" ] || continue
              any=1; code="${rec:0:2}"; rel="${rec:3}"
              if [ "$code" = '!!' ]; then unreadable=1
              elif [ "$code" != '??' ]; then tracked=1
              elif [ -f "$path/$rel" ] && [ ! -L "$path/$rel" ] && [ -f "$REVIEW_REPO/$rel" ] \
                   && cmp -s "$path/$rel" "$REVIEW_REPO/$rel"; then :
              else
                nondup=$((nondup+1))
                if [ "$listbad" = 0 ] && ! printf '%s\0' "$rel" >> "$list" 2>/dev/null; then listbad=1; fi
              fi
            done < <(git -C "$path" status --porcelain=v1 -z -uall --no-renames 2>/dev/null || printf '!!unreadable\0')
            if [ "$unreadable" = 1 ]; then
              echo "  review-tree skip: PR $n tree status is unreadable"
              kept=$((kept+1)); continue
            fi
            if ! command -v lsof >/dev/null 2>&1; then
              echo "  review-tree skip: PR $n tree kept, lsof missing so live processes cannot be ruled out"
              kept=$((kept+1)); continue
            fi
            cwds="$(lsof -d cwd -Fn 2>/dev/null || true)"
            if printf '%s\n' "$cwds" | grep -qxF "n$path" || printf '%s\n' "$cwds" | grep -qF "n$path/"; then
              echo "  review-tree skip: PR $n tree is the cwd of a live process"
              kept=$((kept+1)); continue
            fi
            if [ "$tracked" = 1 ] || [ "$nondup" -gt 0 ]; then
              if [ "$listbad" = 1 ]; then arc=1; arch=""
              else arch="$(_archive_review_tree "$path" "$n" "$list" "$tracked" "$nondup")"; arc=$?; fi
              case "$arc" in
                0) archived=$((archived+1)) ;;
                2) echo "  review-tree skip: PR $n tree holds ${arch}K unique, over the ${KIPI_REVIEW_ARCHIVE_MAX_KB:-51200}K archive cap"
                   kept=$((kept+1)); continue ;;
                *) echo "  review-tree skip: PR $n tree kept, its unique files could not be archived and verified"
                   kept=$((kept+1)); continue ;;
              esac
            fi
            [ "$any" = 1 ] && force="--force"
            if git -C "$REVIEW_REPO" worktree remove $force "$path" 2>/dev/null; then
              gone=$((gone+1)); [ -n "$force" ] && forced=$((forced+1)); command rm -f "$lock" 2>/dev/null || true
              held=""
            else kept=$((kept+1)); fi ;;
          *) kept=$((kept+1)) ;;
        esac ;;
      /tmp/*/wt|/private/tmp/*/wt|/var/folders/*/tmp.*/wt|/private/var/folders/*/tmp.*/wt) unk=$((unk+1)) ;;
    esac
  done < <(_wt_rows)
  _reap_release_lock "$held"; held=""
  git -C "$REVIEW_REPO" worktree prune 2>/dev/null || true
  [ -n "$list" ] && command rm -f -- "$list"
  # ASK-3630 minor: say how many trees were force-removed. ASK-3930: and how many had
  # their unique files archived first, and where.
  echo "  review-tree cleanup: removed $gone finished ($forced of them force-removed; $archived archived to $HOME/.config/kipi/review-tree-archive first), kept $kept; $unk temp tree(s) of unproven owner left alone"
}
# reap-merged-trees-end
reap_finished_review_trees

# codex-sandbox-begin
# THE SCRIPT READS GITHUB FOR THE REVIEWER. A reviewer with network AND a
# logged-in gh, reading a PR author's diff, can be talked into posting
# kipi/reviewer-approved=success or running gh pr merge itself (independent
# review of this change, 2026-10-13). The PR is fetched FRESH at review start
# into PR_CONTEXT_DIR, which the prompt points at. codex runs read-only, which
# also means offline. The claude engine keeps its network; run_engine blocks the
# direct `gh` and `curl` Bash calls, which is NOT containment: python3 (allowed
# in user settings) can still shell out to gh, WebFetch is open, and claude runs
# inside the PR's worktree so it loads that PR's own .claude/settings.json.
# Follow-up ASK-2648: no gh token in the claude engine's environment, or no Bash.
CODEX_SANDBOX="-s read-only"
# codex-sandbox-end
run_engine() {   # run_engine <claude|codex> <destination-file> [codex-account]
  if [ -z "$REVIEW_SCRATCH" ]; then
    WT_BEFORE="$(_wt_rows | cut -d' ' -f1)"
    # A full disk is not "codex is down" (PR #495 review): stop here, named,
    # rather than return 1 into the codex branch, which pages a wrong cause.
    REVIEW_SCRATCH="$(mkdir -p "$SCRATCH_BASE" && mktemp -d "$SCRATCH_BASE/run.XXXXXX")" || {
      echo "REFUSING: cannot create a review scratch dir under $SCRATCH_BASE (disk full?). No review ran; no verdict posted." >&2
      exit 4; }
  fi
  export TMPDIR="$REVIEW_SCRATCH"
  case "$1" in
    # KIPI_BLOCKED_CLAIM_LINT_MODE=advisory (ASK-459): the reviewer's FINAL text is
    # its verdict and the FINDINGS block this script parses. A Stop hook that exits 2
    # forces one more turn, and that turn's text replaces the verdict. Measured on a
    # week of real transcripts: reviewer verdicts say "does not exist" routinely
    # ("cites a backstop that does not exist"). The lint still logs them advisory.
    # `env -u ANTHROPIC_API_KEY` at the call, not a top-of-file unset a later source
    # could undo: subscription only, never the billed API (ASK-2176, test-subscription-only.sh).
    claude) KIPI_BLOCKED_CLAIM_LINT_MODE=advisory run_bounded "$TIMEOUT_SECONDS" bash -c \
              "cd '$REVIEW_ROOT' && env -u ANTHROPIC_API_KEY claude -p --model '$CLAUDE_MODEL' \"\$1\" --disallowedTools 'Bash(git clone:*)' 'Bash(gh:*)' 'Bash(curl:*)' </dev/null > '$2' 2>&1" _ "$PROMPT" ;;
    # THE INVOCATION IS BUILT BY THE RESOLVER, NOT TYPED HERE (ASK-3831). $3 is
    # the account; reviewer_codex_cmd returns the base command for it, pinning
    # CODEX_HOME for the second account and nothing for the primary. It REFUSES
    # an account it does not recognise, and that refusal must not become a run
    # on the primary login -- a review recorded against an account that never
    # saw the code is the sp-8379cd52 false-provenance shape.
    codex)  CODEX_BASE="$(reviewer_codex_cmd "${3:-$REVIEWER_PRIMARY_ACCOUNT}")" || {
              echo "$(TS) REFUSING: no codex invocation for account '${3:-}'. No review ran." >&2
              return 1; }
            run_bounded "$TIMEOUT_SECONDS" bash -c \
              "$CODEX_BASE --ignore-user-config --skip-git-repo-check $CODEX_SANDBOX --model '$CODEX_MODEL' -C '$REVIEW_ROOT' \"\$1\" </dev/null > '$2' 2>&1" _ "$PROMPT" ;;
  esac
}

# THE REVIEWER READS GITHUB THROUGH THE SCRIPT (founder-directed 2026-10-13:
# "it should still read. That is the only way to stay updated"). With no -s flag
# codex ran in its default read-only sandbox, which has NO NETWORK: every
# `gh pr view/diff` it tried since the first codex review on 2026-07-29 failed.
# The fix is not to give the reviewer the network (see CODEX_SANDBOX above); it
# is fetch_pr_context, which reads the PR from GitHub when the review starts.
#
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
    elif is_environmental "$(cat "$REVIEW" 2>/dev/null)"; then
      # THE RUNNER REFUSED, NOT THE REVIEW (PR #421 round 16, minor). A limit
      # line exits 0 and has no FINDINGS block, so it read as an unusable review
      # and converge paged "review produced no verdict", blaming the review for a
      # machine outage. Exit 9, the machine's code: no status is posted (absent
      # is not approved), and the worker marks env_halt for converge.
      echo "$(TS) the $ENGINE reviewer's runner is unavailable ($(environmental_reason "$(cat "$REVIEW")")); no review, no status. Exit 9." >&2
      exit 9
    else
      REVIEW_UNUSABLE=1
      echo "$(TS) the $ENGINE reviewer answered with no complete FINDINGS block (empty or truncated); verdict stays UNSTATED. Output kept at: $REVIEW" >&2
    fi
  else
    rc=$?
    if is_environmental "$(cat "$REVIEW" 2>/dev/null)"; then
      echo "$(TS) the $ENGINE reviewer's runner is unavailable ($(environmental_reason "$(cat "$REVIEW")")); no review, no status. Exit 9." >&2
      exit 9
    fi
    echo "$(TS) reviewer failed or timed out (rc=$rc). Partial output: $REVIEW" >&2
    exit "$rc"
  fi
elif run_engine codex "$REVIEW" "$REVIEWER_PRIMARY_ACCOUNT"; then
  if review_is_usable "$REVIEW"; then
    note_degraded_transition 0
    reviewer_note_codex_ok "$REVIEWER_PRIMARY_ACCOUNT"
    RESOLVED_ENGINE="codex"; RESOLVED_ACCOUNT="$REVIEWER_PRIMARY_ACCOUNT"
    RESOLVED_STAMP="$(reviewer_stamp codex "$REVIEWER_ROLE")"
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
  mv -f "$REVIEW" "$REVIEW.codex-failed" 2>/dev/null || true
  # ONE HEALTH EVENT PER ACCOUNT PER DAY, not one record per PR (ASK-3831). The
  # per-PR version of this ran for seven weeks and produced 24 cap tickets while
  # no single line anywhere said the fleet was down to one reviewer.
  reviewer_note_codex_outage "$REVIEWER_PRIMARY_ACCOUNT" "exit $rc on PR #$PR"
  echo "$(TS) codex failed or timed out on the $REVIEWER_PRIMARY_ACCOUNT account (rc=$rc). Partial output: $REVIEW.codex-failed" >&2

  # THE SECOND CODEX ACCOUNT, BEFORE OPUS. This rung is the whole point of the
  # resolver: a credit outage is per-ACCOUNT, and a second logged-in account is
  # still a second lab's opinion, where Opus is not. It only exists when one is
  # configured, so with none the behaviour below is byte-for-byte the July one.
  #
  # IT IS ONLY REACHED ON AN OUTAGE, never on an unusable answer. The branch
  # above is deliberate: codex answering with nothing parseable is an attempted
  # review whose CONTENT cannot be trusted, and running another engine over it
  # would invent a verdict for a review that said nothing.
  CODEX_SECOND="$(reviewer_secondary_account)"
  SECOND_OK=0
  if [ -n "$CODEX_SECOND" ]; then
    echo "$(TS) trying codex on the '$CODEX_SECOND' account before the Opus fallback..." >&2
    if run_engine codex "$REVIEW" "$CODEX_SECOND"; then
      if review_is_usable "$REVIEW"; then
        SECOND_OK=1
      else
        # Same rule as the primary: an answer with nothing parseable is not an
        # outage of this account, so it earns no outage event. It falls through
        # to UNSTATED, which posts state=failure -- absent is not consent.
        REVIEW_UNUSABLE=1
        reviewer_note_codex_ok "$CODEX_SECOND"
        RESOLVED_ENGINE="codex"; RESOLVED_ACCOUNT="$CODEX_SECOND"
        RESOLVED_STAMP="$(reviewer_stamp codex "$REVIEWER_ROLE")"
        SECOND_OK=1
        echo "$(TS) codex on '$CODEX_SECOND' answered with no complete FINDINGS block; verdict stays UNSTATED. Output kept at: $REVIEW" >&2
      fi
    else
      src=$?
      mv -f "$REVIEW" "$REVIEW.codex-$CODEX_SECOND-failed" 2>/dev/null || true
      reviewer_note_codex_outage "$CODEX_SECOND" "exit $src on PR #$PR"
      echo "$(TS) codex also failed on the '$CODEX_SECOND' account (rc=$src)." >&2
    fi
  fi
  if [ "$SECOND_OK" = "1" ] && [ -z "$RESOLVED_ENGINE" ]; then
    note_degraded_transition 0
    reviewer_note_codex_ok "$CODEX_SECOND"
    RESOLVED_ENGINE="codex"; RESOLVED_ACCOUNT="$CODEX_SECOND"
    RESOLVED_STAMP="$(reviewer_stamp codex "$REVIEWER_ROLE")"
    echo "$(TS) review written by codex on the '$CODEX_SECOND' account (the $REVIEWER_PRIMARY_ACCOUNT account was down): $REVIEW"
    echo "  NOTE: still an independent second opinion -- NOT degraded."
  fi
  if [ "$SECOND_OK" != "1" ]; then
  # BOTH CODEX ACCOUNTS ARE OUT. If nothing filled $STATUS_CONTEXT and it were a
  # required check, every PR in the repo would wedge forever -- so the Opus
  # reviewer fills the slot, and the status says DEGRADED out loud. A SILENT
  # fallback is the real hazard: both statuses would come from one model family
  # and nobody would know the independence this engine exists to buy was lost.
  DEGRADED=1
  echo "$(TS) no codex account produced a review; running the Opus fallback so $STATUS_CONTEXT does not wedge." >&2
  note_degraded_transition 1 \
    "codex exited $rc on every configured account, so the Opus fallback filled the slot and the status is marked DEGRADED"
  if run_engine claude "$REVIEW"; then
    # THE FALLBACK GETS THE SAME PARSEABILITY BAR AS CODEX. Exiting 0 is not
    # evidence it said anything: a truncated stream leaves an unclosed FINDINGS
    # block, which derives APPROVE and would post state=success on the REQUIRED
    # context. Filling the gate with an unread approval is worse than leaving it
    # unstated, because unstated holds the PR and green releases it.
    RESOLVED_ENGINE="claude"; RESOLVED_ACCOUNT="-"
    RESOLVED_STAMP="$(reviewer_stamp claude "$REVIEWER_ROLE")"
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
fi
# THE LAST RUNG IS THE DEFAULT, never an empty string. Every branch above sets
# these, but a future branch that forgets would write a record with no engine on
# it, and a reader cannot tell "nobody recorded it" from "nobody reviewed it".
[ -n "$RESOLVED_ENGINE" ] || { RESOLVED_ENGINE="$ENGINE"; RESOLVED_STAMP="$(reviewer_stamp "$ENGINE" "$REVIEWER_ROLE" 2>/dev/null)"; }

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
# THE RESOLVED RUNG, DEFAULTED INSIDE THIS RANGE ON PURPOSE (ASK-3831).
# test-review-degraded-provenance.sh extracts this block by awk range and runs it
# in a bare subshell, so anything it reads must either be set by that test or
# default here. These default from $ENGINE and $DEGRADED, which the test already
# provides, and the dispatch chain above overrides them with what actually ran.
RESOLVED_ENGINE="${RESOLVED_ENGINE:-$ENGINE}"
[ "$DEGRADED" = "1" ] && RESOLVED_ENGINE="claude"
RESOLVED_ACCOUNT="${RESOLVED_ACCOUNT:--}"
[ "$RESOLVED_ENGINE" = "claude" ] && RESOLVED_ACCOUNT="-"
RESOLVED_STAMP="${RESOLVED_STAMP:-$RESOLVED_ENGINE-review}"
[ "$DEGRADED" = "1" ] && RESOLVED_STAMP="claude-review"
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
python3 - "$PR" "$ISSUE" "$VERDICT" "$REVIEW" "$(TS)" "$STATED_VERDICT" "$DERIVED_VERDICT" "$ROUND" "$HEAD_SHA" "$VERDICT_DIR" "$ENGINE" "$INVOKER" "$REVIEW_USABLE" "$REVIEWED_BY" "$DEGRADED" "$(verdict_record_write_path "$VERDICT_DIR" "$REVIEW_SLUG" "$PR")" "${REVIEW_BASE:-}" "$RESOLVED_ENGINE" "$RESOLVED_ACCOUNT" "$RESOLVED_STAMP" <<'PY'
import json, sys
(pr, issue, verdict, review, ts, stated, derived, rnd, head_sha, verdict_dir,
 engine, invoker, usable, reviewed_by, degraded) = sys.argv[1:16]
out = sys.argv[16]
review_base = sys.argv[17] if len(sys.argv) > 17 else ""
# ASK-3831: `engine` now names WHO ANSWERED, not which flag was passed. The old
# meaning (the flag) moves to `engine_flag`, so no reader loses it. This is the
# fix the sp-8379cd52 comment above asked for and could not make at the time:
# `reviewed_by` carried the truth in a second key while `engine` kept claiming a
# second lab had read code it never saw. Positional reads are guarded so a
# pre-ASK-3831 caller still writes a valid record.
resolved_engine = sys.argv[18] if len(sys.argv) > 18 else engine
resolved_account = sys.argv[19] if len(sys.argv) > 19 else "-"
resolved_stamp = sys.argv[20] if len(sys.argv) > 20 else ""
record = {"pr": int(pr), "issue": issue, "verdict": verdict,
           "stated": stated, "derived": derived,
           "source": "findings" if derived else "prose",
           # WHO ANSWERED (ASK-3831), resolved from the chain in
           # reviewer-resolve.sh. On a degraded round this says `claude`, where
           # before it said `codex` on a review codex never ran.
           "engine": resolved_engine,
           # WHICH FLAG THE RUN WAS ASKED FOR. Kept as its own key rather than
           # dropped: `engine_flag: codex` beside `engine: claude` IS the record
           # of the outage, and the two disagreeing is the signal.
           "engine_flag": engine,
           # Which Codex account produced it: "primary", the second account's
           # name, or "-" for the Opus stand-in, which has no account.
           "account": resolved_account,
           # codex-review | codex-adversarial | claude-review | claude-adversarial
           "stamp": resolved_stamp,
           # reviewed_by is the MODEL that produced the prose, where engine is
           # the family. Both are kept: a model id moves with the routing table.
           "reviewed_by": reviewed_by,
           "degraded": degraded == "1",
           "invoker": invoker,
           # A real boolean, not "1"/"0". A JSON string "0" is TRUTHY in every
           # consumer language here, so a truthiness read of the wrong shape
           # would call every phantom review usable -- the exact inversion this
           # key exists to prevent.
           "usable": usable == "1",
           "round": int(rnd), "review": review, "head_sha": head_sha,
           "ts": ts}
# Written ONLY on a delta round (ASK-3884): absent means this round read the
# whole PR, so every record a full review writes keeps its exact old shape.
# RECORD-ONLY, DELIBERATELY: no gate reads it. Founder rule 11 makes a delta
# approval on the head the same gate as a full one, so a reader that treated the
# two differently would be the bug. It is the audit trail of what this round
# covered, next to the status description that says the same out loud.
if review_base:
    record["review_base"] = review_base
json.dump(record, open(out, "w"), indent=2)
PY

# Severity floor, minors half: APPROVE WITH NITS is a TERMINAL state -- the loop
# stops reworking -- so a minor found here gets no second pass. On REQUEST CHANGES
# the minors ride along in the review, which is the spec for the next rework pass.
#
# THE LEDGER IS NOT THEIR ROUTE, AND THIS BLOCK USED TO PRETEND IT WAS (ASK-1921,
# claude review of PR #392, finding 1). It called `prd_runner.py spillover add`
# with no --severity. That call defaults to `minor`, and `minor` sits in
# SPILLOVER_REFUSED_SEVERITIES: "a minor is fixed in this change or rejected with a
# reason; it is never queued" (founder 2026-09-12). So it returned 2 on every run,
# the captured count was 0 BY CONSTRUCTION rather than by outage, and the alarm
# built on that zero fired on every approved PR carrying a nit. Measured: the exact
# argument list above, against the real runner, rc=2 with that refusal on stderr.
#
# Two consequences, and both are removals.
#
# 1. THE CAPTURE CALL IS GONE, not re-severitied. Filing a review minor at `medium`
#    to clear the door launders the severity the reviewer chose. no-orphan-findings.md
#    already names the only two legal ends for a NEW minor -- fixed in this change,
#    or rejected with a reason -- and the ledger is neither of them.
# 2. THE PAGE IS GONE WITH IT. An alert on a 100-percent policy refusal is the
#    cry-wolf shape: nothing is down, there is nothing to act on, and it fires on
#    every approved PR with a nit. founder-notifications.md asks for a state change,
#    once, never per-event noise. The real loss on this path already has its own page
#    further down: a review that never REACHED the issue, where the findings are
#    genuinely unreadable by anyone.
#
# WHAT IS LEFT IS THE TRUE STATEMENT. Each minor is NAMED -- claim and location --
# so the run log carries the findings and not just a tally. They also reach two
# durable places without this block's help: the review comment on the PR, and the
# FINDINGS block the reviewer posts onto the Linear issue.
#
# WHAT THIS STILL DOES NOT FIX: nobody is ASSIGNED the fix-or-reject decision that
# no-orphan-findings.md requires. Routing that is a change with real Linear inflow
# and its own blast radius, so it is captured rather than bundled here: sp-74e671a4,
# filed as ASK-1940.
# A NONBLOCKING MAJOR IS NOT A MINOR, AND THE TWO ROUTE DIFFERENTLY (ASK-2422,
# round 1 finding 2). The block above released a major from the gate and then
# handed it to the minors path, which files nothing BY POLICY and said so in a
# sentence about minors. So the one severity no-orphan-findings.md requires to be
# captured -- medium and up -- was the one severity that reached nobody, under a
# log line calling it a minor. The severity the reviewer chose decides the route:
#   minor -> named here, not queued (policy: fixed in this change or rejected)
#   major -> ledger row + Linear capture ticket for Sana, at its real severity
if [ "$VERDICT" = "APPROVE WITH NITS" ] && [ -n "$ISSUE" ]; then
  MINOR_COUNT=0
  NB_MAJOR_COUNT=0
  NB_MAJOR_CAPTURED=0
  # findings_row_parts, not `IFS='|' read`: a claim may contain a literal pipe,
  # and the positional read puts its tail in $loc (pr-verdict-lib.sh row shape).
  while IFS= read -r row; do
    [ -n "$row" ] || continue
    { read -r sev; read -r claim; read -r loc; } < <(findings_row_parts "$row")
    [ -n "$claim" ] || continue
    if [ "$sev" = "major" ]; then
      NB_MAJOR_COUNT=$((NB_MAJOR_COUNT+1))
      echo "  nonblocking major $NB_MAJOR_COUNT: $claim ($loc)" >&2
      # --severity major is the WHOLE POINT of this call and the lesson of
      # ASK-1921: the severity-less version defaulted to `minor`, which the
      # runner refuses by policy, so it returned 2 every time and the capture
      # count was zero by construction. `major` is accepted, so this call can
      # actually succeed -- and its rc means something.
      #
      # NO DoR IS PASSED ON PURPOSE. prd_runner's own note: the DoR is written by
      # the agent that CONFIRMED the finding, and a later one guesses. This
      # reviewer did not author the finding, so it files the capture ticket and
      # leaves the DoR to `spillover needs-dor`, which is Sana's drain.
      #
      # cd "$SKEL" because discover_repo_root() reads the CWD, and the reviewer's
      # CWD is the REVIEWED repo, which need not have a .prd-os/ at all.
      #
      # BEHIND THE POST GUARD, unlike everything else in this block. This call
      # files a real Linear issue, and a dry run that mutates the ledger is the
      # defect sp-8424aa32 already names against this very file. A dry run says
      # what it WOULD file and files nothing.
      if [ "$POST" != "1" ]; then
        echo "    WOULD CAPTURE (dry run): spillover add --severity major -- $claim ($loc)" >&2
      elif CAP_OUT="$( (cd "$SKEL" && python3 "$SKEL/plugins/prd-os/scripts/prd_runner.py" \
            spillover add --source "$ISSUE" --severity major \
            --desc "PR #$PR review, nonblocking major: $claim ($loc)") 2>&1 )"; then
        NB_MAJOR_CAPTURED=$((NB_MAJOR_CAPTURED+1))
        echo "    captured: $CAP_OUT" >&2
      else
        # A FAILED capture IS a state change worth paging: a released major that
        # reached no ledger and no issue is exactly the orphan the rule forbids.
        # This is not the ASK-1921 cry-wolf shape -- that alarm fired on a 100%
        # policy refusal with nothing down. This one fires only on a real failure.
        echo "    UNCAPTURED major: $claim ($loc) -- rc nonzero${CAP_OUT:+: $CAP_OUT}" >&2
        bash "$NOTIFY" "reviewer: PR #$PR released a nonblocking major on $ISSUE and the spillover capture FAILED${CAP_OUT:+ ($CAP_OUT)}. The finding is on the PR only; nothing queued it." 2>/dev/null || true
      fi
    else
      MINOR_COUNT=$((MINOR_COUNT+1))
      echo "  $sev $MINOR_COUNT: $claim ($loc)" >&2
    fi
  done <<EOF
$(extract_followup_findings "$REVIEW")
EOF
  echo "  ${MINOR_TAG}review minors on a terminal verdict: $MINOR_COUNT"
  if [ "$NB_MAJOR_COUNT" -gt 0 ]; then
    echo "  ${MINOR_TAG}nonblocking majors on a terminal verdict: $NB_MAJOR_COUNT (captured: $NB_MAJOR_CAPTURED)"
  fi
  if [ "$MINOR_COUNT" -gt 0 ]; then
    echo "  UNROUTED: the $MINOR_COUNT minor(s) above got a terminal APPROVE WITH NITS, so the rework loop stops here. The spillover ledger refuses a minor by policy -- it is fixed in this change or rejected with a reason (no-orphan-findings.md) -- so nothing files them. They are on PR #$PR and in the FINDINGS block on $ISSUE. Owner for the fix-or-reject routing: ASK-1940." >&2
  fi
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
  # A delta approval covers the commits since the base, not the whole PR; the
  # required check says so rather than reading like a full read (ASK-3884).
  [ -n "${REVIEW_BASE:-}" ] && desc="delta ${REVIEW_BASE:0:8}..${sha:0:8}: $desc"
  desc="$(printf '%.140s' "$desc")"
  # STATUS_REPO_PATH, not {owner}/{repo}: `gh api` resolves those placeholders
  # from the CWD repo and accepts no -R, so an unattended run posted
  # kipi/reviewer-approved onto the home repo for a review of another one.
  local args=(api -X POST "repos/$STATUS_REPO_PATH/statuses/$sha"
              -f "state=$state" -f "context=$context" -f "description=$desc")
  # Link only a real URL. The PR comment just above is what --post creates; when
  # that failed there is nothing to link, and a local file path is not a URL.
  case "$target" in https://*) args+=(-f "target_url=$target") ;; esac
  # WHO WRITES THE GATE (ASK-362 stage 2): reviewer_status_run is the one rule,
  # shared with receipt-carry-approval.sh's carry_post. Configured-but-empty
  # returns REVIEWER_TOKEN_REFUSED and posts nothing; an absent status holds the
  # PR, which is the safe side.
  local rc=0 err
  err="$(reviewer_status_run gh "${args[@]}" 2>&1 >/dev/null)" || rc=$?
  # :-3, not bare: a missing lib must not kill the agent under set -u at the
  # one step that writes the gate (PR #431 round 2). It then fails the post loudly.
  if [ "$rc" = "${REVIEWER_TOKEN_REFUSED:-3}" ]; then
    printf '  %s\n' "$err" >&2
    echo "  NO commit status posted on $sha" >&2
    return 0
  fi
  if [ "$rc" = 0 ]; then
    echo "  commit status posted: $context=$state on $sha"
  else
    # gh's own reason, already captured in $err: an expired reviewer token and a
    # network blip need different fixes, and "NO gate moved" alone names neither
    # (PR #431 review nit).
    echo "  WARN: could not post commit status '$context' (state=$state) on sha $sha; the review is recorded but NO gate moved. gh: $(printf '%s' "${err:-printed no reason}" | tr '\n' ' ' | cut -c1-300)" >&2
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
  # A PUBLIC REPO GETS COUNTS, NEVER THE REVIEW (ASK-2893). The rendered review
  # below replays the diff, and on public kipi-system that put 188 term-carrying
  # comments on public PRs; a scrub PR leaked the terms it was removing. Asked
  # HERE, at post time, not once at the top of the run: a review takes minutes,
  # and a stale PRIVATE is the one answer that leaks. repo_visibility fails
  # closed, so a lookup that errors posts the summary. The commit status below
  # is untouched either way: the gate must not depend on what the comment may say.
  REPO_VISIBILITY="$(repo_visibility "$REVIEW_SLUG")"
  # POST_FILE is what gh sends; REVIEW_BODY is only ever a file WE created. Keeping
  # them separate is what makes the degraded path safe: with no temp file we post
  # the raw review unchanged and write nothing, instead of redirecting into the
  # artifact we are trying to read.
  if [ "$REPO_VISIBILITY" != "PRIVATE" ]; then
    # Never the raw-review fallback here: with no temp file a public repo gets no
    # comment at all, and the status still lands.
    POST_FILE=""
    if [ -n "$REVIEW_BODY" ]; then
      review_public_body "$REVIEW" "$VERDICT" "$ENGINE" "$DEGRADED" \
        "$SCRIPT_DIR/client-name-guard.py" >"$REVIEW_BODY"
      POST_FILE="$REVIEW_BODY"
      echo "  public repo (${REVIEW_SLUG:-slug unresolved}): posting the verdict and finding counts only; the review stays at $REVIEW"
    else
      echo "  WARN: public repo and no temp file for the summary; posting NO comment (the raw review never goes on a public PR)" >&2
    fi
  elif [ -n "$REVIEW_BODY" ]; then
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
  if [ -z "$POST_FILE" ]; then
    COMMENT_URL=""
  elif COMMENT_URL="$(gh pr comment "$PR" $KIPI_GH_REPO_ARGS --body-file "$POST_FILE" 2>"$COMMENT_ERR")"; then
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

echo "$(TS) done$DRY_NOTE"
exit 0
