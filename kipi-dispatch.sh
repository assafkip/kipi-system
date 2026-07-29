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
#   3 budget        DAILY_MAX issues per BUDGET DAY (which starts at RESET_HOUR
#                   local, NOT midnight -- see the budget block), and never more
#                   than the free concurrency slots in one tick. The interval
#                   throttles; the daily counter is the actual ceiling.
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
# run's.
#
# UNKNOWN SET => NOT IN PARALLEL, WHICH IS NOT THE SAME AS NEVER (PR #36 r3).
# An unknown set intersects everything by assumption -- and "everything" is
# EMPTY when nothing is live and nothing else has launched this pass, so such an
# issue still runs, alone, and holds the board until it finishes. The first cut
# refused it outright, which on the real board of 2026-07-28 (51 of 55 ready
# issues parse to an empty set) turned a throughput unlock into a throughput
# CUT: 1 issue/tick before the change, 0 after, forever, with the liveness
# beacon still reporting a healthy loop. A safety gate that refuses the whole
# board is not safe, it is off.
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
BURST_GIVEN=0
PARALLEL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --burst)    shift; BURST="${1:-}"; BURST_GIVEN=1 ;;
    --parallel) shift; PARALLEL="${1:-}" ;;
    -h|--help)  usage; exit 0 ;;
    *) printf 'kipi-dispatch: unknown argument %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
case "$BURST" in ''|*[!0-9]*) printf 'kipi-dispatch: --burst wants a number\n' >&2; exit 2 ;; esac
case "$PARALLEL" in '') ;; *[!0-9]*) printf 'kipi-dispatch: --parallel wants a number\n' >&2; exit 2 ;; esac
[ "${PARALLEL:-1}" = "0" ] && { printf 'kipi-dispatch: --parallel 0 would dispatch nothing\n' >&2; exit 2; }
# `--burst 0` is not a burst of nothing, it is the internal value for "this is a
# heartbeat tick", so it fell through EVERY `[ "$BURST" -gt 0 ]` branch below: it
# spent the daily counter and wrote the liveness beacon that the beacon's own
# comment says a burst must never write. A founder typing `--burst 0` gets the
# scheduler's behaviour under the founder's name. Refuse it, like --parallel 0.
[ "$BURST_GIVEN" -eq 1 ] && [ "$BURST" = "0" ] && {
  printf 'kipi-dispatch: --burst 0 would dispatch nothing (drop the flag for a heartbeat tick)\n' >&2; exit 2; }

mkdir -p "$(dirname "$LOG")"
# Also to stdout. A burst is a foreground founder command and MUST show what it
# picked and what it skipped; under launchd stdout goes to the plist's log, so
# echoing costs the heartbeat nothing.
say() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG"; }
page() { bash "$NOTIFY" "$1" >/dev/null 2>&1 || true; }

# Page at most once per marker file. Every recurring condition this script pages
# for -- the daily cap, a broken picker, a board it cannot read -- is TRUE again
# on the next tick, so an ungated page is 96 pings a day. That is the cry-wolf
# failure: it trains the founder to mute the channel and costs the real alerts
# their job. Callers pass a date-stamped marker, so the state re-pages tomorrow
# if it is still true.
page_once() {  # page_once <marker-file> <message>
  [ -f "$1" ] && return 0
  page "$2"
  : > "$1"
}

# LOCAL date, not UTC, and this stamps PAGE MARKERS only -- not the spend
# counter. Every page marker carries this stamp, so a fault that is still true
# tomorrow pages again tomorrow: deduped, not muted. Read before the `cd`
# because repo-not-found needs to stamp a marker too.
#
# THE SPEND COUNTER USES $BUDGET_DAY INSTEAD, which rolls at RESET_HOUR local
# rather than at midnight (see the budget block). Keep the two separate: a
# midnight-rolling budget hands a full allowance to an unattended overnight run
# at the moment the founder falls asleep, which is the thing RESET_HOUR exists
# to prevent. Collapsing them back into one stamp silently reinstates it.
TODAY="$(date +%Y-%m-%d)"

