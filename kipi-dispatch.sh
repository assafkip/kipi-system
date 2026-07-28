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
#
# WHY IT CAN NOW RUN MORE THAN ONE AT A TIME (ASK-225)
# ----------------------------------------------------
# Until 2026-07-28 this picked by READINESS ALONE, so it could not see which
# files a candidate touches and two concurrent runs could land in the same file.
# Observed: ASK-223 edits the same linear-worker.sh region as the then-live
# ASK-222. Unattended, that yields a pile of conflicted PRs, so the cap sat at 1
# as a stopgap. Every ready issue carries a `**Files:**` list in its DoR
# (prd_split.py already parses it, ASK-214), so dispatch is a set-intersection
# problem: a candidate goes only if its file set is disjoint from every LIVE
# run's. Unknown set => never parallel. See disjointness_skip_reason().
set -uo pipefail

REPO="${KIPI_REPO:-/Users/assafkipnis/projects/kipi-system}"
LOG="$HOME/.config/kipi/dispatch.log"
MAX_CONCURRENT="${KIPI_DISPATCH_MAX:-2}"
MAX_ROUNDS="${KIPI_DISPATCH_ROUNDS:-3}"
NOTIFY="${KIPI_NOTIFY:-$REPO/q-system/.q-system/scripts/slack-notify.sh}"

# prd_split.py ships next to THIS script, not inside $REPO. Resolving it from
# $REPO would break the moment KIPI_REPO points at a fixture (the test suite) or
# at a second checkout, and the failure would be silent: no file set parsed
# reads exactly like "no Files line", i.e. it would fail closed and quietly
# serialise the whole board instead of erroring.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRD_SPLIT="${KIPI_DISPATCH_PRD_SPLIT:-$SELF_DIR/plugins/prd-os/scripts/prd_split.py}"

# MAGNET FILE (sp-f3a2ad81). Nearly every test-adding issue appends one line to
# capability-manifest.json, so intersecting on it would make almost every pair
# "conflicting" and serialise the board back down to one -- the exact thing this
# change exists to undo. It is exempt from the intersection test and relies on
# the union-merge rule that already governs it. Stated out loud on purpose: a
# silent exemption is how the next person reintroduces the conflict.
MAGNET_FILES="q-system/.q-system/capability-manifest.json"

usage() {
  cat <<'USAGE'
kipi-dispatch.sh [--burst N] [--parallel P]

  (no args)      one heartbeat tick: honours the concurrency cap AND the daily
                 budget. This is what launchd runs.
  --burst N      dispatch up to N ready issues right now. Ignores the daily cap
                 and does not spend it: the cap exists to stop the UNATTENDED
                 heartbeat spending the subscription overnight, not to limit
                 what the founder explicitly asks for while present.
  --parallel P   at most P concurrent runs during a burst (default: the
                 concurrency cap, KIPI_DISPATCH_MAX).
USAGE
}

BURST=0
PARALLEL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --burst)    shift; BURST="${1:-}" ;;
    --parallel) shift; PARALLEL="${1:-}" ;;
    -h|--help)  usage; exit 0 ;;
    *) printf 'kipi-dispatch: unknown argument %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
case "$BURST" in ''|*[!0-9]*) printf 'kipi-dispatch: --burst wants a number\n' >&2; exit 2 ;; esac
case "$PARALLEL" in '') ;; *[!0-9]*) printf 'kipi-dispatch: --parallel wants a number\n' >&2; exit 2 ;; esac
[ "${PARALLEL:-1}" = "0" ] && { printf 'kipi-dispatch: --parallel 0 would dispatch nothing\n' >&2; exit 2; }

mkdir -p "$(dirname "$LOG")"
# Also to stdout. A burst is a foreground founder command and MUST show what it
# picked and what it skipped; under launchd stdout goes to the plist's log, so
# echoing costs the heartbeat nothing.
say() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG"; }
page() { bash "$NOTIFY" "$1" >/dev/null 2>&1 || true; }

cd "$REPO" 2>/dev/null || {
  say "FATAL: repo not found at $REPO"
  page "kipi dispatch: repo not found at $REPO -- the Linear loop is DEAD. Do: check the path in com.kipi.dispatch.plist."
  exit 1
}

