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

echo "== a second-account path with a space is still RUNNABLE =="
# PR #701 review, minor 2. Both production call sites splice this prefix into a
# `bash -c "<string>"` that bash RE-PARSES (pr-review-agent.sh run_engine,
# linear-worker.sh CODEX_CMD_2), so an unquoted path split at the space: bash read
# `CODEX_HOME=/..../codex` and then tried to run `home` -- exit 127, which
# is_environmental reads as a machine refusal and the ledger records as that
# account's OUTAGE. A typo-free config would have looked like a credit outage.
SPACE_HOME="$WORK/codex home 2"
mkdir -p "$SPACE_HOME"
mkdir -p "$WORK/bin"
cat > "$WORK/bin/show-home" <<'STUB'
#!/usr/bin/env bash
printf '%s' "${CODEX_HOME:-<unset>}"
STUB
chmod +x "$WORK/bin/show-home"
SPACE_CMD="$(KIPI_CODEX_SECONDARY_HOME="$SPACE_HOME" KIPI_CODEX_SECONDARY_LABEL=spacey \
             KIPI_CODEX_RUNNER="$WORK/bin/show-home" reviewer_codex_cmd spacey)"
# Run it the way production does: re-parsed by bash out of a command string.
eq "CODEX_HOME survives a path containing a space" \
  "$(bash -c "$SPACE_CMD" 2>/dev/null)" "$SPACE_HOME"

echo "== concurrent reviews write ONE event, not one each =="
# PR #701 review, minor 3. A fleet-wide credit outage fails every live review in
# the same instant -- the worker's second runner plus every open PR's reviewer --
# and the read-modify-write had no lock, so each process read "no event today"
# and appended one. The file header promises ONE event per account per UTC day;
# without serialisation it held N, and the health finding's "first seen" line
# came from whichever row happened to be first.
RACE="$WORK/race"
mkdir -p "$RACE"
(
  REVIEWER_RESOLVE_STATE_DIR="$RACE"
  for i in $(seq 1 20); do
    reviewer_note_codex_outage primary "rc=1 on PR $i" &
  done
  wait
)
eq "20 concurrent outage notes write exactly ONE event" \
  "$({ grep -c '"account": *"primary"' "$RACE/codex-outage-events.jsonl" 2>/dev/null || echo 0; } | head -1)" "1"
eq "and the state file is still valid JSON after the race" \
  "$(python3 -c 'import json,sys; json.load(open(sys.argv[1])); print("ok")' \
      "$RACE/codex-account-health.json" 2>/dev/null)" "ok"
# THE CASE ABOVE IS THE INVARIANT, NOT THE MECHANISM, and on its own it is
# decoration: the read-modify-write window is microseconds, 20 shell-spawned
# python processes stagger by more than that, and the unserialised version passed
# it on this machine. So the lock is ALSO proven directly -- hold the writer's own
# lock from outside and measure that the writer waits for it. Unlocked, it returns
# in milliseconds, which is the RED this case exists to produce.
LOCKDIR="$WORK/lockproof"
mkdir -p "$LOCKDIR"
python3 - "$LOCKDIR/codex-account-health.json.lock" <<'PY' &
import fcntl, sys, time
fh = open(sys.argv[1], "a+")
fcntl.flock(fh, fcntl.LOCK_EX)
time.sleep(1.2)
PY
HOLDER=$!
sleep 0.3
LOCK_START="$(python3 -c 'import time; print(time.time())')"
( REVIEWER_RESOLVE_STATE_DIR="$LOCKDIR"; reviewer_note_codex_outage primary "rc=1 while the lock is held" )
eq "the writer waits for another holder of its own lock" \
  "$(python3 -c 'import sys, time; print(1 if time.time() - float(sys.argv[1]) >= 0.5 else 0)' "$LOCK_START")" "1"
wait "$HOLDER" 2>/dev/null || true

echo "== one outage event per account per day, never one per PR =="
EV="$(reviewer_outage_events_path)"
has "the event file lives under KIPI_STATE_DIR" "$EV" "$WORK/state"
reviewer_note_codex_outage primary "rc=1 on PR 101"
reviewer_note_codex_outage primary "rc=1 on PR 102"
reviewer_note_codex_outage primary "rc=1 on PR 103"
eq "three failed PRs on one account write ONE event" \
  "$({ grep -c '"account": *"primary"' "$EV" 2>/dev/null || echo 0; } | head -1)" "1"
reviewer_note_codex_outage codex-home-2 "rc=1 on PR 101"
reviewer_note_codex_outage codex-home-2 "rc=1 on PR 102"
eq "the other account gets its own single event" \
  "$({ grep -c '"account": *"codex-home-2"' "$EV" 2>/dev/null || echo 0; } | head -1)" "1"
eq "two accounts out is two events, not four" "$(wc -l < "$EV" | tr -d ' ')" "2"
has "the event names the day"    "$(cat "$EV")" "$(date -u +%Y-%m-%d)"
# THE EVENT CARRIES A CODE, NOT THE CALLER'S WORDS (PR #701 review round 2,
# major). This case asserted the opposite: that `rc=1 on PR 101` reached the
# event file verbatim. That value is the agent's own harmless string, but the
# key it lands in is published VERBATIM in a permanent Linear issue, and the two
# prose call sites were telling the model to put Codex's refusal line there. The
# contract is now one of REVIEWER_OUTAGE_CODES, coerced by the writer.
has "the event carries a bucketed CODE, not the caller's words" "$(cat "$EV")" '"reason_code": "exec-failure"'
hasnt "and not the caller's own phrasing"                       "$(cat "$EV")" "PR 101"

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
    # BOTH day keys, because they answer different questions and the append is
    # keyed on `event_day`: ageing only `outage_day` would leave today's event
    # already filed and prove nothing about a day boundary.
    for key in ("outage_day", "event_day"):
        if key in state[acct]:
            state[acct][key] = "2000-01-01"
