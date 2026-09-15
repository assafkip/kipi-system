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

REPO="${KIPI_REPO:-/Users/assafkipnis/projects/kipi-system}"
# HARDCODED OFF $REPO, DELIBERATELY NOT AN ENV VAR. Every other path in this file
# takes a KIPI_* override for testability; this one must not. A variable here would
# be a documented way to aim the client-repo safety gate at /bin/true while every
# log line still read normally. The tests drive the real script and stub `gh` by
# prepending to PATH instead, which adds no knob to the shipped code.
PREFLIGHT="$REPO/q-system/.q-system/scripts/repo-preflight.sh"
LOG="$HOME/.config/kipi/dispatch.log"
# THE GLOBAL CAP IS NOW A SPEND CEILING, NOT THE CONFLICT GUARD (ASK-804).
# One-run-per-repo is enforced structurally in the selection loop below, so this
# number no longer decides whether two agents can collide on a file -- it decides
# how many `claude -p` pairs may be in flight at once.
#
# 3 IS DERIVED, NOT PICKED. Measured from instance-registry.json 2026-08-14:
# exactly two instances carry dispatch.enabled true, plus the home repo this
# script runs out of, which the selection loop treats as its own dispatchable
# target. Three repos, one run each, so a fourth slot could never be filled by a
# conflict-free pick anyway. Raising it past the number of dispatchable repos
# buys nothing and only loosens the spend bound.
MAX_CONCURRENT="${KIPI_DISPATCH_MAX:-3}"
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
# ONE LOCK PRIMITIVE, used by BOTH page_once and page_clear, so a clear cannot
# interleave with a decision. mkdir is the atomic claim.
#
# AN ORPHANED LOCK MUST AGE OUT. Treating any existing lock dir as a live holder
# meant a notifier killed between the mkdir and its cleanup -- launchd reaping the
# job, a reboot, a SIGKILL -- silenced that key PERMANENTLY. Reproduced: leave the
# dir behind and the next three runs page 0, 0, 0 while the log cheerfully reports
# "another dispatcher is already deciding it" with nobody there.
#
# The critical section is a stat, a notifier call and a small write, so anything
# still holding this after 300s is dead. That is well under the 900s heartbeat, so
# an orphan always self-clears before the next beat rather than needing a human.
page_lock() {
  local lock="$1" now lock_mtime lock_probe
  mkdir "$lock" 2>/dev/null && return 0
  now="$(date -u +%s)"
  lock_probe="$(stat -c %Y "$lock" 2>/dev/null)"
  case "$lock_probe" in ''|*[!0-9]*) lock_probe="" ;; esac
  [ -n "$lock_probe" ] || { lock_probe="$(stat -f %m "$lock" 2>/dev/null)"; case "$lock_probe" in ''|*[!0-9]*) lock_probe="" ;; esac; } # portability-lint-skip
  lock_mtime="$lock_probe"
  # An unreadable mtime means DO NOT REAP: skipping one page is recoverable,
  # stealing a live lock and double-paging is the bug this exists to prevent.
  if [ -n "$lock_mtime" ] && [ "$(( now - lock_mtime ))" -gt 300 ]; then
    say "page lock: reaping an orphaned lock at $lock ($(( now - lock_mtime ))s old; a notifier was killed mid-decision)"
    rmdir "$lock" 2>/dev/null || true
    mkdir "$lock" 2>/dev/null && return 0
  fi
  return 1
}

# CLEARS UNDER THE SAME LOCK. Unlocked, page_clear could run between page_once
# deciding to page and page_once WRITING its marker: the clear finds nothing to
# remove, the write lands a moment later, and a marker now describes a condition
# that has already recovered -- suppressing the next real episode for up to 24h.
# A marker outliving its condition, which is the orphaned-lock shape again.
#
# Taking the lock makes the two strictly ordered. If the lock is held we do NOT
# block a heartbeat waiting: log it and leave it, and the next healthy beat clears
# it. That bounds the stale-marker window to one heartbeat (<=15m) instead of the
# full 24h re-ping. That residual is deliberate and stated rather than hidden.
page_clear() {
  local key="$1" mark lock
  mark="$(dirname "$LOG")/paged-$key"
  lock="$mark.lock"
  # Nothing to clear and nobody mid-decision: stay cheap on the healthy path, which
  # is every single beat.
  [ -f "$mark" ] || [ -d "$lock" ] || return 0
  if ! page_lock "$lock"; then
    say "page state NOT cleared ($key): a notifier is mid-decision; the next healthy beat clears it"
    return 0
  fi
  if [ -f "$mark" ]; then
    rm -f "$mark" 2>/dev/null || true
    say "page state cleared: $key recovered, so a recurrence pages again immediately"
  fi
  rmdir "$lock" 2>/dev/null || true
}

page_once() {
  local key="$1" msg="$2" mark hash now prev stamp lock
  mark="$(dirname "$LOG")/paged-$key"
  hash="$(printf '%s' "$msg" | cksum | tr -d ' \n')"
  now="$(date -u +%s)"
  # READ-CHECK-WRITE UNDER ONE LOCK. Unlocked, two dispatchers both stat a missing
  # marker, both decide to page, and the founder gets the identical line twice --
  # a dedupe that produces duplicates is worse than none, because nobody re-checks it.
  # (Wording note: test-repo-preflight.sh case 8 word-matches this whole FILE,
  # comments included, for terms that would let a repo opt out of the preflight. A
  # few ordinary English words are therefore unusable in comments here. Reworded
  # rather than loosening a client-repo safety gate to suit my own prose. sp-cc67d834.)
  # mkdir is the atomic primitive; a lock we cannot take means another process is
  # already handling this exact key, so staying quiet is the correct answer.
  # AN ORPHANED LOCK MUST AGE OUT. The first cut treated any existing lock dir as a
  # live holder forever, so a notifier killed between the mkdir and its cleanup --
  # launchd reaping the job, a reboot, a SIGKILL -- silenced that key PERMANENTLY.
  # Reproduced: leave the dir behind and the next three runs page 0, 0, 0, while the
  # log cheerfully reports "another dispatcher is already deciding it" with nobody
  # there. A dedupe that becomes a permanent mute is worse than no dedupe, and it is
  # the same guard-that-can-never-fire shape this very audit flagged elsewhere --
  # introduced by the fix for the previous one.
  #
  # The critical section is a stat and a small write, so anything still holding this
  # after 300s is dead. That is far below the 900s heartbeat, so an orphan always
  # self-clears before the next beat rather than needing a human.
  lock="$mark.lock"
  if ! page_lock "$lock"; then
    say "page skipped ($key): another dispatcher is already deciding it"
    return 0
  fi
  # RELEASED EXPLICITLY AT EVERY EXIT, NOT BY A `trap ... RETURN`.
  # The trap form looked tidier and was broken: bash tears down the function's
  # locals before running the RETURN trap, so `rmdir "$lock"` hit an unset variable
  # and `set -u` killed the whole dispatcher mid-page. It surfaced as four unrelated
  # test failures at once (a missing verdict, two missing log lines) because the
  # script simply stopped. Three exits, three rmdirs, no cleverness.
  if [ -f "$mark" ]; then
    prev="$(sed -n 1p "$mark" 2>/dev/null)"
    stamp="$(sed -n 2p "$mark" 2>/dev/null)"
    case "$stamp" in ''|*[!0-9]*) stamp=0 ;; esac
    if [ "$prev" = "$hash" ] && [ "$(( now - stamp ))" -lt "$PAGE_REPING_SECONDS" ]; then
      say "page suppressed ($key unchanged for $(( (now - stamp) / 60 ))m; re-pings after $(( PAGE_REPING_SECONDS / 3600 ))h)"
      rmdir "$lock" 2>/dev/null || true
      return 0
    fi
  fi
  if page_ok "$msg"; then
    printf '%s\n%s\n' "$hash" "$now" > "$mark" 2>/dev/null || true
  else
    say "page: $key did NOT go out; leaving the marker unset so the next heartbeat retries it"
  fi
  rmdir "$lock" 2>/dev/null || true
}

