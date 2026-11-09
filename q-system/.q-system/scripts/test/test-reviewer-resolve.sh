#!/usr/bin/env bash
# Pairs with reviewer-resolve.sh -- the ONE reviewer resolver (ASK-3831).
#
# THE DEFECT. The reviewer fallback was implemented four separate times and none
# of them reached a second Codex account:
#   pr-review-agent.sh    codex, then Opus, marked degraded
#   linear-worker.sh      CODEX_CMD, then SECOND_RUNNER_FALLBACK
#   kipi-dsse/commands/issue-review.md   prose: "use another row and stamp what ran"
#   prd-os/commands/prd-review.md        prose
# When Codex went out of credits on 2026-09-16 each site recorded the outage PER
# PR (24 cap tickets; every "Codex" round since then a degraded Opus stand-in)
# and no health event ever said the fleet had been down to one reviewer for
# seven weeks.
#
# THE RULE UNDER TEST. One resolver names the chain (codex primary, codex on the
# other account, then Opus), owns the ONLY `codex exec` construction in the
# scripts dir, names the stamp each engine earns, and writes AT MOST ONE outage
# event per account per UTC day -- never one per PR.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HERE/../reviewer-resolve.sh"
SCRIPTS="$HERE/.."
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }
eq()  { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want '$3', got '$2')"; fi; }
has() { case "$2" in *"$3"*) ok "$1" ;; *) bad "$1 (no '$3' in: $2)" ;; esac; }
hasnt() { case "$2" in *"$3"*) bad "$1 (found '$3' in: $2)" ;; *) ok "$1" ;; esac; }

[ -f "$LIB" ] || { echo "MISSING: $LIB"; exit 1; }

# The resolver's state lives under KIPI_STATE_DIR, so every case here is
# hermetic: no case can read or write the real fleet's outage ledger.
export KIPI_STATE_DIR="$WORK/state"
# shellcheck source=/dev/null
. "$LIB"

echo "== the chain, with no second account configured =="
unset KIPI_CODEX_SECONDARY_HOME KIPI_CODEX_RUNNER_2 2>/dev/null || true
CANDS="$(reviewer_candidates review)"
eq "two candidates when no second account is configured" "$(printf '%s\n' "$CANDS" | wc -l | tr -d ' ')" "2"
eq "first is codex on the primary account" "$(printf '%s\n' "$CANDS" | sed -n 1p)" "codex	primary	codex-review"
eq "last is the Opus stand-in"             "$(printf '%s\n' "$CANDS" | sed -n 2p)" "claude	-	claude-review"

echo "== the chain, with a second account configured =="
export KIPI_CODEX_SECONDARY_HOME="$WORK/codex-home-2"
mkdir -p "$KIPI_CODEX_SECONDARY_HOME"
CANDS="$(reviewer_candidates review)"
eq "three candidates once a second account exists" "$(printf '%s\n' "$CANDS" | wc -l | tr -d ' ')" "3"
eq "the second account sits BETWEEN codex and Opus" "$(printf '%s\n' "$CANDS" | sed -n 2p)" "codex	codex-home-2	codex-review"
eq "Opus is still last"                             "$(printf '%s\n' "$CANDS" | sed -n 3p)" "claude	-	claude-review"
# A LABEL IS NOT A HOME. The account name recorded on the verdict record is
# overridable, because the basename of a config dir is an implementation detail
# and the founder may name the account something else.
export KIPI_CODEX_SECONDARY_LABEL="codex-ktlyst"
eq "the recorded account name is overridable" \
  "$(reviewer_candidates review | sed -n 2p)" "codex	codex-ktlyst	codex-review"
unset KIPI_CODEX_SECONDARY_LABEL

echo "== a home that does not exist is NOT a candidate =="
# A configured-but-absent CODEX_HOME would make codex exec fail with a confusing
# auth error on every review. Absent means not configured.
export KIPI_CODEX_SECONDARY_HOME="$WORK/nope-not-here"
eq "an absent secondary home drops out of the chain" \
  "$(reviewer_candidates review | wc -l | tr -d ' ')" "2"
