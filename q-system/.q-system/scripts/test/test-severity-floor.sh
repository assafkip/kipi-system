#!/usr/bin/env bash
# Reproducer + acceptance criteria for the review severity floor (ASK-113).
#
# THE DEFECT: the adversarial reviewer had no severity floor -- REQUEST CHANGES
# fired the same on 3 minors as on 1 blocker, and a Netflix-3am bar ALWAYS finds
# something, so nothing could ever reach APPROVE. The gate was unsatisfiable by
# construction (observed: PR #11 rounds 1-2, findings converging 2->1 blockers,
# verdict pinned at REQUEST CHANGES).
#
# THE FIX under test (pr-verdict-lib.sh + its two consumers):
#   - blockers/majors  => REQUEST CHANGES/BLOCK  => rework_gate exit 0 (rework)
#   - minors/nits only => APPROVE WITH NITS      => rework_gate exit 10 (stop;
#     minors are CAPTURED as spillover, not wedged into the PR)
#   - no verdict       => rework_gate exit 20 (no spec to rework against)
#
# THE FIXTURE RULE (test-linear-claim.sh scar): review-text fixtures below are
# VERBATIM slices of the real PR #11 round-1/round-2 reviews on this machine
# (~/.config/kipi/pr-reviews/pr-11-20260726-2033*.md / -2124*.md). The round-2
# slice already earned its keep: its "Fix first: **BLOCKER 1**" line after the
# verdict made a bare BLOCK token match report verdict BLOCK -- a live bug in
# the pre-lib extraction, fixed by the BLOCKER strip in extract_verdict.
# The APPROVE WITH NITS fixture CANNOT be a captured payload yet: no reviewer
# has ever emitted one (that is the defect). It is built to the exact format
# the reviewer prompt now specifies; parser and prompt change in one commit,
# and capture is soft by design (an LLM that drifts from the format yields
# zero captured minors and a logged zero, never an invented finding).
#
# Isolation: everything runs in a mktemp dir; never touches the live
# ~/.config/kipi/pr-reviews or the spillover ledger.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
LIB="$ROOT/q-system/.q-system/scripts/pr-verdict-lib.sh"
WORKER="$ROOT/q-system/.q-system/scripts/linear-worker.sh"
REVIEWER="$ROOT/q-system/.q-system/scripts/pr-review-agent.sh"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$LIB" ] || fail "pr-verdict-lib.sh does not exist at $LIB"
. "$LIB"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# --- fixture: VERBATIM slice, real PR #11 round-2 review (2026-07-26) --------
cat > "$WORK/r2.md" <<'EOF'
**The test is not an orphan.** Registered at `q-system/.q-system/capability-manifest.json:17`.

---

## VERDICT: REQUEST CHANGES

Fix first: **BLOCKER 1**. Add state to the update path so a rewrite reopens a closed rollup issue, or open a fresh issue when the tracked one is closed. Until then, the first time the operator does the right thing and closes ASK-90x, this detector is permanently silent on the board while Slack keeps saying the board has it. That is worse than the pre-PR behavior, which at least never claimed to have surfaced anything.

MAJOR 2 and 3 are the same root cause as the defect the PR was reworked to fix, one layer out: the fix landed on the detector and not on the report. Worth closing in the same change.
EOF

# --- fixture: VERBATIM slice, real PR #11 round-1 review (2026-07-26) --------
cat > "$WORK/r1.md" <<'EOF'
## VERDICT: **REQUEST CHANGES**

**Fix first: finding #1.** Delete the unguarded flag-adjacency clause at `fleet-health-daily.py:290-291`, or gate it to tokens that are actually in command position within their segment.

Findings #2 and #3 are also blocker-class before this reaches the fleet: #2 makes the detector go permanently blind after its first hit, and #3 publishes credentials to an object that cannot be deleted. #1 is first only because it fires most often.
EOF

# --- fixture: spec-format APPROVE WITH NITS (see header for why synthetic) ---
cat > "$WORK/nits.md" <<'EOF'
Attacks that would BLOCK a lesser change all failed against this one.

## VERDICT: APPROVE WITH NITS

The single most important thing: none blocking.

FINDINGS:
minor|log line says "captured" before the write is fsynced|scripts/foo.sh:42
minor|help text omits the --issue flag|scripts/foo.sh:9
nit|two-space indent drifts to tab once|scripts/foo.sh:88
END FINDINGS
EOF

: > "$WORK/empty.md"

# --- extract_verdict against real payloads -----------------------------------
[ "$(extract_verdict "$WORK/r2.md")" = "REQUEST CHANGES" ] \
  || fail "r2 verbatim slice: expected REQUEST CHANGES, got '$(extract_verdict "$WORK/r2.md")' (BLOCKER-after-verdict trap)"
ok "real r2 slice -> REQUEST CHANGES (BLOCKER 1 prose did not read as BLOCK)"

[ "$(extract_verdict "$WORK/r1.md")" = "REQUEST CHANGES" ] \
  || fail "r1 verbatim slice: expected REQUEST CHANGES, got '$(extract_verdict "$WORK/r1.md")'"
ok "real r1 slice (bold verdict) -> REQUEST CHANGES"

[ "$(extract_verdict "$WORK/nits.md")" = "APPROVE WITH NITS" ] \
  || fail "nits fixture: expected APPROVE WITH NITS, got '$(extract_verdict "$WORK/nits.md")' (BLOCK prose before verdict must not win)"
ok "spec-format review -> APPROVE WITH NITS (anchored on the VERDICT line)"

[ -z "$(extract_verdict "$WORK/empty.md")" ] || fail "empty review must yield no verdict"
ok "empty review file (killed run) -> no verdict"

# --- rework_gate: THE acceptance criterion from the approved fix -------------
# "a synthetic review with only minors => worker does NOT re-run; with a
#  blocker => it does" -- expressed as the gate's exit codes, which is the
# only thing the worker consults.
set +e
rework_gate "REQUEST CHANGES"; [ $? -eq 0 ]  || fail "REQUEST CHANGES must allow rework"
rework_gate "BLOCK";           [ $? -eq 0 ]  || fail "BLOCK must allow rework"
rework_gate "APPROVE WITH NITS"; [ $? -eq 10 ] || fail "APPROVE WITH NITS must stop the loop"
rework_gate "APPROVE";         [ $? -eq 10 ] || fail "APPROVE must stop the loop"
rework_gate "";                [ $? -eq 20 ] || fail "no verdict must refuse rework (no spec)"
rework_gate "LGTM";            [ $? -eq 20 ] || fail "unknown token must refuse rework, fail closed"
set -e
ok "rework_gate: blocker reworks, minors-only stops, unreviewed refuses"

# --- minor capture parsing ---------------------------------------------------
MINORS="$(extract_minor_findings "$WORK/nits.md")"
[ "$(printf '%s\n' "$MINORS" | grep -c .)" = "2" ] \
  || fail "expected exactly 2 minor lines (nit excluded), got: $MINORS"
printf '%s\n' "$MINORS" | grep -q 'fsynced' || fail "first minor claim lost in parsing"
ok "FINDINGS block: 2 minors extracted, nit excluded"

[ -z "$(extract_minor_findings "$WORK/r2.md")" ] \
  || fail "review with no FINDINGS block must yield zero minors, never invent"
ok "no FINDINGS block -> zero minors (soft capture, nothing invented)"

# --- verdict record round-trip (what the worker actually reads) --------------
cat > "$WORK/pr-99.verdict.json" <<'EOF'
{"pr": 99, "issue": "ASK-999", "verdict": "APPROVE WITH NITS",
 "review": "/tmp/x.md", "ts": "2026-07-27T05:00:00Z"}
EOF
[ "$(verdict_from_record "$WORK/pr-99.verdict.json")" = "APPROVE WITH NITS" ] \
  || fail "verdict record round-trip failed"