json.dump(state, open(state_path, "w"), indent=2, sort_keys=True)
PY
reviewer_note_codex_outage primary "rc=1 the next morning"
eq "a new day earns a new event" \
  "$(grep -c "$(date -u +%Y-%m-%d)" "$EV")" "1"
eq "today's events are readable on their own" \
  "$(reviewer_outage_events_today | wc -l | tr -d ' ')" "1"

echo "== recovery clears the account, and the day's event stays ONE =="
# THIS CASE USED TO ASSERT THE OPPOSITE and it was wrong (PR #701 review round 3,
# minor 3). It expected a second event row after a recovery, which contradicted
# the contract stated in this file's header, in the resolver's header and in both
# prose call sites: at most ONE event per account per UTC day. The row count is
# not what tells an operator the account is down again -- `outage_day` is, and the
# detector reads it. The case now pins both halves, so a future change cannot buy
# a quiet ledger by losing the live posture.
reviewer_note_codex_ok primary
reviewer_note_codex_outage primary "rc=1 after a recovery"
eq "an outage after a recovery does NOT append a second row" \
  "$(reviewer_outage_events_today | grep -c '"account": *"primary"')" "1"
eq "and the account reads as down again, which is what the detector reads" \
  "$(python3 -c 'import json,sys
print(json.load(open(sys.argv[1]))["primary"].get("outage_day","<none>"))' \
     "$(reviewer_outage_state_path)")" "$(date -u +%Y-%m-%d)"

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
  # claude-ADVERSARIAL, not claude-review (PR #701 review round 2, minor). This
  # case asserted the defect: pr-review-agent.sh is the adversarial reviewer, its
  # REVIEWER_ROLE is `adversarial` and all five dispatch branches stamp through
  # reviewer_stamp -- and then one `[ "$DEGRADED" = "1" ] &&` line overwrote the
  # lot with a literal `claude-review` on exactly the degraded path.
  eq "the degraded stamp KEEPS the adversarial role" "$(key "$R1" stamp)" "claude-adversarial"
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

