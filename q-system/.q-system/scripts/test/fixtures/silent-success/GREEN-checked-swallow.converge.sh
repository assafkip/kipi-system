#!/usr/bin/env bash
# Drive one Linear issue to an APPROVED PR: dispatch Sana, review, repeat.
#
# WHY THIS EXISTS
# ---------------
# `linear-worker.sh` runs exactly ONE round: work, then review, then stop. So
# every subsequent round needed a human to type `kipi work --apply --issue X`
# again. That put a person in the loop for the one thing the loop was built to
# remove, and on PR #11 it meant four hand-dispatched rounds across an evening.
# Sana is a robot. She does not need a human to tell her to keep going.
#
# WHAT IT IS NOT
# --------------
# Not a scheduler. This is a foreground driver for ONE issue with a hard round
# cap. It never merges, never closes an issue, and inherits every refusal in
# linear-worker.sh because it drives that script rather than reimplementing it.
#
# EXITS (audited against .claude/rules/loop-exits.md)
#   1 goal met        -> verdict record reads APPROVE / APPROVE WITH NITS
#   2 turn cap        -> MAX_ROUNDS (default 4), the ceiling on rounds
#   5 no progress     -> same verdict AND no new commit on the branch two rounds
#                        running: the rework is not moving, stop burning rounds
#   7 error threshold -> no PR, or a review that produced no verdict
#   4 wall clock      -> inherited: each round is bounded inside the worker
#                        (1800s work) and the reviewer (2400s review)
#
# Usage: converge.sh --issue ASK-150 [--max-rounds 4] [--dry]
#
# THE BRACE AROUND EVERYTHING BELOW IS LOAD-BEARING (ASK-351). Do not remove it,
# and do not "clean up" the bare `}` on the last line.
#
# bash does not load a script into memory. It reads a chunk, executes ONE command,
# then lseeks back to the byte offset just past that command for the next one.
# This script runs for hours inside a repo that agents edit the whole time, so an
# edit shifts every later byte offset and bash resumes parsing mid-string. Measured
# 2026-08-03, ~/.config/kipi/converge-ASK-288.log, four completed review rounds
# thrown away at the exit:
#
#   converge.sh: line 872: of: command not found
#   converge.sh: line 872: not: command not found
#   converge.sh: line 876: syntax error near unexpected token `fi'
#
# Line 872 on disk is `fi`. `of` and `not` exist only INSIDE the quoted STALL_LOG
# strings, so no correct read can execute them, and `bash -n` passes on every
# committed version -- the file was never syntactically wrong. Commit d142466
# landed seven minutes into that run. That is the edit.
#
# bash must parse a compound command to completion before executing any of it, so
# the brace makes the whole body arrive at startup. The `exit 2` on the last line
# INSIDE the brace is the other half and is not redundant: measured, a brace wrap
# alone still dies rc=2, because bash seeks past the closing brace looking for one
# more command and re-executes leftovers from a file that has grown.
#
# Reproducer for both halves: q-system/.q-system/scripts/test/test-script-stable-under-self-edit.sh
{
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Overridable for the same reason linear-worker.sh:57 makes it overridable: the
# receipt writer below resolves a real worktree from this repo and commits into
# it, so a suite that could not point it elsewhere would write into the founder's
# live checkout and its live .prd-os/receipts.jsonl. Default is always the repo
# this script ships in.
SKEL="${KIPI_SKEL:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
# Overridable so the suite cannot page the founder. A test that Slacks "converge
# stalled" every run is exactly the cry-wolf failure this fleet keeps killing.
NOTIFY="${KIPI_NOTIFY:-$SCRIPT_DIR/slack-notify.sh}"
STATE_DIR="${KIPI_STATE_DIR:-$HOME/.config/kipi}"
REVIEWS_DIR="$STATE_DIR/pr-reviews"
LOG="$STATE_DIR/linear-worker.log"
# THE SAME LEDGER THE WORKER WRITES, AND DELIBERATELY NOT A SECOND ONE (ASK-833).
# The 3-attempt cap keys on this file. converge stops at exit-7 without the worker
# having recorded anything whenever the worker did not RUN TO COMPLETION -- the
# account's usage limit, a timeout, a SIGTERM. The worker's own "exited 0 but
# opened no PR" bump cannot cover that: it is a line inside the worker, and a
# killed worker never reaches its own lines. With no entry the cap never trips, so
# the issue is re-picked every cycle it wins the rotation, spending a budget slot
# each time and producing nothing. Measured 2026-08-15: ASK-128 stopped at exit-7
# twice in one hour and was absent from the ledger entirely; ASK-734, ASK-747 and
# ASK-833 each reached attempt 4 of a 3-attempt cap on empty branches.
ATTEMPTS="$STATE_DIR/linear-worker-attempts.json"
LEDGER="$SCRIPT_DIR/attempts-ledger.py"
attempt_count() { python3 "$LEDGER" "$ATTEMPTS" get "$1" count 0 2>/dev/null || echo 0; }
. "$SCRIPT_DIR/pr-verdict-lib.sh"
# THE ONE SLUG DERIVATION (ASK-738). gh binds to cwd and ignores every path
# variable here, so every gh call below is scoped with -R from this lib.
. "$SCRIPT_DIR/repo-slug-lib.sh"

# The worker command is injectable ONLY so the test suite can drive this loop
# against a fake that returns scripted verdicts. Testing convergence against the
# real worker would cost an hour and real model spend per case, so the loop
# logic would end up untested -- which is how a driver ships with an infinite
# loop in it. Default is always the real worker.
WORKER_CMD="${KIPI_CONVERGE_WORKER:-bash $SCRIPT_DIR/linear-worker.sh}"

ISSUE=""; MAX_ROUNDS=4; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --issue) shift; ISSUE="${1:-}" ;;
    --max-rounds) shift; MAX_ROUNDS="${1:-4}" ;;
    --dry) DRY=1 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
  shift || true
done
[ -n "$ISSUE" ] || { echo "usage: converge.sh --issue ASK-nnn [--max-rounds N] [--dry]" >&2; exit 1; }

TS() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "$(TS) converge[$ISSUE] $*" | tee -a "$LOG"; }

BRANCH="sana/$(echo "$ISSUE" | tr 'A-Z' 'a-z')"
# SCOPED TO THE REPO THE WORK IS IN, not to cwd (ASK-738). This driver runs
# from the dispatcher's cwd (the home checkout), so an unqualified `gh pr list`
# asked the HOME repo whether the TARGET's branch had a PR: after the worker
# opened one in the target, converge found none and stopped -- or worse, found
# an unrelated PR of the same branch name at home and drove rounds against it.
# KIPI_TARGET_REPO is the carrier kipi-dispatch.sh uses; it forwards only its
# own arguments to the worker, so the target crosses that boundary by
# inheritance. Derived ONCE, through the shared lib, same as the worker.
TARGET_REPO="${KIPI_TARGET_REPO:-$SKEL}"
TARGET_SLUG="$(slug_for_repo "$TARGET_REPO" "${KIPI_SLUG_REGISTRY:-$SKEL/instance-registry.json}")"
KIPI_GH_REPO_ARGS="$(gh_repo_args "$TARGET_SLUG")"
export KIPI_GH_REPO_ARGS
# shellcheck disable=SC2086
pr_for_branch() { gh pr list $KIPI_GH_REPO_ARGS --head "$BRANCH" --json number -q '.[0].number' 2>/dev/null; }
# The head sha comes from pr_head_sha in the shared lib, not a local copy of the
# same `gh pr view`: this driver and linear-worker.sh now BOTH compare it against
# the sha a review pinned, and two private readers of one input is how those two
# comparisons drift apart.