set +e
rework_gate "$(verdict_from_record "$WORK/pr-99.verdict.json")"; [ $? -eq 10 ] \
  || fail "record -> gate chain: approved PR must not rework"
set -e
ok "record -> gate chain: APPROVE WITH NITS record stops a rework run"

echo '{broken' > "$WORK/pr-98.verdict.json"
[ -z "$(verdict_from_record "$WORK/pr-98.verdict.json")" ] \
  || fail "corrupt record must read as no-verdict (fail closed), not crash or guess"
ok "corrupt verdict record -> no verdict -> gate refuses (fails closed)"

# --- wiring: the lib is consulted by both consumers, at the right spot -------
grep -q 'pr-verdict-lib.sh' "$WORKER"   || fail "linear-worker.sh does not source pr-verdict-lib.sh"
grep -q 'rework_gate'       "$WORKER"   || fail "linear-worker.sh never calls rework_gate"
CLAIM_LINE="$(grep -n '"\$CLAIM" claim' "$WORKER" | head -1 | cut -d: -f1)"
GATE_LINE="$(grep -n 'rework_gate'      "$WORKER" | head -1 | cut -d: -f1)"
[ -n "$CLAIM_LINE" ] && [ -n "$GATE_LINE" ] && [ "$GATE_LINE" -lt "$CLAIM_LINE" ] \
  || fail "severity gate must run BEFORE the claim (no 'Picked up' note on a skipped issue)"
ok "worker wiring: gate sourced and fires before the claim"

grep -q 'pr-verdict-lib.sh' "$REVIEWER" || fail "pr-review-agent.sh does not source pr-verdict-lib.sh"
grep -q 'verdict.json'      "$REVIEWER" || fail "pr-review-agent.sh never writes the verdict record"
grep -q 'APPROVE WITH NITS' "$REVIEWER" || fail "reviewer prompt lost the severity-floor verdict rule"
grep -q 'spillover add'     "$REVIEWER" || fail "reviewer never captures minors as spillover"
ok "reviewer wiring: severity rule in prompt, record written, minors captured"

# --- fixture: VERBATIM slice, real PR #11 ROUND 4 (2026-07-27) ---------------
# The verdict sits on the line AFTER a bare `## VERDICT` heading AND qualifies
# itself with the word BLOCK. Under the pre-fix extractor this recorded BLOCK --
# it actually reached pr-11.verdict.json that way -- for a review whose own
# sentence says "not BLOCK". Both routed to rework so nothing broke that night,
# but "APPROVE (not BLOCK ...)" would have reworked an approved PR forever.
cat > "$WORK/r4.md" <<'EOF'
## VERDICT

**REQUEST CHANGES** (not BLOCK — nothing here writes an unrecoverable object; findings 1 and 2 cause silence, not corruption, and the code is a net improvement over no detector at all).

**Fix first: finding 1.** Add `skipped_no_key` to the `should_notify` expression.

FINDINGS:
major|Linear unreachable drops every finding with exit 0 and no Slack ping|scripts/fleet-health-daily.py:968
major|A rollup key in the ledger but absent from the project reports "nothing to do" forever|scripts/fleet-health-daily.py:848
minor|A Linear error on the update path kills the run mid-loop|scripts/fleet-health-daily.py:887
minor|_command_index scores a wrapper's option argument as command position|scripts/fleet-health-daily.py:319
minor|The wrapper allowlist is closed, so real invocations behind flock/ssh are missed|scripts/fleet-health-daily.py:231
END FINDINGS
EOF

[ "$(extract_verdict "$WORK/r4.md")" = "REQUEST CHANGES" ] \
  || fail "real r4: verdict-after-heading + '(not BLOCK)' qualifier misread as '$(extract_verdict "$WORK/r4.md")'"
ok "real r4 slice -> REQUEST CHANGES (heading on its own line, self-qualifying verdict)"

# --- verdict_from_findings: the ENFORCEMENT half of the severity floor --------
# The prompt telling a reviewer how to grade is not enforcement. Severities are
# structured data, so the verdict is computed from them.
[ "$(verdict_from_findings "$WORK/r4.md")" = "REQUEST CHANGES" ] \
  || fail "2 majors + 3 minors must derive REQUEST CHANGES, got '$(verdict_from_findings "$WORK/r4.md")'"
ok "derive: majors present -> REQUEST CHANGES"

[ "$(verdict_from_findings "$WORK/nits.md")" = "APPROVE WITH NITS" ] \
  || fail "minors+nit only must derive APPROVE WITH NITS"
ok "derive: minors/nits only -> APPROVE WITH NITS (the loop can now terminate)"

printf 'FINDINGS:\nblocker|publishes a credential to an undeletable object|a.py:1\nminor|typo|a.py:2\nEND FINDINGS\n' > "$WORK/blk.md"
[ "$(verdict_from_findings "$WORK/blk.md")" = "BLOCK" ] \
  || fail "a blocker must derive BLOCK regardless of what else is present"
ok "derive: blocker present -> BLOCK (severity wins over count)"

printf 'FINDINGS:\nEND FINDINGS\n' > "$WORK/clean.md"
[ "$(verdict_from_findings "$WORK/clean.md")" = "APPROVE" ] \
  || fail "an empty findings block must derive APPROVE"
ok "derive: empty findings block -> APPROVE (a clean PR is reachable)"

[ -z "$(verdict_from_findings "$WORK/r2.md")" ] \
  || fail "no FINDINGS block must derive nothing so the caller falls back to prose"
ok "derive: no findings block -> empty (prose fallback, never a guess)"

# The disagreement case the reviewer must not be trusted on: prose says APPROVE
# while its own labels carry a major. Derivation has to win, or a reviewer can
# talk a majors-laden PR through the gate.
cat > "$WORK/liar.md" <<'EOF'
## VERDICT: APPROVE

Looks good overall.

FINDINGS:
major|silently drops every finding when the API is down|a.py:10
END FINDINGS
EOF
[ "$(extract_verdict "$WORK/liar.md")" = "APPROVE" ] || fail "prose extraction should read APPROVE here"
[ "$(verdict_from_findings "$WORK/liar.md")" = "REQUEST CHANGES" ] \
  || fail "labels carry a major; derivation must override the prose APPROVE"
ok "derive overrides prose: 'APPROVE' + a major label -> REQUEST CHANGES"

grep -q 'verdict_from_findings' "$REVIEWER" \
  || fail "reviewer does not derive the verdict from findings (prompt-only enforcement)"
grep -q '"derived"\|derived' "$REVIEWER" || fail "verdict record must keep the derived value"
grep -q 'stated' "$REVIEWER" || fail "verdict record must keep the stated value for drift visibility"
ok "reviewer records stated + derived, and gates on derived"

# --- review_round: the counter the anti-re-litigation rule arms on ------------
# Off-by-one is the whole risk here, and it bit during authoring: an earlier
# draft subtracted 1 on the theory that $REVIEW already existed. It does not --
# it is a bare variable until the reviewer's stdout redirect at the end of the
# script -- so a round-4 review would have announced itself as round 3 and told
# the reviewer to re-litigate one round less than it should.
RD="$WORK/rounds"; mkdir -p "$RD"
[ "$(review_round "$RD" 11)" = "1" ] || fail "no prior reviews must be round 1"
touch "$RD/pr-11-20260726-203324.md"
[ "$(review_round "$RD" 11)" = "2" ] || fail "one prior review must be round 2"
touch "$RD/pr-11-20260726-212446.md" "$RD/pr-11-20260726-215111.md"
[ "$(review_round "$RD" 11)" = "4" ] || fail "three prior reviews must be round 4 (PR #11's real state)"
touch "$RD/pr-9-20260726-120000.md"
[ "$(review_round "$RD" 11)" = "4" ] || fail "another PR's reviews must not count toward this PR"
[ "$(review_round "$RD" 9)"  = "2" ] || fail "per-PR counting broken"
ok "review_round: 0/1/3 priors -> rounds 1/2/4, and PRs do not cross-count"

