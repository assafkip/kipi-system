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

# The short form is the gate's DEFAULT semantics: no merge state supplied reads
# as "still merges". converge.sh called it this way until ASK-219 (it now passes
# four arguments, section O), so this is no longer pinned to a live caller -- it
# pins the contract every future caller inherits, and a silent change to it would
# be a fleet-wide bug found by nobody.
rework_gate "APPROVE"; [ $? = 10 ] || fail "one-arg rework_gate 'APPROVE' no longer returns 10"
rework_gate "REQUEST CHANGES"; [ $? = 0 ] || fail "one-arg rework_gate 'REQUEST CHANGES' no longer returns 0"
ok "the one-argument form keeps its original default semantics"

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
# THE PROMPT ITSELF, same first-writer-wins reasoning (PR #30 review, major 1).
# WHICH prompt the worker hands the work-phase agent is the whole difference
# between a drift round and a rework round, and it was previously unobservable
# from outside the script -- so "gate 40 sends the review-answering prompt at an
# approving review with no findings" could only ever be found by reading source.
if [ ! -s "$W2/prompt.txt" ]; then
  printf '%s\n' "\$*" > "$W2/prompt.txt"
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

# gh_says <pr> <mergeStateStatus> [headRefOid]
# The third argument is OPTIONAL and defaults to empty, so every pre-ASK-219
# caller below keeps reporting an unreadable head -- which is the state the whole
# board was in before the writer started pinning shas. Sections E-K therefore
# assert the same outcomes on the same inputs after the callers grew their sha
# arguments, which is the point: absent must not become drift.
gh_says() {
  cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
case "\$*" in
  "pr list"*)                                  echo $1 ;;
  "pr view $1 --json mergeStateStatus"*)       echo $2 ;;
  "pr view $1 --json headRefOid"*)             echo ${3:-} ;;
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
# "nothing to rework" and not the merge half of the sentence: gate 10 now reports
# the arm state (ASK-222), so pinning "waiting on founder merge" here would pin
# the misstatement this issue removed. What section G is about is WHICH GATE the
# skip came from, and that is what this anchors.
grep -q "nothing to rework" "$W2/ok.out" \
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

# gate-10 anchor only: the merge half of this sentence now reports the arm state (ASK-222)
grep -q "nothing to rework" "$W2/clear.out" \
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

# The one- and two-argument forms were what converge.sh and linear-worker.sh
# called before ASK-219 wired the sha through (both now pass four; section O).
# They must stay byte-identical in behaviour AND silent -- a note printed on
# every call is the cry-wolf failure, not a safety feature, and silence is what
# lets a caller adopt the short form without adding a line to every run.
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
  # A CODEX STUB IS MANDATORY HERE, not belt-and-braces. These cases drive the
  # reviewer with NO --engine flag, and the default engine is codex, so without
  # this stub the real `codex` binary on the ambient PATH gets shelled: billed
  # live calls on a developer laptop, and in CI a failure that falls through to
  # the Opus fallback so every assertion below would pass for the WRONG reason
  # (DEGRADED path, not the path under test). Same body as the claude stub, so
  # the review content -- and therefore every verdict assertion -- is unchanged.
  cat > "$d/bin/codex" <<EOF
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
  chmod +x "$d/bin/python3" "$d/bin/claude" "$d/bin/codex" "$d/bin/gh"
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

# =============================================================================
# THE CALLERS PASS THE SHA (ASK-219, sp-a27722e7)
# =============================================================================
# THE DEFECT: ASK-216 shipped the drift check above and NOTHING ever called it
# with the arguments that arm it. converge.sh passed ONE argument and
# linear-worker.sh TWO, so exit 40 could not fire on any real code path. Section
# L proves the reader is right; it cannot prove anyone reads it, and a reader
# with no caller is the wiring-check defect class -- text in a file is not
# wiring.
#
# OBSERVED 2026-07-28 on the live board, not hypothetical:
#   pr-27.verdict.json  "verdict":"APPROVE WITH NITS"  "head_sha":"bf641ad8..."
#   git push origin sana/ask-215                       -> new head c063c3dd
#   ./kipi converge --issue ASK-215 --max-rounds 2
#   00:27:09Z converge[ASK-215] DONE exit-1: PR #27 verdict 'APPROVE WITH NITS'
#                               after 1 round(s). Waiting on founder merge only.
# Three seconds to call an approval of a commit nobody had read terminal.
#
# So both drivers are run FOR REAL below, with `gh` stubbed. Re-testing the lib
# would pass on exactly the code that shipped broken.
CONV="$ROOT/q-system/.q-system/scripts/converge.sh"
[ -f "$CONV" ] || fail "converge.sh does not exist at $CONV"

# The fake worker. converge dispatches a round, THEN gates on the verdict record,
# which each case seeds -- so the gate is what is under test and a real worker
# would only bury it under an hour of model spend.
cat > "$STUB/convworker" <<EOF
#!/usr/bin/env bash
printf 'dispatched\n' >> "$W2/converge-dispatch.txt"
exit 0
EOF
chmod +x "$STUB/convworker"

CRC=0
# run_converge <state-dir> <out> [max-rounds]
run_converge() {
  ( cd "$W2/skel" \
    && HOME="$W2/home" KIPI_STATE_DIR="$1" KIPI_NOTIFY="$W2/notify.sh" \
       KIPI_CONVERGE_WORKER="$STUB/convworker" \
       bash "$CONV" --issue ASK-AAA --max-rounds "${3:-1}" ) >"$2" 2>&1
  CRC=$?
}

# seed_record <state-dir> <pr> <verdict> [head_sha]
# Omitting the sha writes the shape EVERY record on the board had before
# ASK-216, which case O3 needs to stay exactly as it is today.
seed_record() {
  mkdir -p "$1/pr-reviews"
  if [ -n "${4:-}" ]; then
    printf '{"verdict":"%s","pr":%s,"head_sha":"%s"}\n' "$3" "$2" "$4" \
      > "$1/pr-reviews/pr-$2.verdict.json"
  else
    printf '{"verdict":"%s","pr":%s}\n' "$3" "$2" > "$1/pr-reviews/pr-$2.verdict.json"
  fi
}

# --- O1. converge: an approval at a stale sha is NOT terminal ----------------
# THE REPRODUCER. Exit code, not log prose: 1 is converge's "goal met, waiting on
# the founder" and it is the wrong answer here, because the head carries code no
# reviewer has read. With a 1-round cap the right answer is 2 (cap reached still
# unconverged) -- another round was needed and the budget ran out, which is
# honest, where exit 1 is a lie.
S_DRIFT="$W2/state-drift"; mkdir -p "$S_DRIFT"
seed_record "$S_DRIFT" 801 "APPROVE WITH NITS" "$SHA_A"
gh_says 801 CLEAN "$SHA_B"
: > "$W2/converge-dispatch.txt"; : > "$W2/pages.txt"
run_converge "$S_DRIFT" "$W2/conv-drift.out" 1

[ "$CRC" != "1" ] \
  || fail "THE DEFECT: converge exited 1 (goal met) on PR #801, whose approval was recorded at
      $SHA_A while the head is $SHA_B. It called an approval of code
      nobody reviewed terminal. Under auto-merge that merges unreviewed code fleet-wide. It said:
$(sed 's/^/        /' "$W2/conv-drift.out")"
[ "$CRC" = "2" ] \
  || fail "converge exited $CRC on a stale approval; expected 2 (the round cap, still unconverged).
      Any other code means it stopped for a reason this case did not set up. It said:
$(sed 's/^/        /' "$W2/conv-drift.out")"
ok "converge: an approval at a stale sha does not exit 1 (goal met)"

grep -qi "waiting on founder merge" "$W2/conv-drift.out" \
  && fail "converge still told the operator a PR with unreviewed code at its head was merely
      waiting on the founder"
ok "converge does not report a stale approval as waiting on the founder"

# Pin WHY it did not converge. Without this the case passes for any reason
# converge declines -- the vacuous-test defect the PR #25 round-3 review found.
grep -q "$SHA_A" "$W2/conv-drift.out" && grep -q "$SHA_B" "$W2/conv-drift.out" \
  || fail "converge did not name BOTH the reviewed sha and the current head, so an operator
      reading the log cannot tell drift from any other non-convergence. It said:
$(sed 's/^/        /' "$W2/conv-drift.out")"
ok "converge names the reviewed sha and the head it drifted to"

# --- O2. converge: a MATCHING sha still converges ----------------------------
# The cry-wolf half, and it matters as much as the catch: too strict here and
# every approved PR on the board re-reviews forever, burning model budget and
# writing a permanent Linear comment every round.
S_SAME="$W2/state-same"; mkdir -p "$S_SAME"
seed_record "$S_SAME" 802 "APPROVE WITH NITS" "$SHA_A"
gh_says 802 CLEAN "$SHA_A"
: > "$W2/converge-dispatch.txt"; : > "$W2/pages.txt"
run_converge "$S_SAME" "$W2/conv-same.out" 1

[ "$CRC" = "1" ] \
  || fail "a converged PR (approved at the sha that IS the head) no longer exits 1: got $CRC.
      This fix must not turn every approved PR into an endless re-review. It said:
$(sed 's/^/        /' "$W2/conv-same.out")"
grep -q "DONE exit-1" "$W2/conv-same.out" \
  || fail "converge exited 1 without the terminal message; it converged for the wrong reason"
# THE SECOND REPORTER OF THE SAME STATE (PR #33 review, finding 2, one layer out).
# converge's terminal line and its page are what the operator actually reads at
# 3am -- it is the half of this pair that Slacks. Both said the PR was "waiting on
# founder merge" / "ready to merge", which was true only while nothing armed
# auto-merge. Fixing the worker's closing line and leaving converge's would put
# the pre-fix picture on the founder's phone and the fixed one in a log file.
grep -qi "waiting on founder merge\|waits on founder merge\|ready to merge" "$W2/conv-same.out" \
  && fail "converge still closes an approved PR by telling the operator a founder must merge it.
      The worker armed auto-merge before this line ran; GitHub merges it. It said:
$(sed 's/^/        /' "$W2/conv-same.out")"
grep -qi "waiting on founder merge\|ready to merge" "$W2/pages.txt" \
  && fail "converge's PAGE -- the line that reaches the founder's phone -- still says a human owes
      this PR a merge: $(cat "$W2/pages.txt")"
grep -qi "auto-merge" "$W2/conv-same.out" \
  || fail "converge's terminal line never names auto-merge, so it does not say what does own the
      merge now that no founder does. It said:
$(sed 's/^/        /' "$W2/conv-same.out")"
ok "converge: an approval at the sha that IS the head still converges (no cry-wolf)"
ok "converge's terminal line and page name auto-merge as the merge path, not a founder"

# --- O3. converge: a record with NO head_sha behaves as today, and says so ----
# Every record written before ASK-216 lacks the field. Reading absent as drift
# would re-review the entire board at once.
S_NOSHA="$W2/state-nosha"; mkdir -p "$S_NOSHA"
seed_record "$S_NOSHA" 803 "APPROVE"
gh_says 803 CLEAN "$SHA_B"
: > "$W2/converge-dispatch.txt"
run_converge "$S_NOSHA" "$W2/conv-nosha.out" 1

[ "$CRC" = "1" ] \
  || fail "a pre-ASK-216 record (no head_sha) changed converge's answer: got $CRC, want 1.
      Absent is not drift; reading it that way re-reviews every PR on the board at once."
grep -qi 'head_sha' "$W2/conv-nosha.out" \
  || fail "converge fell back on an unpinned verdict SILENTLY. The blind spot has to reach the
      operator, not be grandfathered. It said:
$(sed 's/^/        /' "$W2/conv-nosha.out")"
ok "converge: an unpinned record behaves as today AND names the blind spot"

# --- O4. converge: an unreadable head falls toward terminal, and says so ------
# Same posture as ASK-212's empty merge state. A manufactured re-review round
# costs every PR in the fleet at once; a missed one costs one human diagnosis.
S_GHDOWN="$W2/state-ghdown"; mkdir -p "$S_GHDOWN"
seed_record "$S_GHDOWN" 804 "APPROVE" "$SHA_A"
gh_says 804 CLEAN ""
: > "$W2/converge-dispatch.txt"
run_converge "$S_GHDOWN" "$W2/conv-ghdown.out" 1

[ "$CRC" = "1" ] \
  || fail "an unreadable current head manufactured a non-terminal round in converge: got $CRC, want 1"
grep -qi 'head' "$W2/conv-ghdown.out" \
  || fail "converge swallowed a failed head lookup silently:
$(sed 's/^/        /' "$W2/conv-ghdown.out")"
ok "converge: an unreadable head does not manufacture a round, and says so"

# --- O5. the WORKER dispatches on drift instead of skipping as done ----------
# The second caller. It passes $MERGE_STATE as argument 2 already, so this is the
# case that proves the sha arguments were appended rather than inserted.
R_DRIFT="$W2/repo-drift"; make_repo "$R_DRIFT"
S_WDRIFT="$W2/state-wdrift"; mkdir -p "$S_WDRIFT"
seed_record "$S_WDRIFT" 805 "APPROVE WITH NITS" "$SHA_A"
gh_says 805 CLEAN "$SHA_B"
: > "$W2/worked.txt"; : > "$W2/pages.txt"; : > "$W2/tree-log.txt"
run_worker_in "$R_DRIFT/skel" "$S_WDRIFT" "$W2/wdrift.out"

