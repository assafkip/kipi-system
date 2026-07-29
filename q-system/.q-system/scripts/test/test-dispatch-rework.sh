#!/usr/bin/env bash
# Reproducer + acceptance criterion for ASK-245: "an issue whose PR went red is
# never picked up again, so In Progress only grows".
#
# THE DEFECT
# ----------
# `ready()` in linear-worker.sh returns backlog/unstarted only. An issue flips to
# In Progress the moment a worker takes it, so from that instant it excludes
# itself from every future heartbeat. kipi-dispatch.sh documents this as
# loop-exit #5 and it is correct as a CONCURRENCY guard -- it doubles as a
# PERMANENT one. converge already knows how to rework a red PR; that mechanism
# has no trigger once the run ends.
#
# Measured 2026-07-29: 5 PRs stranded this way (#40 ASK-223, #36 ASK-225,
# #35 ASK-226, #34 ASK-221, #23 ASK-210) -- red validate or red
# kipi/reviewer-approved, In Progress, nothing picking them back up.
#
# WHY THESE CASES DRIVE THE REAL SCRIPTS
# --------------------------------------
# Part A copies linear-worker.sh into a sandbox next to a FAKE linear-sync.py and
# runs its real picker against canned Linear rows. The classification under test
# is the picker's own python, not a re-implementation of it -- a grep for the
# word "rework" in the source would pass on a script that never emits a
# candidate. Case A0 asserts the copy is byte-identical to the shipped file, so
# the suite cannot quietly grade a stale copy.
#
# Part B drives kipi-dispatch.sh for real against a `kipi` stub whose `work`
# output is the canned dry line. Selection is a side effect (a converge process,
# a spent budget slot, a log line), so every assertion reads one of those back.
#
# Isolation: HOME / KIPI_SKEL / KIPI_STATE_DIR / KIPI_REPO all point inside a
# temp dir; gh and the notifier are stubbed. `git` and `python3` stay REAL --
# the picker's own python and real refs are the subject.
set -uo pipefail

PASS=0; FAIL=0
ok()  { printf '  PASS %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; FAIL=$((FAIL + 1)); }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expected [$3] got [$2]"; fi; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# FOUR levels up: test -> scripts -> .q-system -> q-system -> repo root.
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
WORKER="$REPO_ROOT/q-system/.q-system/scripts/linear-worker.sh"
DISPATCH="$REPO_ROOT/kipi-dispatch.sh"
LIB="$REPO_ROOT/q-system/.q-system/scripts/pr-verdict-lib.sh"
[ -f "$WORKER" ]   || { echo "FATAL: linear-worker.sh not found at $WORKER" >&2; exit 1; }
[ -f "$DISPATCH" ] || { echo "FATAL: kipi-dispatch.sh not found at $DISPATCH" >&2; exit 1; }
[ -f "$LIB" ]      || { echo "FATAL: pr-verdict-lib.sh not found at $LIB" >&2; exit 1; }

REAL_GIT="$(command -v git)" || { echo "FATAL: git not on PATH" >&2; exit 1; }

# A UNIQUE issue id per run, for the same reason test-dispatch-liveness.sh uses
# one: every process-table assertion here is GLOBAL, so a hardcoded id lets two
# concurrent runs of the fleet's suite see each other's decoys.
SUF="$$"
FRESH="ASK-8$SUF"     # backlog, the fresh-work set
STUCK="ASK-9$SUF"     # started, the rework set

WORK="$(mktemp -d)"
trap 'pkill -f "$WORK/converge.sh" 2>/dev/null; rm -r -- "$WORK" 2>/dev/null' EXIT
unset KIPI_LINEAR_CLAIMS KIPI_SESSION_ID CLAUDE_SESSION_ID 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }

