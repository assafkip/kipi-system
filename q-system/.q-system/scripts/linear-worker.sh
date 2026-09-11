#!/usr/bin/env bash
# The autonomous worker: pick a ready Linear issue, do it, leave a trail, open a PR.
#
# WHAT IT IS
# ----------
# The engine is not new. open-loops-heartbeat.sh already runs `claude -p` headless
# under launchd with a timeout, Slack-on-failure and a step audit. This gives that
# same shape a better queue: Linear instead of a local JSON file.
#
# THE FOUR THINGS IT WILL NOT DO
# ------------------------------
# 1. It will not MERGE. It opens a PR and stops. Merging is the founder's.
# 2. It will not CLOSE an issue. Closing runs through /issue-verify and
#    /issue-closeout, which refuse without receipts. A worker that could close its
#    own work would route around the only gates that make the board trustworthy.
# 3. It will not touch an issue labelled `owner:assaf` -- that label exists to mark
#    a founder decision, and an agent resolving one is the failure it guards.
# 4. It will not touch an issue with no Definition of Ready. Without a DoR the
#    agent is guessing, and "agents produce plausible garbage in the background" is
#    the outcome this whole design exists to avoid. linear-dor-drafter.py fills
#    those in nightly; this worker consumes them.
#
# EXITS (audited against .claude/rules/loop-exits.md)
#   turn cap / no progress / budget  -> token-guard.py inside the claude run
#   wall clock                       -> TIMEOUT per issue, below
#   error threshold                  -> MAX_ATTEMPTS per issue with backoff, and
#                                       infra failures do NOT burn an issue's budget
#   human interrupt                  -> destructive-op-deny.sh; and it cannot merge
#   goal met                         -> the PR + the closeout gates, not this script
#
# EXIT CODES
#   0  ran (or had nothing to run). A caller may treat this as healthy.
#   1  usage error
#   9  INFRA: the environment is down (git fetch failed) and the run did NO
#      work. Paged on the way out. Distinct from 1 so a caller can tell a dead
#      environment from a bad invocation.
#
# WHY INFRA FAILURE IS COUNTED SEPARATELY
# ---------------------------------------
# An expired auth token or a Linear outage is not the issue's fault. Counting it
# against the issue would burn a real task's retry budget on an environment
# problem and mark good work STUCK. Same distinction self-healing-retry.md rule 5
# draws, and the same one OpenSwarm's scheduler makes.
#
# Usage:  linear-worker.sh [--apply] [--limit N] [--issue ASK-123]
# Dry by default: prints what it would pick and stops.
#
# THE BRACE AROUND EVERYTHING BELOW IS LOAD-BEARING (ASK-351). Do not remove it,
# and do not "clean up" the bare `}` on the last line.
#
# bash does not load a script into memory. It reads a chunk, executes ONE command,
# then lseeks back to the byte offset just past that command for the next one. A
# round here runs up to 1800s inside a repo that agents edit the whole time, so an
# edit shifts every later byte offset and bash resumes parsing mid-string.
# ~/.config/kipi/linear-worker.log carries the signature: `ial: command not found`,
# and `ial` is not a word in this file -- it is the tail of one, read from a
# slipped offset. converge.sh died the same way on 2026-08-03 and threw away four
# completed review rounds.
#
# bash must parse a compound command to completion before executing any of it, so
# the brace makes the whole body arrive at startup. The `exit 0` on the last line
# INSIDE the brace is the other half and is not redundant: measured, a brace wrap
# alone still dies rc=2, because bash seeks past the closing brace looking for one
# more command and re-executes leftovers from a file that has grown.
#
# Reproducer for both halves: q-system/.q-system/scripts/test/test-script-stable-under-self-edit.sh
{
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# KIPI_SKEL / KIPI_STATE_DIR are TEST-ISOLATION SEAMS, same discipline as
# KIPI_LINEAR_CLAIMS / KIPI_LINEAR_LEDGER / KIPI_LINEAR_QUEUE. Without them a
# suite that drives this script end-to-end would create real worktrees and real
# sana/* branches in the founder's checkout and stomp the live attempts ledger --
# so the ordering this script's whole correctness rests on could only ever be
# asserted by grepping its source. Unset in production; the defaults are the
# real skeleton and the real state dir.
SKEL="${KIPI_SKEL:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
CLAIM="$SCRIPT_DIR/linear-claim.py"
SYNC="$SCRIPT_DIR/linear-sync.py"
# Overridable so the suite can read back WHAT was paged without paging the
# founder, and so "did anyone get told?" is answered by a file instead of by a
# grep of this source. Same seam and same name converge.sh already uses -- one
# convention, not two. Default is always the real Slack sink.
NOTIFY="${KIPI_NOTIFY:-$SCRIPT_DIR/slack-notify.sh}"
# The reviewer is injectable for the SAME reason converge.sh injects its worker:
# "what does this script do when the REVIEWER is down" is a real 3am state, and
# it is the state PR #30's review round 2 found two defects in (an unbounded
# drift loop, and a run reporting CONVERGED off the stale record the same run had
# just refused to trust). Asserting it against the real reviewer would cost an
# adversarial review's model spend per case, so the branch would stay untested --
# which is how it shipped wrong. Default is always the real reviewer.
REVIEWER_CMD="${KIPI_PR_REVIEWER:-bash $SCRIPT_DIR/pr-review-agent.sh}"
# THE SECOND RUNNER (ASK-281). `blocked:capability` used to be terminal: its
# Linear comment named exactly one actor who could clear it, whoever owns the
# config, and the founder declined -- "Blocked is not a state that makes sense
# because it has no continuation. I'm not going to unblock it, Sana or Codex need
# to do that." Ten issues parked while the loop logged `nothing ready` every 15
# minutes. The unstated assumption was that "not Sana" means "the founder"; it
# skipped the third runner. Sana runs inside Claude Code, whose sensitive-path
# guard refuses Edit/Write under `.claude/**` and is NOT liftable by
# `permissions.allow`. Codex is a different binary and does not inherit it
# (probed live 2026-08-01: `codex exec -s workspace-write` created
# `.claude/rules/probe.md` from nothing). A capability SANA lacks is not
# automatically a capability the FLEET lacks -- so ask the other runner before
# parking. Injectable for the same reason REVIEWER_CMD is: otherwise every test
# case of "what if the second runner is also refused" bills a real model run, so
# the branch stays untested, which is how the single-runner assumption shipped.
CODEX_CMD="${KIPI_CODEX_RUNNER:-codex exec --skip-git-repo-check -s workspace-write}"
STATE_DIR="${KIPI_STATE_DIR:-$HOME/.config/kipi}"
ATTEMPTS="$STATE_DIR/linear-worker-attempts.json"
# THE one writer of that ledger. Six functions here used to each do their own
# unsynchronised read-modify-write on it (sp-53b02cc4); codex round 5 caught that
# my round-4 lock covered only one of the six.
LEDGER="$SCRIPT_DIR/attempts-ledger.py"
LOG="$STATE_DIR/linear-worker.log"
REVIEWS_DIR="$STATE_DIR/pr-reviews"
# Verdict semantics shared with pr-review-agent.sh -- one extractor, one gate.
. "$SCRIPT_DIR/pr-verdict-lib.sh"
# THE ONE SLUG DERIVATION (ASK-738). gh binds to cwd and ignores every path
# variable here, so every gh call below is scoped with -R from this lib.
. "$SCRIPT_DIR/repo-slug-lib.sh"

MAX_ATTEMPTS=3
# Conflict rounds are capped SEPARATELY from failed attempts (ASK-212).
# MAX_ATTEMPTS counts two things, and it used to count only the first:
#   1. runs where `claude` exits non-zero
#   2. runs that exit 0 and open NO PR (added 2026-07-30, ASK-221)
# Case 2 was the gap. An agent exiting 0 with nothing written was invisible to
# the counter, so the issue stayed at `attempt 1/3` forever and was immediately
# re-dispatchable -- it could never become stuck, so it never stopped costing
# budget. Budget day 2026-07-30 was spent entirely on that: ASK-149 twice and
# ASK-148 once, all `ok`, all zero commits, all converge STOP exit-7.
# The cited rebase failure mode (an agent that exits 0 having done the WRONG
# thing, as opposed to nothing) is still not counted here, which is why conflict
# rounds keep their own separate counter below.
# 2: a rebase either works on the first honest attempt or the conflict needs a
# human. Round 3 has never been the one that lands it here.
#
# WHAT THIS CAP DOES *NOT* DO (PR #25 review, finding 4): it does not buy a
# converged PR an exemption from review. A rebase REWRITES the diff, so the
# stored APPROVE no longer describes what is on the branch, and the round below
# re-reviews it like any other push. Skipping that would ship a force-pushed
# diff nobody ever read under an approval earned by a different diff. What the
# separate counter buys is that a rebase cannot spend MAX_ATTEMPTS and cannot
# loop forever -- two budgets, two questions, neither one a licence to skip the
# reviewer. `rounds` therefore counts every review this worker triggered,
# rebases included, and `conflict_rounds` says how many of the current streak
# were rebases.
MAX_CONFLICT_ROUNDS=2
# Drift rounds (gate 40) are capped SEPARATELY again, for the reason
# pr-verdict-lib.sh already states about gate 30: "Making APPROVE non-terminal
# opens an unbounded rework path ... every round writes a permanent Linear
# comment on an object that cannot be deleted ... The caller caps conflict rounds
# on its own budget." Gate 40 ALSO makes APPROVE non-terminal, and when ASK-219
# first wired it this caller gave it no budget at all. Measured on that build:
# 5 scheduled runs against one persistently-failing reviewer spent 5 model
# rounds, wrote 10 permanent Linear comments, paged nobody, and left
# conflict_rounds -- the only budget in the file -- at 0.
#
# 2, matching the conflict cap: a drift clears the moment ANY review writes a
# record pinned to the current head, so two rounds that both failed to produce
# one means the reviewer is down or the head keeps moving under it. Neither is
# fixed by a third round; both need a human.
MAX_DRIFT_ROUNDS=2
TIMEOUT_SECONDS=1800
LIMIT=1
APPLY=0
ONLY_ISSUE=""
TARGET_REPO_ARG=""

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --limit) shift; LIMIT="${1:-1}" ;;
    --issue) shift; ONLY_ISSUE="${1:-}" ;;
    --repo) shift; TARGET_REPO_ARG="${1:-}" ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
  shift || true
done

# --- WHICH REPO THIS RUN WORKS IN ----------------------------------------
# $SKEL used to mean two things at once, and separating them is the whole point
# of this argument:
#
#   TARGET_REPO  the repo the work happens in -- fetch, worktree, auto-merge, and
#                the project-identity lookup that decides which issues are ours.
#   SKEL         where the CONTROL CODE lives: $SKEL/kipi and $SKEL/plugins/prd-os,
#                which the agent prompt tells the agent to run.
#
# THEY ARE NOT INTERCHANGEABLE, and assuming they were is the trap here. Measured
# 2026-08-01: every registered instance carries a synced copy of this worker but
# NO ./kipi entrypoint and no plugins/prd-os. Repointing $SKEL at an instance would
# hand the agent `bash <instance>/kipi linear progress ...` and
# `python3 <instance>/plugins/prd-os/...`, neither of which exists there -- so the
# agent could do the work and then be unable to report or capture any of it.
#
# Defaults to $SKEL, so every existing caller behaves exactly as before.
#
# KIPI_TARGET_REPO is the env form, and it exists for one concrete reason:
# converge.sh drives this script through $WORKER_CMD and forwards only its own
# arguments. The env crosses that boundary by inheritance, so a dispatched
# converge run reaches the right repo without converge.sh needing to change.
TARGET_REPO="${TARGET_REPO_ARG:-${KIPI_TARGET_REPO:-$SKEL}}"
if [ ! -d "$TARGET_REPO" ]; then
  echo "--repo: no such directory: $TARGET_REPO" >&2; exit 1
fi
TARGET_REPO="$(cd "$TARGET_REPO" && pwd)"
export TARGET_REPO
# The target's slug, resolved ONCE. Every gh scope and every artifact path in
# this script reads it from here (ASK-738).
TARGET_SLUG="$(slug_for_repo "$TARGET_REPO" "${KIPI_SLUG_REGISTRY:-$SKEL/instance-registry.json}")"

# --- WHICH REPO EVERY `gh` CALL ASKS ABOUT (ASK-738) ----------------------
# `git -C "$TARGET_REPO"` redirects the git half of this script. It does NOT
# redirect `gh`, which resolves its repo from the PROCESS CWD -- and
# kipi-dispatch.sh:205 leaves that cwd in the HOME checkout. Measured: the
# existing-PR lookup below answered about kipi-system while the work happened
# in the target. Derived ONCE, here, and spliced into every gh call as -R.
# Empty for a repo with no pinned remote and no origin: the calls then behave
# exactly as they did before, which is correct only because that case is the
# dispatcher's own checkout.
KIPI_GH_REPO_ARGS="$(gh_repo_args "$TARGET_SLUG")"
export KIPI_GH_REPO_ARGS

export SCRIPT_DIR
mkdir -p "$STATE_DIR"
TS() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "$(TS) $*" | tee -a "$LOG"; }

# A distinct session token per run. The claim lock keys collisions on (agent,
# session), so without a unique token two overlapping runs would look like the
# same session and BOTH be granted -- the exact scar the lock exists to stop.
SESSION="worker-$(date +%s)-$$"
AGENT="sana"

# Wall clock, exit 4 of loop-exits.md. macOS ships NEITHER `timeout` nor `gtimeout`
# unless coreutils is installed, and the old fallback here was an empty string --
# i.e. silently no wall clock at all, which is the runaway-agent case this exit
# exists for. Never degrade a safety exit to a warning: implement it in bash.
#
# THE JOB GETS ITS OWN PROCESS GROUP, and nothing it started outlives it (Codex
# round 3 on PR #141, major). `kill -TERM "$job"` signals ONE pid -- the
# `bash -c` wrapper -- and the agent runs as its GRANDchild, so the wrapper died
# on time and `claude` kept running. Worse, `wait "$job"` returns the instant
# that wrapper dies, and the next line cancels the watchdog, so the TERM ->
# sleep 5 -> KILL escalation never reached the process that was actually stuck.
#
# What that costs is not a stray process, it is a WRONG LINEAR COMMENT. The
# leaked agent still holds the worktree, and worktrees are reused across issues
# by design: it writes `.sana-blocked-capability` minutes later, after the next
# dispatch has cleared the sentinels and while its own agent is running. The
# worker reads a refusal the current issue's agent never wrote, labels the wrong
# issue blocked:capability, and copies the previous issue's reason into Linear.
# The clear one round earlier cannot help -- a clear cannot outrun a writer that
# is still running.
#
# `set -m` is load-bearing, not decoration. Without job control a background job
# INHERITS the worker's own process group, so `kill -- -$job` would either fail
# (no such group) or signal the worker itself. With it, the job is the leader of
# a group of its own and the whole tree under it can be signalled by pgid.
run_bounded() {  # run_bounded <seconds> <cmd...>
  local secs="$1"; shift
  set -m
  "$@" &
  local job=$!
  set +m
  ( sleep "$secs"; kill -0 "$job" 2>/dev/null && {
      echo "$(TS) TIMEOUT after ${secs}s; killing process group $job" >>"$LOG"
      kill -TERM -"$job" 2>/dev/null
      sleep 5
      kill -KILL -"$job" 2>/dev/null
    } ) &
  local watchdog=$!
  wait "$job"; local rc=$?
  kill "$watchdog" 2>/dev/null   # cancel the watchdog if the job finished first
  wait "$watchdog" 2>/dev/null
  # SYNCHRONOUS, and on the success path too: a job that exited 0 can still have
  # left a child behind, and the caller's next act is to dispatch another agent
  # into the same tree. run_bounded returning is the promise that the previous
  # run is over.
  reap_group "$job"
  return "$rc"
}

# reap_group <pgid>: return only when that process group is empty.
#
# `kill -0 -- -<pgid>` is the read, not `ps`: it answers "does any process in
# this group still exist" with the same permission check the kills use. The
# common case is an already-empty group, which costs one syscall and no wait.
#
# TERM first with the same 5s grace the watchdog uses -- a child mid-write gets
# the same chance to flush it had before -- then KILL, which cannot be ignored.
# Both loops are bounded: this runs on the worker's critical path, and a reaper
# that can hang is a worse failure than the leak it fixes.
reap_group() {
  local pgid="$1" i=0
  kill -0 -- -"$pgid" 2>/dev/null || return 0
  echo "$(TS) reaping leftover process group $pgid" >>"$LOG"
  kill -TERM -- -"$pgid" 2>/dev/null
  while [ "$i" -lt 20 ] && kill -0 -- -"$pgid" 2>/dev/null; do sleep 0.25; i=$((i+1)); done
  kill -0 -- -"$pgid" 2>/dev/null || return 0
  kill -KILL -- -"$pgid" 2>/dev/null
  i=0
  while [ "$i" -lt 20 ] && kill -0 -- -"$pgid" 2>/dev/null; do sleep 0.1; i=$((i+1)); done
  if kill -0 -- -"$pgid" 2>/dev/null; then
    echo "$(TS) WARNING: process group $pgid survived SIGKILL" >>"$LOG"
  fi
}

# --- FETCH ONCE, BEFORE ANY WORKTREE EXISTS ---------------------------------
# ASK-211 (sp-28ced3d6). This script used to contain no `git fetch` at all: it
# cut every worktree from whatever local origin/main ref happened to be lying
# around, so the agent was dispatched against a base that could be arbitrarily
# old. Observed 2026-07-27 -- ASK-150 was sent to resolve a conflict against
# main, merged 3b60af0, and the conflict survived because main was already
# 72c782d. The agent did the right thing to the wrong target and two rounds
# were burned.
#
# ONCE PER RUN, not per issue: origin does not move meaningfully inside one run,
# and a 50-issue board would otherwise pay 50 network round-trips to learn the
# same thing. Placed above the picker so no code path can create a worktree
# before it.
#
# A fetch failure is environmental (self-healing-retry.md rule 5), so it stops
# on attempt 1 and is NOT counted against any issue. Continuing would be worse
# than stopping: the whole point is that a stale base silently produces
# plausible work aimed at the wrong target, and the run could not push or open
# a PR against an unreachable origin anyway.
#
# IT PAGES AND EXITS 9, it does not stop quietly (PR #22 review round 3,
# finding 1 -- major). The first version of this guard was `say` + `exit 0`,
# which made an expired credential at 3am byte-for-byte indistinguishable from a
# healthy run with nothing ready: same rc, no Slack, one line in a log nobody
# reads. The issue never became stuck either, because MAX_ATTEMPTS only counts
# DISPATCHED runs. Rule 5 says surface it IMMEDIATELY, and a log line is not
# surfacing.
#
# 9, not 1: 1 is the usage error above, and a caller has to be able to tell an
# environment that is down from a worker that was invoked wrong.
if ! git -C "$TARGET_REPO" fetch --quiet origin 2>>"$LOG"; then
  say "INFRA: git fetch failed in $TARGET_REPO. Stopping before any worktree is cut from a stale base."
  bash "$NOTIFY" "worker: git fetch failed in $TARGET_REPO -- the run did NO work. Check credentials/network." 2>/dev/null || true
  exit 9
fi