grep -q worked "$W2/worked.txt" 2>/dev/null \
  || fail "THE DEFECT, worker half: PR #805 is approved at $SHA_A but the head is
      $SHA_B, and the worker skipped it as done. The code at the head is
      unreviewed and nothing in the loop will ever look at it. It said:
      $(grep -i skip "$W2/wdrift.out" | head -1)"
ok "worker: a stale approval is dispatched, not skipped as done"

# gate-10 anchor only: the merge half of this sentence now reports the arm state (ASK-222)
grep -q "nothing to rework" "$W2/wdrift.out" \
  && fail "the worker still reported a PR with unreviewed code at its head as waiting on the founder"
ok "worker: a stale approval is not reported as waiting on the founder"

grep -q "$SHA_A" "$W2/wdrift.out" && grep -q "$SHA_B" "$W2/wdrift.out" \
  || fail "the worker dispatched without naming the reviewed sha and the head, so the operator
      cannot tell a drift round from an ordinary rework round. It said:
$(sed 's/^/        /' "$W2/wdrift.out")"
ok "worker: the drift dispatch names the reviewed sha and the head"

# --- O6. the worker still leaves a CONVERGED PR alone ------------------------
S_WSAME="$W2/state-wsame"; mkdir -p "$S_WSAME"
seed_record "$S_WSAME" 806 "APPROVE WITH NITS" "$SHA_A"
gh_says 806 CLEAN "$SHA_A"
: > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker "$S_WSAME" "$W2/wsame.out"

[ ! -s "$W2/worked.txt" ] \
  || fail "an approved PR at the sha that IS the head was reworked; this fix must not loop on
      healthy PRs"
# gate-10 anchor only: the merge half of this sentence now reports the arm state (ASK-222)
grep -q "nothing to rework" "$W2/wsame.out" \
  || fail "the worker skipped PR #806 for the WRONG REASON -- it must reach gate 10, not gate 20.
      It said: $(grep -i skip "$W2/wsame.out" | head -1)"
[ ! -s "$W2/pages.txt" ] || fail "a converged PR paged the founder: $(cat "$W2/pages.txt")"
ok "worker: a converged PR at the reviewed sha is still left alone at gate 10"

# --- O7. the worker's argument ORDER survived: merge state is still arg 2 -----
# A reviewed sha that MATCHES plus DIRTY must still be gate 30. If the sha
# arguments had been inserted ahead of the merge state instead of appended, this
# would fall to gate 10 and ASK-212 would silently regress.
R_ORDER="$W2/repo-order"; make_repo "$R_ORDER"
S_ORDER="$W2/state-order"; mkdir -p "$S_ORDER"
seed_record "$S_ORDER" 807 "APPROVE" "$SHA_A"
gh_says 807 DIRTY "$SHA_A"
: > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker_in "$R_ORDER/skel" "$S_ORDER" "$W2/worder.out"

grep -q "rebase round 1/" "$W2/worder.out" \
  || fail "ASK-212 REGRESSED: an approved PR at the reviewed sha that GitHub reports DIRTY no
      longer gets a rebase round. The merge state stopped landing in argument 2. It said:
$(sed 's/^/        /' "$W2/worder.out")"
ok "worker: the merge state still lands in argument 2 (ASK-212 intact)"

# --- O8. drift OUTRANKS the merge state, end to end --------------------------
# Both fire. A rebase round dispatched on a diff nobody reviewed is the same
# unreviewed-code path wearing a rebase coat, so the re-review has to win and the
# fresh record then decides whether a rebase round is needed.
R_BOTH="$W2/repo-both"; make_repo "$R_BOTH"
S_BOTH="$W2/state-both"; mkdir -p "$S_BOTH"
seed_record "$S_BOTH" 808 "APPROVE" "$SHA_A"
gh_says 808 DIRTY "$SHA_B"
: > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker_in "$R_BOTH/skel" "$S_BOTH" "$W2/wboth.out"

grep -q worked "$W2/worked.txt" 2>/dev/null \
  || fail "neither the drift nor the conflict path dispatched anything: $(grep -i skip "$W2/wboth.out" | head -1)"
grep -q "dispatching rebase round" "$W2/wboth.out" \
  && fail "a rebase round was dispatched on a diff nobody reviewed. Drift must be resolved first;
      the fresh review then decides whether this is also a conflict."
LB="$S_BOTH/linear-worker-attempts.json"
[ "$("$REAL_PY" -c "
import json
try: d=json.load(open('$LB'))
except Exception: d={}
print(d.get('ASK-AAA',{}).get('conflict_rounds',0))")" = "0" ] \
  || fail "a drift round spent the CONFLICT budget. The two are separate budgets; spending the
      rebase budget on re-reviews makes a real conflict un-dispatchable later."
ok "worker: drift outranks DIRTY and spends no conflict round"

# =============================================================================
# WHAT THE DRIFT ROUND ACTUALLY DOES (PR #30 review round 2, ASK-219)
# =============================================================================
# Section O proves exit 40 now FIRES on both real call sites. It says nothing
# about what the round it dispatches then does, and that is where round 2 of the
# review found three defects: the round carried the review-answering prompt at a
# review with NO findings, it had no budget and never paged, and the run closed
# by reporting CONVERGED off the same stale record it had just refused to trust.
#
# Every case below needs the REVIEWER to be down, because that is the state all
# three live in: the drift only persists when nothing rewrites the record. The
# real reviewer costs an adversarial review per case, so linear-worker.sh gained
# KIPI_PR_REVIEWER -- the same seam converge.sh already has for its worker.
cat > "$STUB/reviewer-down" <<'EOF'
#!/usr/bin/env bash
echo "reviewer is down" >&2
exit 1
EOF
# The healthy half: writes a record pinned to the head it just read, which is the
# ONLY thing that clears drift. Needed to prove the drift streak ENDS.
cat > "$STUB/reviewer-ok" <<EOF
#!/usr/bin/env bash
PR="\$1"
SHA="\$(gh pr view "\$PR" --json headRefOid -q .headRefOid 2>/dev/null)"
mkdir -p "\$KIPI_STATE_DIR/pr-reviews"
printf '{"verdict":"APPROVE","pr":%s,"head_sha":"%s"}\n' "\$PR" "\$SHA" \
  > "\$KIPI_STATE_DIR/pr-reviews/pr-\$PR.verdict.json"
exit 0
EOF
chmod +x "$STUB/reviewer-down" "$STUB/reviewer-ok"

# run_worker_rev <skel> <state-dir> <out> <reviewer>
run_worker_rev() {
  ( cd "$1" \
    && HOME="$W2/home" KIPI_SKEL="$1" KIPI_STATE_DIR="$2" \
       KIPI_NOTIFY="$W2/notify.sh" KIPI_PR_REVIEWER="$4" \
       bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) >"$3" 2>&1
  return 0
}

ledger_key() {  # ledger_key <state-dir> <key>
  "$REAL_PY" -c "
import json
try: d=json.load(open('$1/linear-worker-attempts.json'))
except Exception: d={}
print(d.get('ASK-AAA',{}).get('$2',0))"
}

# --- P1. the drift round must NOT carry the review-answering prompt ----------
# linear-worker.sh's own comment above the prompt selector says why: 'handing the
# agent "the review is the spec, answer every finding" against a review with no
# findings is how ASK-208 rounds 1 and 2 both did code polish while the conflict
# went untouched.' Gate 30 got its own prompt for exactly that reason; gate 40
# fell through to the rework prompt. The most common drift producer is a HUMAN
# (a founder push, GitHub's "Update branch"), so at 3am this dispatched a 1800s
# model round told to answer findings that do not exist, on top of someone
# else's commit, pushing to the same branch.
R_P1="$W2/repo-p1"; make_repo "$R_P1"
S_P1="$W2/state-p1"; mkdir -p "$S_P1"
seed_record "$S_P1" 811 "APPROVE WITH NITS" "$SHA_A"
gh_says 811 CLEAN "$SHA_B"
: > "$W2/worked.txt"; : > "$W2/pages.txt"; : > "$W2/tree-log.txt"; : > "$W2/prompt.txt"
run_worker_rev "$R_P1/skel" "$S_P1" "$W2/p1.out" "$STUB/reviewer-down"

[ -s "$W2/prompt.txt" ] \
  || fail "the drift round dispatched no work-phase prompt at all, so this case cannot judge it.
      The worker said:
$(sed 's/^/        /' "$W2/p1.out")"
grep -q "THE REVIEW IS THE SPEC FOR THIS PASS" "$W2/prompt.txt" \
  && fail "THE DEFECT: the drift round handed Sana the REWORK prompt -- 'the review is the spec
      for this pass, for EACH finding either fix it or reply why it is not a defect' -- against a
      review whose verdict is APPROVE WITH NITS. There are no findings to answer. This is the
      exact prompt linear-worker.sh's own comment at the selector says must not be used on an
      approved diff. The prompt was:
$(sed 's/^/        /' "$W2/prompt.txt")"
ok "the drift round does not carry the review-answering prompt"

grep -q "$SHA_A" "$W2/prompt.txt" && grep -q "$SHA_B" "$W2/prompt.txt" \
  || fail "the drift round's prompt never names the reviewed sha or the head it drifted to, so
      the agent cannot tell WHY it was woken up. The prompt was:
$(sed 's/^/        /' "$W2/prompt.txt")"
ok "the drift round's prompt names the reviewed sha and the unreviewed head"

grep -qi "re-review round" "$W2/prompt.txt" \
  || fail "the drift round's prompt does not tell the agent what KIND of round this is. Gate 30
      says 'THIS IS A REBASE ROUND'; gate 40 has to be equally explicit or the agent defaults to
      inventing work on an approved diff. The prompt was:
$(sed 's/^/        /' "$W2/prompt.txt")"
ok "the drift round's prompt states that this is a re-review round"

# --- P2. the run must not report CONVERGED off the record it just distrusted --
# Two lines apart in the same run: 'the code at the head was never reviewed' and
# 'converged ... waits on founder merge'. The last line is the one an operator
# scans, and it reported success for work that did not happen. Unreachable before
# ASK-219 (gate 10 skipped the issue before step 5 could run).
# The exact shape of the false claim ("ASK-AAA converged:"), not the bare word --
# the truthful replacement line says "NOT converged" and must not match.
grep -q "ASK-AAA converged:" "$W2/p1.out" \
  && fail "THE DEFECT: the run announced the head was never reviewed, dispatched a round whose
      review then FAILED, and closed by re-reading the same stale record and calling the issue
      CONVERGED. Nothing reviewed the head; the record still pins $SHA_A. It said:
$(sed 's/^/        /' "$W2/p1.out")"
ok "a drift round whose review failed is not reported as converged"

grep -qi "waits on founder merge" "$W2/p1.out" \
  && fail "the run closed by telling the operator PR #811 waits on founder merge, while the code
      at its head has never been read by any reviewer"
ok "a drift round whose review failed is not reported as waiting on founder merge"

grep -q "$SHA_B" "$W2/p1.out" \
  || fail "the run's closing line does not name the head that is still unreviewed, so the operator
      cannot act on it. It said:
$(sed 's/^/        /' "$W2/p1.out")"
ok "the closing line names the head that is still unreviewed"

# --- P3. gate 40 has a ROUND BUDGET and pages at the cap ----------------------
# pr-verdict-lib.sh states the rule this violated: 'Making APPROVE non-terminal
# opens an unbounded rework path ... every round writes a permanent Linear
# comment on an object that cannot be deleted. So this returns a DISTINCT code
# ... The caller caps conflict rounds on its own budget.' Gate 40 also makes
# APPROVE non-terminal, and the caller gave it no budget. Measured on the PR head
# before this fix: 5 scheduled runs -> 5 model rounds, 10 permanent Linear
# comments, 0 founder pages, and the only budget in the file (conflict_rounds)
# untouched at 0.
R_P3="$W2/repo-p3"; make_repo "$R_P3"
S_P3="$W2/state-p3"; mkdir -p "$S_P3"
seed_record "$S_P3" 812 "APPROVE" "$SHA_A"
gh_says 812 CLEAN "$SHA_B"
: > "$W2/pages.txt"
DISPATCHED=0
for i in 1 2 3 4 5; do
  : > "$W2/prompt.txt"
  run_worker_rev "$R_P3/skel" "$S_P3" "$W2/p3-$i.out" "$STUB/reviewer-down"
  grep -q "^.*start ASK-AAA on " "$W2/p3-$i.out" && DISPATCHED=$((DISPATCHED+1))
done

[ "$DISPATCHED" -le 2 ] \
  || fail "THE DEFECT: 5 scheduled runs against one persistently-failing reviewer dispatched
      $DISPATCHED model rounds. Gate 40 has no cap, so a dead reviewer at 3am is an unbounded loop
      of model rounds and undeletable Linear comments. Gate 30 stops at 2."
[ "$DISPATCHED" = "2" ] \
  || fail "the drift budget dispatched $DISPATCHED round(s), expected exactly 2 (MAX_DRIFT_ROUNDS).
      Fewer means it stopped for a reason this case did not set up. Run 1 said:
$(sed 's/^/        /' "$W2/p3-1.out")"
ok "gate 40 stops after its round budget (2), not once per scheduled run forever"