cd "$REPO" 2>/dev/null || {
  say "FATAL: repo not found at $REPO"
  page_once repo-missing "kipi dispatch: repo not found at $REPO -- the Linear loop is DEAD. Do: check the path in com.kipi.dispatch.plist."
  exit 1
}
page_clear repo-missing

# --- SELECTOR-DRIFT GUARD (ASK-355, from sp-d319d541):BEGIN -----------------
# THIS FILE RUNS FROM THE FOUNDER'S WORKING TREE, so which branch is checked out
# decides what the 15-minute heartbeat can do. During ASK-352 the reviewer-redrive
# selector drove the real loop from an unmerged branch; a branch switch in that
# checkout reverts the wiring mid-flight and this script keeps exiting 0 while
# doing strictly less than it did a minute earlier.
#
# It is ADDITIVE LOSS, not corruption -- nothing is written wrong, the loop just
# quietly does less -- which is exactly why nothing catches it. No error, no red
# gate, no page. The capability manifest checks declared-vs-actual per TEST FILE;
# it never asks whether the RUNNING dispatcher still has a call site it had a run
# ago. So the guard has to live here, in the thing whose own wiring is at stake.
#
# PLACED BEFORE stale_check, DELIBERATELY. A branch switch is the very event that
# both drops a selector AND makes this checkout look stale, and stale_check exits
# the script. Behind it, this guard would be mute in the one scenario it exists
# for. It is also cheap: two stats and one awk over this file, no network.
#
# RESOLVED MEANS BOTH HALVES. A selector is resolved when its script exists under
# $REPO *and* this running copy still references it from a non-comment line.
# Statting the path alone would report "healthy" for a dispatcher that no longer
# calls the thing -- the silent downgrade with a green light on it.
SELECTOR_SELF="${BASH_SOURCE[0]}"
SELECTOR_STATE="$(dirname "$LOG")/redrive-selectors.state"
SELECTOR_NAMES="ci-redrive.py review-redrive.py"

# The awk SKIPS this whole guard block, which is why the BEGIN/END markers are
# load-bearing and not decoration: SELECTOR_NAMES above names both selectors, so
# without the skip every selector would always look referenced and the call-site
# half would grade nothing. Comments are stripped before the match for the same
# reason -- the redrive blocks below are surrounded by prose naming them.
#
# AND A RANGE THAT MATCHES NOTHING MUST SAY SO, NOT RETURN A NUMBER. Two live
# defects were found here in one sitting, both green at the time:
#
#  1. The skip was anchored on `GUARD \(ASK-355\):BEGIN` while the marker reads
#     `GUARD (ASK-355, from sp-d319d541):BEGIN`. It never armed, SELECTOR_NAMES
#     counted as a live call site, and every selector read as resolved forever.
#  2. The fix put the marker pattern INSIDE the awk program -- which awk then read
#     off this very file and matched against ITSELF. So "the marker is missing"
#     could never be true, and the mutation written to prove that branch survived.
#
# Hence: the block bounds are found by `grep -n` for a marker anchored at `^# --- `,
# a shape the grep source line (indented, quoted) cannot wear, and the range is
# excluded BY LINE NUMBER. No marker found means the guard cannot answer (rc 2) --
# the caller then pages about the guard rather than reporting health it never
# measured. Same lesson as the LINEAR-OUTAGE-GUARD anchors: a fixture must not be
# anchored to the text it is testing.
SELECTOR_UNREADABLE=2
selector_resolved() {
  local sel="$1" refs begin_line end_line
  begin_line="$(grep -n '^# --- SELECTOR-DRIFT GUARD .*:BEGIN' "$SELECTOR_SELF" 2>/dev/null | head -1 | cut -d: -f1)"
  end_line="$(grep -n '^# --- SELECTOR-DRIFT GUARD .*:END' "$SELECTOR_SELF" 2>/dev/null | head -1 | cut -d: -f1)"
  case "$begin_line$end_line" in ''|*[!0-9]*) return "$SELECTOR_UNREADABLE" ;; esac
  [ "$end_line" -gt "$begin_line" ] || return "$SELECTOR_UNREADABLE"
  refs="$(awk -v sel="$sel" -v b="$begin_line" -v e="$end_line" '
    NR >= b && NR <= e { next }
    { line = $0; sub(/#.*/, "", line); if (index(line, sel)) n++ }
    END { print n + 0 }
  ' "$SELECTOR_SELF" 2>/dev/null)"
  case "$refs" in ''|*[!0-9]*) return "$SELECTOR_UNREADABLE" ;; esac
  [ -f "$REPO/q-system/.q-system/scripts/$sel" ] || return 1
  [ "$refs" -gt 0 ]
}

selector_now() {
  local sel rc
  for sel in $SELECTOR_NAMES; do
    selector_resolved "$sel"; rc=$?
    case "$rc" in
      0) printf '%s present\n' "$sel" ;;
      "$SELECTOR_UNREADABLE") printf '%s unreadable\n' "$sel" ;;
      *) printf '%s absent\n' "$sel" ;;
    esac
  done
}

selector_prev() { awk -v s="$1" '$1 == s { print $2 }' "$SELECTOR_STATE" 2>/dev/null; }

# THE ONLY WRITER OF $SELECTOR_STATE. Temp-then-rename, so a run killed mid-write
# leaves the previous run's answer intact rather than a truncated file that would
# read as "this selector was never resolved" and swallow the next real loss.
selector_state_write() {
  local body="$1" tmp="$SELECTOR_STATE.tmp.$$"
  printf '%s' "$body" > "$tmp" 2>/dev/null || { rm -f "$tmp" 2>/dev/null; say "selector drift: could not write $SELECTOR_STATE"; return 1; }
  mv -f "$tmp" "$SELECTOR_STATE" 2>/dev/null || { rm -f "$tmp" 2>/dev/null; say "selector drift: could not replace $SELECTOR_STATE"; return 1; }
}

# PAGE ON THE TRANSITION, NEVER ON THE LEVEL -- the same shape the liveness beacon
# already takes. This runs every 900s, so a state-based page is 96 identical Slack
# lines a day, which is how an alert trains someone to skim the channel.
#
# RECOVERY PAGES TOO. An operator who never hears the selector come back cannot
# tell a degraded loop from a healthy one; note_degraded_transition in
# pr-review-agent.sh already takes that posture and this matches it. Each
# direction clears the other's marker, so a flap inside the re-ping window is
# still heard.
#
# A FIRST RUN IS SILENT. With no previous record there is nothing to have lost,
# and paging on first sighting would fire once per fresh machine and once per
# state-file loss -- noise about the guard rather than about the loop.
selector_drift_check() {
  local now sel prev cur head branch
  now="$(selector_now)"
  head="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
  # THE GUARD CANNOT READ ITSELF -> SAY SO AND CHANGE NOTHING. Writing this run's
  # answer would overwrite a good baseline with a measurement that was never made,
  # and comparing against it would page for the wrong reason. Loud and inert beats
  # quiet and wrong.
  if printf '%s\n' "$now" | grep -q ' unreadable$'; then
    say "SELECTOR GUARD BROKEN: could not find its own BEGIN/END markers in $SELECTOR_SELF, so it measured nothing this run (branch $branch, HEAD $head)"
    page_once selector-guard-broken "kipi dispatch: the redrive selector drift guard cannot read its own block markers in $SELECTOR_SELF (branch $branch, HEAD $head), so it is measuring nothing. Do: restore the SELECTOR-DRIFT GUARD BEGIN/END marker lines."
    return 0
  fi
  page_clear selector-guard-broken
  if [ -f "$SELECTOR_STATE" ]; then
    for sel in $SELECTOR_NAMES; do
      prev="$(selector_prev "$sel")"
      cur="$(printf '%s\n' "$now" | awk -v s="$sel" '$1 == s { print $2 }')"
      [ -n "$prev" ] || continue
      [ "$prev" = "$cur" ] && continue
      if [ "$cur" = "absent" ]; then
        say "SELECTOR DRIFT: the redrive selector $sel resolved on the previous run and is gone now (branch $branch, HEAD $head)"
        page_clear "selector-back-$sel"
        page_once "selector-gone-$sel" "kipi dispatch: the redrive selector $sel is GONE from the running dispatcher (branch $branch, HEAD $head). The 15-min loop still exits 0 while doing strictly less than it did last run. Do: check out or merge the branch that carries it."
      else
        say "SELECTOR RECOVERED: the redrive selector $sel is resolved again (branch $branch, HEAD $head)"
        page_clear "selector-gone-$sel"
        page_once "selector-back-$sel" "kipi dispatch: the redrive selector $sel is BACK (branch $branch, HEAD $head). The loop is running its full set of redrives again. Nothing to do -- this is the all-clear."
      fi
    done
  fi
  selector_state_write "$now"
}
selector_drift_check
# --- SELECTOR-DRIFT GUARD (ASK-355, from sp-d319d541):END -------------------

