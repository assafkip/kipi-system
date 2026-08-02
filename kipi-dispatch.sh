#!/usr/bin/env bash
# The heartbeat that keeps the Linear loop running with NO terminal open.
#
# WHY THIS EXISTS
# ---------------
# Every converge run before 2026-07-28 was typed by a human into an interactive
# session. `kipi work` and `converge` had no scheduler, unlike every other kipi
# job. So the loop only ran while someone watched it, which is not autonomy --
# it is a person standing in for a cron job. The founder's requirement, verbatim:
# "I want to make sure that I can actually, at the end of this session, close
# this terminal."
#
# Lives at REPO ROOT, not under q-system/. Instance automation inside the synced
# subtree gets deleted by `kipi update`'s rsync --delete (RULE-2026-06-30-A, and
# the scar: income scanners went dark for 6 days that way).
#
# LOOP EXITS (loop-exits.md -- an autonomous loop owns 2, 4, 7 at minimum)
#   2 turn cap      MAX_CONCURRENT live converge runs, counted from the process
#                   table, not from a state file that can lie.
#   3 budget        one dispatch per heartbeat. The interval IS the rate limit.
#   4 wall clock    each converge carries --max-rounds; the reviewer is bounded
#                   at 2400s inside pr-review-agent.sh.
#   5 no progress   an issue moves to In Progress the moment the worker takes
#                   it, and ready() only returns backlog/unstarted -- so a
#                   dispatched issue excludes itself from the next heartbeat.
#   7 error thresh  the worker's own MAX_ATTEMPTS marks an issue stuck and
#                   stops picking it. This script does not second-guess that.
#   6 human interrupt  launchctl unload. Outside the loop, as it must be.
#
# WHAT PICKS THE WORK
# -------------------
# `kipi work` in DRY mode. Deliberately not a second Linear query: ready() lives
# in linear-worker.sh:197 (owner:sana, not owner:assaf, backlog/unstarted, has a
# DoR) and two readers of "ready" with drifting semantics is the exact defect
# class this repo keeps finding. One source of truth, asked politely.
set -uo pipefail

# Resolved BEFORE the cd below, because $0 may be relative and the self-heal
# re-execs this file by path after fast-forwarding it.
SELF="$(cd "$(dirname "$0")" 2>/dev/null && pwd)/$(basename "$0")"

REPO="${KIPI_REPO:-/Users/assafkipnis/projects/kipi-system}"
# HARDCODED OFF $REPO, DELIBERATELY NOT AN ENV VAR. Every other path in this file
# takes a KIPI_* override for testability; this one must not. A variable here would
# be a documented way to aim the client-repo safety gate at /bin/true while every
# log line still read normally. The tests drive the real script and stub `gh` by
# prepending to PATH instead, which adds no knob to the shipped code.
PREFLIGHT="$REPO/q-system/.q-system/scripts/repo-preflight.sh"
LOG="$HOME/.config/kipi/dispatch.log"
MAX_CONCURRENT="${KIPI_DISPATCH_MAX:-2}"
MAX_ROUNDS="${KIPI_DISPATCH_ROUNDS:-3}"
NOTIFY="${KIPI_NOTIFY:-$REPO/q-system/.q-system/scripts/slack-notify.sh}"
# Founder decision 2026-08-01: the converge/worker claude -p calls inherit this;
# unpinned they rode the interactive default (Fable) and burned quota on 2026-08-01.
export ANTHROPIC_MODEL="${KIPI_DISPATCH_MODEL:-claude-opus-5}"

mkdir -p "$(dirname "$LOG")"
say() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }
page() { bash "$NOTIFY" "$1" >/dev/null 2>&1 || true; }
# Same notifier, but REPORTS whether it went out. page() ends in `|| true` on
# purpose -- a notifier must never take its caller down -- which makes it useless
# to a caller that has to know. Kept as a sibling rather than changing page()'s
# contract for the dozen sites that correctly do not care. Used by stale_check,
# which must not write a dedupe marker for a page that never arrived.
page_ok() { bash "$NOTIFY" "$1" >/dev/null 2>&1; }

# ONE PAGE PER STATE, NOT ONE PER HEARTBEAT (ASK-283, 2026-08-02).
# Audited across this file: four guards -- missing repo, unusable `date`, gh off
# PATH, Linear auth dead -- each name a PERMANENT condition and each had NO marker,
# on a 900s timer. That is 96 identical Slack lines a day per guard, and three of
# them can hold at once: ~288 pages a day, worse than the stale-checkout alert that
# actually got noticed. The loud one is rarely the worst one. The founder's
# own detect-act-learn rule already says one summary line, never one ping per
# finding. The cost of the noise is not annoyance, it is that it trains him to skim
# the channel, which is how the one page that matters gets missed.
#
# KEYED ON A HASH OF THE MESSAGE, not on the call site alone. A page whose CONTENT
# changed (different repo path, a different auth error) is a different state and
# must speak up; an unchanged state stays quiet until the re-ping window, so a
# problem still standing a day later is surfaced once more rather than forgotten.
# cksum, not md5/md5sum/shasum: it is POSIX and identical on both kernels this repo
# runs on, and nothing here is adversarial -- it only has to notice a change.
#
# THE MARKER IS WRITTEN ONLY ON DELIVERY. Same lesson the stale-check marker
# already carries: a failed page that still deduped would make the founder
# permanently silent about a live fault, which is strictly worse than a storm.
PAGE_REPING_SECONDS="${KIPI_PAGE_REPING_SECONDS:-86400}"

# CLEAR ON RECOVERY, or the dedupe becomes a guard that can never fire.
# Without this, a fault that heals and RECURS inside the re-ping window is silently
# suppressed: healthy runs never touch the marker, so the file still holds the old
# hash and the second occurrence -- a genuinely new event -- is swallowed. That is
# the same shape as launchd-health's 6h TTL on a 12h job, which this same audit
# flagged. linear-worker.sh already does clear-on-recovery and is the reference.
# Every page_once key below has a matching page_clear on its healthy path.
page_clear() {
  local mark="$(dirname "$LOG")/paged-$1"
  [ -f "$mark" ] || return 0
  rm -f "$mark" 2>/dev/null || true
  say "page state cleared: $1 recovered, so a recurrence pages again immediately"
}

page_once() {
  local key="$1" msg="$2" mark hash now prev stamp lock
  mark="$(dirname "$LOG")/paged-$key"
  hash="$(printf '%s' "$msg" | cksum | tr -d ' \n')"
  now="$(date -u +%s)"
  # READ-CHECK-WRITE UNDER ONE LOCK. Unlocked, two dispatchers both stat a missing
  # marker, both decide to page, and the founder gets the identical line twice --
  # a dedupe that produces duplicates is worse than none, because it is trusted.
  # mkdir is the atomic primitive; a lock we cannot take means another process is
  # already handling this exact key, so staying quiet is the correct answer.
  lock="$mark.lock"
  if ! mkdir "$lock" 2>/dev/null; then
    say "page skipped ($key): another dispatcher is already deciding it"
    return 0
  fi
  trap 'rmdir "$lock" 2>/dev/null || true' RETURN
  if [ -f "$mark" ]; then
    prev="$(sed -n 1p "$mark" 2>/dev/null)"
    stamp="$(sed -n 2p "$mark" 2>/dev/null)"
    case "$stamp" in ''|*[!0-9]*) stamp=0 ;; esac
    if [ "$prev" = "$hash" ] && [ "$(( now - stamp ))" -lt "$PAGE_REPING_SECONDS" ]; then
      say "page suppressed ($key unchanged for $(( (now - stamp) / 60 ))m; re-pings after $(( PAGE_REPING_SECONDS / 3600 ))h)"
      return 0
    fi
  fi
  if page_ok "$msg"; then
    printf '%s\n%s\n' "$hash" "$now" > "$mark" 2>/dev/null || true
  else
    say "page: $key did NOT go out; leaving the marker unset so the next heartbeat retries it"
  fi
}