echo "== the health consumer reads RECOVERY, not only the append-only log =="
# PR #701 review, MAJOR. The event log is append-only, so a single transient
# failure at 03:00 sat in today's rows for the rest of the UTC day. The detector
# read only that log, so it filed a permanent Linear issue saying "the reviewer is
# down to Opus" while Codex had been answering since 03:01 -- and filed the same
# claim on a round the SECOND account answered successfully. The recovery state
# (codex-account-health.json, written by reviewer_note_codex_ok) is the other half
# and has to be read with it.
HEALTH_CASES="$WORK/health_cases.py"
cat > "$HEALTH_CASES" <<'PY'
import importlib.util, sys
from datetime import datetime, timezone
spec = importlib.util.spec_from_file_location("fh", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
DAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
TS = DAY + "T03:00:00Z"

def rows(*accounts):
    return [{"kind": "codex-outage", "account": a, "day": DAY, "ts": TS,
             "reason": "exit 1"} for a in accounts]

case = sys.argv[2]
if case == "recovered":
    # Failed at 03:00, answered at 03:01. reviewer_note_codex_ok popped the day
    # stamp; the event row is still on disk and always will be.
    f = m.codex_outage_findings(rows("primary"),
                               {"primary": {"last_ok": DAY + "T03:01:00Z", "fails": 0}})
    print(len(f))
elif case == "second-answered":
    f = m.codex_outage_findings(
        rows("primary"),
        {"primary": {"outage_day": DAY, "last_fail": TS},
         "codex-home-2": {"last_ok": DAY + "T03:05:00Z", "fails": 0}})
    print(len(f), "down-to-opus" if "down to Opus" in f[0]["title"] else "no-opus-claim",
          "names-answerer" if "codex-home-2" in f[0]["body"] else "silent-on-answerer")
elif case == "all-down":
    f = m.codex_outage_findings(
        rows("primary", "codex-home-2"),
        {"primary": {"outage_day": DAY}, "codex-home-2": {"outage_day": DAY}})
    print(len(f), "down-to-opus" if "down to Opus" in f[0]["title"] else "no-opus-claim")
elif case == "state-unreadable":
    # No recovery state at all beside a real event: that is an anomaly, and the
    # safe direction is to report rather than to go quiet.
    f = m.codex_outage_findings(rows("primary"), {})
    print(len(f))
elif case == "subject-stable":
    a = m.codex_outage_findings(rows("primary"),
                               {"primary": {"outage_day": DAY},
                                "codex-home-2": {"last_ok": DAY + "T01:00:00Z"}})
    b = m.codex_outage_findings(rows("primary", "codex-home-2"),
                               {"primary": {"outage_day": DAY},
                                "codex-home-2": {"outage_day": DAY}})
    print(a[0]["subject"] == b[0]["subject"])
PY
eq "a transient failure that recovered files NOTHING" \
  "$(python3 "$HEALTH_CASES" "$SCRIPTS/fleet-health-daily.py" recovered)" "0"
eq "one account down while the other answers is not 'down to Opus'" \
  "$(python3 "$HEALTH_CASES" "$SCRIPTS/fleet-health-daily.py" second-answered)" \
  "1 no-opus-claim names-answerer"
eq "every account down IS 'down to Opus'" \
  "$(python3 "$HEALTH_CASES" "$SCRIPTS/fleet-health-daily.py" all-down)" "1 down-to-opus"
eq "an event with no recovery state still reports" \
  "$(python3 "$HEALTH_CASES" "$SCRIPTS/fleet-health-daily.py" state-unreadable)" "1"
eq "the dedup subject does not move when the posture flips mid-day" \
  "$(python3 "$HEALTH_CASES" "$SCRIPTS/fleet-health-daily.py" subject-stable)" "True"

echo "== the reader and the writer agree on the state file =="
# The detector's reader is pointed at a ledger the RESOLVER wrote, never at a
# hand-built fixture: an invented shape tests this test's assumption, not the
# contract between two scripts (feedback_fixtures_from_producers).
PAIR="$WORK/pair"
mkdir -p "$PAIR"
(
  REVIEWER_RESOLVE_STATE_DIR="$PAIR"
  reviewer_note_codex_outage primary "rc=1 on PR 700"
  reviewer_note_codex_ok primary
)
eq "an outage the resolver then cleared reads as NO finding" \
  "$(KIPI_STATE_DIR="$PAIR" python3 -c '
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("fh", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(len(m.detect_codex_outage(None)))
' "$SCRIPTS/fleet-health-daily.py")" "0"
(
  REVIEWER_RESOLVE_STATE_DIR="$PAIR"
  reviewer_note_codex_outage primary "rc=1 on PR 701"
)
eq "and the same ledger with the account still down reads as ONE finding" \
  "$(KIPI_STATE_DIR="$PAIR" python3 -c '
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("fh", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
f = m.detect_codex_outage(None)
print(len(f))
' "$SCRIPTS/fleet-health-daily.py")" "1"

echo "== the PR reviewer stamps ADVERSARIAL, which is what it is =="
# PR #701 review, minor 4. reviewer_stamp refuses an unknown role precisely so a
# reader can tell which bar the code was held to -- and then every call site in
# pr-review-agent.sh passed `review`, while the script's own first line calls it
# "Fresh eyes, adversarial" and its prompt says "you are ADVERSARIAL by default".
# A refused-unknown-value argument that is always passed the wrong known value
# protects nothing. findings_writer.py and issue_findings.py both accept
# codex-adversarial / claude-adversarial as REVIEWER_SOURCES, so the honest token
# already exists.
eq "no call site stamps the adversarial reviewer as an ordinary review" \
  "$(grep -c 'reviewer_stamp [a-zA-Z"$][^ ]* review' "$AGENT" || true)" "0"
eq "the role is declared once, as adversarial" \
  "$(grep -c '^REVIEWER_ROLE="adversarial"$' "$AGENT")" "1"
# COUNT-FREE ON PURPOSE (PR #701 review round 2). This case used to pin the
# NUMBER of call sites at 5, so adding a correct sixth turned it red and the
# number -- not the property -- was what a later round had to edit. The property
# is that no INVOCATION hardcodes a role; comment lines that merely discuss
# reviewer_stamp are excluded, since prose is not a call.
eq "no reviewer_stamp INVOCATION hardcodes a role" \
  "$(grep 'reviewer_stamp ' "$AGENT" | grep -v '^[[:space:]]*#' | grep -vc 'REVIEWER_ROLE' || true)" "0"
eq "and the call sites are still there to read it (at least one per engine)" \
  "$([ "$(grep -c 'reviewer_stamp [a-zA-Z"$]' "$AGENT")" -ge 2 ] && echo yes || echo no)" "yes"
# Not a grep of the intent: the agent's OWN declaration is executed against the
# shipped reviewer_stamp, so a role the resolver would refuse fails here.
eq "the agent's declared role produces a real adversarial stamp" \
  "$(eval "$(grep '^REVIEWER_ROLE=' "$AGENT")"; reviewer_stamp codex "$REVIEWER_ROLE")" \
  "codex-adversarial"
# THE WORKER WRITES THE OTHER HALF OF THE LEDGER (PR #701 review, major, one
# layer out). Its primary-account health was noted only inside the
# second-account branch and only on a failure: with no second account the worker
# recorded no outage at all, and a success never cleared a stale day stamp, so
# the reader fix above would have reported a 03:00 transient all day.
WORKER="$SCRIPTS/linear-worker.sh"
# Round 3 moved that decision into the resolver: the worker hands over its rc and
# its output, and `reviewer_note_codex_result` is what clears the account on rc 0.
# Grepping for the old `ok` call would now assert the wiring this round removed.
eq "the worker notes the primary account's result either way, before the next rung" \
  "$(grep -c 'reviewer_note_codex_result "\$REVIEWER_PRIMARY_ACCOUNT" "\$crc" "\$CODEX_OUT"' "$WORKER")" "1"
eq "and it no longer decides for itself what a failed run means" \
  "$({ grep -c '^[^#]*reviewer_note_codex_\(ok\|outage\)' "$WORKER" || true; } | head -1)" "0"
run_writer codex 0 "$WORK/v3" codex primary "$(reviewer_stamp codex adversarial)"
R3="$WORK/v3/pr-900.verdict.json"
if [ -f "$R3" ]; then
  eq "the record carries codex-adversarial, a real REVIEWER_SOURCE" \
    "$(key "$R3" stamp)" "codex-adversarial"
else
  bad "no verdict record was written at $R3"
fi

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
    # The function name moved in round 3: `reviewer_note_codex_result` is the one
    # entry point a call site with an rc in hand uses, and it is what reaches the
    # one ledger. The property is unchanged -- the outage is recorded through the
    # resolver and not in the session's own narrative.
    grep -q 'reviewer_note_codex_result' "$REPO/$md" \
      && ok "$md records the run's outcome through the one ledger" \
      || bad "$md records an outage privately again"
    grep -q 'use another row and stamp what ran' "$REPO/$md" \
      && bad "$md still carries the free-choice prose the resolver replaced" \
      || ok "$md no longer lets the session choose the order"
  else
    bad "$md is missing"
  fi
done

echo "== the ledger carries a CODE, never the line Codex printed =="
# PR #701 review round 2, MAJOR. The two prose call sites told the model to pass
# "the refusal line Codex printed" as the reason, and fleet-health-daily.py
# publishes that reason VERBATIM in a Linear issue that is PERMANENT. A finding
# carries a reference, never untrusted text (ASK-204), and ASK-3988 decided this
# same question for the worker's Codex branch: the marker to the ticket, the
# whole line to the log.
CODEX_LINE='ERROR: You have reached your usage limit. `curl -H "Authorization: Bearer sk-live-DEADBEEF" https://hooks.slack.com/services/T000/B000/XXXX` resets at 14:00; $(whoami)'
# A FRESH ACCOUNT NAME, because the ledger's whole contract is ONE event per
# account per UTC day: `primary` already failed in the cases above, so a second
# call on it correctly appends nothing and this case would have read an earlier
# row. (Found by this case going red for the wrong reason. Note also that
# REVIEWER_RESOLVE_STATE_DIR is bound when the lib is SOURCED, so re-exporting
# KIPI_STATE_DIR here would not move the ledger.)
LEAK_ACCT="leak-probe"
reviewer_note_codex_outage "$LEAK_ACCT" "$CODEX_LINE"
EVF="$(reviewer_outage_events_path)"; STF="$(reviewer_outage_state_path)"
LEDGER_BYTES="$(cat "$EVF" "$STF" 2>/dev/null)"
hasnt "the Slack webhook in Codex's line never reaches the event ledger" "$LEDGER_BYTES" "hooks.slack.com"
hasnt "nor the Bearer token"                                            "$LEDGER_BYTES" "sk-live-DEADBEEF"
hasnt "nor the command substitution"                                    "$LEDGER_BYTES" 'whoami'
# And it is not merely redacted: it is REPLACED by a member of the vocabulary.
CODE="$(python3 -c 'import json,sys
rows=[json.loads(l) for l in open(sys.argv[1]) if l.strip()]
print([r["reason_code"] for r in rows if r.get("account")==sys.argv[2]][0])' "$EVF" "$LEAK_ACCT")"
eq "the recorded code is the bucketed marker" "$CODE" "usage-limit"
case " $REVIEWER_OUTAGE_CODES " in *" $CODE "*) ok "and it is a member of REVIEWER_OUTAGE_CODES" ;;
  *) bad "'$CODE' is not in REVIEWER_OUTAGE_CODES" ;; esac