# --- STALE-CHECKOUT REFUSAL (sp-c775b116) --------------------------------
# The loop runs the founder's WORKING TREE, and nothing kept it in sync with
# main. There is no `git pull` anywhere in this script. Observed 2026-07-30:
# merging PR #34 left this checkout at 1597eaf, so the loop would have gone on
# running the old Claude-only reviewer indefinitely while main carried the codex
# gate. It was fixed by hand twice in one session, which means every future merge
# silently depended on someone remembering.
#
# A DETECTOR, NOT A PULL -- and that is now a MEASURED position, not a default.
# An automatic `git merge --ff-only` was built here on 2026-08-02 and REMOVED the
# same night after three review rounds, each of which found a new way for it to
# lose data (ASK-284 carries the design and everything learned):
#   r1  ignored files are silently overwritten by a fast-forward. Measured: an
#       untracked-not-ignored collision ABORTS, an IGNORED one fast-forwards with
#       exit 0 and no reflog, and `ls-files --others --exclude-standard` cannot
#       see that class at all (3982 of them on this checkout).
#   r2  the backup added to fix r1 continued the merge when a copy FAILED, and the
#       lock added alongside it could silence an alert key forever.
# Each round was smaller and each still produced a new instance of the same class.
# That is a statement about the surface, not about care taken. Writing to a live
# working tree with no recovery path for an untracked file is not something to
# converge on at 3am; it gets designed on its own.
#
# What survives is the half with no write surface outside ~/.config/kipi: refuse,
# and page ONCE per episode instead of once per commit.
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
  # Recovery is a DEFINITIVE not-behind answer, so the next episode pages at once.
  # Deliberately not on the fetch-failed paths above: offline is not proof of health.
  [ "$local_head" != "$remote_head" ] || { page_clear stale-checkout; return 0; }
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
  [ "$base" -gt 0 ] || { page_clear stale-checkout; return 0; }
  say "STALE: origin/main holds $base commit(s) this checkout lacks (HEAD ${local_head:0:7}, origin/main ${remote_head:0:7}). Dispatching would run superseded control code and auto-merge the result."

  # ONE PAGE PER STALE EPISODE, NOT ONE PER COMMIT.
  # The measured complaint: 19 refusing cycles overnight sent 9 Slack pages, one
  # for every new commit that landed on main while the checkout sat behind. The
  # per-sha dedupe that produced those 9 was working exactly as written -- the key
  # was simply wrong. It treated "origin/main moved again" as a new fault, when the
  # fault is one unchanged thing: THIS CHECKOUT IS BEHIND AND CANNOT DISPATCH.
  #
  # So the key is a constant and the MESSAGE carries no volatile detail. Counts and
  # shas go to the log, which is free, not to the founder's phone, which is not.
  # page_clear on the healthy path below turns a recovery into silence and makes the
  # NEXT episode page immediately, which is what a per-sha key was reaching for.
  page_once stale-checkout "kipi dispatch: paused -- this checkout is behind origin/main, so it will not dispatch (it would run superseded control code and auto-merge the result). Do: cd $REPO && git merge --ff-only origin/main. The loop resumes by itself once the checkout is current."
  return 1
}
stale_check || exit 0

# `pgrep -c` exits 1 with no match, which under `set -e` would look like failure
# and under a bare assignment yields an empty string. Force a number.
# COUNTS DISPATCH'S OWN RE-REVIEW CHILDREN -- AND ONLY ITS OWN.
#
# A dispatch does not always launch a converge. On a reviewer redrive it launches
#   bash .../pr-review-agent.sh <PR> --issue ASK-nnn --post
# which a `converge.sh --issue` pattern never matched, so those children spent a
# `claude -p` pair outside the cap.
#
# WIDENING THE pgrep PATTERN TO MATCH THEM WAS WRONG, AND IT STOPPED DISPATCH IN
# PRODUCTION. Measured 2026-08-14T23:46:15Z, first tick after arming:
#   skip: 5 converge run(s) live, cap 3
# There were ZERO converges. All five were pr-review-agent processes belonging to
# an interactive session reviewing PRs by hand. pgrep reads the machine-wide
# process table and cannot tell dispatch's child from anyone else's, so ordinary
# review work became a hard block on the whole loop. That is strictly worse than
# the under-count it replaced: the old bug leaked some spend, this one dispatched
# nothing at all.
#
# So the two populations are counted from the two sources that can actually
# identify them:
#   - CONVERGES via pgrep, because a hand-run converge SHOULD count -- it is real
#     work in a repo and the cap exists to bound exactly that;
#   - RE-REVIEWS via the ledger, because only dispatch writes it, so a row there
#     is by construction a child dispatch launched.
# A third party's review is in neither, which is the point.
LIVE_PATTERN="${KIPI_DISPATCH_LIVE_PATTERN:-converge\.sh --issue}"

live_converges() {
  local conv rr pid issue repo
  conv="$(pgrep -f "$LIVE_PATTERN" 2>/dev/null | grep -c . || true)"
  conv="${conv:-0}"
  rr=0
  if [ -f "$LIVE_LEDGER" ]; then
    while IFS=$'\t' read -r pid issue repo; do
      case "$pid" in ''|*[!0-9]*) continue ;; esac
      kill -0 "$pid" 2>/dev/null || continue
      # Only the re-review shape; a dispatch-launched converge is already in conv.
      ps -p "$pid" -o args= 2>/dev/null | grep -q 'pr-review-agent' || continue
      ps -p "$pid" -o args= 2>/dev/null | grep -qE -- "--issue $issue([[:space:]]|\$)" || continue
      rr=$((rr + 1))
    done < "$LIVE_LEDGER"
  fi
  printf '%s' "$((conv + rr))"
}