# THE THREE FATAL / INFRA PAGES ARE page_once, NOT page (PR #36 r4).
# Every condition this script pages for is TRUE again on the next tick, and
# these three (repo gone, gh missing, Linear unreachable) persist until a human
# fixes them. Ungated, one expired token was 96 identical Slack messages a day.
# The `say` line still fires every tick, so the LOG keeps full fidelity; only
# Slack is deduped. The cost is honest and worth naming: if the founder misses
# the one page, the next one is tomorrow -- the daily re-stamp is the backstop.
cd "$REPO" 2>/dev/null || {
  say "FATAL: repo not found at $REPO"
  page_once "$HOME/.config/kipi/dispatch-repo-$TODAY.paged" \
    "kipi dispatch: repo not found at $REPO -- the Linear loop is DEAD. Do: check the path in com.kipi.dispatch.plist."
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
#
# KIPI_DISPATCH_FAKE_LIVE_FILE (higher precedence) is re-read on EVERY call,
# which is the whole point of it: the defect it pins is a live set read ONCE and
# reused for the rest of the pass, and a static value cannot express "a converge
# started while this pass was running". pgrep is already fresh per call; what
# has to be tested is how often the script CALLS it.
live_issues() {
  if [ -n "${KIPI_DISPATCH_FAKE_LIVE_FILE:-}" ]; then
    grep -oE 'ASK-[0-9]+' "$KIPI_DISPATCH_FAKE_LIVE_FILE" 2>/dev/null | sort -u || true
    return 0
  fi
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
  ISSUE="$1" PRD_SPLIT="$PRD_SPLIT" KIPI_DISPATCH_REPO="$REPO" \
  KIPI_DISPATCH_MAGNETS="$MAGNET_FILES" \
  python3 - > "$2" 2>"$2.err" <<'PY'
import importlib.util, json, os, pathlib, re, sys

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

# `~/`- and `/`-anchored paths, which _extract_paths drops WHOLE: its token
# regex is anchored at [A-Za-z0-9_.]. For prd_split's own job -- scope
# enforcement on repo-relative paths -- that is merely narrow. For an
# INTERSECTION it is a silent hazard, and the reason this gate refused the real
# board: 32 of the 55 issues ready on 2026-07-28 name a
# `~/Library/LaunchAgents/*.plist`. Worse than the refusals, a Files list that
# MIXES a plist with a repo path yielded a set that looks complete and is not,
# so two agents could be sent into one plist while the log called them disjoint.
#
# Only the ANCHOR is matched here; the tail is validated by the same
# _PATH_TOKEN_RE, so there is still one definition of "what is a path". `~` is
# expanded so `~/x` and `/Users/me/x` are one file, not two. Over-collection
# (a prose mention of an absolute directory) makes the intersection MORE
# conservative -- an extra skip with a named path, never a missed conflict.
_ANCHORED_RE = re.compile(r"(?<![A-Za-z0-9_.~/-])(~/|/)([A-Za-z0-9_.][A-Za-z0-9_.\-/]*)")

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
    m = re.search(r"(?mi)^\s*(?:[-*+]\s+)?\*\*\s*Files\s*:?\s*\*\*:?[ \t]*(.*)$", section)
    if m:
        rest = section[m.end():]
        nxt = re.search(r"(?m)^\s*(?:[-*+]\s+)?\*\*\s*[A-Za-z][A-Za-z ]*?\s*:?\s*\*\*", rest)
        value = m.group(1) + "\n" + (rest[: nxt.start()] if nxt else rest)
# A DoR that says the paths are unknown is the same as having none: emit
# nothing so the caller fails closed rather than dispatching on a guess.
if not value or mod._UNKNOWN_RE.search(value):
    raise SystemExit(0)
seen = set()
out = []
_repo = os.environ.get("KIPI_DISPATCH_REPO", "")
_repo = os.path.realpath(_repo) if _repo else ""

def normalise(path):
    # ONE SPELLING PER FILE. The intersection is exact string match, so
    # `/Users/me/projects/kipi-system/foo.sh` and `foo.sh` were two different
    # files to it and two issues editing one file both dispatched. 6 real DoRs
    # spell a repo path absolutely. Everything inside the repo is reduced to the
    # repo-relative form the DoRs mostly use; realpath on both sides so a
    # symlinked checkout (/tmp -> /private/tmp, and the founder's own path)
    # compares equal. Paths OUTSIDE the repo -- a launchd plist under ~ -- stay
    # absolute, which is still one canonical spelling for them.
    path = os.path.expanduser(path)
    if _repo and os.path.isabs(path):
        real = os.path.realpath(path)
        if real.startswith(_repo + os.sep):
            return real[len(_repo) + 1:]
        return real
    return path

def emit(path):
    # A trailing slash means the DoR was talking ABOUT a directory, not naming a
    # file to edit -- ASK-225's own Files bullet contains the prose "must NOT go
    # under the synced `q-system/` subtree". Left in, that token appears in many
    # DoRs and makes unrelated issues collide on a word. The intersection is
    # exact-match on file paths, so only file paths belong in it. Checked BEFORE
    # normalising, because realpath() strips the trailing slash that carries the
    # signal.
    if path.endswith("/"):
        return
    path = normalise(path)
    if path in seen:
        return
    seen.add(path)
    out.append(path)

for m in _ANCHORED_RE.finditer(value):
    tail = m.group(2).rstrip(".,;:")
    if tail and mod._PATH_TOKEN_RE.fullmatch(tail):
        emit(m.group(1) + tail)
for path in mod._extract_paths(value):
    emit(path)

# PARTIAL CONSUMPTION IS "UNKNOWN", NOT A NARROWER SET (PR #36 r5 finding 1).
#
# prd_split._split_candidates returns the BACKTICKED spans whenever the block
# has any, so a plain path sitting beside a backticked one is discarded whole.
# For prd_split's own job -- allowed_files for ONE issue -- a narrower set is
# merely a tighter scope. As a set-membership oracle ACROSS issues it inverts:
# a missing token reads as "safe to run in parallel", so the gate certifies two
# agents into one file and reports `skipped 0`.
#
# Three rounds of this review each found the next spelling that escapes
# (`~/`-anchored, absolute-vs-relative, plain-beside-backticked). Enumerating
# spellings loses that race by construction. So this does not rescue a fourth
# one: it asks whether the block NAMES a file the set does not contain, and if
# so declares the set unknown. Unknown already has a meaning here -- run alone,
# never in parallel -- so this fails closed on the intersection without
# refusing the issue, which is the regression the same finding cost this file
# in round 3.
#
# Deliberately conservative in one direction only: a citation (`foo.sh:318`), a
# prose mention, or an unparseable path all trip it, and the cost of each false
# trip is one issue running alone with a named reason. The cost of a miss is a
# conflicted PR from two agents in one file.
_CITE_RE = re.compile(r":\d+(?:-\d+)?$")
_FILENAME_RE = re.compile(r"\.[A-Za-z][A-Za-z0-9]{1,5}$")

magnets = set()
for _m in os.environ.get("KIPI_DISPATCH_MAGNETS", "").split():
    magnets.add(normalise(_m))
    magnets.add(_m.rsplit("/", 1)[-1])
basenames = {p.rsplit("/", 1)[-1] for p in seen}

def named_files(text):
    """Every word in the block that is shaped like a FILE, however spelled."""
    for raw in text.split():
        w = raw.strip("`*_|\"'").lstrip("([{<").rstrip(")]}>").rstrip(",;:.")
        w = _CITE_RE.sub("", w)          # `foo.sh:318` is a path plus a line no.
        if not w or not mod._PATH_TOKEN_RE.fullmatch(w):
            continue
        # A trailing alphabetic extension is what separates a file from prose
        # that merely contains a dot or a slash: `e.g`, `3.2`, `and/or`, `N/A`
        # and a bare directory name are all rejected here, and none of them
        # would ever be an intersection hit anyway.
        if not _FILENAME_RE.search(w.rsplit("/", 1)[-1]):
            continue
        yield w

missed = []
for w in named_files(value):
    n = normalise(w)
    if n in seen or n in magnets:
        continue
    # A bare basename beside a full path is the same file mentioned twice
    # ("extend `a/b/test-x.sh`; test-x.sh already covers the mutex"), which is
    # a real DoR shape and carries no new file. A basename that is genuinely a
    # DIFFERENT file is the one gap left here, and it is the status quo ante.
    if "/" not in n and n in basenames:
        continue
    missed.append(w)

if missed:
    # Nothing on stdout: an incomplete set is worse than no set, because the
    # caller can act on "unknown" and cannot act on "wrong".
    print("PARTIAL: %s" % " ".join(missed[:3]), file=sys.stderr)
    raise SystemExit(0)

for p in out:
    print(p)
PY
  RC=$?
  [ "$RC" -eq 0 ] && return 0
  printf 'its file set could not be read (%s)' \
    "$(tr '\n' ' ' < "$2.err" | sed 's/  */ /g' | tail -c 200)"
  return 1
}

# Does this issue have a KNOWN file set? 0 = yes (written to <out-file>),
# 1 = unknown (parsed fine, nothing usable in it), 2 = unreadable (a fault).
# Prints why not.
#
# EMPTY IS UNKNOWN, and that distinction is the whole point of this wrapper.
# fileset_for returns non-zero only on a Python EXCEPTION, so "no `**Files:**`
# line", "the DoR says the paths are unknown" and "every token was rejected" all
# came back as SUCCESS with an empty file. Candidates then failed closed on that
# input while LIVE runs failed OPEN -- `cat`ting an empty file into the union
# contributed no constraint, so candidates were dispatched straight into a live
# run's files, two lines under a comment promising the opposite. One helper, so
# the candidate side and the live side cannot drift apart about what "unknown"
# means a second time.
fileset_known() {  # fileset_known <issue> <out-file>
  if ! WHY_NOT="$(fileset_for "$1" "$2")"; then
    printf '%s' "$WHY_NOT"
    return 2
  fi
  [ -s "$2" ] && return 0
  # TWO WAYS TO BE UNKNOWN, AND THEY NEED DIFFERENT FIXES. "No Files list" is
  # answered by writing one. "The block names a path the parser could not take"
  # is answered by backticking it -- and telling that operator to add a list
  # that is already there sends them looking for something they will not find.
  # Same reason fileset_for does not swallow a Linear failure into "no Files
  # line": one wrong reason costs more than no reason.
  PARTIAL="$(sed -n 's/^PARTIAL: //p' "$2.err" 2>/dev/null | head -1)"
  if [ -n "$PARTIAL" ]; then
    printf 'its `**Files:**` block names %s but the parser could not take that spelling, so the set would be INCOMPLETE (backtick every path there to let it share the board)' "$PARTIAL"
    return 1
  fi
  printf 'no usable `**Files:**` list in its DoR, so its file set is unknown (add one to let it share the board)'
  return 1
}

# The first path present in BOTH sets, magnet files excluded. Empty when the two
# sets are disjoint. Named so the skip line can quote it -- "they overlap" with
# no path is a report nobody can act on.
#
# Magnets are matched by FULL PATH and by BARE BASENAME. Real DoRs use both
# spellings: ASK-224 and ASK-218 each write the bare `capability-manifest.json`
# inside a sentence saying they will NOT edit it, and a full-path-only exemption
# missed that, serialising two of the four dispatchable issues on a file neither
# one touches. Same root as the `q-system/` prose token: a negated mention
# becomes a path token, so the exemption has to cover every spelling of the
# magnet, not just the canonical one.
magnet_patterns() {
  for M in $MAGNET_FILES; do printf '%s\n%s\n' "$M" "${M##*/}"; done
}
strip_magnets() { grep -vxF -f "$MAGNETS" || true; }
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

# --- ONE PICKER AT A TIME -------------------------------------------------
# The launchd heartbeat (every 900s) and a founder's foreground `--burst` are
# two producers of a dispatch pass. Nothing stopped them running at once, and
# two passes reading the same live set both find the same candidate disjoint --
# so the file-set intersection, which is the entire point of this script, is
# computed from a state that a concurrent pass is already invalidating. The
# founder's own `kipi converge` is a THIRD producer; the lock cannot see that
# one, which is why the live set is also rebuilt per candidate below. Two
# defences, two different producers.
#
# mkdir is the atomic primitive: macOS ships no flock(1) and this runs under
# /bin/bash 3.2 under launchd. The holder's pid goes INSIDE the directory so a
# SIGKILLed pass does not wedge the loop forever -- a lock nobody can clear is a
# worse outage than the race it prevents (the reclaim-on-read rule the claim
# mutex learned in ASK-189). A directory with no readable pid is treated as
# YOUNG, not stale: that is the microsecond between mkdir and the pid write.
#
# Taken AFTER the beacon on purpose: a tick that gives up because another pass
# holds the lock is still proof of life, and skipping the beat would make a
# healthy loop look dead and fire a false RESUMED page later.
LOCK_DIR="$HOME/.config/kipi/dispatch.lock"
LOCK_HELD=0
SCRATCH=""
cleanup() {
  [ -n "$SCRATCH" ] && rm -rf "$SCRATCH"
  [ "$LOCK_HELD" -eq 1 ] && rm -rf "$LOCK_DIR"
  return 0
}
trap cleanup EXIT

lock_holder_dead() {
  HOLDER="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  case "$HOLDER" in ''|*[!0-9]*) return 1 ;; esac
  kill -0 "$HOLDER" 2>/dev/null && return 1
  return 0
}

# A burst is a founder standing at the terminal, and a heartbeat tick is seconds
# of picking, so waiting it out is right. The heartbeat does NOT wait for a
# burst: launchd re-fires in 900s and a stacked tick buys nothing.
if [ "$BURST" -gt 0 ]; then
  LOCK_WAIT="${KIPI_DISPATCH_LOCK_WAIT:-120}"
else
  LOCK_WAIT="${KIPI_DISPATCH_LOCK_WAIT:-0}"
fi
LOCK_TRIES=0
LOCK_RECLAIMS=0
while ! mkdir "$LOCK_DIR" 2>/dev/null; do
  if [ "$LOCK_RECLAIMS" -lt 2 ] && lock_holder_dead; then
    say "note: clearing a dispatch lock left behind by a killed pass (pid $HOLDER)"
    rm -rf "$LOCK_DIR"
    LOCK_RECLAIMS=$(( LOCK_RECLAIMS + 1 ))
    continue
  fi
  if [ "$LOCK_TRIES" -ge "$LOCK_WAIT" ]; then
    # Not a fault and not an empty board: another pass is doing this work right
    # now. Exit 0, no page -- paging here would cry wolf on the loop WORKING.
    say "skip: another dispatch pass is already picking (lock held by pid $(cat "$LOCK_DIR/pid" 2>/dev/null))"
    exit 0
  fi
  sleep 1; LOCK_TRIES=$(( LOCK_TRIES + 1 ))
done
printf '%s' "$$" > "$LOCK_DIR/pid"
LOCK_HELD=1

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

# THE BUDGET DAY IS NOT $TODAY. It starts at RESET_HOUR LOCAL, not at midnight.
# Founder-set 2026-07-28, and the reason is safety, not tidiness:
#
#   UTC midnight     rolls at 17:00 local -- refills at teatime, leaving the loop
#                    idle through the whole working day it was meant to serve.
#   local midnight   refills the instant the founder falls asleep, handing a full
#                    budget to an unattended overnight run. Worst of the three.
#   local 07:00      overnight can only spend what is LEFT from yesterday, and a
#                    fresh budget arrives when someone is awake to watch it.
#
# Founder, verbatim: "i rather have the cap restart in the morning. because
# midnight makes it so it can work while i sleep and thats not safe."
#
# Deliberately a SEPARATE stamp from $TODAY rather than shifting $TODAY itself:
# $TODAY also names the page-dedup markers, and moving those is a different
# decision that nobody made. Only the spend counter rolls at RESET_HOUR.
#
# Implemented by shifting the clock back RESET_HOUR hours and taking that date,
# so 03:00 Tuesday still belongs to Monday's budget. The file NAME carries the
# label, so the rollover needs no timer, no cron entry and no state machine: a
# new budget day is simply a new filename that reads 0.
RESET_HOUR="${KIPI_DISPATCH_RESET_HOUR:-7}"
# BSD date (macOS) uses -v; GNU date uses -d. Try both so this is not silently
# wrong on a Linux box, where a failed shift would fall back to today's date and
# quietly restore the midnight behaviour this exists to prevent.
BUDGET_DAY="$(date -v-"${RESET_HOUR}"H +%Y-%m-%d 2>/dev/null \
              || date -d "-${RESET_HOUR} hours" +%Y-%m-%d 2>/dev/null)"
if [ -z "$BUDGET_DAY" ]; then
  say "FATAL: could not compute the budget day (neither BSD nor GNU date worked)"
  page_once "$HOME/.config/kipi/dispatch-budgetday-$TODAY.paged" \
    "kipi dispatch: cannot compute its spend budget window, so it refused to dispatch rather than run uncapped. Do: check \`date -v-7H\` on this machine."
  exit 1
fi

COUNT_FILE="$HOME/.config/kipi/dispatch-count-$BUDGET_DAY"
DISPATCHED_TODAY=0
if [ "$BURST" -eq 0 ]; then
  DISPATCHED_TODAY="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"
  case "$DISPATCHED_TODAY" in ''|*[!0-9]*) DISPATCHED_TODAY=0 ;; esac