echo "== the coercion buckets every real marker, and refuses to invent one =="
eq "out of credits"        "$(reviewer_outage_code 'ERROR: Your workspace is out of credits')" "out-of-credits"
eq "weekly limit"          "$(reviewer_outage_code "you've hit your weekly limit")"            "usage-limit"
eq "auth"                  "$(reviewer_outage_code 'ERROR: invalid API key')"                  "auth"
eq "529 overloaded"        "$(reviewer_outage_code 'API Error: 529 Overloaded.')"              "overloaded"
eq "the agent's own exit"  "$(reviewer_outage_code 'exit 124 on PR #701')"                     "exec-failure"
# THE DEFAULT IS A CODE, NOT THE INPUT. A marker nobody bucketed costs one grain
# of detail in the health line; it never leaks a byte.
eq "an unknown refusal degrades to unclassified" \
  "$(reviewer_outage_code 'something nobody has seen before')" "unclassified"
# A caller that already resolved the code hands it over unchanged...
eq "a real code passes through"      "$(_reviewer_code_or_unclassified auth)" "auth"
# ...and one that dresses free text up as a code does not get to publish it.
eq "code-SHAPED free text does not pass" \
  "$(_reviewer_code_or_unclassified 'totally-a-code-honest')" "unclassified"

echo "== the DETECTOR withholds a row that is not a bounded token =="
# THE SECOND BELT, on the READ. The coercion above runs on the write, so a row
# left by an older resolver or a hand-edited ledger is the case it cannot cover,
# and that row's bytes would otherwise land in a permanent issue body.
# THE NOTIFIER IS STUBBED BEFORE THE MODULE IS EVEN IMPORTED. This case only
# calls one pure function, but fleet-health-daily.py reaches slack-notify.sh and
# a suite is not allowed to be one refactor away from paging a real phone (scar
# 2026-08-01: a 14/14-green suite paged the founder twice).
DET="$(KIPI_NOTIFY=/usr/bin/true python3 - "$SCRIPTS/fleet-health-daily.py" "$CODEX_LINE" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("fhd", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
from datetime import datetime, timezone
day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
rows = [{"kind": "codex-outage", "account": "primary", "day": day,
         "ts": day + "T03:00:00Z", "reason_code": sys.argv[2]}]
out = m.codex_outage_findings(rows, {"primary": {"outage_day": day}})
print(out[0]["body"] if out else "<no finding>")
PY
)"
hasnt "the detector does not publish a long raw reason it found on disk" "$DET" "hooks.slack.com"
has   "it says so in the body instead"                                   "$DET" "unpublishable"
has   "and it still points the operator at the local ledger"             "$DET" "codex-outage-events.jsonl"

# A ROW FROM THE PRE-RENAME WRITER IS NOT HYPOTHETICAL. The ledger lives in
# $KIPI_STATE_DIR on a real machine, and the pass-1 resolver wrote `reason` with
# the caller's raw words in it -- including on this developer's own box, from the
# suite above. The reader must not publish those rows either, and the absent key
# must not crash the detector that is the only thing telling Sana the reviewer is
# down. Withheld, not guessed.
OLDROW="$(KIPI_NOTIFY=/usr/bin/true python3 - "$SCRIPTS/fleet-health-daily.py" "$CODEX_LINE" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("fhd", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
from datetime import datetime, timezone
day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
rows = [{"kind": "codex-outage", "account": "primary", "day": day,
         "ts": day + "T03:00:00Z", "reason": sys.argv[2]}]   # the OLD key