cd "$REPO" 2>/dev/null || {
  say "FATAL: repo not found at $REPO"
  page_once repo-missing "kipi dispatch: repo not found at $REPO -- the Linear loop is DEAD. Do: check the path in com.kipi.dispatch.plist."
  exit 1
}
page_clear repo-missing

# --- STALE-CHECKOUT REFUSAL (sp-c775b116) --------------------------------
# The loop runs the founder's WORKING TREE, and nothing kept it in sync with
# main. There is no `git pull` anywhere in this script. Observed 2026-07-30:
# merging PR #34 left this checkout at 1597eaf, so the loop would have gone on
# running the old Claude-only reviewer indefinitely while main carried the codex
# gate. It was fixed by hand twice in one session, which means every future merge
# silently depended on someone remembering.
#
# IT DETECTS *AND* REPAIRS, as of 2026-08-02. This block used to say "a detector,
# not a pull", on the grounds that moving the tree under an interactive session is
# the parallel-session scar. That reasoning was half right: it is a reason to be
# careful about WHICH trees get moved, not a reason to move none of them. The
# version that only detected printed the exact remedy every 15 minutes for a night
# and nobody typed it. attempt_ff() below now applies the remedy where the tree
# demonstrably belongs to nobody, and refuses (and pages) where it might not.
#
# REFUSE, not warn. This loop MERGES ITS OWN PRs and has no accepted-change
# signal, so building on superseded code and auto-merging the result is worse
# than resting until someone fast-forwards. Same posture as the reviewer's
# commit status: absent is not approved, and unstated HOLDS.
#
# A FAILED LOOKUP MUST NOT WEDGE THE LOOP. Refusal needs a POSITIVE answer that
# we are behind; a network blip, an auth prompt or a missing remote logs and
# proceeds. Two different safe directions, deliberately: fail closed on
# staleness, fail open on not knowing.
# THE DETECTOR COMPUTES THE REMEDY, SO IT MUST APPLY IT (ASK-283, 2026-08-02).
# For one night this printed `git merge --ff-only origin/main` every 15 minutes
# while the gap grew 7 -> 10 commits. Measured from the log: 19 refusing cycles,
# 9 Slack pages, ZERO automated action. Nobody read them; the founder fixed it by
# hand in the morning. A detector that names a deterministic, non-destructive,
# loudly-failing command and then waits for a human to type it is an alert with no
# hands, and the founder's detect-act-learn rule already forbids that shape.
#
# Prints NOTHING and returns 0 when the checkout was fast-forwarded.
# Prints ONE line naming what stopped it and returns 1 otherwise -- that line is
# what the page carries, so it has to read as a reason, not a code.
#
# WHAT THIS REFUSES TO TOUCH, and why each one is a tree that belongs to somebody:
# Set by attempt_ff when it had to copy something out of the merge's way. Declared
# here so `set -u` cannot trip on them at a call site that never entered that path.
FF_PRESERVE_DIR=""
FF_PRESERVED_COUNT=0
# REASON RETURNED VIA A GLOBAL, NOT STDOUT, and that is a correctness fix.
# The first cut printed the reason and the caller did `out="$(attempt_ff)"`. A
# command substitution is a SUBSHELL, so FF_PRESERVE_DIR and FF_PRESERVED_COUNT --
# set inside it -- were discarded on return, and the "I preserved your files" receipt
# could never fire. A guard that cannot fire, one day after writing that memory.
ATTEMPT_FF_REASON=""
attempt_ff() {
  local branch out p
  ATTEMPT_FF_REASON=""
  FF_PRESERVE_DIR=""
  FF_PRESERVED_COUNT=0
  # 1. A NON-MAIN OR DETACHED HEAD IS SOMEONE ELSE'S WORK. This is the
  # parallel-sessions scar directly: two sessions sharing one checkout yank each
  # other's tree on a branch move. Moving a feature branch to main is never the
  # remedy the detector computed, so it is never done here.
  branch="$(git symbolic-ref --short HEAD 2>/dev/null)" || branch=""
  if [ "$branch" != "main" ]; then
    ATTEMPT_FF_REASON="the checkout is on ${branch:-a detached HEAD}, not main, so its tree was left untouched"
    return 1
  fi
  # 2. A HALF-FINISHED GIT OPERATION. Moving HEAD out from under a merge, rebase,
  # cherry-pick or bisect destroys in-flight state that has no other copy.
  # --git-path, not a literal .git/, because this also runs inside worktrees where
  # .git is a FILE and these markers live somewhere else entirely.
  for p in MERGE_HEAD REBASE_HEAD CHERRY_PICK_HEAD REVERT_HEAD BISECT_LOG rebase-merge rebase-apply; do
    if [ -e "$(git rev-parse --git-path "$p" 2>/dev/null)" ]; then
      ATTEMPT_FF_REASON="a git $p is in progress, so the tree was left untouched"
      return 1
    fi
  done
  # 3. A STAGED INDEX IS A COMMIT SOMEONE IS COMPOSING. Fast-forwarding over it
  # silently folds their staged hunks into a different base.
  if ! git diff --cached --quiet 2>/dev/null; then
    ATTEMPT_FF_REASON="the index has staged changes (a commit in progress), so the tree was left untouched"
    return 1
  fi
  # 4. MODIFIED TRACKED FILES ARE LEFT TO GIT, NOT PRE-JUDGED, AND THAT IS A
  # DELIBERATE DEPARTURE FROM "refuse if the tree is dirty". Measured on the real
  # checkout that produced this incident: 3 modified tracked files and 5488
  # untracked ones, as its NORMAL resting state. A blanket dirty-tree refusal would
  # make this self-heal permanently inert on the ONE checkout it exists for -- the
  # wired-but-never-runs failure this repo has already eaten once. So the arbiter is
  # git's own check: --ff-only aborts with "local changes would be overwritten" when
  # the incoming commits actually touch a modified file, and otherwise carries the
  # unrelated edits forward untouched. That is a per-file answer instead of a
  # whole-tree guess, and it is the same command the page has been telling the
  # founder to run by hand all along.
  # 5. IGNORED FILES ARE THE ONE THING GIT WILL DESTROY WITHOUT ASKING, and this is
  # the blocker that nearly shipped. Measured 2026-08-02 in a scratch repo:
  #   untracked + NOT ignored, upstream starts tracking the path
  #     -> "would be overwritten by merge ... Aborting", exit 1, file intact. SAFE.
  #   IGNORED, upstream starts tracking the same path
  #     -> "Fast-forward ... create mode 100644", exit 0, LOCAL CONTENT GONE.
  #        No warning, no abort, and no reflog entry either -- an untracked file
  #        has no object in the database, so there is nothing to recover from.
  #
  # "Let git be the arbiter" was right for the untracked class and WRONG for this
  # one, and the measurement that reassured me hid it: `git ls-files --others
  # --exclude-standard` counts 5488 on the founder's checkout and EXCLUDES ignored
  # files entirely. The real ignored count there is 3982, none of which that number
  # could see. Not hypothetical either -- this repo has already started tracking
  # .prd-os/receipts.jsonl and q-system/memory/graph.jsonl upstream while `*.jsonl`
  # sits in .gitignore, which is exactly the collision.
  #
  # So: copy anything the incoming commits would land on top of, BEFORE trying the
  # merge. The merge itself stays a plain --ff-only with no -f, no reset --hard, no
  # clean and no stash, so an abort is still an abort and still pages.
  local risk="" p preserved=0
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    # Only paths that exist here and are NOT tracked at HEAD. A tracked+modified
    # file is already git's own abort case and must stay that way.
    [ -e "$p" ] || continue
    git ls-files --error-unmatch -- "$p" >/dev/null 2>&1 && continue
    risk="$risk$p
"
  done <<EOF
$(git diff --name-only --diff-filter=ACMRT HEAD origin/main 2>/dev/null)
EOF
  if [ -n "$risk" ]; then
    FF_PRESERVE_DIR="$(dirname "$LOG")/ff-preserved/$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short origin/main 2>/dev/null)"
    while IFS= read -r p; do
      [ -n "$p" ] || continue
      mkdir -p "$FF_PRESERVE_DIR/$(dirname "$p")" 2>/dev/null || continue
      # cp, never mv: moving it would itself change the tree the founder is using.
      cp -R "$p" "$FF_PRESERVE_DIR/$p" 2>/dev/null && preserved=$((preserved + 1))
    done <<EOF
$risk
EOF
    FF_PRESERVED_COUNT="$preserved"
    say "self-heal: $preserved untracked/ignored path(s) sit where origin/main adds files; copied to $FF_PRESERVE_DIR before touching anything"
  fi

  out="$(git merge --ff-only origin/main 2>&1)" || {
    ATTEMPT_FF_REASON="git merge --ff-only origin/main did not apply: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-300)"
    return 1
  }
  return 0
}

