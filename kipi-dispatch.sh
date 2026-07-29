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

# MAGNET FILE (sp-f3a2ad81). Nearly every test-adding issue appends one entry to
# capability-manifest.json, so intersecting on it would make almost every pair
# "conflicting" and serialise the board back down to one -- the exact thing this
# change exists to undo. It is exempt from the intersection test.
#
# WHAT THAT EXEMPTION ACTUALLY COSTS (PR #36 r4 finding 1). This used to say the
# exemption "relies on the union-merge rule that already governs" the manifest.
# No such rule exists: `.gitattributes` grants merge=union to exactly one path,
# `.prd-os/receipts.jsonl`, and git reports `merge: unspecified` for the
# manifest. Worse, the cited mechanism could not have worked even if it were
# wired -- union-merge keeps BOTH sides' lines, which is correct for an
# append-only .jsonl ledger and produces INVALID JSON for a .json object.
#
# So the honest statement of the trade, since a false one is how the next person
# reintroduces the conflict: two parallel runs that both append to the manifest
# WILL conflict there, and the second PR to land needs a hand resolve (keep both
# entries, drop the markers). That is one hand-resolved merge against
# serialising the entire board, and it is the reason the waiver is ANNOUNCED at
# dispatch time (see magnet_holders below) rather than discovered in a red PR.
#
# MAGNET CONFLICT IS UNMITIGATED. That marker is load-bearing, not decoration:
# case 30a reads `git check-attr merge` for the magnet and requires this line
# when git says `unspecified` -- and requires it GONE the moment a real merge
# strategy is wired, so the two can never drift again in either direction.
# Wiring one (a JSON-aware merge driver, since union is wrong here) is a founder
# decision on `.gitattributes`, outside this issue's Files list: sp-d11d902c.
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
                 concurrency cap, KIPI_DISPATCH_MAX). Only means anything
                 WITH --burst; on its own it is refused, not treated as a tick.
USAGE
}

BURST=0
BURST_GIVEN=0
PARALLEL=""
PARALLEL_GIVEN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --burst)    shift; BURST="${1:-}"; BURST_GIVEN=1 ;;
    --parallel) shift; PARALLEL="${1:-}"; PARALLEL_GIVEN=1 ;;
    -h|--help)  usage; exit 0 ;;
    *) printf 'kipi-dispatch: unknown argument %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
case "$BURST" in ''|*[!0-9]*) printf 'kipi-dispatch: --burst wants a number\n' >&2; exit 2 ;; esac
# EMPTY IS ONLY "USE THE DEFAULT" WHEN THE FLAG WAS NOT TYPED (PR #36 r4 f4).
# `--parallel` with no value produced PARALLEL="" and fell through to the
# default, so a founder who typed a burst-shaped flag got the SCHEDULER's
# behaviour under their own name: a full production tick that launched an agent
# and spent the daily counter. That is what happened during the r4 review. The
# flag-given bit is what separates "not typed" from "typed with nothing".
if [ "$PARALLEL_GIVEN" -eq 1 ]; then
  case "$PARALLEL" in ''|*[!0-9]*) printf 'kipi-dispatch: --parallel wants a number\n' >&2; exit 2 ;; esac
fi
[ "${PARALLEL:-1}" = "0" ] && { printf 'kipi-dispatch: --parallel 0 would dispatch nothing\n' >&2; exit 2; }
# `--burst 0` is not a burst of nothing, it is the internal value for "this is a
# heartbeat tick", so it fell through EVERY `[ "$BURST" -gt 0 ]` branch below: it
# spent the daily counter and wrote the liveness beacon that the beacon's own
# comment says a burst must never write. A founder typing `--burst 0` gets the
# scheduler's behaviour under the founder's name. Refuse it, like --parallel 0.
[ "$BURST_GIVEN" -eq 1 ] && [ "$BURST" = "0" ] && {
  printf 'kipi-dispatch: --burst 0 would dispatch nothing (drop the flag for a heartbeat tick)\n' >&2; exit 2; }