if [ "$DRY" = "1" ]; then
  PR="$(pr_for_branch)"
  V=""; [ -n "$PR" ] && V="$(verdict_from_record "$(verdict_record_path "$REVIEWS_DIR" "$TARGET_SLUG" "$PR")")"
  say "[dry] branch=$BRANCH pr=${PR:-none} verdict=${V:-none} would run up to $MAX_ROUNDS round(s)"
  exit 0
fi

# RELEASE THE CLAIM IF THIS RUN IS KILLED.
#
# linear-claim.py deliberately does NOT pid-check the claim itself (only the
# critical-section guard) -- the claiming python process exits immediately, so
# its pid is meaningless, and the claim is meant to outlive it. Correct design,
# real operational hole: a SIGKILL, a harness timeout, a laptop sleeping, or a
# ctrl-c leaves the lock held with nothing to reclaim it.
#
# Observed 2026-07-27: this driver was killed mid-run on ASK-181 and left
# `ASK-181 claimed by sana (session worker-1785159359-39569)`. Because the lock
# is still repo-root scoped until ASK-188 lands, that one dead session blocked
# EVERY issue on the board until a human released it by hand. In an unattended
# loop, "a human notices and runs release" is not a recovery path -- nobody is
# watching, which is the entire premise.
#
# The trap cannot know the worker's session token (the worker mints its own), so
# it releases by the holder RECORDED IN THE LOCK, which is what the manual fix
# does. Best-effort by design: never let cleanup failure mask the real exit code.
release_stale_claim_for_issue() {
  local held
  held="$(python3 - "$ISSUE" <<'PY' 2>/dev/null || true
import json, os, subprocess, sys
issue = sys.argv[1]
override = os.environ.get("KIPI_LINEAR_CLAIMS")
if override:
    path = override
else:
    try:
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        raise SystemExit(0)
    path = os.path.join(root, ".linear-claims.json")
try:
    rec = json.load(open(path))
except Exception:
    raise SystemExit(0)
# Only speak up for THIS issue: never release a lock another issue legitimately holds.
if rec.get("issue") == issue:
    print("%s\t%s" % (rec.get("agent", ""), rec.get("session", "")))
PY
)"
  [ -n "$held" ] || return 0
  local agent session
  agent="$(printf '%s' "$held" | cut -f1)"
  session="$(printf '%s' "$held" | cut -f2)"
  [ -n "$session" ] || return 0
  python3 "$SCRIPT_DIR/linear-claim.py" release "$ISSUE" \
    --agent "$agent" --session "$session" >/dev/null 2>&1 \
    && say "released the claim this run left on $ISSUE (holder $session)" || true
}

# Exits 128+n directly rather than re-raising the signal at itself. Re-raising is
# the tidier convention, but `kill -TERM $$` from a backgrounded run reached the
# PARENT too and killed the caller: the test suite that drives this exited 143
# with its own later cases never run. A cleanup path that can take down its
# caller is worse than an unconventional exit code.
on_interrupt() {
  local sig="$1" code="$2"
  say "INTERRUPTED by $sig -- releasing any claim so the board is not wedged"
  release_stale_claim_for_issue
  exit "$code"
}
trap 'on_interrupt TERM 143' TERM
trap 'on_interrupt INT  130' INT
trap 'on_interrupt HUP  129' HUP

# --- THE PRD-OS RECEIPT (ASK-218) -------------------------------------------
#
# WHY THIS LIVES HERE. PR #23 makes `pr-receipt-gate.py` a blocking step in the
# `validate` job -- the single required context on main -- refusing any
# `sana/ask-<n>` branch whose head no prd-os receipt covers. Nothing in the
# autonomous path wrote one: the only writer is kipi-dsse's issue_runner, reached
# through /issue-closeout, and linear-worker.sh:637 explicitly tells the agent NOT
# to run it. So the gate would have refused 100% of worker PRs the day it merged.
#
# The alternative was to tell the agent to run closeout. An agent remembering to
# do a thing is not enforcement (q-system/CLAUDE.md rule 3), and that exact
# instruction already sits in the worker saying the opposite.
#
# THE MOMENT. This driver already knows the one instant the claim becomes true: a
# terminal approving verdict recorded at the PR's CURRENT head (gate 10, which is
# sha-matched since ASK-216 -- a stale approval leaves through 40, never here).
# Writing at any earlier moment, or from any other gate, would stamp a receipt on
# code no reviewer read, and the gate would then rubber-stamp fleet-wide through
# `kipi update` exactly what it exists to refuse. One writer, one moment.
#
# WHAT IT MAY HONESTLY CLAIM. `commit_sha` is the head the verdict pinned, reused
# from the one `gh pr view` this loop already made -- never a fresh lookup, which
# could answer a different sha than the one that cleared the gate. `reviewed_at`
# is the verdict record's own timestamp. Everything else a prd-os receipt can
# carry is LEFT OUT and named on stdout rather than stamped to fill a schema:
#   verified_at        converge reads no CI, and `validate` is the job that runs
#                      this very gate -- gating the receipt on it deadlocks.
#   findings_triaged_at the reviewer captures minors to spillover; this driver
#                      never observes whether that capture landed.
#   closed_at          converge never closes an issue, by design.
# A receipt that lies is worse than a missing one: the gate then passes on a
# claim nobody made.

# receipt_tree <branch> -- the worktree checked out on that branch, or empty.
# Read from git rather than rebuilt from linear-worker.sh's path convention: a
# convention with two implementations is a convention with two meanings, and this
# one already burned ASK-210 (the gate carrying its own copy of the branch regex).
# THE TARGET REPO, NOT THE SKELETON (ASK-821). linear-worker.sh cuts the issue
# branch in the repo the work is FOR, so a cross-repo run's branch never exists in
# the skeleton's worktree list. Searching $SKEL there found nothing, the receipt
# was skipped, and the PR went green and sat with nothing proving it was reviewed.
#
# Measured on the first real cross-repo run, 2026-08-15T00:21:54Z, ASK-144 in
# a non-home dispatch repo: "no worktree under .../dispatch-checkout is on
# sana/ask-144" while the branch was sitting in THAT repo's worktrees the whole
# time. (No instance is named here on purpose: this file ships to every instance
# and validate-separation Gate 1.2 refuses a live instance name. The measurement
# is the durable part; the repo name belongs in the PR body.) Post-ASK-447 $SKEL is
# the PINNED kipi-system checkout, so this was guaranteed to miss for every
# cross-repo issue -- and it was unreachable before, because dispatch was capped
# at 1 and bound to the home repo, so no cross-repo run had ever finished.
#
# TARGET_REPO is already derived at the top of this file from KIPI_TARGET_REPO,
# the carrier kipi-dispatch.sh sets. The information was here; this line was
# reading the wrong variable.
receipt_tree() {
  git -C "$TARGET_REPO" worktree list --porcelain 2>/dev/null \
    | awk -v want="branch refs/heads/$1" \
        '/^worktree /{p=substr($0,10)} $0==want{print p; exit}'
}