# --- PER-REPO CONCURRENCY (sp-e45251f7) --------------------------------------
# WHY THE GLOBAL CAP WAS 1, AND WHY THIS IS THE HONEST WAY TO RAISE IT.
#
# com.kipi.dispatch pinned KIPI_DISPATCH_MAX=1 with a written precondition:
# "Raise this only once dispatch is file-disjointness aware." That was correct.
# The dispatcher picks by READINESS and has no idea which files an issue touches,
# so two concurrent runs IN ONE REPO can land on the same file -- observed
# 2026-07-28, ASK-223 editing the same linear-worker.sh region as the live
# ASK-222. Unattended, that yields conflicted PRs, which is worse than half the
# throughput.
#
# TWO RUNS IN DIFFERENT REPOS CANNOT CONFLICT. They share no working tree, no
# branch namespace and no file. So the conflict argument -- the whole reason the
# cap was 1 -- says nothing about cross-repo concurrency. This makes the rule
# structural instead of numeric: the GLOBAL cap becomes a spend ceiling, and
# a BUSY-REPO PREFERENCE is applied where a repo is chosen: a repo with a live
# run is deprioritised, and taken only when it is the only candidate.
#
# NOT A GUARANTEE, AND THE WORDING MATTERS (codex major, PR #163 r2). An earlier
# version of this comment said "at most ONE live run per repo is enforced", which
# the fallback below plainly does not do. A safety claim in a comment that the
# code does not keep is how the next person reasons themselves into raising the
# cap. What is enforced is the preference plus the GLOBAL cap; same-repo overlap
# is possible when only one repo is dispatchable, and that is ASK-811.
#
# This deliberately does NOT unlock same-repo concurrency. File-disjointness is
# still unbuilt, and sp-f3a2ad81 shows why the obvious version is not enough:
# capability-manifest.json WAS a magnet file every test-adding issue appended
# to (resolved 2026-08-29: it is a per-declaration fragment directory now),
# so a naive disjointness rule would serialize the whole board on it anyway
# (sp-4caf5d7b measured 19 of 22 conflicting PRs conflicting on that one file).
# Cross-repo is the slice that is safe TODAY, on the conflict argument's own terms.
#
# WHY A LEDGER AND NOT pgrep. The converge argv is `./kipi converge --issue N`;
# the target repo crosses as the KIPI_TARGET_REPO env var, which converge.sh
# inherits. Environment is not in the process command line, so pgrep can count
# live runs but CANNOT attribute one to a repo. Recording the pair at launch is
# what makes the question answerable at all.
LIVE_LEDGER="${KIPI_DISPATCH_LIVE_LEDGER:-$HOME/.config/kipi/dispatch-live.tsv}"

# A pid alone is not proof: pids are reused, and a recycled pid pointing at some
# unrelated process would hold a repo hostage forever. Both halves must agree --
# the pid is alive AND that pid is still the converge for that issue.
live_repos() {
  [ -f "$LIVE_LEDGER" ] || return 0
  local pid issue repo
  while IFS=$'\t' read -r pid issue repo; do
    case "$pid" in ''|*[!0-9]*) continue ;; esac
    [ -n "$repo" ] || continue
    kill -0 "$pid" 2>/dev/null || continue
    # BOUNDED, because ASK-10 is a prefix of ASK-100 (codex minor, PR #163).
    # A plain substring match let a live ASK-100 converge satisfy the identity
    # check for a dead ASK-10 row, marking the wrong repo busy until the real
    # process exited. The id must be followed by whitespace or end-of-line.
    ps -p "$pid" -o args= 2>/dev/null | grep -qE -- "--issue $issue([[:space:]]|\$)" || continue
    printf '%s\n' "$repo"
  done < "$LIVE_LEDGER"
}

# Append-only at launch; compacted here so a long-lived box does not grow the
# file without bound. Compaction rewrites via temp+rename so a reader never sees
# a torn file.
# A FAILED LEDGER WRITE IS NOT A SUCCESSFUL ONE (codex major, PR #163 r1).
#
# This ended in `|| true`, which is the right instinct for a notifier and the
# wrong one here. An unwritten row means the run is invisible to live_repos(),
# which silently DISABLES the per-repo exclusion for that repo -- the guard is
# off and nothing says so. Read-only .config, a full disk, or a bad permission
# all produce exactly that, quietly.
#
# It still must not take dispatch down: the run has already been launched and
# killing the script here would strand it. So the write is checked, and a failure
# is made LOUD instead of fatal.
#
# AND THE PAGE SAYS WHAT IS ACTUALLY TRUE (codex major, PR #163 r2). An earlier
# version of this text promised "dispatch will refuse to enter any repo until it
# finishes", which was true of the unattributed-run HALT that used to sit in the
# selection loop. That halt was removed -- it broke test-dispatch-liveness 6a and
# turned one hand-run converge into a fleet-wide stall -- and the promise was left
# behind. A page that describes a guard which no longer exists is worse than no
# page: it is read at the exact moment someone is deciding whether to act. The
# honest consequence is that the repo may be picked again.
record_live_run() {
  local pid="$1" issue="$2" repo="$3"
  mkdir -p "$(dirname "$LIVE_LEDGER")" 2>/dev/null || true
  if ! printf '%s\t%s\t%s\n' "$pid" "$issue" "$repo" >> "$LIVE_LEDGER" 2>/dev/null; then
    say "LEDGER WRITE FAILED for $issue in $repo ($LIVE_LEDGER): this run is unattributed, so the busy-repo preference cannot see it and that repo may be picked again"
    page "kipi dispatch: could not record a live run to $LIVE_LEDGER. The busy-repo preference is blind to $issue, so its repo can be picked again and two agents may land on the same files. Do: check permissions and free space on that path."
    return 1
  fi
}

compact_live_ledger() {
  [ -f "$LIVE_LEDGER" ] || return 0
  local tmp pid issue repo
  tmp="$(mktemp "${LIVE_LEDGER}.XXXXXX")" || return 0
  while IFS=$'\t' read -r pid issue repo; do
    case "$pid" in ''|*[!0-9]*) continue ;; esac
    kill -0 "$pid" 2>/dev/null || continue
    # BOUNDED, because ASK-10 is a prefix of ASK-100 (codex minor, PR #163).
    # A plain substring match let a live ASK-100 converge satisfy the identity
    # check for a dead ASK-10 row, marking the wrong repo busy until the real
    # process exited. The id must be followed by whitespace or end-of-line.
    ps -p "$pid" -o args= 2>/dev/null | grep -qE -- "--issue $issue([[:space:]]|\$)" || continue
    printf '%s\t%s\t%s\n' "$pid" "$issue" "$repo" >> "$tmp"
  done < "$LIVE_LEDGER"
  mv -f "$tmp" "$LIVE_LEDGER" 2>/dev/null || rm -f "$tmp" 2>/dev/null || true
}
# --- END PER-REPO CONCURRENCY ---
# The marker is load-bearing, not decoration. test-dispatch-per-repo-concurrency.sh
# cuts this block out of THIS file and sources it, so the test exercises shipped
# code instead of a copy that can drift green. Delimiting on `^}$` would have
# ended the cut at the first function; it silently captured one of three.

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
# the string "true", or 1 all mean NO.
#
# The registry shipped with all 23 rows off, which was the correct state to ship the
# dangerous piece in. Two are now on: ktlyst and interview-coach (ASK-754). Stating
# the count here was a comment that had to be edited the first time anyone used the
# feature it describes, so it names the opted-in rows instead -- and the authority is
# the registry, not this line. Opt-in is still consent and never safety:
# repo-preflight.sh is what decides whether entering one is safe NOW, and it refuses
# a client engagement repo and the engagement root even when the row says true.
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
  local name path remote out client_n=0 client_names=""
  while IFS=$'\t' read -r name path remote; do
    [ -n "$name" ] || continue
    if [ "$path" = "$REPO" ]; then
      printf '%s\t%s\n' "$name" "$path"
      continue
    fi
    # STDOUT IS CAPTURED, NOT DISCARDED (ASK-741). This used to be
    # `>/dev/null 2>&1`, so the preflight named every failed check on stdout and
    # the dispatcher threw all of it away, logging only "REFUSED". A founder
    # reading that line cannot tell a client-repo refusal from an expired token
    # from an empty queue -- and "silent refusal is indistinguishable from nothing
    # to do" is the exact failure this issue exists to remove. The reason the gate
    # gives is the only thing that makes the gate legible.
    if out="$(bash "$PREFLIGHT" "$path" "$remote" 2>&1)"; then
      printf '%s\t%s\n' "$name" "$path"
    else
      say "preflight REFUSED $name ($path); not entering it -- $(printf '%s' "$out" | grep '^FAIL' | tr '\n' ';' | sed 's/;$//')"
      case "$out" in
        *"FAIL client-repo:"*)
          client_n=$((client_n + 1))
          client_names="${client_names:+$client_names, }$name" ;;
      esac
    fi
  done < <(rotation)
  # COUNTED, AND IN THE DIGEST'S OWN SHAPE. daily-linear-digest.py's third section
  # ("tried, could not be worked") scrapes this log for `N thing(s) <what>` lines,
  # so a refusal phrased any other way is invisible in the one surface the founder
  # actually reads once a day. Emitted only when it happened: a client repo being
  # refused is a real event, and a "0 refused" line every 15 minutes is the
  # cry-wolf noise that gets a channel muted.
  [ "$client_n" -gt 0 ] && say "$client_n repo(s) REFUSED as client engagement repos (unattended dispatch is not allowed there, even when opted in): $client_names"
  return 0
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