# --- severity anchors + anti-re-litigation are IN the reviewer prompt ---------
# Interpretive rules cannot be hook-enforced (the model decides how it grades),
# so the deterministic slice is: the anchors are present, and the round rule is
# conditional on round > 1. A prompt that silently loses them is the failure.
for anchor in 'blocker' 'major' 'minor' 'nit' 'BLAST RADIUS and RECOVERABILITY'; do
  grep -q -- "$anchor" "$REVIEWER" || fail "severity anchor '$anchor' missing from reviewer prompt"
done
ok "severity anchors present (blast-radius definitions for all 4 levels)"

grep -q 'ROUND_RULE' "$REVIEWER"      || fail "reviewer has no round-scoped rule block"
grep -q 'still LIVE\|STILL LIVE' "$REVIEWER" || fail "re-raise rule (repro-or-drop on repeat findings) missing"
grep -q 'Do not escalate severity across rounds' "$REVIEWER" \
  || fail "severity-escalation guard missing: a minor could be re-filed as a major next round"
ROUND_IF="$(grep -n 'if \[ "\$ROUND" -gt 1 \]' "$REVIEWER" | head -1)"
[ -n "$ROUND_IF" ] || fail "round rule must be gated on ROUND > 1 (round 1 has nothing to re-litigate)"
ok "anti-re-litigation rule wired, gated on round > 1"

grep -q 'review_round' "$REVIEWER" || fail "reviewer does not use the shared review_round (would drift from the test)"
ok "reviewer computes its round through the shared lib"

bash -n "$WORKER"   || fail "linear-worker.sh does not parse"
bash -n "$REVIEWER" || fail "pr-review-agent.sh does not parse"
ok "both consumers parse (bash -n)"

# =============================================================================
# MERGEABILITY IS HALF THE GATE (ASK-212, sp-71b63e62)
# =============================================================================
# THE DEFECT: rework_gate decided "is there work to do here" from the stored
# verdict alone. A PR approved earlier that LATER stops merging was invisible to
# the loop: it reported "waiting on founder merge only" and handed it back.
#
# OBSERVED 2026-07-27: PR #11 was approved at 06:08Z. #16 landed at 17:30Z and
# broke it. Both `converge` and a direct worker run then skipped #11 in under two
# seconds. The loop could not dispatch the one thing blocking the merge.
#
# THE TRAP, and why the second half of this section exists: making APPROVE
# non-terminal opens an unbounded rework path. An unresolvable conflict yields
# infinite rounds and a permanent Linear comment on every one. So the cap is
# asserted as hard as the dispatch (PR #22 round-3 review, finding 4).
#
# Errexit is on from the record round-trip above; the worker runs below are
# expected to return non-zero, so statuses are captured explicitly instead.
set +e

# --- D. the gate, per (verdict x merge state) --------------------------------
# gate_is <want-rc> <verdict> <merge-state> <why>
gate_is() {
  local want="$1" verdict="$2" state="$3" why="$4" got
  rework_gate "$verdict" "$state"; got=$?
  [ "$got" = "$want" ] || fail "rework_gate '$verdict' '$state' -> $got, want $want ($why)"
  ok "$why"
}

gate_is 30 "APPROVE"           "DIRTY"    "approved but DIRTY is a rebase round, not done"
gate_is 30 "APPROVE WITH NITS" "DIRTY"    "approved-with-nits + DIRTY is a rebase round too"
gate_is 30 "APPROVE"           "BEHIND"   "BEHIND is the same class of stale-against-main"
gate_is 10 "APPROVE"           "CLEAN"    "approved AND CLEAN still waits on the founder"
gate_is 10 "APPROVE WITH NITS" "CLEAN"    "approved-with-nits + CLEAN waits on the founder"
# Fail toward terminal on every state a rebase cannot fix or that GitHub has not
# stated. A missed conflict costs one human diagnosis; a manufactured one spends
# model budget on every healthy PR in the fleet at once.
gate_is 10 "APPROVE"           "UNKNOWN"  "UNKNOWN (GitHub still computing) does not manufacture a rebase round"
gate_is 10 "APPROVE"           ""         "an absent merge-state reading does not manufacture a rebase round"
gate_is 10 "APPROVE"           "BLOCKED"  "BLOCKED is branch protection; a rebase cannot fix it"
gate_is 10 "APPROVE"           "UNSTABLE" "UNSTABLE is a failing non-required check, not a conflict"
gate_is 0  "REQUEST CHANGES"   "CLEAN"    "REQUEST CHANGES is review rework regardless of merge state"
gate_is 0  "BLOCK"             "DIRTY"    "BLOCK is review rework regardless of merge state"
gate_is 20 ""                  "DIRTY"    "no verdict is still unreviewed, not rework"
gate_is 20 "garbage"           "CLEAN"    "an unrecognised verdict is still unreviewed"

# converge.sh calls this with ONE argument. A silent behaviour change on the
# short form would be a fleet-wide bug in a file this issue does not touch.
rework_gate "APPROVE"; [ $? = 10 ] || fail "one-arg rework_gate 'APPROVE' no longer returns 10"
rework_gate "REQUEST CHANGES"; [ $? = 0 ] || fail "one-arg rework_gate 'REQUEST CHANGES' no longer returns 0"
ok "the one-argument form keeps its original semantics (converge.sh is unchanged)"

# --- the real worker, end to end ---------------------------------------------
# The unit cases above would pass on a lib nobody calls with the second argument,
# so the worker is driven for real. No live GitHub API: `gh` is a stub that
# states the merge status, which is also the only way to script DIRTY on demand.
REAL_PY="$(command -v python3)" || fail "python3 not on PATH"
REAL_GIT="$(command -v git)"    || fail "git not on PATH"

W2="$(mktemp -d)"
trap 'rm -rf "$WORK" "$W2"' EXIT
unset KIPI_LINEAR_CLAIMS KIPI_SESSION_ID CLAUDE_SESSION_ID 2>/dev/null || true
G() { git -c user.email=t@t.t -c user.name=t "$@"; }

git init -q --bare "$W2/origin"
git init -q "$W2/skel"
G -C "$W2/skel" commit -q --allow-empty -m c1
git -C "$W2/skel" branch -M main
git -C "$W2/skel" remote add origin "$W2/origin"
git -C "$W2/skel" push -q -u origin main

STUB="$W2/bin"; mkdir -p "$STUB" "$W2/home"
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '{"ready":[{"id":"ASK-AAA","title":"t","project":"p"}],"total_open":1}\n'
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
echo "worked" >> "$W2/worked.txt"
# The WORK-PHASE agent runs with cwd = the worktree it was handed, so this
# records WHAT WAS IN that tree. Sections E-G only ever asked "was a round
# dispatched"; the destructive case (PR #25 review, finding 1) is a round
# dispatched into a tree that holds none of the PR's commits, which is
# invisible without this.
# FIRST WRITER WINS, because the REVIEWER also shells \`claude\`, from the real
# repo root rather than the worktree. The work phase always runs first, so the
# first record is the one under test; without this guard the reviewer's log
# overwrites it and the probe silently reports the wrong repo entirely.
# (Keying on KIPI_AGENT instead does NOT work: it is often already exported in
# the ambient environment, so the reviewer's call passes the key too.)
if [ ! -s "$W2/tree-log.txt" ]; then
  git log --oneline -n 20 > "$W2/tree-log.txt" 2>&1
fi
exit 0
EOF
# The page sink. "Did anyone get told, and how many times?" is answered by
# reading a file, not by grepping the worker's source.
cat > "$W2/notify.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$W2/pages.txt"
EOF
chmod +x "$STUB/python3" "$STUB/claude" "$W2/notify.sh"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub"

# gh_says <pr> <mergeStateStatus>
gh_says() {
  cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
case "\$*" in
  "pr list"*)                                  echo $1 ;;
  "pr view $1 --json mergeStateStatus"*)       echo $2 ;;
