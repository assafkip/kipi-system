#!/usr/bin/env bash
# Reproducer + acceptance criterion for "nothing caps rework on the direct
# worker path" (ASK-208, PR #22 review round 3, finding 4).
#
# THE DEFECT: before this PR, APPROVE was terminal for the worker. Adding
# mergeability to the gate (sp-71b63e62) made an approved PR that GitHub reports
# CONFLICTING re-enter rework -- correct, and unbounded. MAX_ATTEMPTS only counts
# runs where `claude` exits NON-ZERO, and the cited failure mode is an agent that
# exits 0 having done the wrong thing (two rounds of code polish while the
# conflict went untouched). The `rounds` counter was written every round and
# never read as a gate. Measured by the reviewer over 6 scheduled runs on one
# approved+CONFLICTING PR: 6 rework rounds dispatched, 18 permanent Linear
# comments, 0 refusals.
#
# converge.sh bounds its own loop (MAX_ROUNDS + the exit-5 stall check), so the
# uncapped path is repeated `kipi work --apply --issue X` -- which is what
# launchd runs unattended.
#
# WHY A CAP AND NOT A STALL CHECK: converge's exit-5 needs an unchanged head sha,
# and the cited agent DOES push each round. It polishes code while the conflict
# survives, so the sha moves every time and a stall check never fires. A ceiling
# on rounds is the only thing that bounds that shape.
#
# WHY THE CAP MUST BE RESETTABLE: a counter that only ever grows makes the worker
# go permanently dark on an issue after the operator does the right thing -- the
# exact regression round 2 of this PR flagged one layer up. Case 4 pins the way
# back.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
WORKER="$ROOT/q-system/.q-system/scripts/linear-worker.sh"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$WORKER" ] || fail "linear-worker.sh does not exist at $WORKER"
REAL_PY="$(command -v python3)" || fail "python3 not on PATH"
REAL_GIT="$(command -v git)"    || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_LINEAR_CLAIMS KIPI_SESSION_ID CLAUDE_SESSION_ID 2>/dev/null || true
G() { git -c user.email=t@t.t -c user.name=t "$@"; }

git init -q --bare "$WORK/origin"
git -C "$WORK/origin" symbolic-ref HEAD refs/heads/main
git init -q "$WORK/skel"
G -C "$WORK/skel" commit -q --allow-empty -m c1
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "$WORK/origin"
git -C "$WORK/skel" push -q -u origin main

STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home" "$WORK/state/pr-reviews"
# The linear-sync probe: every progress note is a PERMANENT comment on a Linear
# object that cannot be deleted, so "how many did this cost" is a number the test
# reads back, not a thing anyone estimates.
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '{"ready":[{"id":"ASK-AAA","title":"t","project":"p"}],"total_open":1}\n'
      exit 0 ;;
  *linear-sync.py) echo "\$*" >> "$WORK/linear-notes.txt"; exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
# The PR #11 state: approved earlier, CONFLICTING now. It never resolves, which
# is the whole point -- an unresolvable conflict must not buy infinite rounds.
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "pr list"*)                    echo 999 ;;
  "pr view 999 --json mergeable"*) echo CONFLICTING ;;
esac
exit 0
EOF
# An agent that exits 0 having changed nothing that matters: the cited mode.
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
case "\$*" in
  *"You are Sana"*) echo "round" >> "$WORK/dispatched.txt" ;;
esac
exit 0
EOF
cat > "$WORK/notify-recorder.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$WORK/pages.txt"
EOF
chmod +x "$STUB/python3" "$STUB/gh" "$STUB/claude" "$WORK/notify-recorder.sh"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub"

printf '{"verdict":"APPROVE WITH NITS","pr":999}\n' > "$WORK/state/pr-reviews/pr-999.verdict.json"
: > "$WORK/dispatched.txt"; : > "$WORK/pages.txt"; : > "$WORK/linear-notes.txt"