# FLEET POSTURE, STATED EVERY RUN (ASK-729). The HOLD line below only prints when
# a non-home repo actually wins a turn, and `dispatch.enabled` is true for 0 of the
# 23 registry rows -- so the rotation reaches nothing, the HOLD never fires, and
# the whole cross-repo gap has been invisible in this log since 2026-08-01. That
# silence is what let sp-09c61b20 stay the record for 13 days while the code had
# already moved past it.
#
# Both numbers, unconditionally, even when they are zero: "0 opted in" is the
# single most useful fact about why no client repo is being served, and a line
# that only appears when something happens cannot say it.
FLEET_TOTAL="$(python3 -c 'import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: sys.exit(0)
print(len(d.get("instances",[])))' "${KIPI_DISPATCH_REGISTRY:-$REPO/instance-registry.json}" 2>/dev/null)"
FLEET_OPTED="$(fleet_candidates 2>/dev/null | awk -F'\t' -v h="$REPO" 'NF && $2 != h' | wc -l | tr -d ' ')"
# NO "HELD" COUNT ANY MORE. This line was written while kipi-dispatch.sh:726 held
# every non-home target on unfinished cross-repo gh scoping, and it counted each
# such pick as held. ASK-738 (#146) scoped every gh call and DROPPED that hold, so
# the same number now describes repos the run ENTERS. Reporting them as held while
# entering them is worse than the silence this line replaced: a reader would take
# it as the reason nothing ran. Caught by the Codex review of #143 after the two
# branches merged; each was correct alone.
#
# The opted-in count survives because it is the useful half: "0 of 25 opted in" is
# still the single most useful fact about why no other repo is being served, and a
# line that only appears when something happens cannot say it.
say "dispatch: ${FLEET_OPTED:-0} of ${FLEET_TOTAL:-0} registered repo(s) opted in for cross-repo dispatch"

TARGET_NAME=""
TARGET_PATH=""
# THE PER-REPO RULE IS ENFORCED HERE, WHERE A REPO IS CHOSEN (sp-e45251f7).
# A repo that already has a live converge is SKIPPED rather than aborting the
# cycle, so the rotation continues to the next repo instead of the whole fleet
# stalling behind one busy one -- skipping is the entire throughput win, and an
# early `exit 0` here would leave the cap at 1 by another name.
LIVE_REPOS="$(live_repos)"

# ONE LIVE RUN PER REPO, for every run DISPATCH LAUNCHES. Founder decision
# 2026-08-15 [USER-DIRECTED], recorded in ASK-811: asked whether two agents may
# work one repo at once, the answer was "no, only one per repo".
#
# NOT THE WORD "ABSOLUTE", AND THE PRECISION IS THE POINT (codex major, PR #178).
# This binds what dispatch itself starts, because the ledger is the only thing
# that can say WHICH REPO a run is in. A converge started by hand carries its
# target repo in an env var; environment is not in the process table, so no
# pgrep can attribute it, and such a run does not mark its repo busy. A failed
# ledger write leaves the same hole, loudly -- record_live_run pages when it
# cannot record. Calling the rule absolute would promise a guarantee the
# mechanism cannot keep, which is how someone later raises the cap believing
# they are safe. The residual is ASK-824.
#
# A repo with a live run is SKIPPED and the rotation continues to the next repo.
# If every dispatchable repo is busy, this cycle enters nothing and the next
# 900s tick tries again. There is no fallback; that is the point of the decision.
#
# WHAT THIS COSTS, STATED PLAINLY. test-ci-redrive 14g was written because a live
# converge used to starve the ready queue: a redrive offered the already-live
# issue, NEXT was overwritten with it, and the issue that WAS dispatchable was
# thrown away every heartbeat. Under this rule a busy repo genuinely does defer
# its other ready issues. The difference from that scar is that the deferral is
# now DELIBERATE, LOGGED, and costs no budget -- the issue stays ready and is
# picked up as soon as the repo frees. 14g is updated to assert exactly that,
# because the protection worth keeping is "nothing is silently consumed", not
# "something is always dispatched".
#
# The conflict risk this removes is the reason: the dispatcher picks by readiness
# and has NO idea which files an issue touches, so two runs in one repo can edit
# the same region (observed 2026-07-28, ASK-223 vs live ASK-222) and hand back
# conflicting PRs for a human to untangle.
while IFS=$'\t' read -r PNAME PPATH; do
  [ -n "$PNAME" ] || continue
  # Exact line match. A substring test would let ~/projects/foo suppress
  # ~/projects/foo-bar, silently starving a repo nothing is running in.
  if [ -n "$LIVE_REPOS" ] && printf '%s\n' "$LIVE_REPOS" | grep -qxF -- "$PPATH"; then
    say "skip $PNAME: a converge run is already live in $PPATH (one run per repo, ASK-811)"
    continue
  fi
  TARGET_NAME="$PNAME"
  TARGET_PATH="$PPATH"
  break
done <<PICKEOF
$PICKS
PICKEOF

if [ -z "$TARGET_NAME" ]; then
  say "no free repo this cycle: every dispatchable repo already has a live run; nothing entered, nothing claimed, retrying next tick"