export KIPI_CODEX_SECONDARY_HOME="$WORK/codex-home-2"

echo "== the stamps =="
eq "codex review stamp"           "$(reviewer_stamp codex review)"            "codex-review"
eq "codex adversarial stamp"      "$(reviewer_stamp codex adversarial)"       "codex-adversarial"
eq "claude review stamp"          "$(reviewer_stamp claude review)"           "claude-review"
eq "claude adversarial stamp"     "$(reviewer_stamp claude adversarial)"      "claude-adversarial"
eq "the adversarial chain carries adversarial stamps" \
  "$(reviewer_candidates adversarial | sed -n 1p)" "codex	primary	codex-adversarial"
eq "an unknown role is refused rather than silently stamped" \
  "$(reviewer_stamp codex nonsense 2>/dev/null; echo "rc=$?")" "rc=2"

echo "== the ONE codex exec construction =="
PRIM="$(reviewer_codex_cmd primary)"
has "the primary invocation is codex exec"          "$PRIM" "codex exec"
hasnt "the primary invocation sets no CODEX_HOME"   "$PRIM" "CODEX_HOME"
SEC="$(reviewer_codex_cmd codex-home-2)"
has "the second account invocation is codex exec"   "$SEC" "codex exec"
has "the second account invocation pins CODEX_HOME" "$SEC" "CODEX_HOME=$WORK/codex-home-2"
eq "an unknown account is refused, never run as the primary" \
  "$(reviewer_codex_cmd made-up 2>/dev/null; echo "rc=$?")" "rc=2"
# THE TEST STUB IS A FIRST-CLASS PATH (same reason KIPI_PR_REVIEWER is). Without
# it every "what if both Codex accounts are out" case bills two real model runs,
# so the branch stays untested, which is exactly how the single-account
# assumption shipped four times.
KIPI_CODEX_RUNNER="/bin/false" eq "the primary runner is injectable for tests" \
  "$(KIPI_CODEX_RUNNER=/bin/false reviewer_codex_cmd primary)" "/bin/false"
eq "the second-account runner is injectable too" \
  "$(KIPI_CODEX_RUNNER_2=/bin/false reviewer_codex_cmd codex-home-2)" "/bin/false"

echo "== one outage event per account per day, never one per PR =="
EV="$(reviewer_outage_events_path)"
has "the event file lives under KIPI_STATE_DIR" "$EV" "$WORK/state"
reviewer_note_codex_outage primary "rc=1 on PR 101"
reviewer_note_codex_outage primary "rc=1 on PR 102"
reviewer_note_codex_outage primary "rc=1 on PR 103"
eq "three failed PRs on one account write ONE event" \
  "$(grep -c '"account": *"primary"' "$EV" 2>/dev/null || echo 0)" "1"
reviewer_note_codex_outage codex-home-2 "rc=1 on PR 101"
reviewer_note_codex_outage codex-home-2 "rc=1 on PR 102"
eq "the other account gets its own single event" \
  "$(grep -c '"account": *"codex-home-2"' "$EV" 2>/dev/null || echo 0)" "1"
eq "two accounts out is two events, not four" "$(wc -l < "$EV" | tr -d ' ')" "2"
has "the event names the day"    "$(cat "$EV")" "$(date -u +%Y-%m-%d)"
has "the event carries the reason" "$(cat "$EV")" "rc=1 on PR 101"

echo "== yesterday's event does not silence today =="
# Roll the clock back by aging BOTH halves the way a real overnight would: the
# events already on disk, and the per-account day stamp that is the actual dedup
# key. Aging only the events file would leave the stamp reading today and prove
# nothing about a day boundary.
python3 - "$EV" "$(reviewer_outage_state_path)" <<'PY'
import json, sys
ev, state_path = sys.argv[1], sys.argv[2]
rows = [json.loads(l) for l in open(ev) if l.strip()]
for r in rows:
    r["day"] = "2000-01-01"
    r["ts"] = "2000-01-01T00:00:00Z"