# --- repo identity, for the project-scope filter -----------------------------
# The worker cuts EVERY worktree from $TARGET_REPO (which defaults to $SKEL). An issue filed against
# another repo can therefore never reach a terminal state here: the agent lands
# in kipi-system, cannot find the files the DoR names, and exits 0 with no diff.
# Measured against the live board 2026-07-30: of 29 ready issues, 11 were the
# kipi-system project and 18 were for repos this checkout cannot check out --
# under two thirds of the worker's own queue was undispatchable by construction.
# The GraphQL query below has selected project{name} the whole time; nothing read it.
#
# DERIVED, never hardcoded: this same script runs from other skeletons, and a
# literal "kipi-system" would empty every other instance's queue while silently
# disabling the filter here. basename of the checkout is the convention the
# fleet already uses (instance dir name == Linear project name).
#
# KIPI_LINEAR_PROJECT is the override for the instance where those two names
# legitimately differ. It is also the test seam.
# basename is the LAST resort, not the first. instance-registry.json maps every
# instance path to its name, and that name IS the Linear project name -- while the
# directory very often is not:
#   <Persona>_strategy   -> .../<persona>/projects/strategy (basename: strategy)
#   <Persona>_product    -> .../<persona>/projects/product  (basename: product)
#   <Persona>_consultant -> .../consulting                  (basename: consulting)
# Three of the first three checked. Shipping basename alone would have made this
# filter reject every issue on those instances -- caught loud by the MISCONFIG
# guard below rather than as a silently empty queue, but still wrong.
#
# Order: explicit env override, then the registry, then basename.
# ONE REGISTRY READ, TWO FACTS (ASK-729). sp-421fa27d already records that the
# project-name derivation is duplicated between this script and
# spillover-promote.py. Reachability needs the SAME registry, so the fix was
# either a second reader here or one read that answers both questions. This is
# the second: it returns this repo identity AND the set of project names whose
# checkout exists on this machine, from a single parse.
#
# The path being looked UP is the target; the registry doing the looking up is
# always the skeleton. An instance carries no instance-registry.json, so
# reading it from the target would fall through to basename for every repo and
# quietly re-break the filter for exactly the three instances named below.
#
# registry_ok is carried explicitly and is NOT the same as an empty list. An
# unreadable registry means reachability is UNKNOWN, and reporting unknown as
# unreachable would fire a loud false alarm on every project at once -- the
# failure mode this issue exists to remove, pointed the other way.
#
# THE ALIAS IS A FIELD, NOT A GUESS (ASK-840). The row's `name` was read as if it
# WERE the Linear project name. Nothing ever required those two namespaces to
# agree, and measured against the live board on 2026-08-15 they do not: two rows
# whose checkouts were on disk that minute carried registry names spelled
# differently from their board projects, and 17 of the 44 issues reported
# UNREACHABLE were on them. The log told the operator to clone repos he already
# had. `linear_project` states the mapping instead of deriving it, because a
# name-derivation guess is what produced the bug and a smarter guess would only
# move the day it breaks.
#
# ONE DERIVATION, BOTH QUESTIONS. linear_project() below answers "what is this
# row called on the board" for the repo-identity lookup AND for the reachability
# set. Deriving the same logical value two ways is how the two sides drifted in
# the first place, so there is exactly one function and both callers use it.
REGISTRY_FACTS="$(SKEL_PATH="$TARGET_REPO" REG="$SKEL/instance-registry.json" python3 - <<'PY' 2>/dev/null
import json, os
skel = os.path.realpath(os.environ["SKEL_PATH"])
ok = True
try:
    reg = json.load(open(os.environ["REG"]))
except Exception:
    reg, ok = [], False
entries = reg.get("instances", reg) if isinstance(reg, dict) else reg
name = ""
local = []


def linear_project(entry):
    """The name this row carries ON THE BOARD. Explicit field first, name second."""
    return (entry.get("linear_project") or entry.get("name") or "").strip()


for e in entries if isinstance(entries, list) else []:
    if not isinstance(e, dict):
        continue
    p = e.get("path")
    if not p:
        continue
    proj = linear_project(e)
    if not name and os.path.realpath(p) == skel:
        name = proj
    if proj and os.path.isdir(p):
        # The pinned remote travels WITH the row, because repo-preflight needs it
        # and re-reading the registry to find it is the second reader ASK-729
        # already refused to add.
        d = e.get("dispatch") if isinstance(e.get("dispatch"), dict) else {}
        local.append({"project": proj, "path": p,
                      "remote": d.get("expected_remote") or ""})
local.sort(key=lambda r: r["project"])
# WHO OWNS THE UNSET POPULATION (codex PR #215 round 6, major). A founder-routed
# issue with no project is claimed by no repo, so an earlier round widened
# founder_scope to include unset -- in EVERY instance at once. All 23 workers
# then paged about the same issue into one Linear queue, each with its own
# ledger, so the dedup could not collapse them and the operator got N tickets to
# close by hand. Exactly one worker has to own it, and the registry already
# DECLARES which one: `skeleton.linear_project`. Read, not guessed -- the same
# reason linear_project() exists twelve lines up.
skel_row = reg.get("skeleton") if isinstance(reg, dict) else None
skeleton_project = linear_project(skel_row) if isinstance(skel_row, dict) else ""
print(json.dumps({"name": name, "local_repos": local, "ok": ok,
                  "skeleton_project": skeleton_project}))
PY
)"
_facts_get() { printf '%s' "$REGISTRY_FACTS" | python3 -c "import json,sys;d=json.load(sys.stdin);v=d.get('$1');print('\n'.join(v) if isinstance(v,list) else v)" 2>/dev/null; }
# Structured facts travel as JSON. _facts_get flattens a list to newlines, which
# silently mangles a list of objects into the string "[object]"-shaped nonsense.
_facts_json() { printf '%s' "$REGISTRY_FACTS" | python3 -c "import json,sys;print(json.dumps(json.load(sys.stdin).get('$1')))" 2>/dev/null; }

REPO_PROJECT="${KIPI_LINEAR_PROJECT:-}"
[ -n "$REPO_PROJECT" ] || REPO_PROJECT="$(_facts_get name)"
[ -n "$REPO_PROJECT" ] || REPO_PROJECT="$(basename "$TARGET_REPO")"
export REPO_PROJECT

LOCAL_REPOS="$(_facts_json local_repos)"
REGISTRY_OK="$(_facts_get ok)"
# Empty when the registry is unreadable, or on an instance that carries none.
# The picker treats empty as "nobody declared an owner", which narrows the scope
# rather than widening it -- see founder_scope.
SKELETON_PROJECT="$(_facts_get skeleton_project)"
export LOCAL_REPOS REGISTRY_OK SKELETON_PROJECT

# --- pick ready issues ------------------------------------------------------
PICKED="$(python3 - "$ONLY_ISSUE" <<'PY'
import importlib.util, json, os, sys, pathlib
here = pathlib.Path(os.environ["SCRIPT_DIR"])
spec = importlib.util.spec_from_file_location("ls", here / "linear-sync.py")
ls = importlib.util.module_from_spec(spec); spec.loader.exec_module(ls)
only = (sys.argv[1] or "").strip()