esac
exit 0
EOF
  chmod +x "$STUB/gh"
}

# run_worker <state-dir>  -- one scheduled worker run against that state dir
run_worker() {
  ( cd "$W2/skel" \
    && HOME="$W2/home" KIPI_SKEL="$W2/skel" KIPI_STATE_DIR="$1" \
       KIPI_NOTIFY="$W2/notify.sh" \
       bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) >"$2" 2>&1
  return 0
}

# --- E. approved + DIRTY must be DISPATCHED, not skipped as done -------------
S_DIRTY="$W2/state-dirty"; mkdir -p "$S_DIRTY/pr-reviews"
printf '{"verdict":"APPROVE WITH NITS","pr":777}\n' > "$S_DIRTY/pr-reviews/pr-777.verdict.json"
gh_says 777 DIRTY
: > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker "$S_DIRTY" "$W2/dirty.out"

grep -q worked "$W2/worked.txt" 2>/dev/null \
  || fail "SKIPPED A BLOCKED PR: an approved PR that GitHub reports DIRTY was not
      dispatched. The worker said: $(grep -i skip "$W2/dirty.out" | head -1)"
ok "approved + DIRTY reached the work phase (a rebase round was dispatched)"

grep -qi "waiting on founder merge" "$W2/dirty.out" \
  && fail "the run still claimed a DIRTY PR was merely waiting on the founder"
ok "the run does not report a DIRTY PR as waiting on the founder"

grep -q "rebase round 1/" "$W2/dirty.out" \
  || fail "the run does not say which conflict round it is on; the cap is invisible to the operator"
ok "the dispatch names the conflict round and its cap"

# The conflict budget is its own counter: spending it must NOT spend the review
# rounds or the failed-attempt budget, or a PR that converged on content loses
# its review budget to rebase tries.
LEDGER="$S_DIRTY/linear-worker-attempts.json"
[ "$("$REAL_PY" -c "import json;print(json.load(open('$LEDGER'))['ASK-AAA'].get('conflict_rounds',0))")" = "1" ] \
  || fail "the conflict round was not recorded; nothing would ever reach the cap"
[ "$("$REAL_PY" -c "import json;print(json.load(open('$LEDGER'))['ASK-AAA'].get('count',0))")" = "0" ] \
  || fail "a rebase round burned the failed-attempt budget; the caps must be separate"
ok "conflict rounds are counted separately from failed attempts"

# --- F. at the cap: stop, and page EXACTLY once across repeated runs ----------
# Two scheduled runs, both at the cap. One page total. A "still stuck" line every
# cycle is noise, and noise trains the operator to skim the real pages.
S_CAP="$W2/state-cap"; mkdir -p "$S_CAP/pr-reviews"
printf '{"verdict":"APPROVE","pr":779}\n' > "$S_CAP/pr-reviews/pr-779.verdict.json"
printf '{"ASK-AAA":{"conflict_rounds":2}}\n' > "$S_CAP/linear-worker-attempts.json"
gh_says 779 DIRTY
: > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker "$S_CAP" "$W2/cap1.out"
run_worker "$S_CAP" "$W2/cap2.out"

[ ! -s "$W2/worked.txt" ] \
  || fail "the conflict cap did not hold: a rebase round was dispatched with the budget already spent.
      An unresolvable conflict would rework forever, writing a permanent Linear comment each round."
ok "at the cap the worker refuses to dispatch another rebase round"

# Pin WHY it refused. An absence-of-work assertion passes for any reason the
# worker declines, so on its own it cannot tell "the cap held" from "the fixture
# was broken and it skipped as unreviewed" -- the exact vacuous-test defect the
# round-3 review found in the prior art (finding 2).
grep -q "conflict round(s) -- a human resolves this one" "$W2/cap1.out" \
  || fail "the cap run skipped for the WRONG REASON. It must stop at the conflict cap,
      not at gate 20 (unreviewed). The worker said: $(grep -i skip "$W2/cap1.out" | head -1)"
ok "it stopped at the conflict cap, not as unreviewed"

PAGES="$(grep -c . "$W2/pages.txt" 2>/dev/null || echo 0)"
[ "$PAGES" = "1" ] \
  || fail "expected EXACTLY 1 page across 2 runs at the cap, got $PAGES: $(cat "$W2/pages.txt")"
grep -q "needs a human" "$W2/pages.txt" || fail "the page does not say a human is needed"
ok "exactly one page across two runs at the cap (no per-cycle noise)"

# --- G. approved + CLEAN must still be left alone ----------------------------
# The other half: this fix must not turn every approved PR into a rework loop.
S_OK="$W2/state-ok"; mkdir -p "$S_OK/pr-reviews"
printf '{"verdict":"APPROVE WITH NITS","pr":778}\n' > "$S_OK/pr-reviews/pr-778.verdict.json"
gh_says 778 CLEAN
: > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker "$S_OK" "$W2/ok.out"

[ ! -s "$W2/worked.txt" ] \
  || fail "an approved AND CLEAN PR was reworked; this fix must not loop on healthy PRs"
grep -q "nothing to rework, waiting on founder merge" "$W2/ok.out" \
  || fail "section G skipped for the WRONG REASON -- it must reach gate 10 (approved+clean),
      not gate 20 (unreviewed). The worker said: $(grep -i skip "$W2/ok.out" | head -1)"
[ ! -s "$W2/pages.txt" ] || fail "a healthy approved PR paged the founder: $(cat "$W2/pages.txt")"
ok "approved + CLEAN is left alone at gate 10, and pages nobody"

# --- a repo whose PR head lives ONLY on the remote branch --------------------
# Sections E-G run against a repo where main IS the branch, so "which start
# point did the worktree use" was unobservable there. Here origin/sana/ask-aaa
# carries a commit main does not have, and main has moved past the fork point --
# the real shape of an approved-but-DIRTY PR, and the only shape in which
# cutting a tree from origin/main is visibly destructive.
#
# ONE REPO PER SECTION: two worktrees in one repo cannot both hold
# sana/ask-aaa, and every section below needs its own tree.
make_repo() {
  local d="$1"
  mkdir -p "$d"
  git init -q --bare "$d/origin"
  git init -q "$d/skel"
  G -C "$d/skel" commit -q --allow-empty -m "base commit"
  git -C "$d/skel" branch -M main
  git -C "$d/skel" remote add origin "$d/origin"
  git -C "$d/skel" push -q -u origin main
  G -C "$d/skel" checkout -q -b sana/ask-aaa
  G -C "$d/skel" commit -q --allow-empty -m "the approved work (ASK-AAA)"
  git -C "$d/skel" push -q -u origin sana/ask-aaa
  G -C "$d/skel" checkout -q main
  # Drop the LOCAL branch: the PR's head now exists only as origin/sana/ask-aaa,
  # which is exactly the state after a worktree is swept between rounds.
  git -C "$d/skel" update-ref -d refs/heads/sana/ask-aaa
  G -C "$d/skel" commit -q --allow-empty -m "main moved underneath the PR"
  git -C "$d/skel" push -q origin main
}

# run_worker_in <skel> <state-dir> <out>
run_worker_in() {
  ( cd "$1" \
    && HOME="$W2/home" KIPI_SKEL="$1" KIPI_STATE_DIR="$2" \
       KIPI_NOTIFY="$W2/notify.sh" \
       bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) >"$3" 2>&1
  return 0
}