fi

if [ "$BURST" -eq 0 ] && [ "$DISPATCHED_TODAY" -ge "$DAILY_MAX" ]; then
  # Say it once per budget day, not every 15 minutes -- a budget ceiling
  # repeated 96 times is the cry-wolf failure, and this is not an error anyway.
  if [ ! -f "$COUNT_FILE.paged" ]; then
    say "DAILY CAP: $DISPATCHED_TODAY/$DAILY_MAX issues dispatched for budget day $BUDGET_DAY, stopping until ${RESET_HOUR}:00 local"
    page "kipi dispatch: hit the daily cap of $DAILY_MAX issues (~$((DAILY_MAX * 6)) agent sessions). Not an error -- the loop is resting until ${RESET_HOUR}am, then it picks up again on its own. Do: nothing, or raise KIPI_DISPATCH_DAILY_MAX in com.kipi.dispatch.plist to go faster."
    : > "$COUNT_FILE.paged"
  fi
  exit 0
fi

# gh is what every downstream step needs; failing here with a clear page beats
# dispatching an agent that dies opening its PR.
if ! command -v gh >/dev/null 2>&1; then
  say "FATAL: gh not on PATH ($PATH)"
  page_once "$HOME/.config/kipi/dispatch-gh-$TODAY.paged" \
    "kipi dispatch: gh CLI not on PATH under launchd, so no PR can be opened. The Linear loop is stalled. Do: fix PATH in com.kipi.dispatch.plist."
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
#
# MATCH WHAT THE PRODUCER ACTUALLY PRINTS (PR #36 r4). linear-worker.sh:239 says
# `INFRA: linear unreachable (<reason>)` through its timestamped `say` and exits
# ZERO, and the two likeliest reasons -- linear-sync.py:341 "no Linear API key.
# Create one at ..." and :380 "network: <errno>" -- contain none of the three
# keywords below. So the commonest infra failure of all read as an empty board,
# every 15 minutes, exit 0, no page. The keyword grep stays for anything that
# reaches us by another route; `INFRA:` is the marker the worker owns.
WORK_INFRA="$(printf '%s' "$WORK_OUT" | grep -E '(^|[[:space:]])INFRA:' | head -1)"
if [ -z "$WORK_INFRA" ]; then
  WORK_INFRA="$(printf '%s' "$WORK_OUT" | grep -i 'infra_error\|authentication\|unauthorized' | head -1)"