# `--parallel N` ALONE IS THE THIRD SPELLING OF THE SAME MISTAKE (PR #36 r6 f2).
# `--parallel` with no value and `--burst 0` are both refused above, for the
# stated reason that a founder who typed a burst-shaped flag must not get the
# SCHEDULER's behaviour under their own name. `--parallel 2` with no --burst
# parsed cleanly and did exactly that: a full production tick that spent the
# daily counter, wrote the liveness beacon a burst must never write (it masks a
# dead launchd job and fires a false RESUMED later), and paged. It is also
# incoherent on its own -- it moves SLOTS while TARGET stays the heartbeat's
# free-slot count -- so there is no behaviour here worth keeping.
[ "$PARALLEL_GIVEN" -eq 1 ] && [ "$BURST_GIVEN" -eq 0 ] && {
  printf 'kipi-dispatch: --parallel only means something with --burst (use `--burst N --parallel %s`, or drop the flag for a heartbeat tick)\n' "$PARALLEL" >&2
  exit 2; }

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
#
# NO PIPE INTO grep -q, and that is the point rather than a style preference.
# main's PR #39 review found this same shape one layer down: `writer | grep -q`
# under `set -o pipefail` fires only SOMETIMES -- grep -q exits the instant it
# matches, the writer then takes SIGPIPE and dies 141, and pipefail makes 141 the
# status of the whole pipeline, so the `if` does not run its body. Here that
# inversion reports a LIVE issue as free and starts a second converge on it,
# which is the one-worktree fight this check exists to prevent.
#
# It was masked, not absent: the `|| true` inside live_issues swallows the 141,
# so this guard's correctness rested on an unrelated line someone could
# reasonably delete. Measured rather than reasoned about -- the same pipeline
# without that `|| true` returns 141 five times out of five
# (.pr36rev7/sigpipe-probe.sh). A snapshot plus bash's own pattern match removes
# the pipeline, so there is nothing left to SIGPIPE and nothing for pipefail to
# poison. Exact-line containment, so a live ASK-15 does not answer for ASK-151
# (cases 31g/31h).
issue_is_live() {
  local live
  live="$(live_issues)"
  case $'\n'"$live"$'\n' in
    *$'\n'"$1"$'\n'*) return 0 ;;
  esac
  return 1
}

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


def _is_real_file(token):
    """Does this token name a file that EXISTS in the repo right now?

    A dot-extension is a spelling; existing on disk is a fact. The extension
    rule alone let the repo-root `kipi` CLI through both nets at once (PR #36
    r4 finding 3): _extract_paths drops any token with no `/` and no `.`, and
    the missed-token guard skipped it for the same reason, so two issues both
    editing it dispatched in parallel and the pass reported `skipped 0`.

    isFILE, not isdir, on purpose: a DoR that says "under the `q-system`
    subtree" is discussing a directory, which is the same signal the trailing
    slash carries in emit(). A directory is not a file two agents can collide
    in, and counting one would serialise the board on a word.
    """
    p = os.path.expanduser(token)
    if not os.path.isabs(p):
        if not _repo:
            return False
        p = os.path.join(_repo, p)
    try:
        return os.path.isfile(p)
    except OSError:
        return False

# AN EXTENSIONLESS NAME NEEDS THE MARKUP THAT SAYS "THIS IS A LITERAL", ALONE.
# Measured on the live board before shipping: accepting any real-file token
# flipped ASK-133 and ASK-135 from shareable to run-alone, both on `kipi` -- and
# in both DoRs it is `kipi update` / `kipi check`, a COMMAND named inside the
# Files block, not a file either issue edits. 2 of 8 shareable issues lost to a
# false trip is the same board-serialising over-enforcement round 3 already cost
# this file, arriving through a smaller door.
#
# A dotted name carries its own evidence (`foo.sh` is a file wherever it sits).
# A bare word does not, so it earns the real-file test only as a span of its
# own: `kipi` yes, `kipi update` no, and bare prose `kipi` no. Multi-word spans
# lose nothing -- any file inside one is dotted and already caught above.
_SPAN_RE = re.compile(r"`([^`]+)`")
_STRIP = "`*_|\"'"
standalone_spans = set()
for _s in _SPAN_RE.finditer(value):
    _t = _s.group(1).strip()
    if _t and len(_t.split()) == 1:
        standalone_spans.add(_t.strip(_STRIP).lstrip("([{<").rstrip(")]}>").rstrip(",;:."))