# `grep -c` prints 0 AND exits 1 on no match, so the obvious `|| echo 0` emits
# TWO zeros and every page-count check compares against garbage.
pages_for() {  # pages_for <issue> -> how many pages mention it
  local n
  n="$(grep -c -- "$1" "$WORK/pages.txt" 2>/dev/null)" || n=0
  printf '%s' "${n:-0}"
}

echo "test-dispatch-rework.sh"

# ===========================================================================
# PART A -- the picker: does a started issue become a REWORK candidate?
# ===========================================================================
SBOX="$WORK/scripts"; mkdir -p "$SBOX" "$WORK/home" "$WORK/bin"
cp "$WORKER" "$SBOX/linear-worker.sh"
cp "$LIB"    "$SBOX/pr-verdict-lib.sh"

# --- A0. the copy under test is the shipped file ---------------------------
# Without this the whole of Part A could pass against a stale copy and nobody
# would know the shipped worker still had the bug.
if cmp -s "$WORKER" "$SBOX/linear-worker.sh"; then
  ok "A0 the worker under test is byte-identical to the shipped one"
else
  bad "A0 the worker under test is byte-identical to the shipped one" "cp did not reproduce it"
fi

# The FAKE Linear client. `graphql` is the only symbol the picker imports from
# linear-sync.py, and the two queries are told apart by "teams(" -- the team
# lookup has it, the issue page does not (`team:{id:...}` inside a filter).
cat > "$SBOX/linear-sync.py" <<'PY'
import json, os


def graphql(query, variables):
    if "teams(" in query:
        return {"teams": {"nodes": [{"id": "TEAM"}]}}
    rows = json.load(open(os.environ["KIPI_TEST_ISSUES"]))
    return {"issues": {"nodes": rows,
                       "pageInfo": {"hasNextPage": False, "endCursor": None}}}
PY