with open(ev, "w") as fh:
    for r in rows:
        fh.write(json.dumps(r, sort_keys=True) + "\n")
state = json.load(open(state_path))
for acct in state:
    state[acct]["outage_day"] = "2000-01-01"
json.dump(state, open(state_path, "w"), indent=2, sort_keys=True)
PY
reviewer_note_codex_outage primary "rc=1 the next morning"
eq "a new day earns a new event" \
  "$(grep -c "$(date -u +%Y-%m-%d)" "$EV")" "1"
eq "today's events are readable on their own" \
  "$(reviewer_outage_events_today | wc -l | tr -d ' ')" "1"

echo "== recovery clears the account, so the NEXT outage pages again =="
reviewer_note_codex_ok primary
reviewer_note_codex_outage primary "rc=1 after a recovery"
eq "an outage after a recovery earns its own event in the same day" \
  "$(reviewer_outage_events_today | grep -c '"account": *"primary"')" "2"

echo "== Done: the scripts dir has exactly one codex exec INVOCATION =="
# The DoR's grep catches prose too (every scar comment in this fleet names the
# command it is about), so the check is on invocations: a `codex exec` that is
# not inside a comment. One, and it is the resolver's.
INVOKERS="$(grep -ln 'codex exec' "$SCRIPTS"/*.sh | while read -r f; do
  grep -o '^[^#]*codex exec' "$f" >/dev/null 2>&1 && echo "$f"
done)"
eq "only reviewer-resolve.sh constructs a codex exec invocation" \
  "$(printf '%s\n' "$INVOKERS" | sed '/^$/d' | xargs -n1 basename 2>/dev/null | sort | tr '\n' ' ')" \
  "reviewer-resolve.sh "

echo "== the verdict record names WHO ANSWERED, not which flag was passed =="
# THE SHIPPED WRITER, extracted and executed -- not a copy of it. Same anchors
# test-review-degraded-provenance.sh uses, for the same reason: the one reader of
# these keys must be production's, or every case below proves a record shape the
# fleet does not write. The extraction gets a NEGATIVE SELF-TEST first, because
# an awk range that quietly matches nothing makes every later case pass.
AGENT="$SCRIPTS/pr-review-agent.sh"
WRITER="$WORK/writer.sh"
awk '/^REVIEWED_BY="\$CODEX_MODEL"$/,/^PY$/' "$AGENT" > "$WRITER"
if grep -q 'json.dump' "$WRITER" && grep -q 'RESOLVED_ENGINE=' "$WRITER"; then
  ok "extracted $(wc -l < "$WRITER" | tr -d ' ') lines carrying the resolution and the json writer"
else
  bad "the extraction anchors are wrong -- no json writer or no RESOLVED_ENGINE in the range"
fi

run_writer() {  # run_writer <engine-flag> <degraded> <dir> [resolved-engine] [account] [stamp]
  local flag="$1" degraded="$2" vdir="$3"
  mkdir -p "$vdir"
  (
    set +u
    TS() { echo "2026-11-09T12:00:00Z"; }
    CODEX_MODEL="gpt-5.6-sol"; CLAUDE_MODEL="claude-opus-5"
    ENGINE="$flag"; DEGRADED="$degraded"
    RESOLVED_ENGINE="${4:-}"; RESOLVED_ACCOUNT="${5:-}"; RESOLVED_STAMP="${6:-}"
    PR=900; ISSUE="ASK-3831"; VERDICT="APPROVE"
    REVIEW="$vdir/pr-900-review.md"; STATED_VERDICT="APPROVE"
    DERIVED_VERDICT="APPROVE"; ROUND=1
    HEAD_SHA="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    VERDICT_DIR="$vdir"; INVOKER="worker"; REVIEW_USABLE=1; REVIEW_SLUG=""
    . "$SCRIPTS/repo-slug-lib.sh"
    . "$WRITER"
  ) >/dev/null 2>&1
}
key() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],"<missing>"))' "$1" "$2"; }