out = m.codex_outage_findings(rows, {"primary": {"outage_day": day}})
# Title AND body: the withholding happens in the body, and "is the outage still
# reported at all" is answered by the title.
print((out[0]["title"] + "\n" + out[0]["body"]) if out else "<no finding>")
PY
)"
hasnt "a pre-rename row's raw reason is not published either" "$OLDROW" "hooks.slack.com"
has   "the missing code reads as withheld, not as an empty line" "$OLDROW" "unpublishable"
has   "and the outage is STILL reported -- the row is not dropped" "$OLDROW" "down to Opus"

echo "== the prose call sites no longer hand raw Codex output to the ledger =="
for md in plugins/kipi-dsse/commands/issue-review.md plugins/prd-os/commands/prd-review.md; do
  grep -q 'the refusal line Codex printed' "$REPO/$md" \
    && bad "$md still tells the session to pass Codex's own line into a permanent issue" \
    || ok "$md no longer passes Codex's line"
  grep -q 'codex_env_marker' "$REPO/$md" \
    && ok "$md hands over the closed-vocabulary marker (ASK-3988)" \
    || bad "$md names no bounded source for the reason"
  # ROUND 3: and it does not ask the SESSION to decide what a failed run means.
  # A prose site that files an outage on any non-zero exit is the agent's major
  # finding wearing a markdown file, and no hook watches a command's prose.
  grep -q 'reviewer_note_codex_result' "$REPO/$md" \
    && ok "$md routes the run's result through the resolver's one decision" \
    || bad "$md still asks the session to classify the failure itself"
  grep -q 'reviewer_note_codex_outage' "$REPO/$md" \
    && bad "$md still names the bare outage writer as the thing to call" \
    || ok "$md no longer calls the bare outage writer"
  # The one-event claim this file's header makes is now TRUE on a flapping day,
  # so the prose that repeats the claim says which day it means.
  grep -q 'recovers and fails again' "$REPO/$md" \
    && ok "$md's one-event-per-day claim covers a flapping day" \
    || bad "$md repeats the one-event claim without the flap it used to break on"
done

echo "== an account that ANSWERED unparseably still clears its day stamp =="
# PR #701 review round 2, minor. The primary's answered-but-unparseable branch
# was the one rung that got a reply out of codex and told the ledger nothing,
# while the IDENTICAL second-account branch already cleared it. The stamp then
# stood for the rest of the UTC day, so the morning health line said no Codex
# account could review while codex had been replying for hours. `unusable` is a
# verdict about the CONTENT; the ledger only tracks whether the machine answered.
AGENT_SH="$SCRIPTS/pr-review-agent.sh"
UNUSABLE_BRANCH="$(awk '/^    # Codex ANSWERED and said nothing parseable/,/^  fi$/' "$AGENT_SH")"
if [ -n "$UNUSABLE_BRANCH" ]; then
  ok "extracted the primary's unparseable branch ($(printf '%s\n' "$UNUSABLE_BRANCH" | wc -l | tr -d ' ') lines)"
  has "it clears the primary account's day stamp" "$UNUSABLE_BRANCH" 'reviewer_note_codex_ok "$REVIEWER_PRIMARY_ACCOUNT"'
  has "and it records codex as the engine that answered" "$UNUSABLE_BRANCH" 'RESOLVED_ENGINE="codex"'
else
  bad "could not extract the unparseable branch -- the anchors moved, so the two cases below would be vacuous"
fi
eq "both codex-answered paths on the primary clear it, not just the healthy one" \
  "$(grep -c 'reviewer_note_codex_ok "\$REVIEWER_PRIMARY_ACCOUNT"' "$AGENT_SH")" "2"

echo "== the report names which Codex account answered =="
# The record's `account` key had no reader, which the round-2 review called out:
# a field a machine reads and no human surface shows is half a fix. The second
# account is NOT degraded, so the DEGRADED marker correctly never fires for it,
# and nothing else on the PR distinguished it from the primary.
DESC_BLOCK="$WORK/desc-block.sh"
awk '/^  desc="\$\{verdict:-unstated: no verdict parsed from the review\}"$/,/^  desc="\$\(printf/' \
  "$AGENT_SH" > "$DESC_BLOCK"
# NEGATIVE SELF-TEST ON THE EXTRACTION FIRST. An awk range that matches nothing
# makes every assertion below pass vacuously.
if grep -q 'RESOLVED_ACCOUNT' "$DESC_BLOCK" && grep -q 'DEGRADED' "$DESC_BLOCK"; then
  ok "extracted the shipped status-description block"
else
  bad "the status-description anchors moved; the cases below would be vacuous"
fi
desc_for() {  # desc_for <degraded> <resolved-account>
  ( set +u
    verdict="APPROVE"; DEGRADED="$1"; RESOLVED_ACCOUNT="$2"
    REVIEWER_PRIMARY_ACCOUNT="primary"; REVIEW_BASE=""; sha="deadbeef"
    . "$DESC_BLOCK"; printf '%s' "$desc" )
}
has   "a second-account review names the account in the required check" "$(desc_for 0 codex-ktlyst)" "codex[codex-ktlyst]"
hasnt "a primary-account review reads exactly as before"                "$(desc_for 0 primary)"      "codex["
hasnt "and so does the Opus stand-in"                                   "$(desc_for 1 -)"            "codex["
has   "the Opus stand-in still says DEGRADED out loud"                  "$(desc_for 1 -)"            "DEGRADED"

