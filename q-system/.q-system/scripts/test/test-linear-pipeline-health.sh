#!/usr/bin/env bash
# Reproducer + acceptance criteria for the Linear pipeline pager (ASK-223).
#
# THE DEFECT IT CLOSES, in two halves:
#   1. Every existing pager says WHAT broke and never WHAT TO DO. "converge
#      ASK-208: hit 3-round cap, still REQUEST CHANGES" wakes the founder at 3am
#      and leaves them to work out the rest.
#   2. Every existing pager lives INSIDE the thing that fails, so a dead process
#      reaches nobody. linear-triage.py --apply died on a Linear TimeoutError
#      after closing 32 issues and paged zero times (sp-b5dcf944).
#
# THE RISK IN A PAGER is not the miss, it is the noise: too many pages and the
# channel gets muted, which silently removes every alert including the real ones.
# So the cases that matter most here are the SILENT ones (case 2) and the dedupe
# (case 4), not the detections.
#
# Isolation: KIPI_STATE_DIR, KIPI_NOTIFY and KIPI_PIPELINE_OBSERVATIONS all point
# into a mktemp dir. Never calls gh, never queries Linear, never pages Slack.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
HEALTH="$ROOT/q-system/.q-system/scripts/linear-pipeline-health.py"
CONVERGE="$ROOT/q-system/.q-system/scripts/converge.sh"
WORKER="$ROOT/q-system/.q-system/scripts/linear-worker.sh"
TRIAGE="$ROOT/q-system/.q-system/scripts/linear-triage.py"
INSTALLER="$ROOT/q-system/.q-system/scripts/install-plist.sh"
PLIST="$ROOT/q-system/.q-system/scripts/com.kipi.linear-pipeline-health.plist"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$HEALTH" ] || fail "linear-pipeline-health.py does not exist at $HEALTH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/state"

# --- fake notifier: one line per page, so a page COUNT is assertable ----------
cat > "$WORK/notify.sh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "${1:-}" >> "$FAKE_PAGES"
exit 0
EOF
chmod +x "$WORK/notify.sh"

export KIPI_STATE_DIR="$WORK/state"
export KIPI_NOTIFY="$WORK/notify.sh"
export FAKE_PAGES="$WORK/pages.txt"
export KIPI_PIPELINE_OBSERVATIONS="$WORK/obs.json"

# observe <json-array> -> runs one watcher cycle against that fixture
observe() {
  printf '%s' "$1" > "$WORK/obs.json"
  set +e
  python3 "$HEALTH" > "$WORK/out" 2>&1
  RC=$?
  set -e
}
reset_pages() { : > "$FAKE_PAGES"; }
reset_all()   { reset_pages; rm -f "$WORK/state/linear-pipeline-health-state.json"; }
page_count()  { wc -l < "$FAKE_PAGES" | tr -d ' '; }

# =============================================================================
# CHECK 1 (RED first): a PR green and unmerged past the threshold pages exactly
# once, and the page carries the arm command.
# =============================================================================
reset_all
observe '[{"state":"green_not_merged","subject":"PR #41","facts":{"pr":41,"minutes":45}}]'
[ "$RC" = "0" ] || fail "watcher must exit 0, got $RC: $(cat "$WORK/out")"
[ "$(page_count)" = "1" ] || fail "green-stall must page exactly once, got $(page_count)"
grep -q 'gh pr merge --auto --squash 41' "$FAKE_PAGES" \
  || fail "the page must carry the arm command: $(cat "$FAKE_PAGES")"
grep -q 'has not merged for 45 min' "$FAKE_PAGES" \
  || fail "the page must carry the diagnosis: $(cat "$FAKE_PAGES")"
ok "green + unmerged >20min pages once, with the arm command"

# =============================================================================
# CHECK 2: every 'broken? no' row pages ZERO times. This is the case that keeps
# the channel worth reading; assert on the count, not on the text.
# =============================================================================
for st in request_changes awaiting_review skipped_no_dor; do
  reset_all
  observe "[{\"state\":\"$st\",\"subject\":\"PR #7\",\"facts\":{}}]"
  [ "$(page_count)" = "0" ] || fail "$st must page 0 times, got $(page_count): $(cat "$FAKE_PAGES")"
  grep -q "SILENT: PR #7 \[$st\]" "$WORK/out" \
    || fail "$st must still be LOGGED even though it is silent: $(cat "$WORK/out")"
