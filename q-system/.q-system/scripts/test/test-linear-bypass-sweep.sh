#!/usr/bin/env bash
# Reproducer + regression suite for linear-bypass-sweep.py (ASK-284).
#
# The hole this pins: `git commit --no-verify` skips the commit-msg gate, so a
# commit with no Linear id and no [no-issue:] tag reaches origin and the bypass
# ledger never sees it. The ledger then reports a number LOWER than the truth
# and reads as clean. The sweep is the verify path that reads git directly, so
# skipping the hook does not skip the accounting.
#
# Every case runs against a REAL git repo pushed to a REAL bare origin, because
# the thing under test is "what actually reached origin", not a string.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SWEEP="$SCRIPT_DIR/../linear-bypass-sweep.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0

ok() { echo "  PASS: $1"; pass=$((pass + 1)); }
no() { echo "  FAIL: $1"; fail=$((fail + 1)); }

check() {
  # check <name> <expected> <actual>
  if [ "$2" = "$3" ]; then ok "$1 ($3)"; else no "$1 (expected $2, got $3)"; fi
}

# --- build a repo with a real origin -----------------------------------------
ORIGIN="$TMP/origin.git"
WORK="$TMP/work"
LEDGER="$TMP/bypass.jsonl"

git init --bare -q "$ORIGIN"
git init -q -b main "$WORK"
cd "$WORK" || exit 1
git config user.email sweep@test.local
git config user.name "Sweep Test"
git config commit.gpgsign false
git remote add origin "$ORIGIN"

# The minute is an ARGUMENT, not a counter. Every call site is `$(commit ...)`,
# a command substitution, so a mutating counter increments inside a subshell and
# every commit lands on the same timestamp -- which silently makes the floor case
# untestable rather than failing loudly.
commit() {
  # commit <minute> <message>  — --no-verify mirrors the incident: no gate runs.
  local when
  when=$(printf '2026-07-27T10:%02d:00+00:00' "$1")
  echo "$RANDOM$RANDOM" >> file.txt
  git add file.txt
  GIT_AUTHOR_DATE="$when" GIT_COMMITTER_DATE="$when" \
    git commit -q --no-verify -m "$2"
  git rev-parse HEAD
}

SHA_OK=$(commit 1 "feat: compliant thing (ASK-1)")
SHA_HATCH=$(commit 2 "chore: typo [no-issue: docs typo]")
SHA_HOLE=$(commit 3 "fix(gate): the bypassed one")

# A REAL merge commit, from a real divergent branch. `git merge --no-ff HEAD`
# (the shipped fixture) is "already up to date": git creates nothing, so the
# negative control below asserted the absence of a commit that never existed and
# could not have caught a regression in merge classification.
git checkout -q -b side
SHA_SIDE=$(commit 4 "chore(side): divergent work [no-issue: fixture branch]")
git checkout -q main
SHA_MERGE=$(GIT_AUTHOR_DATE="2026-07-27T10:05:00+00:00" \
  GIT_COMMITTER_DATE="2026-07-27T10:05:00+00:00" \
  git merge -q --no-ff --no-verify -m "Merge branch 'side' into main" side \
  && git rev-parse HEAD)
git push -q origin main

# --all-history is not decoration here. This fixture repo has no commit-msg gate
# in its history at all, so there is no activation floor to derive and the sweep
# now REFUSES rather than silently scanning unfloored (round 5, finding 2). The
# whole-window scan is exactly what these cases want, and asking for it out loud
# is the difference between an opt-in bound and an accident.
sweep() {
  LINEAR_BYPASS_LEDGER="$LEDGER" python3 "$SWEEP" --rev origin/main --all-history \
    --json 2>/dev/null
}

field() { python3 -c "import json,sys; print(json.loads(sys.stdin.read())[sys.argv[1]])" "$1"; }

echo "=== linear-bypass-sweep: the hole ==="

OUT="$(sweep)"
check "first sweep records the unaccounted commit" 1 "$(printf '%s' "$OUT" | field recorded)"

# The ledger is the thing the founder counts. It has to change.
LEDGER_LINES=$(wc -l < "$LEDGER" | tr -d ' ')
check "ledger count changed" 1 "$LEDGER_LINES"

if grep -q "$SHA_HOLE" "$LEDGER"; then
  ok "the bypassed commit's sha is in the ledger"