# gh ANSWERS A REAL QUESTION NOW. Since PR #43 review round 3 the dry path asks
# it "does this branch have an OPEN PR", so a stub that exits 0 saying nothing
# would mean "no PR" for every candidate and quietly turn Part A green by
# announcing nothing at all. Two files drive it, so a case states its world
# instead of the stub deciding:
#   $WORK/gh-open-branches  one branch per line -> that branch has an open PR
#   $WORK/gh-fail           exists              -> gh itself is down (exit 1)
cat > "$WORK/bin/gh" <<EOF
#!/usr/bin/env bash
[ -f "$WORK/gh-fail" ] && { echo "gh: could not connect to github.com" >&2; exit 1; }
head=""
while [ \$# -gt 0 ]; do
  [ "\$1" = "--head" ] && { shift; head="\$1"; }
  shift
done
grep -qx -- "\$head" "$WORK/gh-open-branches" 2>/dev/null && echo 4242
exit 0
EOF
chmod +x "$WORK/bin/gh"
printf '#!/bin/sh\nexit 0\n' > "$WORK/bin/claude"; chmod +x "$WORK/bin/claude"
cat > "$WORK/notify.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$WORK/pages.txt"
EOF
chmod +x "$WORK/notify.sh"

# A real skeleton with a real reachable origin: the worker fetches before it
# picks anything, and a fetch failure would stop the run at exit 9.
git init -q --bare "$WORK/origin"
git -C "$WORK/origin" symbolic-ref HEAD refs/heads/main
git init -q "$WORK/skel"
G -C "$WORK/skel" commit -q --allow-empty -m c1
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "$WORK/origin"
git -C "$WORK/skel" push -q -u origin main

DOR='## Definition of Ready

### Outcome
something'

# row <identifier> <state-type> <label> <with-dor:1|0>
row() {
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import json, sys
ident, stype, label, dor = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
print(json.dumps({
    "id": ident, "identifier": ident, "title": "t",
    "description": "## Definition of Ready\n\n### Outcome\nx" if dor == "1" else "just a note",
    "state": {"name": stype, "type": stype},
    "project": {"name": "p"},
    "labels": {"nodes": [{"name": n} for n in label.split(",") if n]},
}))
PY
}

fixture() {  # fixture <row-json>...
  python3 - "$@" > "$WORK/issues.json" <<'PY'
import json, sys
print(json.dumps([json.loads(a) for a in sys.argv[1:]]))
PY
}

run_worker() {  # run_worker  -> dry output on stdout
  ( cd "$WORK/skel" && HOME="$WORK/home" PATH="$WORK/bin:$PATH" \
      KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state" \
      KIPI_NOTIFY="$WORK/notify.sh" KIPI_TEST_ISSUES="$WORK/issues.json" \
      bash "$SBOX/linear-worker.sh" 2>&1 )
}

reset_worker_state() {
  rm -r -- "$WORK/state" 2>/dev/null; mkdir -p "$WORK/state"
  # The default world: the rework candidate HAS an open PR. Every pre-existing
  # case assumed that implicitly (it is the only state the DoR calls a
  # candidate); it is now written down so the cases that vary it can say so.
  printf 'sana/%s\n' "$(echo "$STUCK" | tr 'A-Z' 'a-z')" > "$WORK/gh-open-branches"
  rm -f -- "$WORK/gh-fail"
  : > "$WORK/pages.txt"
}

# --- A1. THE REGRESSION: a started owner:sana issue with a DoR is a candidate
reset_worker_state
fixture "$(row "$STUCK" started owner:sana 1)"
A1="$(run_worker)"

if printf '%s' "$A1" | grep -q "\[dry\] would rework $STUCK"; then
  ok "A1 a started owner:sana issue with a DoR is announced as a rework candidate"
else
  bad "A1 a started owner:sana issue with a DoR is announced as a rework candidate" \
    "the picker returned nothing for it -- an issue that went In Progress can never be re-entered. Output: $(printf '%s' "$A1" | tail -3 | tr '\n' ' ')"
fi

# --- A2. it is NOT announced as fresh work ---------------------------------
# The sets are disjoint. Folding a started issue into `ready` would send it down
# the fresh-work path, which cuts a worktree from origin/main and would blow away
# the PR's commits (linear-worker.sh:730, the BASE block).
if printf '%s' "$A1" | grep -q "\[dry\] would work $STUCK"; then
  bad "A2 a rework candidate is kept out of the fresh-work set" \
    "it was announced as fresh work, which would cut its worktree from origin/main"
else
  ok "A2 a rework candidate is kept out of the fresh-work set"
fi

# --- A3. the fresh-work set is unchanged ------------------------------------
# Without this the fix could 'pass' by reclassifying everything.
reset_worker_state
fixture "$(row "$FRESH" backlog owner:sana 1)"
A3="$(run_worker)"
if printf '%s' "$A3" | grep -q "\[dry\] would work $FRESH"; then
  ok "A3 a backlog issue is still fresh work"
else
  bad "A3 a backlog issue is still fresh work" "$(printf '%s' "$A3" | tail -3 | tr '\n' ' ')"
fi
if printf '%s' "$A3" | grep -q "\[dry\] would rework $FRESH"; then
  bad "A3b a backlog issue is not also a rework candidate" "it appeared in both sets"
else
  ok "A3b a backlog issue is not also a rework candidate"
fi

# --- A4. the owner and DoR filters still hold on the rework set -------------
# A rework candidate that skipped these would hand the loop the founder's own
# issues and issues with no spec.
reset_worker_state
fixture "$(row "$STUCK" started owner:assaf 1)"
if run_worker | grep -q "would rework $STUCK"; then
  bad "A4a owner:assaf is still hands-off in the rework set" "the founder's issue became a candidate"
else
  ok "A4a owner:assaf is still hands-off in the rework set"
fi

reset_worker_state
fixture "$(row "$STUCK" started '' 1)"
if run_worker | grep -q "would rework $STUCK"; then
  bad "A4b an unlabelled issue is not a rework candidate" "an issue nobody owns became a candidate"
else
  ok "A4b an unlabelled issue is not a rework candidate"
fi

reset_worker_state
fixture "$(row "$STUCK" started owner:sana 0)"
if run_worker | grep -q "would rework $STUCK"; then
  bad "A4c an issue with no DoR is not a rework candidate" "an issue with no spec became a candidate"
else
  ok "A4c an issue with no DoR is not a rework candidate"
fi

# --- A5. a completed issue is never a rework candidate ----------------------
reset_worker_state
fixture "$(row "$STUCK" completed owner:sana 1)"
if run_worker | grep -q "would rework $STUCK"; then
  bad "A5 a completed issue is not a rework candidate" "closed work would be reopened forever"
else
  ok "A5 a completed issue is not a rework candidate"
fi

# --- A6. the attempts cap bounds the rework set (loop-exit 7) ---------------
# The DoR: "A permanently-red PR must not consume the allowance forever."
# MAX_ATTEMPTS is 3 in linear-worker.sh.
reset_worker_state
printf '{"%s":{"count":3}}' "$STUCK" > "$WORK/state/linear-worker-attempts.json"
fixture "$(row "$STUCK" started owner:sana 1)"
if run_worker | grep -q "would rework $STUCK"; then
  bad "A6 an issue at MAX_ATTEMPTS drops out of the rework set" \
    "it would be re-dispatched every heartbeat forever, spending a budget slot each time"
else
  ok "A6 an issue at MAX_ATTEMPTS drops out of the rework set"
fi

# --- A7. a run with only rework candidates still exits 0 -------------------
reset_worker_state
fixture "$(row "$STUCK" started owner:sana 1)"
run_worker >/dev/null; RCA=$?
check "A7 a run with only rework candidates exits 0" "$RCA" "0"
check "A7b it pages nobody" "$([ -s "$WORK/pages.txt" ] && echo paged || echo silent)" "silent"

# --- A8. THE ROUND-3 REGRESSION: no OPEN PR means no candidate --------------
# PR #43 review round 3, major. Nothing in this repo moves an issue out of
# `started` when its PR merges, so every issue the loop has ever FINISHED sits In
# Progress forever. Announcing those is not a harmless no-op: the apply loop's
# own `gh pr list --head` is equally empty, so the severity-floor gate is
# skipped, BASE stays origin/main, and the agent is handed the FRESH-WORK prompt
# for work that is already on main -- a duplicate PR and two permanent Linear
# comments, every heartbeat, forever. Observed live 2026-07-29: ASK-150.
reset_worker_state
: > "$WORK/gh-open-branches"          # the PR merged; nothing open on the branch
fixture "$(row "$STUCK" started owner:sana 1)"
A8="$(run_worker)"
if printf '%s' "$A8" | grep -q "would rework $STUCK"; then
  bad "A8a a started issue with NO open PR is not a rework candidate" \
    "it would be re-dispatched forever AS FRESH WORK -- the fresh-work prompt, a worktree cut from origin/main, a duplicate PR and 2 Linear comments per heartbeat"
else
  ok "A8a a started issue with NO open PR is not a rework candidate"
fi
if printf '%s' "$A8" | grep -q "skip rework $STUCK: no OPEN PR"; then
  ok "A8b and the run SAYS why it passed on it, rather than going quiet"
else
  bad "A8b and the run SAYS why it passed on it, rather than going quiet" \
    "silence bought by a filter reads as an empty board: $(printf '%s' "$A8" | tail -3 | tr '\n' ' ')"
fi

# --- A9. a gh failure refuses the path, it does not fall through ------------
# "gh could not be asked" is not the same statement as "there is no PR". Falling
# through would announce the WHOLE pool -- merged issues included -- on exactly
# the run where nothing can be verified.
reset_worker_state
: > "$WORK/gh-fail"
fixture "$(row "$STUCK" started owner:sana 1)"
A9="$(run_worker)"
if printf '%s' "$A9" | grep -q "would rework $STUCK"; then
  bad "A9a a gh failure does not announce an unverified candidate" \
    "the merged-PR population would be announced on exactly the run that cannot check it"
else
  ok "A9a a gh failure does not announce an unverified candidate"
fi
if printf '%s' "$A9" | grep -q "rework: gh could not be asked"; then
  ok "A9b and it says so, so the quiet run is legible"
else
  bad "A9b and it says so, so the quiet run is legible" "$(printf '%s' "$A9" | tail -3 | tr '\n' ' ')"
fi
rm -f -- "$WORK/gh-fail"

# --- A10. MAX_REWORK_DISPATCHES bounds a PR that stays red (loop-exit 7) -----
# The DoR: "A permanently-red PR must not consume the allowance forever... if
# MAX_ATTEMPTS does not cover this path, bound it here and say so." It does not:
# `bump_attempt` fires only when claude exits NON-ZERO, and this path's failure
# mode is an agent that exits 0 with the PR still red. A6 above proves the
# attempts cap works when it is reached -- this proves the cap that CAN be.
reset_worker_state
printf '{"%s":{"rework_dispatches":2}}' "$STUCK" > "$WORK/state/linear-worker-attempts.json"
fixture "$(row "$STUCK" started owner:sana 1)"
A10="$(run_worker)"
if printf '%s' "$A10" | grep -q "would rework $STUCK"; then
  bad "A10a an issue at MAX_REWORK_DISPATCHES drops out of the rework set" \
    "a red PR that the agent cannot fix is re-dispatched every heartbeat forever, spending a budget slot and a converge launch each time"
else
  ok "A10a an issue at MAX_REWORK_DISPATCHES drops out of the rework set"
fi
if printf '%s' "$A10" | grep -q "rework dispatch(es) already"; then
  ok "A10b and it says it is stuck rather than vanishing"
else
  bad "A10b and it says it is stuck rather than vanishing" "$(printf '%s' "$A10" | tail -3 | tr '\n' ' ')"
fi
check "A10c going stuck pages a human" \
  "$(pages_for "$STUCK")" "1"

# --- A11. ...and pages ONCE, not every 15 minutes ---------------------------
# 96 ticks a day is the cry-wolf failure the conflict/drift caps already carry a
# claim_page_once for (founder-notifications.md).
run_worker >/dev/null
run_worker >/dev/null
check "A11 a stuck rework candidate pages once, not per heartbeat" \
  "$(pages_for "$STUCK")" "1"

# --- A12. the COUNT LINE tells the truth ------------------------------------
# The other half of the round-3 major: the fix must land on the REPORT too. The
# line the operator reads at 3am used to say "1 rework candidate(s)" for a pool
# member with a merged PR that would never be a candidate.
reset_worker_state
: > "$WORK/gh-open-branches"
fixture "$(row "$STUCK" started owner:sana 1)"
A12="$(run_worker)"
if printf '%s' "$A12" | grep -q "1 rework candidate(s) (owner:sana"; then
  bad "A12a the pool is not reported as a candidate count" \
    "the log claims a candidate the run then refuses to announce"
else
  ok "A12a the pool is not reported as a candidate count"
fi
if printf '%s' "$A12" | grep -q "0 of 1 rework candidate(s) announced"; then
  ok "A12b the announced count is reported alongside the pool"
else
  bad "A12b the announced count is reported alongside the pool" "$(printf '%s' "$A12" | tail -3 | tr '\n' ' ')"
fi

# ===========================================================================
# PART B -- dispatch selection: does the heartbeat pick a rework candidate?
# ===========================================================================
FAKE_REPO="$WORK/repo"
git init -q --bare "$WORK/origin2"
git -C "$WORK/origin2" symbolic-ref HEAD refs/heads/main
git init -q "$FAKE_REPO"
G -C "$FAKE_REPO" commit -q --allow-empty -m c1
git -C "$FAKE_REPO" branch -M main
git -C "$FAKE_REPO" remote add origin "$WORK/origin2"
git -C "$FAKE_REPO" push -q -u origin main

# A stand-in for converge.sh, named so `converge.sh --issue` matches it in the
# process table exactly as the real one does.
cat > "$WORK/converge.sh" <<'SH'
#!/usr/bin/env bash
sleep 30
SH
chmod +x "$WORK/converge.sh"

# A git wrapper that COUNTS fetches, so "did the rework dispatch refresh
# origin/main first?" is answered by a file and not by a grep of the source.
mkdir -p "$WORK/bin2"
cat > "$WORK/bin2/git" <<EOF
#!/usr/bin/env bash
for a in "\$@"; do [ "\$a" = "fetch" ] && { echo x >> "$WORK/fetches.txt"; break; }; done
exec "$REAL_GIT" "\$@"
EOF
chmod +x "$WORK/bin2/git"

# `work --rework-dispatched` is NOT stubbed: it runs the REAL worker against the
# same ledger Part A reads. That is deliberate -- the round-3 finding is that a
# fix can be locally right and wrong one layer out, so the budget written by the
# dispatcher has to be proved against the reader that consumes it, not against a
# recorder the suite invented. Everything else about `work` stays canned, because
# selection is what Part B is measuring.
make_kipi() {  # make_kipi "<work stdout>"
  cat > "$FAKE_REPO/kipi" <<SH
#!/usr/bin/env bash
case "\$1" in
  work)
    shift
    if [ "\${1:-}" = "--rework-dispatched" ]; then
      exec env HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state" \\
        KIPI_NOTIFY="$WORK/notify.sh" \\
        bash "$SBOX/linear-worker.sh" --rework-dispatched "\${2:-}"
    fi
    printf '%s' '$1'
    ;;
  converge)
    shift
    exec bash "$WORK/converge.sh" "\$@"
    ;;
esac
SH
  chmod +x "$FAKE_REPO/kipi"
}