fi

# A CRASHED PICKER IS NOT AN EMPTY BOARD. WORK_RC used to be captured and never
# read, so anything the infra grep above did not match -- a traceback, an OOM, a
# git failure inside the worker -- fell through to "nothing ready", every 15
# minutes, exit 0, no page. That is this fleet's own lesson (a zero result must
# prove it is empty, not broken) failing in its own scheduler.
if [ "$WORK_RC" -ne 0 ]; then
  say "kipi work FAILED (exit $WORK_RC): $(printf '%s' "$WORK_OUT" | tail -5 | tr '\n' ' ' | tail -c 300)"
  page_once "$HOME/.config/kipi/dispatch-workfail-$TODAY.paged" \
    "kipi dispatch: \`kipi work\` exited $WORK_RC, so NO issue can be picked up. The picker is BROKEN, not the board empty -- the loop is stopped. Do: run \`bash kipi work\` in $REPO and read the error."
  exit 1
fi

# The board total, from the worker's own count. `--limit` truncates the LIST it
# prints, never this number, which is why the closing summary has to quote it:
# "of 5 candidate(s)" while 55 issues are ready is exactly the silent truncation
# that skip() exists to prevent, committed by the summary line itself.
READY_TOTAL="$(printf '%s' "$WORK_OUT" | grep -oE '[0-9]+ ready issue' | head -1 | grep -oE '^[0-9]+' || true)"