# RE-EXEC RATHER THAN FALL THROUGH, and this is a correctness fix not a nicety.
# bash reads a script lazily by byte offset. The fast-forward above can rewrite
# kipi-dispatch.sh underneath the running interpreter, after which bash resumes at
# the old offset in the NEW file and executes whatever bytes happen to land there.
# Continuing in-process is the one thing we must not do. exec restarts cleanly on
# the code we just pulled, which is also exactly what "run the current control
# code" means. A non-interactive bash exits if exec fails, so there is no path
# where a failed exec silently proceeds on the stale bytes.
relaunch_self() { exec env KIPI_DISPATCH_SELFHEALED=1 bash "$SELF"; }

stale_check() {
  local local_head remote_head base
  # Bounded by hand: macOS ships no `timeout`, and an unbounded fetch inside a
  # 15-minute launchd job is how a heartbeat becomes a stuck process.
  ( git fetch --quiet origin main 2>/dev/null ) &
  local fetch_pid=$! waited=0
  while kill -0 "$fetch_pid" 2>/dev/null && [ "$waited" -lt 60 ]; do
    sleep 1; waited=$((waited + 1))
  done
  if kill -0 "$fetch_pid" 2>/dev/null; then
    kill "$fetch_pid" 2>/dev/null || true
    say "stale-check: fetch exceeded 60s, proceeding without a freshness answer"
    return 0
  fi
  wait "$fetch_pid" 2>/dev/null || {
    say "stale-check: git fetch failed, proceeding (cannot distinguish stale from offline)"
    return 0
  }
  local_head="$(git rev-parse HEAD 2>/dev/null)" || return 0
  remote_head="$(git rev-parse origin/main 2>/dev/null)" || return 0
  [ -n "$local_head" ] && [ -n "$remote_head" ] || return 0
  [ "$local_head" != "$remote_head" ] || return 0
  # THE PREDICATE IS "does origin/main hold commits this tree lacks", NOT "is HEAD
  # an ancestor of origin/main". Codex round 2 on PR #47 called the ancestor form a
  # major, and it was right: --is-ancestor is FALSE for a DIVERGED tree, so the
  # first version ran happily on a checkout missing origin/main's newest control
  # code. I had captured that as a deliberate trade (sp-18cd7843) on the grounds
  # that refusing would wedge a session holding local commits. That reasoning was
  # backwards. The commonest way to diverge is a merge of this very branch: after
  # PR #47 lands, origin/main gains a merge commit while this tree keeps the
  # unmerged parent -- diverged AND substantively behind. So the dangerous case was
  # the LIKELY case, not an edge.
  #
  # rev-list HEAD..origin/main counts exactly what is missing here, and it is 0 for
  # both "equal" and "ahead-only". Ahead still runs: an agent commits locally
  # before it opens a PR, and refusing there would wedge the loop on its own work.
  base="$(git rev-list --count "$local_head..$remote_head" 2>/dev/null || echo 0)"
  case "$base" in ''|*[!0-9]*) return 0 ;; esac   # unparseable count = no answer = run
  [ "$base" -gt 0 ] || return 0
  say "STALE: origin/main holds $base commit(s) this checkout lacks (HEAD ${local_head:0:7}, origin/main ${remote_head:0:7}). Dispatching would run superseded control code and auto-merge the result."

  # --- SELF-HEAL BEFORE PAGING ---------------------------------------------
  # The refusal above is CORRECT and is not weakened: nothing dispatches while the
  # checkout is behind. What changes is that the fix is now attempted instead of
  # printed. The page below is reserved for the case a human is genuinely needed.
  # Declared separately from the assignment below: `local x="$(f)"` swallows f's
  # exit status (local always succeeds), which would make every attempt look green.
  local why=""
  if [ "${KIPI_DISPATCH_SELFHEALED:-0}" = "1" ]; then
    # ONE ATTEMPT PER LAUNCH. We already fast-forwarded and re-execed this cycle
    # and the tree is STILL behind, which means something is racing the merge (a
    # push landing between fetch and merge, most likely). Re-execing again would
    # spin. Hand it to a human and let the next heartbeat start clean.
    why="a fast-forward already ran this cycle and origin/main moved again underneath it"
  elif attempt_ff; then
    say "self-heal: fast-forwarded this checkout to origin/main ${remote_head:0:7} ($base commit(s)); re-execing on the new control code"
    # A PAGE THAT IS A RECEIPT, NOT AN ALARM. Only fires when the merge landed on
    # top of untracked or ignored local files, which git would otherwise have
    # replaced with no warning and no way back. The founder needs the restore path
    # exactly once; the heal itself stays silent, as a working fix should.
    if [ "${FF_PRESERVED_COUNT:-0}" -gt 0 ]; then
      page_once "ff-preserved-$remote_head" "kipi dispatch: fast-forwarded the checkout myself, and $FF_PRESERVED_COUNT untracked/ignored file(s) sat where the incoming commits add files. I copied them first, nothing was lost. Originals: $FF_PRESERVE_DIR"
    fi
    # Released before exec, because exec replaces this process and no trap runs.
    checkout_unlock
    relaunch_self
    # Unreached in production: relaunch_self execs. The tests stub it, and for them
    # returning 0 is the right answer -- the tree is current, so dispatch proceeds.
    return 0
  else
    why="$ATTEMPT_FF_REASON"
  fi

  say "REFUSING: self-heal could not fix it -- $why (HEAD ${local_head:0:7}, origin/main ${remote_head:0:7})"
  # PAGE ONCE PER REMOTE SHA, not once per heartbeat. Second major from the same
  # review: at a 900s interval an unrepaired checkout sent the identical Slack
  # message 96 times a day, which trains the founder to ignore the channel and
  # buries the one line that matters. Same fix the daily cap already uses (a
  # `.paged` marker), keyed on the remote sha so a NEW divergence pages again.
  # Beside the dispatch log and the daily-cap counters, which is where this
  # script's other state already lives. Derived from $LOG so there is one
  # definition of "the state dir" rather than a second literal path.
  local paged_mark="$(dirname "$LOG")/stale-paged-$remote_head"
  if [ ! -f "$paged_mark" ]; then
    # MARK ONLY WHAT WAS ACTUALLY DELIVERED (codex round 4, major 2). The first cut
    # wrote the marker unconditionally, so a page that FAILED -- webhook down, no
    # network, slack-notify missing -- still suppressed every later notification for
    # that sha. The founder would then be permanently silent about a refusing loop,
    # which is strictly worse than the 96-a-day storm this dedupe was added to stop:
    # a storm is annoying, silence is invisible.
    #
    # page() ends in `|| true` so it cannot report, deliberately (a notifier must
    # never take the caller down). So call the notifier directly here and read its
    # status, rather than changing page()'s contract for every other caller.
    # NAMES THE ATTEMPT, NOT JUST THE SYMPTOM. This page now only fires when the
    # automatic fix was tried and could not apply, so it has to say what was tried
    # and what stopped it -- otherwise it reads like the old "type this command"
    # ping the founder correctly stopped reading, and he would type the command
    # that has ALREADY been tried and failed.
    if page_ok "kipi dispatch: paused -- origin/main has $base commit(s) this checkout lacks. I tried the fast-forward myself and it did not apply: $why. This one needs you: cd $REPO. The loop resumes on its own once the checkout is current."; then
      : > "$paged_mark" 2>/dev/null || true
    else
      say "stale-check: the page did NOT go out; leaving the dedupe marker unset so the next heartbeat retries it"
    fi
  fi
  return 1
}
# ONE WRITER TO THE WORKING TREE, ACROSS THE WHOLE CHECK-THEN-MERGE.
# stale_check reads HEAD, decides, and then REWRITES the checkout. Unlocked, two
# dispatchers (a launchd beat overlapping a hand-run one, or two instances after a
# reload) can both pass the freshness gate against the same HEAD and both merge --
# the parallel-sessions scar with a machine on both ends instead of a person. The
# turn lock further down only covers repo SELECTION, which is far too late: by then
# the tree has already moved. So the lock has to span read + decide + write, not
# just the write.
#
# Same mkdir primitive and same stale-reaping posture as turn_lock: mkdir is atomic
# on every filesystem this runs on, and a dispatcher killed mid-merge must not wedge
# the loop forever. Reap at 1h, which is far longer than any merge and far shorter
# than a night.
CHECKOUT_LOCK="${KIPI_DISPATCH_CHECKOUT_LOCK:-$HOME/.config/kipi/dispatch-checkout.lock}"
checkout_unlock() { rmdir "$CHECKOUT_LOCK" 2>/dev/null || true; }
checkout_lock() {
  mkdir -p "$(dirname "$CHECKOUT_LOCK")" 2>/dev/null || true
  if mkdir "$CHECKOUT_LOCK" 2>/dev/null; then return 0; fi
  local now mtime probe
  now="$(date -u +%s)"
  probe="$(stat -c %Y "$CHECKOUT_LOCK" 2>/dev/null)"
  case "$probe" in ''|*[!0-9]*) probe="" ;; esac
  [ -n "$probe" ] || { probe="$(stat -f %m "$CHECKOUT_LOCK" 2>/dev/null)"; case "$probe" in ''|*[!0-9]*) probe="" ;; esac; } # portability-lint-skip
  mtime="$probe"
  # An unreadable mtime means DO NOT REAP. Skipping one beat is safe; stealing a
  # lock we cannot age and then merging under the holder is not.
  if [ -n "$mtime" ] && [ "$(( now - mtime ))" -gt 3600 ]; then
    say "checkout-lock: reaping a stale lock ($(( now - mtime ))s old)"
    rmdir "$CHECKOUT_LOCK" 2>/dev/null || true
    mkdir "$CHECKOUT_LOCK" 2>/dev/null && return 0
  fi
  return 1
}