magnets = set()
for _m in os.environ.get("KIPI_DISPATCH_MAGNETS", "").split():
    magnets.add(normalise(_m))
    magnets.add(_m.rsplit("/", 1)[-1])
basenames = {p.rsplit("/", 1)[-1] for p in seen}

def _parses(token):
    """Would the tokenizer take this spelling, standing alone in a block?"""
    return token in mod._extract_paths("`%s`" % token)


def _fix_advice(token, had_cite):
    """The spelling that WOULD work, or an honest statement that none does.

    PR #36 r6 finding 3: this line used to say "backtick every path there" for
    every shape that trips the guard. The guard also trips on an
    already-backticked standalone span, so the printed fix was already done and
    the operator had nothing to act on -- a fix nobody can follow is the same as
    no reason at all, which is the failure the PARTIAL branch exists to avoid.
    """
    target = token if _parses(token) else None
    if target is None and _parses("./%s" % token):
        target = "./%s" % token
    if target is None:
        return "no spelling of `%s` parses, so nothing in the DoR can let it share the board" % token
    if had_cite:
        return "write it as `%s` there, without the line number, to let it share the board" % target
    if target != token:
        return ("spell it `%s` there (a bare name with no extension is not a path "
                "the parser can take) to let it share the board" % target)
    return "backtick `%s` there to let it share the board" % token


def named_files(text):
    """Every word in the block that is shaped like a FILE, however spelled.

    Yields (token, had_line_number): the second half is what separates "you
    forgot the backticks" from "drop the `:318`", and the advice is wrong
    without it.
    """
    for raw in text.split():
        w = raw.strip("`*_|\"'").lstrip("([{<").rstrip(")]}>").rstrip(",;:.")
        w, n_cite = _CITE_RE.subn("", w)  # `foo.sh:318` is a path plus a line no.
        had_cite = n_cite > 0
        if not w or not mod._PATH_TOKEN_RE.fullmatch(w):
            continue
        # A trailing alphabetic extension is what separates a file from prose
        # that merely contains a dot or a slash: `e.g`, `3.2`, `and/or`, `N/A`
        # and a bare directory name are all rejected here, and none of them
        # would ever be an intersection hit anyway.
        #
        # OR it is a span of its own naming a file that actually exists in this
        # repo. That second test is what covers the extensionless ones (`kipi`,
        # `Makefile`, `LICENSE`), and it is a fact rather than a seventh
        # spelling -- bounded by standalone_spans so a command mention cannot
        # widen it into over-detection (see the measurement note above).
        if not _FILENAME_RE.search(w.rsplit("/", 1)[-1]) \
                and not (w in standalone_spans and _is_real_file(w)):
            continue
        yield w, had_cite

missed = []
for w, had_cite in named_files(value):
    n = normalise(w)
    if n in seen or n in magnets:
        continue
    # A bare basename beside a full path is the same file mentioned twice
    # ("extend `a/b/test-x.sh`; test-x.sh already covers the mutex"), which is
    # a real DoR shape and carries no new file. A basename that is genuinely a
    # DIFFERENT file is the one gap left here, and it is the status quo ante.
    if "/" not in n and n in basenames:
        continue
    missed.append((w, had_cite))