# --- H. a rebase round must be handed the PR's OWN commits -------------------
# PR #25 review, finding 1 (major). `git worktree add -B <branch> <tree>
# origin/main` RESETS the branch to origin/main. Before this line of work an
# approved PR never reached it (gate 10 was terminal); gate 30 routes one
# through it AND hands the agent a prompt that says `git push --force-with-lease
# origin <branch>`. A tree with none of the PR's commits plus that instruction
# wipes the approved diff off the remote, and --force-with-lease does not stop
# it: the worker's own `git fetch origin` refreshed origin/<branch> first, so
# the lease sees no surprise and allows the push.
R_HEAD="$W2/repo-head"; make_repo "$R_HEAD"
S_HEAD="$W2/state-head"; mkdir -p "$S_HEAD/pr-reviews"
printf '{"verdict":"APPROVE","pr":781}\n' > "$S_HEAD/pr-reviews/pr-781.verdict.json"
gh_says 781 DIRTY
: > "$W2/worked.txt"; : > "$W2/pages.txt"; : > "$W2/tree-log.txt"
run_worker_in "$R_HEAD/skel" "$S_HEAD" "$W2/head.out"

grep -q worked "$W2/worked.txt" 2>/dev/null \
  || fail "no rebase round was dispatched at all: $(grep -i skip "$W2/head.out" | head -1)"
grep -q "the approved work" "$W2/tree-log.txt" 2>/dev/null \
  || fail "DESTRUCTIVE: the rebase round was handed a worktree that does NOT contain PR #781's
      commits. The prompt tells that agent to force-push this tree over the branch, which
      deletes the approved diff from the remote. Tree contained:
$(sed 's/^/        /' "$W2/tree-log.txt")"
ok "the rebase round is handed a tree that contains the PR's own commits"

# The other half: it must be ON the branch, not on a detached head or main, or
# the force-push in the prompt has no branch to push.
grep -q "sana/ask-aaa" "$W2/head.out" \
  || fail "the run never names the branch it worked on"
[ "$(git -C "$S_HEAD/worktrees/ask-aaa" rev-parse --abbrev-ref HEAD 2>/dev/null)" = "sana/ask-aaa" ] \
  || fail "the worktree is not on sana/ask-aaa; the prompt's push has no branch to push"
ok "the worktree stands on the PR's branch"

# Finding 4: a rebased diff DOES get re-reviewed (the diff changed, so the old
# APPROVE no longer describes it). Pinned so a later "save the review budget"
# change cannot silently ship an unreviewed force-push.
LH="$S_HEAD/linear-worker-attempts.json"
[ "$("$REAL_PY" -c "import json;print(json.load(open('$LH'))['ASK-AAA'].get('rounds',0))")" = "1" ] \
  || fail "the rebased diff was not re-reviewed; a force-push nobody looked at ships under the OLD verdict"
ok "a rebase round's resulting diff is re-reviewed (round recorded)"

# --- I. a skipped run must not spend the conflict budget ---------------------
# PR #25 review, finding 2 (major). The bump used to run at the gate, before the
# worktree and before the claim. A stale claim (converge.sh's own documented
# 2026-07-27 scar: SIGKILL/timeout/sleep leaves a lock nobody reclaims) then
# burned the whole budget across two runs having dispatched ZERO rebase rounds,
# paged a count that never happened, and locked the issue out permanently.
R_STALE="$W2/repo-stale"; make_repo "$R_STALE"
S_STALE="$W2/state-stale"; mkdir -p "$S_STALE/pr-reviews" "$S_STALE/worktrees"
printf '{"verdict":"APPROVE","pr":782}\n' > "$S_STALE/pr-reviews/pr-782.verdict.json"
gh_says 782 DIRTY
git -C "$R_STALE/skel" worktree add -q -B sana/ask-aaa \
  "$S_STALE/worktrees/ask-aaa" origin/sana/ask-aaa 2>/dev/null \
  || fail "could not pre-create the worktree for the stale-claim case"
# A REAL lock, written by the real locker (fixture rule: never hand-roll the
# on-disk shape), held by a session that is gone.
( cd "$S_STALE/worktrees/ask-aaa" \
  && "$REAL_PY" "$ROOT/q-system/.q-system/scripts/linear-claim.py" claim ASK-AAA \
       --agent ghost --session ghost-dead-session ) >/dev/null 2>&1 \
  || fail "could not seed the stale claim"

: > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker_in "$R_STALE/skel" "$S_STALE" "$W2/stale1.out"
run_worker_in "$R_STALE/skel" "$S_STALE" "$W2/stale2.out"

grep -q "claimed by another session" "$W2/stale1.out" \
  || fail "section I did not hit the stale claim at all: $(grep -i skip "$W2/stale1.out" | head -1)"
LS="$S_STALE/linear-worker-attempts.json"
BURNED="$("$REAL_PY" -c "
import json
try: d=json.load(open('$LS'))
except Exception: d={}
print(d.get('ASK-AAA',{}).get('conflict_rounds',0))")"
[ "$BURNED" = "0" ] \
  || fail "two runs that dispatched NOTHING spent $BURNED/2 conflict round(s). The budget is
      gone before the work, so the issue is locked out with zero rebases tried."
ok "a run skipped by another session's claim spends no conflict round"

[ ! -s "$W2/pages.txt" ] \
  || fail "the founder was paged a rebase count that never happened: $(cat "$W2/pages.txt")"
ok "no page claiming rebase rounds that were never dispatched"

grep -q "dispatching rebase round" "$W2/stale1.out" \
  && fail "the log says it dispatched a rebase round on a run that skipped at the claim"
ok "the log does not announce a dispatch that did not happen"

# And the budget really is still there: release the dead session's lock, and the
# next run gets round 1 of 2, not 'a human resolves this one'.
( cd "$S_STALE/worktrees/ask-aaa" \
  && "$REAL_PY" "$ROOT/q-system/.q-system/scripts/linear-claim.py" release ASK-AAA \
       --agent ghost --session ghost-dead-session ) >/dev/null 2>&1
: > "$W2/worked.txt"
run_worker_in "$R_STALE/skel" "$S_STALE" "$W2/stale3.out"
grep -q "rebase round 1/" "$W2/stale3.out" \
  || fail "after the stale claim cleared, the issue did not get its first rebase round.
      The worker said: $(grep -iE 'skip|rebase' "$W2/stale3.out" | head -1)"
ok "once the claim clears, the full conflict budget is still available"

# --- J. the conflict budget is consecutive, not a lifetime total -------------
# PR #25 review, finding 3 (minor). Nothing reset the counter, so an issue that
# hit two conflicts across its life -- both successfully rebased -- could never
# be dispatched for a third, silently (conflict_paged was already true, so it
# did not even page).
R_CLEAR="$W2/repo-clear"; make_repo "$R_CLEAR"
S_CLEAR="$W2/state-clear"; mkdir -p "$S_CLEAR/pr-reviews"
printf '{"verdict":"APPROVE","pr":783}\n' > "$S_CLEAR/pr-reviews/pr-783.verdict.json"
printf '{"ASK-AAA":{"conflict_rounds":2,"conflict_paged":true}}\n' > "$S_CLEAR/linear-worker-attempts.json"
gh_says 783 CLEAN
: > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker_in "$R_CLEAR/skel" "$S_CLEAR" "$W2/clear.out"

grep -q "nothing to rework, waiting on founder merge" "$W2/clear.out" \
  || fail "section J skipped for the WRONG REASON; it must reach gate 10 (approved + CLEAN).
      The worker said: $(grep -i skip "$W2/clear.out" | head -1)"
LC="$S_CLEAR/linear-worker-attempts.json"
[ "$("$REAL_PY" -c "import json;print(json.load(open('$LC'))['ASK-AAA'].get('conflict_rounds',0))")" = "0" ] \
  || fail "the PR merges cleanly again and the conflict counter still reads spent. The cap is a
      LIFETIME total, so the next real conflict on this issue is un-dispatchable and silent."
[ "$("$REAL_PY" -c "import json;print(json.load(open('$LC'))['ASK-AAA'].get('conflict_paged',False))")" = "False" ] \
  || fail "the page flag survived the PR becoming mergeable, so a NEW conflict streak would
      stop the loop without ever telling the founder"
ok "a PR that merges cleanly again resets its conflict budget and its page flag"