if ! checkout_lock; then
  say "skip: another dispatcher holds the checkout lock (freshness check and merge are one transaction)"
  exit 0
fi
# Covers every later exit, including the FATAL paths below. exec is the one case a
# trap cannot cover, so relaunch_self's caller releases explicitly before it.
trap 'checkout_unlock' EXIT
stale_check || exit 0
# The tree is current and nobody else is mid-merge. Everything past this point only
# READS the checkout, so the lock is handed back rather than held for the whole run.
checkout_unlock
trap - EXIT

# `pgrep -c` exits 1 with no match, which under `set -e` would look like failure
# and under a bare assignment yields an empty string. Force a number.
live_converges() { pgrep -f "converge.sh --issue" 2>/dev/null | grep -c . || true; }

# --- FLEET SELECTION (finding-8 and finding-9) ----------------------------
# 18 ready owner:sana issues sit across 14 projects and no worker can pick them up,
# because exactly one dispatch job exists fleet-wide and it is bound to this
# checkout. Letting this script iterate the registry closes that gap and, done
# naively, aims an unattended self-merging loop at Alice, Prodigy_Gold and
# Pure_spectrum_Q -- CLIENT repos. So selection is two things that must both hold:
# a preflight every candidate has to pass, and a rotation so no repo starves.
#
# THE HOME REPO IS A STRUCTURAL CLASS, NOT A SETTING. Below, a candidate is
# preflighted unless its path equals $REPO -- the checkout this script is running
# out of, which is not "entered" at all and is already gated by stale_check() a few
# dozen lines up. That distinction is a path equality, so no env var, flag or
# registry field can move a repo into the ungated class. It is the only branch
# around the preflight and it cannot be reached by configuration.