# What the worker's ledger says about an issue's rework budget.
rework_dispatches() {  # rework_dispatches <issue>
  python3 -c "
import json,sys
try: d=json.load(open('$WORK/state/linear-worker-attempts.json'))
except Exception: d={}
print(d.get(sys.argv[1],{}).get('rework_dispatches',0))" "$1"
}

run_dispatch() {
  ( cd "$FAKE_REPO" && HOME="$WORK/dhome" PATH="$WORK/bin2:$WORK/bin:$PATH" \
      KIPI_REPO="$FAKE_REPO" KIPI_NOTIFY="$WORK/notify.sh" \
      KIPI_DISPATCH_DAILY_MAX="${DMAX:-9}" KIPI_DISPATCH_MAX=999 \
      bash "$DISPATCH" 2>&1 )
}

dlog() { cat "$WORK/dhome/.config/kipi/dispatch.log" 2>/dev/null; }
budget() { cat "$WORK/dhome/.config/kipi/dispatch-count-"* 2>/dev/null || echo 0; }

reset_dispatch_state() {
  rm -r -- "$WORK/dhome" 2>/dev/null
  mkdir -p "$WORK/dhome/.config/kipi"
  date -u +%s > "$WORK/dhome/.config/kipi/dispatch-lastbeat"
  : > "$WORK/pages.txt"; : > "$WORK/fetches.txt"
  pkill -f "$WORK/converge.sh" 2>/dev/null
}