done
ok "REQUEST CHANGES / awaiting review / skipped-no-DoR page 0 times and are logged"

# An UNKNOWN state is borderline, and borderline goes silent.
reset_all
observe '[{"state":"some_state_nobody_classified","subject":"PR #9","facts":{}}]'
[ "$(page_count)" = "0" ] || fail "an unclassified state must stay silent, got $(page_count)"
grep -q 'unclassified pipeline state' "$WORK/out" || fail "unknown state must be logged"
ok "an unclassified state stays silent and is logged"

# =============================================================================
# CHECK 3: every 'broken? yes' row pages exactly once, carrying a diagnosis AND
# an action. `Do:` is the literal contract every page in this fleet honours.
# =============================================================================
BROKEN_FIXTURES='
round_cap|{"issue":"ASK-208","pr":41,"rounds":3,"verdict":"REQUEST CHANGES"}
no_verdict|{"issue":"ASK-208","pr":41}
worker_infra|{"issue":"ASK-208","detail":"gh auth failed"}
green_not_merged|{"pr":41,"minutes":45}
unreviewed_head|{"pr":41,"issue":"ASK-208","reviewed_sha":"bf641ad","head_sha":"c063c3d"}
stranded_issue|{"issue":"ASK-208","hours":6}
dead_converge|{"issue":"ASK-208","line":"round 1/4 dispatching Sana"}
main_red|{"workflow":"validate","run_id":123}
'
while IFS='|' read -r st facts; do
  [ -n "$st" ] || continue
  reset_all
  observe "[{\"state\":\"$st\",\"subject\":\"ASK-208\",\"facts\":$facts}]"
  [ "$(page_count)" = "1" ] || fail "$st must page exactly once, got $(page_count)"
  grep -q 'Do: ' "$FAKE_PAGES" || fail "$st page carries no action: $(cat "$FAKE_PAGES")"
  # A diagnosis is the text BEFORE `Do:`, and it has to be more than the label.
  DIAG="$(sed 's/ Do: .*//' "$FAKE_PAGES")"
  [ "${#DIAG}" -gt 40 ] || fail "$st page carries no real diagnosis: $DIAG"
  # An action has to be more than "needs a human".
  ACT="$(sed 's/.* Do: //' "$FAKE_PAGES")"
  [ "${#ACT}" -gt 10 ] || fail "$st page action is not actionable: $ACT"
  case "$ACT" in *"{"*) fail "$st page leaked an unrendered field: $ACT" ;; esac
done <<< "$BROKEN_FIXTURES"
ok "all 8 broken states page once, each with a rendered diagnosis and an action"

# A broken state whose facts are incomplete still pages, and says so rather than
# rendering a template placeholder at the founder.
reset_all
observe '[{"state":"round_cap","subject":"ASK-208","facts":{}}]'
[ "$(page_count)" = "1" ] || fail "incomplete facts must still page, got $(page_count)"
grep -q 'detail fields are incomplete' "$FAKE_PAGES" || fail "incomplete facts must be named"
case "$(cat "$FAKE_PAGES")" in *"{pr}"*) fail "unrendered template reached the page" ;; esac
ok "a broken state with missing facts pages honestly instead of leaking a template"

# =============================================================================
# CHECK 4: THE SAME broken state on three consecutive runs pages ONCE. On a
# 10-minute watcher, the level-triggered version is 144 pages a day.
# =============================================================================
reset_all
OBS='[{"state":"green_not_merged","subject":"PR #41","facts":{"pr":41,"minutes":45}}]'
observe "$OBS"; observe "$OBS"; observe "$OBS"
[ "$(page_count)" = "1" ] || fail "3 identical runs must page once, got $(page_count)"
ok "the same broken state on 3 consecutive runs pages once, not three times"