# THE WHOLE TURN, UNDER ONE LOCK (codex finding-4). cursor_set's own lock only
# serialises the WRITE, so two overlapping heartbeats could both read the same
# cursor, both select the same next repo, and both then write the identical value
# -- a lock that made the race invisible instead of preventing it. Read, select
# and advance have to be one transaction, so the turn is what gets locked.
#
# STALE LOCKS ARE REAPED, not waited on. A dispatcher killed mid-turn (launchd
# reaping the group, a reboot) would otherwise wedge the whole fleet forever,
# which is a worse failure than the duplicate turn this prevents.
turn_lock() {
  local LOCK="${KIPI_DISPATCH_TURNLOCK:-$HOME/.config/kipi/dispatch-turn.lock}"
  mkdir -p "$(dirname "$LOCK")" 2>/dev/null || true
  if [ -d "$LOCK" ]; then
    local now mtime age probe
    now="$(date -u +%s)"
    # PORTABILITY, AND IT IS NOT COSMETIC. The first cut was
    #   mtime="$(stat -f %m "$LOCK" || stat -c %Y "$LOCK" || echo "$now")"
    # which is correct on BSD/macOS and CRASHES THE CALLER on GNU/Linux. GNU -f
    # is --file-system and takes no format argument, so %m is read as a FILE
    # operand: stat errors on %m, still prints a filesystem block for $LOCK on
    # stdout, and exits 1. The nonzero exit then runs the || fallback whose output
    # is APPENDED, so mtime became multi-line junk and `$(( now - mtime ))` died
    # with "File: unbound variable" -- and under `set -u` that is FATAL for a
    # non-interactive shell. turn_lock therefore killed the whole dispatcher
    # instead of returning 1, every time the lock directory already existed.
    # It passed on macOS and failed only in CI, which is exactly the shape a
    # portability bug takes.
    #
    # GNU form FIRST, each candidate validated as digits before it is used, and
    # an unreadable mtime means DO NOT REAP -- keeping a lock we cannot age is
    # safe (one skipped turn), reaping one we guessed at is not.
    mtime=""
    probe="$(stat -c %Y "$LOCK" 2>/dev/null)"
    case "$probe" in ''|*[!0-9]*) probe="" ;; esac
    # The BSD arm OF the two-kernel branch described above, reached only after the GNU
    # form returned no digits. Deliberate, not an oversight, hence: portability-lint-skip
    [ -n "$probe" ] || { probe="$(stat -f %m "$LOCK" 2>/dev/null)"; case "$probe" in ''|*[!0-9]*) probe="" ;; esac; } # portability-lint-skip
    mtime="$probe"
    if [ -n "$mtime" ]; then
      age=$(( now - mtime ))
      if [ "$age" -gt 3600 ]; then
        say "turn-lock: reaping a stale lock (${age}s old)"
        rmdir "$LOCK" 2>/dev/null || true
      fi
    fi
  fi
  mkdir "$LOCK" 2>/dev/null || return 1
  TURN_LOCK_DIR="$LOCK"
  trap 'rmdir "$TURN_LOCK_DIR" 2>/dev/null || true' EXIT
  return 0
}

# The cursor's ONLY writer. Finding-12 rejected storing this in attempts-ledger.py
# and the reason generalises: a plain read-then-write from two overlapping
# heartbeats loses an update, which is the exact race attempts-ledger.py exists to
# prevent. So the file gets one writer, an atomic mkdir lock (mkdir is the portable
# test-and-set; macOS ships no flock(1)), and a rename rather than a truncating
# write so no reader ever sees a half-written name.
cursor_set() {
  local name="$1"
  local CURSOR_FILE="${KIPI_DISPATCH_CURSOR:-$HOME/.config/kipi/dispatch-cursor}"
  mkdir -p "$(dirname "$CURSOR_FILE")" 2>/dev/null || true
  # NO SECOND LOCK HERE. This used to take its own mkdir lock, which was both
  # redundant and dangerous: turn_lock already serialises the entire
  # read-select-advance, and a dispatcher killed between creating this inner lock
  # and removing it left a directory nothing ever reaped. Every later heartbeat
  # then waited 5s, failed to advance, and re-picked the same repo forever --
  # starving exactly the repos round-robin exists to protect. One lock, held by
  # the turn, is the whole transaction.
  printf '%s' "$name" > "$CURSOR_FILE.tmp.$$" || return 1
  mv -f "$CURSOR_FILE.tmp.$$" "$CURSOR_FILE" || return 1
}

cursor_get() {
  local CURSOR_FILE="${KIPI_DISPATCH_CURSOR:-$HOME/.config/kipi/dispatch-cursor}"
  cat "$CURSOR_FILE" 2>/dev/null || true
}

# Emits `name<TAB>path<TAB>expected_remote`, home first.
#
# OPT-IN IS DEFAULT OFF, AND STRICTLY SO: a row joins the fleet only when it
# carries dispatch.enabled === true (JSON boolean). A missing dispatch key, false,
# the string "true", or 1 all mean NO. Every one of the 23 rows in the shipped
# registry is therefore off, which is the correct state to ship the dangerous piece
# in -- the fleet stays exactly as it is today until a human opts a repo in by hand.
fleet_candidates() {
  local registry="${KIPI_DISPATCH_REGISTRY:-$REPO/instance-registry.json}"
  printf '%s\t%s\t%s\n' "$(basename "$REPO")" "$REPO" ""
  [ -f "$registry" ] || { say "fleet: no registry at $registry, home repo only"; return 0; }
  python3 - "$registry" "$REPO" <<'PY'
import json, sys
reg, home = sys.argv[1], sys.argv[2]
try:
    data = json.load(open(reg))
except Exception:
    sys.exit(0)          # an unreadable registry means home only, never "everything"
for e in data.get("instances", []):
    d = e.get("dispatch")
    if not isinstance(d, dict) or d.get("enabled") is not True:
        continue
    p = e.get("path", "")
    if not p or p == home:
        continue
    print("%s\t%s\t%s" % (e.get("name", ""), p, d.get("expected_remote", "")))
PY
}

# Registry order, rotated to start just after the last repo that took a turn.
#
# WHY NOT REGISTRY ORDER (finding-9). Under a plain registry-order scan the head of
# the list is whichever repo has work, and this checkout nearly always does. A
# later client repo is then not merely served late, it is NEVER reached. The cursor
# records who last consumed a turn so the next cycle starts after them, which
# bounds the wait for any repo at one full rotation.
rotation() {
  local cur; cur="$(cursor_get)"
  local -a rows=(); local line
  while IFS= read -r line; do [ -n "$line" ] && rows+=("$line"); done < <(fleet_candidates)
  local n=${#rows[@]}
  [ "$n" -gt 0 ] || return 0
  local start=0 i rowname
  if [ -n "$cur" ]; then
    i=0
    while [ "$i" -lt "$n" ]; do
      rowname="${rows[$i]%%	*}"
      if [ "$rowname" = "$cur" ]; then start=$(( (i + 1) % n )); break; fi
      i=$((i + 1))
    done
  fi
  i=0
  while [ "$i" -lt "$n" ]; do
    printf '%s\n' "${rows[$(( (start + i) % n ))]}"
    i=$((i + 1))
  done
}

# The rotation with every refused repo removed. Emits `name<TAB>path`.
#
# A REFUSED REPO IS SKIPPED, NOT A WALL. It drops out of the list and the rotation
# carries on past it; a repo that is permanently unsafe must not stall the repos
# behind it forever.
pick_list() {
  local name path remote
  while IFS=$'\t' read -r name path remote; do
    [ -n "$name" ] || continue
    if [ "$path" = "$REPO" ]; then
      printf '%s\t%s\n' "$name" "$path"
      continue
    fi
    if bash "$PREFLIGHT" "$path" "$remote" >/dev/null 2>&1; then
      printf '%s\t%s\n' "$name" "$path"
    else
      say "preflight REFUSED $name ($path); not entering it"
    fi
  done < <(rotation)
}

# --- LIVENESS BEACON: page when the heartbeat COMES BACK ------------------
# Founder ask 2026-07-28: "I want to get a slack notification that the heartbeat
# restarted when it does."
#
# The signal is the TRANSITION (was gone -> is back), never the level. This runs
# every 900s, so paging per tick would be 96 pings a day -- the cry-wolf failure
# that trains someone to mute the channel and costs the real alerts their job.
#
# Placed BEFORE every early exit on purpose. Most ticks legitimately skip (cap
# reached, nothing ready), and a skip is still proof of life. Recording the beat
# only on a dispatch would make a healthy-but-idle loop look dead, and would fire
# a false "resumed" ping on the next dispatch.
#
# A gap larger than GAP_MINUTES means it was not running: reboot, a manual
# unload/load, a crash the launchd watchdog restarted, or the Mac asleep. All
# four are worth one line.
GAP_MINUTES="${KIPI_DISPATCH_GAP_MINUTES:-45}"   # 3 missed ticks at 900s
BEAT_FILE="$HOME/.config/kipi/dispatch-lastbeat"
NOW_EPOCH="$(date -u +%s)"
LAST_BEAT="$(cat "$BEAT_FILE" 2>/dev/null || echo "")"
case "$LAST_BEAT" in ''|*[!0-9]*) LAST_BEAT="" ;; esac