CANDIDATES="$(printf '%s' "$WORK_OUT" | grep -oE '\[dry\] would work ASK-[0-9]+' | grep -oE 'ASK-[0-9]+')"

# THE INFRA VERDICT IS TAKEN HERE, WHERE THE BOARD IS KNOWN TO BE EMPTY, and
# nowhere else -- one reader, not two. `INFRA:` is not always fatal: the worker
# prints a per-issue one at :763 and :823 and keeps going, so stopping on the
# marker alone would turn one bad issue into a stopped loop, which is the same
# over-enforcement finding 1 already cost this file once. An infra line WITH
# candidates is reported and stepped past; an empty board WITH an infra line is
# a fault, because a zero result must prove it is empty, not broken.
if [ -z "$CANDIDATES" ]; then
  if [ -n "$WORK_INFRA" ]; then
    say "infra error from kipi work: $WORK_INFRA"
    page_once "$HOME/.config/kipi/dispatch-infra-$TODAY.paged" \
      "kipi dispatch: Linear is unreachable or auth expired, so NO issues can be picked up. The loop is stopped, not slow. Do: run \`bash kipi work\` by hand and check the Linear token."
    exit 1
  fi
  say "nothing ready (${READY_TOTAL:-an unknown number of} ready issue(s) on the board)"
  exit 0