# =============================================================================
# CHECK 5: clearing and re-breaking pages AGAIN. Dedupe must suppress the level,
# never the transition.
# =============================================================================
observe '[]'
observe "$OBS"
[ "$(page_count)" = "2" ] || fail "a cleared-then-rebroken state must page again, got $(page_count)"
ok "state clears then re-breaks -> pages again (transition, not level)"

# A DIFFERENT subject in the same state is its own breakage, not a duplicate.
reset_all
observe '[{"state":"green_not_merged","subject":"PR #41","facts":{"pr":41,"minutes":45}},
          {"state":"green_not_merged","subject":"PR #42","facts":{"pr":42,"minutes":99}}]'
[ "$(page_count)" = "2" ] || fail "two PRs stalled = two pages, got $(page_count)"
ok "the same state on two different subjects pages twice"

# =============================================================================
# CHECK 6: a converge log ending at `dispatching` with no live process is a dead
# agent. Drives the pure detector, so no process is ever spawned.
# =============================================================================
DEAD="$(python3 - "$HEALTH" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("h", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
log = "\n".join([
    "2026-07-28T01:00:00Z converge[ASK-208] round 1/4 dispatching Sana",
    "2026-07-28T01:00:00Z converge[ASK-209] round 1/4 dispatching Sana",
    "2026-07-28T01:05:00Z converge[ASK-209] round 1 -> APPROVE (head abc); reworking",
    "2026-07-28T01:06:00Z converge[ASK-210] round 1/4 dispatching Sana",
])
# ASK-210 has a live converge; ASK-209 got past its dispatch; only ASK-208 died.
print(json.dumps(m.dead_converge_findings(log, {"ASK-210"})))
PY
)"
echo "$DEAD" | grep -q '"subject": "ASK-208"' \
  || fail "a log ending at 'dispatching' with no process must be a dead agent: $DEAD"
echo "$DEAD" | grep -q 'ASK-209' && fail "an issue that logged past its dispatch is not dead: $DEAD"
echo "$DEAD" | grep -q 'ASK-210' && fail "an issue with a live converge is not dead: $DEAD"
ok "converge log ending at 'dispatching' with no live process -> dead agent (and only that one)"

# =============================================================================
# CHECK 7: a missing notifier must not break the watcher. A broken pager taking
# down the pipeline it watches is worse than the silence it was built to fix.
# =============================================================================
reset_all
KIPI_NOTIFY="$WORK/does-not-exist.sh" observe "$OBS"
[ "$RC" = "0" ] || fail "a missing notifier must still exit 0, got $RC"
grep -q 'BROKEN: pipeline' "$WORK/out" || fail "a missing notifier must still LOG the finding"
grep -q 'notify script missing' "$WORK/out" || fail "the missing notifier must be named in the log"
ok "slack-notify.sh unavailable -> watcher exits 0 and logs the finding anyway"

# --dry writes no state and sends no page, so a hand-run preview is read-only.
reset_all
printf '%s' "$OBS" > "$WORK/obs.json"
python3 "$HEALTH" --dry > "$WORK/out" 2>&1
[ "$(page_count)" = "0" ] || fail "--dry must not page"
[ ! -f "$WORK/state/linear-pipeline-health-state.json" ] || fail "--dry must not write state"
grep -q '\[dry\] would page 1' "$WORK/out" || fail "--dry must report the real number: $(cat "$WORK/out")"
python3 "$HEALTH" --bogus > "$WORK/out" 2>&1
grep -q 'refusing to run' "$WORK/out" || fail "an unrecognized flag must refuse, not run live"
ok "--dry is read-only and reports the real number; an unknown flag refuses"