# --- B1. THE REGRESSION: nothing fresh, one rework candidate -> dispatch ----
reset_dispatch_state
make_kipi '0 ready issue
1 rework candidate
[dry] would rework '"$STUCK"'
'
run_dispatch >/dev/null; RCB=$?

check "B1a a rework-only board dispatches, and exits 0" "$RCB" "0"

if dlog | grep -q "dispatching $STUCK"; then
  ok "B1b the dispatcher picked the rework candidate"
else
  bad "B1b the dispatcher picked the rework candidate" \
    "In Progress only grows: it said -- $(dlog | tail -2 | tr '\n' ' ')"
fi

if dlog | grep -q "rework"; then
  ok "B1c the log says this was a rework dispatch, not fresh work"
else
  bad "B1c the log says this was a rework dispatch, not fresh work" "$(dlog | tail -2 | tr '\n' ' ')"
fi

check "B1d a rework dispatch spends the same daily allowance" "$(budget)" "1"

# --- B2. it fetched before dispatching a rework candidate -------------------
# The second cause on the issue: origin/main was 17 commits behind local main, so
# every stranded PR was built on a stale base. Reworking without refreshing
# origin/main reproduces the same conflict.
if [ -s "$WORK/fetches.txt" ]; then
  ok "B2 the rework dispatch refreshed origin before launching"