grep -q "drift round(s) -- a human resolves this one" "$W2/p3-5.out" \
  || fail "the capped run skipped for the WRONG REASON: it must stop at the DRIFT cap, not at
      gate 10 or gate 20. It said: $(grep -i skip "$W2/p3-5.out" | head -1)"
ok "it stopped at the drift cap, not as approved or unreviewed"

PAGES="$(grep -c . "$W2/pages.txt" 2>/dev/null || echo 0)"
[ "$PAGES" = "1" ] \
  || fail "expected EXACTLY 1 founder page across 5 runs at the drift cap, got $PAGES. Zero means
      unreviewed code sits at the head of an approved PR with nobody told; more than one is the
      per-cycle noise that trains the operator to skim. Pages were:
$(sed 's/^/        /' "$W2/pages.txt")"
grep -q "$SHA_B" "$W2/pages.txt" \
  || fail "the page does not name the unreviewed head, so it reads as a benign stall on an
      approved PR. It said: $(cat "$W2/pages.txt")"
grep -qi "never reviewed\|unreviewed" "$W2/pages.txt" \
  || fail "the page never says the code at the head is unreviewed: $(cat "$W2/pages.txt")"
ok "exactly one page at the drift cap, and it names the unreviewed head"

# --- P4. the drift budget is its OWN counter ---------------------------------
# Three budgets, three questions. A drift round that spent the conflict budget
# would leave a real conflict un-dispatchable later; one that spent `count`
# would mark good work STUCK.
[ "$(ledger_key "$S_P3" drift_rounds)" = "2" ] \
  || fail "drift rounds are not recorded under their own ledger key, so nothing can ever reach the
      cap: $(cat "$S_P3/linear-worker-attempts.json" 2>/dev/null)"
[ "$(ledger_key "$S_P3" conflict_rounds)" = "0" ] \
  || fail "a drift round spent the CONFLICT budget"
[ "$(ledger_key "$S_P3" count)" = "0" ] \
  || fail "a drift round burned the failed-ATTEMPT budget; a round that ran is not a failure"
ok "drift rounds are counted separately from conflict rounds and failed attempts"

# --- P5. the drift streak ENDS when a review repins the record ----------------
# PR #25 finding 3, one layer out: nothing cleared the conflict keys, so the cap
# counted every conflict in the issue's LIFETIME and the third one was
# permanently un-dispatchable AND silent (already paged). A drift budget with no
# clear path repeats that exactly.
R_P5="$W2/repo-p5"; make_repo "$R_P5"
S_P5="$W2/state-p5"; mkdir -p "$S_P5"
seed_record "$S_P5" 813 "APPROVE" "$SHA_A"
gh_says 813 CLEAN "$SHA_B"
: > "$W2/pages.txt"
run_worker_rev "$R_P5/skel" "$S_P5" "$W2/p5-drift.out" "$STUB/reviewer-down"
[ "$(ledger_key "$S_P5" drift_rounds)" = "1" ] \
  || fail "the first drift round was not counted; the P5 fixture is not in the state it needs"

# The reviewer comes back up and repins the record to the head. Next run sees no
# drift at all -- and the streak that led here has to end with it.
run_worker_rev "$R_P5/skel" "$S_P5" "$W2/p5-heal.out" "$STUB/reviewer-ok"
run_worker_rev "$R_P5/skel" "$S_P5" "$W2/p5-clear.out" "$STUB/reviewer-down"
# gate-10 anchor only: the merge half of this sentence now reports the arm state (ASK-222)
grep -q "nothing to rework" "$W2/p5-clear.out" \
  || fail "after a review repinned the record to the head, the PR is no longer drifting and must
      reach gate 10. It said: $(grep -i skip "$W2/p5-clear.out" | head -1)"
[ "$(ledger_key "$S_P5" drift_rounds)" = "0" ] \
  || fail "the drift streak survived the drift being RESOLVED, so the budget counts an issue's
      LIFETIME drifts. The third genuine drift in this issue's life would then be permanently
      un-dispatchable and silent (drift_paged already true). Ledger:
      $(cat "$S_P5/linear-worker-attempts.json" 2>/dev/null)"
ok "a review that repins the record ends the drift streak and refills the budget"

# --- P6. converge's page on a STUCK drift says the head is unreviewed --------
# Gate 40 falls through to the no-progress guard on purpose. When the head stops
# moving (claim held, tree needs a human, reviewer down), converge exits 5 and
# pages -- and that page is the ONLY thing that reaches the founder's phone. It
# read 'stalled at APPROVE WITH NITS, no code change in round 2', which is a
# benign stall on an approved PR. The gate-40 line is in the log; the log is not
# what wakes anyone.
S_PSTALL="$W2/state-pstall"; mkdir -p "$S_PSTALL"
seed_record "$S_PSTALL" 814 "APPROVE WITH NITS" "$SHA_A"
gh_says 814 CLEAN "$SHA_B"
: > "$W2/converge-dispatch.txt"; : > "$W2/pages.txt"
run_converge "$S_PSTALL" "$W2/conv-stall.out" 3

[ "$CRC" = "5" ] \
  || fail "converge did not reach the no-progress guard on a frozen drifting head: got $CRC, want 5.
      It said:
$(sed 's/^/        /' "$W2/conv-stall.out")"
[ -s "$W2/pages.txt" ] || fail "converge exited 5 without paging anyone"
grep -qi "never reviewed\|unreviewed" "$W2/pages.txt" \
  || fail "THE DEFECT: the only thing that reaches the founder's phone on a stuck drift never
      mentions that unreviewed code sits at the head. It reads as a benign stall on an approved
      PR. The page was: $(cat "$W2/pages.txt")"
grep -q "$SHA_B" "$W2/pages.txt" \
  || fail "the page does not name the unreviewed head: $(cat "$W2/pages.txt")"
ok "converge's stall page says the head is unreviewed and names it"

# --- P7. ARGUMENT 3 IS NOT ARGUMENT 4, at both call sites --------------------
# O3 grepped for 'head_sha' and O4 for 'head'. Both fallback NOTEs contain both
# substrings, so swapping the reviewed sha and the current head at either call
# site left the suite at 100/100. The two NOTEs say different things; assert the
# text that is UNIQUE to each, and assert the other one is absent.
NOTE_UNPINNED="written before ASK-216"
NOTE_UNREADABLE="could not read the PR's current head_sha"

# Arg 3 empty (record predates ASK-216), arg 4 readable -> the UNPINNED note.
# Swap the two and this becomes the UNREADABLE note instead.
grep -q "$NOTE_UNPINNED" "$W2/conv-nosha.out" \
  || fail "converge: an unpinned record did not produce the unpinned-record NOTE. If arguments 3
      and 4 are swapped at that call site, an unpinned record reports 'could not read the PR's
      current head_sha' and sends the operator after a phantom GitHub outage. It said:
$(sed 's/^/        /' "$W2/conv-nosha.out")"
grep -qF "$NOTE_UNREADABLE" "$W2/conv-nosha.out" \
  && fail "converge reported an UNREADABLE HEAD on a record that simply has no head_sha -- the
      arguments are the wrong way round at that call site"
ok "converge: an unpinned record reports the unpinned NOTE, not an unreadable head"

# Arg 3 pinned, arg 4 empty (gh down) -> the UNREADABLE note, and NOT the other.
grep -qF "$NOTE_UNREADABLE" "$W2/conv-ghdown.out" \
  || fail "converge: an unreadable head did not produce the unreadable-head NOTE. It said:
$(sed 's/^/        /' "$W2/conv-ghdown.out")"
grep -q "$NOTE_UNPINNED" "$W2/conv-ghdown.out" \
  && fail "converge blamed a MISSING head_sha in the record for what is a gh outage -- the
      arguments are the wrong way round at that call site"
ok "converge: an unreadable head reports the unreadable NOTE, not a missing head_sha"

# The same pinning at the WORKER's call site, which O5-O8 never covered: every
# worker case there passes both shas non-empty, so a swap is invisible.
R_P7A="$W2/repo-p7a"; make_repo "$R_P7A"
S_P7A="$W2/state-p7a"; mkdir -p "$S_P7A"
seed_record "$S_P7A" 815 "APPROVE"            # no head_sha: arg 3 is empty
gh_says 815 CLEAN "$SHA_B"                    # arg 4 is readable
: > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker_in "$R_P7A/skel" "$S_P7A" "$W2/p7a.out"
grep -q "$NOTE_UNPINNED" "$W2/p7a.out" \
  || fail "worker: an unpinned record did not produce the unpinned-record NOTE at the worker's
      call site. It said:
$(sed 's/^/        /' "$W2/p7a.out")"
grep -qF "$NOTE_UNREADABLE" "$W2/p7a.out" \
  && fail "worker: arguments 3 and 4 are swapped -- an unpinned record was reported as an
      unreadable head"
ok "worker: argument 3 is the RECORD's sha (an unpinned record says so)"

R_P7B="$W2/repo-p7b"; make_repo "$R_P7B"
S_P7B="$W2/state-p7b"; mkdir -p "$S_P7B"
seed_record "$S_P7B" 816 "APPROVE" "$SHA_A"   # arg 3 is pinned
gh_says 816 CLEAN ""                          # arg 4 unreadable: gh is down
: > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker_in "$R_P7B/skel" "$S_P7B" "$W2/p7b.out"
grep -qF "$NOTE_UNREADABLE" "$W2/p7b.out" \
  || fail "worker: an unreadable head did not produce the unreadable-head NOTE. It said:
$(sed 's/^/        /' "$W2/p7b.out")"
grep -q "$NOTE_UNPINNED" "$W2/p7b.out" \
  && fail "worker: arguments 3 and 4 are swapped -- a gh outage was blamed on a record written
      before ASK-216"
[ ! -s "$W2/worked.txt" ] \
  || fail "worker: an unreadable head manufactured a round (it must fall toward terminal)"
ok "worker: argument 4 is the CURRENT head (a gh outage says so)"

# =============================================================================
# THE DRIFT BUDGET UNDER A HEAD NOBODY COULD READ (PR #30 review round 3)
# =============================================================================
# P3 proves the cap holds while `gh pr view --json headRefOid` answers on every
# run. It cannot see this: its fixture is seeded ONCE and never varies the one
# input that clears the budget. `pr_head_sha` returns empty on any gh failure,
# rework_gate then falls toward terminal and returns 10 -- not 40 -- so a clear
# conditioned only on "the gate did not say 40" REFILLS the budget from a state
# nobody read, and pops `drift_paged` with it. clear_conflict_rounds' own comment
# forbids exactly this: "refilling a budget from a state nobody actually read is
# how an unresolvable conflict gets infinite rounds."
#
# Not invented: `gh_says <pr> <state> ""` is this suite's own fixture for that
# state, already driving O4, L3 and P7B. It needs `gh pr view` to fail while
# `gh pr list` succeeds -- a total outage leaves EXISTING_PR empty and skips the
# whole gate block.

# --- P8. an unreadable head must not refill the drift budget -----------------
R_P8="$W2/repo-p8"; make_repo "$R_P8"
S_P8="$W2/state-p8"; mkdir -p "$S_P8"
seed_record "$S_P8" 817 "APPROVE" "$SHA_A"
: > "$W2/pages.txt"
P8_DISPATCHED=0
P8_AFTER_BLIND=""
for i in 1 2 3 4 5 6 7 8 9; do
  # Every third run, gh answers the head lookup with nothing.
  case "$i" in
    3|6|9) gh_says 817 CLEAN "" ;;
    *)     gh_says 817 CLEAN "$SHA_B" ;;
  esac
  : > "$W2/prompt.txt"
  run_worker_rev "$R_P8/skel" "$S_P8" "$W2/p8-$i.out" "$STUB/reviewer-down"
  grep -q "start ASK-AAA on " "$W2/p8-$i.out" && P8_DISPATCHED=$((P8_DISPATCHED+1))
  # Snapshot right after the FIRST blind run, while the budget is fully spent.
  [ "$i" = "3" ] && P8_AFTER_BLIND="$(ledger_key "$S_P8" drift_rounds)"
done

[ "$P8_AFTER_BLIND" = "2" ] \
  || fail "THE DEFECT: two drift rounds were spent, then ONE run could not read the head, and the
      streak went from 2 to $P8_AFTER_BLIND. The head lookup failing is not a statement that the
      drift is over -- nobody read anything. clear_conflict_rounds clears only on a STATED CLEAN
      for this exact reason. Ledger after run 3:
      $(cat "$S_P8/linear-worker-attempts.json" 2>/dev/null)"
ok "an unreadable head does not refill the drift budget"

[ "$P8_DISPATCHED" = "2" ] \
  || fail "THE DEFECT: 9 scheduled runs against one persistently-failing reviewer, with the head
      unreadable on runs 3/6/9, dispatched $P8_DISPATCHED model rounds; MAX_DRIFT_ROUNDS is 2. Each
      blind run resets the streak, so the cap is never reached and the loop is unbounded again --
      the round-2 major this budget was added to fix, wearing a gh hiccup as a coat."
ok "the drift cap holds across runs whose head could not be read"

P8_PAGES="$(grep -c . "$W2/pages.txt" 2>/dev/null || echo 0)"
[ "$P8_PAGES" = "1" ] \
  || fail "expected EXACTLY 1 founder page across 9 runs, got $P8_PAGES. Zero means the cap was
      never reached, so unreviewed code sits at the head of an approved PR with nobody told. More
      than one means a blind run popped drift_paged and re-paged the same head. Pages were:
$(sed 's/^/        /' "$W2/pages.txt")"
grep -q "$SHA_B" "$W2/pages.txt" \
  || fail "the page does not name the unreviewed head: $(cat "$W2/pages.txt")"
ok "exactly one page across 9 runs, and a blind run does not un-page the issue"

# --- P9. step 5 must not swallow the gate's own NOTE -------------------------
# converge.sh:180 states the rule this call site broke: "The gate's NOTE goes
# through `say` so it lands in the run log with everything else. Swallowing it
# would silently grandfather the blind spot it announces." The step-5 re-gate
# sent it to /dev/null. pr-review-agent.sh always writes head_sha and writes it
# EMPTY when its own `gh pr view` could not answer, so an approval pinned to
# nothing closes the run as "converged ... waits on founder merge" with no line
# anywhere saying the approval could not be tied to a commit. The behaviour is
# correct and settled (absent is not drift, fail toward terminal); the missing
# thing is the sentence that says so.
#
# The seeded record is REQUEST CHANGES so the TOP-of-run gate returns 0 without
# emitting any NOTE -- step 5 is then the only possible source of one.
cat > "$STUB/reviewer-unpinned" <<EOF
#!/usr/bin/env bash
PR="\$1"
mkdir -p "\$KIPI_STATE_DIR/pr-reviews"
printf '{"verdict":"APPROVE","pr":%s,"head_sha":""}\n' "\$PR" \
  > "\$KIPI_STATE_DIR/pr-reviews/pr-\$PR.verdict.json"
exit 0
EOF
chmod +x "$STUB/reviewer-unpinned"

R_P9="$W2/repo-p9"; make_repo "$R_P9"
S_P9="$W2/state-p9"; mkdir -p "$S_P9"
seed_record "$S_P9" 818 "REQUEST CHANGES" "$SHA_A"
gh_says 818 CLEAN "$SHA_B"
: > "$W2/worked.txt"; : > "$W2/pages.txt"; : > "$W2/prompt.txt"
run_worker_rev "$R_P9/skel" "$S_P9" "$W2/p9.out" "$STUB/reviewer-unpinned"

grep -q "ASK-AAA converged:" "$W2/p9.out" \
  || fail "the P9 fixture never reached step 5's closing line, so it cannot judge what step 5
      printed. The run said:
$(sed 's/^/        /' "$W2/p9.out")"
grep -q "$NOTE_UNPINNED" "$W2/p9.out" \
  || fail "THE DEFECT: the reviewer wrote an approval with an EMPTY head_sha, the gate said so on
      stdout, and step 5 sent that NOTE to /dev/null. The run closed with 'converged ... waits on
      founder merge' and nothing anywhere says the approval is pinned to no commit -- which is the
      one thing that separates it from a verified one. It said:
$(sed 's/^/        /' "$W2/p9.out")"
ok "step 5 says when the record it converged off is pinned to nothing"

# =============================================================================
# TWO ENGINES, ONE SCRIPT: CODEX IS THE REVIEWER THAT GATES (ASK-221)
# =============================================================================
# THE DEFECT: the reviewer was `claude -p` and the PR author (Sana) is also
# Claude. Different process, no shared memory, genuinely useful -- but the same
# lab and the same model family, so the blind spots stay correlated. Fresh
# context is not an independent mind.
#
# Codex began life here as an ADVISORY second opinion on kipi/codex-approved,
# appended after the Claude review. Founder directive 2026-07-29 made it the
# gate: codex is the agent that checks Sana's work, so it owns the required
# kipi/reviewer-approved and writes the one verdict record the loop reads, and
# claude drops to an advisory kipi/claude-approved. The Q-series below asserts
# that contract in BOTH directions -- codex owns the gate, and the advisory
# engine cannot answer for it.
#
# THE SHAPE: `pr-review-agent.sh --engine codex` runs the SAME script -- same sha
# capture, same verdict derivation, same status post, same spillover -- against a
# different lab's model, and posts `kipi/codex-approved` instead of
# `kipi/reviewer-approved`. A second script would be a second writer with its own
# semantics, which is the defect class this repo keeps finding.
#
# THE TWO DANGEROUS PATHS, and why each case below exists:
#   1. Codex is DOWN and `kipi/codex-approved` is required -> every PR wedges
#      forever. So an outage falls back to Opus, marks the slot DEGRADED, and
#      pages ONCE on the transition (a page every run is the cry-wolf failure).
#   2. Codex answers but says nothing parseable -> "no findings" reads as
#      APPROVE and an empty review silently green-lights a PR. That is the single
#      most dangerous path in this issue, so an unusable answer is UNSTATED, and
#      unstated is `state=failure`. It is NOT laundered through the Opus fallback:
#      an outage has no review to trust, but garbage IS an attempted review whose
#      content cannot be trusted, and approving over it invents a verdict.
#
# Every assertion is on the gh CALL LOG or the page file, never on stdout prose.
# Nothing here calls live Codex, live GitHub, or live Slack.
# CODEX OWNS THE GATE (founder directive 2026-07-29). Codex is the engine that
# checks Sana's work, so it posts the REQUIRED `kipi/reviewer-approved` and writes
# the one verdict record the loop reads. Claude drops to an advisory slot. These
# two constants are what the whole Q-series asserts against, so the contract flip
# is stated once here rather than spelled into thirty greps.
CODEX_CONTEXT="kipi/reviewer-approved"
CLAUDE_CONTEXT="kipi/claude-approved"

# The observed shape of real `codex exec` stdout: harness noise around the answer
# (issue ASK-221 recorded `hook: Stop`, `tokens used`, and a repeated final line).
# None of it may parse as a finding or move the verdict.
CODEX_NOISY_APPROVE='hook: Stop
Reading additional input from stdin...
## VERDICT: APPROVE WITH NITS

FINDINGS:
minor|the retry loop logs the first error and drops the last|q-system/x.sh:12
minor|help text omits --engine|q-system/x.sh:9
END FINDINGS

tokens used: 26,429
hook: Stop
'
CODEX_BLOCKED='## VERDICT: REQUEST CHANGES

FINDINGS:
major|the fallback fills the slot without marking it degraded|q-system/x.sh:40
END FINDINGS
'
# Truncated: the stream died after the block opened. `sed /FINDINGS:/,/END
# FINDINGS/p` runs to EOF on this, so an empty range derives APPROVE unless the
# closing line is REQUIRED. This is path 2 above, in its exact observed shape.
CODEX_TRUNCATED='hook: Stop
## VERDICT: APPROVE

FINDINGS:
'

# mk_engine_stubs <dir> <headRefOid> <codex-mode> <codex-body>
#   codex-mode: ok | fail (non-zero exit) | empty (exit 0, no output)
# The claude stub always emits $APPROVE_REVIEW, so a `success` status on a codex
# run can only have come from the Opus fallback -- which is what makes the
# degraded cases readable at all.
mk_engine_stubs() {
  local d="$1" oid="$2" mode="$3" body="$4"
  mkdir -p "$d/bin" "$d/home"
  : > "$d/gh-calls.log"; : > "$d/codex-calls.log"; : > "$d/claude-calls.log"
  printf '%s' "$body" > "$d/codex-body.txt"
  printf '%s' "$APPROVE_REVIEW" > "$d/claude-body.txt"
  cat > "$d/bin/python3" <<EOF
#!/usr/bin/env bash
exec "$REAL_PY" "\$@"
EOF
  cat > "$d/bin/claude" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$d/claude-calls.log"
cat "$d/claude-body.txt"
EOF
  cat > "$d/bin/codex" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$d/codex-calls.log"
case "$mode" in
  fail)  echo "codex: stream disconnected before first token" >&2; exit 1 ;;
  empty) exit 0 ;;
esac
cat "$d/codex-body.txt"
EOF
  cat > "$d/bin/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$d/gh-calls.log"
case "\$1 \$2" in
  "pr view")    printf '$oid\tsecond opinion under test\n' ;;
  "pr comment") printf '$COMMENT_URL_FIXTURE\n' ;;
esac
exit 0
EOF
  # The page sink. "Was the founder told, and how many times?" is answered by
  # reading a file, not by grepping the reviewer's source.
  cat > "$d/bin/notify" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$d/pages.txt"
EOF
  chmod +x "$d/bin/python3" "$d/bin/claude" "$d/bin/codex" "$d/bin/gh" "$d/bin/notify"
}

# run_engine_reviewer <dir> [args...]  -- HOME is per-dir, so the degraded-state
# file persists across runs in the same dir and resets between cases.
run_engine_reviewer() {
  local d="$1"; shift
  ( PATH="$d/bin:$PATH" HOME="$d/home" KIPI_NOTIFY="$d/bin/notify" \
    bash "$REVIEWER" 901 "$@" ) >"$d/out.txt" 2>"$d/err.txt"
  RC=$?
}

pages_in() { grep -c . "$1/pages.txt" 2>/dev/null || echo 0; }

# --- Q1. an approving codex review posts kipi/codex-approved on the read sha ---
Q1="$W2/eng-approve"
mk_engine_stubs "$Q1" "$SHA_A" ok "$CODEX_NOISY_APPROVE"
run_engine_reviewer "$Q1" --post --engine codex
CALL="$(status_call "$Q1")"
[ -n "$CALL" ] || fail "THE DEFECT: --engine codex posted NOTHING to GitHub, so there is no
      independent second opinion any gate could ever read. gh was called with:
$(sed 's/^/        /' "$Q1/gh-calls.log")"
printf '%s' "$CALL" | grep -q "context=$CODEX_CONTEXT" \
  || fail "the codex engine did not post context '$CODEX_CONTEXT'. Call was: $CALL"
printf '%s' "$CALL" | grep -q "statuses/$SHA_A" \
  || fail "the codex status went to a sha the reviewer never read. Call was: $CALL"
printf '%s' "$CALL" | grep -q 'state=success' \
  || fail "an APPROVE WITH NITS codex review did not map to state=success. Call was: $CALL"
ok "--engine codex posts $CODEX_CONTEXT=success on the sha it read"

printf '%s' "$CALL" | grep -qi 'degraded' \
  && fail "a healthy codex review was marked DEGRADED: $CALL"
[ ! -s "$Q1/claude-calls.log" ] \
  || fail "the Opus fallback ran on a HEALTHY codex review, so every PR pays for two model
      reviews and the 'degraded' marker means nothing"
[ "$(pages_in "$Q1")" = "0" ] \
  || fail "a healthy codex review paged the founder: $(cat "$Q1/pages.txt")"
ok "a healthy codex run runs no fallback, marks nothing degraded, pages nobody"

# --- Q2. a reviewer that can only approve is not a gate ----------------------
Q2="$W2/eng-block"
mk_engine_stubs "$Q2" "$SHA_A" ok "$CODEX_BLOCKED"
run_engine_reviewer "$Q2" --post --engine codex
CALL="$(status_call "$Q2")"
printf '%s' "$CALL" | grep -q 'state=failure' \
  || fail "a REQUEST CHANGES codex review did not map to state=failure. Call was: $CALL"
printf '%s' "$CALL" | grep -q "context=$CODEX_CONTEXT" \
  || fail "the refusing status carries the wrong context: $CALL"
ok "a REQUEST CHANGES codex review maps to state=failure (the second opinion can refuse)"

# --- Q3. codex DOWN -> Opus fills the slot, marked degraded, paged once -------
# If codex fails and the slot is required, every PR wedges forever. So the
# fallback must actually fill it -- and it must SAY it is degraded, because a
# silent fallback means both statuses come from one model and nobody knows the
# independence this whole issue buys was lost.
Q3="$W2/eng-down"
mk_engine_stubs "$Q3" "$SHA_A" fail ""
run_engine_reviewer "$Q3" --post --engine codex
CALL="$(status_call "$Q3")"
[ -n "$CALL" ] || fail "THE DEFECT: codex exited non-zero and the reviewer posted NO status at all.
      Once $CODEX_CONTEXT is a required check that wedges every PR in the fleet forever. gh saw:
$(sed 's/^/        /' "$Q3/gh-calls.log")"
printf '%s' "$CALL" | grep -q "context=$CODEX_CONTEXT" \
  || fail "the fallback filled the wrong slot: $CALL"
ok "codex down: the Opus fallback still fills $CODEX_CONTEXT"

# --- Q3B. a TRUNCATED Opus fallback must not green the required gate ----------
# FOUND BY CODEX ON 2026-07-29 reviewing this very branch (major,
# pr-review-agent.sh:403) while this suite was green. The codex path checked its
# answer for a COMPLETE findings block; the FALLBACK path did not. So an Opus run
# that exited 0 with a truncated stream left an unclosed `FINDINGS:`, which
# verdict_from_findings reads as an EMPTY findings list, which derives APPROVE --
# posting state=success on the REQUIRED context for a review nobody read. Filling
# the gate with an unread approval is strictly worse than leaving it unstated:
# unstated holds the PR, green releases it.
Q3B="$W2/eng-down-truncated"
mk_engine_stubs "$Q3B" "$SHA_A" fail ""
# The fallback answers, exits 0, and is cut off mid-block. mk_engine_stubs pins the
# claude body to $APPROVE_REVIEW, so overwrite it after the fact.
printf '%s' '## VERDICT: APPROVE