# =============================================================================
# GAP 1 CONTRACT: every page the in-process pagers emit carries an action too.
# This is a lint over the real scripts, not a mock -- the nine existing messages
# in converge.sh and linear-worker.sh are exactly what wakes the founder, and a
# regression there is invisible to every test above.
# =============================================================================
for script in "$CONVERGE" "$WORKER"; do
  [ -f "$script" ] || fail "missing $script"
  MISSING=0
  FOUND=0
  while IFS= read -r line; do
    # `grep -n` prefixes NNN:, so a comment test has to strip that first -- the
    # naive `grep -v '^#'` matched nothing and let a prose line about $NOTIFY
    # count as an unactioned page.
    body="${line#*:}"
    case "${body#"${body%%[![:space:]]*}"}" in "#"*) continue ;; esac
    FOUND=$((FOUND + 1))
    case "$line" in *"Do: "*) ;; *) echo "  no action: $line" >&2; MISSING=$((MISSING + 1)) ;; esac
  done < <(grep -n 'bash "\$NOTIFY"' "$script")
  # A lint that finds nothing to lint passes for the wrong reason. If the pages
  # are ever renamed out from under this grep, that is a RED, not a green.
  [ "$FOUND" -gt 0 ] || fail "$(basename "$script") has no \$NOTIFY pages -- the lint matched nothing"
  [ "$MISSING" = "0" ] \
    || fail "$(basename "$script") has $MISSING page(s) with no 'Do: ' action"
done
ok "every page in converge.sh and linear-worker.sh carries a 'Do: ' action"

# =============================================================================
# CHECK 8 (review round 3, MAJOR 1): a DRAFT PR is never a green-stall.
#
# A draft with a green rollup is a PR the founder parked on purpose. GitHub
# REFUSES `gh pr merge --auto` on a draft, so paging it is both a wrong
# diagnosis and an unrunnable action. This repo's PR #4 has been exactly that
# since 2026-07-01 -- on the first live cycle it was the ONLY thing the watcher
# would have said, four times a day, forever.
#
# Two halves, and the second is the one that matters: the pure detector must
# skip drafts, AND the live query must actually ASK for isDraft. A detector
# reading a field nobody requested sees None and skips nothing.
# =============================================================================
DRAFTS="$(python3 - "$HEALTH" <<'PY'
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("h", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
now = time.time()
old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 6 * 3600))
green = [{"conclusion": "SUCCESS"}]
prs = [
    {"number": 4, "updatedAt": old, "statusCheckRollup": green,
     "autoMergeRequest": None, "isDraft": True},
    {"number": 41, "updatedAt": old, "statusCheckRollup": green,
     "autoMergeRequest": None, "isDraft": False},
]
print(json.dumps(m.green_not_merged_findings(prs, now)))
PY
)"
echo "$DRAFTS" | grep -q '"subject": "PR #41"' \
  || fail "a non-draft green PR is still a stall: $DRAFTS"
case "$DRAFTS" in
  *'"state": "green_not_merged", "subject": "PR #4"'*)
    fail "a DRAFT PR must never be reported as a green stall: $DRAFTS" ;;
esac
echo "$DRAFTS" | grep -q '"state": "green_but_draft"' \
  || fail "a skipped draft must still be OBSERVED and logged, not dropped: $DRAFTS"
ok "a draft PR is logged silently, never paged as a green stall"

# The wiring half: run the LIVE collector against a fake gh on PATH and assert
# the isDraft field is actually requested. Without this the fix above is inert.
mkdir -p "$WORK/bin"
cat > "$WORK/bin/gh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_GH_LOG"
OLD="$(python3 -c 'import time;print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()-21600)))')"
case "$1 $2" in
  "pr list")
    echo "[{\"number\":4,\"updatedAt\":\"$OLD\",\"statusCheckRollup\":[{\"conclusion\":\"SUCCESS\"}],\"autoMergeRequest\":null,\"isDraft\":true}]" ;;
  "run list") echo '[]' ;;
  *) echo '[]' ;;
esac
EOF
chmod +x "$WORK/bin/gh"
export FAKE_GH_LOG="$WORK/gh.log"
: > "$FAKE_GH_LOG"
LIVE="$(PATH="$WORK/bin:$PATH" python3 - "$HEALTH" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("h", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
# The Linear half is stubbed: the suite must never reach the network.
m.fetch_in_progress_issues = lambda: []
observations, unobserved = m.collect_live()
print(json.dumps({"obs": observations, "unobserved": sorted(unobserved)}))
PY
)"
grep -q 'isDraft' "$FAKE_GH_LOG" \
  || fail "collect_live never asks gh for isDraft, so the draft skip can never fire: $(cat "$FAKE_GH_LOG")"