# --- K. a tree cut by an OLDER run is repositioned, not abandoned ------------
# Section H covers the tree the worker cuts itself. This covers the one it
# INHERITS: $TREE already exists, cut from origin/main by a previous version, so
# it holds none of the PR's commits. Refusing forever would trade a destructive
# round for a permanently stalled issue, so a lossless move onto the PR's head
# has to actually happen -- and "lossless" must not be defeated by the worker's
# OWN claim file, which lands untracked inside the very tree being judged.
R_LEGACY="$W2/repo-legacy"; make_repo "$R_LEGACY"
S_LEGACY="$W2/state-legacy"; mkdir -p "$S_LEGACY/pr-reviews" "$S_LEGACY/worktrees"
printf '{"verdict":"APPROVE","pr":784}\n' > "$S_LEGACY/pr-reviews/pr-784.verdict.json"
gh_says 784 DIRTY
git -C "$R_LEGACY/skel" worktree add -q -B sana/ask-aaa \
  "$S_LEGACY/worktrees/ask-aaa" origin/main 2>/dev/null \
  || fail "could not pre-create the legacy worktree"
: > "$W2/worked.txt"; : > "$W2/pages.txt"; : > "$W2/tree-log.txt"
run_worker_in "$R_LEGACY/skel" "$S_LEGACY" "$W2/legacy.out"

grep -q "the approved work" "$W2/tree-log.txt" 2>/dev/null \
  || fail "an inherited worktree cut from origin/main was never moved onto PR #784's head.
      Either the round ran in a tree whose force-push deletes the PR, or the issue is now
      stalled every cycle. The worker said: $(grep -iE 'skip|rebase' "$W2/legacy.out" | head -1)
      Tree contained:
$(sed 's/^/        /' "$W2/tree-log.txt")"
ok "an inherited tree is repositioned onto the PR's head before the round"

[ ! -s "$W2/pages.txt" ] \
  || fail "a tree that could be repositioned safely paged the founder anyway: $(cat "$W2/pages.txt")"
ok "a repositionable tree costs the founder no page"

# --- wiring: the worker actually consults the merge state --------------------
grep -q 'pr_merge_state' "$WORKER" \
  || fail "linear-worker.sh never reads the merge state (the gate's second argument would be empty forever)"
grep -q 'MAX_CONFLICT_ROUNDS' "$WORKER" \
  || fail "linear-worker.sh has no conflict-round cap"
ok "worker wiring: merge state read through the lib, conflict cap present"

# =============================================================================
# THE VERDICT IS BOUND TO A SHA, NOT TO A PR NUMBER (ASK-216, sp-12f99480)
# =============================================================================
# THE DEFECT: the verdict record keyed on a PR NUMBER and carried no sha. The
# worker reuses one branch and one PR across rework rounds, so every push after
# an approval silently inherited that approval. Nothing in the record could tell
# "reviewed and approved" from "approved, then three more commits landed".
#
# OBSERVED 2026-07-27, the live record for PR #25:
#   {"pr":25,"issue":"ASK-212","verdict":"APPROVE WITH NITS", ... }  <- no sha
#
# Today that costs a stale skip. With an integrator on top it is an auto-merge
# of code no reviewer ever read, on a repo whose main fans out fleet-wide.
#
# THE SHAPE OF THE FIX: the writer pins the sha the review actually read, and
# the gate refuses to call an approval at a DIFFERENT sha terminal (exit 40 --
# re-review at the new head; never merge, never auto-approve).
SHA_A="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
SHA_B="ffeeddccbbaa99887766554433221100aabbccdd"

# gate_sha <want-rc> <verdict> <merge-state> <recorded-sha> <current-sha> <why>
# Never touches the live GitHub API: both shas are scripted, which is also the
# only way to hold "the head moved" still long enough to assert on it.
gate_sha() {
  local want="$1" verdict="$2" state="$3" rec="$4" cur="$5" why="$6" got
  rework_gate "$verdict" "$state" "$rec" "$cur" >/dev/null; got=$?
  [ "$got" = "$want" ] \
    || fail "rework_gate '$verdict' '$state' rec='$rec' cur='$cur' -> $got, want $want ($why)"
  ok "$why"
}

# --- L1. an approval at a sha that is no longer the head is NOT terminal -----
gate_sha 40 "APPROVE"           "CLEAN" "$SHA_A" "$SHA_B" \
  "approved at a sha that is no longer the head is stale, not terminal"
gate_sha 40 "APPROVE WITH NITS" "CLEAN" "$SHA_A" "$SHA_B" \
  "approve-with-nits at a stale sha is stale too"

# Drift wins over the merge state. Both are true here, and a rebase round on a
# diff nobody reviewed is the same unreviewed-code path wearing a rebase coat:
# re-review first, then the fresh record decides whether it is a rebase round.
gate_sha 40 "APPROVE"           "DIRTY" "$SHA_A" "$SHA_B" \
  "drift outranks DIRTY: re-review at the new head before any rebase round"

# --- L2. a matching sha keeps every one of today's outcomes ------------------
# The converged-PR half. Too strict here and every approved PR on the board
# re-reviews forever, burning model budget and writing a permanent Linear
# comment each round.
gate_sha 10 "APPROVE"           "CLEAN" "$SHA_A" "$SHA_A" \
  "a matching sha stays terminal (a converged PR does not re-review forever)"
gate_sha 10 "APPROVE WITH NITS" "CLEAN" "$SHA_A" "$SHA_A" \
  "approve-with-nits at the reviewed sha stays terminal"
gate_sha 30 "APPROVE"           "DIRTY" "$SHA_A" "$SHA_A" \
  "reviewed sha + DIRTY is still a rebase round (ASK-212 survives)"
gate_sha 10 "APPROVE"           "CLEAN" "ABC123DEF" "abc123def" \
  "sha comparison is case-insensitive (hex case is not drift)"

# A non-approving verdict already routes to rework; drift cannot make it worse,
# and must not change its code (the rework loop owns that PR either way).
gate_sha 0  "REQUEST CHANGES"   "CLEAN" "$SHA_A" "$SHA_B" \
  "drift does not change a REQUEST CHANGES verdict (already rework)"
gate_sha 20 ""                  "CLEAN" "$SHA_A" "$SHA_B" \
  "drift does not rescue an unreviewed PR from gate 20"

# --- L3. ABSENT is not DRIFT, and the gate says so --------------------------
# Every record written before this change lacks the field. Reading absent as
# drift would re-review every converged PR on the board at once. So absent falls
# back to today's behaviour -- and announces the blind spot instead of being
# silently grandfathered.
NOTE="$(rework_gate "APPROVE" "CLEAN" "" "$SHA_B")"; GOT=$?
[ "$GOT" = "10" ] \
  || fail "a record with NO head_sha must behave as it does today (got $GOT, want 10).
      Reading absent-as-drift re-reviews every pre-ASK-216 PR on the board at once."
ok "absent head_sha falls back to today's behaviour (no mass re-review)"

printf '%s' "$NOTE" | grep -qi 'head_sha' \
  || fail "the gate fell back on an unpinned verdict SILENTLY. The blind spot has to be
      stated on stdout, not grandfathered. It said: '$NOTE'"
ok "the gate names the unpinned-verdict blind spot on stdout"

# The mirror case: the record pins a sha but the CURRENT head could not be read
# (gh down, API slow). Same posture as ASK-212's empty merge state -- fail
# toward terminal, because a manufactured re-review round costs every PR in the
# fleet at once while a missed one costs a single human diagnosis.
NOTE2="$(rework_gate "APPROVE" "CLEAN" "$SHA_A" "")"; GOT=$?
[ "$GOT" = "10" ] \
  || fail "an unreadable current head manufactured a re-review round (got $GOT, want 10)"
printf '%s' "$NOTE2" | grep -qi 'head' \
  || fail "a failed head lookup was swallowed silently: '$NOTE2'"
ok "an unreadable current head does not manufacture a re-review round, and says so"