if missed:
    # Nothing on stdout: an incomplete set is worse than no set, because the
    # caller can act on "unknown" and cannot act on "wrong".
    print("PARTIAL: %s" % " ".join(w for w, _ in missed[:3]), file=sys.stderr)
    print("PARTIAL_FIX: %s" % _fix_advice(*missed[0]), file=sys.stderr)
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
  #
  # AND THE FIX IS DERIVED FROM THE TOKEN, NOT A CONSTANT SENTENCE (r6 f3). The
  # old text said "backtick every path there" for every shape, including the
  # already-backticked standalone span that is the guard's commonest real trip --
  # so the printed remedy was already done and the operator had nothing to act
  # on. The parser itself now says which spelling would have worked.
  PARTIAL="$(sed -n 's/^PARTIAL: //p' "$2.err" 2>/dev/null | head -1)"
  if [ -n "$PARTIAL" ]; then
    PARTIAL_FIX="$(sed -n 's/^PARTIAL_FIX: //p' "$2.err" 2>/dev/null | head -1)"
    printf 'its `**Files:**` block names %s but the parser could not take that spelling, so the set would be INCOMPLETE (%s)' \
      "$PARTIAL" "${PARTIAL_FIX:-read the block: one of those paths is spelled in a way the parser cannot take}"
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