fi
# --- END REPO SELECTION ---
# The marker is load-bearing. The test cuts this whole block out and sources it,
# and a cut that ended at PICKEOF stopped one line before the fallback -- so the
# suite tested a selection loop that could never fall back and reported the
# missing behaviour as a failure of the code rather than of the cut. That is the
# fourth incomplete-extract in this file's history; delimit explicitly.

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
  # THE HOLD IS GONE (ASK-738). It was here from sp-9421b9b7 because `gh`
  # resolves its repository from the process cwd and ignores every path variable
  # this script carries -- and line 205 cd's into the home checkout and stays. So
  # `git -C` worked in the target while `gh` answered about kipi-system. Three
  # paths did that; the worst, pr-review-agent.sh, would review the wrong repo's
  # code and post `kipi/reviewer-approved` on it, so the wrong-repo failure ran
  # through the gate itself. All three are now scoped with -R from ONE derivation
  # (repo-slug-lib.sh), and review artifacts are keyed by repo AND PR so two
  # repos' PR #42 cannot consume each other's records.
  #
  # WHAT PROTECTS CLIENT REPOS IS NOT THIS LINE, AND NEVER WAS. Founder,
  # 2026-08-13: "no. unattended agents should not reach a client repo." That is
  # enforced by repo-preflight.sh check 0, which #144 landed and which pick_list
  # above runs BEFORE any repo reaches this point -- a client-shaped path is
  # refused there even when its registry row says dispatch.enabled: true. This
  # HOLD was a blunt stand-in for a gate that did not exist yet. It exists now,
  # upstream, and it fails closed. Removing a stand-in is only safe because the
  # real thing landed first; if check 0 is ever weakened, that is the line that
  # matters, not this one.
  #
  # TWO CARRIERS FOR ONE FACT, as the comment above says: --repo is the explicit
  # argument the worker parses, and KIPI_TARGET_REPO crosses the converge.sh
  # boundary by inheritance because converge forwards only its own arguments.
  # Setting one and not the other dispatches the work to the target and then
  # converges against home, which is the defect wearing the other hat.
  #
  # WHITESPACE **AND GLOB CHARACTERS** REFUSE. $WORK_ARGS is spliced unquoted into
  # `bash ./kipi work` below (it must be, so that empty expands to nothing), which
  # means the shell does BOTH word-splitting and pathname expansion on it:
  #   - a space splits the path into two wrong arguments, and the worker runs
  #     against the home repo with a garbage --repo;
  #   - a `*`, `?` or `[` is glob-expanded against the CWD, so --repo silently
  #     becomes some unrelated matching path, or the literal path if nothing
  #     matches. Either way the agent is aimed somewhere nobody chose.
  # The glob half was missed on the first cut and caught by codex on PR #146
  # (sp-b2f0627e). Loud refusal beats a silent wrong target: this decides which
  # repository an unattended self-merging loop enters.
  case "$TARGET_PATH" in
    *[[:space:]]*|*'*'*|*'?'*|*'['*|*']'*)
      say "REFUSING $TARGET_NAME: its registry path contains whitespace or a glob character ($TARGET_PATH), which cannot be passed safely as an unquoted --repo; not entering"
      exit 0 ;;
  esac
  WORK_ARGS="--repo $TARGET_PATH"
  export KIPI_TARGET_REPO="$TARGET_PATH"
  say "entering $TARGET_NAME ($TARGET_PATH) -- cleared preflight, gh scoped to its own remote"
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
# MATCHED AGAINST WHAT THE PRODUCER ACTUALLY PRINTS, verified 2026-08-02 by
# grepping linear-worker.sh rather than assuming a format. The previous pattern
# (infra_error|authentication|unauthorized) matched NONE of the real loop-stopping
# output, so a genuine Linear outage fell straight through to page_clear below --
# it did not merely fail to page, it ERASED the state that would have paged. That
# is silence dressed as health, and it is the same defect class this whole issue
# has been unpicking. A pattern I invent tests my assumption, not the system.
#
# The producer's real shapes, and whether each stops the run:
#   linear-worker.sh:417  "INFRA: linear unreachable (<exc>)."     exit 0  <- MISSED
#   linear-worker.sh:320  {"infra_error": ...} (python helper)     internal
#   linear-worker.sh:251  "INFRA: git fetch failed in <repo>."     exit 9
#   linear-worker.sh:989  "INFRA: could not create worktree ..."   continue
#   linear-worker.sh:1049 "INFRA: claim failed rc=<n> ..."         continue
# These reach us because the worker's say() is `tee -a "$LOG"`, so it writes to
# stdout as well as its log, and WORK_OUT is captured with 2>&1.
#
# DELIBERATELY NOT a bare `INFRA:` match. :989 and :1049 print an INFRA: line and
# then `continue` -- the worker keeps working -- so a prefix match would page "the
# loop is stopped" while it is demonstrably still running. Precision here is the
# difference between a real alarm and the noise this issue exists to remove.
# --- LINEAR-OUTAGE-GUARD:BEGIN ---
# A STABLE EXTRACTION ANCHOR, and it earns its keep. The test used to slice this
# block with an awk range keyed on the matcher line itself, so a mutant that
# reworded the matcher made the range match nothing: the harness bailed instead of
# asserting, and two mutants that restore the round-3 defect were reported as
# SURVIVED. A fixture must not be anchored to the text it is testing.
if printf '%s' "$WORK_OUT" | grep -qiE 'INFRA: linear unreachable|infra_error|authentication|unauthorized'; then
  say "infra error from kipi work: $(printf '%s' "$WORK_OUT" | head -3 | tr '\n' ' ')"
  page_once linear-down "kipi dispatch: Linear is unreachable or auth expired, so NO issues can be picked up. The loop is stopped, not slow. Do: run \`bash kipi work\` by hand and check the Linear token."
  exit 1
fi
# A RUN THAT NEVER REACHED LINEAR IS NOT EVIDENCE LINEAR RECOVERED -- the same rule
# stale_check applies to a failed fetch. linear-worker.sh:251 exits BEFORE any
# Linear call and already pages the founder itself, so this must not double-page;
# it must only refrain from clearing.
if printf '%s' "$WORK_OUT" | grep -qiE 'INFRA: git fetch failed'; then
  say "worker stopped on an environment failure before reaching Linear; leaving linear-down state untouched (the worker pages this one itself)"
  exit 1
fi
page_clear linear-down
# --- LINEAR-OUTAGE-GUARD:END ---

NEXT="$(printf '%s' "$WORK_OUT" | grep -oE '\[dry\] would work ASK-[0-9]+' | grep -oE 'ASK-[0-9]+' | head -1)"

# --- RED-CI REDRIVE (ASK-295) -----------------------------------------------
# A PR this loop opened going red is a dead end: ready() only returns
# backlog/unstarted issues, and an issue with a live PR is In Progress, so the
# fresh pick above can never return it. GitHub's notifier is then the only thing
# that noticed, and its only addressee is the repo owner -- who does not work on
# the code. Three such emails reached him on 2026-08-02.
#
# BEFORE the empty-NEXT exit, not after. Nothing ready is the ORDINARY state of
# a healthy queue, so handling the red PR only when something else was also
# waiting would leave it unhandled on exactly the quiet cycles.
#
# AHEAD of a fresh pick, because finishing an issue that already has a PR beats
# starting a new one, and because the red PR is what is generating founder mail
# right now.
#
# HERE AND NOT IN A NEW LAUNCHD JOB: every cap this needs already exists in this
# file and has been proven (MAX_CONCURRENT, the daily budget, the liveness
# assert, page_once, one dispatch per heartbeat). A second job would be a second
# copy of all four, drifting -- and per-repo jobs die silently: the income
# scanners went dark for 6 days that way. ci-redrive.py holds its own cap of one
# attempt per PR per failure signature in the SAME attempts ledger the worker
# uses, so a handler cannot re-run a flake forever.
#
# rc 2 (gh could not answer) is NOT treated as "no red PRs": the fresh pick
# stands and the reason is logged. rc 1 is the ordinary "nothing red".
#
# THE OFFER IS NOT THE CLAIM (PR #73 review, finding 2). `redrive` writes
# nothing: it prints `<issue>\t<signature>\t<head_sha>` and leaves the ledger
# alone. This block is still ~70 lines above the launch, and one of the guards
# in between (a converge run already live for that issue) exits 0 without
# launching anything. Claiming here spent the PR's one machine attempt on a
# dispatch that never happened, and the next heartbeat then paged the founder
# with a message asserting a re-dispatch and a second CI failure, neither of
# which had occurred. The claim now happens at MARK-DISPATCHED below, past every
# guard that can still abort.
#
# AND AN OFFER MUST NOT COST THE FRESH PICK ITS SLOT (PR #73 review r2, finding
# 2). NEXT is overwritten below, and the duplicate-dispatch guard ~40 lines down
# exits 0 without launching anything when a converge for that issue is already
# live. So a red PR whose converge was still running discarded the ready issue
# that WAS dispatchable -- every heartbeat, for the whole run.
#
# Fixed where the decision is made, not here: ci-redrive.py's converge_live()
# reads the same `ps -Ao args=` command line the guard below matches and does not
# OFFER a candidate that is already in flight, so NEXT keeps the fresh pick. A
# second liveness rule spelled out in this file is the drift this repo keeps
# paying for, and only the Python side can also suppress the founder page (that
# page is finding 1). Its stderr lands in this log, so the skip is visible here.
REDRIVE="$REPO/q-system/.q-system/scripts/ci-redrive.py"
REDRIVE_NEXT=""; REDRIVE_SIG=""; REDRIVE_SHA=""; REDRIVE_BRANCH=""; REDRIVE_PR=""
if [ -f "$REDRIVE" ]; then
  REDRIVE_LINE="$(KIPI_NOTIFY="$NOTIFY" python3 "$REDRIVE" \
                    --repo-dir "$TARGET_PATH" redrive 2>>"$LOG")"
  REDRIVE_RC=$?
  if [ "$REDRIVE_RC" = "0" ] && [ -n "$REDRIVE_LINE" ]; then
    REDRIVE_NEXT="$(printf '%s' "$REDRIVE_LINE" | cut -f1)"
    REDRIVE_SIG="$(printf '%s' "$REDRIVE_LINE" | cut -f2)"
    REDRIVE_SHA="$(printf '%s' "$REDRIVE_LINE" | cut -f3)"
    # The branch the selected PR is ACTUALLY on, as the selector read it, and the
    # PR number so the refusal can name it. Kept for the same reason REVIEW_BRANCH
    # is kept below: branch_guard must not ask gh a question it has just been
    # answered -- see its FROM THE SELECTOR note. Empty when ci-redrive could not
    # confirm the head lives in this repo, which branch_guard reads as "no earlier
    # observation" and handles on its fail-open arm.
    REDRIVE_BRANCH="$(printf '%s' "$REDRIVE_LINE" | cut -f4)"
    REDRIVE_PR="$(printf '%s' "$REDRIVE_LINE" | cut -f5)"
    say "red-CI redrive: handing $REDRIVE_NEXT back to its agent ahead of the fresh pick${NEXT:+ ($NEXT waits)}"
    NEXT="$REDRIVE_NEXT"
  elif [ "$REDRIVE_RC" = "2" ]; then
    say "red-CI redrive: gh could not read PR state in $TARGET_NAME -- fresh pick stands, nothing claimed"
  fi