else
  no "the bypassed commit's sha is NOT in the ledger"
fi

echo "=== negative controls ==="

# Without this the three greps below pass vacuously on a missing file, which is
# the classic green-but-wrong shape: a negative control that cannot fail.
if [ -s "$LEDGER" ]; then
  ok "ledger exists, so the negative controls below can actually fail"
else
  no "ledger missing — the negative controls below prove nothing"
fi

if grep -q "$SHA_OK" "$LEDGER"; then
  no "a commit naming an issue was recorded (false positive)"
else
  ok "a commit naming an issue is not recorded"
fi

if grep -q "$SHA_HATCH" "$LEDGER"; then
  no "a hook-path [no-issue:] commit was recorded twice (hook + sweep)"
else
  ok "a hook-path [no-issue:] commit is not double-counted"
fi

# Merge machinery inherits provenance; gating it would break merges for no gain.
# The fixture must actually CONTAIN a merge commit first, or the two checks below
# assert the absence of something that was never created.
MERGE_COUNT=$(git rev-list --merges --count origin/main)
check "the fixture contains a real merge commit" 1 "$MERGE_COUNT"

if [ -n "${SHA_MERGE:-}" ] && grep -q "$SHA_MERGE" "$LEDGER"; then
  no "the merge commit's sha was recorded"
else
  ok "the merge commit's sha is not recorded"
fi

if grep -qi "merge branch" "$LEDGER"; then
  no "a merge commit was recorded"
else
  ok "merge machinery is not recorded"
fi

echo "=== idempotence (must not re-ping the same fact every cycle) ==="

OUT2="$(sweep)"
check "second sweep records nothing new" 0 "$(printf '%s' "$OUT2" | field recorded)"
check "ledger unchanged on re-run" 1 "$(wc -l < "$LEDGER" | tr -d ' ')"

echo "=== a new occurrence is still caught ==="

SHA_HOLE2=$(commit 9 "docs: another bypassed one")
git push -q origin main
OUT3="$(sweep)"
check "third sweep records the new one only" 1 "$(printf '%s' "$OUT3" | field recorded)"
check "ledger grew by exactly one" 2 "$(wc -l < "$LEDGER" | tr -d ' ')"

if grep -q "$SHA_HOLE2" "$LEDGER"; then
  ok "the new bypassed sha is in the ledger"
else
  no "the new bypassed sha is missing"
fi

echo "=== entry shape ==="

ENTRY=$(grep "$SHA_HOLE2" "$LEDGER")
SRC=$(printf '%s' "$ENTRY" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('source'))")
check "sweep entries are tagged source=sweep" "sweep" "$SRC"

REASON=$(printf '%s' "$ENTRY" | python3 -c "import json,sys; print(bool(json.loads(sys.stdin.read()).get('reason')))")
check "sweep entries carry a reason like hook entries" "True" "$REASON"

echo "=== unreachable rev is a no-op, not a crash ==="

LINEAR_BYPASS_LEDGER="$LEDGER" python3 "$SWEEP" --rev refs/heads/does-not-exist --json >/dev/null 2>&1
check "missing rev exits 0" 0 "$?"
check "ledger untouched by a missing rev" 2 "$(wc -l < "$LEDGER" | tr -d ' ')"

echo "=== a pre-existing hook entry (no sha) does not break dedup ==="

printf '{"at":"2026-08-01T19:48:50+00:00","reason":"legacy hook entry","subject":"chore: old"}\n' >> "$LEDGER"
OUT4="$(sweep)"
check "sweep still records nothing new alongside a legacy entry" 0 "$(printf '%s' "$OUT4" | field recorded)"

echo "=== a commit predating the gate is not a bypass ==="

# Nothing to bypass before the gate existed. Counting pre-gate history makes the
# ledger lie in the OTHER direction: on the real repo the unfloored sweep
# reported 246 when the true number was 3.
LEDGER_FLOOR="$TMP/floor.jsonl"
FLOOR=$(git log -1 --format=%aI "$SHA_HOLE2")
# An empty floor would fall back to the gate-activation default and silently
# test nothing, which is the failure this whole file exists to refuse.
if [ -n "$FLOOR" ]; then
  ok "fixture floor resolved ($FLOOR)"
else
  no "fixture floor is empty; the cases below would prove nothing"