if [ -z "$LAST_BEAT" ]; then
  say "heartbeat: first beat on record"
  page "kipi heartbeat: STARTED. The Linear loop is live and will check for ready issues every 15 min (max ${KIPI_DISPATCH_DAILY_MAX:-4} issues/day). Nothing to do."
else
  GAP=$(( (NOW_EPOCH - LAST_BEAT) / 60 ))
  if [ "$GAP" -ge "$GAP_MINUTES" ]; then
    say "heartbeat: RESUMED after ${GAP}m without a beat"
    page "kipi heartbeat: RESUMED after ${GAP} min down (reboot, sleep, or a reload). The Linear loop is running again. Nothing to do -- this is the all-clear, not a fault."
  fi
fi
printf '%s' "$NOW_EPOCH" > "$BEAT_FILE"

LIVE="$(live_converges)"; LIVE="${LIVE:-0}"
if [ "$LIVE" -ge "$MAX_CONCURRENT" ]; then
  say "skip: $LIVE converge run(s) live, cap $MAX_CONCURRENT"
  exit 0
fi

# --- DAILY BUDGET (loop-exits.md exit 3) ---------------------------------
# The concurrency cap bounds how many run AT ONCE. It does NOT bound how many
# run IN A DAY -- at ~1 issue/hour that is ~24 issues and ~144 `claude -p`
# sessions overnight, against a subscription with a real weekly ceiling.
# Measured 2026-07-28: one interactive night spawned 89 sessions and 44 reviewer
# runs. An unbounded heartbeat is a runaway-bill loop, which is exactly the
# thing loop-exits.md says an autonomous loop must not be.
#
# One issue costs up to MAX_ROUNDS x (1 agent + 1 reviewer) sessions. Do NOT read
# that as a fixed 6: the code default is 3 rounds, but the LOADED plist sets
# KIPI_DISPATCH_ROUNDS=4, so the live cost is up to 8 sessions per issue. The
# older comment here hardcoded 6 and quietly understated the running job by a
# third. Compute it from MAX_ROUNDS, never from a remembered number.
#
# THIS IS NOT A MONEY DIAL (founder correction, 2026-07-29). It caps SESSIONS and
# BLAST RADIUS, not dollars: how many issues per day may enter a loop that merges
# its own PRs. Two ceilings now sit behind it, not one -- since ASK-221 each review
# round is a real codex run, so an issue also spends up to MAX_ROUNDS of a
# separate external quota that did not exist when this number was chosen.
#
# HELD AT 3 on 2026-07-30 (sana's call, the founder does not set this). Reasons,
# in order of weight:
#   1. Per-issue cost went UP since 3 was picked -- 4 rounds instead of 3, plus a
#      codex run per round -- while the number stayed put. Raising it now would
#      compound a cost increase that was never accounted for.
#   2. The loop self-merges and has NO accepted-change instrumentation. That is
#      loop-exits.md's own named blind spot. Raising throughput on a loop that
#      cannot measure whether its output is good buys more blast radius blind.
#   3. The loop is not clean on the first pass, and tonight is the evidence: codex
#      found two majors in PR #46, which was itself the fix for a codex minor. The
#      review rounds are load-bearing, so throughput is not the binding constraint.
#   4. What actually blocked progress was evidence, not rate: the review never
#      reached the PR (sp-48688b24) and the receipt was unreadable (sp-1d1ad606).
#      Raising the cap before those landed would only have produced more
#      invisible reviews. Revisit AFTER an accepted-change signal exists.
DAILY_MAX="${KIPI_DISPATCH_DAILY_MAX:-4}"
# The budget day starts at RESET_HOUR LOCAL, not at midnight and not at UTC.
# Founder-set 2026-07-28, and the reasoning is safety, not tidiness:
#
#   UTC midnight     rolls at 17:00 local -- refills at teatime, leaving the loop
#                    idle through the whole working day it was meant to serve.
#   local midnight   refills the instant the founder falls asleep, handing a full
#                    budget to an unattended overnight run. Worst of the three.
#   local 07:00      overnight can only spend what is LEFT from yesterday, and a
#                    fresh budget arrives when someone is awake to watch it.
#
# Implemented by shifting the clock back RESET_HOUR hours and taking that date,
# so 03:00 Tuesday still belongs to Monday's budget. The file NAME carries the
# label, so the rollover needs no timer, no cron entry and no state machine: a
# new budget day is simply a new filename that reads 0.
RESET_HOUR="${KIPI_DISPATCH_RESET_HOUR:-7}"
# BSD date (macOS) uses -v; GNU date uses -d. Try both so this is not silently
# wrong on a Linux box, where a failed shift would fall back to today's date and
# quietly restore the midnight behaviour.
BUDGET_DAY="$(date -v-"${RESET_HOUR}"H +%Y-%m-%d 2>/dev/null \
              || date -d "-${RESET_HOUR} hours" +%Y-%m-%d 2>/dev/null)"
if [ -z "$BUDGET_DAY" ]; then
  say "FATAL: could not compute the budget day (neither BSD nor GNU date worked)"
  page_once budget-day "kipi dispatch: cannot compute its spend budget window, so it refused to dispatch rather than run uncapped. Do: check \`date -v-7H\` on this machine."
  exit 1
fi
page_clear budget-day
# --- TWO LANES: production and verification -------------------------------
# Founder directive 2026-07-30: "refill the budget for this test -- the budget
# should never stop testing."
#
# The principle, and why a counter reset was the WRONG answer. The cap protects
# production dispatch: sessions, blast radius, an unattended loop that merges its
# own PRs. It was never meant to stop us PROVING the loop works. On 2026-07-30 it
# did exactly that: the day's three slots went to runs that opened no PR, so the
# dispatcher-driven proof could not be attempted at all until 07:00 the next day.
# A gate that blocks verification is not protecting anything.
#
# Resetting the counter would have conflated a test run with a production run and
# put the same wall back tomorrow. So verification gets its OWN budget: its own
# counter file, its own cap, and a visible label in every line it writes. The
# production budget is untouched and still 3 -- the reasoning above the DAILY_MAX
# assignment is unchanged and still holds.
#
# A SEPARATE CAP, NOT NO CAP. "Never stop testing" is not "never bounded": an
# unbounded test lane is the same runaway loop wearing a different label, and the
# codex spend is just as real. Two slots, resetting on the same budget day, is
# enough to run a proof and retry it once.
DISPATCH_LANE="${KIPI_DISPATCH_LANE:-production}"
case "$DISPATCH_LANE" in
  production) COUNT_SUFFIX=""      ; LANE_MAX="$DAILY_MAX" ; LANE_TAG="" ;;
  test)       COUNT_SUFFIX="-test" ; LANE_MAX="${KIPI_DISPATCH_TEST_MAX:-2}" ; LANE_TAG="[test] " ;;
  *) say "FATAL: unknown KIPI_DISPATCH_LANE '$DISPATCH_LANE' (expected production|test)"; exit 1 ;;
