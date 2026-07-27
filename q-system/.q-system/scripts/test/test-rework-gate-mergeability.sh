#!/usr/bin/env bash
# Reproducer + acceptance criterion for "the rework gate ignores mergeability"
# (ASK-208, sp-71b63e62).
#
# THE DEFECT: rework_gate decided "is there work to do" from the stored verdict
# alone. A PR approved earlier that LATER stops being mergeable was invisible:
# the loop reported "waiting on founder merge only" and handed it back.
#
# OBSERVED (2026-07-27): PR #11 was approved 06:08Z. #16 landed 17:30Z and broke
# it. Both `converge` and a direct worker run skipped it in under 2 seconds. The
# loop could not dispatch the one thing that was blocking the merge.
#
# Two layers, because the unit case alone would pass on a lib nobody calls with
# the second argument:
#   A. the gate itself, every (verdict x mergeability) pair
#   B. the real worker, end to end, on an approved-but-CONFLICTING PR
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SCRIPTS="$ROOT/q-system/.q-system/scripts"
LIB="$SCRIPTS/pr-verdict-lib.sh"
WORKER="$SCRIPTS/linear-worker.sh"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$LIB" ] || fail "pr-verdict-lib.sh does not exist at $LIB"
REAL_PY="$(command -v python3)" || fail "python3 not on PATH"
REAL_GIT="$(command -v git)"    || fail "git not on PATH"

# shellcheck source=/dev/null
. "$LIB"

# --- A. the gate, per (verdict, mergeability) pair ---------------------------
# gate_is <want-rc> <verdict> <mergeable> <why>
gate_is() {
  local want="$1" verdict="$2" mergeable="$3" why="$4" got
  rework_gate "$verdict" "$mergeable"; got=$?
  [ "$got" = "$want" ] || fail "rework_gate '$verdict' '$mergeable' -> $got, want $want ($why)"
  ok "$why"
}

gate_is 0  "APPROVE WITH NITS" "CONFLICTING" "approved but CONFLICTING is rework, not done"
gate_is 0  "APPROVE"           "CONFLICTING" "a clean APPROVE that stopped merging is rework too"
gate_is 10 "APPROVE WITH NITS" "MERGEABLE"   "approved AND mergeable still waits on the founder"
gate_is 10 "APPROVE"           "MERGEABLE"   "APPROVE + MERGEABLE waits on the founder"
# UNKNOWN is GitHub still computing. Treating it as conflicting would dispatch a
# rework round on a healthy PR every time the API was mid-computation, so the
# unknown case keeps the old behaviour: only a stated CONFLICTING is a conflict.
gate_is 10 "APPROVE WITH NITS" "UNKNOWN"     "UNKNOWN mergeability does not manufacture a rework round"
gate_is 10 "APPROVE"           ""            "an absent mergeability reading does not manufacture a rework round"
gate_is 0  "REQUEST CHANGES"   "MERGEABLE"   "REQUEST CHANGES is rework regardless of mergeability"
gate_is 0  "BLOCK"             "CONFLICTING" "BLOCK is rework regardless of mergeability"
gate_is 20 ""                  "CONFLICTING" "no verdict is still unreviewed, not rework"
gate_is 20 "garbage"           "MERGEABLE"   "an unrecognised verdict is still unreviewed"

# The one-argument call must keep its old meaning: this lib is sourced by more
# than one caller and a silent behaviour change on the short form is a fleet bug.
rework_gate "APPROVE"; [ $? = 10 ] || fail "one-arg rework_gate 'APPROVE' no longer returns 10"
ok "the one-argument form keeps its original semantics"

# --- B. the real worker, on an approved-but-CONFLICTING PR -------------------
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_LINEAR_CLAIMS KIPI_SESSION_ID CLAUDE_SESSION_ID 2>/dev/null || true
G() { git -c user.email=t@t.t -c user.name=t "$@"; }

git init -q --bare "$WORK/origin"
git init -q "$WORK/skel"
G -C "$WORK/skel" commit -q --allow-empty -m c1
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "$WORK/origin"
git -C "$WORK/skel" push -q -u origin main

STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home" "$WORK/state/pr-reviews"
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '{"ready":[{"id":"%s","title":"t","project":"p"}],"total_open":1}\n' "\${2:-ASK-AAA}"
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
# An APPROVED PR that GitHub reports as CONFLICTING -- the exact PR #11 state.
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "pr list"*)                    echo 777 ;;
  "pr view 777 --json mergeable"*) echo CONFLICTING ;;
esac
exit 0
EOF
# The work phase leaves a marker. Reaching it at all IS the assertion.
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
echo "worked" >> "$WORK/worked.txt"
exit 0
EOF
chmod +x "$STUB/python3" "$STUB/gh" "$STUB/claude"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub"

printf '{"verdict":"APPROVE WITH NITS","pr":777}\n' > "$WORK/state/pr-reviews/pr-777.verdict.json"
: > "$WORK/worked.txt"

( cd "$WORK/skel" \
  && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state" \
     bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) >"$WORK/run.out" 2>&1

if grep -q "worked" "$WORK/worked.txt" 2>/dev/null; then
  ok "an approved-but-CONFLICTING PR reached the work phase (rework was dispatched)"
else
  fail "SKIPPED A BLOCKED PR: the worker did not dispatch rework for an approved PR
      that GitHub reports as CONFLICTING. It said: $(grep -i 'skip' "$WORK/run.out" | head -1)"
fi

grep -qi "waiting on founder merge" "$WORK/run.out" \
  && fail "the run still reported 'waiting on founder merge' for a CONFLICTING PR"
ok "the run does not claim the PR is merely waiting on the founder"

# --- C. mergeable + approved must still be left alone -----------------------
# The other half of the gate: this fix must not turn every approved PR into an
# endless rework loop. Same fixture, MERGEABLE instead of CONFLICTING.
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "pr list"*)                    echo 778 ;;
  "pr view 778 --json mergeable"*) echo MERGEABLE ;;
esac
exit 0
EOF
chmod +x "$STUB/gh"
# The verdict record goes in the state dir the RUN BELOW actually reads.
# Round-3 review, finding 2: this used to write to $WORK/state while the run used
# KIPI_STATE_DIR=$WORK/state-ok. The worker found no verdict, skipped at gate 20
# (unreviewed) and never reached the APPROVE branch at all, so `worked.txt is
# empty` held no matter what that branch did. Verified: with the paths crossed, a
# worker mutated to ignore gate 10 entirely still printed "ok: an approved AND
# mergeable PR is still left alone" and the suite still said PASS (15 checks).
mkdir -p "$WORK/state-ok/pr-reviews"
printf '{"verdict":"APPROVE WITH NITS","pr":778}\n' > "$WORK/state-ok/pr-reviews/pr-778.verdict.json"
: > "$WORK/worked.txt"

( cd "$WORK/skel" \
  && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state-ok" \
     bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) >"$WORK/run-ok.out" 2>&1

[ ! -s "$WORK/worked.txt" ] \
  || fail "an approved AND mergeable PR was reworked; this fix must not loop on healthy PRs"
ok "an approved AND mergeable PR is still left alone for the founder"

# ...and pin WHY it was left alone. An absence-of-work assertion passes for any
# reason the worker declines, so on its own it can never tell "the gate approved
# it" from "the fixture was broken and it skipped as unreviewed". Asserting the
# gate that fired is what makes the case above able to fail.
grep -q "nothing to rework, waiting on founder merge" "$WORK/run-ok.out" \
  || fail "section C skipped for the WRONG REASON -- it must reach gate 10 (approved),
      not gate 20 (unreviewed). The worker said: $(grep -i skip "$WORK/run-ok.out" | head -1)"
ok "it was left alone at gate 10 (approved+mergeable), not skipped as unreviewed"

bash -n "$LIB"    || fail "pr-verdict-lib.sh does not parse"
bash -n "$WORKER" || fail "linear-worker.sh does not parse"
ok "both scripts parse (bash -n)"

echo "PASS: rework gate mergeability ($PASS checks)"