# The one- and two-argument forms are what converge.sh and linear-worker.sh call
# today, and this issue does not touch either file. They must be byte-identical
# in behaviour AND silent -- a note printed on every worker run is the cry-wolf
# failure, not a safety feature.
QUIET="$(rework_gate "APPROVE" "CLEAN")"; GOT=$?
[ "$GOT" = "10" ] || fail "two-arg rework_gate 'APPROVE' 'CLEAN' changed: got $GOT, want 10"
[ -z "$QUIET" ] || fail "the two-arg form now prints on every call: '$QUIET'. That is a line on
      every worker run for every PR, which trains the operator to skim the real ones."
QUIET1="$(rework_gate "APPROVE")"; GOT=$?
[ "$GOT" = "10" ] || fail "one-arg rework_gate 'APPROVE' changed: got $GOT, want 10"
[ -z "$QUIET1" ] || fail "the one-arg form (converge.sh) now prints on every call: '$QUIET1'"
ok "the one- and two-arg forms are unchanged and silent (converge.sh, linear-worker.sh)"

# --- L4. record -> gate chain, the way a consumer will actually use it -------
cat > "$W2/pr-901.verdict.json" <<EOF
{"pr": 901, "issue": "ASK-901", "verdict": "APPROVE", "head_sha": "$SHA_A",
 "review": "/tmp/x.md", "ts": "2026-07-27T05:00:00Z"}
EOF
[ "$(head_sha_from_record "$W2/pr-901.verdict.json")" = "$SHA_A" ] \
  || fail "head_sha round-trip out of the record failed"
rework_gate "$(verdict_from_record "$W2/pr-901.verdict.json")" CLEAN \
            "$(head_sha_from_record "$W2/pr-901.verdict.json")" "$SHA_B" >/dev/null
[ $? = 40 ] || fail "record -> gate chain: an approved record at a stale head must not be terminal"
ok "record -> gate chain: approved record + moved head -> re-review, not merge"

# A record written before this change (the whole board today) yields empty, and
# empty is the absent case above -- not a crash and not a drift claim.
[ -z "$(head_sha_from_record "$WORK/pr-99.verdict.json")" ] \
  || fail "a pre-ASK-216 record must yield an EMPTY head sha, never a guess"
ok "a pre-ASK-216 record (no head_sha key) reads as empty, not as drift"

[ -z "$(head_sha_from_record "$WORK/pr-98.verdict.json")" ] \
  || fail "a corrupt record must yield an empty head sha, not crash"
ok "a corrupt record reads as an empty head sha (fails closed, same as the verdict)"

# --- M. the WRITER pins the sha, asserted on the JSON it really produces -----
# Not a hand-rolled fixture: the real pr-review-agent.sh runs end to end with
# `gh` and `claude` stubbed, and the assertion is on the record it wrote. The
# fixture rule (test-linear-claim.sh scar) is exactly this -- a record shaped by
# the same mind as the reader proves nothing.
#
# ISOLATION: HOME is redirected so OUT_DIR lands in the temp tree, and the
# stubbed review derives APPROVE with an EMPTY findings block, so the spillover
# capture path (live ledger) is never entered.
SW="$W2/stub-writer"; mkdir -p "$SW" "$W2/home-writer"
# The section-E stub set swallows `python3 -` (it fakes the ready-issues query),
# and the record writer IS a `python3 -` heredoc. So this section needs a real
# python3 ahead of it on PATH.
cat > "$SW/python3" <<EOF
#!/usr/bin/env bash
exec "$REAL_PY" "\$@"
EOF
cat > "$SW/gh" <<EOF
#!/usr/bin/env bash
case "\$*" in
  "pr view 901 --json"*) printf '$SHA_A\tpin the sha the review actually read\n' ;;
  *) exit 1 ;;
esac
exit 0
EOF
cat > "$SW/claude" <<'EOF'
#!/usr/bin/env bash
printf '## VERDICT: APPROVE\n\nNothing survived reproduction.\n\nFINDINGS:\nEND FINDINGS\n'
EOF
chmod +x "$SW/python3" "$SW/gh" "$SW/claude"

( PATH="$SW:$PATH" HOME="$W2/home-writer" bash "$REVIEWER" 901 ) >"$W2/writer.out" 2>&1
REC="$W2/home-writer/.config/kipi/pr-reviews/pr-901.verdict.json"
[ -s "$REC" ] \
  || fail "the reviewer wrote no verdict record at all. It said:
$(sed 's/^/        /' "$W2/writer.out")"

[ "$("$REAL_PY" -c "import json;print('head_sha' in json.load(open('$REC')))")" = "True" ] \
  || fail "THE DEFECT: the record the REAL writer just produced has NO head_sha key, so the
      approval binds to a PR number and any later push inherits it. Record was:
$(sed 's/^/        /' "$REC")"
ok "the writer's record carries a head_sha key"

[ "$("$REAL_PY" -c "import json;print(json.load(open('$REC')).get('head_sha',''))")" = "$SHA_A" ] \
  || fail "the record pinned the wrong sha: got
      '$("$REAL_PY" -c "import json;print(json.load(open('$REC')).get('head_sha',''))")', want '$SHA_A'"
ok "the pinned sha is the head the reviewer was pointed at"

# The sha must be read BEFORE the reviewer runs, from the state it reads. Looked
# up afterwards, a push landing mid-review makes the record claim a commit the
# reviewer never saw -- worse than no sha, because it looks authoritative.
SHA_LINE="$(grep -n 'headRefOid' "$REVIEWER" | head -1 | cut -d: -f1)"
RUN_LINE="$(grep -n 'run_bounded "\$TIMEOUT_SECONDS"' "$REVIEWER" | head -1 | cut -d: -f1)"
[ -n "$SHA_LINE" ] || fail "pr-review-agent.sh never reads headRefOid; it cannot pin a sha"
[ -n "$RUN_LINE" ] || fail "could not find the reviewer dispatch line to order against"
[ "$SHA_LINE" -lt "$RUN_LINE" ] \
  || fail "the head sha is captured AFTER the reviewer runs (line $SHA_LINE vs $RUN_LINE). A push
      landing mid-review would make the record claim a commit the reviewer never read."
ok "the head sha is captured before the review is taken, not looked up afterwards"

# --- N. the verdict leaves the machine as a COMMIT STATUS (ASK-217) ----------
# THE DEFECT: the verdict is a LOCAL file (~/.config/kipi/pr-reviews/...json).
# GitHub cannot see it, so no required check can gate on it, so every approved
# PR ends its life waiting on a human. Same harness as section M -- the REAL
# pr-review-agent.sh runs end to end with `gh` and `claude` stubbed and HOME
# redirected -- and every assertion below is on the gh CALL LOG, never on stdout
# prose. "posted" printed while nothing left the machine is this repo's whole
# defect class (something fails while reporting success), so the prose is not
# admissible evidence here.
#
# A commit STATUS, not a PR review: this agent runs as the account that authors
# these PRs and GitHub forbids self-approval, so a review would deadlock.
STATUS_CONTEXT="kipi/reviewer-approved"
COMMENT_URL_FIXTURE="https://github.com/o/r/pull/901#issuecomment-4242"

# $1 dir  $2 review body the stubbed reviewer emits  $3 headRefOid gh reports
# $4 "fail-status"  => the status POST exits non-zero
#    "fail-comment" => `gh pr comment` exits non-zero, so there is no URL to thread
mk_status_stubs() {
  local d="$1" body="$2" oid="$3" mode="${4:-}"
  mkdir -p "$d/bin" "$d/home"
  : > "$d/gh-calls.log"
  printf '%s' "$body" > "$d/review-body.txt"
  # Section E's stub set swallows `python3 -`, and the record writer IS a
  # `python3 -` heredoc, so a real python3 has to sit ahead of it on PATH.
  cat > "$d/bin/python3" <<EOF
#!/usr/bin/env bash
exec "$REAL_PY" "\$@"
EOF
  cat > "$d/bin/claude" <<EOF
#!/usr/bin/env bash
cat "$d/review-body.txt"
EOF
  cat > "$d/bin/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$d/gh-calls.log"
case "\$1 \$2" in
  "pr view")    printf '$oid\tstatus emission under test\n' ;;
  "pr comment") [ "$mode" = "fail-comment" ] && exit 1
                printf '$COMMENT_URL_FIXTURE\n' ;;
  "api -X")     [ "$mode" = "fail-status" ] && exit 1
                printf '{"context":"$STATUS_CONTEXT","state":"ok"}\n' ;;