esac
# The lane is named in the log on every non-production run, so a test dispatch can
# never be mistaken for the unattended proof later. The proof is a verdict record
# carrying invoker=worker; a lane label in the log is how a human tells which run
# produced it.
[ "$DISPATCH_LANE" = "production" ] || say "${LANE_TAG}lane=$DISPATCH_LANE cap=$LANE_MAX (production budget untouched)"
DAILY_MAX="$LANE_MAX"
COUNT_FILE="$HOME/.config/kipi/dispatch-count$COUNT_SUFFIX-$BUDGET_DAY"
DISPATCHED_TODAY="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"
case "$DISPATCHED_TODAY" in ''|*[!0-9]*) DISPATCHED_TODAY=0 ;; esac

if [ "$DISPATCHED_TODAY" -ge "$DAILY_MAX" ]; then
  # Say it once per day, not every 15 minutes -- a budget ceiling repeated 96
  # times is the cry-wolf failure, and this is not an error state anyway.
  if [ ! -f "$COUNT_FILE.paged" ]; then
    say "${LANE_TAG}DAILY CAP: $DISPATCHED_TODAY/$DAILY_MAX issues dispatched for budget day $BUDGET_DAY (lane=$DISPATCH_LANE), stopping until ${RESET_HOUR}:00 local"
    page "kipi dispatch: hit the daily cap of $DAILY_MAX issues (~$((DAILY_MAX * MAX_ROUNDS * 2)) agent sessions). Not an error -- the loop is resting until ${RESET_HOUR}am, then it picks up again on its own. Do: nothing, or raise KIPI_DISPATCH_DAILY_MAX in com.kipi.dispatch.plist to go faster."
    : > "$COUNT_FILE.paged"
  fi
  exit 0
fi

# gh is what every downstream step needs; failing here with a clear page beats
# dispatching an agent that dies opening its PR.
#
# LOOK FOR IT BEFORE PAGING ABOUT IT. launchd hands a job the bare
# /usr/bin:/bin:/usr/sbin:/sbin, so a gh installed by homebrew is not "missing", it
# is one directory off a minimal PATH -- and "fix PATH in the plist" is a search
# this script can perform itself. Prepending a directory to this process's own PATH
# is scoped to this run and touches nothing on disk, so there is no state to undo.
if ! command -v gh >/dev/null 2>&1; then
  for _ghdir in /opt/homebrew/bin /usr/local/bin "$HOME/.local/bin"; do
    if [ -x "$_ghdir/gh" ]; then
      PATH="$_ghdir:$PATH"; export PATH
      say "self-heal: gh was not on the launchd PATH; found $_ghdir/gh and prepended $_ghdir for this run"
      break
    fi
  done
fi
if command -v gh >/dev/null 2>&1; then
  page_clear gh-missing
fi
if ! command -v gh >/dev/null 2>&1; then
  say "FATAL: gh not on PATH ($PATH)"
  page_once gh-missing "kipi dispatch: gh CLI is not on PATH and I could not find it in the usual install dirs, so no PR can be opened and the Linear loop is stalled. Do: install gh, or add its directory to PATH in com.kipi.dispatch.plist."
  exit 1
fi

# --- WHICH REPO GETS THIS TURN -------------------------------------------
# pick_list() has already refused every candidate that failed its preflight, so
# nothing below has to re-check safety -- and nothing below is allowed to add a
# candidate back.
# Hold the turn across read-select-advance. A dispatcher that cannot get the lock
# is not an error: another one is mid-selection and will advance the cursor.
if ! turn_lock; then
  say "skip: another dispatcher holds the selection turn"
  exit 0
fi
PICKS="$(pick_list)"

# A dry pick list, for proving the gate from outside. It prints what selection
# WOULD choose and exits before any work is claimed or any agent starts. It runs
# AFTER the preflight filter on purpose: a dry run that listed the raw rotation
# would show a repo that the real path refuses, which is a report that lies in the
# safe-looking direction.
if [ "${KIPI_DISPATCH_PICK_DRY:-0}" = "1" ]; then
  printf '%s\n' "$PICKS"
  exit 0
fi

TARGET_NAME=""
TARGET_PATH=""
while IFS=$'\t' read -r PNAME PPATH; do
  [ -n "$PNAME" ] || continue
  TARGET_NAME="$PNAME"
  TARGET_PATH="$PPATH"
  break
done <<PICKEOF
$PICKS
PICKEOF

if [ -z "$TARGET_NAME" ]; then
  say "no dispatchable repo this cycle"
  exit 0
fi

# Aim the worker AND the converge run at the repo whose turn this is. The worker
# resolves its own project identity from this path, so asking it what is ready
# without passing it would return the HOME repo's queue and then dispatch that
# answer against another repo -- work for one project landing in another.
#
# Two carriers for one fact, because they cross different boundaries: --repo is
# the explicit argument, and KIPI_TARGET_REPO is inherited through converge.sh,
# which forwards only its own arguments to the worker.
WORK_ARGS=""
if [ "$TARGET_PATH" != "$REPO" ]; then
  # HELD: cleared preflight, and STILL not entered (sp-9421b9b7).
  #
  # The worker's --repo argument redirects `git -C`, and that part is built and
  # tested. It does NOT redirect `gh`, and codex found three paths that silently
  # bind to the home checkout anyway:
  #   1. the worker's existing-PR lookup, merge-state/head queries and reviewer
  #      invocation are unqualified `gh` calls;
  #   2. converge.sh runs pr_for_branch / pr_head_sha from the home checkout, so
  #      after the worker opens a PR in the target it finds none and stops;
  #   3. pr-review-agent.sh derives its repo from its own location, so an external
  #      PR number resolves against the HOME repo -- and if that number exists,
  #      the wrong code is reviewed and gets the verdict.
  # Review artifacts are also keyed pr-<number>.* in one shared state dir, so two
  # repos with PR #42 consume each other's records.
  #
  # Any one of those is enough to act on the wrong repository, and two of the
  # three files are outside this issue's contract. A gate that lets an agent into
  # a client repo on that footing is worse than the gap it closes, so entry stays
  # shut until the gh-scoping issue lands. The rotation still OFFERS the turn and
  # advances past it, so nothing starves behind this.
  say "HOLD $TARGET_NAME: cleared preflight, but cross-repo gh scoping is unfinished (sp-9421b9b7); not entering"
  exit 0
fi
# Consume the turn HERE, not after a successful dispatch. A repo that took its turn
# and had nothing ready must still hand the next turn on, or an idle home repo
# pins the rotation and the fleet starves exactly as it does today.
cursor_set "$TARGET_NAME"

WORK_OUT="$(bash ./kipi work $WORK_ARGS 2>&1)"
WORK_RC=$?

# An infra error (Linear down, auth expired) is environmental: it will not
# self-heal on the next heartbeat, so say so once rather than fail silently
# every 15 minutes forever. self-healing-retry.md rule 5.
if printf '%s' "$WORK_OUT" | grep -qi "infra_error\|authentication\|unauthorized"; then
  say "infra error from kipi work: $(printf '%s' "$WORK_OUT" | head -3 | tr '\n' ' ')"
  page_once linear-down "kipi dispatch: Linear is unreachable or auth expired, so NO issues can be picked up. The loop is stopped, not slow. Do: run \`bash kipi work\` by hand and check the Linear token."
  exit 1
fi
page_clear linear-down