echo "== only a MACHINE REFUSAL is an outage; a timeout is not =="
# PR #701 review round 3, MAJOR. pr-review-agent.sh recorded an outage on ANY
# non-zero codex exit, with no `codex_env_reason` guard -- where linear-worker.sh
# had asked that question since ASK-3988. So one reviewer timeout stamped
# `outage_day` on the primary account and the next morning's health run filed the
# PERMANENT "the reviewer is down to Opus" issue over a single slow review.
#
# THE DECISION IS NOW ONE FUNCTION IN THE RESOLVER, not a condition repeated at
# four call sites. That is the same reason the chain, the stamps and the codex
# exec construction live here: a second place that decides "is this the machine
# refusing" is a second place for the two readers to disagree, which is exactly
# what this finding was.
# shellcheck source=/dev/null
. "$SCRIPTS/env-failure-lib.sh"
ENV_REFUSAL='You have hit your usage limit'
TIMEOUT_TAIL='timeout: the codex reviewer exceeded 1800s and was killed'
# Guard the fixtures themselves: if env-failure-lib stops reading these the way
# production does, every case below proves nothing about the real decision.
is_environmental "$ENV_REFUSAL"  && ok "fixture check: the refusal line reads as the machine refusing" \
                                 || bad "fixture check: '$ENV_REFUSAL' no longer reads as environmental"
is_environmental "$TIMEOUT_TAIL" && bad "fixture check: a timeout tail must NOT read as environmental" \
                                 || ok "fixture check: the timeout tail is not a machine refusal"

RESULT_EV="$(reviewer_outage_events_path)"
RESULT_ST="$(reviewer_outage_state_path)"
_acct_key() {  # _acct_key <account> <key> -> the state value, or <none>
  python3 - "$RESULT_ST" "$1" "$2" <<'PY'
import json, sys
try:
    state = json.load(open(sys.argv[1]))
except Exception:
    state = {}
print((state.get(sys.argv[2]) or {}).get(sys.argv[3], "<none>"))
PY
}
# `|| true`, not `|| echo 0`: grep -c already PRINTS 0 when it matches nothing and
# then exits 1, so the fallback printed a second line and every count read "0\n0".
_ev_count() { { grep -c "\"account\": *\"$1\"" "$RESULT_EV" 2>/dev/null || true; } | head -1; }

reviewer_note_codex_result timeout-acct 124 "$TIMEOUT_TAIL"
eq "a timeout writes NO outage event"          "$(_ev_count timeout-acct)" "0"
eq "and stamps no outage day on the account"   "$(_acct_key timeout-acct outage_day)" "<none>"
# ...and it does not claim the account ANSWERED either. `last_ok` is what the
# detector reads to decide a second account is still a live second opinion, so
# stamping it on a crash would flip the headline from "down to Opus" to "still
# answering" for an account that answered nothing. That is the same false-claim
# class as the finding, in the opposite direction, and linear-worker.sh:3592 made
# exactly that call before this round: `codex_env_reason` false meant `ok`, even
# on a non-zero exit.
eq "nor does it claim the account answered"    "$(_acct_key timeout-acct last_ok)" "<none>"

reviewer_note_codex_result refusal-acct 1 "$ENV_REFUSAL"
eq "a real machine refusal DOES write one event" "$(_ev_count refusal-acct)" "1"
eq "with the bucketed code, never the line"      \
  "$(python3 -c 'import json,sys
rows=[json.loads(l) for l in open(sys.argv[1]) if l.strip()]
print([r["reason_code"] for r in rows if r.get("account")==sys.argv[2]][0])' "$RESULT_EV" refusal-acct)" \
  "usage-limit"
eq "and the account is stamped down today"       \
  "$(_acct_key refusal-acct outage_day)" "$(date -u +%Y-%m-%d)"

reviewer_note_codex_result ok-acct 0 "a perfectly ordinary review"
eq "rc=0 clears the account"                   "$(_acct_key ok-acct outage_day)" "<none>"
has "and records that it answered"             "$(_acct_key ok-acct last_ok)" "$(date -u +%Y-%m-%d)"
eq "a success writes no event"                 "$(_ev_count ok-acct)" "0"

# CANNOT TELL ERRS TOWARD REPORTING, NEVER TOWARD SILENCE. env-failure-lib owns
# the refusal vocabulary; a caller that forgot to source it must not turn every
# outage into nothing. Without the classifier a non-zero exit is still an
# outage, bucketed `unclassified`.
( unset -f codex_env_reason codex_env_marker is_environmental 2>/dev/null || true
  reviewer_note_codex_result no-lib-acct 1 "$ENV_REFUSAL" )
eq "with no classifier available the outage is still recorded" "$(_ev_count no-lib-acct)" "1"
eq "bucketed unclassified rather than dropped" \
  "$(python3 -c 'import json,sys
rows=[json.loads(l) for l in open(sys.argv[1]) if l.strip()]
print([r["reason_code"] for r in rows if r.get("account")==sys.argv[2]][0])' "$RESULT_EV" no-lib-acct)" \
  "unclassified"

echo "== every shell call site routes through that ONE decision =="
# The engine above is executed; this is the wiring half. A guard the resolver
# owns and a call site bypasses is the four-implementations defect returning.
_call_count() { { grep -c "^[^#]*$2" "$SCRIPTS/$1" 2>/dev/null || true; } | head -1; }
for f in pr-review-agent.sh linear-worker.sh; do
  eq "$f calls no bare reviewer_note_codex_outage" \
    "$(_call_count "$f" reviewer_note_codex_outage)" "0"
  grep -q 'reviewer_note_codex_result' "$SCRIPTS/$f" \
    && ok "$f routes its codex outcome through reviewer_note_codex_result" \
    || bad "$f does not call reviewer_note_codex_result"