fi

# --- REVIEWER REDRIVE (ASK-352) ----------------------------------------------
# The OTHER half of a failing status check. ci-redrive.py above deliberately
# EXCLUDES the reviewer's own verdict slots from what it calls red CI, and that
# exclusion stays -- including them re-dispatched PRs whose build was passing
# (PR #73, live). But its docstring justified the exclusion by asserting the
# reviewer's Linear comment already caused a re-dispatch, and no such selector
# existed. Six PRs sat parked ~29 hours. This is that selector: one consumer per
# event, neither reading the other's slot.
#
# AFTER ci-redrive AND ONLY IF IT PASSED. Red CI outranks a reviewer refusal --
# a build that does not compile makes any review of it moot, and re-reviewing a
# broken tree spends a codex call to be told the build is broken.
#
# TWO ACTIONS, NOT ONE, and this is the whole reason the selector exists. A
# `failure` on the reviewer slot means either "someone objected" (rework: the
# review is the spec) or "nobody read the code" (re-review: there is no spec).
# The verdict does not separate them -- PR #80 recorded REQUEST CHANGES from the
# prompt's own echoed grading rule. review-redrive.py reads the `usable` key
# pr-review-agent.sh now persists, and answers with the action.
#
# rc 2 (gh could not answer) leaves the fresh pick standing, same as above.
REVIEW_REDRIVE="$REPO/q-system/.q-system/scripts/review-redrive.py"
REVIEW_ACTION=""; REVIEW_NEXT=""; REVIEW_PR=""; REVIEW_SHA=""; REVIEW_BRANCH=""
if [ -z "$REDRIVE_NEXT" ] && [ -f "$REVIEW_REDRIVE" ]; then
  REVIEW_LINE="$(python3 "$REVIEW_REDRIVE" --repo-dir "$TARGET_PATH" select 2>>"$LOG")"
  REVIEW_RC=$?
  if [ "$REVIEW_RC" = "0" ] && [ -n "$REVIEW_LINE" ]; then
    REVIEW_ACTION="$(printf '%s' "$REVIEW_LINE" | cut -f1)"
    REVIEW_NEXT="$(printf '%s' "$REVIEW_LINE" | cut -f2)"
    REVIEW_PR="$(printf '%s' "$REVIEW_LINE" | cut -f3)"
    REVIEW_SHA="$(printf '%s' "$REVIEW_LINE" | cut -f4)"
    # The branch the selected PR is ACTUALLY on, as the selector read it. Kept so
    # branch_guard below need not ask gh the same question a second time -- see
    # its FROM THE SELECTOR note.
    REVIEW_BRANCH="$(printf '%s' "$REVIEW_LINE" | cut -f5)"
    say "reviewer redrive: $REVIEW_NEXT PR #$REVIEW_PR needs $REVIEW_ACTION${NEXT:+ ($NEXT waits)}"
    NEXT="$REVIEW_NEXT"
  elif [ "$REVIEW_RC" = "2" ]; then
    say "reviewer redrive: gh could not read PR state in $TARGET_NAME -- fresh pick stands, nothing claimed"
  fi
fi

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