else
  bad "B2 the rework dispatch refreshed origin before launching" \
    "no git fetch ran; the rework starts from whatever origin/main ref was lying around"
fi

pkill -f "$WORK/converge.sh" 2>/dev/null

# --- B3. fresh work still wins ---------------------------------------------
# Rework is the FALLBACK. Preferring it would starve the backlog.
reset_dispatch_state
make_kipi '1 ready issue
[dry] would work '"$FRESH"'
[dry] would rework '"$STUCK"'
'
run_dispatch >/dev/null

if dlog | grep -q "dispatching $FRESH"; then
  ok "B3a fresh work is preferred over rework"
else
  bad "B3a fresh work is preferred over rework" "$(dlog | tail -2 | tr '\n' ' ')"
fi
if dlog | grep -q "dispatching $STUCK"; then
  bad "B3b the rework candidate was not also dispatched" "two dispatches in one heartbeat"
else
  ok "B3b the rework candidate was not also dispatched"
fi

pkill -f "$WORK/converge.sh" 2>/dev/null

# --- B4. THE CONCURRENCY GUARD IS UNCHANGED ---------------------------------
# The blast-radius line on the issue: "an issue with a LIVE converge is still
# excluded, or two runs fight over one worktree." This is the case that would
# make the fix worse than the bug.
reset_dispatch_state
make_kipi '0 ready issue
[dry] would rework '"$STUCK"'
'
bash "$WORK/converge.sh" --issue "$STUCK" --max-rounds 3 >/dev/null 2>&1 &
DECOY=$!
disown "$DECOY" 2>/dev/null || true
sleep 1