Q = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}}},first:250,after:$a){
 nodes{id identifier title description state{name type} project{name}
       labels{nodes{name}}} pageInfo{hasNextPage endCursor}}}"""
try:
    tid = ls.graphql('query{teams(filter:{key:{eq:"ASK"}}){nodes{id}}}',{})["teams"]["nodes"][0]["id"]
except Exception as exc:
    print(json.dumps({"infra_error": str(exc)[:200]})); raise SystemExit(0)

issues, after = [], None
while True:
    p = ls.graphql(Q, {"t": tid, "a": after})["issues"]
    issues += p["nodes"]
    if not p["pageInfo"]["hasNextPage"]: break
    after = p["pageInfo"]["endCursor"]

repo_project = os.environ["REPO_PROJECT"]
# Reachability, from the SAME registry read that produced repo_project (ASK-729),
# now carrying the board name, the path and the pinned remote per row (ASK-840).
try:
    local_repos = json.loads(os.environ.get("LOCAL_REPOS") or "[]") or []
except Exception:
    local_repos = []
local_by_project = {r["project"]: r for r in local_repos if r.get("project")}
registry_ok = os.environ.get("REGISTRY_OK", "") == "True"

def project_of(i):
    return (i.get("project") or {}).get("name")

# A FLEET ALERT IS A NOTIFICATION, NOT DISPATCH WORK (ASK-839).
#
# alert-to-linear.py files these and stamps this marker into every one. Their
# body is a raw alert line -- "auto-commit left 3 file(s) uncommitted" -- and
# nobody scoped it. The DoR drafter was writing a Definition of Ready onto them
# anyway, which does not make one executable; it makes it READY-SHAPED, and that
# is the only thing this queue checks.
#
# Measured against the live board 2026-08-15: 19 issues were ready-shaped AND
# project-unset, and ALL 19 were alert tickets -- 43 percent of the whole
# UNREACHABLE bucket, growing by one drafter batch a night out of the remaining
# 62. THE FORK THIS ANSWERS: backfill a project onto the 81, or declare them not
# dispatch work. Backfill was refused on the measurement -- only 33 of the 81
# carry a label that names a real project, 22 were raised from a cwd of / and 16
# from a worktree directory, so a backfill invents routing for the majority and
# then hands a worker an alert line as if it were a spec. They stay on the board,
# labelled and now project-attributed, for a human or a triage pass to convert
# into a real issue; they do not enter the automatic queue.
#
# Keyed on the MARKER THE WRITER ITSELF STAMPS, not the title prefix (prose a
# human edits) and not owner:sana (shared with every real Sana issue).
# NO APOSTROPHE IN THIS HEREDOC. It sits inside a $( ) and bash tracks quote
# state straight through a quoted heredoc there, so one apostrophe in a PYTHON
# COMMENT takes the whole script to "unexpected EOF" 800 lines away. This comment
# is the third time that scar has been earned in this file; the first draft of it
# wrote WRITER-apostrophe-S and the suite went from 24 green to 11 failures.
ALERT_MARKER = "kipi-alert-fingerprint"

def is_fleet_alert(i):
    # MATCHED IN THE WRITERS OWN STRUCTURAL FORM (ASK-839, PR #191 round 4):
    # alert-to-linear.py:515 emits <!-- kipi-alert-fingerprint: <fp> -->. The
    # bare-name test matched any issue whose body merely DISCUSSES the alert
    # mechanism and silently dropped it from this queue -- ASK-839 itself is one,
    # since its description says the tickets carry that marker. Fixed at all three
    # readers together (here, and both call sites in linear-dor-drafter.py):
    # leaving one behind splits the predicate, so the drafter would write a DoR
    # onto an issue this side still refuses to pick.
    #
    # Parsed rather than regexed because there is no re import in this heredoc and
    # adding one is a wider edit than the fix. A comment key must be the WHOLE key,
    # so prose inside some other HTML comment cannot match either.
    for chunk in (i.get("description") or "").split("<!--")[1:]:
        head = chunk.split("-->", 1)[0]
        name, sep, _rest = head.partition(":")
        if sep and name.strip() == ALERT_MARKER:
            return True
    return False

def in_this_repo(i):
    # Unset project is NOT this repo. "Target unknown" and "target is here" are
    # different claims, and treating the first as the second is how 18 foreign
    # issues got into this queue in the first place.
    return project_of(i) == repo_project

def ready(i):
    labels = {l["name"] for l in i["labels"]["nodes"]}
    if "owner:assaf" in labels:      return False   # founder decision, hands off
    if "owner:sana" not in labels:   return False
    # A REJECTION BY SANA, MADE MACHINE-READABLE (ASK-275).
    # NOTE: no apostrophes anywhere in this heredoc. It sits inside a $( )
    # command substitution, and bash tracks quote state through a quoted
    # heredoc there -- one apostrophe in a PYTHON COMMENT swallowed the rest of
    # the substitution and the whole script died at "unexpected EOF".
    # Before this label the only way to get a correctly-refused issue out of the
    # queue was to relabel it `owner:assaf` -- the FOUNDER queue -- which is how
    # ASK-149 got there on 2026-07-30. Routing an engineering re-scope to the
    # founder is the thing this loop exists to avoid, so the refusal needed a
    # label of its own that means "re-scope this", not "the founder decides".
    if "needs-scope" in labels:      return False
    # blocked:capability is the OTHER terminal refusal: the spec is fine, the
    # runner lacks something it cannot grant itself (a harness permission, a
    # missing tool). Excluded for the same reason, routed somewhere different.
    if "blocked:capability" in labels: return False
    if i["state"]["type"] not in ("backlog", "unstarted"): return False
    if is_fleet_alert(i):            return False   # ASK-839, see ALERT_MARKER
    if not in_this_repo(i):          return False
    d = i.get("description") or ""
    return "## Definition of Ready" in d or "Definition of Ready" in d

# Everything the project filter is ABOUT to drop, counted before it drops it, so
# the run can report the shrink. A queue that silently falls from 29 to 11 is
# indistinguishable from a broken query, and "it got quiet" is the failure mode
# this filter could most easily cause.
def ready_ignoring_project(i):
    labels = {l["name"] for l in i["labels"]["nodes"]}
    return ("owner:assaf" not in labels and "owner:sana" in labels
            and "needs-scope" not in labels and "blocked:capability" not in labels
            and not is_fleet_alert(i)
            and i["state"]["type"] in ("backlog", "unstarted")
            and "Definition of Ready" in (i.get("description") or ""))

# BOTH SELECTORS, OR THE FIX IS HALF DONE. ready() alone would stop an alert
# ticket being WORKED while leaving it in `dropped`, so it would keep being
# reported UNREACHABLE forever -- the same 19-issue line, now describing work the
# loop has already decided it will never take. A bucket nobody can act on and
# nobody intends to act on is not a backlog, it is noise on the one line an
# operator reads at 3am.

dropped = [i for i in issues if ready_ignoring_project(i) and not in_this_repo(i)]

# TWO POPULATIONS, NOT ONE (ASK-729). Every out-of-repo issue used to be reported
# on a single "skipped as out-of-repo" line. On 2026-08-13 that line read 45 and
# it hid the distinction that decides whether anyone can do anything:
#
#   SKIPPED     the project has a checkout on this machine, just not the one this
#               run is in. The dispatcher rotation reaches it on a later turn.
#   UNREACHABLE no checkout exists for it anywhere here. No rotation, no cursor
#               and no amount of waiting reaches it. Someone must clone the repo
#               or register it before any machine can pick that work up.
#
# Reporting the second as the first is why 45 issues read as a filter doing its
# job for 13 days. An unset project is UNREACHABLE, not skipped: "target unknown"
# is not "target is elsewhere", and it needs a human to set the project.
#
# A THIRD BUCKET, BECAUSE TWO OF THEM WERE BOTH WRONG FOR THE SAME REPOS
# (ASK-840). Resolving the alias moves 17 issues out of UNREACHABLE, and the
# tempting next step -- drop them in with the routine skips -- swaps one false
# sentence for another. "The rotation reaches it on a later turn" is false
# FOREVER for a client engagement repo: repo-preflight check 0 refuses it whether
# or not its name resolves, and no waiting changes that. So reachability answers
# only "is there a checkout", and the preflight verdict (taken from the REAL
# script, in the shell, never re-implemented here) splits what is left.
def has_local_checkout(i):
    name = project_of(i)
    return bool(name) and name in local_by_project

# An unreadable registry means reachability is UNKNOWN. Calling every project
# unreachable there would be a false alarm on the whole board at once, so the
# classification collapses back to the old single bucket and the shell says why.
if registry_ok:
    reachable = [i for i in dropped if has_local_checkout(i)]
    unreachable = [i for i in dropped if not has_local_checkout(i)]
else:
    reachable, unreachable = dropped, []

# One row per reachable project, carrying what the shell needs to run preflight
# against it: the path, the pinned remote, and how many issues ride on the answer.
# An empty path means "no registry row backs this" -- the unreadable-registry
# collapse above -- and the shell treats that as the routine skip it reports
# today, rather than calling a gate it has no target for. NO APOSTROPHE IN THIS
# HEREDOC: it sits inside a $( ) and bash tracks quote state straight through a
# quoted heredoc there, so one in a PYTHON COMMENT takes the whole script to
# "unexpected EOF" 800 lines away. The file carries this scar twice already.
def reachable_rows():
    rows = {}
    for i in reachable:
        proj = project_of(i) or "(unset)"
        row = local_by_project.get(proj) or {}
        r = rows.setdefault(proj, {"project": proj, "path": row.get("path", ""),
                                   "remote": row.get("remote", ""), "count": 0})
        r["count"] += 1
    return [rows[k] for k in sorted(rows)]
# HELD IS A STATEMENT ABOUT OPEN WORK (ASK-841). The team fetch above is the whole
# board, closed rows included, and this helper used to select on label + project
# alone. A refusal label is never removed when the issue finishes -- grep confirms
# nothing in this file calls issueRemoveLabel -- so every issue that was ever
# refused stayed in these counts after it was Done, and the counts could only rise.
# Measured 2026-08-15: the run said "2 issue(s) held at blocked:capability
# (ASK-284 ASK-281)" while ASK-281 was Done. The true number was 1.
#
# That matters because the blocked:capability count is the ONLY signal that this
# loop is starving on a capability nobody granted (see its reporting site below).
# A number that never falls reports the same alarm whether or not anything is
# blocked, which is the same as reporting nothing.
#
# TERMINAL types are excluded rather than open types allowlisted, deliberately.
# An allowlist of (backlog, unstarted, started) would silently drop an issue
# parked in `triage` -- still open, still refused, still needing someone -- and a
# held issue missing from the count is invisible in a way an extra one is not.
# ASK-288 owns re-testing whether a block still applies; this is only the count.
TERMINAL_STATES = ("completed", "canceled")

def held_with(label, scope=in_this_repo):
    return [i for i in issues
            if label in {l["name"] for l in i["labels"]["nodes"]} and scope(i)
            and i["state"]["type"] not in TERMINAL_STATES]

# THE FOUNDER POPULATION IS SCOPED WIDER THAN THE WORK POPULATION (codex PR #215,
# minor). `in_this_repo` treats an unset project as NOT this repo, which is right
# for deciding what to WORK -- "target unknown" and "target is here" are different
# claims and conflating them is how 18 foreign issues got into this queue. It is
# wrong for deciding what to REPORT: an owner:assaf issue with no project set is
# founder-routed work that no repo's worker claims, so under the narrow scope
# every worker in the fleet stays silent about it and it is invisible everywhere.
# That is the precise failure the directive closes -- a refilling founder queue
# that looks identical to an empty board.
#
# Unset is included; ANOTHER repo's project is still excluded. A worker paging
# about issues routed at a different checkout would put the same line on every
# run in the fleet, which is the cry-wolf shape founder-notifications.md names.
#
# AND THE UNSET HALF IS OWNED BY ONE WORKER, NOT ALL OF THEM (codex PR #215
# round 6, major). `or project_of(i) is None` alone put the same unset issue in
# the founder population of every instance. Each one keeps its own attempts
# ledger, so the per-id dedup cannot collapse pages across them, and the
# alert-to-linear fingerprint cannot either: measured here, two workers whose
# founder populations differ by one id hash differently (d5547a63 vs ff6479df),
# so the fleet opens one Linear ticket per instance for one mislabelled issue.
# That is the cry-wolf shape again, arrived at through the fix for invisibility.
#
# NOTE: no apostrophes anywhere in this heredoc. It sits inside a $( ) command
# substitution and bash tracks quote state through a quoted heredoc there.
#
# The owner is DECLARED, never derived: the skeleton.linear_project field in
# instance-registry.json. An empty value -- unreadable registry, or an instance
# that carries none -- means nobody claims the unset population here, so the
# scope NARROWS to this repo. Failing narrow is right for a widening: a fleet
# that under-reports one unset issue is recoverable, a fleet where all 23
# workers page about it is the flood this rule exists to stop.
unset_owner = os.environ.get("SKELETON_PROJECT", "").strip()
owns_unset = bool(unset_owner) and unset_owner == repo_project


def founder_scope(i):
    return in_this_repo(i) or (owns_unset and project_of(i) is None)

deferred = held_with("needs-scope")
# owner:assaf IS AN ERROR PATH NOW, NOT A QUEUE (ASK-353, founder directive
# 2026-08-03: nothing should be on me). The archived PRD
# prd-terminal-state-redrive-2026-08-01 called this label the one place routing
# to a person is by design. The founder closed that queue and emptied it (85
# issues), so a non-empty count is a DEFECT and the run has to say so out loud
# rather than filter it in silence. ready() still excludes these -- working an
# issue the founder marked hands-off would be worse than reporting it -- but the
# population is now counted and reported, so a refilling queue is loud.
founder_routed = held_with("owner:assaf", founder_scope)
# Counted SEPARATELY from needs-scope. A rising blocked:capability count is a
# claim about the ENVIRONMENT, and averaging it into "held" would hide the one
# number that says the loop is starving for a capability nobody has granted.
blocked_cap = held_with("blocked:capability")

pool = [i for i in issues if ready(i)]
# An explicit --issue is a DRIVER OVERRIDE and deliberately skips the filter:
# converge.sh and an explicit kipi-work invocation both name an issue the picker
# already chose, and a rework round must be able to return to it. The job of the
# filter is choosing, not vetoing a choice already made.
# NOTE: no backticks either. Inside a $( ) a backtick opens a nested command
# substitution even here, which is the second way this heredoc has been broken.
if only:
    pool = [i for i in issues if i["identifier"] == only]

print(json.dumps({
    "ready": [{"id": i["identifier"], "title": i["title"], "project": project_of(i)}
              for i in pool],
    "total_open": len(issues),
    "dropped_out_of_repo": len(dropped),
    "dropped_projects": sorted({project_of(i) or "(unset)" for i in dropped}),
    # ASK-729: the same population, split by whether anyone here can act on it.
    # ASK-840: the reachable half is emitted as rows, not a count, because the
    # shell has to ask repo-preflight about each one before it can say which of
    # them a later rotation turn actually reaches.
    "reachable_rows": reachable_rows(),
    "unreachable": len(unreachable),
    "unreachable_projects": sorted({project_of(i) or "(unset)" for i in unreachable}),
    "unreachable_ids": [i["identifier"] for i in unreachable],
    "registry_ok": registry_ok,
    "deferred_needs_scope": len(deferred),
    # ASK-353. Reported as a DEFECT count, not a queue depth.
    "founder_routed": len(founder_routed),
    "founder_routed_ids": [i["identifier"] for i in founder_routed],
    "blocked_capability": len(blocked_cap),
    "blocked_capability_ids": [i["identifier"] for i in blocked_cap],
    # Does the derived repo identity name a project that EXISTS on the board?
    # If not, every issue fails in_this_repo() and the queue reads a healthy
    # empty -- a permanently silent loop reporting success. That is strictly
    # worse than the bug being fixed here, so it is called out as MISCONFIG
    # rather than allowed to look like a finished board.
    "project_known": any(project_of(i) == repo_project for i in issues),
    "repo_project": repo_project,
}))
PY
)"

INFRA="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("infra_error",""))' 2>/dev/null)"
if [ -n "$INFRA" ]; then
  say "INFRA: linear unreachable ($INFRA). Not counted against any issue."
  exit 0
fi

READY_COUNT="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["ready"]))')"

# MISCONFIG BEFORE ANY COUNT IS BELIEVED (ASK-275). Checked ahead of the ready
# line because if the derived project matches nothing on the board, that count
# is 0 for a reason that has nothing to do with the board being empty. Reporting
# "nothing ready" there would be a loop that stopped working while claiming to
# be finished -- the one outcome worse than the queue it replaced. It PAGES and
# exits non-zero for the same reason the git-fetch guard at line 203 does: a log
# line is not surfacing, and this is environmental, not an issue's fault.
PROJECT_KNOWN="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("project_known"))' 2>/dev/null)"
if [ "$PROJECT_KNOWN" = "False" ]; then
  say "MISCONFIG: repo identity '$REPO_PROJECT' (from $TARGET_REPO) matches NO Linear project on team ASK."
  say "MISCONFIG: every issue would be filtered out, so this run picked nothing for a config reason, not an empty board."
  say "MISCONFIG: fix by renaming the Linear project to match the checkout, or set KIPI_LINEAR_PROJECT."
  bash "$NOTIFY" "kipi worker: repo identity '$REPO_PROJECT' matches no Linear project, so the queue reads empty and NO work can ever be picked. Do: set KIPI_LINEAR_PROJECT in the worker's environment, or rename the project to match the checkout." 2>/dev/null || true
  exit 9
fi

# THE REACHABLE HALF IS SPLIT BY THE REAL GATE, NOT BY A COPY OF ITS RULES
# (ASK-840). A project with a checkout is not therefore dispatchable, and the
# difference is exactly what repo-preflight.sh already decides. Re-implementing
# its client-repo test here would be a second copy of the one refusal the founder
# said must hold everywhere -- and the copy is what goes stale. So preflight is
# executed, once per distinct project, and its own words become the reason.
#
# CHEAP FOR THE CASE THAT MATTERS: check 0 is decided on path shape and exits
# before any network call, so every client repo costs a fork and nothing else.
# The handful that get past it pay a few gh calls once per run, not per issue.
PREFLIGHT="$SCRIPT_DIR/repo-preflight.sh"
# UNIT SEPARATOR, NOT TAB. Tab is an IFS WHITESPACE character, so bash collapses
# runs of it however IFS is set -- and an unpinned row has an EMPTY remote, which
# is the common case here (only two registry rows pin one). Measured with a probe
# on a 4-field row whose third field was empty: read landed the COUNT in $_remote
# and left $_cnt unset, so every reachable project scored 0 issues and both report
# lines below vanished entirely. \037 is not IFS whitespace, so an empty field
# stays an empty field. kipi-dispatch.sh:640 reads its rotation rows the same way
# and carries the same latent hole (captured as spillover, not fixed here).
REACH_ROWS="$(printf '%s' "$PICKED" | python3 -c 'import json,sys
for r in json.load(sys.stdin).get("reachable_rows", []):
    print("\037".join([r.get("project",""), r.get("path",""), r.get("remote",""), str(r.get("count",0))]))' 2>/dev/null)"

DROPPED=0; DROPPED_IN=""; REFUSED_N=0; REFUSED_IN=""
while IFS=$'\037' read -r _proj _path _remote _cnt; do
  [ -n "${_proj:-}" ] || continue
  _cnt="${_cnt:-0}"
  # No path means no registry row backs this project (the unreadable-registry
  # collapse). Reporting it as today's routine skip is the honest answer: we
  # cannot ask the gate anything without a target.
  if [ -z "${_path:-}" ] || _pf_out="$(bash "$PREFLIGHT" "$_path" "${_remote:-}" 2>&1)"; then
    DROPPED=$((DROPPED + _cnt))
    DROPPED_IN="${DROPPED_IN:+$DROPPED_IN, }$_proj"
  else
    REFUSED_N=$((REFUSED_N + _cnt))
    # THE CHECK NAMES, NOT THE FULL MESSAGES. One failed check carries a fix
    # command long enough to bury the line it is on, and this is read in a daily
    # digest. The class of refusal is what tells a permanent one (client-repo)
    # from a curable one (control-code), which is the decision being supported.
    _why="$(printf '%s' "$_pf_out" | grep '^FAIL' | sed 's/^FAIL \([^:]*\):.*/\1/' | tr '\n' ',' | sed 's/,$//')"
    REFUSED_IN="${REFUSED_IN:+$REFUSED_IN; }$_proj (${_why:-refused})"
  fi
done <<REACHEOF
$REACH_ROWS
REACHEOF

UNREACH="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("unreachable",0))' 2>/dev/null)"
UNREACH_IN="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;print(", ".join(json.load(sys.stdin).get("unreachable_projects",[])))' 2>/dev/null)"
REG_OK="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("registry_ok",True))' 2>/dev/null)"
DEFERRED="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("deferred_needs_scope",0))' 2>/dev/null)"

say "worker: $READY_COUNT ready issue(s) (owner:sana, has a DoR, not owner:assaf, project=$REPO_PROJECT)"
# Accounted for, never silently dropped. These two lines are what let an operator
# tell a working filter from a broken query without re-querying Linear by hand.
[ "${DROPPED:-0}" != "0" ] && say "worker: $DROPPED ready-shaped issue(s) skipped as out-of-repo (other project: $DROPPED_IN) -- this checkout is $REPO_PROJECT and cannot check those out"
# THE THIRD BUCKET (ASK-840). Reachable, and refused anyway. Stated on its own
# line for the same reason UNREACHABLE was: the response differs. A routine skip
# resolves itself on a later rotation turn, an unreachable repo needs a clone, and
# this one needs either a cure (control-code drift) or nothing at all ever
# (client-repo, which no rotation and no cure will change). Collapsing it into the
# skip line promises the operator a turn that is never coming.
[ "${REFUSED_N:-0}" != "0" ] && say "worker: $REFUSED_N ready-shaped issue(s) REFUSED by preflight: the checkout exists but the gate will not let a dispatcher in -- $REFUSED_IN"
# UNREACHABLE IS NOT A ROUTINE SKIP, AND NEVER SHARES ITS LINE (ASK-729). A skip
# resolves itself on a later rotation turn; this does not resolve at all until a
# human clones or registers the repo. It is stated separately, with the project
# names and the count, on every run -- because the failure being fixed here is
# 13 days of a real backlog reading as normal filter output.
[ "${UNREACH:-0}" != "0" ] && say "worker: $UNREACH ready-shaped issue(s) UNREACHABLE: no local checkout for $UNREACH_IN -- no dispatcher on this machine can reach them until those repos are cloned and registered"
# Fail loud rather than classify on a guess (see registry_ok in the picker).
[ "$REG_OK" = "False" ] && say "worker: WARNING instance-registry.json could not be read, so reachability is UNKNOWN this run and every out-of-repo issue is reported as a routine skip"
[ "${DEFERRED:-0}" != "0" ] && say "worker: $DEFERRED issue(s) held at needs-scope (refused as unexecutable; the DoR drafter re-scopes them)"

# THE FOUNDER QUEUE IS AN ERROR PATH (ASK-353). Directive 2026-08-03: "nothing
# should be on me". The archived PRD called owner:assaf the designed destination
# for founder-routed work; that decision is reversed, the queue was emptied (85
# issues) and it must never refill. So a non-zero count is stated as a DEFECT on
# its own line, and paged -- because the failure mode being closed here is
# exactly the silent one: ready() filtered these out without a word, so a
# refilling founder queue looked identical to an empty board.
#
# NOT a hard exit. Refusing to run would let one mislabelled issue stop the whole
# loop, which routes MORE work to the founder, not less. Loud and still working
# is the behaviour the directive asks for.
FOUNDER_ROUTED="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("founder_routed",0))' 2>/dev/null)"
if [ "${FOUNDER_ROUTED:-0}" != "0" ]; then
  FOUNDER_IDS="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;print(" ".join(json.load(sys.stdin).get("founder_routed_ids",[])))' 2>/dev/null)"
  say "worker: DEFECT: owner:assaf is an ERROR PATH, not a queue (founder directive 2026-08-03), and $FOUNDER_ROUTED open issue(s) carry it: ${FOUNDER_IDS:-unknown}"
  say "worker: DEFECT: whatever routed those to the founder is the bug. Re-label them owner:sana with a DoR, or needs-scope if the spec is not executable."

  # THE LOG LINES ABOVE FIRE EVERY RUN. THE PAGE DOES NOT (codex PR #215, major).
  # The worker ticks every 15 minutes, so an unguarded page here meant the same
  # sentence on the founder phone ~96 times a day for as long as one mislabelled
  # issue sat there -- and this alert asks for a HUMAN relabel, so it necessarily
  # keeps firing until he acts. That is cry-wolf by construction: the louder it
  # gets the faster it is muted, and a muted channel is how the silent board this
  # whole reversal exists to kill comes back wearing a different coat.
  #
  # DEDUPED PER ISSUE ID, NOT PER RUN AND NOT PER POPULATION. Per run pages every
  # tick (the bug). Per population re-pages on every DEPARTURE too -- relabel one
  # of four and the remaining three look like a new episode -- so the fix would
  # page most on a queue being correctly drained. Per id is the honest unit: each
  # newly founder-routed issue is one new instance of the routing bug, and it is
  # announced once.
  #
  # ONE CONSOLIDATED LINE, never one per id (founder-notifications.md). The claim
  # is about the routing, not about each issue; N pages for N issues is the same
  # cry-wolf failure in a smaller font. New ids decide WHETHER to page, the full
  # population is what the line REPORTS.
  #
  # Uses the ledger's claim-flag verb directly rather than page_once(), which is
  # defined ~200 lines below this block. This site cannot move down to reach it:
  # the `READY_COUNT = 0` early exit sits between them, and an empty board with a
  # refilling founder queue is exactly the case that must still page.
  # THE CLAIM IS PROVISIONAL, AND THE RECOVERY IS NOT ON THIS LINE. Read this
  # before concluding that a kill here mutes the issue forever (codex PR #215
  # round 7 raised exactly that, having probed only for a `trap` between the
  # claim and the send; there is none, and none is needed):
  #
  #   claim-flag <id> founder-routed         <- here. provisional.
  #   claim-flag <id> founder-routed-filed   <- only after the notifier exits 0
  #   the sweep below the FOUNDER_ROUTED block releases any founder-routed flag
  #   whose -filed marker is absent, on the NEXT tick
  #
  # So a SIGKILL, a reboot or launchd stopping the job between these two leaves
  # a claimed-but-unfiled flag, and the next run releases it and pages. That is
  # the reclaim-after-the-fact shape; it needs no in-process handler, because a
  # kill runs no handler. Proven end to end by test-worker-project-scope.sh case
  # 6h, whose fixture is the exact ledger state a kill leaves, written by the
  # ledger CLI -- and mutation-killed: treat an unfiled claim as filed and 6h
  # goes red.
  FOUNDER_NEW=""
  for fid in $FOUNDER_IDS; do
    rc=0
    python3 "$LEDGER" "$ATTEMPTS" claim-flag "$fid" founder-routed >/dev/null 2>&1 || rc=$?
    case "$rc" in
      0) FOUNDER_NEW="$FOUNDER_NEW $fid" ;;
      1) : ;;   # already announced on an earlier run -- stay quiet
      # 2 = nothing written, 3 = lock contended. Same routing as ledger_fault():
      # the caller writes NOTHING, because a page whose dedup did not record is a
      # page that repeats forever (exit 2) -- the failure being fixed here. Exit 3
      # defers by one cycle, it does not drop.
      *) say "WARN: the attempts ledger did not record the founder-routed flag for $fid (exit $rc) -- not paging, to avoid an undeduplicated repeat. Check $ATTEMPTS is writable." ;;
    esac
  done
  # THE CLAIM IS PROVISIONAL UNTIL THE ALERT IS FILED (codex PR #215 round 3,
  # major). The flag was claimed above and the send's status was thrown away by
  # `|| true`, so ONE failed send -- a 20s timeout, a Linear 500, an unset API key
  # on a fresh machine -- marked the issue announced forever. The next tick read
  # the flag, stayed quiet, and the founder queue refilled in silence: the exact
  # failure this whole block exists to end, now reached through the fix for it.
  #
  # CLAIM-THEN-CLEAR, not send-then-claim. The invariant that ordering protects is
  # the one the dedup was built for: a page must never go out without its dedup
  # already recorded, because a page whose flag did not land repeats every 15
  # minutes forever. Sending first inverts that. So the claim stays first and a
  # send that did not file gives it back.
  #
  # slack-notify.sh's exit contract (its own header) is what makes this decidable
  # rather than a guess: 0 filed, 1 attempted and failed, 3 no Linear API key
  # configured, 4 refused as a fixture run. Only 0 means a ticket exists, so only
  # 0 keeps the claim. 3 and 4 are not errors and still filed nothing -- holding a
  # claim for them would mean the first page after the key is configured never
  # goes out.
  if [ -n "$FOUNDER_NEW" ]; then
    NRC=0
    bash "$NOTIFY" "kipi worker: $FOUNDER_ROUTED issue(s) are labelled owner:assaf, which is an error path now, not a queue (${FOUNDER_IDS:-unknown}). New since the last page:${FOUNDER_NEW}. Do: find what routed them there and re-label to owner:sana or needs-scope." 2>/dev/null || NRC=$?
    if [ "$NRC" = "0" ]; then
      # THE SECOND HALF OF THE CLAIM (codex PR #215 round 5, major). The claim
      # above is PROVISIONAL: between it and this line the worker can be killed
      # -- launchd stopping the job, a reboot, an OOM -- and the release below
      # only runs when the notifier RETURNED non-zero. A kill returns nothing, so
      # the flag stood with no ticket behind it and that issue was muted forever.
      # The sweep further down cannot see it either: the issue is still IN the
      # founder population, so departure never releases it.
      #
      # So "claimed" and "filed" are two facts and they are recorded separately.
      # A flag that is claimed and not filed is an interrupted announcement, and
      # the sweep releases it on the next tick.
      #
      # A kill in the OTHER window -- after the ticket filed, before this line --
      # costs ONE duplicate page. That direction is chosen deliberately: a
      # repeated page is visible and self-correcting, a swallowed one is the
      # silent founder queue this whole block exists to end.
      for fid in $FOUNDER_NEW; do
        frc=0
        python3 "$LEDGER" "$ATTEMPTS" claim-flag "$fid" founder-routed-filed >/dev/null 2>&1 </dev/null || frc=$?
        # 0 = recorded here, 1 = already recorded (a duplicate page after a kill
        # in the narrow window above). Anything else means nothing was written,
        # so the next run reads an unfiled claim and pages again -- the safe
        # direction, but say it out loud rather than let a duplicate look random.
        case "$frc" in
          0|1) : ;;
          *) say "WARN: filed the owner:assaf alert for $fid but could not record that (exit $frc) -- it will page once more on the next run." ;;
        esac
      done
    fi
    if [ "$NRC" != "0" ]; then
      say "WARN: the owner:assaf alert did NOT file (notifier exit $NRC). Releasing the announce flag for${FOUNDER_NEW} so the next run tries again."
      for fid in $FOUNDER_NEW; do
        crc=0
        python3 "$LEDGER" "$ATTEMPTS" clear-flag "$fid" founder-routed >/dev/null 2>&1 || crc=$?
        # THE ONE CASE THAT STAYS BROKEN, SAID OUT LOUD. If the release also fails
        # the flag is set with nothing filed behind it, which is the bug above. It
        # cannot be fixed from here -- the ledger is the single writer and going
        # around it is how two runs corrupt it -- so it is named, with the command
        # that clears it by hand, instead of leaving one id silently muted.
        [ "$crc" = "0" ] || say "WARN: could not release the founder-routed flag for $fid (exit $crc) -- that issue will NOT page again until: python3 $LEDGER $ATTEMPTS clear-flag $fid founder-routed"
      done
    fi
  fi
fi

# --- RECOVERY RE-ARMS THE ANNOUNCEMENT (codex PR #215 round 4, major) --------
#
# `claim-flag` was set on the first page and cleared on exactly one event: a send
# that failed. Nothing cleared it when the issue RECOVERED. So: ASK-x is
# mislabelled owner:assaf, the page fires, the flag sticks; someone re-labels it
# owner:sana and the issue leaves this population with its flag still held; the
# same issue is mis-routed again next week and `claim-flag` answers 1 -- already
# announced -- and the second occurrence is swallowed. Permanently, until someone
# hand-clears the ledger, which nobody knows to do because there is no page
# telling them to. A detector that stops detecting is worse than no detector: the
# board reads quiet for the same reason it read quiet before this whole block
# existed. Same defect class as clear-automerge in attempts-ledger.py, where a PR
# armed, unarmed and armed again went permanently silent.
#
# THE FLAG MEANS "announced WHILE routed", so departure from the population is
# what releases it. Clearing on departure never pages -- it only re-arms that id
# for a future recurrence -- so it does NOT reintroduce the per-population
# re-paging the block above rejects (relabel one of four and the other three
# stay claimed, because they are still in the population).
#
# RUNS ON EVERY TICK INCLUDING AN EMPTY QUEUE, which is why it sits outside the
# `FOUNDER_ROUTED != 0` guard: the case being fixed is precisely the one where
# the population is now empty and the flags from the last episode are still set.
# It is above the `READY_COUNT = 0` early exit for the same reason the page site
# is: a board with nothing ready still has to re-arm.
#
# SKIPPED, NOT EMPTIED, WHEN THE PICKER OUTPUT IS UNREADABLE. An unparseable
# $PICKED would make the current population read as empty and this sweep would
# release every flag it holds, so the next tick re-pages the entire founder queue
# -- a page storm caused by a broken picker, announcing nothing new. The sentinel
# says the JSON parsed; without it the sweep does nothing and the flags stand.
FOUNDER_POP="$(printf '%s' "$PICKED" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("PARSED")
print(" ".join(d.get("founder_routed_ids", [])))
' 2>/dev/null)"
if [ "$(printf '%s\n' "$FOUNDER_POP" | head -1)" = "PARSED" ]; then
  FOUNDER_STILL=" $(printf '%s\n' "$FOUNDER_POP" | sed -n '2p') "
  while IFS= read -r flagged; do
    [ -n "$flagged" ] || continue
    # TWO WAYS A CLAIM STOPS STANDING FOR A SENT PAGE.
    #
    # (1) The issue LEFT the population: recovered, so the flag must come off or
    #     the next recurrence of that id is swallowed.
    # (2) The claim was never FILED: the worker was killed between claim-flag and
    #     the notifier returning (codex PR #215 round 5, major). Departure alone
    #     cannot see this one -- the issue is still founder-routed, so it stays
    #     in FOUNDER_STILL forever while its flag suppresses every later tick.
    #     The failed-send release below only runs when the notifier RETURNED.
    #
    # Checked in that order because a departed id needs no filed-lookup.
    WHY_RELEASE="is no longer founder-routed"
    case "$FOUNDER_STILL" in
      *" $flagged "*)
        FILED="$(python3 "$LEDGER" "$ATTEMPTS" get "$flagged" founder-routed-filed "" 2>/dev/null </dev/null)"
        # A read that FAILED returns empty too, and empty means "release it" --
        # so an unreadable ledger costs a duplicate page, never a swallowed one.
        [ -n "${FILED:-}" ] && continue
        WHY_RELEASE="was announced but the alert never filed (worker killed mid-announce)"
        ;;
    esac
    src=0
    # </dev/null: this loop reads the flagged list from a heredoc on stdin, and a
    # child inheriting it would eat the remaining ids.
    python3 "$LEDGER" "$ATTEMPTS" clear-flag "$flagged" founder-routed >/dev/null 2>&1 </dev/null || src=$?
    python3 "$LEDGER" "$ATTEMPTS" clear-flag "$flagged" founder-routed-filed >/dev/null 2>&1 </dev/null || true
    if [ "$src" = "0" ]; then
      say "worker: $flagged $WHY_RELEASE -- released its announce flag, so it can page again"
    else
      # Named, not swallowed. A release that did not land leaves that id muted
      # for its next recurrence, which is the defect this sweep exists to close,
      # so it gets the hand command exactly like the failed-send release above.
      say "WARN: could not release the founder-routed flag for $flagged (exit $src) -- that issue will NOT page again if it recurs, until: python3 $LEDGER $ATTEMPTS clear-flag $flagged founder-routed"
    fi
  done <<FRECOVEOF
$(python3 "$LEDGER" "$ATTEMPTS" list-flagged founder-routed 2>/dev/null)
FRECOVEOF
fi

BLOCKED_CAP="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("blocked_capability",0))' 2>/dev/null)"
BLOCKED_IDS="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;print(" ".join(json.load(sys.stdin).get("blocked_capability_ids",[])))' 2>/dev/null)"
# ONE consolidated line per run, never one per issue. Six issues blocked on the
# same missing permission is ONE fact about the environment, and six pages of it
# is the cry-wolf failure founder-notifications.md names. The count is the signal:
# a queue starving on a capability nobody has granted looks identical to a quiet
# queue unless someone says the number out loud.
if [ "${BLOCKED_CAP:-0}" != "0" ]; then
  say "worker: $BLOCKED_CAP issue(s) held at blocked:capability -- the specs are sound, the runner is missing something it cannot grant itself ($BLOCKED_IDS)"
fi

if [ "$READY_COUNT" = "0" ]; then
  say "nothing ready. The DoR drafter feeds this queue; check kipi dor."
  exit 0
fi

attempts_for() { python3 -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: d={}
print(d.get(sys.argv[1],{}).get('count',0))" "$1"; }

# SINGLE-WRITER CHOKEPOINT FOR THE ATTEMPTS LEDGER (codex round 4, major 1).
#
# This was a bare read-modify-write. Two workers finishing together both read the
# same count, both wrote count+1, and one update vanished -- so an issue could
# exceed MAX_ATTEMPTS and keep being dispatched, which is exactly the runaway the
# cap exists to stop. sp-53b02cc4 already recorded FIVE bumpers with this shape;
# the no-PR bump added tonight would have been the sixth. Fixing the shared helper
# fixes all of them at once, which is why it belongs here and not at a call site.
#
# The lock is `fcntl.flock` on the ledger's own lock file. This paragraph used to
# describe an O_EXCL file carrying its owner's token, justified by "macOS ships no
# flock" -- and that justification was simply false (attempts-ledger.py:60 retracts
# it in this same PR; the claim is true of the flock(1) BINARY, which is why
# converge.sh, being bash, does have to hand-roll one). The hand-rolled version had
# to guess whether a leftover lock's owner was alive, and pids wrap, so a corpse
# lock eventually named a live process that never held it and froze the counter
# forever. The kernel drops an flock on close AND on process death, so there is no
# liveness to guess at. Write-temp-then-rename makes the replacement atomic too, so
# a crash mid-write cannot leave a truncated ledger.
#
# KEEP THIS PARAGRAPH TRUE. It is the one a future agent cites when it is told to
# reuse an in-repo lock rather than invent another -- which already happened once,
# on 2026-08-02, and propagated both defects of the version it cited.
#
# A LOCK IT CANNOT TAKE MEANS IT WRITES NOTHING AND EXITS 3 (ASK-286). This
# paragraph used to say the opposite -- that the timeout took the lock BY FORCE
# rather than drop a bump -- and that reasoning was wrong in a way that made the
# lock worse than none: the forced run entered the transaction holding nothing
# and its release then deleted the live holder's lock, so both runs sat inside
# one read-decide-write. A skipped bump is recoverable (the next scheduled run
# retries, and the run that DID hold the lock is counting); two writers in one
# transaction is not. None of the callers below run under `set -e`, so a 3 is a
# reported miss on stderr, not a dead worker -- and that sentence is only true
# because nothing in this script turns errexit on behind them. `page_once` did
# exactly that for one commit (codex round 2), which is why it now reads its exit
# code through a `||` list instead of bracketing the call in `set +e`/`set -e`.
bump_attempt() { python3 "$LEDGER" "$ATTEMPTS" bump-attempt "$1" "$2"; }

# --- conflict-round ledger (ASK-212) ----------------------------------------
# Its own counter in the same file, deliberately NOT `count` (failed attempts)
# and NOT `rounds` (review rounds). Three different budgets answering three
# different questions; sharing one would let a rebase attempt spend a review
# round, which is the thing the separate cap exists to prevent.
conflict_rounds_for() { python3 "$LEDGER" "$ATTEMPTS" get "$1" conflict_rounds 0; }

bump_conflict_round() { python3 "$LEDGER" "$ATTEMPTS" bump-conflict "$1"; }

# CONSECUTIVE, NOT LIFETIME (PR #25 review, finding 3). Nothing used to clear
# these keys, so the cap counted every conflict the issue ever had -- including
# ones a rebase successfully fixed -- and the third conflict across an issue's
# life was permanently un-dispatchable AND silent, because `conflict_paged` was
# already true so it did not even page. A PR that merges cleanly again ended its
# streak, so the streak's counters go with it.
#
# Only on a STATED "CLEAN": empty means gh failed and UNKNOWN means GitHub is
# still computing, and refilling a budget from a state nobody actually read is
# how an unresolvable conflict gets infinite rounds. Clearing conflict_paged
# alongside is deliberate: a NEW conflict streak after the PR was healthy is new
# information, not a repeat of the page the founder already got.
clear_conflict_rounds() { python3 "$LEDGER" "$ATTEMPTS" clear-conflict "$1"; }

# --- drift-round ledger (ASK-219, PR #30 review round 2) ---------------------
# A FOURTH key, deliberately not `count`, not `rounds`, not `conflict_rounds`.
# Four budgets, four questions. A drift round that spent the conflict budget
# would leave a real conflict un-dispatchable later; one that spent `count`
# would mark good work STUCK after three rounds that all ran fine.
drift_rounds_for() { python3 "$LEDGER" "$ATTEMPTS" get "$1" drift_rounds 0; }

bump_drift_round() { python3 "$LEDGER" "$ATTEMPTS" bump-drift "$1"; }

# CONSECUTIVE, NOT LIFETIME -- the same scar clear_conflict_rounds carries (PR
# #25 finding 3). Without this the cap would count every drift in the issue's
# life, so the third genuine drift would be permanently un-dispatchable AND
# silent, because drift_paged was already true.
#
# Cleared on "the gate did not say 40", which is the ONE reader's own answer
# rather than a second sha comparison living out here. 40 is the only code that
# means drift, so anything else means there is none right now: a review has
# repinned the record to the head, or the verdict is no longer approving, or the
# record is gone. Re-deriving that comparison in this file is exactly the
# two-readers-of-one-input defect pr-verdict-lib.sh exists to close.
clear_drift_rounds() { python3 "$LEDGER" "$ATTEMPTS" clear-drift "$1"; }

# Returns 0 the FIRST time <flag> is claimed for this issue and 1 every time
# after, so a page fires exactly once instead of once per scheduled run. A
# repeated "still stuck" every cycle is noise, and noise trains the reader to
# skim the real pages (founder-notifications.md). The flag is claimed in the
# same write that reports it, so two runs cannot both read "not paged yet".
# Takes the flag NAME so every once-only page in this script shares one
# mechanism instead of each stuck-state inventing its own convention.
claim_page_once() { python3 "$LEDGER" "$ATTEMPTS" claim-flag "$1" "$2"; }

# page_once <issue> <flag>: TRUE when this caller should page. Every once-only
# page routes through here rather than through `if claim_page_once`, because
# bash `if` only asks "was the exit 0" and the ledger answers three things
# (ASK-286, codex round 1 on PR #67, finding 2):
#
#   0  claimed here, first time         -> page
#   1  already claimed on a prior run   -> quiet
#   2  nothing written (usage error, or any unexpected failure)  -> ledger fault
#   3  nothing written (lock contended)                          -> ledger fault
#
# The bare `if` collapsed 2 and 3 into the same branch as 1, so a page was
# dropped for a state NO FILE RECORDS -- which means no later run retires it
# either. It is simply gone. That is the silent stall this worker exists to kill,
# re-created inside the mechanism built to kill it.
#
# WHAT 2 AND 3 MUST NOT DO IS RUN THE CALLER'S PAGE (codex round 4, major). They
# used to `return 0`, and `return 0` here means the CALLER writes its artifact --
# which at the stuck site is a permanent Linear comment. The dedup for that
# comment is the ledger flag. So on exactly the two codes that mean THE LEDGER
# DID NOT ANSWER, the worker drove a non-idempotent permanent write with its
# dedup switched off:
#
#   exit 3, contention: run A pages, run B takes the lock and pages   = 2 comments
#   exit 2, unwritable: nothing is ever claimed, so EVERY run posts, forever
#
# Observed pre-fix at 5 comments over 5 cycles and 4 comments for a 4-issue queue
# in ONE run (cases 7-9). "Bounded by the retry budget" was true of contention and
# false of exit 2, and the old comment above generalised from the bounded one.
# Repeating "still stuck" every 15 minutes forever is the cry-wolf failure the
# stuck site's own comment (line 814) says the once-only flag exists to prevent.
#
# So the two codes route to `ledger_fault` instead: return 1 (caller writes
# nothing) and raise the alarm through the EPHEMERAL channel, ONCE PER RUN.
# Nothing is dropped silently -- what changes is which channel hears it and what
# it is about. The fault is the LEDGER, not the issue, so the alert names the
# ledger; a Slack line is idempotent by nature where a Linear comment is not.
#
# The two codes differ in whether a later run recovers, and that difference is in
# the message, not the routing:
#   exit 3  the flag is still UNCLAIMED, so the next cycle claims it and pages.
#           Contention defers a page by one heartbeat; it does not drop it.
#   exit 2  no later run will claim it either, so no later run pages. That is a
#           real drop, and it is why the fault alert has to exist at all.
#
# IT CAPTURES THE CODE WITHOUT TOUCHING THE SHELL'S FLAGS (codex round 2, major).
# This body used to read `set +e; claim_page_once ...; rc=$?; set -e`, and that
# trailing `set -e` does not RESTORE errexit -- it ENABLES it. This script runs
# `set -uo pipefail` (line 47) and has never had `-e`, so the first page in a run
# re-flagged everything after it: the queue drain is a pipeline into `while read`,
# and the next benign non-zero killed it mid-drain while the worker still printed
# "run complete" and exited 0 -- which this file's own header tells callers to
# treat as healthy. A partial drain reported healthy is the silent stall this
# worker exists to kill, which is the second time that class has been re-created
# inside the mechanism built to kill it (finding 2 was the first).
#
# `|| rc=$?` rather than a bare call: inside a `||` list errexit is suspended, so
# this reads the code correctly whether or not a future caller has `-e`, and it
# still leaves the caller's flags exactly as it found them. Case 5 of
# test-claim-page-once-routing.sh asserts `$-` is unchanged across the call, from
# a fork running THIS script's flags -- the suite itself runs `set -euo pipefail`,
# so in-process the leak is invisible.
# ONE ALERT PER RUN, not one per issue. A broken ledger is a property of the
# WORKER, so a 40-issue queue must not send 40 alerts -- that is the same
# cry-wolf failure in the channel we just moved the notice into. Every issue that
# hits it still lands in the run log via `say`; the Slack line fires on the first
# one and names it as an example. Run-scoped state, so the next worker run (a
# fresh process, 15 minutes later) alerts again while the fault is still real.
LEDGER_FAULT_ALERTED=0
ledger_fault() {
  local issue="$1" flag="$2" rc="$3" detail
  case "$rc" in
    3) detail="the lock was contended, so nothing was written. The flag is still UNCLAIMED and the next run will claim it and page -- this defers a page by one cycle, it does not drop it." ;;
    *) detail="the ledger wrote nothing (exit $rc). No later run will claim this flag either, so no later run will page: this state is dropped until the ledger is writable." ;;
  esac
  say "WARN: the attempts ledger did not record the $flag flag for $issue (exit $rc) -- $detail"
  [ "$LEDGER_FAULT_ALERTED" -eq 0 ] || return 0
  LEDGER_FAULT_ALERTED=1
  bash "$NOTIFY" "kipi worker: the attempts ledger at $ATTEMPTS is not answering (exit $rc, first seen on $issue/$flag). Once-only pages cannot be de-duplicated while this holds, so the worker is staying quiet on them rather than re-posting. Do: check the ledger file is writable." 2>/dev/null || true
}

page_once() {
  local rc=0
  claim_page_once "$1" "$2" || rc=$?
  case "$rc" in
    0) return 0 ;;
    1) return 1 ;;
    *) ledger_fault "$1" "$2" "$rc"
       return 1 ;;
  esac
}

# Pops the two auto-merge page flags the moment the PR is SEEN armed. Same scar
# clear_conflict_rounds and clear_drift_rounds both carry (PR #25 finding 3): a
# once-only page with no clear is a page that fires once in an issue's LIFE, so
# the second time the state is real it is silent -- and silent is the failure
# this whole issue exists to kill. Only ever called on a STATED "armed": clearing
# off a state nobody could read would refill the budget from a guess.
clear_automerge_pages() { python3 "$LEDGER" "$ATTEMPTS" clear-automerge "$1"; }

# --- arm auto-merge (ASK-222) ------------------------------------------------
# arm_automerge <pr-number> <dir>: make GitHub own the merge, and publish what
# that attempt actually reached. Sets $AUTOMERGE to armed | unarmed | unknown.
#
# ONE FUNCTION, TWO CALLERS, and that is the whole of PR #33 round 3's major.
# This logic lived inline at step 5, which only runs when a ROUND is dispatched.
# The gate above `continue`s on an approved, clean, non-drifted PR -- a PR with
# nothing left to do but merge, which is precisely the population this issue is
# named for -- four hundred lines before step 5 exists. So the done PRs were the
# ones nothing ever armed, and converge.sh Slacked "no human merge needed" over
# that state off a comment claiming otherwise. A second copy at the gate would
# have been two arms with drifting semantics; this is one.
#
# BEFORE the review at step 5, never after. `--auto` is not "merge now": GitHub
# holds the PR until every REQUIRED context is green, and `kipi/reviewer-approved`
# is ABSENT until the reviewer posts it (ASK-217). Arming afterwards would need
# something to come back once the review lands -- the same gap wearing a coat.
#
# BLAST RADIUS -- READ THIS BEFORE TOUCHING BRANCH PROTECTION. With this function
# in place, code reaches main with no human in the path, on a repo that fans out
# fleet-wide through `kipi update`. The only thing between a diff and main is the
# set of REQUIRED contexts on the branch. Remove `kipi/reviewer-approved` from
# that set and this becomes an unreviewed-merge machine. It was made required
# FIRST, and watched refusing on ABSENT and on FAILURE (PRs #27, #30), before
# this was allowed to exist. This worker still never merges anything: GitHub
# merges, and only once the required checks pass.
#
# THE PROBE'S rc IS PART OF ITS ANSWER (PR #33 review round 1, finding 3). `gh pr
# view` says true/false when it answers at all and an EMPTY STRING when it could
# not -- a rate limit, a dropped connection, an unattended schedule against a
# live API. Reading that empty string as "not armed" is how an ARMED PR earns a
# warning saying it will sit green forever plus a command already run. Three
# states are kept apart, never two: armed / unarmed / could not tell.
AUTOMERGE=""
arm_automerge() {
  local pr="$1" dir="$2" probe
  AUTOMERGE="unknown"
  # `gh pr merge --auto --squash ''` acts on whatever branch the cwd is on, so an
  # empty number is not "arm nothing", it is "arm something else".
  [ -n "$pr" ] || { AUTOMERGE=""; return 0; }
  # ASKED FOR, not armed-and-forgiven. This runs on the same PR every rework
  # round AND on every scheduled run for as long as the PR sits approved, so a
  # warning per pass would train the operator to skim the one that matters -- and
  # which exit code `gh pr merge` returns for an already-armed PR varies by
  # version. Asking makes the no-op a real no-op.
  if ! probe="$( cd "$dir" && gh pr view "$pr" --json autoMergeRequest \
                   -q '.autoMergeRequest != null' 2>>"$LOG" )"; then
    probe="unknown"
  fi
  if [ "$probe" = "true" ]; then
    AUTOMERGE="armed"
  elif ( cd "$dir" && gh pr merge --auto --squash "$pr" ) >/dev/null 2>&1; then
    AUTOMERGE="armed"
    say "$ISSUE: auto-merge armed on PR #$pr (GitHub merges it once every required check is green)"
  else
    # ASK THE STATE AGAIN BEFORE CRYING WOLF. `gh pr merge --auto` refuses for
    # reasons that are not "unarmed", and an already-armed PR is one of them.
    # The refusal alone cannot tell an armed PR from a broken one, so the PR is
    # asked what it IS. Only ever runs on this path.
    if ! probe="$( cd "$dir" && gh pr view "$pr" --json autoMergeRequest \
                     -q '.autoMergeRequest != null' 2>>"$LOG" )"; then
      probe="unknown"
    fi
    if [ "$probe" = "true" ]; then
      # It was already armed and the refusal WAS the no-op. Silent on purpose:
      # this is the healthy state, reached through a blip.
      AUTOMERGE="armed"
    elif [ "$probe" = "unknown" ]; then
      AUTOMERGE="unknown"
      # STILL AUDIBLE, but claiming only what can be backed. gh refused the arm
      # AND refused the state, so "it will sit green and unmerged" is a sentence
      # nothing here knows to be true -- and this may equally be a PR that is
      # fine. It pages anyway: this is the branch where the PR may really be
      # unarmed, and quieting it would re-create the stall one layer down.
      say "WARN: could not arm auto-merge on PR #$pr for $ISSUE and could not read its state either -- gh answered neither. If it sits green: gh pr merge --auto --squash $pr"
      if page_once "$ISSUE" automerge_unknown_paged; then
        bash "$NOTIFY" "worker: $ISSUE PR #$pr -- gh could neither arm auto-merge nor read its state, so whether this PR merges itself is unknown. Needs a human to check: gh pr merge --auto --squash $pr" 2>/dev/null || true
      fi
    else
      AUTOMERGE="unarmed"
      # LOUD MEANS $NOTIFY, NOT $LOG (PR #33 review round 1, finding 1 -- major).
      # This was `say` alone, and `say` is `tee -a "$LOG"`: under the launchd
      # heartbeat that is a file nobody opens at 3am. This worker's channel for
      # "a human must do something" is `bash "$NOTIFY"`, used at five other sites
      # in this file, and this state is exactly that -- the message ends in the
      # command a human has to run. An unarmed PR is invisible by construction
      # (everything green, nothing merges, no signal), so a log-only warning does
      # not kill the silent stall, it relocates it.
      say "WARN: could not arm auto-merge on PR #$pr for $ISSUE -- it will sit green and unmerged until someone runs: gh pr merge --auto --squash $pr"
      if page_once "$ISSUE" automerge_unarmed_paged; then
        bash "$NOTIFY" "worker: $ISSUE PR #$pr is NOT armed -- it goes green and sits there forever. Needs a human: gh pr merge --auto --squash $pr" 2>/dev/null || true
      fi
    fi
  fi
  # ONCE PER ISSUE, NOT PER RUN -- and the comment that used to sit here claimed
  # the opposite while calling the approved-but-blocked pages above its precedent
  # (PR #33 review round 3, finding 3). All three of those go through
  # claim_page_once. So does this now, because the alternative is worse than an
  # inaccurate comment: the gate caller below re-reaches this state on EVERY
  # scheduled run for as long as the PR sits there, so per-run paging is a page
  # every cycle, forever, for one fact that has not changed.
  #
  # NOT fatal on any path: the PR still stands, the review still runs, the exit
  # code is unchanged. The `( ... ) >/dev/null 2>&1` around the arm inside an
  # `if` is what keeps a refusal out of `$?`.
  [ "$AUTOMERGE" = "armed" ] && clear_automerge_pages "$ISSUE"
  # PUBLISHED, so the second reporter reads instead of asserts. converge.sh has
  # to tell the operator who merges this PR and cannot re-probe without becoming
  # a second reader of one input; asserting instead is what put "no human merge
  # needed" on PRs nothing had armed.
  record_automerge "$REVIEWS_DIR/$(artifact_key "$TARGET_SLUG" "$pr").automerge" "$AUTOMERGE"
  return 0
}

# --- worktree positioning (ASK-212, PR #25 review finding 1) -----------------
# tree_holds_pr_head <tree> <branch>: true when everything on origin/<branch> is
# already reachable from the tree's HEAD -- i.e. a push from this tree destroys
# nothing. Compared against origin/<branch> rather than the API's headRefOid on
# purpose: origin/<branch> is exactly what a force-push overwrites, and reading
# it costs no network call that could fail open.
tree_holds_pr_head() {
  # A remote branch that does not exist has nothing to lose, so the invariant
  # ("hold everything origin/<branch> has") is vacuously satisfied. Same
  # reasoning as the start-point fallback below; without this the check would
  # refuse every round on a PR whose head branch was already pruned.
  git -C "$1" rev-parse --verify -q "origin/$2" >/dev/null 2>&1 || return 0
  git -C "$1" merge-base --is-ancestor "origin/$2" HEAD 2>/dev/null
}

# position_tree_on_pr_head <tree> <branch>: move a tree onto the PR's head
# without discarding anything that exists only there. Refuses (1) on a dirty
# working tree, or on any commit not reachable from origin/<branch> or
# origin/main -- the two places work can legitimately live. An unattended job
# does not get to throw away commits nobody has seen; when it cannot prove the
# move is lossless it declines the round and leaves the tree for a human.
# Sets POSITION_REFUSAL to the REASON when it declines, because "cannot be moved
# safely" covers four different states and the operator reading this at 3am has
# to know which one they are looking at.
POSITION_REFUSAL=""
position_tree_on_pr_head() {
  local tree="$1" branch="$2" dirty extra
  POSITION_REFUSAL=""
  # `.linear-claims.json` is EXCLUDED: the claim taken two lines above this call
  # writes that file into the very tree being judged, so counting it as local
  # work made every inherited tree unrepositionable -- turning a destructive
  # round into a permanently stalled issue plus a page. It is this worker's own
  # lock, never a human's work.
  # .sana-needs-scope joins the ignore list for the same reason .linear-claims.json
  # is on it: both are the loop talking to itself, never a human's work. It is
  # normally consumed in the same run that writes it, but a run killed between the
  # write and the read would otherwise leave a file that makes this tree
  # permanently unrepositionable -- a refusal that wedges the issue it refused.
  dirty="$(git -C "$tree" status --porcelain 2>/dev/null | grep -v -e '\.linear-claims\.json$' -e '\.sana-needs-scope$')"
  if [ -n "$dirty" ]; then
    POSITION_REFUSAL="the tree has uncommitted changes"
    return 1
  fi
  extra="$(git -C "$tree" rev-list HEAD --not "origin/$branch" origin/main 2>/dev/null)"
  if [ -n "$extra" ]; then
    POSITION_REFUSAL="the tree holds $(printf '%s\n' "$extra" | grep -c .) commit(s) that exist nowhere else"
    return 1
  fi
  if ! git -C "$tree" checkout -q -B "$branch" "origin/$branch" 2>>"$LOG"; then
    POSITION_REFUSAL="git could not check out origin/$branch (see $LOG)"
    return 1
  fi
  if ! tree_holds_pr_head "$tree" "$branch"; then
    POSITION_REFUSAL="the tree still does not contain origin/$branch after the checkout"
    return 1
  fi
}

DONE=0
printf '%s' "$PICKED" | python3 -c 'import json,sys;[print(i["id"]) for i in json.load(sys.stdin)["ready"]]' | \
while IFS= read -r ISSUE; do
  [ "$DONE" -ge "$LIMIT" ] && break

  N="$(attempts_for "$ISSUE")"
  if [ "$N" -ge "$MAX_ATTEMPTS" ]; then
    # NOTHING IS TERMINAL WITHOUT A NAMED HUMAN ACTION (sp-58f0ec83).
    #
    # This branch said "a human decides next" to a LOG FILE and continued, every
    # heartbeat, forever. No Linear comment, no page, no statement of what the
    # human was supposed to decide. So "stuck" was indistinguishable from
    # "nobody has looked yet", and an issue could sit there indefinitely while
    # the log repeated a sentence nobody reads.
    #
    # Every other gate in this repo distinguishes REFUSED from PASSED. This one
    # did not, which is the same defect that let a correct BLOCKED diagnosis on
    # ASK-149 read as success (the agent had done the right thing and the worker
    # could not tell). The fix is not "add a BLOCKED state" -- it is that a
    # terminal state must carry the ONE action that ends it. If the loop cannot
    # name that action, it has not finished diagnosing and must say SO rather
    # than parking the issue quietly.
    #
    # Paged ONCE via the shared claim_page_once flag, not per heartbeat: a
    # repeated "still stuck" every 15 minutes is the cry-wolf failure that trains
    # the reader to mute the channel (founder-notifications.md).
    STUCK_WHY="$(python3 "$LEDGER" "$ATTEMPTS" get "$ISSUE" why "" 2>/dev/null)"
    if [ -z "$STUCK_WHY" ]; then
      # The honest degraded case. An unexplained cap is itself the finding: the
      # loop burned its whole budget and cannot say what a human should do.
      STUCK_WHY="the worker recorded no reason, which means it never diagnosed why this fails"
    fi
    say "skip $ISSUE: $N/$MAX_ATTEMPTS attempts. TERMINAL. Last reason: $STUCK_WHY"
    if page_once "$ISSUE" stuck_paged; then
      python3 "$SYNC" progress "$ISSUE" \
        "**Stuck after $N/$MAX_ATTEMPTS attempts. The autonomous loop has stopped picking this up.**

Last recorded reason: $STUCK_WHY

**Human action needed:** review the reason above and do ONE of:
- fix the blocker, then clear the attempt count so the loop retries, or
- rewrite the Definition of Ready so it is achievable from a non-interactive session, or
- close the issue if it should not be built.

A DoR that cannot be met from the environment the worker actually runs in is a defective spec, not a founder decision. Rewriting it is engineering work." \
        --agent sana >/dev/null 2>&1 || true
      # `bash "$NOTIFY"`, the shape used at five other sites in this file. There is
      # no page() helper here -- calling one would have been a silent no-op under
      # `set -uo pipefail` (command-not-found, no -e), i.e. a terminal state that
      # pages nobody, which is the exact defect this block fixes.
      bash "$NOTIFY" "kipi worker: $ISSUE is STUCK after $N attempts and the loop has stopped picking it up. Reason: $STUCK_WHY. Do: read the comment on $ISSUE -- it names the three options." 2>/dev/null || true
    fi
    continue
  fi

  if [ "$APPLY" = "0" ]; then
    say "[dry] would work $ISSUE (attempt $((N+1))/$MAX_ATTEMPTS)"
    DONE=$((DONE+1)); continue
  fi

  BRANCH="sana/$(echo "$ISSUE" | tr 'A-Z' 'a-z')"

  # SEVERITY FLOOR GATE (deterministic, before any side effect). Only REQUEST
  # CHANGES or BLOCK starts another rework round: an approved PR waits on the
  # founder, and an unreviewed PR has no spec to rework against. The gate runs
  # BEFORE the claim and the Linear progress note on purpose -- a "Picked up"
  # note on a permanent Linear object followed by an immediate skip is a false
  # alarm, and false alarms train the reader to ignore the real notes.
  # shellcheck disable=SC2086  # unquoted on purpose: empty must expand to nothing
  EXISTING_PR="$(gh pr list $KIPI_GH_REPO_ARGS --head "$BRANCH" --json number -q '.[0].number' 2>/dev/null)"
  REWORK=""
  CONFLICT_ROUND=""
  DRIFT_ROUND=""
  if [ -n "$EXISTING_PR" ]; then
    PR_VERDICT="$(verdict_from_record "$(verdict_record_path "$REVIEWS_DIR" "$TARGET_SLUG" "$EXISTING_PR")")"
    if [ -z "$PR_VERDICT" ]; then
      # Fallback for PRs reviewed before the verdict record existed: extract
      # from the newest review .md with the SAME extractor the reviewer uses.
      LATEST_REVIEW="$(ls -t "$REVIEWS_DIR/$(artifact_key "$TARGET_SLUG" "$EXISTING_PR")-"*.md "$REVIEWS_DIR/pr-$EXISTING_PR-"*.md 2>/dev/null | head -1)"
      [ -n "$LATEST_REVIEW" ] && PR_VERDICT="$(extract_verdict "$LATEST_REVIEW")"
    fi
    # MERGEABILITY IS HALF THE GATE (ASK-212). Read once, through the shared lib,
    # so the worker and the driver cannot drift on what "still merges" means.
    MERGE_STATE="$(pr_merge_state "$EXISTING_PR")"
    # The streak ends the moment the PR merges cleanly again -- see
    # clear_conflict_rounds. Placed before the gate so it runs on every verdict,
    # not just the approving ones: a rework round that also resolves the
    # conflict ended the streak just as much.
    [ "$MERGE_STATE" = "CLEAN" ] && clear_conflict_rounds "$ISSUE"
    # THE VERDICT IS BOUND TO A SHA, NOT A PR NUMBER (ASK-216, armed here by
    # ASK-219, sp-a27722e7). This worker reuses ONE branch and ONE PR across every
    # rework round, so before this call passed a sha, each push landing after an
    # approval inherited that approval silently. The reviewed sha is the one the
    # reviewer pinned into the record; the current head goes through the same
    # shared lib as the merge state so the worker and converge.sh cannot drift on
    # what "the current head" means.
    #
    # APPENDED, NEVER INSERTED: $MERGE_STATE keeps argument 2. Reordering it would
    # silently stop ASK-212's rebase rounds from ever firing again.
    REVIEWED_SHA="$(head_sha_from_record "$(verdict_record_path "$REVIEWS_DIR" "$TARGET_SLUG" "$EXISTING_PR")")"
    CURRENT_SHA="$(pr_head_sha "$EXISTING_PR")"
    GATE_NOTE="$(rework_gate "$PR_VERDICT" "$MERGE_STATE" "$REVIEWED_SHA" "$CURRENT_SHA")"; GATE=$?
    [ -n "$GATE_NOTE" ] && say "$GATE_NOTE"
    # THE DRIFT STREAK ENDS ON A STATED NON-DRIFT, and nothing less. Two halves,
    # both of them scars:
    #
    # It sits ABOVE the branches because gates 10 and 20 both `continue`, so a
    # clear placed with the gate-40 block would never run on the one path that
    # matters most -- the review came back, repinned the record, the PR is
    # healthy again. (Observed RED as P5: drift_rounds stayed at 2 through a
    # full heal.)
    #
    # And it requires BOTH shas to have been read, because "the gate did not say
    # 40" is not the same statement as "there is no drift". `pr_head_sha` returns
    # empty on any `gh` failure and the gate then falls toward terminal and
    # returns 10 -- so the bare `!= 40` form treated a head NOBODY COULD READ as
    # proof the drift was over: it reset the streak AND popped `drift_paged`, and
    # one hiccup every other run was enough to make the cap unreachable and the
    # page never fire. clear_conflict_rounds 190 lines up refuses the identical
    # move for the identical reason -- "refilling a budget from a state nobody
    # actually read is how an unresolvable conflict gets infinite rounds"
    # (PR #30 review round 3, major 1; observed RED as P8: 9 runs, 6 rounds, 0
    # pages).
    #
    # This is a readability check on the gate's INPUTS, not a second sha
    # comparison: 40 is still the one reader's own answer to "is this drift?".
    # What it costs, stated: a blind run no longer refills the budget, so a drift
    # that quietly resolved during a blind window can reach the cap one round
    # early. That direction pages ("unreviewed code sits at the head, needs a
    # human") on a run where the gate really did say 40, so the page is true when
    # it fires -- louder, never quieter, which is the only safe way to be wrong
    # about a budget guarding unreviewed code.
    if [ "$GATE" != "40" ] && [ -n "$REVIEWED_SHA" ] && [ -n "$CURRENT_SHA" ]; then
      clear_drift_rounds "$ISSUE"
    fi
    if [ "$GATE" = "10" ]; then
      # ARM BEFORE THE SKIP (PR #33 review round 3, finding 1 -- major). This
      # branch is the population the issue is named for: approved, clean, pinned
      # to its own head, nothing left to do but merge. And it `continue`d four
      # hundred lines ABOVE the arm at step 5, so it was the one population
      # nothing armed -- while converge.sh paged "auto-merge lands it, no human
      # merge needed" across exactly this state. Arming here does not turn a done
      # PR into a round: no agent, no reviewer, no Linear comment. The skip stays
      # a skip; only the arm is new.
      arm_automerge "$EXISTING_PR" "$TARGET_REPO"
      # AND THE LINE SAYS WHO MERGES IT (round 3, finding 2 -- minor). Round 2
      # fixed this sentence at the closing line and at converge's and left this
      # third site saying "waiting on founder merge". For a PR armed a round ago,
      # nobody is waiting. Three outcomes, three sentences: a hedge covering all
      # of them would make the healthy case -- which is most of them -- unreadable.
      case "$AUTOMERGE" in
        armed)
          say "skip $ISSUE: PR #$EXISTING_PR verdict is '$PR_VERDICT' -- nothing to rework; auto-merge is armed, GitHub merges it once every required check is green" ;;
        unarmed)
          say "skip $ISSUE: PR #$EXISTING_PR verdict is '$PR_VERDICT' -- nothing to rework, but it is NOT armed and will sit green: gh pr merge --auto --squash $EXISTING_PR" ;;
        *)
          say "skip $ISSUE: PR #$EXISTING_PR verdict is '$PR_VERDICT' -- nothing to rework; gh could not read its auto-merge state this run, so check it landed: gh pr merge --auto --squash $EXISTING_PR" ;;
      esac
      continue
    fi
    if [ "$GATE" = "20" ]; then
      say "skip $ISSUE: PR #$EXISTING_PR has no recorded review verdict -- run: kipi review $EXISTING_PR --issue $ISSUE --post"
      continue
    fi
    if [ "$GATE" = "40" ]; then
      # STALE. The record approves a commit that is no longer the head, so nobody
      # has read the code that is actually there. Dispatch a RE-REVIEW round on
      # its OWN budget: the round ends in a review (step 5 below), and THAT review
      # writes a record pinned to the current head, which is the only thing that
      # clears this. When the reviewer is the thing that is down, nothing clears
      # it -- so the budget below is what stops a dead reviewer at 3am from
      # becoming an unbounded loop of model rounds and undeletable Linear
      # comments with nobody told (PR #30 review round 2, major 2).
      #
      # CONFLICT_ROUND stays empty on purpose even when the PR is also DIRTY. A
      # drift round is a review round, not a rebase round; spending the rebase
      # budget on it would leave a real conflict un-dispatchable later, and the
      # rebase prompt would tell the agent to force-push a diff nobody reviewed.
      DR="$(drift_rounds_for "$ISSUE")"
      if [ "$DR" -ge "$MAX_DRIFT_ROUNDS" ]; then
        say "skip $ISSUE: PR #$EXISTING_PR is '$PR_VERDICT' recorded at $REVIEWED_SHA but the head is $CURRENT_SHA, still never reviewed after $DR/$MAX_DRIFT_ROUNDS drift round(s) -- a human resolves this one."
        if page_once "$ISSUE" drift_paged; then
          bash "$NOTIFY" "worker: $ISSUE PR #$EXISTING_PR is approved at $REVIEWED_SHA but its head $CURRENT_SHA is still unreviewed after $MAX_DRIFT_ROUNDS re-review round(s) - unreviewed code sits at the head, needs a human" 2>/dev/null || true
        fi
        continue
      fi
      # PLANNED, NOT SPENT (same discipline as CONFLICT_ROUND below). Everything
      # between here and the dispatch can still decline the run -- another
      # session's claim, a worktree that cannot be created, a tree that cannot be
      # positioned. Spending the budget here would let two runs skipped by a stale
      # claim burn it having re-reviewed nothing, then page a round count that
      # never happened.
      DRIFT_ROUND=$((DR + 1))
      say "$ISSUE: PR #$EXISTING_PR reads '$PR_VERDICT', but that verdict was recorded at $REVIEWED_SHA and the head is now $CURRENT_SHA -- the code at the head was never reviewed. Dispatching a round so it gets re-reviewed."
    fi
    if [ "$GATE" = "30" ]; then
      # Approved on content, but it no longer merges. Dispatch a REBASE round on
      # its own budget -- and stop dead once that budget is spent, because an
      # unresolvable conflict would otherwise rework forever and write a
      # permanent Linear comment on every round.
      CR="$(conflict_rounds_for "$ISSUE")"
      if [ "$CR" -ge "$MAX_CONFLICT_ROUNDS" ]; then
        say "skip $ISSUE: PR #$EXISTING_PR is '$PR_VERDICT' but $MERGE_STATE after $CR/$MAX_CONFLICT_ROUNDS conflict round(s) -- a human resolves this one."
        if page_once "$ISSUE" conflict_paged; then
          bash "$NOTIFY" "worker: $ISSUE PR #$EXISTING_PR is approved but still $MERGE_STATE after $MAX_CONFLICT_ROUNDS rebase round(s) - needs a human" 2>/dev/null || true
        fi
        continue
      fi
      # THE ROUND IS NOT SPENT HERE, only planned (PR #25 review, finding 2).
      # Everything between this line and the dispatch can still decline the run:
      # another session's claim, a worktree that cannot be created, a tree that
      # cannot be positioned on the PR's head. Spending the budget up here meant
      # two runs skipped by a stale claim -- converge.sh's own documented
      # 2026-07-27 scar, a SIGKILL or a sleeping laptop leaving a lock nobody
      # reclaims -- burned the whole budget having dispatched ZERO rebases, then
      # paged the founder a round count that never happened and locked the issue
      # out until someone hand-edited the ledger. The bump and the log line both
      # live at the dispatch site below, where the round actually happens.
      CONFLICT_ROUND=$((CR + 1))
    fi
  fi

  # 1. WORKTREE FIRST, and only then the claim -- in that order, because the
  # claim has to be taken from INSIDE the tree it protects.
  #
  # Scar from this worker's own first live run (ASK-150, 2026-07-26): it branched
  # in place and left the founder's main checkout sitting on sana/ask-150. The
  # claim lock stopped a concurrent AGENT from colliding, but it cannot stop the
  # worker yanking the FOUNDER's working tree out from under them mid-edit --
  # commit 53f2eeb, the scar this whole line of work started from. A worktree
  # makes that collision impossible by construction instead of merely detected.
  TREE="$STATE_DIR/worktrees/$(echo "$ISSUE" | tr 'A-Z' 'a-z')"
  # WHERE A NEW TREE STARTS DEPENDS ON WHETHER A PR ALREADY EXISTS (PR #25
  # review, finding 1 -- major). `worktree add -B` RESETS the branch to the
  # start point. origin/main is correct for fresh work and destructive for a PR
  # that is already open: the agent gets a tree holding NONE of the PR's
  # commits, and the rebase prompt below then tells it to
  # `git push --force-with-lease`, which deletes the approved diff from the
  # remote branch. The lease does not catch it -- the fetch above just
  # refreshed origin/$BRANCH, so the lease sees no surprise and allows the
  # push. The PR's head is origin/$BRANCH; when there is a PR, that is the
  # only defensible start point.
  BASE="origin/main"
  if [ -n "$EXISTING_PR" ]; then
    if git -C "$TARGET_REPO" rev-parse --verify -q "origin/$BRANCH" >/dev/null 2>&1; then
      BASE="origin/$BRANCH"
    else
      # gh named a PR whose head branch is not on the remote (deleted after a
      # merge, pruned by hand). Cutting from main is safe HERE and only here:
      # there is no remote branch left for a force-push to destroy. Said out
      # loud rather than fallen through silently, because an unexplained
      # origin/main is the exact behaviour this block exists to stop -- and
      # refusing instead would stall the issue every cycle with one INFRA line
      # nobody reads.
      say "$ISSUE: PR #$EXISTING_PR is recorded but origin/$BRANCH does not exist; cutting from origin/main (nothing on the remote to overwrite)"
    fi
  fi
  if [ ! -d "$TREE" ]; then
    mkdir -p "$(dirname "$TREE")"
    if ! git -C "$TARGET_REPO" worktree add -q -B "$BRANCH" "$TREE" "$BASE" 2>>"$LOG"; then
      # A concurrent worker on the SAME issue can create this tree between the
      # test above and this line. That is the collision the claim below exists to
      # adjudicate, not an infra failure -- so fall through and let it, rather
      # than reporting a phantom outage and burning nothing.
      if [ ! -d "$TREE" ]; then
        say "INFRA: could not create worktree for $ISSUE (not counted against the issue)"
        continue
      fi
    fi
  fi

  # 2. CLAIM, from INSIDE $TREE. exit 3 = another session holds THIS tree; that
  # is a skip, not an error.
  #
  # ASK-188: the claim used to run here at step 1, BEFORE the worktree existed,
  # so its cwd was the skeleton. `linear-claim.py::claims_path()` resolves the
  # lock from `git rev-parse --show-toplevel` OF THE CALLER'S CWD, which meant
  # every issue on the board contended for one file at the skeleton root -- one
  # lock, whole repo, total serialization. Measured 2026-07-27: 50+ ready issues
  # behind a queue that could only ever run one. Inside a worktree that same
  # command returns THAT worktree's path, so the lock lands in the tree it
  # actually protects, which is what the function's own docstring says it is for.
  # Two workers on the SAME issue still share one worktree and still collide, so
  # the mutex is unweakened -- that is case 4 of test-linear-worker-parallel.sh.
  #
  # `rc=$?` cannot live under `if ! cmd`: bash sets $? from the NEGATION there, so
  # it read 0 on every failure and the collision branch was unreachable -- a real
  # collision reported as "INFRA: claim failed rc=0". Capture the status directly.
  #
  # --holder-pid IS THIS SCRIPT'S OWN PID (ASK-189). The claiming python3 exits
  # within milliseconds, so its pid means nothing -- but THIS shell lives for the
  # entire run, and until now that fact was simply never written down. With it
  # recorded, a claim left behind by a killed run is reclaimable on read instead
  # of wedging the tree until a human runs `release --holder`. Measured twice
  # 2026-07-27; the kills were SIGKILL, which converge.sh's TERM/INT/HUP trap
  # cannot ever catch.
  #
  # `$$` and not `$BASHPID`: this line runs inside a subshell inside the pipeline
  # subshell of the `while` loop, and `$$` stays the SCRIPT's pid through both
  # (verified). `$BASHPID` would be the innermost subshell, dead on the next line
  # -- and it does not exist at all in the bash 3.2 macOS ships.
  #
  # RESIDUAL, stated rather than papered over: if this shell alone is killed and
  # its backgrounded `claude` child is orphaned, the holder reads dead while work
  # continues. That needs a targeted kill of this pid only; a timeout, a killed
  # process group, a slept laptop or a reboot -- every case actually observed --
  # takes the whole tree down together.
  #
  # STDERR IS KEPT. With `>/dev/null 2>&1` a tree CHANGING HANDS left this log
  # showing a normal `start ASK-xxx` and nothing else, so the one line an
  # operator has while debugging a two-workers-one-tree collision was the one
  # line thrown away -- the fix landing on the detector and not on the report
  # (PR #31 review, finding 2). Only the RECLAIMED line is echoed: an ordinary
  # refusal already gets its own `skip ... claimed by another session` below, and
  # repeating that here would trade a missing signal for a duplicated one.
  CLAIM_ERR="$(mktemp)"
  ( cd "$TREE" && python3 "$CLAIM" claim "$ISSUE" --agent "$AGENT" --session "$SESSION" \
      --holder-pid "$$" ) >/dev/null 2>"$CLAIM_ERR"
  rc=$?
  while IFS= read -r claim_line; do
    case "$claim_line" in RECLAIMED:*) say "$claim_line" ;; esac
  done < "$CLAIM_ERR"
  rm -f "$CLAIM_ERR"
  if [ "$rc" != "0" ]; then
    if [ "$rc" = "3" ]; then say "skip $ISSUE: working tree is claimed by another session"; continue; fi
    say "INFRA: claim failed rc=$rc on $ISSUE (not counted against the issue)"; continue
  fi
  # 3. THE TREE MUST STAND ON THE PR'S HEAD before a round that will push over
  # it. A tree left by an earlier round, or cut by the version of this script
  # that always used origin/main, can be missing every commit the PR is made of
  # -- and the round would then force-push that emptiness over the approved
  # diff. Repositioning happens HERE, after the claim, because it mutates the
  # tree and the claim is what says this session owns it.
  if [ -n "$EXISTING_PR" ] && ! tree_holds_pr_head "$TREE" "$BRANCH"; then
    if ! position_tree_on_pr_head "$TREE" "$BRANCH"; then
      say "skip $ISSUE: $TREE is missing PR #$EXISTING_PR's commits and cannot be moved onto them -- $POSITION_REFUSAL. Refusing a round that would force-push over the PR. A human resolves this one: $TREE"
      if page_once "$ISSUE" tree_paged; then
        bash "$NOTIFY" "worker: $ISSUE worktree does not hold PR #$EXISTING_PR's commits and has local work - $TREE needs a human" 2>/dev/null || true
      fi
      # Release before skipping: a claim held by a run that did nothing wedges
      # this issue for every later run, which is the failure this refusal exists
      # to avoid, one layer out.
      ( cd "$TREE" && python3 "$CLAIM" release "$ISSUE" --agent "$AGENT" --session "$SESSION" ) >/dev/null 2>&1 || true
      continue
    fi
  fi

  # 4. SPEND THE CONFLICT ROUND, at the dispatch and nowhere earlier. Every
  # decline above this line left the budget intact (PR #25 review, finding 2),
  # so the counter and the log line below both describe rounds that really ran.
  if [ -n "$CONFLICT_ROUND" ]; then
    bump_conflict_round "$ISSUE"
    say "$ISSUE: PR #$EXISTING_PR is '$PR_VERDICT' but $MERGE_STATE -- dispatching rebase round $CONFLICT_ROUND/$MAX_CONFLICT_ROUNDS"
  fi
  if [ -n "$DRIFT_ROUND" ]; then
    bump_drift_round "$ISSUE"
    say "$ISSUE: PR #$EXISTING_PR is '$PR_VERDICT' at $REVIEWED_SHA but the head is $CURRENT_SHA -- dispatching re-review round $DRIFT_ROUND/$MAX_DRIFT_ROUNDS"
  fi
  say "start $ISSUE on $BRANCH in $TREE (attempt $((N+1))/$MAX_ATTEMPTS)"
  python3 "$SYNC" progress "$ISSUE" \
    "Picked up by the autonomous worker. Branch \`$BRANCH\`. Attempt $((N+1)) of $MAX_ATTEMPTS." \
    --agent "$AGENT" >/dev/null 2>&1 || true

  # REWORK: if a PR already exists for this branch, the worker is not starting
  # fresh -- it is answering a review. Without this the prompt would say "do the
  # DoR" to an agent whose work is already written and already criticised, and it
  # would plausibly start over. The review is the spec for this pass.
  # EXISTING_PR was discovered above, before the claim; reaching this line means
  # the severity-floor gate already ruled the verdict REQUEST CHANGES or BLOCK,
  # or ruled it approved-but-unmergeable (gate 30, the conflict branch below).
  #
  # A CONFLICT ROUND IS NOT A REVIEW ROUND, so it does not get the review prompt.
  # The review APPROVED this diff -- handing the agent "the review is the spec,
  # answer every finding" against a review with no findings is how ASK-208's
  # rounds 1 and 2 both did code polish while the conflict went untouched. The
  # spec for this pass is the conflict and nothing else.
  if [ -n "$CONFLICT_ROUND" ]; then
    REWORK="

## THIS IS A REBASE ROUND. THE CONFLICT IS THE ONLY TASK.

PR #$EXISTING_PR on this branch was already REVIEWED AND APPROVED ('$PR_VERDICT').
GitHub now reports its merge state as $MERGE_STATE: main moved underneath it and
it no longer merges. This is round $CONFLICT_ROUND of $MAX_CONFLICT_ROUNDS; at the cap the
worker stops and pages a human, so do not spend this round on anything else.

Do exactly this:

  git fetch origin
  git rebase origin/main        # or merge origin/main, whichever this repo prefers
  # resolve the conflicts, keeping BOTH intents: yours and whatever landed on main
  bash <the tests this PR already ships>   # they must still pass after the rebase
  git push --force-with-lease origin $BRANCH

DO NOT redesign, refactor, polish, or 'improve' the approved diff. DO NOT re-open
the design. Any change beyond what resolving the conflict requires costs the PR
its approval and starts the review over.

If the conflict cannot be resolved without a real decision (the two sides changed
the same behaviour on purpose), say so on the issue via progress and STOP:
  bash $SKEL/kipi linear progress $ISSUE \"<the conflict and the decision it needs>\" --agent sana

Push to the SAME branch $BRANCH. Do not open a second PR."
  elif [ -n "$DRIFT_ROUND" ]; then
    # A DRIFT ROUND IS NOT A REVIEW ROUND EITHER, and for the same reason the
    # rebase round is not: the stored review APPROVED, so it carries no findings
    # to answer. Handing it the rework prompt below said "the review is the spec,
    # for EACH finding either fix it or reply why it is not a defect" against a
    # review with no findings -- ASK-208's failure shape exactly, and the most
    # common producer of this drift is a HUMAN (a founder push, GitHub's "Update
    # branch" button), so that prompt sent an agent to invent work on top of
    # someone else's commit and push it to the same branch (PR #30 review, major
    # 1).
    #
    # What actually clears the drift is step 5's review, not this round's edits.
    # So the honest instruction is: read the unreviewed commits, change NOTHING
    # unless they are broken, and let the review run. Doing nothing is a correct
    # outcome here and is stated as one -- otherwise an agent handed a round with
    # no task will manufacture one.
    REWORK="

## THIS IS A RE-REVIEW ROUND. THE CODE AT THE HEAD HAS NEVER BEEN REVIEWED.

PR #$EXISTING_PR on this branch carries a stored verdict of '$PR_VERDICT', but that
verdict was recorded against commit $REVIEWED_SHA. The head of the branch is now
$CURRENT_SHA. Whatever landed in between has never been read by any reviewer.

This is round $DRIFT_ROUND of $MAX_DRIFT_ROUNDS; at the cap the worker stops and pages a human.

THERE ARE NO FINDINGS TO ANSWER. The stored review approved. Do not read it as a
spec, do not re-open the design, and do not restart the task.

The re-review at the end of this round is what clears the drift, not your edits.
So:

  git log --oneline $REVIEWED_SHA..$CURRENT_SHA     # what nobody has reviewed
  git diff $REVIEWED_SHA..$CURRENT_SHA

  1. If those commits are coherent and complete, CHANGE NOTHING. Say so via
     progress and stop. That is a correct and expected outcome for this round --
     the review runs next either way. Inventing work here is the failure mode.
  2. Only if they are actually broken -- a partial push, a botched merge, a WIP
     commit, tests that no longer pass -- fix exactly that, and nothing else.
     Run this PR's tests before you push.

Someone else may have pushed those commits (a founder push, GitHub's 'Update
branch'). Treat them as work you did not write and must not silently rewrite.

Push to the SAME branch $BRANCH. Do not open a second PR."
  elif [ -n "$EXISTING_PR" ]; then
    REWORK="

## THIS IS A REWORK, NOT A FRESH START

PR #$EXISTING_PR already exists for this branch and has been reviewed by CODEX
(gpt-5.6-sol) acting as a senior staff engineer at Meta. It is a DIFFERENT LAB'S
MODEL, not another instance of you -- so when it reports something you are sure is
fine, the default assumption is that it saw something you structurally cannot,
because you and the code share one mental model and it does not.

Read the review before touching anything. It is in two places:

  gh pr view $EXISTING_PR --comments
  python3 q-system/.q-system/scripts/linear-sync.py comments $ISSUE

THE REVIEW IS THE SPEC FOR THIS PASS. Do not restart the task and do not
re-litigate the design. For EACH finding, either:
  - fix it, and add a test that FAILS without the fix (observed red, then green), or
  - answer it with the file:line that already handles it.

## REPLY ON THE LINEAR ISSUE, NOT ONLY THE PR

The review conversation lives on $ISSUE, because that is the one surface both you
and the reviewer read (and the founder reads it too). When you have worked the
findings, post ONE reply there:

  python3 q-system/.q-system/scripts/linear-sync.py progress $ISSUE \\
    "<one line per finding: fixed + the test that now covers it, or answered + the file:line>" \\
    --agent sana --evidence "<the command you ran and its real output>"

One reply per rework pass, not one per finding: the issue is permanent and a
comment per finding turns one review into ten objects nobody can read.

Findings you disagree with are answered, never silently ignored -- a finding that
gets no response reads as a finding nobody read. "I ran X and got Y" is an answer;
"should be fine" is not.

The reviewer's own bar applies to your fixes too: a fix with no test that could
have caught the bug is not a fix, it is a patch. Re-read what the reviewer said it
tried and could NOT break, and do not regress those.

## CHECK THE LAYER ABOVE YOUR FIX

Observed on BOTH review rounds of this PR, so treat it as the likely failure mode
rather than a hypothetical:

  round 1: the detector had no update path      -> you added one
  round 2: the update path rewrites a CLOSED issue and never reopens it,
           so the detector goes permanently dark after the operator does the
           right thing -- WORSE than before the fix
  round 2 also: 'the fix landed on the detector and not on the report'

A local fix that is correct in isolation can create a worse failure one layer out.
Before you call a finding fixed, walk the value you changed to its CONSUMERS and
ask what each now does with it:

- who READS the thing I just started writing? what if it is in a state I did not
  consider (closed, empty, stale, concurrent)?
- does the REPORT (Slack line, counts, dry-run output) still tell the truth after
  this change, or does it now claim something that is not happening?
- is there a SECOND code path doing the same job that I did not touch? Two readers
  of the same input with different semantics is a defect even when each is
  individually defensible.
- what does the operator SEE when this fires at 3am, and is that signal or noise?

If a fix makes any downstream thing quieter, say so explicitly on the PR and
justify it. Silence bought by a fix is the most expensive kind.

Push to the SAME branch $BRANCH. Do not open a second PR."
  fi

  PROMPT="You are Sana, the kipi Systems Engineer, working Linear issue $ISSUE.$REWORK

You are in a DEDICATED GIT WORKTREE at $TREE, already on branch $BRANCH off origin/main.
Work here. Never `cd` to $TARGET_REPO and never switch this branch -- the founder may be using that checkout.

1. Read the issue: \`python3 $SYNC progress $ISSUE\` is for REPORTING; to read it use the Linear MCP or
   \`gh\`-style inspection. The issue carries a Definition of Ready: Outcome, Files, Check, Blast radius, Not doing.
2. Work ONLY what the DoR scopes. The 'Not doing' line is binding.
3. Follow this repo's discipline: reproducer first and observed RED before green, then the real command output.
4. Commit on branch $BRANCH with the issue id $ISSUE in the message (the commit-msg gate requires it).
5. Post progress with: bash $SKEL/kipi linear progress $ISSUE \"<what happened>\" --agent sana --evidence \"<command and its real output>\"
6. Open a PR. DO NOT MERGE. DO NOT close the issue - closeout runs through /issue-verify and /issue-closeout.
   OPEN IT BEFORE YOUR TURN ENDS. Never finish on \"I'll open the PR once X finishes\" -- your turn
   ends there and the PR never exists, so the review never runs and the work is stranded (observed
   on ASK-184). If a check is still running, open the PR FIRST and post the result as a comment.
7. If you cannot finish, REFUSE IN A FILE, not only in prose. TWO different files, and
   picking the right one decides who acts next, so do not guess:

   a) THE SPEC IS WRONG (unbounded, contradictory, names files that do not exist,
      no achievable outcome). The environment is fine; the issue is not workable as written:
        printf '%s' \"<why it cannot be executed as written, and what a workable DoR would scope>\" > $TREE/.sana-needs-scope
      This routes to linear-dor-drafter.py to be re-scoped.

   b) THE SPEC IS FINE, THE RUNNER IS NOT EQUIPPED (a refused harness permission, a
      missing binary, an expired credential, a tool this session does not have):
        printf '%s' \"<the exact capability missing, what refused it, and what it unblocks>\" > $TREE/.sana-blocked-capability
      This does NOT go to the drafter. Re-scoping a correct spec burns a pass and
      returns the same blocked issue. It routes to whoever owns the config.

   Choosing (a) when it is really (b) is the costly mistake: it throws away a good
   spec and hides the real constraint. Ask yourself: would a perfectly written DoR
   still fail here? If yes, it is (b).

   Then post the same reasoning via progress and STOP. Do not improvise a different task.
   NEVER route around a refused permission by another route (writing the file through
   Bash, disabling the gate). A gate that is inconvenient is a gate doing its job.
   The file is what makes the refusal stick: the worker reads it, labels the issue needs-scope so the
   picker stops handing it back, and routes it to the DoR drafter for re-scoping. A refusal written
   ONLY as a comment is invisible to the loop -- the issue returns as the top pick on the next run and
   burns the budget again (observed on ASK-148 and ASK-149, three dispatches, zero diffs).
   Refusing is a correct outcome and is not counted as a failed attempt. Refuse when the DoR is
   genuinely unexecutable, not when it is merely hard.

Anything real you find and are not fixing: capture it, never just mention it:
  python3 $SKEL/plugins/prd-os/scripts/prd_runner.py spillover add --source $ISSUE --desc \"...\""

  # CLEAR BEFORE DISPATCH, so presence AFTER the run means exactly one thing:
  # THIS run wrote it (Codex round 2 on PR #141, major).
  #
  # The sentinel protocol always assumed that and never established it. The
  # consumption below deletes the file, but only on a run that REACHES it -- a
  # SIGKILL, a timeout, a slept laptop or a reboot in the window between the
  # agent writing the sentinel and the worker reading it leaves the file in a
  # worktree that is reused across runs by design. The next issue dispatched
  # into that tree is then blocked by a refusal about a different issue, and its
  # Linear comment carries the other issue's reason text.
  #
  # UNTIL NOW AN ACCIDENT COVERED HALF OF IT: a leftover sentinel was untracked,
  # so `git status --porcelain` read the tree dirty and position_tree_on_pr_head
  # declined the round. Gitignoring the sentinels (the fix one round earlier on
  # this same branch) makes them invisible to `status`, so the tree reads clean
  # and the round proceeds. That is why the fix is here and not a restored
  # dirty-tree wedge: the wedge only ever stalled the issue, and it depended on
  # a side effect of the sentinels being un-ignored, which is the property that
  # let one get committed in the first place.
  #
  # `.codex-blocked-capability` already had exactly this clear immediately
  # before the Codex dispatch. This is the same move at the Sana dispatch, so
  # both runners establish the freshness their own readers assume.
  rm -f "$TREE/.sana-needs-scope" "$TREE/.sana-blocked-capability"
  if run_bounded "$TIMEOUT_SECONDS" bash -c "cd '$TREE' && KIPI_AGENT='$AGENT' claude -p \"\$1\" </dev/null >>'$LOG' 2>&1" _ "$PROMPT"; then
    say "ok $ISSUE"
    python3 "$SYNC" progress "$ISSUE" "Worker run completed. See the branch/PR for the diff." \
      --agent "$AGENT" >/dev/null 2>&1 || true
  else
    rc=$?
    bump_attempt "$ISSUE" "claude run failed rc=$rc"
    N2="$(attempts_for "$ISSUE")"
    say "fail $ISSUE rc=$rc ($N2/$MAX_ATTEMPTS)"
    python3 "$SYNC" progress "$ISSUE" \
      "Worker run FAILED (attempt $N2 of $MAX_ATTEMPTS, rc=$rc). Log: ~/.config/kipi/linear-worker.log" \
      --agent "$AGENT" >/dev/null 2>&1 || true
    if [ "$N2" -ge "$MAX_ATTEMPTS" ]; then
      bash "$NOTIFY" "worker: $ISSUE stuck after $MAX_ATTEMPTS attempts - needs a human" 2>/dev/null || true
    fi
  fi

  # 4b. A REFUSAL IS A DECISION, NOT A FAILURE (ASK-275).
  #
  # Sana already had the judgment and used it correctly on ASK-148 and ASK-149.
  # What she had no way to do was ACT on it. The only lever available was
  # relabelling to owner:assaf -- the founder queue -- so a spec that needed
  # re-scoping became a founder decision. The founder does not do implementation,
  # so that lever was the wrong one and the issue simply came back.
  #
  # A FILE, not a grep of the run log. The agent writes one path; this reads it.
  # Parsing prose out of stdout for the word BLOCKED would make the loop depend on
  # the model phrasing its refusal a particular way, which is exactly the
  # prompt-only enforcement this repo bans. Presence of a file is deterministic.
  #
  # It does NOT bump_attempt: the attempt counter measures runs that failed to
  # produce, and a reasoned refusal produced the correct answer. Counting it would
  # spend a real budget on being right, and after three would mark the issue STUCK
  # and page a human -- routing to the founder by the back door.
  # TWO CLASSES, NOT ONE (ASK-275, corrected 2026-07-30 after first live contact).
  #
  # The first build of this had a single sentinel. On its first real run Sana used
  # it to escape ASK-140 and wrote, in her own words, "blocked on a harness
  # permission, NOT on scope" -- and the worker labelled it needs-scope anyway,
  # which routes the issue to linear-dor-drafter.py to be RE-SCOPED. The spec was
  # already correct. Re-scoping it would rewrite a good DoR and hand the loop the
  # same blocked issue again, having burned a drafter pass to learn nothing.
  #
  # self-healing-retry.md rule 5 already draws this line: environmental-trigger is
  # not latent-defect, and retrying logic cannot fix an environment. One channel
  # for both was my error, and the loop surfaced it in one run.
  #
  #   .sana-needs-scope        the SPEC is wrong    -> needs-scope        -> DoR drafter
  #   .sana-blocked-capability the RUNNER lacks a   -> blocked:capability -> capability grant
  #                            capability; spec ok
  #
  # Both leave the ready pool. They differ in who acts next and what they do, and
  # collapsing them loses exactly the information that decides which.
  # RESET PER ISSUE. $REFUSED gates two decisions further down (the no-PR attempt
  # bump and the budget spend), and this loop reuses every variable across
  # iterations -- a value that survived would make the issue AFTER a refusal
  # inherit its exemptions.
  SENTINEL=""; REFUSE_LABEL=""; REFUSE_KIND=""; REFUSED=""
  if [ -f "$TREE/.sana-blocked-capability" ]; then
    SENTINEL="$TREE/.sana-blocked-capability"; REFUSE_LABEL="blocked:capability"; REFUSE_KIND="capability"
  elif [ -f "$TREE/.sana-needs-scope" ]; then
    SENTINEL="$TREE/.sana-needs-scope"; REFUSE_LABEL="needs-scope"; REFUSE_KIND="scope"
  fi
  # Capability is checked FIRST: a run that wrote both is telling us the spec is
  # fine and the environment is not, and the environment is the blocking fact.
  if [ -n "$SENTINEL" ]; then
    SCOPE_WHY="$(head -c 1500 "$SENTINEL" 2>/dev/null)"
    [ -n "$SCOPE_WHY" ] || SCOPE_WHY="the run refused the DoR but recorded no reason"
    # CONSUMED, NOT KEPT. Two failures if it survives the run, and the worktree
    # is reused across runs so both are certain rather than theoretical:
    #   1. after the DoR is re-scoped, the next run reads the STALE file and
    #      refuses again -- an issue that can never be un-refused.
    #   2. an untracked file makes the tree dirty, and the position guard above
    #      refuses to reposition a dirty tree, wedging this issue permanently.
    # The durable record is the label plus the Linear comment, not this file.
    rm -f "$TREE/.sana-needs-scope" "$TREE/.sana-blocked-capability"
    if [ "$REFUSE_KIND" = "capability" ]; then
      say "$ISSUE BLOCKED on a missing capability (the spec is fine, the runner is not): $SCOPE_WHY"
    else
      say "$ISSUE REFUSED as unexecutable: $SCOPE_WHY"
    fi
    # HAND TO THE SECOND RUNNER BEFORE PARKING (ASK-281).
    #
    # Capability class ONLY. A scope refusal says the SPEC is wrong, and a second
    # runner reading the same wrong spec reaches the same wall -- that one really
    # does belong to the drafter. This branch is for "the spec is fine, THIS
    # runner is not equipped", which is a claim about a runner, not about the
    # fleet.
    #
    # RESET PER ISSUE, like $REFUSED above: this loop reuses every variable across
    # iterations, so a $CODEX_WHY that survived would attach the previous issue's
    # Codex refusal to the next issue's Linear comment.
    CODEX_WHY=""; CODEX_CONTINUED=""
    if [ "$REFUSE_KIND" = "capability" ]; then
      # A stale sentinel from a previous run would be read as this run's refusal,
      # which is the same defect the Sana sentinel already has a comment about.
      rm -f "$TREE/.codex-blocked-capability"
      CODEX_HEAD_BEFORE="$(git -C "$TREE" rev-parse HEAD 2>/dev/null || true)"
      say "$ISSUE handing to the Codex runner before parking (ONE attempt, never a loop)"
      CODEX_PROMPT="You are Codex, the SECOND runner on Linear issue $ISSUE.

Sana (Claude Code) already worked this issue in the git worktree $TREE, on branch
$BRANCH, and stopped. She did NOT judge the spec unworkable -- she judged her own
runner unequipped, and wrote this:

  $SCOPE_WHY

You are a different binary with a different harness. Claude Code's sensitive-path
guard over \`.claude/**\` is not yours. So the question is only: can YOU finish
what she could not?

1. Read the issue's Definition of Ready (Outcome, Files, Check, Blast radius, Not
   doing) and read what is already committed on $BRANCH. Sana's work stands --
   you are continuing it, not restarting it.
2. Work ONLY the part she was blocked on, and only what the DoR scopes. The
   'Not doing' line is binding on you exactly as it was on her.
3. Reproducer first: observe it RED, then make it green, then paste the real
   command output. A fix with no check that could have caught the bug is a patch.
4. Commit on $BRANCH with $ISSUE in the message (the commit-msg gate requires it).
   A COMMIT IS HOW THIS RUN IS SCORED. Exiting 0 having changed nothing reads as
   a refusal, and the issue gets parked -- which is the correct outcome if you
   genuinely cannot proceed, and the wrong one if you simply did not commit.
5. If you are ALSO not equipped -- the capability is missing for you too, not
   merely awkward -- say so in a file and stop:
     printf '%s' \"<the exact capability YOU lack, and what refused it>\" > $TREE/.codex-blocked-capability
   Both refusals then go on the Linear issue together, naming what each runner
   lacked, and the issue parks. That is a correct outcome, not a failure.

NEVER route around a refused permission by another route (writing through a shell
to dodge a guard, disabling a gate). A gate that is inconvenient is a gate doing
its job -- if the guard is the blocker, that is exactly what step 5 is for."
      # run_bounded, not a bare call: an unbounded second runner at 3am is the
      # failure mode loop-exits.md exit 7 exists for. ONE invocation, no retry --
      # a dead Codex must cost one timeout, not a spend loop.
      if run_bounded "$TIMEOUT_SECONDS" bash -c "cd '$TREE' && $CODEX_CMD \"\$1\" </dev/null >>'$LOG' 2>&1" _ "$CODEX_PROMPT"; then
        crc=0
      else
        crc=$?
      fi
      if [ -f "$TREE/.codex-blocked-capability" ]; then
        CODEX_WHY="$(head -c 1500 "$TREE/.codex-blocked-capability" 2>/dev/null)"
        [ -n "$CODEX_WHY" ] || CODEX_WHY="the Codex run refused but recorded no reason"
        # Consumed for the same reason Sana's is: it is untracked, and the
        # position guard refuses to reposition a dirty tree.
        rm -f "$TREE/.codex-blocked-capability"
      fi
      CODEX_HEAD_AFTER="$(git -C "$TREE" rev-parse HEAD 2>/dev/null || true)"
      # A NEW COMMIT IS THE BAR, not exit 0. "Exited 0 having done nothing" is the
      # exact shape that stayed invisible to the attempt counter until ASK-221,
      # and here it would be worse: it would un-park an issue nobody worked, with
      # the label gone and nothing on the branch to show for it.
      #
      # AND THE COMMIT MUST HAVE CHANGED FILES. A moved HEAD is not work: an empty
      # commit, an `--amend` that re-points at the same tree, or a rebase that
      # dropped its only hunk all move HEAD while leaving the branch byte-identical.
      # That is the ASK-221 shape one layer deeper -- a runner that believes it
      # worked and did not -- so the tree, not the pointer, is what gets compared.
      #
      # FAIL CLOSED: any git failure here yields an empty diff list and the issue
      # parks. Parking work that WAS done is recoverable (the label names the
      # capability and a human clears it); un-parking work that was NOT done is
      # not, because the label is gone and the picker never offers the issue again.
      CODEX_CHANGED_FILES=""
      if [ -n "$CODEX_HEAD_BEFORE" ] && [ -n "$CODEX_HEAD_AFTER" ] \
         && [ "$CODEX_HEAD_AFTER" != "$CODEX_HEAD_BEFORE" ]; then
        CODEX_CHANGED_FILES="$(git -C "$TREE" diff --name-only "$CODEX_HEAD_BEFORE" "$CODEX_HEAD_AFTER" 2>/dev/null || true)"
      fi
      if [ "$crc" -eq 0 ] && [ -z "$CODEX_WHY" ] && [ -n "$CODEX_CHANGED_FILES" ]; then
        CODEX_CONTINUED="$CODEX_HEAD_AFTER"
        say "$ISSUE Codex CONTINUED the work Sana was not equipped for (HEAD $CODEX_HEAD_BEFORE -> $CODEX_HEAD_AFTER) -- not parking it"
        # Clearing the label is the whole point: with it applied the picker never
        # offers the issue again, so a continuation that still parked would be a
        # continuation nobody could act on.
        REFUSE_LABEL=""
      elif [ -n "$CODEX_WHY" ]; then
        say "$ISSUE Codex is ALSO not equipped: $CODEX_WHY -- parking with both refusals recorded"
      else
        # Named precisely, because "no commit" and "a commit that changed nothing"
        # send a reader to different places: the first says Codex never got that
        # far, the second says it committed and the branch is unchanged anyway.
        if [ -n "$CODEX_HEAD_AFTER" ] && [ "$CODEX_HEAD_AFTER" != "$CODEX_HEAD_BEFORE" ]; then
          CODEX_WHY="the Codex run committed but changed no files (rc=$crc) and left no reason"
          say "$ISSUE Codex committed but changed no files (rc=$crc) -- parking"
        else
          CODEX_WHY="the Codex run produced no commit (rc=$crc) and left no reason"
          say "$ISSUE Codex left no commit (rc=$crc) -- parking"
        fi
      fi
    fi
    if [ -z "$REFUSE_LABEL" ]; then
      : # Codex continued it; there is nothing to park and no label to apply.
    elif python3 "$SYNC" label "$ISSUE" "$REFUSE_LABEL" >>"$LOG" 2>&1; then
      say "$ISSUE labelled $REFUSE_LABEL -- the picker will stop offering it"
    else
      # The label is the ONLY thing that makes this stick. If it did not land, the
      # issue returns as the top pick next run, so say so rather than reporting a
      # clean refusal: a silent failure here is an infinite redispatch loop.
      say "$ISSUE REFUSED but the $REFUSE_LABEL label did NOT apply (see $LOG) -- it will be offered again"
    fi
    # Different next action per class. A capability block that says "re-scope this"
    # sends the drafter to rewrite a spec that was already right.
    if [ -n "$CODEX_CONTINUED" ]; then
      REFUSE_NOTE="**Sana was not equipped; Codex was.** Not labelled \`blocked:capability\` -- the issue stays in the pool.

Sana stopped here:

$SCOPE_WHY

The Codex runner was handed the same issue and committed on \`$BRANCH\` (HEAD now \`$CODEX_CONTINUED\`). A capability one runner lacks is not a capability the fleet lacks.

**Next:** review the branch/PR as normal. No capability grant is needed and no founder decision is pending."
    elif [ "$REFUSE_KIND" = "capability" ]; then
      REFUSE_NOTE="**Blocked on a missing capability, not on scope.** Labelled \`blocked:capability\`; the picker will not offer it again until the capability exists.

BOTH runners were tried. Neither is equipped:

- **Sana (Claude Code):** $SCOPE_WHY
- **Codex:** $CODEX_WHY

**The Definition of Ready is sound.** Do NOT re-scope this: the spec is achievable, neither runner is equipped. Rewriting it would burn a drafter pass and return the same blocked issue.

**Next:** the capability above has to be granted or built. A harness permission is an authorization decision and belongs to whoever owns the config -- it is the one thing an agent must not grant itself. Once it exists, remove this label and the loop picks the issue straight back up."
    else
      REFUSE_NOTE="**Refused as unexecutable by the autonomous worker.** Labelled \`needs-scope\`; the picker will not offer it again until it is re-scoped.

$SCOPE_WHY

**Next:** linear-dor-drafter.py re-scopes this into a Definition of Ready that is achievable from a non-interactive session, or it is closed. This is engineering work, not a founder decision -- no action is needed from the founder."
    fi
    python3 "$SYNC" progress "$ISSUE" "$REFUSE_NOTE" --agent "$AGENT" >/dev/null 2>&1 || true
    # A REFUSAL DOES NOT SKIP THE REVIEW (ASK-275, 2026-08-01).
    #
    # This was `release` + `continue` -- jumping the whole of step 5. The
    # reasoning was that a refusal produces no diff, so there is nothing to
    # review. That is false for the capability class, and it is false in the
    # common case: a capability block is usually PARTIAL. Sana ships the half
    # she can, pushes it, opens the PR, and refuses the rest. The `continue`
    # then abandoned that PR: no reviewer, no verdict record, no
    # kipi/reviewer-approved -- and because the blocked:capability label pulls
    # the issue out of the picker, no later run ever comes back for it.
    #
    # Observed on the first three live partial blocks, all on 2026-07-31:
    # PR #49 (ASK-134), #50 (ASK-133), #51 (ASK-132). Each has a real commit,
    # each is still open, none has a verdict. converge.sh reported them
    # correctly ("STOP exit-7: PR #49 has no verdict after round 1 -- the review
    # died or timed out") and its diagnosis was wrong in the only way that
    # mattered: the review did not die, it was never invoked. The loop had just
    # been taught to review every PR it opens, and the refusal path was a second
    # way to open one it would not review.
    #
    # So: FALL THROUGH to step 5 instead of continuing. Step 5 is the single
    # chokepoint where a PR gets armed and reviewed, and a PR that came out of a
    # blocked run is not a different kind of PR -- it is committed code sitting
    # on a branch, which is exactly what the reviewer is for. A second review
    # call in this branch would be a second copy of that chokepoint with its own
    # drift; there is one.
    #
    # $REFUSED carries the refusal past step 5 so the two things a refusal must
    # NOT do still hold: it does not bump the attempt counter, and it does not
    # spend the work budget. Both are enforced below at their own sites. The
    # claim release moves to step 6, which already owns it -- releasing here and
    # then falling through would release the same claim twice from two places.
    #
    # EXCEPT WHEN CODEX CONTINUED IT. $REFUSED is read at three sites below and
    # every one of them is wrong for a continuation, because the issue did not
    # refuse -- a second runner worked it and committed:
    #   - the budget (`[ -n "$REFUSED" ] || DONE=$((DONE+1))`): a continuation is
    #     real work by a real runner, so it spends a dispatch. Carried as a
    #     refusal it costs nothing and an unattended run overruns its own --limit,
    #     which is exactly the silent budget burn ASK-221 was about.
    #   - the closing line: it reports the issue "held at $REFUSE_LABEL", and the
    #     handoff has just deliberately EMPTIED that variable -- so a completed
    #     issue was announced as held at nothing at all.
    #   - the no-PR branch: "a refusal is not a failed attempt" is true of a
    #     refusal. A run that produced commits and left no PR is the ASK-221 shape
    #     and does belong to the counter, whichever runner produced them.
    # The label was already cleared above; this is the same fact reaching the rest
    # of the loop instead of stopping at the label.
    [ -n "$CODEX_CONTINUED" ] || REFUSED="$REFUSE_KIND"
  fi

  # 5. REVIEW. Every PR this worker opens gets the adversarial reviewer, with no
  # human having to remember to ask. The author of the PR and the author of the
  # review must not be the same mind: the worker's `claude -p` wrote the diff, so
  # a reviewer inside that same session would re-derive its blind spots rather
  # than find them. This is a separate process with fresh eyes and no memory of
  # why the code looks the way it does.
  PR_NUM="$(cd "$TREE" && gh pr list --head "$BRANCH" --json number -q '.[0].number' 2>/dev/null)"

  # OPEN THE PR IN CODE, not on the agent remembering to. Observed on ASK-184
  # (2026-07-27): Sana pushed two good commits with an observed red-then-green
  # reproducer, then ended her turn on "bar 4 is in flight -- I'll report its
  # exit code, then open the PR". The turn ended; no PR existed; the review
  # never ran and the driver stopped with nothing to look at. Good work
  # stranded on an unopened PR is the most expensive possible failure here,
  # and "tell the agent to remember" is not enforcement.
  # Only fires when there is something to open a PR FOR: commits ahead of
  # origin/main. A branch with no commits still yields no PR, which is a real
  # failure the driver should still see.
  AHEAD="$(cd "$TREE" && git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)"

  # PUSH BEFORE THE REVIEW, ON BOTH PATHS -- not only when this worker opens the
  # PR. The push used to live inside the `[ -z "$PR_NUM" ]` branch below, so it
  # ran only when there was no PR yet. Every commit made AFTER a PR already
  # existed stayed local, and the Codex handoff (step 4b) is exactly that case:
  # a capability block is usually PARTIAL, so Sana ships a half and opens a PR,
  # and only then does the second runner commit. The reviewer was handed that
  # PR, read a remote head that was still Sana's half, and the run reported the
  # issue CONTINUED -- an approval for a diff the continuation is absent from.
  # That is worse than skipping the review: the label is cleared, the issue
  # leaves the parked pool, and the only copy of the work is a worktree on one
  # machine that the next round's position guard will refuse to move.
  #
  # Guarded on the two conditions that make a push meaningful, so a run that
  # produced nothing does not fire a no-op: there are commits past origin/main,
  # and the local tip differs from what the remote already has. A MISSING
  # origin/$BRANCH reads as "differs", which is correct -- nothing is there yet.
  #
  # A failed push is SAID, not swallowed. The review still runs (a stale review
  # beats none), but the operator has to be able to tell an approval of the real
  # head from an approval of an old one, and silence cannot carry that.
  if [ "${AHEAD:-0}" -gt 0 ]; then
    LOCAL_TIP="$(cd "$TREE" && git rev-parse HEAD 2>/dev/null || true)"
    REMOTE_TIP="$(cd "$TREE" && git rev-parse "origin/$BRANCH" 2>/dev/null || true)"
    if [ "$LOCAL_TIP" != "$REMOTE_TIP" ]; then
      if (cd "$TREE" && git push -u origin "$BRANCH" >/dev/null 2>&1); then
        say "$ISSUE: pushed $BRANCH to origin ($LOCAL_TIP) -- the reviewer reads the remote, not the worktree"
      else
        say "WARN: $ISSUE could not push $BRANCH; any review below reads the remote's older head"
      fi
    fi
  fi

  if [ -z "$PR_NUM" ]; then
    if [ "${AHEAD:-0}" -gt 0 ]; then
      say "$ISSUE: $AHEAD commit(s) pushed but no PR; opening it (the agent left it unopened)"
      (cd "$TREE" && gh pr create --head "$BRANCH" --base main \
         --title "$(git log -1 --pretty=%s)" \
         --body "Autonomous worker (Sana) on $ISSUE. Opened by the worker because the run ended without opening it.

Commits on this branch:
$(git log --oneline origin/main..HEAD)

Review runs next. Do not merge without it." >/dev/null 2>&1) || true
      PR_NUM="$(cd "$TREE" && gh pr list --head "$BRANCH" --json number -q '.[0].number' 2>/dev/null)"
      [ -n "$PR_NUM" ] && say "$ISSUE: opened PR #$PR_NUM"
    fi
  fi

  if [ -n "$PR_NUM" ]; then
    # ARM AUTO-MERGE, on BOTH paths that resolve $PR_NUM above: the PR the agent
    # opened, and the PR this worker opened because the agent did not. Until this
    # line, arming was a hand-typed `gh pr merge --auto --squash <n>` plus a
    # watcher loop inside an interactive session -- and both die when the terminal
    # closes, so a PR opened after that sat green forever with nobody left to
    # merge it. A human remembering is not enforcement.
    #
    # THE SAME FUNCTION the approved-PR gate calls, not a second copy: one arm,
    # one set of semantics, one place the three-state probe lives. The rationale,
    # the blast radius, and the paging discipline are all stated at its
    # definition. $AUTOMERGE is what it reached, and the closing line below reads
    # it -- without that, the arm landed here and the REPORT two lines down still
    # told the operator a founder owed this PR a merge (PR #33 review round 1,
    # finding 2), which is the pre-fix picture printed underneath the fix.
    arm_automerge "$PR_NUM" "$TREE"
    # Count review ROUNDS per issue, distinct from failed ATTEMPTS. A run that
    # succeeds but comes back REQUEST CHANGES is not a failure, so the attempts
    # counter never sees it -- yet rounds-to-approve is the number that actually
    # decides whether this worker can be trusted unattended. Without it the
    # question "does it converge or oscillate?" is answered by memory, and memory
    # is what this whole system exists to replace.
    ROUNDS="$(python3 -c "
import json
try: d=json.load(open('$ATTEMPTS'))
except Exception: d={}
e=d.setdefault('$ISSUE',{}); e['rounds']=e.get('rounds',0)+1
json.dump(d,open('$ATTEMPTS','w'),indent=2); print(e['rounds'])" 2>/dev/null || echo "?")"
    say "review PR #$PR_NUM for $ISSUE (round $ROUNDS)"
    # CLAUDE REVIEWS SANA'S WORK (founder-directed 2026-09-06, "forget codex go
    # with the claude fallback"). This REVERSES ASK-221 / the 2026-07-29 directive.
    # The cost is known and accepted: Sana is Claude, so a Claude reviewer shares her
    # lab and model family and re-derives her blind spots, and fresh context is not
    # an independent mind. Availability decided it, not the argument -- codex has
    # been returning "workspace is out of credits" at EXIT 0, and an engine that
    # fails silently cannot hold a required gate. See pr-review-agent.sh's header
    # for the measured chain. `--engine claude`
    # is stated EXPLICITLY here rather than inherited from the reviewer's default,
    # because which model checks this fleet's work is the kind of fact that must be
    # readable at the call site, not two files away.
    #
    # ONE call, not two. It was claude-then-codex, then codex-only, and since
    # 2026-09-06 claude-only: claude owns kipi/reviewer-approved and writes the one
    # verdict record every gate below reads, so a second codex pass would only burn
    # spend and post an advisory status nobody gates on.
    #
    # THERE IS NO FALLBACK IN THIS DIRECTION, and the sentence here used to claim
    # one. The Opus fallback and the DEGRADED marking hang off the reviewer's codex
    # branch, so with claude PRIMARY nothing stands behind a claude outage. That is
    # the SAFE direction, not a gap: the reviewer exits non-zero and posts NO status,
    # reviewer-floor turns an absent verdict into a red required context, and the PR
    # holds. A codex fallback would be worse than none -- codex is out of credits and
    # fails at EXIT 0, so it would fill the required gate with nothing.
    # LABEL THE INVOKER HERE, at the one place the scheduled path runs the reviewer
    # (sp-53aad86f). This is what makes a dispatcher-driven review distinguishable
    # from a hand run in the verdict record. It is set on the call rather than
    # exported once, so it cannot leak into an unrelated reviewer invocation.
    KIPI_REVIEW_INVOKER=worker $REVIEWER_CMD "$PR_NUM" --issue "$ISSUE" --post --engine claude >>"$LOG" 2>&1 \
      || say "WARN: the claude reviewer failed on PR #$PR_NUM (the PR stands, unreviewed)"
    # Read back the verdict RECORD the reviewer just wrote (never re-grep the
    # review prose) and state what happens next in plain terms. Rework itself
    # fires on the NEXT run, through the severity-floor gate above.
    FINAL_VERDICT="$(verdict_from_record "$(verdict_record_path "$REVIEWS_DIR" "$TARGET_SLUG" "$PR_NUM")")"
    # RE-GATE THE RECORD BEFORE REPORTING ON IT (PR #30 review round 2, major 3).
    # The reviewer above can fail -- it is a `|| say WARN` line, not a hard stop --
    # and when it does, this read returns the SAME record the gate at the top of
    # this run already refused to trust. Reporting "converged ... waits on founder
    # merge" off it put that line two lines below "the code at the head was never
    # reviewed", and the closing line is the one an operator scans. Unreachable
    # before ASK-219 (gate 10 skipped the issue before step 5 could run), which is
    # why arming exit 40 is what exposed it.
    #
    # Both shas are re-read rather than reused: a round that pushed moved the head,
    # so the values from the top of the loop describe a state that no longer
    # exists. The gate is the ONE reader of the comparison -- deriving it here
    # would be a second reader with drifting semantics.
    FINAL_REVIEWED_SHA="$(head_sha_from_record "$(verdict_record_path "$REVIEWS_DIR" "$TARGET_SLUG" "$PR_NUM")")"
    FINAL_CURRENT_SHA="$(pr_head_sha "$PR_NUM")"
    # AND THE GATE'S NOTE IS SAID, NOT SWALLOWED (PR #30 review round 3, minor 2).
    # converge.sh's own call site states the rule this line broke: "Swallowing it
    # would silently grandfather the blind spot it announces." The reviewer always
    # writes head_sha and writes it EMPTY when its own `gh pr view` could not
    # answer, and a fresh issue reaches step 5 with no prior PR -- so the
    # top-of-run gate, the one that does `say` its NOTE, never ran. The run then
    # closed on "converged ... waits on founder merge" with nothing anywhere
    # saying the approval is pinned to no commit, which is the one thing that
    # separates it from a verified one. The BEHAVIOUR is right and settled
    # (absent is not drift, fail toward terminal); the missing thing was the
    # sentence. Adds no per-run noise: the gate is silent whenever both shas were
    # read, which is every healthy round.
    FINAL_GATE_NOTE="$(rework_gate "$FINAL_VERDICT" "" "$FINAL_REVIEWED_SHA" "$FINAL_CURRENT_SHA")"; FINAL_GATE=$?
    [ -n "$FINAL_GATE_NOTE" ] && say "$FINAL_GATE_NOTE"
    # NO PAGE HERE, deliberately, and it is the one place in this pass that buys
    # silence: the NEXT scheduled run gates this same PR at 40, spends a drift
    # round, and pages once at the cap. Paging here too would double-page the same
    # unreviewed head on every round. What this line owes the operator is the
    # truth, not a second alarm.
    #
    # It reports and falls THROUGH to the release at step 6 rather than
    # `continue`-ing: a claim held by a run that already finished wedges this
    # issue for every later run, which is worse than the wrong log line this
    # replaces.
    if [ "$FINAL_GATE" = "40" ]; then
      say "$ISSUE NOT converged: PR #$PR_NUM still reads '$FINAL_VERDICT' recorded at $FINAL_REVIEWED_SHA while the head is $FINAL_CURRENT_SHA -- this round's review wrote no record, so the code at the head is still unreviewed. Re-review next run ($(drift_rounds_for "$ISSUE")/$MAX_DRIFT_ROUNDS drift round(s) spent)."
    else
    case "$FINAL_VERDICT" in
      "APPROVE"|"APPROVE WITH NITS")
        # WHO MERGES IT (PR #33 review, finding 2). This line closed every approved
        # run with "waits on founder merge" -- two lines under the same run's
        # "auto-merge armed on PR #N". Nobody waits; GitHub merges it. The closing
        # line is the one an operator scans, so it reports the state the arm above
        # actually reached instead of the one that was true before this worker
        # armed anything. Three outcomes, three sentences: a hedge that covered all
        # of them would make the healthy case unreadable.
        case "$AUTOMERGE" in
          armed)
            say "$ISSUE converged: $FINAL_VERDICT after $ROUNDS round(s); PR #$PR_NUM has auto-merge armed -- GitHub merges it once every required check is green, no human merge needed" ;;
          unarmed)
            say "$ISSUE converged: $FINAL_VERDICT after $ROUNDS round(s); PR #$PR_NUM is NOT armed and waits on a human merge: gh pr merge --auto --squash $PR_NUM" ;;
          *)
            say "$ISSUE converged: $FINAL_VERDICT after $ROUNDS round(s); PR #$PR_NUM -- gh could not read its auto-merge state this run, so check it landed; if it sits green: gh pr merge --auto --squash $PR_NUM" ;;
        esac ;;
      "REQUEST CHANGES"|"BLOCK")
        say "$ISSUE: $FINAL_VERDICT (round $ROUNDS) -- rework via: kipi work --apply --issue $ISSUE" ;;
      *)
        say "$ISSUE: no verdict recorded for PR #$PR_NUM (round $ROUNDS) -- review may have died; see $REVIEWS_DIR" ;;
    esac
    fi
  else
    say "no PR found for $BRANCH; nothing to review"
    # A RUN THAT PRODUCED NOTHING IS A FAILED ATTEMPT (ASK-221, 2026-07-30).
    #
    # MAX_ATTEMPTS used to count only runs where `claude` exited non-zero (the
    # note at the top of this file said so deliberately). But the agent can exit
    # 0 having written nothing at all, and that outcome was invisible to the
    # counter: no bump, ledger stays {}, the issue reads `attempt 1/3` forever
    # and is immediately re-dispatchable. It never becomes stuck, so it never
    # stops costing budget.
    #
    # Measured on the founder's machine for budget day 2026-07-30: the loop spent
    # its ENTIRE 3-issue budget on this. 14:15 ASK-149, 14:30 ASK-149 again
    # (third dispatch of that issue overall), 14:45 ASK-148 -- every one exiting
    # `ok` with zero commits, zero dirty files and no remote branch, then
    # converge STOP exit-7. Three unattended dispatches, no PR, and therefore no
    # review and no verdict record on a day the loop ran to its cap.
    #
    # Bumping here reuses the mechanism that already exists rather than adding a
    # new one: three no-output runs mark the issue stuck and a human decides,
    # which is the correct terminal state for "the agent cannot make progress on
    # this spec". The cost of getting it wrong is bounded and visible -- a stuck
    # issue is reported, whereas the current behaviour is silent budget burn.
    #
    # EXCEPT WHEN THE RUN REFUSED. A refusal with no diff is the correct answer,
    # not a failed attempt -- the same reasoning stated at the sentinel above,
    # enforced here because the refusal path now REACHES this line instead of
    # `continue`-ing past it. Without this guard the fall-through would silently
    # start counting every refusal as a failure and mark a correctly-refused
    # issue STUCK after three, which is the founder-queue routing the whole of
    # ASK-275 removed.
    if [ -n "$REFUSED" ]; then
      say "$ISSUE: refused ($REFUSED) and left no PR -- nothing to review, and a refusal is not a failed attempt"
      # SAY SO WHERE converge CAN READ IT (PR #192 review round 2). converge
      # stops at exit-7 on "no PR" and charges an attempt when nothing else did.
      # It cannot tell this refusal from an interrupted worker: both leave the
      # counter untouched and no PR. Without a durable marker three CORRECT
      # refusals reach the 3-attempt cap and the issue is falsely marked stuck --
      # the founder-queue routing ASK-275 removed, re-entering from the driver.
      # The sentinel files cannot carry it: they are deleted before this line.
      # The ledger can -- both scripts already share it, through one locked writer.
      python3 "$LEDGER" "$ATTEMPTS" claim-flag "$ISSUE" refused_no_pr >/dev/null 2>&1 || true
    else
      bump_attempt "$ISSUE" "run exited 0 but opened no PR on $BRANCH (no output)"
    fi
  fi

  # 6. RELEASE at PR-open, not at close, so a reviewer can pick the tree up.
  # From INSIDE $TREE, matching the claim above. A claim taken in one cwd and
  # released in another does not error: release reads a DIFFERENT lock file,
  # finds nothing, prints "not held" and exits 0 while the real lock sits in the
  # worktree forever, wedging that issue permanently. Asserted by case 3 of
  # test-linear-worker-parallel.sh, which reads the lock files back after the run.
  ( cd "$TREE" && python3 "$CLAIM" release "$ISSUE" --agent "$AGENT" --session "$SESSION" ) >/dev/null 2>&1 || true
  # THE CLOSING LINE MUST NOT SAY "converged" ABOUT A BLOCKED ISSUE. The verdict
  # report above speaks for the PR and is correct about it -- an APPROVE on a
  # partial diff is a real approval of the code that is there. It is not a
  # statement about the ISSUE, which is still held at $REFUSE_LABEL and is not
  # done. The closing line is the one an operator scans, so it says which.
  if [ -n "$REFUSED" ]; then
    say "$ISSUE is NOT done: held at $REFUSE_LABEL. Any PR above carries only the half that shipped before the block, and the verdict on it is a verdict on that half."
  fi
  # A REFUSAL COSTS A TURN, NOT A DISPATCH. This was a `continue` before the
  # DONE++ at the sentinel above; the fall-through moved the skip here so the
  # budget semantics are unchanged while the review is no longer skipped with
  # them. When the worker holds the pool (no --issue), the loop moves straight to
  # the next ready issue and spends its budget on one that can actually yield a
  # diff.
  [ -n "$REFUSED" ] || DONE=$((DONE+1))
done

say "worker: run complete"
# The `exit 0` below is the last statement INSIDE the ASK-351 brace, and it has to
# stay last and stay unconditional: it is what stops bash from ever reading this
# file again. See the header. Nothing may be added below the closing brace.
exit 0
}