# --- WHAT IS LIVE RIGHT NOW -----------------------------------------------
# The issue ids of the converge runs in flight. Read from the process table's
# --issue argument, NOT from the worktrees: a worktree can be stale, half-cut,
# or left behind by a killed run, and a file set derived from one would let a
# second agent into a file the live run is still editing.
#
# KIPI_DISPATCH_FAKE_LIVE is a TEST SEAM, and not an optional nicety: the real
# heartbeat runs on the same machine as the suite, so a test that shells out to
# pgrep sees the founder's actual converge runs and its concurrency assertions
# change meaning depending on what the fleet happens to be doing. Set it (even
# to empty) to pin the live set. Unset = the real process table.
live_issues() {
  if [ "${KIPI_DISPATCH_FAKE_LIVE+set}" = "set" ]; then
    printf '%s\n' $KIPI_DISPATCH_FAKE_LIVE | grep . || true
    return 0
  fi
  pgrep -fl "converge.sh --issue" 2>/dev/null \
    | grep -oE 'ASK-[0-9]+' | sort -u || true
}

# `pgrep -c` exits 1 with no match, which under `set -e` would look like failure
# and under a bare assignment yields an empty string. Force a number.
live_converges() { live_issues | grep -c . || true; }

# Is a converge run for exactly this issue already up? Belt and braces against
# the race between dispatch and the In Progress transition.
issue_is_live() { live_issues | grep -qx "$1"; }

# --- FILE SETS FROM THE DoR -----------------------------------------------
# Prints one repo-relative path per line, nothing at all when the set is
# unknown. Reuses prd_split.py's DoR parser rather than a second regex: two
# readers of "what files does this issue touch" with drifting semantics is the
# defect class this repo keeps finding.
#
# KIPI_DISPATCH_DOR_FIXTURE stubs only the NETWORK. The parsing and the
# intersection still run for real, so the test exercises the code that decides
# whether two agents land in one file.
#
# Failures are NOT swallowed. Both "no Files line" and "Linear refused the
# query" produce an empty set and therefore fail closed, but they need
# different fixes: one is a DoR to edit, the other is a token to renew. A bare
# `2>/dev/null` would report the second as the first and leave the board
# serialised with a skip line pointing at the wrong thing.
fileset_for() {  # fileset_for <issue> <out-file> ; prints the failure reason
  ISSUE="$1" PRD_SPLIT="$PRD_SPLIT" python3 - > "$2" 2>"$2.err" <<'PY'
import importlib.util, json, os, pathlib, sys

issue = os.environ["ISSUE"]
spec = importlib.util.spec_from_file_location("prd_split", os.environ["PRD_SPLIT"])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

fixture = os.environ.get("KIPI_DISPATCH_DOR_FIXTURE", "")
if fixture:
    desc = json.loads(pathlib.Path(fixture).read_text()).get(issue, "")
else:
    here = pathlib.Path(os.environ["PRD_SPLIT"]).resolve()
    root = here.parents[3]                      # <repo>/plugins/prd-os/scripts
    lsspec = importlib.util.spec_from_file_location(
        "ls", root / "q-system" / ".q-system" / "scripts" / "linear-sync.py")
    ls = importlib.util.module_from_spec(lsspec)
    lsspec.loader.exec_module(ls)
    q = "query($id:String!){issue(id:$id){description}}"
    desc = ((ls.graphql(q, {"id": issue}) or {}).get("issue") or {}).get("description") or ""

section = mod._dor_section(desc or "")
if section is None:
    raise SystemExit(0)

value = mod._dor_fields(section).get("files", "")
if not value:
    # prd_split._dor_fields ends a value at the first BLANK line, but Linear
    # renders `**Files:**` with a blank line before its bullet list -- the exact
    # shape of every DoR in this team, including ASK-225's own. That returns an
    # empty value, which here would fail closed and serialise the entire board
    # for a formatting reason. So take the block ourselves and hand it to the
    # SAME path tokenizer, keeping one definition of "what is a path".
    # (Upstream parser bug captured as spillover against ASK-225.)
    import re
    m = re.search(r"(?mi)^\s*(?:[-*+]\s+)?\*\*\s*Files\s*:?\s*\*\*:?[ \t]*(.*)$", section)
    if m:
        rest = section[m.end():]
        nxt = re.search(r"(?m)^\s*(?:[-*+]\s+)?\*\*\s*[A-Za-z][A-Za-z ]*?\s*:?\s*\*\*", rest)
        value = m.group(1) + "\n" + (rest[: nxt.start()] if nxt else rest)
# A DoR that says the paths are unknown is the same as having none: emit
# nothing so the caller fails closed rather than dispatching on a guess.
if not value or mod._UNKNOWN_RE.search(value):
    raise SystemExit(0)
for path in mod._extract_paths(value):
    # A trailing slash means the DoR was talking ABOUT a directory, not naming a
    # file to edit -- ASK-225's own Files bullet contains the prose "must NOT go
    # under the synced `q-system/` subtree". Left in, that token appears in many
    # DoRs and makes unrelated issues collide on a word. The intersection is
    # exact-match on file paths, so only file paths belong in it.
    if path.endswith("/"):
        continue
    print(path)
PY
  RC=$?
  [ "$RC" -eq 0 ] && return 0
  printf 'its file set could not be read (%s)' \
    "$(tr '\n' ' ' < "$2.err" | sed 's/  */ /g' | tail -c 200)"
  return 1
}