# receipt_append <ledger> <issue> <sha> <verdict-record> <tree-head>
#   0 appended   3 already receipted   4 could not write   5 tree is not at <sha>
# One process reads the ledger AND decides, so there is no window where a second
# reader could disagree about whether the head is already receipted.
receipt_append() {
  python3 - "$1" "$2" "$3" "$4" "$5" <<'PY'
import json, os, re, sys
ledger, issue, sha, record, tree_head = sys.argv[1:6]
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")

def records(path):
    try:
        handle = open(path, encoding="utf-8")
    except OSError:
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue          # not a receipt; the gate agrees
            if isinstance(rec, dict):
                yield rec

# Dedup FIRST. converge is re-run by hand and by the dispatcher, and a ledger
# that grows a line per invocation is a ledger nobody can audit. Same predicate
# the gate matches on: the issue id in some string field, plus the commit.
for rec in records(ledger):
    if rec.get("commit_sha") != sha:
        continue
    if any(isinstance(v, str) and v.upper() == issue.upper() for v in rec.values()):
        print("already receipted at %s -- nothing appended" % sha[:12])
        raise SystemExit(3)

# The receipt is committed onto this tree, so the tree must BE at the sha the
# review approved. A tree a later run repositioned would carry the line onto
# another line of history, where the gate's ancestry check refuses it anyway.
if tree_head != sha:
    print("the worktree stands at %s, not the reviewed head %s -- no receipt written"
          % ((tree_head or "nothing")[:12], sha[:12]))
    raise SystemExit(5)

reviewed_at = ""
try:
    with open(record, encoding="utf-8") as handle:
        reviewed_at = json.load(handle).get("ts", "") or ""
except (OSError, ValueError):
    reviewed_at = ""

receipt = {"commit_sha": sha, "issue_id": issue}
unclaimed = [
    "verified_at (converge reads no CI, and `validate` is the job that runs this gate)",
    "findings_triaged_at (the reviewer captures minors; converge never sees whether it landed)",
    "closed_at (converge never closes an issue)",
]
if ISO.match(reviewed_at):
    receipt["reviewed_at"] = reviewed_at
    # THE ARTIFACT DECLARES ITS OWN SCOPE (round 3, finding 2 -- major). The
    # omissions above were named on STDOUT only, so the receipt itself was
    # indistinguishable from a full prd-os closeout receipt: a consumer saw
    # commit_sha + issue_id and could not tell "checked and absent" from "never
    # considered". A receipt that can be written without the work is a claim, and
    # a claim that does not say what it covers is the false green this whole
    # mechanism exists to prevent.
    #
    # `receipts` is prd-os's own nested block and the ONLY structural way to say
    # this inside the ledger's closed key allowlist (receipts-ledger-check.py,
    # which is not this PR's to edit). Writing `reviewed` and NOTHING else states
    # positively that exactly one of the three receipts is carried, so a gate
    # requiring verified / findings_triaged can refuse it on what is present
    # rather than infer scope from what is missing.
    receipt["receipts"] = {"reviewed": reviewed_at}
else:
    unclaimed.insert(0, "reviewed_at (the verdict record carries no usable timestamp)")

try:
    parent = os.path.dirname(ledger)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(ledger, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, sort_keys=True) + "\n")
except OSError as exc:
    print("could not append to the ledger: %s" % exc)
    raise SystemExit(4)

print("wrote %s at %s; left unclaimed: %s"
      % (", ".join(sorted(receipt)), sha[:12], "; ".join(unclaimed)))
PY
}

# receipt_only_ahead <tree> <sha>
#   0 when everything this tree carries beyond <sha> is the receipt ledger and
#   nothing else -- so the ONLY thing a push can add to the PR branch is a
#   receipt. Anything else is code no reviewer read.
#
# WHY A SECOND GATE ON TOP OF "did the writer get somewhere" (PR #42 review
# round 2, finding 1). receipt_append dedups on the ledger FILE (exit 3) BEFORE
# it checks the tree head, so "a receipt for this head exists" does not mean the
# tree stands where the reviewer stood. Gating only on the writer's exit code
# would still hand origin a tree carrying unreviewed source whenever a receipt
# happened to be sitting in the ledger next to it. The question that decides a
# push is not "is there a receipt" but "what does origin GAIN", and the answer
# has to be the ledger.
#
# Same shape as PR #23's own LEDGER_PREFIX allowance, deliberately: converge may
# only ever add to a reviewed head the one file that gate lets past.
receipt_only_ahead() {
  local tree="$1" sha="$2" gained
  git -C "$tree" merge-base --is-ancestor "$sha" HEAD 2>/dev/null || return 1
  gained="$(git -C "$tree" diff --name-only "$sha" HEAD 2>/dev/null)" || return 1
  [ -z "$gained" ] || [ "$gained" = ".prd-os/receipts.jsonl" ]
}

# WHY THE RECEIPT NEEDS A CHANNEL OUT OF THIS FUNCTION (PR #42 review, finding 1
# -- major). Every failure path below reports through `say`, which reaches stdout
# and the run log. The terminal report under it then paged the founder
# "auto-merge armed -- GitHub lands it, no human merge needed" whether or not a
# receipt existed, so the ONE thing that reaches a phone at 3am said the opposite
# of what `validate` was about to do. Same inversion the no-progress guard's own
# comment was written to fix ("THE PAGE HAS TO CARRY THE DRIFT, because it is the
# only thing that reaches the founder's phone").
#
# RECEIPT_MISS is the reason no receipt covers the head, empty when one does.
# RECEIPT_FIX is the command that fixes it. Both are read by the terminal page.
RECEIPT_MISS=""; RECEIPT_FIX=""

# THE RECEIPT COMMIT NEEDS AN IDENTITY OF ITS OWN, BECAUSE HEADLESS IT HAS NONE
# (ASK-218). This commit inherited whatever identity was ambient. A developer
# machine always has one -- git falls back to the passwd gecos field -- so every
# local run passed and the gap was invisible here for seven CI runs. Anywhere
# gecos is empty and $HOME carries no .gitconfig (a CI runner, a container, any
# sandboxed HOME), git resolves nothing and refuses:
#   fatal: empty ident name (for <runner@host.(none)>) not allowed
# converge then rolled the ledger line back and reported a receipt miss, so the
# PR could never satisfy PR #23's gate -- a live failure mode, not a test artifact.
# `validate.yml` already carries this exact scar for kipi-update.sh, and its fix
# (`git config --global` on the runner) cannot reach here: the suite redirects
# HOME, which is where --global writes.
#
# ONLY WHEN GIT HAS NOTHING. Gated on the probe rather than set unconditionally,
# so a receipt written on the founder's machine still carries the founder's name
# instead of being silently re-attributed to a bot.
#
# ENV, NOT `git -c`. Config loses to the environment: with GIT_COMMITTER_NAME
# exported empty, `git -c user.name=x commit` still dies with the same
# `empty ident name`. A config-level fallback would fix the runner and leave the
# exported-empty case broken, and that is the case a fixture can actually create.
RECEIPT_IDENT_NAME="kipi-converge"
RECEIPT_IDENT_EMAIL="converge@kipi.invalid"

# receipt_commit <tree> <message>
# The one place a receipt commit is authored. No --no-verify: the pre-commit
# ledger check (receipts-ledger-check.py) is what keeps this public repo's one
# allowed .jsonl to a closed key allowlist, and a receipt that has to bypass its
# own content gate is not a receipt.
receipt_commit() {
  local tree="$1" msg="$2"
  if git -C "$tree" var GIT_COMMITTER_IDENT >/dev/null 2>&1; then
    git -C "$tree" commit -q -m "$msg" -- .prd-os/receipts.jsonl 2>>"$LOG"
    return $?
  fi
  say "receipt: git resolves no committer identity in $tree (no user.name/user.email, nothing to guess from), so the receipt is authored as $RECEIPT_IDENT_NAME <$RECEIPT_IDENT_EMAIL> rather than dropping a review that did happen"
  GIT_AUTHOR_NAME="$RECEIPT_IDENT_NAME" GIT_AUTHOR_EMAIL="$RECEIPT_IDENT_EMAIL" \
  GIT_COMMITTER_NAME="$RECEIPT_IDENT_NAME" GIT_COMMITTER_EMAIL="$RECEIPT_IDENT_EMAIL" \
    git -C "$tree" commit -q -m "$msg" -- .prd-os/receipts.jsonl 2>>"$LOG"
}

