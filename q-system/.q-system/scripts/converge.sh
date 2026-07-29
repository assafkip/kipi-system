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
. "$SCRIPT_DIR/pr-verdict-lib.sh"

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
pr_for_branch() { gh pr list --head "$BRANCH" --json number -q '.[0].number' 2>/dev/null; }
# The head sha comes from pr_head_sha in the shared lib, not a local copy of the
# same `gh pr view`: this driver and linear-worker.sh now BOTH compare it against
# the sha a review pinned, and two private readers of one input is how those two
# comparisons drift apart.

if [ "$DRY" = "1" ]; then
  PR="$(pr_for_branch)"
  V=""; [ -n "$PR" ] && V="$(verdict_from_record "$REVIEWS_DIR/pr-$PR.verdict.json")"
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
receipt_tree() {
  git -C "$SKEL" worktree list --porcelain 2>/dev/null \
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

# receipt_ensure <sha> <verdict-record>
# Best-effort by design and NEVER touches this run's exit code, exactly like the
# worker's auto-merge arm: a ledger that cannot be written is a PR a human has to
# push a receipt onto, not a converge run that should report a different outcome.
# It DOES change what the report says, which is a different thing: the exit code
# is a contract other code reads, the page is what a human reads.
receipt_ensure() {
  local sha="$1" record="$2" tree ledger head note rc backup had=0 ahead
  RECEIPT_MISS=""; RECEIPT_FIX=""
  if [ -z "$sha" ]; then
    say "receipt: no head sha to pin one to, so no receipt was written"
    RECEIPT_MISS="converge never read a head sha, so nothing could be pinned"
    RECEIPT_FIX="read the head with 'gh pr view <pr> --json headRefOid', then write a receipt for $ISSUE at it"
    return 0
  fi
  tree="$(receipt_tree "$BRANCH")"
  if [ -z "$tree" ]; then
    say "receipt: no worktree under $SKEL is on $BRANCH, so there is no tree to commit a receipt into. Write one by hand or PR #23's gate will refuse this PR."
    RECEIPT_MISS="no worktree under $SKEL is on $BRANCH, so there was no tree to commit into"
    RECEIPT_FIX="git -C $SKEL worktree add <path> $BRANCH, then write a receipt for $ISSUE at $sha and push it"
    return 0
  fi
  ledger="$tree/.prd-os/receipts.jsonl"
  head="$(git -C "$tree" rev-parse HEAD 2>/dev/null)"

  backup="$(mktemp)"
  [ -f "$ledger" ] && { had=1; cp "$ledger" "$backup" 2>/dev/null || true; }
  note="$(receipt_append "$ledger" "$ISSUE" "$sha" "$record" "$head")"; rc=$?
  [ -n "$note" ] && say "receipt: $note"

  # 3 is "already receipted" -- a receipt EXISTS, so it is not a miss; the push
  # guard below still owns whether origin carries it. 4 and 5 wrote nothing.
  if [ "$rc" = "4" ] || [ "$rc" = "5" ]; then
    RECEIPT_MISS="the ledger write was refused ($note)"
    RECEIPT_FIX="git -C $tree status, then write a receipt for $ISSUE at $sha into .prd-os/receipts.jsonl and push it"
  fi

  if [ "$rc" = "0" ]; then
    # No --no-verify: the pre-commit ledger check (receipts-ledger-check.py) is
    # what keeps this public repo's one allowed .jsonl to a closed key allowlist.
    # A receipt that has to bypass its own content gate is not a receipt.
    # $ISSUE in the message is what clears the commit-msg linear-issue-ref-check.
    if git -C "$tree" add -- .prd-os/receipts.jsonl 2>>"$LOG" \
       && git -C "$tree" commit -q -m "chore(receipt): prd-os receipt for $ISSUE at $(printf '%.12s' "$sha")" \
            -- .prd-os/receipts.jsonl 2>>"$LOG"; then
      say "receipt: committed onto $BRANCH in $tree"
    else
      # Roll the line back. Leaving an uncommitted receipt in the tree would make
      # every later run dedup against it and skip, so the PR would carry nothing
      # while the ledger claimed it did.
      git -C "$tree" reset -q -- .prd-os/receipts.jsonl 2>/dev/null || true
      if [ "$had" = "1" ]; then cp "$backup" "$ledger" 2>/dev/null || true
      else rm -f "$ledger" 2>/dev/null || true; fi
      say "receipt: the commit was REFUSED in $tree (see $LOG) -- rolled the ledger line back rather than leave an uncommitted receipt. PR #23's gate will refuse this PR until one lands."
      RECEIPT_MISS="the receipt commit was REFUSED in $tree (see $LOG); the ledger line was rolled back"
      RECEIPT_FIX="git -C $tree commit -m 'chore(receipt): prd-os receipt for $ISSUE' -- .prd-os/receipts.jsonl && git -C $tree push origin $BRANCH"
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
  ahead="$(git -C "$tree" rev-list --count "origin/$BRANCH..HEAD" 2>>"$LOG")" || ahead=""
  if [ -z "$ahead" ]; then
    say "receipt: git could not tell whether origin/$BRANCH is behind this tree (no tracking ref for it in $tree). Pushing anyway rather than reading that as nothing to push."
  fi
  if [ -z "$ahead" ] || [ "$ahead" != "0" ]; then
    if git -C "$tree" push -q origin "HEAD:refs/heads/$BRANCH" 2>>"$LOG"; then
      say "receipt: pushed -- origin/$BRANCH now carries it, so validate reads it"
    else
      say "receipt: the push to origin/$BRANCH FAILED (see $LOG). CI reads the pushed head, so validate still refuses this PR. By hand: git -C $tree push origin $BRANCH"
      RECEIPT_MISS="the receipt is committed in $tree but the push to origin/$BRANCH FAILED (see $LOG), and CI reads the pushed head"
      RECEIPT_FIX="git -C $tree push origin $BRANCH"
    fi
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
  $WORKER_CMD --apply --limit 1 --issue "$ISSUE" >>"$LOG" 2>&1
  WRC=$?

  PR="$(pr_for_branch)"
  if [ -z "$PR" ]; then
    say "STOP exit-7: no PR on $BRANCH after round $ROUND (worker rc=$WRC). Sana could not open one; see $LOG"
    bash "$NOTIFY" "converge $ISSUE: stopped, no PR after round $ROUND" 2>/dev/null || true
    exit 7
  fi

  VERDICT="$(verdict_from_record "$REVIEWS_DIR/pr-$PR.verdict.json")"
  SHA="$(pr_head_sha "$PR")"
  REVIEWED_SHA="$(head_sha_from_record "$REVIEWS_DIR/pr-$PR.verdict.json")"

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
    # place it may be written: it is the one state where a terminal approving
    # verdict is pinned to the sha that IS the head. It runs before the auto-merge
    # report because auto-merge lands the PR the moment `validate` goes green, and
    # `validate` is the job that reads this receipt.
    receipt_ensure "$SHA" "$REVIEWS_DIR/pr-$PR.verdict.json"

    AUTOMERGE="$(automerge_from_record "$REVIEWS_DIR/pr-$PR.automerge")"
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
    if [ -n "$RECEIPT_MISS" ]; then
      MERGE_LOG="$MERGE_LOG -- BUT no prd-os receipt covers the head: $RECEIPT_MISS. \`validate\` refuses it, so it does not merge until one lands. By hand: $RECEIPT_FIX"
      case "$AUTOMERGE" in
        armed) MERGE_PAGE="PR #$PR approved and auto-merge armed, but NO prd-os receipt covers the head ($RECEIPT_MISS) -- validate refuses it, so GitHub will NOT land it. Needs a human: $RECEIPT_FIX" ;;
        *)     MERGE_PAGE="$MERGE_PAGE. AND no prd-os receipt covers the head ($RECEIPT_MISS), so validate refuses it too: $RECEIPT_FIX" ;;
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

say "STOP exit-2: hit the $MAX_ROUNDS-round cap still at '$LAST_VERDICT'. A cap-out means the reviewer and Sana disagree persistently; read the last review before raising the cap."
bash "$NOTIFY" "converge $ISSUE: hit $MAX_ROUNDS-round cap, still $LAST_VERDICT" 2>/dev/null || true
exit 2