CAP=3
run_worker() {
  ( cd "$WORK/skel" \
    && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state" \
       KIPI_NOTIFY="$WORK/notify-recorder.sh" KIPI_MAX_ROUNDS="$CAP" \
       bash "$WORKER" "$@" ) >>"$WORK/run.out" 2>&1
}
count() { wc -l < "$1" | tr -d ' '; }

# --- 1. the cap bounds the rounds ------------------------------------------
# Six scheduled runs, the reviewer's own measurement, against a cap of 3.
: > "$WORK/run.out"
for _ in 1 2 3 4 5 6; do run_worker --apply --issue ASK-AAA --limit 1; done

DISPATCHED="$(count "$WORK/dispatched.txt")"
if [ "$DISPATCHED" -gt "$CAP" ]; then
  fail "UNBOUNDED: 6 scheduled runs on ONE approved-but-CONFLICTING PR dispatched
      $DISPATCHED rework rounds against a cap of $CAP. Each is a bounded claude run
      and 3 permanent Linear comments; nothing ever refuses."
fi
[ "$DISPATCHED" = "$CAP" ] \
  || fail "the cap is too tight: only $DISPATCHED of $CAP allowed rounds ran"
ok "6 scheduled runs dispatched exactly $CAP rework rounds, then refused"

grep -qi "round cap" "$WORK/run.out" \
  || fail "the refusal does not say why. It said: $(grep -i skip "$WORK/run.out" | tail -1)"
ok "the refusal names the round cap (an operator can act on it)"

# --- 2. the refusal costs no permanent Linear comments ----------------------
# The gate runs BEFORE the claim and before the "Picked up" note on purpose. A
# refusal that still comments is the residue the finding is actually about.
NOTES="$(count "$WORK/linear-notes.txt")"
NOTES_PER_ROUND=$(( NOTES / CAP ))
[ "$NOTES" -le $(( NOTES_PER_ROUND * CAP )) ] \
  || fail "the 3 refused runs still wrote Linear comments ($NOTES total for $CAP rounds)"
ok "the refused runs wrote no additional Linear comments ($NOTES for $CAP dispatched rounds)"

# --- 3. it pages ONCE, on the transition, not once per refused run ----------
# A capped issue that pages every scheduled run is a channel the founder stops
# reading, which costs more than the silence it replaced.
PAGES="$(count "$WORK/pages.txt")"
[ "$PAGES" != "0" ] \
  || fail "hitting the cap paged nobody; a wedged issue in an unattended loop has
      to reach a human, or it just sits there"
[ "$PAGES" = "1" ] \
  || fail "hitting the cap paged $PAGES times across 3 refused runs; it must page on
      the transition only"
ok "hitting the cap pages exactly once, on the transition"

# --- 4. the dry run reports the truth ---------------------------------------
# `kipi work` (dry) said "would work ASK-AAA" for an issue it would in fact
# refuse. The fix has to land on the REPORT, not only on the gate.
: > "$WORK/run.out"
run_worker --issue ASK-AAA --limit 1
grep -q "would work" "$WORK/run.out" \
  && fail "the dry run still claims it would work a capped issue: $(grep 'would work' "$WORK/run.out")"
grep -qi "round cap" "$WORK/run.out" \
  || fail "the dry run says nothing about the cap: $(tail -2 "$WORK/run.out")"
ok "the dry run reports the cap instead of claiming it would work the issue"

# --- 5. the cap is resettable: no permanent darkness ------------------------
# A counter that only grows turns "the operator fixed it" into "the worker never
# looks at this issue again", which is worse than the unbounded loop it replaced.
: > "$WORK/run.out"; : > "$WORK/dispatched.txt"
run_worker --reset-rounds --issue ASK-AAA
run_worker --apply --issue ASK-AAA --limit 1
[ "$(count "$WORK/dispatched.txt")" = "1" ] \
  || fail "after --reset-rounds the worker still refused; the cap is permanent
      darkness, which is the regression this fix must not introduce"
ok "--reset-rounds clears the cap and the next run dispatches again"

# --- 6. a fresh issue is never capped ---------------------------------------
# The counter is per-issue. A cap that leaked across issues would stall a board.
: > "$WORK/dispatched.txt"
( cd "$WORK/skel" \
  && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state" \
     KIPI_NOTIFY="$WORK/notify-recorder.sh" KIPI_MAX_ROUNDS="$CAP" \
     bash "$WORKER" --apply --issue ASK-ZZZ --limit 1 ) >>"$WORK/run.out" 2>&1
[ "$(count "$WORK/dispatched.txt")" = "1" ] \
  || fail "a DIFFERENT issue was refused by ASK-AAA's round count; the cap leaked across issues"
ok "the cap is per-issue: a different issue still dispatches"

bash -n "$WORKER" || fail "linear-worker.sh does not parse"
ok "linear-worker.sh parses (bash -n)"

echo "PASS: worker round cap ($PASS checks)"