# The first path present in BOTH sets, magnet files excluded. Empty when the two
# sets are disjoint. Named so the skip line can quote it -- "they overlap" with
# no path is a report nobody can act on.
strip_magnets() { grep -vxF "$MAGNET_FILES" || true; }
first_overlap() {  # first_overlap <fileA> <fileB>
  grep -Fx -f "$1" "$2" 2>/dev/null | strip_magnets | head -1
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
#
# A manual burst is NOT a beat. Recording one would mask a heartbeat that has
# been dead for hours (the founder's own command would keep resetting the gap),
# and a burst after a real outage would fire the "RESUMED" all-clear for a
# launchd job that is still down. The beacon watches the scheduler, so only the
# scheduler writes to it.
GAP_MINUTES="${KIPI_DISPATCH_GAP_MINUTES:-45}"   # 3 missed ticks at 900s
BEAT_FILE="$HOME/.config/kipi/dispatch-lastbeat"
NOW_EPOCH="$(date -u +%s)"
LAST_BEAT="$(cat "$BEAT_FILE" 2>/dev/null || echo "")"
case "$LAST_BEAT" in ''|*[!0-9]*) LAST_BEAT="" ;; esac

if [ "$BURST" -gt 0 ]; then
  :
elif [ -z "$LAST_BEAT" ]; then
  say "heartbeat: first beat on record"
  page "kipi heartbeat: STARTED. The Linear loop is live and will check for ready issues every 15 min (max ${KIPI_DISPATCH_DAILY_MAX:-4} issues/day). Nothing to do."
else
  GAP=$(( (NOW_EPOCH - LAST_BEAT) / 60 ))
  if [ "$GAP" -ge "$GAP_MINUTES" ]; then
    say "heartbeat: RESUMED after ${GAP}m without a beat"
    page "kipi heartbeat: RESUMED after ${GAP} min down (reboot, sleep, or a reload). The Linear loop is running again. Nothing to do -- this is the all-clear, not a fault."
  fi
fi
[ "$BURST" -gt 0 ] || printf '%s' "$NOW_EPOCH" > "$BEAT_FILE"

LIVE="$(live_converges)"; LIVE="${LIVE:-0}"
SLOTS="${PARALLEL:-$MAX_CONCURRENT}"
if [ "$BURST" -eq 0 ] && [ "$LIVE" -ge "$MAX_CONCURRENT" ]; then
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
# One issue costs up to MAX_ROUNDS x (1 agent + 1 reviewer) = 6 sessions.
# So DAILY_MAX is roughly "sessions per day / 6".
#
# A BURST NEITHER READS NOR SPENDS THIS (ASK-225). The cap's job is to stop the
# unattended heartbeat quietly spending the founder's subscription overnight. A
# burst is an explicit human request made while they are present and watching
# the estimate this script prints first, so gating it on the overnight budget
# would be the cap doing a job it was never given -- and letting it DECREMENT
# the counter would mean an afternoon burst silently eats the night's budget.
DAILY_MAX="${KIPI_DISPATCH_DAILY_MAX:-4}"
# LOCAL date, not UTC. Founder-set 2026-07-28. A UTC budget day rolls over at
# 17:00 PDT, so spending the cap overnight left the loop idle through the whole
# working day and refilled it at teatime -- the budget window was inverted
# against the day it is meant to serve. Local midnight gives a fresh budget each
# morning. `date` with no -u is the local date, and the file name carries it, so
# the rollover needs no timer: a new day is simply a new file that reads 0.
TODAY="$(date +%Y-%m-%d)"
COUNT_FILE="$HOME/.config/kipi/dispatch-count-$TODAY"
DISPATCHED_TODAY=0
if [ "$BURST" -eq 0 ]; then
  DISPATCHED_TODAY="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"
  case "$DISPATCHED_TODAY" in ''|*[!0-9]*) DISPATCHED_TODAY=0 ;; esac