# --- BRANCH TARGET GUARD (ASK-358) -------------------------------------------
# Refuse to dispatch an issue whose work would land on a branch no open PR is on.
#
# THE DEFECT, measured on ASK-352. converge.sh:83 derives the branch it commits
# into from the issue id alone -- BRANCH="sana/$(lower ISSUE)". ASK-352 has TWO
# branches: sana/ask-352 backs PR #90, which is CLOSED, and sana/ask-352-clean
# backs PR #91, which is open. So a rework dispatched for ASK-352 commits onto
# the closed branch, where no PR and no reviewer will ever read it. Silent
# wrong-target is worse than a stall: the work looks done and is unreachable.
#
# ON EVERY DISPATCH, NOT ONLY THE REDRIVE ONES. The reviewer redrive is where the
# defect was found, but the naming rule is converge's and converge runs for the
# fresh pick too -- a guard on one path is this repo's recurring class (two
# paths, one guarded). One chokepoint, above every selector, before the attempt
# is claimed: refusing after mark-dispatched would burn the PR's one attempt.
#
# IT REFUSES RATHER THAN RETARGETS. Retargeting means passing a branch through to
# converge, and converge.sh is not in this change's scope; more to the point, a
# dispatcher that silently rewrites where work lands is the same class of surprise
# as the bug. The refusal names the branch, so the next move is a human's and it
# is one line long.
#
# FAILS OPEN ON NOT KNOWING, closed on knowing -- the posture stale_check already
# takes on a failed fetch. rc 2 (gh could not answer) and a missing resolver both
# RUN: one gh outage must not halt the loop. rc 1 (no open PR) also runs, because
# round one legitimately has no PR yet.
#
# IT GUARDS COMMITS, SO IT SKIPS THE ONE ACTION THAT MAKES NONE (PR #211 round 1,
# MAJOR 1). A `re-review` runs pr-review-agent.sh against a PR NUMBER; converge's
# branch rule never applies to it and it cannot land work anywhere. Refusing one
# parks a PR overnight over a condition it structurally cannot cause -- and a
# gate that blocks the harmless case is a gate that gets switched off. `rework`
# and the fresh pick both become a converge, so both stay guarded.
#
# FROM THE SELECTOR, NOT FROM A SECOND QUERY (PR #211 round 1, MAJOR 3; extended
# to the red-CI lane in round 3, MAJOR 2). When EITHER redrive picked this issue
# it already READ the branch its PR is on, and asking gh again opens a window
# between the two answers: PR #91 closing in between makes the second answer "no
# open PR", the fail-open arm fires, and the work lands on precisely the branch
# this guard exists to reject. The carried value is also the more correct
# question -- it describes the PR whose one attempt is about to be spent, where a
# fresh query describes the issue's board now. The fresh pick has no earlier
# observation, so it still asks; so does a redrive whose selector could not
# confirm the head lives in this repo, which arrives as an empty carried branch.
# A REFUSAL NOBODY IS TOLD ABOUT IS A SILENT PARK (PR #211 round 2, MAJOR 2).
# Every arm below used to end in `say`, which appends to dispatch.log and nothing
# else. From outside, the guard doing its job was indistinguishable from the loop
# having nothing to do: the same candidate refused every 15 minutes, the issue
# never moving, and the queue starving behind it with nobody learning why.
#
# A branch mismatch and an ambiguous board are the two refusals here that CANNOT
# SELF-HEAL -- both need a human to rename a branch, reopen a PR, or close a
# stale one. That is what earns a page. The fail-open arms do not get one: they
# RUN the dispatch, so there is no stall to report, and paging on a gh outage is
# noise on top of an outage.
#
# page_once rather than page, because this code path fires on every beat while
# the condition holds, and `founder-notifications.md` is explicit that repeating
# "still waiting" each cycle is noise rather than a page. The dedupe (and its
# 24h re-ping) already exists above and is what makes paging from a per-beat path
# safe at all. Its matching page_clear runs on the healthy exit, or the marker
# outlives its condition and swallows the NEXT park for the whole window.
#
# ONE VERDICT, THEN ONE ACTION. The arms compute a message and fall through to a
# single exit, rather than each arm remembering to say AND page AND return. Six
# return sites each owning three obligations is how the log-only refusal survived
# round 1 in the first place.
branch_guard() {
  local expect actual rc key msg
  # The producer's rule, mirrored. Drift here is silent, so the anti-drift check
  # is the test asserting converge.sh still builds the branch this same way.
  expect="sana/$(printf '%s' "$NEXT" | tr 'A-Z' 'a-z')"
  key="branch-guard-$NEXT"
  msg=""
  if [ -n "$REDRIVE_NEXT" ] && [ "$NEXT" = "$REDRIVE_NEXT" ]; then
    # THE RED-CI LANE READS ITS OWN OBSERVATION TOO (PR #211 round 3, MAJOR 2).
    # Round 2 carried the branch for the reviewer redrive only. The red-CI
    # selector read the branch and dropped it, so this lane fell through to the
    # elif below and asked gh a SECOND time -- and that second answer is the
    # fail-open one: if the PR closed between the two calls, `branch-for` says
    # "no open PR", rc 1 runs the dispatch, and the work lands on the branch this
    # guard exists to reject. Fail-open in the guard whose thesis is "refuse a
    # dispatch that would land on a branch no open PR is on" is the PR
    # contradicting itself.
    #
    # No `re-review` carve-out here: every red-CI hand-back becomes a converge,
    # so converge's naming rule always applies to it.
    if [ -n "$REDRIVE_BRANCH" ] && [ "$REDRIVE_BRANCH" != "$expect" ]; then
      msg="skip $NEXT: its open PR #$REDRIVE_PR is on $REDRIVE_BRANCH, but converge would commit onto $expect -- work there reaches no PR and no reviewer. Rename the branch to $expect, or reopen the PR on it."
    fi
  elif [ -n "$REVIEW_ACTION" ] && [ "$NEXT" = "$REVIEW_NEXT" ]; then
    if [ "$REVIEW_ACTION" != "re-review" ] && [ -n "$REVIEW_BRANCH" ] \
       && [ "$REVIEW_BRANCH" != "$expect" ]; then
      msg="skip $NEXT: its open PR #$REVIEW_PR is on $REVIEW_BRANCH, but converge would commit onto $expect -- work there reaches no PR and no reviewer. Rename the branch to $expect, or reopen the PR on it."
    fi
  elif [ -f "$REVIEW_REDRIVE" ]; then
    actual="$(python3 "$REVIEW_REDRIVE" --repo-dir "$TARGET_PATH" \
              branch-for --issue "$NEXT" 2>>"$LOG")"
    rc=$?
    case "$rc" in
      0) [ "$actual" = "$expect" ] || msg="skip $NEXT: its open PR is on $actual, but converge would commit onto $expect -- work there reaches no PR and no reviewer. Rename the branch to $expect, or reopen the PR on it." ;;
      3) msg="skip $NEXT: it maps to more than one live branch, so which one the work belongs on is a guess (see $LOG). Close the stale PR, or say which branch is current." ;;
      *) ;;
    esac
  fi
  if [ -z "$msg" ]; then
    page_clear "$key"
    return 0
  fi
  say "$msg"
  page_once "$key" "kipi dispatch: $msg"
  return 1
}
branch_guard || exit 0

# --- RED-CI REDRIVE: MARK-DISPATCHED (ASK-295) -------------------------------
# Past every guard that can still abort, and immediately before the launch. This
# is where the PR's one machine attempt is spent, and the call is the atomic
# gate: rc 0 means this run owns the attempt, rc non-zero means another run
# already claimed it (or the ledger could not be written, which is the same
# answer -- nothing was recorded, so nothing may act as though it was).
if [ -n "$REDRIVE_SIG" ] && [ "$NEXT" = "$REDRIVE_NEXT" ]; then
  if ! python3 "$REDRIVE" mark-dispatched --issue "$NEXT" \
       --signature "$REDRIVE_SIG" --head-sha "$REDRIVE_SHA" 2>>"$LOG"; then
    say "red-CI redrive: the attempt for $NEXT is already claimed -- not dispatching"
    exit 0
  fi
fi

# Same contract for the reviewer redrive (ASK-352): the OFFER above wrote
# nothing, and THIS is the atomic claim. rc non-zero means another run owns it,
# or the ledger could not be written -- the same answer either way, because
# nothing was recorded so nothing may act as though it was. The cap is one
# attempt per PR per action per HEAD SHA, so a PR that pushes a real fix is
# eligible again while a re-review that keeps coming back phantom at the same sha
# is not retried.
if [ -n "$REVIEW_ACTION" ] && [ "$NEXT" = "$REVIEW_NEXT" ]; then
  if ! python3 "$REVIEW_REDRIVE" mark-dispatched --issue "$NEXT" \
       --action "$REVIEW_ACTION" --pr "$REVIEW_PR" --head-sha "$REVIEW_SHA" 2>>"$LOG"; then
    say "reviewer redrive: the $REVIEW_ACTION attempt for $NEXT PR #$REVIEW_PR is already claimed -- not dispatching"
    exit 0
  fi
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

# WHAT THIS DISPATCH ACTUALLY RUNS (ASK-352). Converge for everything except a
# reviewer redrive that asked for a RE-REVIEW, where the right action is another
# review and not another rework round: the PR is parked because nobody read the
# code, so there are no findings for a converge to work from and it would come
# back to this same failing slot having spent a full round.
#
# --post is required and is the point. Without it the reviewer writes a verdict
# record and never touches the commit status, so the slot that parked the PR
# stays failing and the next heartbeat picks the same PR again -- a loop that
# looks like progress. --invoker labels it dispatcher-driven (sp-53aad86f), so a
# hand-run review can never pass as evidence the loop closed itself.
#
# ONE ARRAY, EXPANDED ONCE BELOW. The launch machinery underneath (setsid, the
# pid capture, the liveness assert) is proven and is not duplicated per action;
# only the argv differs.
DISPATCH_ARGV=(./kipi converge --issue "$NEXT" --max-rounds "$MAX_ROUNDS")
if [ "$REVIEW_ACTION" = "re-review" ] && [ "$NEXT" = "$REVIEW_NEXT" ]; then
  DISPATCH_ARGV=(bash "$REPO/q-system/.q-system/scripts/pr-review-agent.sh" \
                 "$REVIEW_PR" --issue "$NEXT" --post)
  export KIPI_REVIEW_INVOKER="dispatcher"
fi

CHILD_PID="$(python3 - "$CONVERGE_LOG" \
         "${DISPATCH_ARGV[@]}" <<'PY'
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
# RECORD BEFORE THE LIVENESS WAIT, NOT AFTER (sp-e45251f7). The assert below
# watches the child for 10 seconds. Recording after it would leave a window in
# which this repo has a live run that live_repos() cannot see, and a concurrent
# tick landing in that window would pick the same repo -- rebuilding the very
# same-file collision the per-repo rule exists to prevent. A row for a child that
# dies immediately costs nothing: live_repos() drops it on the next read, because
# the pid is gone.
case "$CHILD_PID" in
  ''|*[!0-9]*) : ;;
  *) record_live_run "$CHILD_PID" "$NEXT" "${TARGET_PATH:-$REPO}" ;;
esac
compact_live_ledger
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