FINDINGS:
' > "$Q3B/claude-body.txt"
run_engine_reviewer "$Q3B" --post --engine codex
CALL="$(status_call "$Q3B")"
printf '%s' "$CALL" | grep -q 'state=success' \
  && fail "THE DEFECT CODEX FOUND: the Opus fallback was cut off mid-FINDINGS and the reviewer
      posted state=success on the REQUIRED context anyway. An unclosed block derives APPROVE, so
      this is a green gate for a review that said nothing. Call was: $CALL"
printf '%s' "$CALL" | grep -q 'state=failure' \
  || fail "a truncated fallback posted neither success nor failure, so the gate state is
      unreadable. Call was: ${CALL:-<no status posted>}"
ok "a truncated Opus fallback posts state=failure, never a green required gate"

[ -s "$Q3/claude-calls.log" ] \
  || fail "codex failed and no fallback reviewer ran at all, so the slot was filled by nothing"
ok "codex down: the Opus fallback reviewer actually ran"

printf '%s' "$CALL" | grep -qi 'degraded' \
  || fail "THE DEFECT: the fallback filled $CODEX_CONTEXT with NO degraded marker. Both statuses
      now come from one model family and the status text says nothing about it. Call was: $CALL"
ok "the fallback's status description marks the slot DEGRADED"

[ "$(pages_in "$Q3")" = "1" ] \
  || fail "expected EXACTLY 1 page on the transition into degraded mode, got $(pages_in "$Q3"):
$(sed 's/^/        /' "$Q3/pages.txt" 2>/dev/null)"
grep -qi 'codex' "$Q3/pages.txt" || fail "the page never names codex: $(cat "$Q3/pages.txt")"
ok "the founder is paged exactly once on the transition into degraded mode"

# --- Q4. codex answers with NOTHING USABLE -> never APPROVE -------------------
# The single most dangerous path in this issue. An empty or truncated answer has
# no findings in it, and "no findings" derives APPROVE. Both shapes must land on
# a NON-success status, and neither may be laundered through the Opus fallback:
# an outage has no review at all, but garbage is an attempted review whose
# content cannot be trusted, so approving over it invents a verdict.
Q4="$W2/eng-empty"
mk_engine_stubs "$Q4" "$SHA_A" empty ""
run_engine_reviewer "$Q4" --post --engine codex
CALL="$(status_call "$Q4")"
printf '%s' "$CALL" | grep -q 'state=success' \
  && fail "THE DEFECT: codex returned an EMPTY review and the reviewer posted state=success. An
      empty answer read as 'no findings survived reproduction' green-lights a PR nobody read.
      Call was: $CALL"
ok "an EMPTY codex review never posts state=success"

Q4B="$W2/eng-trunc"
mk_engine_stubs "$Q4B" "$SHA_A" ok "$CODEX_TRUNCATED"
run_engine_reviewer "$Q4B" --post --engine codex
CALL="$(status_call "$Q4B")"
printf '%s' "$CALL" | grep -q 'state=success' \
  && fail "THE DEFECT: codex output that opens 'FINDINGS:' and is then cut off derived APPROVE.
      The findings range runs to EOF, so a truncated stream reads as a clean review and the
      prose 'VERDICT: APPROVE' above it confirms the lie. Call was: $CALL"
ok "a TRUNCATED codex review (unclosed FINDINGS block) never posts state=success"

[ ! -s "$Q4B/claude-calls.log" ] \
  || fail "an unusable codex answer was laundered through the Opus fallback. An outage has no
      review to trust; garbage is a review whose CONTENT cannot be trusted, and filling the slot
      with an Opus approval over it invents a verdict for a review that said nothing."
ok "an unusable codex answer is not laundered through the fallback"

# --- Q5. harness noise is not a finding and does not move the verdict ---------
# Q1's fixture is the noisy one on purpose; this reads back what the parser
# actually extracted from it, because a status assertion alone cannot tell
# "the noise was ignored" from "the noise happened to be harmless".
Q1_REVIEW="$(ls -t "$Q1/home/.config/kipi/pr-reviews/codex/pr-901-"*.md 2>/dev/null | head -1)"
[ -n "$Q1_REVIEW" ] \
  || fail "the codex engine wrote no review file under pr-reviews/codex/, so nothing can be
      re-parsed. Tree was: $(find "$Q1/home/.config/kipi/pr-reviews" -type f 2>/dev/null | tr '\n' ' ')"
grep -q 'hook: Stop' "$Q1_REVIEW" \
  || fail "the noise fixture never reached the review file, so Q5 proves nothing about noise"
[ "$(verdict_from_findings "$Q1_REVIEW")" = "APPROVE WITH NITS" ] \
  || fail "harness noise moved the derived verdict: got '$(verdict_from_findings "$Q1_REVIEW")',
      want APPROVE WITH NITS"
[ "$(extract_minor_findings "$Q1_REVIEW" | grep -c .)" = "2" ] \
  || fail "codex harness noise parsed as a finding: expected exactly the 2 real minors, got:
$(extract_minor_findings "$Q1_REVIEW" | sed 's/^/        /')"
ok "codex harness noise parses as neither a finding nor a verdict change"

# --- Q6. paged on the TRANSITION, not on every run while still degraded -------
# A ping every cycle is the cry-wolf failure that trains the operator to ignore
# the real one. Q3's dir is already degraded; run it twice more.
run_engine_reviewer "$Q3" --post --engine codex
run_engine_reviewer "$Q3" --post --engine codex
[ "$(pages_in "$Q3")" = "1" ] \
  || fail "THE DEFECT: $(pages_in "$Q3") pages across 3 runs all in degraded mode. A page every
      scheduled run is noise, and noise is what makes the operator skim the real one. Pages:
$(sed 's/^/        /' "$Q3/pages.txt")"
ok "still-degraded runs do not re-page (one page for the whole streak)"

# And the recovery edge: codex comes back, and the operator is told once.
cat > "$Q3/bin/codex" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$Q3/codex-calls.log"
cat "$Q3/codex-body.txt"
EOF
printf '%s' "$CODEX_NOISY_APPROVE" > "$Q3/codex-body.txt"
chmod +x "$Q3/bin/codex"
run_engine_reviewer "$Q3" --post --engine codex
[ "$(pages_in "$Q3")" = "2" ] \
  || fail "codex recovered and the founder was never told independence was restored (pages:
      $(pages_in "$Q3"), want 2). Without it the operator cannot tell a live second opinion from
      an Opus stand-in. Pages were:
$(sed 's/^/        /' "$Q3/pages.txt")"
run_engine_reviewer "$Q3" --post --engine codex
[ "$(pages_in "$Q3")" = "2" ] \
  || fail "a healthy run re-paged recovery: $(cat "$Q3/pages.txt")"
ok "recovery pages once on the way out of degraded mode, then goes quiet"

# --- Q7. the ADVISORY engine cannot answer for the gate -----------------------
# Before the founder directive this case asserted `--engine claude` == the default
# path, both posting kipi/reviewer-approved. That equality is now FALSE BY DESIGN:
# claude is the advisory engine and codex is the default. The guard that matters
# is the inverse of the old one -- an advisory engine must NEVER be able to post
# the required context, or a Claude review could satisfy the gate that exists
# specifically to not be Claude.
Q7="$W2/eng-claude"
mk_engine_stubs "$Q7" "$SHA_A" fail ""      # codex would FAIL if it were consulted
run_engine_reviewer "$Q7" --post --engine claude
CALL_EXPLICIT="$(status_call "$Q7")"
[ ! -s "$Q7/codex-calls.log" ] \
  || fail "--engine claude invoked codex. The advisory review path must not depend on a second
      lab's CLI being installed. codex saw: $(cat "$Q7/codex-calls.log")"
ok "--engine claude never shells codex"

printf '%s' "$CALL_EXPLICIT" | grep -q "context=$CLAUDE_CONTEXT" \
  || fail "--engine claude did not post its advisory context '$CLAUDE_CONTEXT'.
      Call was: $CALL_EXPLICIT"
printf '%s' "$CALL_EXPLICIT" | grep -q "context=$STATUS_CONTEXT" \
  && fail "THE DEFECT THIS GUARDS: --engine claude posted the REQUIRED context
      '$STATUS_CONTEXT'. Sana is Claude, so a Claude reviewer would then satisfy the
      very gate that exists to be a different lab's opinion. Call was: $CALL_EXPLICIT"
ok "--engine claude posts only its advisory $CLAUDE_CONTEXT, never the required gate"

# --- Q7D. the DEFAULT engine is codex and it owns the required context ---------
# kipi/reviewer-approved is ALREADY a required context. Breaking it blocks 100% of
# PRs, so this pins the exact context and state on the DEFAULT path -- which is
# now codex. The codex stub is set to `ok`: a failing codex would fall through to
# the Opus fallback and mark the status DEGRADED, which is a different path than
# the one under test here (Q3 already covers that one).
Q7D="$W2/eng-default"
mk_engine_stubs "$Q7D" "$SHA_A" ok "$CODEX_NOISY_APPROVE"
run_engine_reviewer "$Q7D" --post
CALL_DEFAULT="$(status_call "$Q7D")"
[ -s "$Q7D/codex-calls.log" ] \
  || fail "THE DEFECT: the default (no --engine) path did not shell codex, so the fleet's PRs are
      still being checked by the same lab that wrote them. The founder directive was that codex
      is the agent that checks Sana's work."
printf '%s' "$CALL_DEFAULT" | grep -q "context=$STATUS_CONTEXT" \
  || fail "the default engine stopped posting '$STATUS_CONTEXT', which is a REQUIRED context.
      Every PR in the repo would block forever. Call was: $CALL_DEFAULT"
printf '%s' "$CALL_DEFAULT" | grep -q 'state=success' \
  || fail "the default engine's APPROVE no longer maps to state=success: $CALL_DEFAULT"
printf '%s' "$CALL_DEFAULT" | grep -qi 'degraded' \
  && fail "the default engine's status is marked degraded even though codex answered: $CALL_DEFAULT"
ok "the default engine is codex and still posts $STATUS_CONTEXT=success (branch protection intact)"

# --- Q7E. MOVED OUT (codex review round 1 of PR #34, minor) -------------------
# This case used to build its non-ancestor fixture with
# `git -C "$ROOT" commit-tree`, which writes a loose object into the REAL
# repository's object database -- the live data path this suite is supposed to
# stay away from, and a write that cannot happen at all in a read-only review
# checkout. It also made the suite mutate the founder's store on every run.
#
# The assertion itself is not lost, it is stronger: test-review-tree-guard.sh
# owns it in a mktemp sandbox repo (case 1 asserts non-zero exit, the REFUSING
# reason on stderr, no codex dispatch, no Opus dispatch, no verdict record and no
# commit status -- a superset of what this block checked), with case 2 as its
# negative self-test and case 4 covering the autonomous worktree shape. Reaching
# the refuse path needs a real-but-unrelated object, and you cannot manufacture
# one inside the tree whose history this suite also asserts on. That is why it
# lives in its own file with its own repo.
#
#   bash test/test-review-tree-guard.sh

# An UNKNOWN sha must WARN and proceed, never refuse: a stale or partial clone
# cannot prove ancestry either way, and refusing there would wedge the loop on a
# fetch problem. Every other engine case above uses a fake sha, so they all take
# this path -- their continued passing IS this assertion, and this makes it explicit.
grep -qi "cannot be proven\|WARN" "$Q7D/err.txt" \
  || fail "a PR sha absent from the object store did not produce the cannot-prove WARN, so the
      guard is either silent or refusing on unknown objects. stderr was:
$(sed 's/^/        /' "$Q7D/err.txt")"
ok "an unknown PR sha warns and proceeds (a partial clone does not wedge the loop)"