fi

if [ "$BURST" -eq 0 ] && [ "$DISPATCHED_TODAY" -ge "$DAILY_MAX" ]; then
  # Say it once per day, not every 15 minutes -- a budget ceiling repeated 96
  # times is the cry-wolf failure, and this is not an error state anyway.
  if [ ! -f "$COUNT_FILE.paged" ]; then
    say "DAILY CAP: $DISPATCHED_TODAY/$DAILY_MAX issues dispatched today, stopping until local midnight"
    page "kipi dispatch: hit the daily cap of $DAILY_MAX issues (~$((DAILY_MAX * 6)) agent sessions). Not an error -- the loop is resting until midnight tonight, then it picks up again on its own. Do: nothing, or raise KIPI_DISPATCH_DAILY_MAX in com.kipi.dispatch.plist to go faster."
    : > "$COUNT_FILE.paged"
  fi
  exit 0
fi

# gh is what every downstream step needs; failing here with a clear page beats
# dispatching an agent that dies opening its PR.
if ! command -v gh >/dev/null 2>&1; then
  say "FATAL: gh not on PATH ($PATH)"
  page "kipi dispatch: gh CLI not on PATH under launchd, so no PR can be opened. The Linear loop is stalled. Do: fix PATH in com.kipi.dispatch.plist."
  exit 1
fi

# How many to dispatch this run.
#   burst      : exactly what the founder asked for.
#   heartbeat  : fill the free concurrency slots, never past the day's budget.
#                Before ASK-225 this was hard-wired to 1 because dispatch could
#                not tell whether two picks collided. Now it can.
if [ "$BURST" -gt 0 ]; then
  TARGET="$BURST"
else
  TARGET=$(( MAX_CONCURRENT - LIVE ))
  BUDGET_LEFT=$(( DAILY_MAX - DISPATCHED_TODAY ))
  [ "$TARGET" -gt "$BUDGET_LEFT" ] && TARGET="$BUDGET_LEFT"
fi
[ "$TARGET" -lt 1 ] && { say "skip: no free slot (live=$LIVE cap=$MAX_CONCURRENT)"; exit 0; }

# Ask for more candidates than the target: disjointness REJECTS candidates, so a
# 1-for-1 request would let a single overlap end the pass with slots still free.
LOOKAHEAD=$(( TARGET * 3 + 2 ))

WORK_OUT="$(bash ./kipi work --limit "$LOOKAHEAD" 2>&1)"
WORK_RC=$?

# An infra error (Linear down, auth expired) is environmental: it will not
# self-heal on the next heartbeat, so say so once rather than fail silently
# every 15 minutes forever. self-healing-retry.md rule 5.
if printf '%s' "$WORK_OUT" | grep -qi "infra_error\|authentication\|unauthorized"; then
  say "infra error from kipi work: $(printf '%s' "$WORK_OUT" | head -3 | tr '\n' ' ')"
  page "kipi dispatch: Linear is unreachable or auth expired, so NO issues can be picked up. The loop is stopped, not slow. Do: run \`bash kipi work\` by hand and check the Linear token."
  exit 1
fi

CANDIDATES="$(printf '%s' "$WORK_OUT" | grep -oE '\[dry\] would work ASK-[0-9]+' | grep -oE 'ASK-[0-9]+')"
if [ -z "$CANDIDATES" ]; then
  say "nothing ready ($(printf '%s' "$WORK_OUT" | grep -oE '[0-9]+ ready issue' | head -1))"
  exit 0
fi
N_CANDIDATES="$(printf '%s\n' "$CANDIDATES" | grep -c .)"

# The union of every live run's file set. Seeded from the process table so a
# burst launched while the heartbeat has runs in flight still respects them.
SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT
LIVE_SET="$SCRATCH/live-set"
: > "$LIVE_SET"
UNREADABLE_LIVE=0
for LI in $(live_issues); do
  # A live run whose file set cannot be read stays unknown, and unknown
  # intersects everything -- so nothing gets dispatched alongside it. Fail
  # closed on the side that already holds a worktree.
  if fileset_for "$LI" "$SCRATCH/live-$LI" >/dev/null; then
    cat "$SCRATCH/live-$LI" >> "$LIVE_SET"
  else
    say "note: file set for the live run $LI is unreadable; holding every candidate this pass"
    UNREADABLE_LIVE=1
  fi
done