fi
OUT5=$(LINEAR_BYPASS_LEDGER="$LEDGER_FLOOR" python3 "$SWEEP" --rev origin/main \
  --since "$FLOOR" --json 2>/dev/null)
check "a floor at the newer bypass excludes the older one" 1 "$(printf '%s' "$OUT5" | field recorded)"

if grep -q "$SHA_HOLE" "$LEDGER_FLOOR"; then
  no "the pre-floor commit was recorded"
else
  ok "the pre-floor commit is not recorded"
fi

# ...and the floor is an OPT-IN bound, not a silent drop of the whole window.
LEDGER_ALL="$TMP/all.jsonl"
OUT6=$(LINEAR_BYPASS_LEDGER="$LEDGER_ALL" python3 "$SWEEP" --rev origin/main \
  --all-history --json 2>/dev/null)
check "--all-history sees both bypasses" 2 "$(printf '%s' "$OUT6" | field recorded)"

# A floor git would silently ignore must be a hard error, never "no floor".
LEDGER_JUNK="$TMP/junk.jsonl"
LINEAR_BYPASS_LEDGER="$LEDGER_JUNK" python3 "$SWEEP" --rev origin/main \
  --since "last tuesday-ish" --json >/dev/null 2>&1
check "an unparseable floor exits non-zero" 1 "$?"
if [ -s "$LEDGER_JUNK" ]; then
  no "an unparseable floor still wrote rows (silently became no floor)"
else
  ok "an unparseable floor writes nothing"
fi

echo "=== a pre-gate commit REPLAYED after the gate went live is a bypass ==="

# A cherry-pick or rebase writes a BRAND NEW commit object that carries the
# original AUTHOR date. Comparing author dates against the floor meant that
# commit was "before the gate" forever, even though the object was created after
# activation, reached origin after activation, and no hook ever saw it. The
# activation floor is about when a commit ENTERED this history, so both sides
# compare committer dates.
CHERRY="$TMP/cherry"
CHERRY_ORIGIN="$TMP/cherry-origin.git"
CHERRY_LEDGER="$TMP/cherry.jsonl"
git init --bare -q "$CHERRY_ORIGIN"
git init -q -b main "$CHERRY"
git -C "$CHERRY" config user.email sweep@test.local
git -C "$CHERRY" config user.name "Sweep Test"
git -C "$CHERRY" config commit.gpgsign false

echo base > "$CHERRY/base.txt"
git -C "$CHERRY" add base.txt
GIT_AUTHOR_DATE=2026-06-30T10:00:00Z GIT_COMMITTER_DATE=2026-06-30T10:00:00Z \
  git -C "$CHERRY" commit -q --no-verify -m 'chore: base (ASK-1)'

# The pre-gate work, parked on a stale branch.
git -C "$CHERRY" checkout -q -b legacy
echo old > "$CHERRY/old-change.txt"
git -C "$CHERRY" add old-change.txt
GIT_AUTHOR_DATE=2026-07-01T10:00:00Z GIT_COMMITTER_DATE=2026-07-01T10:00:00Z \
  git -C "$CHERRY" commit -q --no-verify -m 'fix: old work with no id'
git -C "$CHERRY" checkout -q main

# The gate goes live. gate_live_since derives the floor from THIS commit.
mkdir -p "$CHERRY/q-system/.q-system/scripts"
cp "$SCRIPT_DIR/../linear-issue-ref-check.py" "$CHERRY/q-system/.q-system/scripts/"
git -C "$CHERRY" add .
GIT_AUTHOR_DATE=2026-08-01T10:00:00Z GIT_COMMITTER_DATE=2026-08-01T10:00:00Z \
  git -C "$CHERRY" commit -q --no-verify -m 'feat: install the gate (ASK-1)'

# ...and the stale branch is replayed onto it. New object, old author date.
# No --no-verify here: git cherry-pick does not accept it (and this fixture repo
# has no hooks installed anyway, which is the point — a replay runs no gate).
if GIT_COMMITTER_DATE=2026-08-02T10:00:00Z \
     git -C "$CHERRY" cherry-pick legacy >/dev/null 2>&1; then
  ok "the cherry-pick landed"
else
  no "the cherry-pick failed; every case below proves nothing"
fi
CHERRY_SHA=$(git -C "$CHERRY" rev-parse HEAD)
git -C "$CHERRY" remote add origin "$CHERRY_ORIGIN"
git -C "$CHERRY" push -q -u origin main