esac
exit 0
EOF
  chmod +x "$d/bin/python3" "$d/bin/claude" "$d/bin/gh"
}

# Sets RC and writes out.txt / err.txt SEPARATELY: check 4 asserts the failure
# WARN reaches stderr specifically, which a combined redirect cannot tell apart.
RC=0
run_status_reviewer() {
  local d="$1"; shift
  ( PATH="$d/bin:$PATH" HOME="$d/home" bash "$REVIEWER" 901 "$@" ) \
    >"$d/out.txt" 2>"$d/err.txt"
  RC=$?
}

status_call() { grep 'statuses/' "$1/gh-calls.log" 2>/dev/null | head -1; }

APPROVE_REVIEW='## VERDICT: APPROVE

Nothing survived reproduction.

FINDINGS:
END FINDINGS
'
BLOCKED_REVIEW='## VERDICT: REQUEST CHANGES

FINDINGS:
major|the retry loop drops the last error|q-system/x.sh:12
END FINDINGS
'

# N1. an APPROVE under --post emits success on the sha the reviewer READ.
N1="$W2/st-approve"
mk_status_stubs "$N1" "$APPROVE_REVIEW" "$SHA_A"
run_status_reviewer "$N1" --post
CALL="$(status_call "$N1")"
[ -n "$CALL" ] || fail "THE DEFECT: the reviewer approved PR #901 and posted NOTHING to GitHub. The
      verdict stayed a local file, so no required check can ever read it and the PR waits on a
      human forever. gh was called with:
$(sed 's/^/        /' "$N1/gh-calls.log")"
ok "an approving review posts a commit status to GitHub"

printf '%s' "$CALL" | grep -q "statuses/$SHA_A" \
  || fail "the status went to the wrong sha. The stub's headRefOid was $SHA_A; the call was:
      $CALL
      A status on a sha the reviewer never read is worse than none -- it looks authoritative."
ok "the status is posted on the exact sha the reviewer read (the stub's headRefOid)"

printf '%s' "$CALL" | grep -q "context=$STATUS_CONTEXT" \
  || fail "the status carries the wrong context; 5b makes '$STATUS_CONTEXT' required and a
      mismatch would block every PR forever. Call was: $CALL"
printf '%s' "$CALL" | grep -q 'state=success' \
  || fail "an APPROVE did not map to state=success. Call was: $CALL"
ok "APPROVE maps to state=success on context $STATUS_CONTEXT"

printf '%s' "$CALL" | grep -q "target_url=$COMMENT_URL_FIXTURE" \
  || fail "the status did not carry the PR-comment URL --post had just created, so a human
      clicking the check lands nowhere. Call was: $CALL"
ok "target_url is the PR comment URL --post actually created"

# N2. a gate that can only ever say success is not a gate.
N2="$W2/st-block"
mk_status_stubs "$N2" "$BLOCKED_REVIEW" "$SHA_A"
run_status_reviewer "$N2" --post
CALL="$(status_call "$N2")"
[ -n "$CALL" ] || fail "a REQUEST CHANGES review posted no status at all; the PR would look
      unreviewed rather than refused"
printf '%s' "$CALL" | grep -q 'state=failure' \
  || fail "REQUEST CHANGES did not map to state=failure. A reviewer that only ever posts success
      is a gate that cannot refuse. Call was: $CALL"
printf '%s' "$CALL" | grep -q 'state=success' \
  && fail "a REQUEST CHANGES review posted state=success. Call was: $CALL"
ok "REQUEST CHANGES maps to state=failure (the gate can refuse)"

# N3. --post means "write to the outside world". A human running `kipi review 23`
# for a dry read must not move a gate on a real PR.
N3="$W2/st-nopost"
mk_status_stubs "$N3" "$APPROVE_REVIEW" "$SHA_A"
run_status_reviewer "$N3"
[ -z "$(status_call "$N3")" ] \
  || fail "a run WITHOUT --post moved a gate on a live PR. gh calls were:
$(sed 's/^/        /' "$N3/gh-calls.log")"
ok "without --post no status call is made (a dry read moves nothing)"

# N4. a lost status must not lose the review, and must not be silent.
N4="$W2/st-ghfail"
mk_status_stubs "$N4" "$APPROVE_REVIEW" "$SHA_A" fail-status
run_status_reviewer "$N4" --post
[ "$RC" = "0" ] \
  || fail "a failed status POST took the whole review down (exit $RC). The verdict record is the
      loop's hand-off; losing it to a transient GitHub error costs a full re-review."
[ -s "$N4/home/.config/kipi/pr-reviews/pr-901.verdict.json" ] \
  || fail "a failed status POST cost the verdict record, which converge.sh and linear-worker.sh
      both read"
grep -q "$SHA_A" "$N4/err.txt" \
  || fail "a failed status POST did not name the sha on stderr. Operator output was:
$(sed 's/^/        /' "$N4/err.txt")"
grep -q "$STATUS_CONTEXT" "$N4/err.txt" \
  || fail "a failed status POST did not name the context on stderr; the operator cannot tell
      WHICH gate did not move. stderr was:
$(sed 's/^/        /' "$N4/err.txt")"
grep -qi 'warn' "$N4/err.txt" \
  || fail "a failed status POST was not flagged as a WARN on stderr"
grep -qi 'status.*posted\|posted.*status' "$N4/out.txt" \
  && fail "the run reported the status as POSTED while the POST failed. That is this repo's
      defect class exactly. stdout was:
$(sed 's/^/        /' "$N4/out.txt")"
ok "a failed status POST is loud on stderr, keeps the record, and exits 0"

# N5. no sha, no status. A status on a guessed commit looks authoritative and is
# the one outcome worse than posting nothing.
N5="$W2/st-nosha"
mk_status_stubs "$N5" "$APPROVE_REVIEW" ""
run_status_reviewer "$N5" --post
[ -z "$(status_call "$N5")" ] \
  || fail "with an EMPTY headRefOid the reviewer still posted a status, so it guessed a sha.
      gh calls were:
$(sed 's/^/        /' "$N5/gh-calls.log")"
grep -qi 'head sha' "$N5/out.txt" \
  || fail "the reviewer skipped the status silently on an empty head sha. Absent must be SAID,
      because once the context is required, absent is what holds the PR. stdout was:
$(sed 's/^/        /' "$N5/out.txt")"
ok "an empty head sha posts no status at all, and says so"

# N6. the comment URL is threaded, never invented. A local file path is not a URL.
N6="$W2/st-nourl"
mk_status_stubs "$N6" "$APPROVE_REVIEW" "$SHA_A" fail-comment
run_status_reviewer "$N6" --post
CALL="$(status_call "$N6")"
[ -n "$CALL" ] || fail "a failed PR comment took the status down with it; the comment and the
      gate are independent"
printf '%s' "$CALL" | grep -q 'target_url=' \
  && fail "with no comment URL available the reviewer invented a target_url: $CALL"
ok "no comment URL means no target_url (omitted, not invented)"

bash -n "$REVIEWER" || fail "pr-review-agent.sh does not parse"
ok "the reviewer parses (bash -n)"

bash -n "$LIB" || fail "pr-verdict-lib.sh does not parse"
ok "the lib parses (bash -n)"

echo "PASS: $PASS/$PASS severity-floor checks"