case "$LIVE" in
  *'"state": "green_not_merged"'*)
    fail "the live collector still reports a draft as a green stall: $LIVE" ;;
esac
ok "the live gh query requests isDraft, so the draft skip actually fires"

# =============================================================================
# CHECK 9 (review round 3, MAJOR 2): every BROKEN state is REACHABLE.
#
# stranded_issue shipped in the classifier table, in the PR body, and in a green
# test -- with no collector anywhere that could emit it. The test passed because
# the fixture seam injects the state string directly, which proves the template
# renders, not that anything observes the world. A state nothing can observe is
# a promise, and the founder reads the promise as coverage.
# =============================================================================
REACH="$(python3 - "$HEALTH" <<'PY'
import importlib.util, json, re, sys
spec = importlib.util.spec_from_file_location("h", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
source = open(sys.argv[1]).read()
emitted = set(re.findall(r'"state":\s*"([a-z_]+)"', source))
declared = set(m.BROKEN_STATES)
in_process = set(getattr(m, "IN_PROCESS_PAGED_STATES", ()))
print(json.dumps({"unreachable": sorted(declared - emitted - in_process),
                  "emitted": sorted(emitted)}))
PY
)"
echo "$REACH" | grep -q '"unreachable": \[\]' \
  || fail "BROKEN_STATES no collector can emit (and not declared in-process-paged): $REACH"
ok "every broken state is either emitted by a collector or declared in-process-paged"

# And the stranded detector itself: In Progress, past the window, no branch and
# no PR. An issue with either one is somebody's live work, not a dead holder.
STRAND="$(python3 - "$HEALTH" <<'PY'
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("h", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
now = time.time()
def ago(hours):
    # The LINEAR shape, fractional seconds and all. The suite used to build the
    # GitHub shape here, which nothing produces for startedAt -- so it stayed
    # green while the parse rejected every real timestamp (round 4, MAJOR).
    return time.strftime("%Y-%m-%dT%H:%M:%S.412Z", time.gmtime(now - hours * 3600))
issues = [
    {"identifier": "ASK-300", "startedAt": ago(9)},   # stranded
    {"identifier": "ASK-301", "startedAt": ago(9)},   # has a PR
    {"identifier": "ASK-302", "startedAt": ago(9)},   # has a branch
    {"identifier": "ASK-303", "startedAt": ago(1)},   # still inside the window
]
print(json.dumps(m.stranded_issue_findings(
    issues, {"ASK-301"}, {"sana/ask-302"}, now)))
PY
)"
echo "$STRAND" | grep -q '"subject": "ASK-300"' || fail "a stranded issue must be found: $STRAND"
for other in ASK-301 ASK-302 ASK-303; do
  echo "$STRAND" | grep -q "$other" && fail "$other is not stranded: $STRAND"
done
ok "stranded_issue: found with no branch and no PR past the window, and only then"

# =============================================================================
# CHECK 10 (review round 3, MAJOR 3): a collector that FAILED is not a state
# that CLEARED.
#
# `_gh_json` returns None on a rate limit, a network blip, or an expired token,
# and the old code turned that into [] -- byte-identical to "main went green".
# The ledger was rebuilt from that empty set, the key vanished, and the next
# successful cycle read a transition and paged a breakage nobody had fixed. At
# 96 cycles a day one flaky call turns one real break into a stream.
# =============================================================================
reset_all
BREAK='[{"state":"main_red","subject":"main","facts":{"workflow":"validate","run_id":7}}]'
observe "$BREAK"
observe "$BREAK"
[ "$(page_count)" = "1" ] || fail "the real breakage must page once first, got $(page_count)"
# gh falls over: nothing observed, main_red explicitly UNOBSERVED (not cleared).
observe '{"observations": [], "unobserved": ["main_red"]}'
[ "$(page_count)" = "1" ] || fail "a blind cycle must not page, got $(page_count)"
grep -q 'DEGRADED' "$WORK/out" \
  || fail "a blind cycle must SAY it was blind, not print a clean zero: $(cat "$WORK/out")"