done
# NOT A COUNT OF THE `ok` CALLS. pr-review-agent.sh has four and all four are
# legitimate: each sits inside an `if run_engine codex ...; then` branch, where
# codex exited 0 and only the CONTENT may be in question. A count pins a number
# the next correct call site changes, which is the mistake round 2 made here.
# The property that can actually fail: on a FAILED codex exit, the first health
# note the script reaches is the resolver's one decision, never a bare ok or a
# bare outage. Both failure branches are anchored on the `rc=$?` that opens them.
# The anchor is compared as a WHOLE LINE, not as a regex: `rc=$?` is three
# regex metacharacters in a row and the first draft of this case went red on its
# own escaping rather than on the code.
_first_note_after() {  # _first_note_after <exact-anchor-line>
  awk -v a="$1" '
    $0 == a { on = 1 }
    on && /reviewer_note_codex_[a-z]+/ {
      match($0, /reviewer_note_codex_[a-z]+/)
      print substr($0, RSTART, RLENGTH); exit
    }' "$SCRIPTS/pr-review-agent.sh"
}
_anchor_count() {  # _anchor_count <exact-anchor-line>
  awk -v a="$1" '$0 == a { n++ } END { print n + 0 }' "$SCRIPTS/pr-review-agent.sh"
}
# NEGATIVE SELF-TEST ON BOTH ANCHORS FIRST. An anchor that matches nothing makes
# _first_note_after print nothing, which `eq` would catch -- but an anchor that
# matched the WRONG line could still print the right token by luck.
# `  rc=$?` is NOT the anchor for the primary: it opens the claude engine's
# failure branch too, and that earlier match walked forward into the codex
# SUCCESS branch and read its (correct) `ok` call. Found by this case going red
# for the wrong reason. The codex-down block's own opening comment is unique.
PRIMARY_DOWN='  # Codex is DOWN. If nothing filled $STATUS_CONTEXT and it were a required'
eq "anchor check: the codex-down block opens once"  "$(_anchor_count "$PRIMARY_DOWN")" "1"
eq "anchor check: the second account's branch too"  "$(_anchor_count '      src=$?')" "1"
eq "after a failed codex exit on the primary, the one decision runs" \
  "$(_first_note_after "$PRIMARY_DOWN")" "reviewer_note_codex_result"
eq "and the same after a failed exit on the second account" \
  "$(_first_note_after '      src=$?')" "reviewer_note_codex_result"

echo "== the detector, end to end, over a ledger a timeout wrote =="
# The producer/consumer pair again, on the finding's own scenario: the shipped
# resolver writes, the shipped detector reads, in a ledger of their own.
TO_DIR="$WORK/timeout-pair"
mkdir -p "$TO_DIR"
TO_OUT="$(
  KIPI_STATE_DIR="$TO_DIR" bash -c '
    . "'"$SCRIPTS"'/env-failure-lib.sh"
    . "'"$SCRIPTS"'/reviewer-resolve.sh"
    reviewer_note_codex_result primary 124 "timeout: the codex reviewer exceeded 1800s and was killed"
    KIPI_NOTIFY=/usr/bin/true python3 - "'"$SCRIPTS"'/fleet-health-daily.py" <<PY