# The fixture only proves something if the two dates actually straddle the floor.
CHERRY_A=$(git -C "$CHERRY" log -1 --format=%aI "$CHERRY_SHA")
CHERRY_C=$(git -C "$CHERRY" log -1 --format=%cI "$CHERRY_SHA")
if [ "$CHERRY_A" != "$CHERRY_C" ]; then
  ok "the replayed commit kept its old author date ($CHERRY_A vs $CHERRY_C)"
else
  no "the cherry-pick did not preserve the author date; the case proves nothing"
fi

OUT_CHERRY=$(cd "$CHERRY" && LINEAR_BYPASS_LEDGER="$CHERRY_LEDGER" \
  python3 "$SWEEP" --rev origin/main --json 2>/dev/null)
check "a pre-gate commit replayed after activation is recorded" 1 \
  "$(printf '%s' "$OUT_CHERRY" | field recorded)"

if [ -s "$CHERRY_LEDGER" ] && grep -q "$CHERRY_SHA" "$CHERRY_LEDGER"; then
  ok "the replayed commit's sha is in the ledger"
else
  no "the replayed commit's sha is NOT in the ledger"
fi

echo "=== a commit pushed from another checkout is seen (the ref is a cache) ==="

# origin/main in a second checkout is a LOCAL cache. Nothing refreshes it on its
# own, so before this the sweep read a stale ref and reported clean about commits
# it had never seen -- the same shape as the ledger hole, one layer down.
CLONE="$TMP/clone"
git clone -q "$ORIGIN" "$CLONE"
CLONE_BEFORE=$(git -C "$CLONE" rev-parse origin/main)

SHA_ELSEWHERE=$(commit 14 "chore: landed from another checkout")
git push -q origin main

# The reproducer only bites while the clone's ref is genuinely behind.
if [ "$CLONE_BEFORE" != "$SHA_ELSEWHERE" ]; then
  ok "the clone's origin/main is stale before the sweep"
else
  no "the clone is already current; the case below proves nothing"
fi

LEDGER_CLONE="$TMP/clone.jsonl"
(cd "$CLONE" && LINEAR_BYPASS_LEDGER="$LEDGER_CLONE" python3 "$SWEEP" --all-history \
  --json >/dev/null 2>&1)
if grep -q "$SHA_ELSEWHERE" "$LEDGER_CLONE" 2>/dev/null; then
  ok "the sweep fetched and recorded a commit pushed from elsewhere"
else
  no "the sweep read a stale ref and missed a commit pushed from elsewhere"
fi

# ...and --no-fetch is the opt-out, which must still read the stale ref.
git -C "$CLONE" update-ref refs/remotes/origin/main "$CLONE_BEFORE"
LEDGER_NOFETCH="$TMP/nofetch.jsonl"
OUT_NF=$(cd "$CLONE" && LINEAR_BYPASS_LEDGER="$LEDGER_NOFETCH" \
  python3 "$SWEEP" --no-fetch --all-history --json 2>/dev/null)
check "--no-fetch reports that it did not refresh" "skipped" \
  "$(printf '%s' "$OUT_NF" | field fetched)"

echo "=== the ledger read and append are one critical section ==="

# Two sweeps overlapping between "is this sha in the file" and "append it" both
# see it as absent and both write it, double-counting the one file whose entire
# job is a true count. Rather than race and hope, this HOLDS the lock, writes the
# competing row inside it, and releases: if the sweep's read happens inside the
# lock it sees that row and records nothing. If it does not, it duplicates.
LEDGER_LOCK="$TMP/lock.jsonl"
: > "$LEDGER_LOCK"
SHA_RACE=$(commit 16 "chore: the contended one")
git push -q origin main

cat > "$TMP/contend.py" <<'PY'
import fcntl, json, os, subprocess, sys, time

sweep, ledger, sha = sys.argv[1], sys.argv[2], sys.argv[3]
env = dict(os.environ, LINEAR_BYPASS_LEDGER=ledger)