GUARD_RUNS=5; GUARD_HELD=0
for _ in $(seq 1 "$GUARD_RUNS"); do
  run_dispatch >/dev/null
  dlog | grep -q "dispatching $STUCK" || GUARD_HELD=$((GUARD_HELD + 1))
  : > "$WORK/dhome/.config/kipi/dispatch.log"
done
check "B4a a rework candidate with a LIVE converge is never dispatched" \
  "$GUARD_HELD" "$GUARD_RUNS"
check "B4b and no budget slot is spent on it" "$(budget)" "0"

kill "$DECOY" 2>/dev/null
pkill -f "$WORK/converge.sh" 2>/dev/null

# --- B5. an empty board is still a quiet no-op ------------------------------
reset_dispatch_state
make_kipi '0 ready issue
0 rework candidate
'
run_dispatch >/dev/null; RCE=$?
check "B5a an empty board exits 0" "$RCE" "0"
check "B5b and spends no budget" "$(budget)" "0"
check "B5c and pages nobody" "$([ -s "$WORK/pages.txt" ] && echo paged || echo silent)" "silent"

# --- B6. the daily cap still stops a rework dispatch ------------------------
# Rework spends the same allowance as fresh work (the DoR: "Not doing: raising
# the daily cap"), so the cap has to bind it too.
reset_dispatch_state
make_kipi '0 ready issue
[dry] would rework '"$STUCK"'
'
DMAX=1 run_dispatch >/dev/null
pkill -f "$WORK/converge.sh" 2>/dev/null
: > "$WORK/dhome/.config/kipi/dispatch.log"
DMAX=1 run_dispatch >/dev/null