import importlib.util, sys
spec = importlib.util.spec_from_file_location("fh", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print("after-timeout", len(m.detect_codex_outage(None)))
PY
    reviewer_note_codex_result primary 1 "You have hit your usage limit"
    KIPI_NOTIFY=/usr/bin/true python3 - "'"$SCRIPTS"'/fleet-health-daily.py" <<PY
import importlib.util, sys
spec = importlib.util.spec_from_file_location("fh", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print("after-refusal", len(m.detect_codex_outage(None)))
PY
' 2>/dev/null)"
has "one reviewer timeout files NO health finding" "$TO_OUT" "after-timeout 0"
has "a real refusal files exactly one"             "$TO_OUT" "after-refusal 1"

echo "== a number in the reason is not a 529 =="
# PR #701 review round 3, minor. The bucket matched a bare `529` anywhere in the
# text, and both live callers put an identifier in that text: the worker passes
# "$ISSUE: <marker>" and the agent passed "exit $rc on PR #$PR". So ASK-529 and
# PR #529 reported the provider as OVERLOADED -- a transient server-side
# condition an operator waits out -- when the run had actually crashed.
# The real marker is `API Error: 529 Overloaded`, which `*overloaded*` already
# catches, so the bare-number arm bought nothing and cost a wrong bucket.
eq "an issue id that happens to contain 529"  "$(reviewer_outage_code 'ASK-529: exit 1')"       "exec-failure"
eq "a PR number that happens to contain 529"  "$(reviewer_outage_code 'exit 2 on PR #529')"     "exec-failure"
eq "the real overload marker still buckets"   "$(reviewer_outage_code 'API Error: 529 Overloaded.')" "overloaded"
eq "including with its full real tail"        \
  "$(reviewer_outage_code 'API Error: 529 Overloaded. This is a server-side issue, usually temporary')" \
  "overloaded"
eq "and a bare 529 with no overload word is not a provider outage" \
  "$(reviewer_outage_code 'ASK-529')" "unclassified"

echo "== ONE event per account per UTC day, flap included =="
# PR #701 review round 3, minor. The header, both prose call sites and the
# writer's own docstring all promise at most ONE event per account per UTC day.
# They were wrong on a flapping day: `reviewer_note_codex_ok` popped `outage_day`,
# which was ALSO the append key, so fail/recover/fail appended a second row and
# the health body carried the same account twice with two different "first seen"
# times. The two questions are different and now have different keys:
#   outage_day  is this account down RIGHT NOW (popped by a recovery)
#   event_day   has today's one event already been filed (never popped)
FLAP="$WORK/flap"
mkdir -p "$FLAP"
FLAP_OUT="$(
  KIPI_STATE_DIR="$FLAP" bash -c '
    . "'"$SCRIPTS"'/env-failure-lib.sh"
    . "'"$SCRIPTS"'/reviewer-resolve.sh"
    reviewer_note_codex_outage primary usage-limit
    reviewer_note_codex_ok primary
    reviewer_note_codex_outage primary out-of-credits
    echo "events $(wc -l < "$(reviewer_outage_events_path)" | tr -d " ")"
    KIPI_NOTIFY=/usr/bin/true python3 - "'"$SCRIPTS"'/fleet-health-daily.py" <<PY
import importlib.util, sys
spec = importlib.util.spec_from_file_location("fh", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
f = m.detect_codex_outage(None)
print("findings", len(f))
print(f[0]["body"] if f else "<none>")
PY
' 2>/dev/null)"
has "a fail/recover/fail day appends ONE row, as the header promises" "$FLAP_OUT" "events 1"
# AND THE QUIET IS NOT BOUGHT WITH SILENCE. The account is down again, so the
# detector must still report it -- suppressing the ROW must not suppress the
# FINDING. This is the half that makes the change safe.
has "the account that is down again is STILL reported"               "$FLAP_OUT" "findings 1"
# The row is the FIRST failure of the day; the live reason is the state's. Taking
# the reason from the stale row would have reported `usage-limit` while the
# account was actually out of credits.
has "and the body carries the CURRENT reason, not the first one"     "$FLAP_OUT" "out-of-credits"
hasnt "the superseded reason is not listed as if it were live"       "$FLAP_OUT" '`usage-limit`'

echo "== the agent REFUSES BY NAME when the resolver is absent =="
# FOUND BY CI, NOT BY A REVIEWER (PR #701, the validate check). ASK-3831 gave
# pr-review-agent.sh a fifth sourced lib. A bare `.` on a missing file prints one
# line and CONTINUES, so two harnesses that copy the lib set by hand kept running
# an agent with no resolver: one reached the dispatch and died on
# `REVIEWER_PRIMARY_ACCOUNT: unbound variable`, the other failed later for an
# unrelated reason. Both failed CLOSED, which is the only reason this was a
# legibility defect and not a green-on-nothing one. The real-world shape is a
# partial install or an rsync filter.
#
# The harness derives the lib set the way the two tests now do, and omits exactly
# one file, so this case cannot pass by failing to build the skeleton.
MISSING_SKEL="$WORK/missing-resolver"
mkdir -p "$MISSING_SKEL/q-system/.q-system/scripts"
git init -q "$MISSING_SKEL"
_agent_libs() { awk -F'"' '/^\. "\$SCRIPT_DIR\//{ sub(/\$SCRIPT_DIR\//,"",$2); print $2 }' \
                  "$SCRIPTS/pr-review-agent.sh"; }
has "the agent sources the resolver at all" "$(_agent_libs | tr '\n' ' ')" "reviewer-resolve.sh"
_build_skel() {  # _build_skel <skip-lib-or-empty>
  rm -rf "$MISSING_SKEL/q-system/.q-system/scripts"
  mkdir -p "$MISSING_SKEL/q-system/.q-system/scripts"
  cp "$SCRIPTS/pr-review-agent.sh" "$MISSING_SKEL/q-system/.q-system/scripts/"
  local lib
  for lib in $(_agent_libs); do
    [ -n "$1" ] && [ "$lib" = "$1" ] && continue
    [ -f "$SCRIPTS/$lib" ] && cp "$SCRIPTS/$lib" "$MISSING_SKEL/q-system/.q-system/scripts/"
  done
  cp "$SCRIPTS/model_route.py" "$MISSING_SKEL/q-system/.q-system/scripts/" 2>/dev/null || true
  echo code > "$MISSING_SKEL/FILE.txt"
  git -C "$MISSING_SKEL" -c user.email=t@t.t -c user.name=t add -A >/dev/null 2>&1
  git -C "$MISSING_SKEL" -c user.email=t@t.t -c user.name=t commit -q -m c >/dev/null 2>&1 || true
}
_build_skel reviewer-resolve.sh
MISSING_OUT="$(cd "$MISSING_SKEL" && HOME="$MISSING_SKEL/home" \
                 bash "$MISSING_SKEL/q-system/.q-system/scripts/pr-review-agent.sh" 1 2>&1)"
MISSING_RC=$?
eq "a run with no resolver exits non-zero" "$([ "$MISSING_RC" -ne 0 ] && echo yes || echo no)" "yes"
has "and the refusal NAMES the missing file" "$MISSING_OUT" "reviewer-resolve.sh is missing"
hasnt "it never announces a review it cannot run" "$MISSING_OUT" "reviewer (bounded at"
hasnt "and it does not die on an unbound variable instead" "$MISSING_OUT" "unbound variable"
# CONTROL: the same harness WITH the resolver gets past that line, so the three
# assertions above are about the missing file and not about a broken skeleton.
_build_skel ""
PRESENT_OUT="$(cd "$MISSING_SKEL" && HOME="$MISSING_SKEL/home" \
                 bash "$MISSING_SKEL/q-system/.q-system/scripts/pr-review-agent.sh" 1 2>&1)"
hasnt "control: with the resolver present the refusal does not fire" \
  "$PRESENT_OUT" "reviewer-resolve.sh is missing"

echo
echo "pass=$PASS fail=$FAIL"
[ "$FAIL" -eq 0 ]