# THE DoR's CHECK, half one: both Codex invocations down, the review lands on
# Opus, and the record says so where a machine reads it.
run_writer codex 1 "$WORK/v1"
R1="$WORK/v1/pr-900.verdict.json"
if [ -f "$R1" ]; then
  eq "a degraded round records engine=claude (it used to say codex)" "$(key "$R1" engine)" "claude"
  eq "the flag it was INVOKED with is kept, so the outage is still legible"  "$(key "$R1" engine_flag)" "codex"
  eq "the stamp is claude-review"      "$(key "$R1" stamp)"   "claude-review"
  eq "the Opus stand-in has no account" "$(key "$R1" account)" "-"
  eq "degraded is still true"           "$(key "$R1" degraded)" "True"
else
  bad "no verdict record was written at $R1"
fi

# Half two: the primary account is down, the OTHER account answered. Still codex,
# still a second lab, so NOT degraded -- and the record names the account.
run_writer codex 0 "$WORK/v2" codex codex-home-2 codex-review
R2="$WORK/v2/pr-900.verdict.json"
if [ -f "$R2" ]; then
  eq "a second-account round records engine=codex" "$(key "$R2" engine)"  "codex"
  eq "and names which account read the code"        "$(key "$R2" account)" "codex-home-2"
  eq "stamped codex-review"                         "$(key "$R2" stamp)"   "codex-review"
  eq "NOT degraded: a second login is still a second lab" "$(key "$R2" degraded)" "False"
else
  bad "no verdict record was written at $R2"
fi

echo "== the health consumer reads the ledger, and one outage is ONE finding =="
# The consumer is fleet-health-daily.py's detector, driven directly. Asserting a
# model of it here would be the sp-e9284708 defect: a fail-safe that lives only
# in the test file.
eq "two accounts out today is ONE finding, not one per account or per PR" \
  "$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("fh", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
rows = [{"kind": "codex-outage", "account": a, "day": "d", "ts": "t", "reason": "exit 1"}
        for a in ("primary", "codex-home-2")]
f = m.codex_outage_findings(rows)
print(len(f), f[0]["subject"] if f else "")
' "$SCRIPTS/fleet-health-daily.py")" "1 codex-reviewer-outage"
eq "a healthy fleet files nothing at all" \
  "$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("fh", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(len(m.codex_outage_findings([])))
' "$SCRIPTS/fleet-health-daily.py")" "0"

echo "== the two PROSE call sites point at the resolver, not at their own order =="
# These two cannot source a shell lib as part of their control flow -- they are
# instructions a model follows, and the reviewer they drive is a plugin command
# (`codex:review`), not `codex exec`. What the resolver gives them is the ORDER
# and the STAMP VOCABULARY, which is the half that drifted: both said "use
# another row and stamp what ran", which is four words for "pick one" and is how
# a seven-week outage went unrecorded at two of the four sites.
REPO="$(cd "$SCRIPTS/../../.." && pwd)"
for md in plugins/kipi-dsse/commands/issue-review.md plugins/prd-os/commands/prd-review.md; do
  if [ -f "$REPO/$md" ]; then
    grep -q 'reviewer-resolve.sh' "$REPO/$md" \
      && ok "$md names the resolver" || bad "$md does not name the resolver"
    grep -q 'reviewer_note_codex_outage' "$REPO/$md" \
      && ok "$md records an outage through the one ledger" \
      || bad "$md records an outage privately again"
    grep -q 'use another row and stamp what ran' "$REPO/$md" \
      && bad "$md still carries the free-choice prose the resolver replaced" \
      || ok "$md no longer lets the session choose the order"
  else
    bad "$md is missing"
  fi
done

echo
echo "pass=$PASS fail=$FAIL"
[ "$FAIL" -eq 0 ]