# The magnet path this pass is about to WAIVE, or nothing. The mirror of
# first_overlap: same two sets, keeping exactly what that one throws away.
first_magnet_overlap() {  # first_magnet_overlap <fileA> <fileB>
  grep -Fx -f "$1" "$2" 2>/dev/null | grep -xF -f "$MAGNETS" | head -1
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
# mutex learned in ASK-189).
#
# THAT RULE HAD TWO STATES IT COULD NOT CLEAR (PR #36 r4 finding 2), and each
# one turned the whole loop off permanently and silently, which is strictly
# worse than the race:
#
#   no pid file   SIGKILL or power loss in the window between mkdir and the pid
#                 write. The old code called that YOUNG rather than stale -- and
#                 young had no expiry, so it was young forever. LOCK_GRACE gives
#                 young an end: the real window is microseconds, so a minute is
#                 four orders of magnitude of margin.
#   reused pid    a reboot (or pid wraparound) hands the recorded number to an
#                 unrelated process. `kill -0` succeeds, so the holder read as
#                 alive indefinitely. An age fallback alone would paper over
#                 this and stay wrong for the first hour after every reboot, so
#                 the test is what the pid IS RUNNING, not how old the lock is.
#
# Nothing here steals a lock from a live pass: a pid whose command line is this
# script is honoured no matter how old it gets, because two pickers in flight is
# the exact failure the lock exists to prevent. An ancient one that is still
# held is a hung pass -- real, and the only state left with no other signal, so
# it PAGES (once a day) instead of exiting 0 into silence every 900s.
#
# Taken AFTER the beacon on purpose: a tick that gives up because another pass
# holds the lock is still proof of life, and skipping the beat would make a
# healthy loop look dead and fire a false RESUMED page later.
LOCK_DIR="$HOME/.config/kipi/dispatch.lock"
LOCK_GRACE="${KIPI_DISPATCH_LOCK_GRACE:-60}"        # mkdir -> pid write window

# HOW LONG A PASS MAY HOLD THE LOCK BEFORE IT IS CALLED HUNG. Not a constant any
# more (PR #36 r6 finding 1): the constant was BELOW a legitimate hold, so the
# only anti-silence page this loop has fired on the loop WORKING.
#
# The arithmetic the old comment (`> any legitimate hold`) got wrong: the lock is
# taken before the candidate loop and released at exit, so a pass holds it for
# its whole life, and that life is bounded by TARGET x (SLOT_WAIT + the confirm
# window). `--burst 4 --parallel 2` against real converges is 40-90 minutes of
# perfectly healthy work, and 3600s told the founder at 3am that "the Linear loop
# is STOPPED" with a kill-and-rm remediation for it. An alert that fires on the
# normal duration of the feature it guards is the alert training the operator to
# mute it, which costs the real outage its only signal.
#
# So the HOLDER declares its own worst case into the lock (max_hold, written in
# the same breath as the pid) and whoever finds the lock reads it. Derived from
# the same inputs the pass actually uses, never a second copy of the formula --
# two readers of one bound with drifting arithmetic is how this defect got here.
# LOCK_MAX_HOLD stays as the FLOOR: a hang is never detected later than before.
LOCK_MAX_HOLD="${KIPI_DISPATCH_LOCK_MAX_HOLD:-3600}"
# ...and the CEILING, because a file that can silence the loop's only
# anti-silence page is a worse defect than the false positive this fixes. A
# corrupt, absurd, or hand-edited max_hold gets clamped, never obeyed.
LOCK_MAX_HOLD_CEIL="${KIPI_DISPATCH_LOCK_MAX_HOLD_CEIL:-86400}"

# ONE DEFINITION EACH, read here (to declare the ceiling) and again in the
# candidate loop (to do the waiting). Both were defined further down, next to
# their use; computing them twice is the drift this file keeps paying for.
#
# A burst is a founder standing at the terminal who asked for N runs, so waiting
# is the point. The heartbeat is a launchd job that re-fires every 900s, so a
# 10-minute block there would stack overlapping ticks; it gives up fast and
# retries on the next beat, which costs nothing.
if [ "$BURST" -gt 0 ]; then
  SLOT_WAIT="${KIPI_DISPATCH_SLOT_WAIT:-600}"
else
  SLOT_WAIT="${KIPI_DISPATCH_SLOT_WAIT:-60}"
fi
# The per-child liveness window (see the launch block). A test seam, same class
# as SLOT_WAIT: the window is what has to be short in a test.
CONFIRM_SECS="${KIPI_DISPATCH_CONFIRM_SECS:-10}"

# The most candidates this pass can possibly walk. A burst asks for exactly N;
# a tick is bounded by the concurrency cap however the budget narrows it later.
# An OVER-estimate is the safe direction here -- it only ever delays the page.
if [ "$BURST" -gt 0 ]; then
  TARGET_CEILING="$BURST"
else
  TARGET_CEILING="$MAX_CONCURRENT"
fi
HOLD_LIMIT=$(( LOCK_MAX_HOLD + TARGET_CEILING * (SLOT_WAIT + CONFIRM_SECS) ))

# What the pass holding the lock says its own worst case is, clamped. Falls back
# to the constant when the file is absent (a SIGKILLed pass, or a lock written by
# an older build), garbage, or shorter than the floor.
holder_hold_limit() {
  DECL="$(cat "$LOCK_DIR/max_hold" 2>/dev/null || true)"
  case "$DECL" in ''|*[!0-9]*) printf '%s' "$LOCK_MAX_HOLD"; return 0 ;; esac
  # Length first: bash arithmetic on a 30-digit number errors out, and an
  # errored comparison here would read as "not expired" and mute the page.
  [ "${#DECL}" -gt 10 ] && { printf '%s' "$LOCK_MAX_HOLD_CEIL"; return 0; }
  [ "$DECL" -lt "$LOCK_MAX_HOLD" ] && { printf '%s' "$LOCK_MAX_HOLD"; return 0; }
  [ "$DECL" -gt "$LOCK_MAX_HOLD_CEIL" ] && { printf '%s' "$LOCK_MAX_HOLD_CEIL"; return 0; }
  printf '%s' "$DECL"
  return 0
}
# What a holder's command line has to contain. Derived from this file's own
# name rather than hardcoded, so a rename cannot silently turn every live
# holder into a "reused pid" and hand two passes the lock at once.
SELF_TAG="$(basename "${BASH_SOURCE[0]}" .sh)"
LOCK_HELD=0
SCRATCH=""
cleanup() {
  [ -n "$SCRATCH" ] && rm -rf "$SCRATCH"
  [ "$LOCK_HELD" -eq 1 ] && rm -rf "$LOCK_DIR"
  return 0
}
trap cleanup EXIT

# Seconds since the lock was taken, or -1 if it cannot be read. Creating the pid
# file inside the directory updates the directory's own mtime, so this is the
# acquisition time, not merely the mkdir time. BSD then GNU, like the budget-day
# shift above: a silent fallback to "0 seconds old" on Linux would make every
# lock look brand new and reinstate the wedge.
lock_age() {
  LMTIME="$(stat -f %m "$LOCK_DIR" 2>/dev/null || stat -c %Y "$LOCK_DIR" 2>/dev/null || true)"
  case "$LMTIME" in ''|*[!0-9]*) printf '%s' '-1'; return 0 ;; esac
  printf '%s' "$(( $(date +%s) - LMTIME ))"
}