fi
[ -n "$WORK_INFRA" ] && say "note: kipi work reported an infra problem but still returned candidates, continuing: $WORK_INFRA"
N_CANDIDATES="$(printf '%s\n' "$CANDIDATES" | grep -c .)"

# A TARGET above the candidate count is not a plan, it is a wrong number in the
# one place it costs something (PR #36 r5 finding 2). The loop dispatches at
# most one run per candidate, so `--burst 10` on a 2-issue board could never
# start more than 2 -- yet it printed "estimated cost up to 60 sessions"
# against a true ceiling of 12, at the exact moment that number exists to let
# the founder say no. Clamping here also makes the per-dispatch counter honest
# ("burst 1/2", not "burst 1/10").
#
# Clamped HERE and not before LOOKAHEAD: that window is deliberately TARGET*3+2
# because disjointness REJECTS candidates, and asking 1-for-1 would end the
# pass with slots free. The window is what we ask for; TARGET is what can land.
[ "$TARGET" -gt "$N_CANDIDATES" ] && TARGET="$N_CANDIDATES"

SCRATCH="$(mktemp -d)"      # freed by cleanup(), together with the lock
LIVE_SET="$SCRATCH/live-set"
: > "$LIVE_SET"
MAGNETS="$SCRATCH/magnets"
magnet_patterns > "$MAGNETS"
OURS="$SCRATCH/ours"
: > "$OURS"

# ONE READ of one issue's DoR per pass, cached. The union below is rebuilt for
# EVERY candidate -- that is the fix -- and re-fetching each live run's DoR from
# Linear each time would turn one network call into a dozen. A DoR does not
# change mid-pass; the LIST of live runs is the thing that has to be fresh, and
# that comes from pgrep, which costs nothing.
SET_FILE=""
SET_RC=0
SET_WHY=""
set_for_issue() {  # set_for_issue <issue>  -> SET_FILE, SET_RC, SET_WHY
  SET_FILE="$SCRATCH/set-$1"
  if [ -f "$SCRATCH/rc-$1" ]; then
    SET_RC="$(cat "$SCRATCH/rc-$1")"
    SET_WHY="$(cat "$SCRATCH/why-$1")"
    return 0
  fi
  SET_WHY="$(fileset_known "$1" "$SET_FILE")"; SET_RC=$?
  printf '%s' "$SET_RC" > "$SCRATCH/rc-$1"
  printf '%s' "$SET_WHY" > "$SCRATCH/why-$1"
  return 0
}

# Say a per-issue note ONCE per pass. The union is rebuilt per candidate, so an
# unconditional note would repeat the same line N times and bury the
# per-candidate skips under it. Noise is how a real signal gets missed.
note_once() {  # note_once <issue> <message>
  [ -f "$SCRATCH/noted-$1" ] && return 0
  : > "$SCRATCH/noted-$1"
  say "$2"
}

# THE UNION OF EVERY FILE SET THAT IS LIVE RIGHT NOW, REBUILT PER CANDIDATE.
# Frozen once per pass, this was the hole (PR #36 r4 finding 1): issue_is_live()
# and external_live() both re-read pgrep, so a pass could sit in the slot wait,
# watch one run end and another BEGIN, and still test overlap against the set it
# built minutes earlier. Two agents in one file, reported as `skipped 0` -- the
# exact collision this whole script exists to prevent, certified clean.
#
# OURS is folded in because a run we launched a moment ago may not be in the
# process table yet, and because a finished-but-ours run still owns the files it
# just wrote. Over-counting there costs one extra skip with a named reason;
# under-counting costs a conflicted PR.
#
# PASS_UNKNOWN is one variable for one fact: something is running whose files we
# cannot name, so nothing may run beside it. It now falls out of the rebuild
# rather than being set by hand in two places, so a solo run we launch ourselves
# holds the board by the same rule as one we found.
LIVE_NOW=0
PASS_UNKNOWN=""
UNREADABLE_LIVE=0
refresh_live_set() {
  : > "$LIVE_SET"
  LIVE_NOW=0
  PASS_UNKNOWN=""
  UNREADABLE_LIVE=0
  for LI in $( { live_issues; cat "$OURS"; } | sort -u ); do
    LIVE_NOW=$(( LIVE_NOW + 1 ))
    set_for_issue "$LI"
    case "$SET_RC" in
      0) cat "$SET_FILE" >> "$LIVE_SET" ;;
      1) PASS_UNKNOWN="$LI"
         note_once "$LI" "note: the live run $LI has an unknown file set ($SET_WHY); nothing may run alongside it" ;;
      *) UNREADABLE_LIVE=1
         note_once "$LI" "note: the file set for the live run $LI is UNREADABLE; holding every candidate" ;;
    esac
  done
}

