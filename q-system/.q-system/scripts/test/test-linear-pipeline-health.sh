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

echo "PASS: $PASS/$PASS checks"