# The two engines must not share a review directory: review_round globs
# pr-<N>-*.md, so a codex review dropped beside a claude one silently advances
# the claude round counter and arms the anti-re-litigation rule a round early.
# EACH ENGINE KEEPS ITS HISTORICAL REVIEW DIRECTORY ACROSS THE GATE FLIP. This is
# the defect that a naive "just swap the pair" would have shipped: moving codex's
# reviews into pr-reviews/ alongside claude's would make review_round() -- which
# globs pr-<N>-*.md -- count the EXISTING claude rounds as codex's own, arming the
# anti-re-litigation rule a round early on every PR with review history. So the
# round counters do not move even though the gate did.
[ -n "$(ls "$Q7/home/.config/kipi/pr-reviews/pr-901-"*.md 2>/dev/null)" ] \
  || fail "the claude engine stopped writing its review to pr-reviews/ ; the worker's
      \`ls pr-reviews/pr-<N>-*.md\` read would find nothing"
[ -z "$(ls "$Q1/home/.config/kipi/pr-reviews/pr-901-"*.md 2>/dev/null)" ] \
  || fail "a codex review landed in the CLAUDE review directory. review_round globs
      pr-901-*.md, so every codex run would advance the claude reviewer's round counter."
ok "the engines keep separate review directories (round counters do not cross-count)"

# THE VERDICT RECORD IS THE GATE, and it belongs to codex now. converge.sh:36 and
# linear-worker.sh:76 both read pr-<N>.verdict.json at the pr-reviews ROOT. Codex
# is the engine that checks Sana's work, so codex writes THAT file -- and the
# advisory claude engine must not, or two writers would answer for one gate.
[ -s "$Q1/home/.config/kipi/pr-reviews/pr-901.verdict.json" ] \
  || fail "THE DEFECT: the codex engine wrote no verdict record at the pr-reviews ROOT, so the
      file converge.sh:36 and linear-worker.sh:76 gate the loop on is never written by the
      engine that actually reviewed. The loop would read a stale or absent verdict."
[ ! -f "$Q7/home/.config/kipi/pr-reviews/pr-901.verdict.json" ] \
  || fail "the ADVISORY claude engine wrote the loop's verdict record (pr-901.verdict.json).
      Two engines answering for one gate is the single-writer defect this repo keeps finding;
      a Claude verdict would drive the loop that exists to be checked by another lab."
[ -s "$Q7/home/.config/kipi/pr-reviews/claude/pr-901.verdict.json" ] \
  || fail "the claude engine wrote no verdict record of its own, so its advisory opinion is not
      recorded anywhere a later run can read"
ok "codex writes the loop's verdict record; claude records its advisory one beside its reviews"

# --- Q8. both engines pin their model explicitly ------------------------------
# Today the Claude reviewer passes no --model and inherits the session default,
# so the reviewer's identity is unpinned and drifts with whatever the caller
# happened to be running.
# Reads $Q7 (the --engine claude run), not $Q7D: the default path is codex now, so
# $Q7D never shells claude and its claude-calls.log is empty. A grep against an
# empty log would fail for the wrong reason and read as an unpinned model.
grep -q -- '--model' "$Q7/claude-calls.log" \
  || fail "THE DEFECT: the claude engine still passes no --model, so the reviewer's identity is
      whatever the calling session happened to default to. It was invoked as:
$(sed 's/^/        /' "$Q7/claude-calls.log")"
grep -q -- '--model' "$Q1/codex-calls.log" \
  || fail "the codex engine passes no --model. It was invoked as:
$(sed 's/^/        /' "$Q1/codex-calls.log")"
ok "both engines pin their model explicitly on the command line"

grep -q -- '--skip-git-repo-check' "$Q1/codex-calls.log" \
  || fail "codex was invoked without --skip-git-repo-check; outside a trusted dir it refuses with
      'Not inside a trusted directory'. It was invoked as: $(cat "$Q1/codex-calls.log")"
ok "codex is invoked with --skip-git-repo-check"

# `codex exec` READS STDIN and hangs without a redirect (observed: "Reading
# additional input from stdin..."). A stub cannot prove the redirect exists --
# it would just inherit the suite's stdin -- so this is asserted on the source.
grep -q 'codex exec.*</dev/null' "$REVIEWER" \
  || fail "the codex dispatch has no </dev/null. codex exec reads stdin and hangs without it;
      at 3am that is a review that never returns until the 2400s bound kills it."
ok "the codex dispatch redirects stdin from /dev/null"

# --- Q9. the worker runs the codex engine as THE review -----------------------
# A reviewer nobody invokes is text in a file. The worker is the only thing that
# reviews PRs on a schedule, and it now states --engine codex explicitly at the
# call site rather than inheriting the reviewer's default: which model checks this
# fleet's work is a fact that should be readable where the review is dispatched.
grep -q -- '--engine codex' "$WORKER" \
  || fail "linear-worker.sh never runs the codex engine, so every PR in the autonomous loop is
      reviewed by the same lab that wrote it"
ok "worker wiring: the codex engine is dispatched as the review"
# EVERY PR THE WORKER TOUCHES ARMS ITS OWN AUTO-MERGE (ASK-222)
# =============================================================================
# THE DEFECT: nothing in CODE armed auto-merge. Every required piece already
# existed and was proven -- `kipi/reviewer-approved` is a REQUIRED context,
# watched refusing on ABSENT and on FAILURE (PRs #27, #30), and PR #30 merged
# itself at 01:38:07Z with no human once auto-merge was armed. The one missing
# piece was WHO ARMS IT: a hand-typed `gh pr merge --auto --squash <n>` plus a
# watcher loop inside an interactive session. Both die when the terminal closes,
# so a PR opened after that sits green forever with nobody left to merge it. A
# human remembering, or a session staying open, is not enforcement.
#
# Every case below drives the REAL worker with `gh` stubbed to a CALL LOG, and
# asserts on what the worker actually asked GitHub to do. Never the live API.
ARMLOG="$W2/gh-arm.log"

# gh_arm <pr> <merge-state> <head-sha> <merge-rc> <armed>
#   <merge-rc>  what `gh pr merge --auto` exits with (non-zero = the API refused)
#   <armed>     what `gh pr view --json autoMergeRequest` reports: "true" once
#               this PR is already armed, "false" while it is not
gh_arm() {
  cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$ARMLOG"
case "\$*" in
  "pr list"*)                                  echo $1 ;;
  "pr view $1 --json mergeStateStatus"*)       echo $2 ;;
  "pr view $1 --json headRefOid"*)             echo $3 ;;
  "pr view $1 --json autoMergeRequest"*)       echo $5 ;;
  "pr merge"*)                                 exit $4 ;;
esac
exit 0
EOF
  chmod +x "$STUB/gh"
}

# gh_arm_opens <pr> -- THE OTHER PATH. There is no PR at all until the worker
# opens one itself (the agent ended its turn without opening it, ASK-184), so
# `pr list` answers only after a `pr create` has been seen.
gh_arm_opens() {
  rm -f "$W2/pr-created"
  cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$ARMLOG"
case "\$*" in
  "pr create"*)                                : > "$W2/pr-created" ;;
  "pr list"*)                                  [ -f "$W2/pr-created" ] && echo $1 ;;
  "pr view $1 --json autoMergeRequest"*)       echo false ;;
esac
exit 0
EOF
  chmod +x "$STUB/gh"
}

# The reviewer logs into the SAME file as `gh`, which is the only way to assert
# ORDER: arming has to happen BEFORE the review, or the unattended path needs
# something to come back afterwards and do it -- the gap this issue exists for.
cat > "$STUB/reviewer-arm" <<EOF
#!/usr/bin/env bash
printf 'REVIEWER RAN on %s\n' "\$1" >> "$ARMLOG"
mkdir -p "\$KIPI_STATE_DIR/pr-reviews"
printf '{"verdict":"APPROVE","pr":%s,"head_sha":"%s"}\n' "\$1" "$SHA_A" \
  > "\$KIPI_STATE_DIR/pr-reviews/pr-\$1.verdict.json"
exit 0
EOF
chmod +x "$STUB/reviewer-arm"

# The work-phase agent COMMITS, which sections E-P never needed: the
# worker-opened path only fires when the branch is ahead of origin/main.
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
echo "worked" >> "$W2/worked.txt"
"$REAL_GIT" -c user.email=t@t.t -c user.name=t commit -q --allow-empty \
  -m "the agent's work (ASK-AAA)" 2>/dev/null
exit 0
EOF
# The agent that pushes NOTHING: no commits ahead, so no PR is opened and there
# is nothing to arm.
cat > "$STUB/claude-idle" <<EOF
#!/usr/bin/env bash
echo "worked" >> "$W2/worked.txt"
exit 0
EOF
chmod +x "$STUB/claude" "$STUB/claude-idle"

# run_worker_arm <skel> <state-dir> <out> -- keeps the REAL exit code, which
# run_worker/run_worker_in deliberately throw away. A failure to arm must not
# change it.
ARM_RC=0
run_worker_arm() {
  ( cd "$1" \
    && HOME="$W2/home" KIPI_SKEL="$1" KIPI_STATE_DIR="$2" \
       KIPI_NOTIFY="$W2/notify.sh" KIPI_PR_REVIEWER="$STUB/reviewer-arm" \
       bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) >"$3" 2>&1
  ARM_RC=$?
}

# `grep -c` PRINTS the count and EXITS 1 when that count is zero, so a `|| echo 0`
# fallback here emits "0" twice and every zero-call assertion fails on a two-line
# value. Swallow the status, keep grep's own number.
arm_calls() { grep -c "^pr merge --auto" "$ARMLOG" 2>/dev/null || true; }

# --- Q1. the PR the AGENT opened gets armed ----------------------------------
# A rework round: PR #830 already exists (the agent opened it on an earlier run)
# and its recorded verdict is REQUEST CHANGES, so the gate routes it through and
# step 5 resolves PR_NUM from `gh pr list` -- the first of the two paths.
R_ARM1="$W2/repo-arm1"; make_repo "$R_ARM1"
S_ARM1="$W2/state-arm1"; mkdir -p "$S_ARM1"
seed_record "$S_ARM1" 830 "REQUEST CHANGES" "$SHA_A"
gh_arm 830 CLEAN "$SHA_A" 0 false
: > "$ARMLOG"; : > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker_arm "$R_ARM1/skel" "$S_ARM1" "$W2/arm1.out"

grep -q "^pr merge --auto --squash 830$" "$ARMLOG" \
  || fail "THE DEFECT: the worker ran a full round on PR #830 and never armed auto-merge. The PR
      now waits on a human or on a watcher process that dies with the terminal, which is the
      silent stall this issue exists to kill. gh was called with:
$(sed 's/^/        /' "$ARMLOG")"
ok "the PR the agent opened is armed: gh pr merge --auto --squash 830"

MERGE_LINE="$(grep -n '^pr merge --auto' "$ARMLOG" | head -1 | cut -d: -f1)"
REVIEW_LINE="$(grep -n '^REVIEWER RAN' "$ARMLOG" | head -1 | cut -d: -f1)"
[ -n "$MERGE_LINE" ] && [ -n "$REVIEW_LINE" ] && [ "$MERGE_LINE" -lt "$REVIEW_LINE" ] \
  || fail "auto-merge was armed AFTER the review (merge at line ${MERGE_LINE:-none}, review at
      line ${REVIEW_LINE:-none}). Arming after the review re-creates the gap: something has to
      come back once the review lands. --auto is not 'merge now' -- GitHub holds the PR until
      every required context is green -- so arming early is both safe and the point. Log:
$(sed 's/^/        /' "$ARMLOG")"
ok "the arm happens BEFORE the review (--auto holds until the required checks are green)"

[ "$ARM_RC" = "0" ] || fail "arming changed the worker's exit code to $ARM_RC"
ok "arming a PR leaves the run's exit code alone"

# THE CLOSING LINE REPORTS WHO MERGES IT (PR #33 review, finding 2 -- minor).
# Two lines after "auto-merge armed on PR #830", the same run told the operator
# "PR #830 waits on founder merge". It does not; GitHub does. The closing line is
# the one an operator scans, so a fix that lands on the arm and not on the report
# leaves the operator with the pre-fix picture of who owes the merge.
CONV_LINE="$(grep 'ASK-AAA converged:' "$W2/arm1.out" | tail -1)"
[ -n "$CONV_LINE" ] \
  || fail "the Q1 fixture never reached the converged line, so it cannot judge it. It said:
$(sed 's/^/        /' "$W2/arm1.out")"
case "$CONV_LINE" in
  *"waits on founder merge"*|*"waits on a human merge"*)
    fail "THE REPORT DID NOT MOVE WITH THE FIX: this run armed auto-merge on PR #830 and then
      closed by telling the operator the PR waits on a human to merge it. Nobody is waiting --
      GitHub merges it once the required contexts are green. It said:
        $CONV_LINE" ;;
esac
case "$CONV_LINE" in
  *armed*) : ;;
  *) fail "the closing line does not say the PR is armed, so the operator cannot tell an
      auto-merging PR from one that needs their hand. It said:
        $CONV_LINE" ;;
esac
ok "the closing line on an armed PR says GitHub merges it, not a human"

# --- Q2. the PR the WORKER opened gets armed too -----------------------------
# One is not the other: this PR does not exist when the run starts. The agent
# ends its turn without opening it (ASK-184), the worker opens it at step 5, and
# the arm has to fire on THAT number.
R_ARM2="$W2/repo-arm2"
mkdir -p "$R_ARM2"
git init -q --bare "$R_ARM2/origin"
git init -q "$R_ARM2/skel"
G -C "$R_ARM2/skel" commit -q --allow-empty -m "base commit"
git -C "$R_ARM2/skel" branch -M main
git -C "$R_ARM2/skel" remote add origin "$R_ARM2/origin"
git -C "$R_ARM2/skel" push -q -u origin main
S_ARM2="$W2/state-arm2"; mkdir -p "$S_ARM2"
gh_arm_opens 831
: > "$ARMLOG"; : > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker_arm "$R_ARM2/skel" "$S_ARM2" "$W2/arm2.out"

grep -q "opened PR #831" "$W2/arm2.out" \
  || fail "the Q2 fixture never reached the worker-opened path, so it cannot judge it. It said:
$(sed 's/^/        /' "$W2/arm2.out")"
grep -q "^pr merge --auto --squash 831$" "$ARMLOG" \
  || fail "the worker OPENED PR #831 itself and then left it unarmed. This is the path where no
      human was ever involved, so it is the one that most needs arming. gh was called with:
$(sed 's/^/        /' "$ARMLOG")"
ok "the PR the worker opened itself is armed too (both paths, not one)"

# --- Q3. a refused arm is LOUD and does not fail the run ---------------------
# An unarmed PR is invisible by construction: everything green, nothing merges,
# no signal. So the failure has to be said. It must not stop the review or move
# the exit code -- the PR still stands, and the cost is one human command.
R_ARM3="$W2/repo-arm3"; make_repo "$R_ARM3"
S_ARM3="$W2/state-arm3"; mkdir -p "$S_ARM3"
seed_record "$S_ARM3" 832 "REQUEST CHANGES" "$SHA_A"
gh_arm 832 CLEAN "$SHA_A" 1 false
: > "$ARMLOG"; : > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker_arm "$R_ARM3/skel" "$S_ARM3" "$W2/arm3.out"

grep -qi "auto-merge" "$W2/arm3.out" \
  || fail "THE SILENT STALL: gh refused to arm PR #832 and the run said nothing about it. The PR
      goes green and never merges, with no line anywhere saying why. It said:
$(sed 's/^/        /' "$W2/arm3.out")"
grep -q "832" "$W2/arm3.out" \
  || fail "the auto-merge warning does not name the PR, so nobody can act on it"
ok "a refused arm is said out loud, naming the PR"

# LOUD MEANS $NOTIFY, NOT $LOG (PR #33 review, finding 1 -- major). `say` is
# `tee -a "$LOG"`, and under the launchd heartbeat $LOG is a file nobody opens at
# 3am. This worker's channel for "a human must do something" is `bash "$NOTIFY"`,
# used at five other sites in the same file, and this failure state is precisely
# that: the message itself ends "until someone runs: gh pr merge --auto". An
# unarmed PR goes green, never merges, and if nothing pages, the silent stall
# this issue exists to kill has just moved one step down.
[ -s "$W2/pages.txt" ] \
  || fail "THE STALL MOVED, IT DID NOT DIE: gh refused to arm PR #832 and nobody was paged. The
      warning went to \$LOG only, which at 3am under launchd reaches no one. The PR goes green,
      never merges, and the first human to know is whoever happens to open GitHub. The run said:
$(sed 's/^/        /' "$W2/arm3.out")"
grep -q "832" "$W2/pages.txt" \
  || fail "the page does not name the PR, so the operator cannot act on it: $(cat "$W2/pages.txt")"
grep -qi "gh pr merge --auto --squash 832" "$W2/pages.txt" \
  || fail "the page does not carry the one command that fixes it: $(cat "$W2/pages.txt")"
ok "a refused arm PAGES the founder, naming the PR and the command that fixes it"

grep -q "^REVIEWER RAN on 832$" "$ARMLOG" \
  || fail "a failed arm killed the review. The PR must still stand and still be reviewed. Log:
$(sed 's/^/        /' "$ARMLOG")"
[ "$ARM_RC" = "0" ] \
  || fail "a failed arm changed the run's exit code to $ARM_RC. The driver would read a healthy
      run as a worker failure and burn an attempt on it."
ok "a failed arm still reviews the PR and leaves the exit code unchanged"

# --- Q4. re-running on an ALREADY-ARMED PR is a no-op, not an error ----------
# The worker re-runs on the same PR every rework round. A WARN per round trains
# the operator to skim the one that matters, and a non-zero exit would read as a
# worker failure -- so the state is asked for first rather than armed-and-forgiven.
R_ARM4="$W2/repo-arm4"; make_repo "$R_ARM4"
S_ARM4="$W2/state-arm4"; mkdir -p "$S_ARM4"
seed_record "$S_ARM4" 833 "REQUEST CHANGES" "$SHA_A"
gh_arm 833 CLEAN "$SHA_A" 0 false
: > "$ARMLOG"; : > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker_arm "$R_ARM4/skel" "$S_ARM4" "$W2/arm4a.out"
[ "$(arm_calls)" = "1" ] || fail "round 1 did not arm PR #833 exactly once (got $(arm_calls))"

# Round 2: GitHub now reports the PR as already armed, and `gh pr merge` would
# refuse. Nothing should call it, and nothing should warn.
seed_record "$S_ARM4" 833 "REQUEST CHANGES" "$SHA_A"
gh_arm 833 CLEAN "$SHA_A" 1 true
: > "$ARMLOG"; : > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker_arm "$R_ARM4/skel" "$S_ARM4" "$W2/arm4b.out"

[ "$(arm_calls)" = "0" ] \
  || fail "the second round re-armed an already-armed PR. gh was called with:
$(sed 's/^/        /' "$ARMLOG")"
# WARN, not the bare word: the closing line now names auto-merge on every healthy
# round on purpose (it is what tells the operator no human owes this PR a merge),
# so the thing that must not repeat is the WARNING, which is what this case was
# ever about. Asserted on both channels -- a page per rework round is the version
# of this noise that reaches a phone.
grep -qi "WARN.*auto-merge" "$W2/arm4b.out" \
  && fail "an already-armed PR produced a warning on the re-run. Every rework round would repeat
      it, and noise is what makes the real warning unreadable. It said:
$(grep -i auto-merge "$W2/arm4b.out")"
[ ! -s "$W2/pages.txt" ] \
  || fail "an already-armed PR paged the founder on a re-run. Every rework round would page again
      for a PR that is fine: $(cat "$W2/pages.txt")"
[ "$ARM_RC" = "0" ] || fail "a re-run on an armed PR exited $ARM_RC"
ok "a re-run on an already-armed PR: no call, no warning, no error"

# --- Q5. no PR means nothing to arm ------------------------------------------
# The agent pushed nothing, so no PR is opened. Arming must not be attempted
# against an empty PR number -- `gh pr merge --auto --squash ''` would act on
# whatever branch the cwd happens to be on.
R_ARM5="$W2/repo-arm5"
mkdir -p "$R_ARM5"
git init -q --bare "$R_ARM5/origin"
git init -q "$R_ARM5/skel"
G -C "$R_ARM5/skel" commit -q --allow-empty -m "base commit"
git -C "$R_ARM5/skel" branch -M main
git -C "$R_ARM5/skel" remote add origin "$R_ARM5/origin"
git -C "$R_ARM5/skel" push -q -u origin main
S_ARM5="$W2/state-arm5"; mkdir -p "$S_ARM5"
cp "$STUB/claude-idle" "$STUB/claude"
gh_arm_opens 834
: > "$ARMLOG"; : > "$W2/worked.txt"
run_worker_arm "$R_ARM5/skel" "$S_ARM5" "$W2/arm5.out"

grep -q "no PR found" "$W2/arm5.out" \
  || fail "the Q5 fixture did not reach the no-PR branch, so it cannot judge it. It said:
$(sed 's/^/        /' "$W2/arm5.out")"
[ "$(arm_calls)" = "0" ] \
  || fail "auto-merge was armed with no PR to arm. gh was called with:
$(sed 's/^/        /' "$ARMLOG")"
ok "no PR means no arm call at all"

# --- Q6/Q7. the probe's rc is part of its answer -----------------------------
# PR #33 review, finding 3 (minor). `gh pr view ... 2>/dev/null` threw away both
# stderr AND the exit code, so a rate limit or a network blip produced the same
# empty string as "not armed" -- and `gh pr merge --auto` on an ALREADY-ARMED PR
# returns non-zero on some gh versions. The pair yields a WARN about a PR that is
# armed and will merge, telling the operator to run a command already run. The
# probe exists to kill exactly that noise; it held on the happy path and dropped
# it on the error path, which is the path that only happens at 3am.
#
# gh_arm_probe <pr> <merge-state> <head-sha> <merge-rc> <probe1> <probe2>
#   <probe1>/<probe2>  successive answers from `pr view --json autoMergeRequest`:
#                      "true", "false", or FAIL (exits 1 with no output, which is
#                      what a rate limit or a dropped connection looks like).
gh_arm_probe() {
  rm -f "$W2/probe-n"
  cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$ARMLOG"
case "\$*" in
  "pr list"*)                                  echo $1 ;;
  "pr view $1 --json mergeStateStatus"*)       echo $2 ;;
  "pr view $1 --json headRefOid"*)             echo $3 ;;
  "pr view $1 --json autoMergeRequest"*)
    N=\$(cat "$W2/probe-n" 2>/dev/null || echo 0); N=\$((N+1)); echo "\$N" > "$W2/probe-n"
    if [ "\$N" = "1" ]; then A="$5"; else A="$6"; fi
    [ "\$A" = "FAIL" ] && exit 1
    echo "\$A" ;;
  "pr merge"*)                                 exit $4 ;;
esac
exit 0
EOF
  chmod +x "$STUB/gh"
}

# Q6. a gh blip on an ARMED PR must not cry wolf. PR #836 IS armed. The first
# probe cannot answer, so the arm is attempted (the right move: an unarmed PR is
# the expensive state), gh refuses it because it is already armed, and the run
# then has to tell "already armed" from "broken" before it says anything.
R_ARM6="$W2/repo-arm6"; make_repo "$R_ARM6"
S_ARM6="$W2/state-arm6"; mkdir -p "$S_ARM6"
seed_record "$S_ARM6" 836 "REQUEST CHANGES" "$SHA_A"
gh_arm_probe 836 CLEAN "$SHA_A" 1 FAIL true
: > "$ARMLOG"; : > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker_arm "$R_ARM6/skel" "$S_ARM6" "$W2/arm6.out"

grep -qi "sit green and unmerged" "$W2/arm6.out" \
  && fail "CRY WOLF: PR #836 is armed and WILL merge, and the run told the operator it will sit
      green and unmerged until a human runs a command that is already done. One gh blip on the
      probe was enough. It said:
$(grep -i 'auto-merge' "$W2/arm6.out")"
[ ! -s "$W2/pages.txt" ] \
  || fail "an armed PR paged the founder off a transient gh failure: $(cat "$W2/pages.txt")"
CONV6="$(grep 'ASK-AAA converged:' "$W2/arm6.out" | tail -1)"
case "$CONV6" in
  *armed*) : ;;
  *) fail "the closing line does not report PR #836 as armed even though the state probe says it
      is. It said:
        ${CONV6:-<no converged line at all>}" ;;
esac
ok "a gh blip on an armed PR: no false warning, no page, and the report still says armed"

# Q7. and when NOTHING can tell -- the arm refused and neither probe answered --
# the run must still be audible, because that is the state where the PR may
# genuinely be unarmed. What it may not do is assert the thing it cannot back.
# Buying quiet here would be the fix re-creating the silence it exists to kill.
R_ARM7="$W2/repo-arm7"; make_repo "$R_ARM7"
S_ARM7="$W2/state-arm7"; mkdir -p "$S_ARM7"
seed_record "$S_ARM7" 837 "REQUEST CHANGES" "$SHA_A"
gh_arm_probe 837 CLEAN "$SHA_A" 1 FAIL FAIL
: > "$ARMLOG"; : > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker_arm "$R_ARM7/skel" "$S_ARM7" "$W2/arm7.out"

grep -qi "auto-merge" "$W2/arm7.out" \
  || fail "gh could neither arm PR #837 nor read its state and the run said nothing at all. It said:
$(sed 's/^/        /' "$W2/arm7.out")"
grep -qi "sit green and unmerged" "$W2/arm7.out" \
  && fail "the run asserted PR #837 will sit green and unmerged. Nothing here knows that: gh
      refused the arm and refused the state, so the honest word is that it could not tell."
[ -s "$W2/pages.txt" ] \
  || fail "SILENCE BOUGHT BY THE FIX: gh could not arm PR #837 and could not read its state, and
      nobody was paged. This is the one branch where the PR may really be unarmed, so quieting it
      re-creates the stall one layer down. The run said:
$(sed 's/^/        /' "$W2/arm7.out")"
grep -q "837" "$W2/pages.txt" || fail "the page does not name the PR: $(cat "$W2/pages.txt")"
grep -qi "sit green and unmerged" "$W2/pages.txt" \
  && fail "the page repeats the claim the run cannot back: $(cat "$W2/pages.txt")"
[ "$ARM_RC" = "0" ] || fail "an unreadable auto-merge state changed the run's exit code to $ARM_RC"
ok "an unreadable auto-merge state pages, says it could not tell, and claims nothing more"

# =============================================================================
# R. THE POPULATION THE WORKER SKIPS IS STILL A POPULATION (PR #33 round 3)
# =============================================================================
# THE DEFECT (major, filed on converge.sh:198). Gate 10 -- approved, clean, no
# drift -- `continue`s 400+ lines ABOVE the arm at step 5. So the PRs with
# NOTHING LEFT BUT THE MERGE, the exact population this issue exists for, were
# the one population nothing armed. converge.sh then Slacked "auto-merge lands
# it, no human merge needed" across that state, justified by a comment claiming
# the worker "arms every PR it touches". It did not touch them.
#
# Every case drives the REAL worker and the REAL converge against a `gh` call
# log. Never the live API.

# --- R1. an approved PR is armed AT THE GATE, not only inside a round --------
R_ARM8="$W2/repo-arm8"; make_repo "$R_ARM8"
S_ARM8="$W2/state-arm8"; mkdir -p "$S_ARM8"
seed_record "$S_ARM8" 900 "APPROVE" "$SHA_A"
gh_arm 900 CLEAN "$SHA_A" 0 false
: > "$ARMLOG"; : > "$W2/worked.txt"; : > "$W2/pages.txt"
run_worker_arm "$R_ARM8/skel" "$S_ARM8" "$W2/arm8.out"

grep -q "skip ASK-AAA: PR #900" "$W2/arm8.out" \
  || fail "the R1 fixture never reached the approved-and-done gate, so it cannot judge it. It said:
$(sed 's/^/        /' "$W2/arm8.out")"
grep -q "^pr merge --auto --squash 900$" "$ARMLOG" \
  || fail "THE DEFECT: PR #900 is approved, clean, and pinned to its own head -- there is nothing
      left to do but merge it -- and the worker skipped it without arming auto-merge. This is the
      population the issue is named for, and it is the one the arm never reached: the gate
      \`continue\`s hundreds of lines above it. gh was called with:
$(sed 's/^/        /' "$ARMLOG")"
ok "an approved PR is armed at the gate that skips it, not only inside a rework round"

# ARMING IS NOT A ROUND. The skip must stay a skip: no agent dispatched, no
# reviewer, no Linear comment. A fix that arms by turning done PRs back into
# rework rounds would burn model spend on every scheduled run forever.
[ ! -s "$W2/worked.txt" ] \
  || fail "arming at the gate dispatched the work agent on a PR that was already approved and
      clean. The skip has to stay a skip; only the arm is new."
grep -q "^REVIEWER RAN" "$ARMLOG" \
  && fail "arming at the gate re-reviewed an already-approved PR. Every scheduled run would pay
      for a review of a PR with nothing left to review. Log:
$(sed 's/^/        /' "$ARMLOG")"
[ "$ARM_RC" = "0" ] || fail "arming at the gate changed the run's exit code to $ARM_RC"
ok "arming at the gate stays a skip: no agent, no reviewer, no change to the exit code"

# --- R2. the gate's own line reports who merges it ---------------------------
# PR #33 round 3, finding 2 (minor). Round 2 fixed this exact sentence at the
# closing line and at converge's, and left the third site. For a PR armed a round
# ago, no founder is waiting; the line is the misstatement the issue set out to
# remove.
SKIP900="$(grep 'skip ASK-AAA: PR #900' "$W2/arm8.out" | tail -1)"
case "$SKIP900" in
  *"waiting on founder merge"*|*"waits on founder merge"*)
    fail "THE THIRD SITE: the same run armed auto-merge on PR #900 and the skip line still tells
      the operator a founder owes it a merge. It said:
        $SKIP900" ;;
esac
case "$SKIP900" in
  *armed*) : ;;
  *) fail "the gate's skip line does not say whether the PR is armed, so an operator scanning the
      log cannot tell an auto-merging PR from one that needs their hand. It said:
        $SKIP900" ;;
esac
ok "the gate-10 skip line reports the arm state, not a founder who is not waiting"

# --- R3. the arm state is PUBLISHED, so the second reporter reads it ---------
# converge.sh cannot assert arm state it never read, and re-probing `gh` there
# would be a second reader of one input with its own semantics -- the defect
# pr-verdict-lib.sh exists to close. So the ONE reader publishes its answer and
# the other reporter reads the record, exactly like the verdict record.
#
# This assertion is what keeps the converge fixtures below honest: they seed the
# record, and this pins that the REAL worker writes that same file with that same
# vocabulary. A fixture built on a key no producer emits proves nothing.
AMREC="$S_ARM8/pr-reviews/pr-900.automerge"
[ -s "$AMREC" ] \
  || fail "the worker armed PR #900 and recorded nothing, so the only thing converge could do is
      assert or guess. Expected the arm state at $AMREC"
[ "$(tr -d '[:space:]' < "$AMREC")" = "armed" ] \
  || fail "the worker armed PR #900 and recorded '$(cat "$AMREC")' instead of 'armed'"
ok "the worker publishes the arm state it read, so the second reporter never has to assert it"

# --- R4. converge reports the RECORDED state, and only that ------------------
S_CV_ARM="$W2/state-conv-armed"; mkdir -p "$S_CV_ARM/pr-reviews"
seed_record "$S_CV_ARM" 902 "APPROVE" "$SHA_A"
printf 'armed\n' > "$S_CV_ARM/pr-reviews/pr-902.automerge"
gh_says 902 CLEAN "$SHA_A"
: > "$W2/converge-dispatch.txt"; : > "$W2/pages.txt"
run_converge "$S_CV_ARM" "$W2/conv-armed.out" 1
[ "$CRC" = "1" ] \
  || fail "converge exited $CRC on an approved, armed PR; expected 1 (goal met). It said:
$(sed 's/^/        /' "$W2/conv-armed.out")"
grep -qi "no human merge needed" "$W2/pages.txt" \
  || fail "the worker recorded PR #902 as armed and converge's page does not say the merge is
      handled. The healthy case has to stay readable or the operator checks every one by hand:
$(cat "$W2/pages.txt")"
ok "converge says no human owes the merge when the worker RECORDED the PR armed"

S_CV_UN="$W2/state-conv-unarmed"; mkdir -p "$S_CV_UN/pr-reviews"
seed_record "$S_CV_UN" 903 "APPROVE" "$SHA_A"
printf 'unarmed\n' > "$S_CV_UN/pr-reviews/pr-903.automerge"
gh_says 903 CLEAN "$SHA_A"
: > "$W2/converge-dispatch.txt"; : > "$W2/pages.txt"
run_converge "$S_CV_UN" "$W2/conv-unarmed.out" 1
grep -qi "no human merge needed" "$W2/pages.txt" \
  && fail "THE DEFECT ON THE PHONE: the worker recorded PR #903 as NOT armed and converge Slacked
      that no human merge is needed. Nobody acts, the PR sits green, and the page said it was
      fine -- the silent stall relocated into the alert channel. It said:
$(cat "$W2/pages.txt")"
grep -qi "gh pr merge --auto --squash 903" "$W2/pages.txt" \
  || fail "converge knows PR #903 is unarmed and its page does not carry the command that fixes
      it, so the operator is told there is a problem and not what to do: $(cat "$W2/pages.txt")"
ok "converge does not claim auto-merge on a PR the worker recorded as unarmed"

S_CV_NONE="$W2/state-conv-none"; mkdir -p "$S_CV_NONE/pr-reviews"
seed_record "$S_CV_NONE" 904 "APPROVE" "$SHA_A"
gh_says 904 CLEAN "$SHA_A"
: > "$W2/converge-dispatch.txt"; : > "$W2/pages.txt"
run_converge "$S_CV_NONE" "$W2/conv-none.out" 1
grep -qi "no human merge needed" "$W2/pages.txt" \
  && fail "NOTHING RECORDED THE ARM and converge asserted it anyway. This is the reviewer's own
      repro: the worker never reached the arm this round, so the claim is backed by a comment
      rather than by a read. It said:
$(cat "$W2/pages.txt")"
grep -qi "gh pr merge --auto --squash 904" "$W2/conv-none.out" \
  || fail "converge could not read the arm state and did not leave the operator the fallback
      command. It said:
$(sed 's/^/        /' "$W2/conv-none.out")"
ok "converge claims nothing about a PR whose arm state nobody recorded"

# --- R5. an unarmed PR pages ONCE, and the flag CLEARS -----------------------
# PR #33 round 3, finding 3 (minor). The comment justified per-run paging as "the
# same shape as the approved-but-blocked pages above, which also fire per run".
# All three of those go through claim_page_once and fire once per ISSUE. With the
# arm now running at the gate -- which repeats on EVERY scheduled run for as long
# as the PR sits there -- per-run paging is not merely an inaccurate comment, it
# is a page every cycle forever. The code moves to the claim the comment makes.
R_ARM9="$W2/repo-arm9"; make_repo "$R_ARM9"
S_ARM9="$W2/state-arm9"; mkdir -p "$S_ARM9"
seed_record "$S_ARM9" 901 "APPROVE" "$SHA_A"
gh_arm 901 CLEAN "$SHA_A" 1 false
: > "$ARMLOG"; : > "$W2/pages.txt"
run_worker_arm "$R_ARM9/skel" "$S_ARM9" "$W2/arm9a.out"
run_worker_arm "$R_ARM9/skel" "$S_ARM9" "$W2/arm9b.out"
PAGES_N="$(grep -c . "$W2/pages.txt" 2>/dev/null || true)"
[ -n "$PAGES_N" ] && [ "$PAGES_N" != "0" ] \
  || fail "the R5 fixture never paged at all, so it cannot judge the cardinality. Runs said:
$(sed 's/^/        /' "$W2/arm9a.out")"
[ "$PAGES_N" = "1" ] \
  || fail "an unarmed PR paged $PAGES_N times across 2 runs. Nothing about the PR changed between
      them, and the gate re-reaches this state on every scheduled run for as long as it sits
      there -- so this is a page every cycle, forever, for one unchanged fact. Noise is what
      makes the real page unreadable (founder-notifications.md). Pages:
$(sed 's/^/        /' "$W2/pages.txt")"
ok "an unarmed PR pages ONCE across repeated runs, not once per run"

# THE ONCE-ONLY FLAG HAS TO CLEAR, or the second time this PR is genuinely
# unarmed it is silent forever -- the PR #25 finding-3 scar that
# clear_conflict_rounds and clear_drift_rounds both carry.
gh_arm 901 CLEAN "$SHA_A" 0 true
: > "$W2/pages.txt"
run_worker_arm "$R_ARM9/skel" "$S_ARM9" "$W2/arm9c.out"
[ ! -s "$W2/pages.txt" ] \
  || fail "PR #901 is armed and the run paged anyway: $(cat "$W2/pages.txt")"
gh_arm 901 CLEAN "$SHA_A" 1 false
: > "$W2/pages.txt"
run_worker_arm "$R_ARM9/skel" "$S_ARM9" "$W2/arm9d.out"
[ -s "$W2/pages.txt" ] \
  || fail "PERMANENTLY SILENT: PR #901 was armed, then became unarmed again, and the once-only
      page never fired because nothing cleared the flag. A page that can only ever fire once in
      an issue's life is a page that is missing exactly when the state comes back. The run said:
$(sed 's/^/        /' "$W2/arm9d.out")"
ok "the once-only page clears when the PR is seen armed, so a NEW unarmed state still pages"

# --- wiring: the arm lives in the worker, at the PR_NUM resolution point -----
grep -q 'pr merge --auto --squash' "$WORKER" \
  || fail "linear-worker.sh never arms auto-merge"
ARM_SRC="$(grep -n 'pr merge --auto --squash' "$WORKER" | head -1 | cut -d: -f1)"
REV_SRC="$(grep -n 'REVIEWER_CMD' "$WORKER" | grep -v '^.*REVIEWER_CMD=' | head -1 | cut -d: -f1)"
[ -n "$ARM_SRC" ] && [ -n "$REV_SRC" ] && [ "$ARM_SRC" -lt "$REV_SRC" ] \
  || fail "the arm does not sit before the reviewer call in linear-worker.sh (arm at
      ${ARM_SRC:-none}, reviewer at ${REV_SRC:-none})"
ok "worker wiring: the arm is in the worker and precedes the review call"

# BOTH POPULATIONS, asserted on the CALL SITES rather than on the one `gh pr
# merge` line. Once the arm became a function, the line above moved to the
# helper's definition near the top of the file and stopped saying anything about
# where it is USED -- so this pins the two callers: the gate that skips a done PR,
# and step 5 for a PR inside a round. One caller is how this round's major got in.
ARM_CALLS="$(grep -c 'arm_automerge "' "$WORKER" 2>/dev/null || true)"
[ "${ARM_CALLS:-0}" -ge 2 ] \
  || fail "linear-worker.sh calls the arm from ${ARM_CALLS:-0} site(s). It needs both: the gate
      that skips an approved PR (nothing left but the merge -- the population this issue is
      named for) and step 5 (a PR inside a round). One caller leaves a whole population unarmed
      while the report says otherwise."