# Sets LOCK_HOLDER / LOCK_AGE / LOCK_STATE in THIS shell. Not a function that
# prints its verdict: the caller needs all three, and reading them back through
# a command substitution is a subshell that discards the other two -- the same
# trap that let the first cut of case 14a pass while the script hung.
LOCK_HOLDER=""
LOCK_AGE=-1
LOCK_STATE="young"
read_lock() {
  LOCK_HOLDER="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  LOCK_AGE="$(lock_age)"
  case "$LOCK_HOLDER" in
    ''|*[!0-9]*)
      if [ "$LOCK_AGE" -ge 0 ] && [ "$LOCK_AGE" -lt "$LOCK_GRACE" ]; then
        LOCK_STATE="young"
      else
        LOCK_STATE="stale"
      fi
      return 0 ;;
  esac
  if ! kill -0 "$LOCK_HOLDER" 2>/dev/null; then
    LOCK_STATE="stale"
    return 0
  fi
  # Alive. Is it US, or a number handed to something else? An EMPTY ps answer is
  # not evidence of reuse -- it is ps failing -- so that case stays "held".
  # Fail-safe on the side that never puts two pickers in flight.
  HOLDER_CMD="$(ps -o args= -p "$LOCK_HOLDER" 2>/dev/null | head -1)"
  if [ -n "$HOLDER_CMD" ] && ! printf '%s' "$HOLDER_CMD" | grep -q "$SELF_TAG"; then
    LOCK_STATE="stale"
    return 0
  fi
  LOCK_STATE="held"
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
  read_lock
  if [ "$LOCK_RECLAIMS" -lt 2 ] && [ "$LOCK_STATE" = "stale" ]; then
    say "note: clearing a dispatch lock no live pass owns (pid ${LOCK_HOLDER:-none recorded}, ${LOCK_AGE}s old)"
    rm -rf "$LOCK_DIR"
    LOCK_RECLAIMS=$(( LOCK_RECLAIMS + 1 ))
    continue
  fi
  if [ "$LOCK_TRIES" -ge "$LOCK_WAIT" ]; then
    # Not a fault and not an empty board: another pass is doing this work right
    # now. Exit 0, no page -- paging here would cry wolf on the loop WORKING.
    say "skip: another dispatch pass is already picking (lock held by pid ${LOCK_HOLDER:-unknown}, ${LOCK_AGE}s old)"
    # ...unless it has been "right now" for longer than a working pass CAN hold
    # it. Then the loop is off, every tick exits 0, and the liveness beacon above
    # still reports healthy -- the silence this whole block exists to end.
    # Stealing it would be the race, so this pages a human instead, once per day
    # like every other standing fault.
    #
    # Against the HOLDER's declared ceiling, not a constant (r6 f1): a burst that
    # is legitimately 90 minutes into its work is not hung, and telling the
    # founder it is, at 3am, with a kill-and-rm, is how this alert lost its job.
    HELD_LIMIT="$(holder_hold_limit)"
    if [ "$LOCK_AGE" -ge "$HELD_LIMIT" ]; then
      page_once "$HOME/.config/kipi/dispatch-lockheld-$TODAY.paged" \
        "kipi dispatch: a dispatch pass (pid ${LOCK_HOLDER:-unknown}) has held the pick lock for $(( LOCK_AGE / 60 )) min -- past the $(( HELD_LIMIT / 60 )) min a working pass can take -- so no issue has been picked up since. The Linear loop is STOPPED. Do: \`ps -p ${LOCK_HOLDER:-?}\` in $REPO; if it is not really working, kill it, then \`rm -rf $LOCK_DIR\`. Converge runs it already started have their own session and keep going."
    fi
    exit 0
  fi
  sleep 1; LOCK_TRIES=$(( LOCK_TRIES + 1 ))