# gh recovers. main was never fixed, so this is the same breakage, not a new one.
observe "$BREAK"
[ "$(page_count)" = "1" ] \
  || fail "a transient collector failure must not re-page an unfixed breakage, got $(page_count)"
# A state that genuinely clears (observed empty, nothing unobserved) still
# re-pages when it breaks again -- the transition semantics must survive.
observe '[]'
observe "$BREAK"
[ "$(page_count)" = "2" ] || fail "a genuinely cleared-then-rebroken state must page again, got $(page_count)"
ok "a failed collector carries the ledger forward; a genuine clear still re-pages"

# A tool that is MISSING is permanent and actionable, so it pages once. That is
# not the same as a call that failed: this plist runs under launchd, whose PATH
# is /usr/bin:/bin:/usr/sbin:/sbin, and gh lives nowhere near it.
BLIND="$(python3 - "$HEALTH" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("h", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(json.dumps(m.missing_tool_findings(["gh"])))
PY
)"
echo "$BLIND" | grep -q '"state": "watcher_blind"' \
  || fail "a missing tool must be its own finding: $BLIND"
reset_all
observe '[{"state":"watcher_blind","subject":"gh","facts":{"tool":"gh"}}]'
[ "$(page_count)" = "1" ] || fail "watcher_blind must page once, got $(page_count)"
grep -q 'Do: ' "$FAKE_PAGES" || fail "watcher_blind page carries no action: $(cat "$FAKE_PAGES")"
ok "a missing tool pages once with a fix; a failing call stays silent and degraded"

# =============================================================================
# CHECK 11 (review round 3): the plist must run the watcher through a login
# shell. /usr/bin/python3 straight from launchd gets PATH=/usr/bin:/bin:... --
# no gh, no git -- so every collector returns nothing and the watcher is blind
# forever while looking perfectly healthy in `launchctl list`.
# =============================================================================
[ -f "$PLIST" ] || fail "missing $PLIST"
grep -q -- '-lc' "$PLIST" \
  || fail "the plist must exec through a login shell or launchd's PATH hides gh: $PLIST"
grep -q 'linear-pipeline-health.py' "$PLIST" || fail "the plist must run the watcher"
ok "the launchd plist runs through a login shell, so gh is on PATH"

# =============================================================================
# CHECK 12 (review round 3, MINOR 1): install-plist.sh may only claim labels it
# can actually install. It documented com.kipi.launchd-health, which has no
# template -- `install-plist.sh com.kipi.launchd-health` exits 2.
# =============================================================================
MISSING_TPL=0
while read -r label; do
  [ -n "$label" ] || continue
  if [ ! -f "$ROOT/q-system/.q-system/scripts/$label.plist" ]; then
    echo "  no template: $label" >&2
    MISSING_TPL=$((MISSING_TPL + 1))
  fi
done < <(grep -o 'com\.kipi\.[a-z][a-z-]*' "$INSTALLER" | sort -u)
[ "$MISSING_TPL" = "0" ] \
  || fail "install-plist.sh names $MISSING_TPL label(s) it has no template for"
ok "every label install-plist.sh names has a template it can render"

# =============================================================================
# CHECK 13 (review round 3, MINOR 2): the incident this whole issue opens with.
#
# linear-triage.py --apply died on a Linear TimeoutError after commenting on 74
# issues and CLOSING 32, and paged zero times (sp-b5dcf944). No collector here
# can see a triage run, so the only place that failure is observable is inside
# the process that has it. It now pages on the way down, with a Do:.
#
# The API endpoint is pointed at a closed local port: this never touches Linear.
# =============================================================================
reset_pages
set +e
KIPI_LINEAR_API_URL="http://127.0.0.1:1/graphql" \
KIPI_LINEAR_API_KEY="test-key-never-used" \
KIPI_NOTIFY="$WORK/notify.sh" \
  python3 "$TRIAGE" --project kipi-system --limit 1 > "$WORK/out" 2>&1
TRC=$?
set -e
[ "$TRC" != "0" ] || fail "a triage run against a dead endpoint must not exit 0"
[ "$(page_count)" = "1" ] \
  || fail "linear-triage.py crashing must page exactly once, got $(page_count): $(cat "$WORK/out")"