if [ "$BURST" -gt 0 ]; then
  # BEFORE launching, not after. The founder is standing here; the cost of the
  # thing they are about to start is the one number that lets them say no.
  say "burst: up to $TARGET issue(s), at most $SLOTS at once, from $N_CANDIDATES ready candidate(s)."
  say "burst: estimated cost up to $(( TARGET * MAX_ROUNDS * 2 )) \`claude -p\` sessions ($TARGET x $MAX_ROUNDS rounds x 2). The daily cap is NOT consulted and NOT spent."
fi

DISPATCHED=0
SKIPPED=0
LAUNCHED_PIDS=""

# Our own launched runs that are still alive. Counted from PIDs we hold rather
# than from pgrep: the runs we just started also match the pgrep pattern, so
# reusing live_converges() here would double-count them against our own cap.
our_active() {
  ACTIVE=0
  for P in $LAUNCHED_PIDS; do kill -0 "$P" 2>/dev/null && ACTIVE=$((ACTIVE+1)); done
  printf '%s' "$ACTIVE"
}

# Every candidate we do not dispatch says why. "dispatched 3 of 10" with no
# reasons reads as "there were only 3", which is the silent-truncation failure.
skip() { SKIPPED=$((SKIPPED+1)); say "skip $1: $2"; }

for ISSUE in $CANDIDATES; do
  if [ "$UNREADABLE_LIVE" -eq 1 ]; then
    skip "$ISSUE" "a live run's file set is unreadable, so no overlap check is trustworthy this pass"
    continue
  fi
  if [ "$DISPATCHED" -ge "$TARGET" ]; then
    skip "$ISSUE" "target of $TARGET reached this run; still ready for the next one"
    continue
  fi

  # Two converge runs on one issue would fight over one worktree.
  if issue_is_live "$ISSUE"; then
    skip "$ISSUE" "a converge run for it is already live"
    continue
  fi

  CAND_SET="$SCRATCH/cand-$ISSUE"
  if ! WHY="$(fileset_for "$ISSUE" "$CAND_SET")"; then
    skip "$ISSUE" "$WHY"
    continue
  fi
  if [ ! -s "$CAND_SET" ]; then
    # FAIL CLOSED. An unknown file set intersects everything by assumption:
    # guessing is exactly how two agents end up in one file.
    skip "$ISSUE" "no usable \`**Files:**\` list in its DoR, so its file set is unknown and it cannot run in parallel. Add the paths to the DoR."
    continue
  fi

  OVERLAP="$(first_overlap "$LIVE_SET" "$CAND_SET")"
  if [ -n "$OVERLAP" ]; then
    skip "$ISSUE" "its file set overlaps a live run on $OVERLAP"
    continue
  fi

  # Wait for a free slot. Polling beats `wait -n`, which needs bash 4.3 and this
  # runs under macOS /bin/bash 3.2 under launchd.
  while [ "$(( $(our_active) + LIVE ))" -ge "$SLOTS" ]; do sleep 2; done

  # Count BEFORE launching. Counting after would let a crash between the two
  # hand out a free dispatch every heartbeat -- the budget must fail closed.
  # Burst does not touch the counter at all (see the DAILY BUDGET note).
  if [ "$BURST" -eq 0 ]; then
    DISPATCHED_TODAY=$(( DISPATCHED_TODAY + 1 ))
    printf '%s' "$DISPATCHED_TODAY" > "$COUNT_FILE"
    say "dispatching $ISSUE (live=$LIVE cap=$MAX_CONCURRENT rounds=$MAX_ROUNDS budget=$DISPATCHED_TODAY/$DAILY_MAX)"
  else
    say "dispatching $ISSUE (burst $((DISPATCHED + 1))/$TARGET, at most $SLOTS at once, rounds=$MAX_ROUNDS)"
  fi

  nohup ./kipi converge --issue "$ISSUE" --max-rounds "$MAX_ROUNDS" \
    > "$HOME/.config/kipi/converge-$ISSUE.log" 2>&1 &
  LAUNCHED_PIDS="$LAUNCHED_PIDS $!"
  DISPATCHED=$(( DISPATCHED + 1 ))

  # This run is now live for the purposes of the next candidate. Without this
  # the whole change is decorative: candidates 2..N would only be checked
  # against runs that were already live when the pass started.
  cat "$CAND_SET" >> "$LIVE_SET"

  say "dispatched $ISSUE"
done

say "done: dispatched $DISPATCHED, skipped $SKIPPED, of $N_CANDIDATES candidate(s)"
exit 0