# Why this candidate may not go, or nothing at all. Called TWICE per candidate
# -- once before the slot wait as a cheap early-out, once after it as the
# authoritative answer -- and it is one function on purpose: two readers of "may
# this run" with drifting semantics is the defect class this repo keeps finding.
# Reads the globals refresh_live_set just wrote; writes none, because it is
# called inside a command substitution and a subshell would swallow them.
candidate_blocked() {  # candidate_blocked <issue> <set-rc> <why> <set-file>
  if [ "$UNREADABLE_LIVE" -eq 1 ]; then
    printf 'a live run has an UNREADABLE file set, so no overlap check is trustworthy right now'
    return 0
  fi
  if [ -n "$PASS_UNKNOWN" ]; then
    printf '%s is running with an unknown file set, so nothing may run alongside it; still ready for the next pass' "$PASS_UNKNOWN"
    return 0
  fi
  if [ "$2" -eq 1 ]; then
    # FAIL CLOSED MEANS NOT IN PARALLEL -- NOT NEVER. An unknown file set
    # intersects everything, and everything is EMPTY when nothing is live. So it
    # runs, alone. Refusing it outright is what made this gate reject 51 of 55
    # real ready issues and dispatch zero, forever.
    # The reason carries its own fix (add a list / backtick the paths), so this
    # line must not staple a second one on: the two unknown cases need
    # different edits and a generic "add the paths" is wrong for one of them.
    [ "$LIVE_NOW" -gt 0 ] && printf '%s -- so it can only run ALONE, and something is already running (live=%s); still ready for the next pass' "$3" "$LIVE_NOW"
    return 0
  fi
  OVERLAP="$(first_overlap "$LIVE_SET" "$4")"
  [ -n "$OVERLAP" ] && printf 'its file set overlaps a live run on %s' "$OVERLAP"
  return 0
}

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

# The live runs that are NOT ours, read FRESH. The runs we just launched also
# match the pgrep pattern, so a plain live count here would double-count them
# against our own cap -- hence the exclusion by issue id rather than a simpler
# count.
external_live() {
  if [ -s "$OURS" ]; then
    live_issues | grep -vxF -f "$OURS" | grep -c . || true
  else
    live_issues | grep -c . || true
  fi
}

# How long to sit waiting for a busy slot before giving up on this pass.
# A burst is a founder standing at the terminal who asked for N runs, so waiting
# is the point. The heartbeat is a launchd job that re-fires every 900s, so a
# 10-minute block there would stack overlapping ticks; it gives up fast and
# retries on the next beat, which costs nothing.
if [ "$BURST" -gt 0 ]; then
  SLOT_WAIT="${KIPI_DISPATCH_SLOT_WAIT:-600}"
else
  SLOT_WAIT="${KIPI_DISPATCH_SLOT_WAIT:-60}"
fi
SLOTS_FULL=0

# Every candidate we do not dispatch says why. "dispatched 3 of 10" with no
# reasons reads as "there were only 3", which is the silent-truncation failure.
skip() { SKIPPED=$((SKIPPED+1)); say "skip $1: $2"; }

# Wait for a free slot. Polling beats `wait -n`, which needs bash 4.3 and this
# runs under macOS /bin/bash 3.2 under launchd.
#
# RE-READ the live count every iteration, and BOUND the wait. This used to test
# `our_active + LIVE`, where LIVE was the snapshot taken at the top of the pass:
# with live runs already filling --parallel, that condition could never go
# false, so a burst printed its cost estimate and then sat there forever, even
# after the live runs finished. A foreground command that blocks with no output
# and no end is worse than one that says it gave up.
wait_for_slot() {
  WAITED=0
  while [ "$(( $(our_active) + $(external_live) ))" -ge "$SLOTS" ]; do
    if [ "$WAITED" -ge "$SLOT_WAIT" ]; then SLOTS_FULL=1; return 0; fi
    [ "$WAITED" -eq 0 ] && say "waiting for one of $SLOTS slot(s) to free up (up to ${SLOT_WAIT}s)"
    sleep 2; WAITED=$(( WAITED + 2 ))
  done
  return 0
}