if dlog | grep -q "DAILY CAP"; then
  ok "B6 the daily cap binds rework dispatches too"
else
  bad "B6 the daily cap binds rework dispatches too" "$(dlog | tail -2 | tr '\n' ' ')"
fi

pkill -f "$WORK/converge.sh" 2>/dev/null

# --- B8. a rework dispatch SPENDS a rework-budget slot ----------------------
# The half of the round-3 major that MAX_ATTEMPTS structurally cannot do:
# `bump_attempt` has one call site and it fires only when claude exits non-zero,
# so on the path where the agent exits 0 with the PR still red the ledger file
# was never even created. The counter has to move on a SUCCESSFUL dispatch.
reset_dispatch_state
rm -f -- "$WORK/state/linear-worker-attempts.json"
make_kipi '0 ready issue
[dry] would rework '"$STUCK"'
'
run_dispatch >/dev/null
pkill -f "$WORK/converge.sh" 2>/dev/null
check "B8a one rework dispatch spends exactly one rework-budget slot" \
  "$(rework_dispatches "$STUCK")" "1"

reset_dispatch_state
make_kipi '1 ready issue
[dry] would work '"$FRESH"'
'
run_dispatch >/dev/null
pkill -f "$WORK/converge.sh" 2>/dev/null
check "B8b a FRESH dispatch spends none of it" "$(rework_dispatches "$FRESH")" "0"
check "B8c and does not touch the rework candidate's budget either" \
  "$(rework_dispatches "$STUCK")" "1"

# --- B9. THE LAYER ABOVE: what dispatch writes, the picker reads ------------
# Neither half of this fix is worth anything alone. The dispatcher can spend the
# budget perfectly and the loop is still unbounded if the announcement never
# reads it back. So: drive the budget to the cap through the REAL dispatcher,
# then run the REAL picker and assert the candidate is gone from the announced
# set. MAX_REWORK_DISPATCHES is 2 in linear-worker.sh.
reset_dispatch_state
rm -f -- "$WORK/state/linear-worker-attempts.json"
make_kipi '0 ready issue
[dry] would rework '"$STUCK"'
'
run_dispatch >/dev/null; pkill -f "$WORK/converge.sh" 2>/dev/null
run_dispatch >/dev/null; pkill -f "$WORK/converge.sh" 2>/dev/null
check "B9a two dispatches reach the cap" "$(rework_dispatches "$STUCK")" "2"

printf 'sana/%s\n' "$(echo "$STUCK" | tr 'A-Z' 'a-z')" > "$WORK/gh-open-branches"
rm -f -- "$WORK/gh-fail"; : > "$WORK/pages.txt"
fixture "$(row "$STUCK" started owner:sana 1)"
B9="$(run_worker)"
if printf '%s' "$B9" | grep -q "would rework $STUCK"; then
  bad "B9b the picker refuses a candidate whose rework budget the DISPATCHER spent" \
    "the two halves do not meet: the budget is written and never read, so the loop is still unbounded"
else
  ok "B9b the picker refuses a candidate whose rework budget the DISPATCHER spent"
fi
check "B9c and reaching the cap pages a human once" \
  "$(pages_for "$STUCK")" "1"

# --- B7. both scripts still parse ------------------------------------------
bash -n "$WORKER"   && ok "B7a linear-worker.sh parses (bash -n)" || bad "B7a linear-worker.sh parses" ""
bash -n "$DISPATCH" && ok "B7b kipi-dispatch.sh parses (bash -n)" || bad "B7b kipi-dispatch.sh parses" ""

echo
printf '== %s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