# --- the guard, and the only thing that counts as delivery -------------------
#
# TWO RUNS MUST NOT INTERLEAVE INSIDE THE TRANSACTION (round 2, finding 2 --
# major). Reading the ledger, deciding it needs a line, appending, committing and
# pushing was a bare read-decide-write. Two convergence runs on one issue (a hand
# `kipi converge` next to the scheduled one) both read "no receipt", both append,
# and then contend on the same git index -- both commits can fail, both roll back,
# and origin ends with no receipt after TWO terminal approvals. sp-53b02cc4
# already records this exact shape across five sites in this fleet.
#
# mkdir IS the lock: atomic on POSIX and needing no flock, which macOS does not
# ship -- the same primitive and the same reasoning as the attempts ledger
# (attempts-ledger.py `_mutate`, wired at linear-worker.sh:464). It is NOT a new
# fourth mechanism; page_once, apply_claude_changes and the checkout self-heal
# all closed this shape the same way.
#
# It lives under STATE_DIR, not in the tree: a lock directory inside .prd-os/
# would show up as untracked next to the file being committed, and the first
# `git clean` or stray `add .` would either sweep it or commit it.
#
# NOT TAKEN BY FORCE ON TIMEOUT (round 3, finding 1 -- major). The first version
# copied attempts-ledger.py `_mutate` wholesale, including two defects that file
# is ALREADY RECORDED as having: sp-626e9452, "the lock proceeds on timeout and
# the release removes a directory it may not own". Copied here that produced a
# lock strictly WORSE than no lock: a run that timed out returned success without
# holding anything, entered the transaction anyway, and its release then deleted
# the live lock belonging to the run that did hold it -- with both believing they
# were serialized.
#
# Reusing an in-repo pattern is right; inheriting one without checking whether it
# is sound is how a known defect gets a second home. The exemplar was not
# verified before it was copied. That is what this block exists to correct.
#
# TWO INVARIANTS, both absent from the exemplar:
#   1. A timeout returns FAILURE and the caller must not enter the transaction.
#      Writing no receipt this run is recoverable -- the dispatcher re-runs and
#      receipt_confirm_origin reports the miss honestly. Two runs inside one
#      read-decide-write is not.
#   2. A release removes ONLY a lock this process owns, proven by a token it
#      wrote, never by the path alone.
#
# The lock is a FILE created under `noclobber`, not a directory: `set -C` makes
# the create O_EXCL, so the create and the ownership stamp are ONE atomic step.
# mkdir leaves a window where the directory exists carrying no owner yet, and a
# run killed inside that window leaves a lock nothing can ever attribute.
#
# Stale locks are broken on OWNER LIVENESS, not on a timer: a lock whose creating
# pid is gone is a corpse, and honouring it would block every future receipt
# forever. The token is re-read immediately before the break, so a lock that
# changed hands in between is left alone.
#
# RESIDUAL, named rather than papered over: that re-read is a narrow TOCTOU
# window, and pid reuse can make a corpse look live. Both degrade in the SAFE
# direction -- either a second run enters (which is where this PR started, and
# receipt_append's dedup plus origin confirmation make that idempotent), or this
# run writes no receipt and says so. Neither can delete a live run's lock, which
# is the property that was actually broken.
#
# Overridable ONLY so the suite can assert the contended path without a 10s
# sleep per case. Production never sets it, same posture as KIPI_SKEL.
RECEIPT_LOCK_TRIES="${KIPI_RECEIPT_LOCK_TRIES:-100}"
RECEIPT_LOCK_HELD=""
RECEIPT_LOCK_TOKEN=""

receipt_lock_take() {
  local lock="$1" i=0 seen owner
  RECEIPT_LOCK_HELD=""
  RECEIPT_LOCK_TOKEN="$$:$(date +%s):${RANDOM:-0}"
  mkdir -p "$(dirname "$lock")" 2>/dev/null || true
  while [ "$i" -lt "$RECEIPT_LOCK_TRIES" ]; do
    if ( set -C; printf '%s\n' "$RECEIPT_LOCK_TOKEN" > "$lock" ) 2>/dev/null; then
      RECEIPT_LOCK_HELD="$lock"
      return 0
    fi
    seen="$(cat "$lock" 2>/dev/null)"
    owner="${seen%%:*}"
    if [ -n "$owner" ] && ! kill -0 "$owner" 2>/dev/null \
       && [ -n "$seen" ] && [ "$seen" = "$(cat "$lock" 2>/dev/null)" ]; then
      say "receipt: breaking the receipt lock at $lock -- it was left by pid $owner, which is no longer running"
      rm -f "$lock" 2>/dev/null || true
    fi
    sleep 0.1
    i=$((i + 1))
  done
  say "receipt: another run still holds the receipt lock at $lock. NOT entering the transaction -- a run that cannot take the lock writes no receipt rather than racing the run that can."
  return 1
}

# Only ever removes a lock whose token this process wrote. A release that trusts
# the path deletes whichever run happens to hold it.
receipt_lock_drop() {
  local lock="$1"
  [ -n "$RECEIPT_LOCK_HELD" ] && [ "$RECEIPT_LOCK_HELD" = "$lock" ] || return 0
  if [ "$(cat "$lock" 2>/dev/null)" = "$RECEIPT_LOCK_TOKEN" ]; then
    rm -f "$lock" 2>/dev/null || true
  else
    say "receipt: NOT releasing $lock -- it no longer carries this run's token, so it belongs to another run now"
  fi
  RECEIPT_LOCK_HELD=""
}

# receipt_confirm_origin <tree> <sha> <record>
#
# A LOCAL COMMIT IS NOT DELIVERY (round 2, finding 1 -- major). Success used to
# be decided from the working tree: a line in the ledger FILE set receipted=1,
# and a tree that was not ahead returned success without ever asking the remote.
# So a run that died between the append and the commit left an uncommitted line,
# the next run dedup'd against that line, reported success, and told the founder
# no human was needed -- while origin carried zero receipts and `validate` would
# refuse the PR forever. The receipt exists for exactly one reader, CI, and CI
# reads the PUSHED head. Nothing in a worktree is evidence about that.
#
# So the last word belongs to origin, always, whatever happened locally.
#
# It reuses receipt_append as the PREDICATE rather than re-deriving "is this head
# receipted" out here: exit 3 is that function's own "already receipted" answer,
# so origin is judged by the identical rule that decided the append. Two readers
# of one input with different semantics is the defect this file keeps paying for.
# The probe is a throwaway copy of ORIGIN's ledger, so an append lands in a
# tempfile and changes nothing.
receipt_confirm_origin() {
  local tree="$1" sha="$2" record="$3" probe rc
  if ! git -C "$tree" fetch -q origin "$BRANCH" 2>>"$LOG"; then
    say "receipt: could not reach origin/$BRANCH to confirm the receipt landed (see $LOG), so this run claims nothing about it"
    RECEIPT_MISS="${RECEIPT_MISS:-converge could not reach origin/$BRANCH to confirm a receipt landed, so nothing here proves one did}"
    RECEIPT_FIX="${RECEIPT_FIX:-git -C $tree fetch origin $BRANCH to see why, then re-run: kipi converge --issue $ISSUE}"
    return 0
  fi
  probe="$(mktemp)"
  git -C "$tree" show "FETCH_HEAD:.prd-os/receipts.jsonl" > "$probe" 2>/dev/null || : > "$probe"
  receipt_append "$probe" "$ISSUE" "$sha" "$record" "$sha" >/dev/null 2>&1; rc=$?
  rm "$probe" 2>/dev/null || true
  if [ "$rc" = "3" ]; then
    RECEIPT_MISS=""; RECEIPT_FIX=""
    say "receipt: CONFIRMED on origin/$BRANCH -- validate reads a receipt for $ISSUE at $(printf '%.12s' "$sha")"
    return 0
  fi
  say "receipt: origin/$BRANCH carries NO receipt for $ISSUE at $(printf '%.12s' "$sha"). Whatever happened in the worktree, the head CI reads has nothing on it."
  RECEIPT_MISS="${RECEIPT_MISS:-origin/$BRANCH carries no receipt for this head, so nothing CI reads proves it was reviewed}"
  RECEIPT_FIX="${RECEIPT_FIX:-re-run: kipi converge --issue $ISSUE}"
  return 0
}