for ISSUE in $CANDIDATES; do
  if [ "$SLOTS_FULL" -eq 1 ]; then
    skip "$ISSUE" "every one of the $SLOTS slot(s) was still held after waiting ${SLOT_WAIT}s for a free slot; still ready for the next run"
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

  set_for_issue "$ISSUE"
  CAND_RC="$SET_RC"; CAND_WHY="$SET_WHY"; CAND_SET="$SET_FILE"
  if [ "$CAND_RC" -eq 2 ]; then
    skip "$ISSUE" "$CAND_WHY"
    continue
  fi
  SOLO=0
  [ "$CAND_RC" -eq 1 ] && SOLO=1

  # Cheap early-out: a candidate that ALREADY overlaps is skipped before we
  # spend up to ${SLOT_WAIT}s waiting for a slot it cannot use. Without this, a
  # burst of 5 candidates all overlapping one live run would wait the full
  # timeout five times over -- an hour of a founder's foreground command to
  # reach an answer it had at second zero.
  refresh_live_set
  WHY_BLOCKED="$(candidate_blocked "$ISSUE" "$CAND_RC" "$CAND_WHY" "$CAND_SET")"
  if [ -n "$WHY_BLOCKED" ]; then skip "$ISSUE" "$WHY_BLOCKED"; continue; fi

  wait_for_slot
  if [ "$SLOTS_FULL" -eq 1 ]; then
    skip "$ISSUE" "every one of the $SLOTS slot(s) was still held after waiting ${SLOT_WAIT}s for a free slot; still ready for the next run"
    continue
  fi

  # AND AGAIN, AUTHORITATIVELY. The wait above is the window: it ends precisely
  # BECAUSE the live set changed, and the run that freed the slot is not
  # necessarily the run that is holding it now. Same function, same data, so the
  # two checks cannot disagree -- the second one is simply the one that is true
  # at the moment of launch.
  refresh_live_set
  WHY_BLOCKED="$(candidate_blocked "$ISSUE" "$CAND_RC" "$CAND_WHY" "$CAND_SET")"
  if [ -n "$WHY_BLOCKED" ]; then skip "$ISSUE" "$WHY_BLOCKED"; continue; fi

  # Count BEFORE launching. Counting after would let a crash between the two
  # hand out a free dispatch every heartbeat -- the budget must fail closed.
  # Burst does not touch the counter at all (see the DAILY BUDGET note).
  if [ "$BURST" -eq 0 ]; then
    DISPATCHED_TODAY=$(( DISPATCHED_TODAY + 1 ))
    printf '%s' "$DISPATCHED_TODAY" > "$COUNT_FILE"
    say "dispatching $ISSUE (live=$LIVE_NOW cap=$MAX_CONCURRENT rounds=$MAX_ROUNDS budget=$DISPATCHED_TODAY/$DAILY_MAX)"
  else
    say "dispatching $ISSUE (burst $((DISPATCHED + 1))/$TARGET, at most $SLOTS at once, rounds=$MAX_ROUNDS)"
  fi
  # Quote the REASON rather than restating one of them. A block that names
  # paths the parser cannot take is now also unknown, and telling that operator
  # "its DoR names no files" is a false statement about a file they can read.
  [ "$SOLO" -eq 1 ] && say "  ...ALONE: $CAND_WHY. Nothing may run alongside it until it finishes."

  nohup ./kipi converge --issue "$ISSUE" --max-rounds "$MAX_ROUNDS" \
    > "$HOME/.config/kipi/converge-$ISSUE.log" 2>&1 &
  LAUNCHED_PIDS="$LAUNCHED_PIDS $!"
  # This run is now live for the purposes of every later candidate, including
  # the seconds before the process table shows it. refresh_live_set folds OURS
  # into the union, so this one line is what keeps candidates 2..N honest --
  # without it the whole change is decorative.
  printf '%s\n' "$ISSUE" >> "$OURS"
  DISPATCHED=$(( DISPATCHED + 1 ))

  say "dispatched $ISSUE"
done

say "done: dispatched $DISPATCHED, skipped $SKIPPED, of $N_CANDIDATES candidate(s) examined (${READY_TOTAL:-an unknown number of} ready on the board)"

# A pass that dispatched NOTHING while nothing was live and the board was not
# empty. After the rules above, the only way to reach this is that the file sets
# could not be READ: an unknown set now runs alone, and an overlap needs a live
# run to overlap WITH. So it is a fault, and it had no page site -- the liveness
# beacon kept reporting a healthy loop that was doing no work, and the only
# other signal was a log nobody reads.
#
# Deliberately NOT paged when something is live: a busy loop holding candidates
# back is the gate working, not the gate stuck. Read FRESH, not from the count
# taken at the top: a converge that started mid-pass is exactly why every
# candidate was held, and paging "nothing is running" about it would be a lie
# the operator gets woken for.
LIVE_AT_END="$(live_converges)"; LIVE_AT_END="${LIVE_AT_END:-0}"
if [ "$BURST" -eq 0 ] && [ "$DISPATCHED" -eq 0 ] && [ "$LIVE" -eq 0 ] && [ "$LIVE_AT_END" -eq 0 ] && [ "$N_CANDIDATES" -gt 0 ]; then
  page_once "$HOME/.config/kipi/dispatch-stuck-$TODAY.paged" \
    "kipi dispatch: ${READY_TOTAL:-several} issue(s) ready, nothing running, and the loop dispatched nothing -- their file sets could not be read. The Linear loop is IDLE, not busy. Do: run \`bash kipi-dispatch.sh --burst 1\` in $REPO and read the skip lines."
fi
exit 0
