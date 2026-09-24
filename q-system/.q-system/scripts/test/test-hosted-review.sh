#!/usr/bin/env bash
# Reproducer for ASK-318 failure mode 2: no verdict producer runs when the
# dispatcher Mac is off.
#
# The captured case (2026-09-23): .github/workflows/ held only reviewer-floor.yml,
# validate.yml and verify.yml, and `gh secret list` returned nothing. So a PR
# opened while com.kipi.dispatch was not running got the floor's red and nothing
# else, ever. This suite pins:
#   A. a pull_request workflow exists that runs the reviewer gate from the BASE
#      checkout (the floor's trust pattern), and cannot mint a success itself;
#   B. the gate with no credential runs nothing, posts nothing, exits 0;
#   C. the gate with a credential execs the SAME reviewer, <pr> --post;
#   D. a malformed PR argument is refused and runs nothing.
# The model and gh are never called: the agent is a stub that logs its argv.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
WF="$ROOT/.github/workflows/reviewer-hosted.yml"
GATE="${HOSTED_REVIEW_GATE:-$ROOT/q-system/.q-system/scripts/hosted-review-gate.sh}"

PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
bad()  { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
has()  { case "$2" in *"$1"*) return 0 ;; esac; return 1; }

echo "A. the workflow"
if [ ! -s "$WF" ]; then
  bad "THE DEFECT: no hosted reviewer workflow at .github/workflows/reviewer-hosted.yml, so a PR opened while the dispatcher Mac is off never gets a verdict"
else
  W="$(cat "$WF")"
  has "pull_request:" "$W" && ok "triggers on pull_request" || bad "does not trigger on pull_request"
  has 'ref: ${{ github.event.pull_request.base.sha }}' "$W" \
    && ok "checks out the BASE sha, so the PR cannot edit the code that holds the secret" \
    || bad "does not check out base.sha: a PR could edit the reviewer that runs with the secret"
  has "persist-credentials: false" "$W" && ok "checkout keeps no credentials" || bad "checkout persists credentials"
  has 'hosted-review-gate.sh "${{ github.event.pull_request.number }}"' "$W" \
    && ok "runs the gate on the PR number" || bad "does not run hosted-review-gate.sh on the PR number"
  has "state=success" "$W" && bad "the workflow itself writes state=success" || ok "the workflow never writes state=success itself"
fi

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
STUB="$WORK/agent.sh"; LOG="$WORK/agent.log"
printf '#!/usr/bin/env bash\necho "$*" >> "%s"\n' "$LOG" > "$STUB"; chmod +x "$STUB"

run_gate() {  # run_gate <out> <pr> [VAR=value ...]
  local out="$1" pr="$2"; shift 2
  : > "$LOG"
  env -u ANTHROPIC_API_KEY -u CLAUDE_CODE_OAUTH_TOKEN HOSTED_REVIEW_AGENT="$STUB" "$@" \
    bash "$GATE" "$pr" > "$out" 2>&1
}

echo "B. no credential"
run_gate "$WORK/b.out" 431; RC=$?
[ "$RC" = 0 ] && ok "exits 0 (the floor's red holds the PR)" || bad "exited $RC with no credential"
[ ! -s "$LOG" ] && ok "runs no reviewer" || bad "ran the reviewer with no credential: $(cat "$LOG")"
grep -c 'HOSTED REVIEWER OFF' "$WORK/b.out" >/dev/null && ok "says it is off, in the job log" || bad "silent when off"

echo "C. a credential"
run_gate "$WORK/c.out" 431 ANTHROPIC_API_KEY=k-test; RC=$?
[ "$RC" = 0 ] && ok "exits with the reviewer's status" || bad "exited $RC with a credential"
[ "$(cat "$LOG")" = "431 --post" ] && ok "execs the same reviewer: 431 --post" || bad "reviewer argv was '$(cat "$LOG")', want '431 --post'"
run_gate "$WORK/c2.out" 431 CLAUDE_CODE_OAUTH_TOKEN=t-test
[ "$(cat "$LOG")" = "431 --post" ] && ok "an OAuth token counts as a credential too" || bad "OAuth token did not run the reviewer"

echo "D. malformed PR"
run_gate "$WORK/d.out" '431;x' ANTHROPIC_API_KEY=k-test; RC=$?
[ "$RC" = 2 ] && [ ! -s "$LOG" ] && ok "refused, nothing run" || bad "malformed PR: rc=$RC, ran '$(cat "$LOG")'"

echo
echo "passed $PASS, failed $FAIL"
[ "$PASS" -gt 0 ] && [ "$FAIL" = 0 ]