# receipt_ensure <sha> <verdict-record> <reviewed-sha> <pr>
# Best-effort by design and NEVER touches this run's exit code, exactly like the
# worker's auto-merge arm: a ledger that cannot be written is a PR a human has to
# push a receipt onto, not a converge run that should report a different outcome.
# It DOES change what the report says, which is a different thing: the exit code
# is a contract other code reads, the page is what a human reads.
receipt_ensure() {
  local sha="$1" record="$2" reviewed="$3" pr="$4" tree lock
  RECEIPT_MISS=""; RECEIPT_FIX=""
  if [ -z "$sha" ]; then
    say "receipt: no head sha to pin one to, so no receipt was written"
    RECEIPT_MISS="converge never read a head sha, so nothing could be pinned"
    RECEIPT_FIX="read the head with 'gh pr view <pr> --json headRefOid', then write a receipt for $ISSUE at it"
    return 0
  fi
  # THE REVIEW HAS TO NAME A HEAD, OR THERE IS NOTHING TO PIN A CLAIM TO (PR #42
  # review round 3, finding 1 -- major). The comment at the call site claimed
  # gate 10 is "the one state where a terminal approving verdict is pinned to the
  # sha that IS the head." rework_gate reaches 10 from three states and only one
  # of them is that: a record with no `head_sha` -- the shape of EVERY record
  # written before ASK-216, 13 of them approving on the live board including PR
  # #23's -- prints an explicit "falling back to verdict-only" NOTE and lands on
  # 10 anyway. converge printed that sentence and minted a receipt at the current
  # head regardless, so the one door the whole change is staked on shutting (a
  # receipt telling `validate` that unreviewed code was reviewed) stood open next
  # to it. Gate 40 shuts the case where the shas DISAGREE; this shuts the case
  # where there is nothing to disagree with.
  #
  # It is deliberately NOT a second sha comparison. rework_gate owns drift and is
  # the only thing that may decide it; two readers of the same input with
  # different semantics is the defect this repo keeps paying for. This asks the
  # one question that gate structurally cannot answer for the writer: did anyone
  # record WHICH commit they read.
  #
  # The fix is a re-review, not a git command, so it must not share a fix line
  # with the tree/commit/push failures below -- sending the operator to
  # `git status` for a missing field in a JSON record is a page that wastes the
  # 3am it just bought.
  if [ -z "$reviewed" ]; then
    say "receipt: the verdict record names no head_sha, so nothing compared the review to $sha -- no receipt written"
    RECEIPT_MISS="the verdict record names no head_sha (written before ASK-216), so nothing proves the review covered this head"
    RECEIPT_FIX="kipi review ${pr:-<pr>} --issue $ISSUE --post to record a verdict pinned to this head, then re-run: kipi converge --issue $ISSUE"
    return 0
  fi
  tree="$(receipt_tree "$BRANCH")"
  if [ -z "$tree" ]; then
    say "receipt: no worktree under $TARGET_REPO is on $BRANCH, so there is no tree to commit a receipt into. Write one by hand or PR #23's gate will refuse this PR."
    RECEIPT_MISS="no worktree under $TARGET_REPO is on $BRANCH, so there was no tree to commit into"
    RECEIPT_FIX="git -C $TARGET_REPO worktree add <path> $BRANCH, then write a receipt for $ISSUE at $sha and push it"
    return 0
  fi
  # Everything from the ledger read through the push is ONE transaction under one
  # lock, and origin -- not the tree it just wrote -- decides whether it worked.
  lock="$STATE_DIR/receipt-$(echo "$BRANCH" | tr '/' '-').lock"
  if receipt_lock_take "$lock"; then
    receipt_transaction "$sha" "$record" "$tree"
    receipt_lock_drop "$lock"
  else
    # A run that could not take the lock does NOT write. It still asks origin,
    # because the run that DID hold the lock has most likely just delivered the
    # receipt -- in which case there is nothing to report and confirm_origin
    # clears this miss.
    RECEIPT_MISS="another converge run held the receipt lock for $BRANCH, so this run wrote none"
    RECEIPT_FIX="let the other run finish, then re-run: kipi converge --issue $ISSUE"
  fi
  receipt_confirm_origin "$tree" "$sha" "$record"
  return 0
}

