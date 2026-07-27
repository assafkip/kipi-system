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

# --- wiring: the worker actually consults the merge state --------------------
grep -q 'pr_merge_state' "$WORKER" \
  || fail "linear-worker.sh never reads the merge state (the gate's second argument would be empty forever)"
grep -q 'MAX_CONFLICT_ROUNDS' "$WORKER" \
  || fail "linear-worker.sh has no conflict-round cap"
ok "worker wiring: merge state read through the lib, conflict cap present"

bash -n "$LIB" || fail "pr-verdict-lib.sh does not parse"
ok "the lib parses (bash -n)"

echo "PASS: $PASS/$PASS severity-floor checks"
