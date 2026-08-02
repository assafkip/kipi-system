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

sweep() {
  LINEAR_BYPASS_LEDGER="$LEDGER" python3 "$SWEEP" --rev origin/main --json 2>/dev/null
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
(cd "$CLONE" && LINEAR_BYPASS_LEDGER="$LEDGER_CLONE" python3 "$SWEEP" --json >/dev/null 2>&1)
if grep -q "$SHA_ELSEWHERE" "$LEDGER_CLONE" 2>/dev/null; then
  ok "the sweep fetched and recorded a commit pushed from elsewhere"
else
  no "the sweep read a stale ref and missed a commit pushed from elsewhere"
fi

# ...and --no-fetch is the opt-out, which must still read the stale ref.
git -C "$CLONE" update-ref refs/remotes/origin/main "$CLONE_BEFORE"
LEDGER_NOFETCH="$TMP/nofetch.jsonl"
OUT_NF=$(cd "$CLONE" && LINEAR_BYPASS_LEDGER="$LEDGER_NOFETCH" \
  python3 "$SWEEP" --no-fetch --json 2>/dev/null)
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
    proc = subprocess.Popen([sys.executable, sweep, "--rev", "origin/main", "--json"],
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
  --dry --json 2>/dev/null)
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

echo
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ] || exit 1