grep -q 'Do: ' "$FAKE_PAGES" || fail "the triage crash page carries no action: $(cat "$FAKE_PAGES")"
grep -q 'linear-triage' "$FAKE_PAGES" || fail "the triage crash page must name the job"
ok "linear-triage.py crashing mid-run pages once, naming the job and the next command"

# =============================================================================
# CHECK 14 (review round 4, MAJOR): the timestamp shape Linear actually emits.
#
# `_minutes_since` parsed with %Y-%m-%dT%H:%M:%S%Z, which rejects Linear's
# fractional seconds (`2026-07-27T19:50:40.412Z`). stranded_issue_findings skips
# any issue it cannot date -- by design, so unknown age never renders as old --
# so the detector was reachable, wired, and structurally unable to fire. Its
# output ("0 findings, no DEGRADED line") is byte-identical to a healthy
# pipeline, so nothing downstream could tell the two apart.
#
# Both producer shapes are pinned here: GitHub's updatedAt has no fraction and
# is why green_not_merged worked while this did not.
# =============================================================================
STAMPS="$(python3 - "$HEALTH" <<'PY'
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("h", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
now = time.time()
base = time.gmtime(now - 9 * 3600)
shapes = {
    "linear": time.strftime("%Y-%m-%dT%H:%M:%S.412Z", base),   # Linear GraphQL
    "github": time.strftime("%Y-%m-%dT%H:%M:%SZ", base),       # gh --json
    "micros": time.strftime("%Y-%m-%dT%H:%M:%S.000001Z", base),
}
out = {}
for name, stamp in shapes.items():
    out[name] = {
        "minutes": m._minutes_since(stamp, now),
        "found": len(m.stranded_issue_findings(
            [{"identifier": "ASK-400", "startedAt": stamp}], set(), [], now)),
    }
out["garbage"] = {"minutes": m._minutes_since("not-a-date", now)}
print(json.dumps(out, sort_keys=True))
PY
)"
for shape in linear github micros; do
  echo "$STAMPS" | python3 -c "
import json,sys
d = json.load(sys.stdin)['$shape']
assert d['minutes'] == 540, 'minutes=%r' % d['minutes']
assert d['found'] == 1, 'findings=%r' % d['found']
" || fail "the $shape timestamp shape does not reach the stranded detector: $STAMPS"
done
echo "$STAMPS" | grep -q '"garbage": {"minutes": null}' \
  || fail "an unparseable timestamp must still be None, not a bogus age: $STAMPS"
ok "stranded_issue dates issues in Linear's fractional shape, GitHub's, and neither-guesses on garbage"

# =============================================================================
# CHECK 15 (review round 4, dropped-but-real): a longer issue id must not mask a
# shorter one.
#
# Branch matching was a substring test over one joined blob, so "ASK-22" matched
# "sana/ask-223" and ASK-22 read as somebody's live work for as long as that
# unrelated branch existed. The failure is silent and permanent -- exactly the
# shape a pager cannot afford, because the founder reads the quiet as health.
# =============================================================================
MASK="$(python3 - "$HEALTH" <<'PY'
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("h", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
now = time.time()
old = time.strftime("%Y-%m-%dT%H:%M:%S.412Z", time.gmtime(now - 9 * 3600))
issues = [{"identifier": i, "startedAt": old}
          for i in ("ASK-22", "ASK-223", "ASK-9")]
found = m.stranded_issue_findings(
    issues, set(), ["sana/ask-223", "main", "feature/ASK-9-thing"], now)
print(json.dumps({"stranded": sorted(f["subject"] for f in found),
                  "ids": sorted(m.branch_issue_ids(
                      ["sana/ask-223", "main", "feature/ASK-9-thing"]))}))
PY
)"
echo "$MASK" | grep -q '"stranded": \["ASK-22"\]' \
  || fail "ASK-22 is stranded and ASK-223/ASK-9 are not; got: $MASK"
echo "$MASK" | grep -q '"ids": \["ASK-223", "ASK-9"\]' \
  || fail "branch_issue_ids must extract whole ids, not substrings: $MASK"
ok "a branch for ASK-223 does not mask stranded ASK-22"