# receipt_transaction <sha> <verdict-record> <tree>
# The guarded body: read the ledger, decide, append, commit, push. Runs under the
# receipt lock and never decides its own success -- receipt_confirm_origin does
# that, from the remote. Its RECEIPT_MISS/RECEIPT_FIX lines are the local REASON
# a receipt may be missing, kept because they are more specific than "origin has
# none"; the confirm step clears them when origin proves them wrong.
receipt_transaction() {
  local sha="$1" record="$2" tree="$3" ledger head note rc backup had=0 ahead gained receipted=0
  ledger="$tree/.prd-os/receipts.jsonl"
  head="$(git -C "$tree" rev-parse HEAD 2>/dev/null)"

  backup="$(mktemp)"
  [ -f "$ledger" ] && { had=1; cp "$ledger" "$backup" 2>/dev/null || true; }
  note="$(receipt_append "$ledger" "$ISSUE" "$sha" "$record" "$head")"; rc=$?
  [ -n "$note" ] && say "receipt: $note"

  # 3 is "already receipted" -- a receipt EXISTS, so it is not a miss; the push
  # guard below still owns whether origin carries it. 4 and 5 wrote nothing, and
  # they are not the same miss: 4 is a filesystem the tree cannot write, 5 is a
  # tree parked on the wrong commit. Handing both the same fix sends the operator
  # to `git status` on a tree whose problem is where it is standing.
  # A LINE IN THE FILE IS NOT A DELIVERED RECEIPT (round 2, finding 1 -- major).
  # 3 means the ledger FILE already carries this receipt. That used to be read as
  # "done", which is true only when the line is also COMMITTED. A run killed
  # between the append and the commit leaves it uncommitted, and every retry then
  # dedup'd against it, skipped the commit, found nothing to push, and reported
  # success -- a permanent dead end that got louder the more it was retried.
  #
  # An uncommitted line is not a reason to stop, it is the work this run should
  # finish: hand it to the commit path below by treating it as a fresh append.
  # The rollback there restores the same content it started from, so a failing
  # commit is no worse off than before.
  if [ "$rc" = "3" ]; then
    if ! git -C "$tree" diff --quiet -- .prd-os/receipts.jsonl 2>/dev/null \
       || ! git -C "$tree" diff --cached --quiet -- .prd-os/receipts.jsonl 2>/dev/null; then
      say "receipt: the ledger already carries this receipt but it was never committed (a run that died mid-transaction). Finishing it now rather than dedup'ing against a line origin has never seen."
      rc=0
    else
      receipted=1
    fi
  fi
  if [ "$rc" = "4" ]; then
    RECEIPT_MISS="the ledger write was refused ($note)"
    RECEIPT_FIX="git -C $tree status, then write a receipt for $ISSUE at $sha into .prd-os/receipts.jsonl and push it"
  fi
  if [ "$rc" = "5" ]; then
    RECEIPT_MISS="$note, and converge pushed nothing from that tree"
    RECEIPT_FIX="git -C $tree log --oneline -3 to see what it is standing on, put it back on $sha, then re-run: kipi converge --issue $ISSUE"
  fi

  if [ "$rc" = "0" ]; then
    # $ISSUE in the message is what clears the commit-msg linear-issue-ref-check.
    # The commit itself goes through receipt_commit, which owns the identity
    # question -- see the scar above it.
    if git -C "$tree" add -- .prd-os/receipts.jsonl 2>>"$LOG" \
       && receipt_commit "$tree" \
            "chore(receipt): prd-os receipt for $ISSUE at $(printf '%.12s' "$sha")"; then
      say "receipt: committed onto $BRANCH in $tree"
      receipted=1
    else
      # Roll the line back. Leaving an uncommitted receipt in the tree would make
      # every later run dedup against it and skip, so the PR would carry nothing
      # while the ledger claimed it did.
      git -C "$tree" reset -q -- .prd-os/receipts.jsonl 2>/dev/null || true
      if [ "$had" = "1" ]; then cp "$backup" "$ledger" 2>/dev/null || true
      else rm -f "$ledger" 2>/dev/null || true; fi
      say "receipt: the commit was REFUSED in $tree (see $LOG) -- rolled the ledger line back rather than leave an uncommitted receipt. PR #23's gate will refuse this PR until one lands."
      RECEIPT_MISS="the receipt commit was REFUSED in $tree (see $LOG); the ledger line was rolled back"
      # A REMEDY THAT CANNOT WORK BURNS THE ONE HUMAN WHO READS IT (round 2,
      # finding 3 -- minor). This said `git commit -- .prd-os/receipts.jsonl`,
      # but the rollback two lines up already removed that line, so the operator's
      # copy-paste died with `nothing to commit` and told them the page was wrong
      # rather than the commit. There is nothing staged to rescue by hand: the
      # only thing that re-creates the line is another converge run, so send them
      # to the cause first and then to that.
      RECEIPT_FIX="read $LOG for why the commit was refused and fix that (the rolled-back line is gone, so there is nothing to commit by hand), then re-run: kipi converge --issue $ISSUE"
    fi
  fi
  rm -f "$backup" 2>/dev/null || true

  # CI reads the PUSHED head. A receipt sitting in a worktree clears nothing, so
  # the push is part of the write, not a follow-up. Guarded on being ahead so a
  # re-run on an already-pushed head makes no network call at all -- and so a
  # push that failed on an earlier run is retried on the next one.
  #
  # AN ERROR IS NOT A ZERO (PR #42 review, finding 3). This read was
  # `rev-list --count ... 2>/dev/null || echo 0`, which answered "nothing to
  # push" for a clone with no refs/remotes/origin/<branch> -- a worktree cut
  # before its first fetch of that branch. The committed receipt then never left
  # the machine, silently, and every re-run repeated the same skip, so the retry
  # the comment above promises could never happen on that tree. Unknown is not
  # zero: when rev-list cannot answer, PUSH and let git decide. `Everything
  # up-to-date` is a cheap no-op; a receipt that never reaches origin is a PR
  # `validate` refuses forever.
  # THE PUSH IS GATED ON WHAT THE WRITER DECIDED (PR #42 review round 2, finding
  # 1 -- major). It was conditioned only on `ahead`, so the writer's own refusal
  # -- exit 5, "the tree is not at the reviewed sha, no receipt written" -- fell
  # straight THROUGH into the push and delivered whatever that worktree was
  # carrying to origin/$BRANCH, with auto-merge armed on the PR. Source no
  # reviewer read, pushed by the guard that exists to stop exactly that. And the
  # line below it announced "origin now carries it" two lines after the writer
  # said it had written nothing (finding 2, same repro).
  #
  # converge's push has ONE job: put a receipt on the head CI reads. No receipt,
  # no push -- and the line that reports a push can then only ever run on a run
  # that has one, so it cannot lie.
  #
  # This buys no silence. Every path that leaves receipted=0 has already set
  # RECEIPT_MISS above, so the page still wakes a human; what stops is the WRITE,
  # not the report.
  if [ "$receipted" != "1" ]; then
    say "receipt: not pushing $BRANCH -- no receipt was written this run (see above), and converge pushes only receipts."
    return 0
  fi

  ahead="$(git -C "$tree" rev-list --count "origin/$BRANCH..HEAD" 2>>"$LOG")" || ahead=""
  if [ -z "$ahead" ]; then
    say "receipt: git could not tell whether origin/$BRANCH is behind this tree (no tracking ref for it in $tree). Pushing anyway rather than reading that as nothing to push."
  fi
  [ "$ahead" = "0" ] && return 0

  # ...AND ON WHAT THE PUSH WOULD ADD. See receipt_only_ahead: holding a receipt
  # licenses pushing THE RECEIPT, never whatever else is parked in the tree.
  if ! receipt_only_ahead "$tree" "$sha"; then
    gained="$(git -C "$tree" diff --name-only "$sha" HEAD 2>/dev/null | tr '\n' ' ')"
    say "receipt: NOT pushing $BRANCH. Beyond the reviewed head $sha this tree carries ${gained:-commits off that line of history}, which no review has read, and this PR can auto-merge. The receipt stays local."
    RECEIPT_MISS="a receipt for the head sits in $tree, but beyond the reviewed head that tree also carries ${gained:-a different line of history}, so converge would not push it"
    RECEIPT_FIX="git -C $tree log --stat $sha..HEAD to see what is in there, then push the receipt commit alone: git -C $tree push origin <receipt-sha>:refs/heads/$BRANCH"
    return 0
  fi

  if git -C "$tree" push -q origin "HEAD:refs/heads/$BRANCH" 2>>"$LOG"; then
    say "receipt: pushed -- origin/$BRANCH now carries it, so validate reads it"
  else
    say "receipt: the push to origin/$BRANCH FAILED (see $LOG). CI reads the pushed head, so the receipt reaches nothing. By hand: git -C $tree push origin $BRANCH"
    RECEIPT_MISS="the receipt is committed in $tree but the push to origin/$BRANCH FAILED (see $LOG), and CI reads the pushed head"
    RECEIPT_FIX="git -C $tree push origin $BRANCH"
  fi
  return 0
}