done
# Owned from the mkdir, not from the pid write. Claiming it one line later left
# a normal (non-SIGKILL) exit inside that window leaking a pid-less lock dir --
# the very state above. Now only a kill -9 or a power cut can reach it.
LOCK_HELD=1
printf '%s' "$$" > "$LOCK_DIR/pid"
# IN THE SAME BREATH AS THE PID, and that is not tidiness. Creating a file inside
# the lock directory updates the DIRECTORY's mtime, which is what lock_age() reads
# as the acquisition time. Writing this later -- after `kipi work`, say, where the
# TARGET is finally known -- would silently reset the lock's age by however long
# the picker took, so the ceiling is computed from values available at parse time
# instead. Same moment, one age, no second meaning for it.
printf '%s' "$HOLD_LIMIT" > "$LOCK_DIR/max_hold"

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

# Which live runs also name <path>. Reads the sets refresh_live_set already
# cached, so naming the other side of a waived magnet overlap costs no extra
# Linear call. LIVE_SET is a UNION with no issue labels on it, and "it overlaps
# a live run" without saying which one is a report nobody can act on.
magnet_holders() {  # magnet_holders <path>
  for LI in $( { live_issues; cat "$OURS"; } | sort -u ); do
    [ -f "$SCRATCH/set-$LI" ] && grep -qxF "$1" "$SCRATCH/set-$LI" && printf '%s ' "$LI"
  done
  return 0
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
# A child that was launched and died. Separate from DISPATCHED because the two
# answer different questions: how much work started, and whether the launcher
# itself is broken. The exit code comes from this one.
DIED=0

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

# SLOT_WAIT is defined once, up in the lock block, because the lock's own
# hold ceiling is derived from it -- a second copy here is the drift that made
# the ceiling wrong in the first place (r6 f1).
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

  # SAY WHAT THE WAIVER BUYS AND WHAT IT COSTS, at the moment it is spent. The
  # magnet exemption is the one place this gate KNOWINGLY dispatches two runs
  # into one file, and it used to do it silently on the strength of a merge rule
  # that does not exist. Named runs and a named path, so the conflict is an
  # expected event with its resolution attached rather than a red PR at 3am.
  # Log/stdout only, never a page: it is the gate working as designed.
  MAGNET_HIT="$(first_magnet_overlap "$LIVE_SET" "$CAND_SET")"
  if [ -n "$MAGNET_HIT" ]; then
    say "  ...WAIVED: $ISSUE and $(magnet_holders "$MAGNET_HIT")both touch $MAGNET_HIT (magnet file, exempt from the disjointness test). Expect a git CONFLICT there on the second PR to land; resolve it by keeping both entries."
  fi

  # THE CHILD NEEDS ITS OWN SESSION, AND THIS IS NOT A STYLE CHOICE. This was
  # `nohup ... & disown`, which is right in an interactive shell and WRONG under
  # launchd: launchd reaps the job's whole process group when the main process
  # exits, and nohup only blocks SIGHUP, so the converge died the instant this
  # pass returned -- invisibly, because the redirect had already created the log
  # file and `dispatched X` still printed. main's PR #39 proved and fixed that on
  # the SINGLE-issue tail that this branch rewrote into the loop above, so the
  # merge either carries it forward or silently undoes it. All 91 cases from the
  # earlier rounds stayed green while it was undone; case 31a is the pin.
  #
  # macOS ships no setsid(1), so python3 is how setsid(2) gets called. A new
  # session means a new process group with no controlling terminal, which is
  # outside the group launchd tears down.
  #
  # APPENDED with a run boundary, never truncated. This log is the file the
  # failure page sends the operator to, and `>` erased the previous run's
  # evidence on every re-dispatch of the same issue. Case 31b.
  CONVERGE_LOG="$HOME/.config/kipi/converge-$ISSUE.log"
  printf '\n===== dispatch %s  %s  rounds=%s =====\n' \
    "$ISSUE" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$MAX_ROUNDS" >> "$CONVERGE_LOG"
  CHILD_PID="$(python3 - "$CONVERGE_LOG" \
           ./kipi converge --issue "$ISSUE" --max-rounds "$MAX_ROUNDS" <<'PY'
import subprocess, sys
log_path, argv = sys.argv[1], sys.argv[2:]
# Append, never truncate: a re-dispatch must not erase the previous run's log.
log = open(log_path, "ab", buffering=0)
p = subprocess.Popen(argv, stdout=log, stderr=log, start_new_session=True)
# The pid is the whole point. The pass has to watch THE CHILD IT LAUNCHED, not
# "some converge for this issue" -- otherwise an unrelated live run answers on a
# dead child's behalf, which is the silent-success hole one layer up.
print(p.pid, flush=True)
PY
)"; LAUNCH_RC=$?

  # PROVE IT IS ALIVE BEFORE CLAIMING IT. The budget slot is spent by this line,
  # so a death reported as a dispatch costs a slot and does no work while the
  # loop looks healthy. Checked every second rather than once, because a child
  # that falls over at t+4 is most of how this actually fails.
  # CONFIRM_SECS (a test seam, cases 31c-31f) is defined once in the lock block:
  # the lock's hold ceiling counts this window per candidate, so the two must be
  # the same number by construction and not by coincidence.
  ALIVE=0
  case "$CHILD_PID" in
    ''|*[!0-9]*) ALIVE=0 ;;
    *)
      if [ "$LAUNCH_RC" -eq 0 ]; then
        ALIVE=1
        CONFIRMED=0
        while [ "$CONFIRMED" -lt "$CONFIRM_SECS" ]; do
          kill -0 "$CHILD_PID" 2>/dev/null || { ALIVE=0; break; }
          sleep 1
          CONFIRMED=$(( CONFIRMED + 1 ))
        done
      fi
      ;;
  esac

  if [ "$ALIVE" -eq 0 ]; then
    # NOT counted as dispatched and NOT added to OURS: nothing is live for this
    # issue, so a later candidate must not be held back by a ghost. And the pass
    # STOPS -- an instant death is systemic (launchd reaping, a broken `kipi`, a
    # worktree already held), so launching the next candidate would spend more
    # budget on the same fault.
    say "DISPATCH DIED: $ISSUE was launched but no converge process is alive after ${CONFIRM_SECS}s; the budget slot is spent"
    page_once "$HOME/.config/kipi/dispatch-died-$TODAY.paged" \
      "kipi dispatch: $ISSUE was launched but died immediately -- the loop is spending budget and doing no work. Do: read $CONVERGE_LOG and check whether launchd is reaping the child."
    DIED=1
    break
  fi

  LAUNCHED_PIDS="$LAUNCHED_PIDS $CHILD_PID"
  # This run is now live for the purposes of every later candidate, including
  # the seconds before the process table shows it. refresh_live_set folds OURS
  # into the union, so this one line is what keeps candidates 2..N honest --
  # without it the whole change is decorative.
  printf '%s\n' "$ISSUE" >> "$OURS"
  DISPATCHED=$(( DISPATCHED + 1 ))

  say "dispatched $ISSUE (confirmed running)"
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
#
# DIED is excluded because this page would then be a LIE about a real fault: a
# child that was launched and died means the file sets were read fine, and the
# operator would get two pages for one fault with the second one sending them to
# look at DoR parsing. The death has its own page, naming the converge log.
if [ "$BURST" -eq 0 ] && [ "$DISPATCHED" -eq 0 ] && [ "$DIED" -eq 0 ] && [ "$LIVE" -eq 0 ] && [ "$LIVE_AT_END" -eq 0 ] && [ "$N_CANDIDATES" -gt 0 ]; then
  page_once "$HOME/.config/kipi/dispatch-stuck-$TODAY.paged" \
    "kipi dispatch: ${READY_TOTAL:-several} issue(s) ready, nothing running, and the loop dispatched nothing -- their file sets could not be read. The Linear loop is IDLE, not busy. Do: run \`bash kipi-dispatch.sh --burst 1\` in $REPO and read the skip lines."
fi

# NON-ZERO ON A DEAD LAUNCH, and the summary above still prints first so the
# report stays truthful about how much work started. launchd runs this on
# StartInterval with no KeepAlive, so a non-zero exit lands in dispatch.err and
# the next tick comes at the normal interval -- no restart storm.
[ "$DIED" -eq 1 ] && exit 1
exit 0