# =============================================================================
# CHECK 16 (review round 4, MINOR): unreviewed_head's cost is flat in the number
# of verdict records.
#
# It ran one sequential `gh pr view` per record in ~/.config/kipi/pr-reviews,
# a directory that gains a file per PR forever and is never pruned: 27 records
# was already 16.6s per cycle and the shape was unbounded. The heads now come
# out of the open-PR list green_not_merged already pays for.
#
# The half that could regress: detection must still work. This asserts BOTH --
# zero per-record calls AND the finding still fires on a real head mismatch.
# =============================================================================
mkdir -p "$WORK/state/pr-reviews" "$WORK/bin2"
for n in $(seq 1 30); do
  printf '{"pr":%d,"issue":"ASK-%d","verdict":"APPROVE","head_sha":"aaaa1111"}\n' \
    "$n" "$n" > "$WORK/state/pr-reviews/pr-$n.verdict.json"
done
cat > "$WORK/bin2/gh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_GH_LOG"
case "$1 $2" in
  # PR 7 is open on a DIFFERENT head than the one reviewed -> one finding.
  "pr list") echo '[{"number":7,"updatedAt":"2026-01-01T00:00:00Z","statusCheckRollup":[],"autoMergeRequest":null,"isDraft":false,"headRefOid":"bbbb2222"}]' ;;
  *) echo '[]' ;;
esac
EOF
chmod +x "$WORK/bin2/gh"
export FAKE_GH_LOG="$WORK/gh2.log"
: > "$FAKE_GH_LOG"
BATCH="$(PATH="$WORK/bin2:$PATH" python3 - "$HEALTH" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("h", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.fetch_in_progress_issues = lambda: []
observations, unobserved = m.collect_live()
print(json.dumps({"obs": observations, "unobserved": sorted(unobserved)}))
PY
)"
VIEWS="$(grep -c '^pr view' "$FAKE_GH_LOG" || true)"
[ "$VIEWS" = "0" ] \
  || fail "30 verdict records cost $VIEWS per-record gh calls; the cost must be flat"
TOTAL="$(wc -l < "$FAKE_GH_LOG" | tr -d ' ')"
[ "$TOTAL" -le 6 ] \
  || fail "one cycle made $TOTAL gh calls against 30 records; expected a fixed handful"
echo "$BATCH" | grep -q '"state": "unreviewed_head", "subject": "PR #7"' \
  || fail "batching lost the detection: an open PR past its reviewed sha must still fire: $BATCH"
case "$BATCH" in
  *'"subject": "PR #1"'*|*'"subject": "PR #2"'*)
    fail "a record whose PR is not open must not fire: $BATCH" ;;
esac
ok "unreviewed_head costs a fixed number of gh calls at 30 records, and still detects"

# And the window batching opened: a FULL page of open PRs may be clipped, so a PR
# past the edge would read as "not open" -- undetectable rather than merely slow.
# A full page must mark both list-fed states unobserved, not report a clean cycle.
cat > "$WORK/bin2/gh" <<'EOF'
#!/usr/bin/env bash
case "$1 $2" in
  "pr list")
    python3 -c "
import json
print(json.dumps([{'number': n, 'updatedAt': '2026-01-01T00:00:00Z',
                   'statusCheckRollup': [], 'autoMergeRequest': None,
                   'isDraft': False, 'headRefOid': 'cccc3333'}
                  for n in range(1, 101)]))" ;;
  *) echo '[]' ;;
esac
EOF
FULL="$(PATH="$WORK/bin2:$PATH" python3 - "$HEALTH" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("h", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.fetch_in_progress_issues = lambda: []
print(json.dumps(sorted(m.collect_live()[1])))
PY
)"
echo "$FULL" | grep -q 'green_not_merged' \
  || fail "a clipped PR page must not read as a fully observed cycle: $FULL"
echo "$FULL" | grep -q 'unreviewed_head' \
  || fail "a clipped PR page leaves unreviewed_head partly blind too: $FULL"
ok "a full page of open PRs degrades both list-fed states instead of claiming a clean cycle"

echo "PASS: $PASS/$PASS checks"