GATE10_SRC="$(grep -n 'GATE" = "10"' "$WORKER" | head -1 | cut -d: -f1)"
GATE_ARM_SRC="$(awk -v s="$GATE10_SRC" 'NR>=s && /arm_automerge "/ {print NR; exit}' "$WORKER")"
CONT_SRC="$(awk -v s="$GATE10_SRC" 'NR>=s && /^ *continue$/ {print NR; exit}' "$WORKER")"
[ -n "$GATE_ARM_SRC" ] && [ -n "$CONT_SRC" ] && [ "$GATE_ARM_SRC" -lt "$CONT_SRC" ] \
  || fail "the gate-10 branch \`continue\`s at line ${CONT_SRC:-none} before it arms (arm at
      ${GATE_ARM_SRC:-none}). That is the original defect verbatim: the skip exits the iteration
      above the arm, so the done PRs are never touched."
ok "worker wiring: the approved-PR gate arms BEFORE it skips the issue"

grep -q 'automerge_from_record' "$CONV" \
  || fail "converge.sh reports on auto-merge without reading the arm state the worker recorded.
      Asserting a state nobody read is what put 'no human merge needed' on an unarmed PR."
ok "converge wiring: the second reporter READS the arm state instead of asserting it"

bash -n "$CONV" || fail "converge.sh does not parse"
ok "converge.sh parses (bash -n)"

bash -n "$REVIEWER" || fail "pr-review-agent.sh does not parse"
ok "the reviewer parses (bash -n)"

bash -n "$LIB" || fail "pr-verdict-lib.sh does not parse"
ok "the lib parses (bash -n)"

echo "PASS: $PASS/$PASS severity-floor checks"