with open(ledger + ".lock", "a+") as lock:
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    # --all-history: this fixture repo has no gate in history, so without it the
    # sweep REFUSES and writes nothing -- and this case counts rows containing the
    # sha, so the competing writer's single row would satisfy it. The case would
    # pass while testing no lock at all.
    proc = subprocess.Popen([sys.executable, sweep, "--rev", "origin/main",
                             "--all-history", "--json"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    time.sleep(1.0)  # the sweep is either blocked on the lock, or already past it
    with open(ledger, "a") as fh:
        fh.write(json.dumps({"at": "2026-07-27T10:16:00+00:00", "reason": "competing writer",
                             "commit": sha, "source": "sweep"}) + "\n")
    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

proc.wait(timeout=60)
rows = [ln for ln in open(ledger, encoding="utf-8") if sha in ln]
print(len(rows))
PY

RACE_ROWS=$(cd "$WORK" && python3 "$TMP/contend.py" "$SWEEP" "$LEDGER_LOCK" "$SHA_RACE")
check "a contended sha is recorded exactly once" 1 "$RACE_ROWS"

OUT_LOCK=$(LINEAR_BYPASS_LEDGER="$TMP/lockflag.jsonl" python3 "$SWEEP" --rev origin/main \
  --all-history --dry --json 2>/dev/null)
check "the sweep reports that it held the lock" "True" \
  "$(printf '%s' "$OUT_LOCK" | field locked)"

echo "=== a scan that ran out of window says so, instead of reading clean ==="

# The scan reads a fixed number of commits back. One unaccounted commit followed
# by enough accounted ones pushes it past the cap: every commit IN the window is
# accounted, so the run reports zero and the ledger never learns. "Nothing
# unaccounted in the newest N" is not "nothing unaccounted".
#
# The cap is the argument, not the fixture size: --max-count=2 over 3 commits
# reproduces the same shape as 500 over 501, in a fixture that builds in a second.
LEDGER_WIN="$TMP/window.jsonl"
SHA_BEYOND=$(commit 20 "fix(window): the one past the cap")
commit 21 "chore: filler one (ASK-2)" >/dev/null
commit 22 "chore: filler two (ASK-2)" >/dev/null
git push -q origin main

OUT_WIN=$(LINEAR_BYPASS_LEDGER="$LEDGER_WIN" python3 "$SWEEP" --rev origin/main \
  --all-history --max-count=2 --dry --json 2>/dev/null)
check "a capped scan reports that it was truncated" "True" \
  "$(printf '%s' "$OUT_WIN" | field truncated)"
check "and the truncated scan saw only its window" 2 \
  "$(printf '%s' "$OUT_WIN" | field scanned)"
check "the capped scan found nothing unaccounted inside its window" 0 \
  "$(printf '%s' "$OUT_WIN" | field unaccounted)"

# Widened by one, the same scan finds it. This is what proves the case above is
# a WINDOW defect and not a classification one.
OUT_WIDE=$(LINEAR_BYPASS_LEDGER="$TMP/wide.jsonl" python3 "$SWEEP" --rev origin/main \
  --all-history --max-count=3 --dry --json 2>/dev/null)
check "widening the window by one finds the missed commit" 1 \
  "$(printf '%s' "$OUT_WIDE" | field unaccounted)"
if printf '%s' "$OUT_WIDE" | grep -q "$SHA_BEYOND"; then
  ok "and it is the commit the capped scan walked past"
else
  no "the widened scan found a different commit than the fixture planted"
fi

# A scan whose window covers the whole range is NOT truncated. Without this the
# fix could hardcode True and every case above would still pass.
OUT_FULL=$(LINEAR_BYPASS_LEDGER="$TMP/full.jsonl" python3 "$SWEEP" --rev origin/main \
  --all-history --max-count=1000 --dry --json 2>/dev/null)
check "a scan that reached the end of history is not truncated" "False" \
  "$(printf '%s' "$OUT_FULL" | field truncated)"

echo "=== a repo with no gate in history REFUSES, it does not scan unfloored ==="

# "No floor" used to be the fallback when the activation date could not be
# derived, on the reasoning that over-counting beats dropping the window. But the
# over-count lands as rows in a permanent, sha-deduped ledger whose entire job is
# a true count, and a row written once is never re-evaluated. Refusing is the
# recoverable direction: the operator picks --all-history or --since.
LEDGER_NOGATE="$TMP/nogate.jsonl"
LINEAR_BYPASS_LEDGER="$LEDGER_NOGATE" python3 "$SWEEP" --rev origin/main \
  --json >/dev/null 2>&1
check "an underivable floor exits non-zero" 1 "$?"
if [ -s "$LEDGER_NOGATE" ]; then
  no "an underivable floor still wrote rows (silently became no floor)"
else
  ok "an underivable floor writes nothing"
fi

echo "=== the floor comes from the swept REV, not from whatever HEAD is ==="

# gate_live_since ran `git log` with no rev, so it answered about HEAD while the
# sweep scanned origin/main. Check out anything predating the gate -- a bisect, a
# detached CI checkout, an old tag -- and the floor silently became "" for a scan
# of a ref that has the gate right there in its history.
REVF="$TMP/revfloor"
REVF_ORIGIN="$TMP/revfloor-origin.git"
REVF_LEDGER="$TMP/revfloor.jsonl"
git init --bare -q "$REVF_ORIGIN"
git init -q -b main "$REVF"
git -C "$REVF" config user.email sweep@test.local
git -C "$REVF" config user.name "Sweep Test"
git -C "$REVF" config commit.gpgsign false

echo pre > "$REVF/pre.txt"
git -C "$REVF" add pre.txt
GIT_AUTHOR_DATE=2026-07-01T10:00:00Z GIT_COMMITTER_DATE=2026-07-01T10:00:00Z \
  git -C "$REVF" commit -q --no-verify -m 'chore: pre-gate work with no id'
REVF_PRE=$(git -C "$REVF" rev-parse HEAD)

mkdir -p "$REVF/q-system/.q-system/scripts"
cp "$SCRIPT_DIR/../linear-issue-ref-check.py" "$REVF/q-system/.q-system/scripts/"
git -C "$REVF" add .
GIT_AUTHOR_DATE=2026-08-01T10:00:00Z GIT_COMMITTER_DATE=2026-08-01T10:00:00Z \
  git -C "$REVF" commit -q --no-verify -m 'feat: install the gate (ASK-1)'

echo post > "$REVF/post.txt"
git -C "$REVF" add post.txt
GIT_AUTHOR_DATE=2026-08-02T10:00:00Z GIT_COMMITTER_DATE=2026-08-02T10:00:00Z \
  git -C "$REVF" commit -q --no-verify -m 'fix: post-gate bypass'
REVF_POST=$(git -C "$REVF" rev-parse HEAD)
git -C "$REVF" remote add origin "$REVF_ORIGIN"
git -C "$REVF" push -q -u origin main

# HEAD is moved BEFORE the gate. origin/main still carries it.
git -C "$REVF" checkout -q --detach "$REVF_PRE"
if [ -f "$REVF/q-system/.q-system/scripts/linear-issue-ref-check.py" ]; then
  no "the detached HEAD still has the gate file; the case proves nothing"
else
  ok "HEAD predates the gate while origin/main carries it"
fi

OUT_REVF=$(cd "$REVF" && LINEAR_BYPASS_LEDGER="$REVF_LEDGER" \
  python3 "$SWEEP" --rev origin/main --json 2>/dev/null)
check "a floor derived from the rev skips the pre-gate commit" 1 \
  "$(printf '%s' "$OUT_REVF" | field recorded)"
if [ -s "$REVF_LEDGER" ] && grep -q "$REVF_POST" "$REVF_LEDGER"; then
  ok "the post-gate bypass is recorded"
else
  no "the post-gate bypass is NOT recorded"
fi
if [ -s "$REVF_LEDGER" ] && grep -q "$REVF_PRE" "$REVF_LEDGER"; then
  no "the pre-gate commit was recorded (the floor came from HEAD)"
else
  ok "the pre-gate commit is not recorded"
fi

echo "=== the window grows to cover the range; it does not blind on volume ==="

# The floor is pinned at gate activation and never advances, so the number of
# in-range commits only grows. Against a FIXED cap that is a clock: the day
# in-range volume passes the cap, `truncated` is true on every run forever, the
# daily detector raises, and the operator gets BLIND SPOT every morning on a repo
# where nothing is wrong. `truncated` has to mean "something really went unread",
# not "the calendar moved", so an unpinned window grows until it covers the range.
GROW="$TMP/grow"
GROW_ORIGIN="$TMP/grow-origin.git"
GROW_LEDGER="$TMP/grow.jsonl"
git init --bare -q "$GROW_ORIGIN"
git init -q -b main "$GROW"
git -C "$GROW" config user.email sweep@test.local
git -C "$GROW" config user.name "Sweep Test"
git -C "$GROW" config commit.gpgsign false

mkdir -p "$GROW/q-system/.q-system/scripts"
cp "$SCRIPT_DIR/../linear-issue-ref-check.py" "$GROW/q-system/.q-system/scripts/"
git -C "$GROW" add .
GIT_AUTHOR_DATE=2026-08-01T10:00:00Z GIT_COMMITTER_DATE=2026-08-01T10:00:00Z \
  git -C "$GROW" commit -q --no-verify -m 'feat: install the gate (ASK-1)'

# The bypass sits at the BOTTOM of the range, right above the gate commit, so a
# window that merely "happened to be big enough" is not enough -- it has to reach
# all the way down. Everything above it is compliant, which is the shape that
# makes a truncated scan report a clean zero.
echo hole > "$GROW/hole.txt"
git -C "$GROW" add hole.txt
GIT_AUTHOR_DATE=2026-08-01T10:01:00Z GIT_COMMITTER_DATE=2026-08-01T10:01:00Z \
  git -C "$GROW" commit -q --no-verify -m 'fix: the deep bypass'
GROW_HOLE=$(git -C "$GROW" rev-parse HEAD)

# One more than the default window. Empty commits: the cap is about how many
# commits git walks, and nothing here depends on their contents.
GROW_FILL=$(python3 -c "import sys;sys.path.insert(0,'$SCRIPT_DIR/..');
import importlib.util as u
s=u.spec_from_file_location('sw','$SWEEP');m=u.module_from_spec(s);s.loader.exec_module(m)
print(m.DEFAULT_MAX_COUNT)")
i=0
while [ "$i" -lt "$GROW_FILL" ]; do
  i=$((i + 1))
  GIT_AUTHOR_DATE=2026-08-02T10:00:00Z GIT_COMMITTER_DATE=2026-08-02T10:00:00Z \
    git -C "$GROW" commit -q --allow-empty --no-verify -m "chore: filler $i (ASK-2)"
done
git -C "$GROW" remote add origin "$GROW_ORIGIN"
git -C "$GROW" push -q -u origin main

# The fixture proves itself before it proves anything: in-range volume must
# actually exceed the default window, or the growth path never runs.
GROW_INRANGE=$(git -C "$GROW" rev-list --count origin/main)
if [ "$GROW_INRANGE" -gt "$GROW_FILL" ]; then
  ok "the fixture exceeds the default window ($GROW_INRANGE > $GROW_FILL)"
else
  no "the fixture fits inside the default window; the growth case proves nothing"
fi

OUT_GROW=$(cd "$GROW" && LINEAR_BYPASS_LEDGER="$GROW_LEDGER" \
  python3 "$SWEEP" --rev origin/main --dry --json 2>/dev/null)
check "an unpinned window is not truncated by ordinary volume" "False" \
  "$(printf '%s' "$OUT_GROW" | field truncated)"
check "and it read the whole range, not the default window" "$GROW_INRANGE" \
  "$(printf '%s' "$OUT_GROW" | field scanned)"
check "so the deep bypass is found" 1 "$(printf '%s' "$OUT_GROW" | field unaccounted)"
if printf '%s' "$OUT_GROW" | grep -q "$GROW_HOLE"; then
  ok "and it is the commit the fixture planted"
else
  no "the grown scan found a different commit than the fixture planted"
fi

# The reported window says how far it actually had to go. Without this the fix
# could satisfy every case above by never reporting truncation at all.
check "the grown window is reported, not hidden" "True" \
  "$(printf '%s' "$OUT_GROW" | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['window'] > $GROW_FILL)")"

# Negative control: an EXPLICIT --max-count is a hard bound the operator asked
# for, so it must still truncate. If growth ignored the flag, `truncated` would
# be False here and "not truncated" above would prove nothing.
OUT_PINNED=$(cd "$GROW" && LINEAR_BYPASS_LEDGER="$TMP/grow-pinned.jsonl" \
  python3 "$SWEEP" --rev origin/main --max-count=2 --dry --json 2>/dev/null)
check "an explicit --max-count is still a hard bound" "True" \
  "$(printf '%s' "$OUT_PINNED" | field truncated)"
check "and it stays at the size the operator pinned" 2 \
  "$(printf '%s' "$OUT_PINNED" | field window)"

echo
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ] || exit 1