LAST_VERDICT=""; LAST_SHA=""; ROUND=0
while [ "$ROUND" -lt "$MAX_ROUNDS" ]; do
  ROUND=$((ROUND + 1))
  say "round $ROUND/$MAX_ROUNDS dispatching Sana"

  # One full round: work phase, then the adversarial review, both bounded inside
  # the worker. A nonzero rc is the worker's own failure handling (it already
  # bumped attempts and pinged); the verdict check below decides what to do.
  # READ THE COUNTER FIRST so the exit-7 branch below can tell "the worker
  # recorded this failure" from "nobody did" (ASK-833).
  ATT_BEFORE="$(attempt_count "$ISSUE")"
  # CLEAR THE REFUSAL MARKER FIRST so only THIS round's worker can set it. A
  # marker left behind by an earlier round (converge killed between the worker
  # setting it and the exit-7 branch reading it) would otherwise suppress a real
  # failure's attempt forever, which is the bug this file is fixing, inverted.
  # Best-effort on purpose: the safety-critical write is the bump below, and an
  # unwritable ledger is caught there with exit 8 rather than twice.
  python3 "$LEDGER" "$ATTEMPTS" clear-flag "$ISSUE" refused_no_pr >>"$LOG" 2>&1 \
    || say "note: could not clear the stale refusal marker for $ISSUE; see $LOG"
  $WORKER_CMD --apply --limit 1 --issue "$ISSUE" >>"$LOG" 2>&1
  WRC=$?

  PR="$(pr_for_branch)"
  if [ -z "$PR" ]; then
    # CHARGE THE ATTEMPT ONLY IF THE WORKER DID NOT (ASK-833). Comparing the
    # counter across the run is what makes this idempotent: the worker's own
    # "exited 0 but opened no PR" bump already moved it, and charging a second
    # one for the same round would mark a retryable issue stuck after two
    # failures instead of three -- the same starvation bug pointed the other way.
    # A refusal is NOT counted here for the same reason the worker does not count
    # it: a correctly-refused issue is labelled and left, never marked stuck.
    ATT_AFTER="$(attempt_count "$ISSUE")"
    # A REFUSAL IS A CORRECT TERMINAL OUTCOME, NOT A FAILED ATTEMPT (PR #192
    # review round 2, major). An unchanged counter cannot on its own tell "the
    # worker refused this spec" from "the worker was interrupted": both leave no
    # PR and touch nothing. Charging the first would let three CORRECT refusals
    # reach the 3-attempt cap and falsely mark the issue stuck -- the founder-queue
    # routing ASK-275 removed, re-entering from the driver instead of the worker.
    # The worker now records the refusal in the shared ledger; this reads it.
    REFUSED_MARK="$(python3 "$LEDGER" "$ATTEMPTS" get "$ISSUE" refused_no_pr "" 2>/dev/null || echo "")"
    if [ -n "$REFUSED_MARK" ] && [ "$REFUSED_MARK" != "None" ]; then
      say "$ISSUE was REFUSED by the worker and left no PR. A refusal is a correct terminal outcome, so it costs no attempt; the issue is held at its refusal label, not marked stuck."
    elif [ "$ATT_AFTER" = "$ATT_BEFORE" ]; then
      # A FAILED BUMP IS NOT A DETAIL TO SWALLOW (PR #192 review, major).
      # The first cut ended this call in `|| true`. That converts an unwritable
      # ledger into a silent success, the counter stays put, and the retry-forever
      # bug this whole change closes comes straight back -- now with a fix in
      # place that reads as working. Reproduced by the reviewer against a ledger
      # path that cannot be written: before=0 after=0 final=0, branch reported
      # success. An attempt that was not PERSISTED did not happen, so the run
      # says so and stops on its own exit code rather than blending into the
      # ordinary no-PR case that the dispatcher expects to see repeatedly.
      if ! python3 "$LEDGER" "$ATTEMPTS" bump-attempt "$ISSUE" \
           "converge stopped at exit-7: no PR on $BRANCH after round $ROUND (worker rc=$WRC, recorded nothing itself)" \
           >>"$LOG" 2>&1; then
        say "STOP exit-8: could not record the attempt in $ATTEMPTS. The 3-attempt cap keys on that file, so it cannot trip while the write fails and this issue would retry forever. Fix the ledger before re-dispatching; see $LOG"
        bash "$NOTIFY" "converge $ISSUE: attempts ledger unwritable -- the retry cap is not enforceable until it is fixed" 2>/dev/null || true
        exit 8
      fi
    fi
    say "STOP exit-7: no PR on $BRANCH after round $ROUND (worker rc=$WRC). Sana could not open one; see $LOG"
    bash "$NOTIFY" "converge $ISSUE: stopped, no PR after round $ROUND" 2>/dev/null || true
    exit 7
  fi

  VERDICT="$(verdict_from_record "$(verdict_record_path "$REVIEWS_DIR" "$TARGET_SLUG" "$PR")")"
  SHA="$(pr_head_sha "$PR")"
  REVIEWED_SHA="$(head_sha_from_record "$(verdict_record_path "$REVIEWS_DIR" "$TARGET_SLUG" "$PR")")"

  # ARGUMENT 2 IS THE MERGE STATE, and this driver still does not read it: ASK-212
  # scoped mergeability to the worker, which runs first inside every round here.
  # "" is byte-identical to the one-argument form this call used before, so the
  # merge half of the gate behaves exactly as it did.
  #
  # ARGUMENTS 3 AND 4 ARM ASK-216 (ASK-219, sp-a27722e7). That drift exit shipped
  # with NO caller passing them -- this call site was the one-argument form named
  # in its own comment -- so exit 40 could never fire. Observed live 2026-07-28:
  # an approval recorded at bf641ad and a head of c063c3d converged in three
  # seconds as "waiting on founder merge only". The reviewed sha comes from the
  # record the reviewer wrote; the current head is the ONE `gh pr view` read on
  # the line above, reused rather than read a second time.
  #
  # The gate's NOTE goes through `say` so it lands in the run log with everything
  # else. Swallowing it would silently grandfather the blind spot it announces.
  GATE_NOTE="$(rework_gate "$VERDICT" "" "$REVIEWED_SHA" "$SHA")"; GATE=$?
  [ -n "$GATE_NOTE" ] && say "$GATE_NOTE"
  if [ "$GATE" = "10" ]; then
    # NOBODY IS WAITING (ASK-222; PR #33 review, finding 2, one layer out from
    # where it was filed). This line and the page under it are the SECOND reporter
    # of the same state the worker's closing line reports -- and this is the half
    # that Slacks, so it is the one an operator actually reads at 3am. Both said
    # "waiting on founder merge only" / "ready to merge", true only while nothing
    # armed auto-merge. The worker runs first inside every round here and arms
    # every PR it touches, so the merge is the platform's job now.
    #
    # It still does NOT re-probe `gh pr view --json autoMergeRequest`: that would
    # be a second reader of the arm state with its own semantics, drifting from
    # the worker's. But the alternative to a second reader is NOT an assertion,
    # which is what this was -- the comment here used to justify the claim with
    # "the worker arms every PR it touches", and the worker's gate skipped this
    # exact population 400 lines above its arm, so the sentence was false for
    # every PR that reached this line (PR #33 review round 3, finding 1 -- major).
    # It reads the record the ONE reader publishes. Three states, three sentences.
    #
    # An empty record means nothing recorded an arm for this PR -- the worker
    # declined the issue this round, or never got that far -- so this claims
    # nothing and hands over the command instead.
    # THE RECEIPT, before the terminal report (ASK-218). Gate 10 is the only
    # place it may be written, but gate 10 is NOT by itself the proof: it is
    # reached from three states and only one of them has a terminal approving
    # verdict pinned to the sha that IS the head. This comment used to assert the
    # one and the code trusted it (PR #42 review round 3, finding 1 -- major), so
    # the reviewed sha is now PASSED and the writer refuses without it. The other
    # two states -- an unreadable current head, and no head recorded at all --
    # both reach the writer and both must leave without a receipt.
    #
    # It runs before the auto-merge report because auto-merge lands the PR the
    # moment `validate` goes green, and `validate` is the job that reads this
    # receipt.
    receipt_ensure "$SHA" "$(verdict_record_path "$REVIEWS_DIR" "$TARGET_SLUG" "$PR")" "$REVIEWED_SHA" "$PR"

    AUTOMERGE="$(automerge_from_record "$REVIEWS_DIR/$(artifact_key "$TARGET_SLUG" "$PR").automerge")"
    case "$AUTOMERGE" in
      armed)
        MERGE_LOG="Auto-merge is armed -- GitHub merges it once every required check is green. If it sits green: gh pr merge --auto --squash $PR"
        MERGE_PAGE="PR #$PR approved and auto-merge armed -- GitHub lands it, no human merge needed" ;;
      unarmed)
        MERGE_LOG="Auto-merge is NOT armed on it, so it goes green and sits: gh pr merge --auto --squash $PR"
        MERGE_PAGE="PR #$PR approved but NOT armed -- it will sit green. Needs a human: gh pr merge --auto --squash $PR" ;;
      *)
        MERGE_LOG="Nothing recorded whether auto-merge is armed on it this run, so check it landed: gh pr merge --auto --squash $PR"
        MERGE_PAGE="PR #$PR approved -- its auto-merge state was never recorded, so check it landed: gh pr merge --auto --squash $PR" ;;
    esac
    # ARMED OR NOT, A HEAD NO RECEIPT COVERS DOES NOT LAND. pr-receipt-gate.py is
    # a blocking step in `validate`, the single required context on main, so it
    # fails the very check auto-merge waits on. The armed sentence is REPLACED
    # rather than extended: "no human merge needed" followed by "needs a human"
    # is a page an operator learns to skim. The other two already say a human is
    # needed and already carry the merge command, so those are extended -- both
    # facts are true at once there and dropping either loses an action.
    #
    # AND IT REPORTS THE STATE, NOT A VERDICT IT NEVER READ (PR #42 review round
    # 2, finding 1, second half). This said "validate refuses it, so GitHub will
    # NOT land it". converge cannot know that: pr-receipt-gate.py rides on PR #23
    # and THIS change merges first, so on the day it ships the opposite happens --
    # armed plus green means GitHub lands a head no receipt covers. A page that
    # names the wrong failure is how an operator learns to skim the right ones.
    # The fact converge does own is the receipt, and it is the same call to
    # action either way.
    if [ -n "$RECEIPT_MISS" ]; then
      MERGE_LOG="$MERGE_LOG -- BUT no prd-os receipt covers the head: $RECEIPT_MISS. Nothing proves it was reviewed. By hand: $RECEIPT_FIX"
      case "$AUTOMERGE" in
        armed) MERGE_PAGE="PR #$PR approved and auto-merge armed, but NO prd-os receipt covers the head ($RECEIPT_MISS). Nothing proves it was reviewed: if the receipt gate in validate is live this sits red, and if it is not GitHub lands it anyway. Needs a human: $RECEIPT_FIX" ;;
        *)     MERGE_PAGE="$MERGE_PAGE. AND no prd-os receipt covers the head ($RECEIPT_MISS), so nothing proves it was reviewed: $RECEIPT_FIX" ;;
      esac
    fi
    say "DONE exit-1: PR #$PR verdict '$VERDICT' after $ROUND round(s). $MERGE_LOG"
    bash "$NOTIFY" "converge $ISSUE: $VERDICT after $ROUND round(s), $MERGE_PAGE" 2>/dev/null || true
    exit 1
  fi
  if [ "$GATE" = "20" ]; then
    say "STOP exit-7: PR #$PR has no verdict after round $ROUND -- the review died or timed out. Re-run: kipi review $PR --issue $ISSUE --post"
    bash "$NOTIFY" "converge $ISSUE: review produced no verdict on round $ROUND" 2>/dev/null || true
    exit 7
  fi

  # 40 = STALE. The verdict approves a commit that is no longer the head, so the
  # code sitting at the head has never been read. NOT terminal and never a merge:
  # another round runs, and the review at the end of it writes a record pinned to
  # the current head, which is the only thing that clears this.
  #
  # Deliberately falls THROUGH to the no-progress guard below rather than
  # `continue`-ing past it. If the head and the verdict both stop moving, that
  # guard stops the loop at exit 5; skipping it would re-review the same PR every
  # round to the cap, which is the cry-wolf failure this exit has to avoid.
  if [ "$GATE" = "40" ]; then
    say "round $ROUND: PR #$PR reads '$VERDICT', but that verdict was recorded at $REVIEWED_SHA and the head is now $SHA -- the code at the head was never reviewed. NOT done; re-reviewing."
  fi

  # NO PROGRESS (exit 5). Same verdict AND the branch head never moved means the
  # rework pass changed nothing -- running it again re-reads the same review and
  # produces the same nothing. Requiring BOTH avoids a false stop: a real fix
  # that happens to draw the same verdict again still moves the sha, and that is
  # convergence in progress, not a stall.
  if [ "$VERDICT" = "$LAST_VERDICT" ] && [ -n "$LAST_SHA" ] && [ "$SHA" = "$LAST_SHA" ]; then
    # THE PAGE HAS TO CARRY THE DRIFT, because it is the only thing that reaches
    # the founder's phone (PR #30 review round 2, minor 4). Gate 40 falls through
    # to this guard on purpose, so a stuck drift -- a held claim, a tree that
    # needs a human, a reviewer that is down -- exits here. The generic text read
    # "stalled at 'APPROVE WITH NITS', no code change in round N", which is a
    # benign stall on an approved PR. The gate-40 line above is in the run log;
    # the log is not what wakes anyone.
    STALL_LOG="STOP exit-5: round $ROUND changed no code and drew the same verdict '$VERDICT'. Not burning another round."
    STALL_PAGE="converge $ISSUE: stalled at '$VERDICT', no code change in round $ROUND"
    if [ "$GATE" = "40" ]; then
      STALL_LOG="STOP exit-5: round $ROUND changed no code, and PR #$PR is STILL approved at $REVIEWED_SHA with an unreviewed head of $SHA. Re-reviewing it is not working; not burning another round."
      STALL_PAGE="converge $ISSUE: PR #$PR is '$VERDICT' at $REVIEWED_SHA but its head $SHA was never reviewed, and round $ROUND changed nothing - unreviewed code is sitting at the head, needs a human"
    fi
    say "$STALL_LOG"
    bash "$NOTIFY" "$STALL_PAGE" 2>/dev/null || true
    exit 5
  fi
  LAST_VERDICT="$VERDICT"; LAST_SHA="$SHA"
  say "round $ROUND -> $VERDICT (head $SHA); reworking"