NEXT="$(printf '%s' "$WORK_OUT" | grep -oE '\[dry\] would work ASK-[0-9]+' | grep -oE 'ASK-[0-9]+' | head -1)"
if [ -z "$NEXT" ]; then
  say "nothing ready ($(printf '%s' "$WORK_OUT" | grep -oE '[0-9]+ ready issue' | head -1))"
  exit 0
fi

# Belt and braces against the race between dispatch and the In Progress
# transition: two converge runs on one issue would fight over one worktree.
#
# NOT pgrep, and NOT \b (PR #39 review, finding 2). BSD pgrep reads `\b` as a
# literal `b`, so this guard has never fired on macOS -- the only platform it
# runs on. It was harmless while every dispatched child was being reaped
# instantly; the moment children survive (the fix below), it becomes reachable
# and lets a second converge start on an issue that already has one. Same
# `ps -Ao args=` form and same [c] self-match guard as the liveness check.
# NO PIPE INTO grep -q, and that is the whole point (PR #39 review r3,
# finding 1). `ps ... | grep -q` under `set -o pipefail` fires only sometimes:
# grep -q exits the instant it matches, ps then takes SIGPIPE and dies 141, and
# pipefail makes 141 the status of the whole pipeline -- so the `if` does NOT
# run its body. Whether ps has finished writing before grep leaves is a race,
# so the guard worked load-dependently, which is worse than never working
# because it looks fine when you test it by hand.
#
# A snapshot into a variable plus bash's own =~ removes the pipeline entirely,
# so there is nothing to SIGPIPE and nothing for pipefail to poison. It also
# removes the need for the [c] self-match trick: with no grep process there is
# no grep command line in the table to match.
PS_SNAPSHOT="$(ps -Ao args= 2>/dev/null || true)"
if [[ "$PS_SNAPSHOT" =~ converge\.sh\ --issue\ ${NEXT}([[:space:]]|$) ]]; then
  say "skip $NEXT: a converge run for it is already live"
  exit 0
fi

# Count BEFORE launching. Counting after would let a crash between the two
# hand out a free dispatch every heartbeat -- the budget must fail closed.
printf '%s' "$((DISPATCHED_TODAY + 1))" > "$COUNT_FILE"

say "${LANE_TAG}dispatching $NEXT (live=$LIVE cap=$MAX_CONCURRENT rounds=$MAX_ROUNDS budget=$((DISPATCHED_TODAY + 1))/$DAILY_MAX lane=$DISPATCH_LANE)"

# THE CHILD NEEDS ITS OWN SESSION, AND THIS IS NOT A STYLE CHOICE.
#
# This was `nohup ... & disown`, which is correct in an interactive shell and
# WRONG under launchd. launchd reaps the job's whole process group when the main
# process exits; nohup only blocks SIGHUP, so the converge was killed the instant
# this script returned. Every launchd dispatch since the dispatcher was installed
# died that way, and the failure was invisible by construction: the log file is
# created by the redirect before the child dies, so it exists and is 0 bytes,
# `say "dispatched $NEXT"` still runs, and the budget counter is already spent.
# The loop reported four healthy dispatches of ASK-224 on 2026-07-28 and did no
# work at all -- it only spent the subscription.
#
# PROVEN, not reasoned about. A launchd job whose only act was
# `nohup bash -c "sleep 25; touch F" & disown; exit`:
#     under launchd   F never written  (child killed)
#     same script from an interactive shell   F written (child survived)
# and with the setsid form below, under launchd, F is written.
#
# macOS ships no setsid(1), so python3 is how setsid(2) gets called. A new
# session means a new process group with no controlling terminal, which is
# outside the group launchd tears down.
CONVERGE_LOG="$HOME/.config/kipi/converge-$NEXT.log"
# A RUN BOUNDARY, because the log is appended (PR #39 review, finding 3). The
# failure page points the operator at this file; without a marker they cannot
# tell where a re-dispatch's output starts and are reading the previous run's
# tail as if it were this one's.
printf '\n===== dispatch %s  %s  rounds=%s =====\n' \
  "$NEXT" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$MAX_ROUNDS" >> "$CONVERGE_LOG"

CHILD_PID="$(python3 - "$CONVERGE_LOG" \
         ./kipi converge --issue "$NEXT" --max-rounds "$MAX_ROUNDS" <<'PY'
import subprocess, sys
log_path, argv = sys.argv[1], sys.argv[2:]
# Append, never truncate: a re-dispatch of the same issue must not erase the
# evidence of the previous run (the burst incident truncated a live log with >).
log = open(log_path, "ab", buffering=0)
p = subprocess.Popen(argv, stdout=log, stderr=log, start_new_session=True)
# The PID is the whole point: the caller has to watch THE CHILD IT LAUNCHED,
# not "some converge for this issue". `kipi` runs converge.sh with bash rather
# than exec, so this pid stays alive exactly as long as the run does.
print(p.pid)
PY
)"
RC=$?
if [ "$RC" -ne 0 ]; then
  # A launch that failed must NOT report success -- that is the same shape as
  # the bug above. The budget slot is already spent, so say so plainly.
  say "FAILED to launch converge for $NEXT (rc=$RC); the budget slot is spent"
  page "kipi dispatch: could not launch the converge run for $NEXT, so NO work is happening even though the loop looks alive. Do: run \`bash kipi-dispatch.sh\` by hand and read the error."
  exit 1
fi

# PROVE IT IS ALIVE BEFORE CLAIMING IT. The whole defect above was a dispatch
# that reported success into a void, so the report is now evidence-backed: the
# process either shows up in the table or the founder hears about it.
#
# NOT `pgrep -f "...$NEXT\b"`. \b is a GNU regex extension and BSD pgrep (macOS,
# where this actually runs under launchd) does not honour it, so that pattern
# never matches and a HEALTHY run gets reported as died -- a false alarm is how
# an alert earns itself muted. The boundary is done in grep, which does support
# it, against `pgrep -fl` output.
#
# WATCH THE PID, NOT THE PROCESS TABLE (PR #39 review, finding 1). Asking "is
# some converge for this issue running?" lets an UNRELATED live converge answer
# on the dead child's behalf -- which is the exact silent-success hole this
# check exists to close, rebuilt one layer up. The reachable chain the reviewer
# walked: the duplicate guard above was dead on macOS, so a second converge
# started while one was live, converge.sh refused the claim and that child died
# instantly, and the table still held converge #1. Success reported, budget
# spent, nobody paged.
#
# `kill -0` sends no signal; it only asks whether the pid is still there.
# Checked every second rather than once, so a child that dies at t+4 is caught
# too -- "alive at least once" would pass a run that fell over immediately after
# starting, which is most of the ways this actually fails.
DISPATCH_OK=0
case "$CHILD_PID" in
  ''|*[!0-9]*)
    say "DISPATCH DIED: no child pid was returned for $NEXT"
    ;;
  *)
    DISPATCH_OK=1
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      if ! kill -0 "$CHILD_PID" 2>/dev/null; then DISPATCH_OK=0; break; fi
      sleep 1
    done
    ;;
esac
if [ "$DISPATCH_OK" -eq 1 ]; then
  say "dispatched $NEXT (confirmed running)"
else
  say "DISPATCH DIED: $NEXT was launched but no converge process is alive after 10s"
  page "kipi dispatch: $NEXT was launched but died immediately -- the loop is spending budget and doing no work. Do: check ~/.config/kipi/converge-$NEXT.log and whether launchd is reaping the child."
  exit 1
fi
exit 0