done

CAPOUT_WHY="hit the $MAX_ROUNDS-round cap still at '$LAST_VERDICT'${PR:+ on PR #$PR}"
say "STOP exit-2: $CAPOUT_WHY. A cap-out means the reviewer and Sana disagree persistently; read the last review before raising the cap."
# THE MACHINE-READABLE HALF, AND IT IS THE POINT OF ASK-871. Until this line the
# cap-out announced itself to a human twice -- the `say` above and the page below
# -- and to a machine not at all. So ci-redrive.py and review-redrive.py, whose
# whole job is to re-enter a PR nobody else will, correctly-by-their-own-rules
# re-entered this one: 2026-08-16, ASK-830 capped out at 15:59:53Z and was handed
# back at 16:14:01Z, six rounds and five Opus reviews in one morning. Their caps
# key per PR per head sha and every round moved the head, so nothing they read
# was stale. Nothing bounded dispatches PER ISSUE. This record is that bound.
#
# WRITTEN BEFORE THE PAGE. The page names the command that clears the park, and a
# page telling the founder to clear a record that was never written is worse than
# no page. If the ledger refuses (a lock timeout, a read-only disk) the run says
# so and still pages, because a cap-out the founder never hears about is the
# 29-hour park with the alarm removed.
CAPOUT_NOTE=""
if ! python3 "$LEDGER" "$ATTEMPTS" record-capout "$ISSUE" "$CAPOUT_WHY" 2>>"$LOG"; then
  CAPOUT_NOTE=" WARNING: the cap-out could NOT be recorded in $ATTEMPTS, so the redrives may re-enter this issue -- check that file."
  say "WARNING: record-capout failed for $ISSUE; the redrives cannot see this cap-out."
fi
bash "$NOTIFY" "converge $ISSUE: hit $MAX_ROUNDS-round cap, still $LAST_VERDICT. Parked -- no redrive will re-enter it until you clear it: python3 q-system/.q-system/scripts/attempts-ledger.py $ATTEMPTS clear-capout $ISSUE$CAPOUT_NOTE" 2>/dev/null || true
# The `exit 2` on the line BELOW this comment -- not the `bash "$NOTIFY"` above it --
# is the last statement INSIDE the ASK-351 brace, and it has to stay last and stay
# unconditional: it is what stops bash from ever reading this file again. See the
# header. Nothing may be added between it and the closing brace, and nothing may be
# added below the closing brace.
exit 2
}
