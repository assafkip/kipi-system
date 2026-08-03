#!/usr/bin/env bash
# Pairs with ci-redrive.py's `wedged` op (ASK-313): a REQUIRED status context
# that nothing ever posts blocks a PR forever, silently.
#
# THE SCAR (2026-08-02)
# ---------------------
# PR #75 (ASK-311) sat at mergeStateStatus=BLOCKED with auto-merge armed,
# `validate` SUCCESS, and `kipi/reviewer-approved` ABSENT. Measured that day:
#
#   $ gh api repos/assafkip/kipi-system/branches/main/protection
#     required_status_checks.contexts = ["validate","kipi/reviewer-approved"]
#   $ gh pr view 75 --json mergeStateStatus   -> BLOCKED
#   $ gh pr checks 75                          -> validate only
#
# `kipi/reviewer-approved` has exactly one producer, pr-review-agent.sh, whose
# only automated caller is linear-worker.sh:1802 -- reachable only from the
# dispatcher loop, for DoR-ready issues. A PR opened by hand gets a required
# check with no producer. Auto-merge was armed and correctly refusing; nothing
# said so, so the founder was told it would land on its own.
#
# WHY THE STANDARD GITHUB FIX IS THE WRONG FIX HERE
# -------------------------------------------------
# The documented remedy for a never-reported required check is a no-op job that
# always posts the context green. That would be catastrophic on this repo.
# linear-worker.sh:687 states the blast radius: "Remove `kipi/reviewer-approved`
# from that set and this becomes an unreviewed-merge machine." ABSENCE HERE IS A
# CORRECT REFUSAL. So nothing in this suite asserts that a wedged PR becomes
# mergeable -- it asserts that the wedge is SEEN and handed to the real
# producer. A fix that made these PRs green would pass a suite built the other
# way, which is why the discrimination is written down here.
#
# WHY THE EXISTING SWEEP CANNOT SEE THIS
# --------------------------------------
# failing_checks() iterates statusCheckRollup, so it can only observe contexts
# that were POSTED. An absent required context contributes zero rollup entries.
# The sweep reads a wedged PR as perfectly healthy. Case 1 pins exactly that.
#
# WHAT THIS SUITE PINS
# --------------------
#   1. Required-but-absent is detected (the wedge).
#   2. NEGATIVE SELF-TEST: a PR with every required context posted is NOT
#      wedged. Without this, a detector that returned "wedged" unconditionally
#      would pass case 1.
#   3. A required context POSTED and FAILING is not a wedge. That PR was
#      reviewed and rejected -- a visible state with its own consumer. Folding
#      it in here would re-review every rejected PR forever.
#   4. Protection unreadable is a THIRD answer (rc 2), never "nothing required".
#      Reading a 404/403 as "no requirements" would report every wedged PR
#      healthy at the exact moment the tool lost the ability to tell.
#   5. One reviewer run per PR per missing-context set, claimed through the
#      SAME attempts ledger the redrive path uses.
#   6. Drafts are excluded: a draft is not asking to merge, and spending a codex
#      review on one is spending the founder's money on a question nobody asked.
#
# The gh seam is a fixture script that dispatches on ARGV -- this detector makes
# two different gh calls (`pr list` and `api .../protection`), so the existing
# print-one-file stub in test-ci-redrive.sh cannot express these cases.
set -uo pipefail

PASS=0; FAIL=0
ok()  { printf '  PASS %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; FAIL=$((FAIL + 1)); }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expected [$3] got [$2]"; fi; }
contains() {
  if printf '%s' "$2" | grep -qF -- "$3"; then ok "$1"
  else bad "$1" "expected to find [$3] in [$2]"; fi
}
lacks() {
  if printf '%s' "$2" | grep -qF -- "$3"; then bad "$1" "did NOT expect [$3] in [$2]"
  else ok "$1"; fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# FOUR levels up: test -> scripts -> .q-system -> q-system -> repo root.
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
REDRIVE="$REPO_ROOT/q-system/.q-system/scripts/ci-redrive.py"
[ -f "$REDRIVE" ] || { echo "FATAL: ci-redrive.py not found at $REDRIVE" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- the gh seam, dispatching on ARGV ----------------------------------------
# `pr list ...`            -> $GH_FIXTURE          (the open PRs)
# `api .../protection`     -> $PROT_FIXTURE        (branch protection)
# $PROT_RC != 0 makes ONLY the protection call fail, which is the real-world
# shape: a token that can list PRs but cannot read protection (that endpoint
# needs admin). A stub that failed both would test a different outage.
# The two failure MESSAGES are gh's own, copied from real runs on 2026-08-02:
#   unprotected base : `gh: Branch not protected (HTTP 404)`      rc 1
#   no admin scope   : `gh: Resource not accessible ... (HTTP 403)` rc 1
# Both exit 1. Only the HTTP code separates a definite answer from an
# indefinite one, which is exactly why the reader matches on the code.
cat > "$TMP/gh" <<'SH'
#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in
    */protection)
      if [ -n "${PROT_404_BRANCH:-}" ] && [[ "$a" == *"/branches/${PROT_404_BRANCH}/protection" ]]; then
        echo "gh: Branch not protected (HTTP 404)" >&2; exit 1
      fi
      [ "${PROT_RC:-0}" = "0" ] || {
        echo "gh: Resource not accessible by integration (HTTP 403)" >&2
        exit "${PROT_RC}"; }
      cat "$PROT_FIXTURE"; exit 0 ;;
  esac
done
[ "${GH_RC:-0}" = "0" ] || { echo "gh: could not read PRs" >&2; exit "${GH_RC}"; }
cat "$GH_FIXTURE"
SH
chmod +x "$TMP/gh"

cat > "$TMP/notify.sh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$NOTIFY_LOG"
SH
chmod +x "$TMP/notify.sh"

printf '#!/bin/sh\ncat "${PS_FIXTURE:-/dev/null}"\n' > "$TMP/ps"; chmod +x "$TMP/ps"
: > "$TMP/ps-empty"

# Real shape, `gh api repos/assafkip/kipi-system/branches/main/protection`,
# 2026-08-02. Both halves are populated by GitHub; the reader must not depend
# on only one of them.
PROT_BOTH='{"required_status_checks":{"strict":false,
  "contexts":["validate","kipi/reviewer-approved"],
  "checks":[{"context":"validate","app_id":null},
            {"context":"kipi/reviewer-approved","app_id":null}]}}'

# PR 75 verbatim from `gh pr list --json ...` on 2026-08-02: validate green,
# NO reviewer-approved entry at all. This is the wedge.
WEDGED='[
 {"number":75,"headRefName":"sana/ask-311","isDraft":false,"baseRefName":"main",
  "headRefOid":"1111111111111111111111111111111111111111",
  "url":"https://github.com/assafkip/kipi-system/pull/75",
  "title":"feat(guard): when Opus is stuck, Fable triages (ASK-311)",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"validate","status":"COMPLETED",
     "conclusion":"SUCCESS","workflowName":"Skeleton Validation"}]}]'

# Same PR with the reviewer's verdict posted and FAILING. Reviewed, rejected,
# visible. Not a wedge.
REVIEWED_RED='[
 {"number":75,"headRefName":"sana/ask-311","isDraft":false,"baseRefName":"main",
  "headRefOid":"1111111111111111111111111111111111111111",
  "url":"https://github.com/assafkip/kipi-system/pull/75",
  "title":"feat(guard): when Opus is stuck, Fable triages (ASK-311)",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"validate","status":"COMPLETED",
     "conclusion":"SUCCESS","workflowName":"Skeleton Validation"},
    {"__typename":"StatusContext","context":"kipi/reviewer-approved",
     "state":"FAILURE","targetUrl":"https://github.com/x/y/pull/75#c1"}]}]'

# Every required context posted and green.
HEALTHY='[
 {"number":76,"headRefName":"sana/ask-300","isDraft":false,"baseRefName":"main",
  "headRefOid":"2222222222222222222222222222222222222222",
  "url":"https://github.com/assafkip/kipi-system/pull/76",
  "title":"fix: something (ASK-300)",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"validate","status":"COMPLETED",
     "conclusion":"SUCCESS","workflowName":"Skeleton Validation"},
    {"__typename":"StatusContext","context":"kipi/reviewer-approved",
     "state":"SUCCESS","targetUrl":"https://github.com/x/y/pull/76#c1"}]}]'

# A draft, wedged in exactly the same way. Not asking to merge.
DRAFT='[
 {"number":80,"headRefName":"sana/ask-301","isDraft":true,"baseRefName":"main",
  "headRefOid":"3333333333333333333333333333333333333333",
  "url":"https://github.com/assafkip/kipi-system/pull/80",
  "title":"wip (ASK-301)",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"validate","status":"COMPLETED",
     "conclusion":"SUCCESS","workflowName":"Skeleton Validation"}]}]'

# The founder's own hand-opened PR: no agent prefix on the branch. It wedges
# identically -- branch protection does not care who pushed -- so the detector
# must not inherit redrive's agent-only attribution.
FOUNDER='[
 {"number":103,"headRefName":"assaf-hotfix","isDraft":false,"baseRefName":"main",
  "headRefOid":"4444444444444444444444444444444444444444",
  "url":"https://github.com/assafkip/kipi-system/pull/103",
  "title":"chore: founder hand edit",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"validate","status":"COMPLETED",
     "conclusion":"SUCCESS","workflowName":"Skeleton Validation"}]}]'

fixture()      { printf '%s' "$1" > "$TMP/prs.json"; }
prot_fixture() { printf '%s' "$1" > "$TMP/prot.json"; }

run() {  # run <op> [args...]
  KIPI_GH="$TMP/gh" \
  KIPI_PS="$TMP/ps" \
  KIPI_NOTIFY="$TMP/notify.sh" \
  KIPI_ATTEMPTS="$LEDGER" \
  GH_FIXTURE="$TMP/prs.json" \
  PROT_FIXTURE="$TMP/prot.json" \
  GH_RC="${GH_RC:-0}" \
  PROT_RC="${PROT_RC:-0}" \
  PROT_404_BRANCH="${PROT_404_BRANCH:-}" \
  PS_FIXTURE="${PS_FIXTURE:-$TMP/ps-empty}" \
  NOTIFY_LOG="$NOTIFY_LOG" \
  python3 "$REDRIVE" --repo-dir "$TMP" "$@" 2>"$TMP/err"
}

fresh_state() {
  LEDGER="$TMP/attempts-$1.json"
  NOTIFY_LOG="$TMP/notify-$1.log"
  : > "$NOTIFY_LOG"
  rm -f "$LEDGER"
  PS_FIXTURE="$TMP/ps-empty"
  GH_RC=0; PROT_RC=0; PROT_404_BRANCH=""
  prot_fixture "$PROT_BOTH"
}

pages() { wc -l < "$NOTIFY_LOG" | tr -d ' '; }

echo "== wedged-PR detection (ASK-313) =="

# --- 1. the scar itself ------------------------------------------------------
fresh_state 1; fixture "$WEDGED"
OUT="$(run wedged)"; RC=$?
check "1a rc 0: a required context nobody posted is a wedge" "$RC" "0"
contains "1b names the PR" "$OUT" "75"
contains "1c names the missing context in stderr" "$(cat "$TMP/err")" "kipi/reviewer-approved"

# --- 2. NEGATIVE SELF-TEST ---------------------------------------------------
# Without this, "return wedged for everything" passes case 1.
fresh_state 2; fixture "$HEALTHY"
OUT="$(run wedged)"; RC=$?
check "2a rc 1: every required context posted is NOT a wedge" "$RC" "1"
check "2b prints nothing" "$OUT" ""

# --- 3. posted-and-failing is not absent -------------------------------------
fresh_state 3; fixture "$REVIEWED_RED"
OUT="$(run wedged)"; RC=$?
check "3a rc 1: reviewed-and-rejected is a visible state, not a wedge" "$RC" "1"
check "3b prints nothing" "$OUT" ""

# --- 4. protection unreadable is a third answer ------------------------------
fresh_state 4; fixture "$WEDGED"; PROT_RC=1
OUT="$(run wedged)"; RC=$?
check "4a rc 2: unreadable protection is not 'nothing required'" "$RC" "2"
check "4b claims nothing" "$OUT" ""
lacks "4c does not page on a probe failure" "$(cat "$NOTIFY_LOG")" "wedged"

# --- 5. one attempt per PR per missing set -----------------------------------
fresh_state 5; fixture "$WEDGED"
OUT="$(run wedged)"; RC=$?
check "5a offered once" "$RC" "0"
SIG="$(printf '%s' "$OUT" | cut -f2)"
run mark-reviewed --pr 75 --signature "$SIG" >/dev/null; MRC=$?
check "5b the claim succeeds the first time" "$MRC" "0"
OUT2="$(run wedged)"; RC2=$?
check "5c not offered twice for the same missing set" "$RC2" "1"
run mark-reviewed --pr 75 --signature "$SIG" >/dev/null; MRC2=$?
check "5d the claim is refused the second time" "$MRC2" "1"

# --- 6. drafts are not asking to merge ---------------------------------------
fresh_state 6; fixture "$DRAFT"
OUT="$(run wedged)"; RC=$?
check "6a rc 1: a draft is excluded" "$RC" "1"
check "6b prints nothing" "$OUT" ""

# --- 7. the founder's own PR wedges too --------------------------------------
# redrive attributes only agent branches. Branch protection does not, so this
# detector must not inherit that filter, or the one PR class that has NO agent
# to hand it back to is the one class left wedged forever.
fresh_state 7; fixture "$FOUNDER"
OUT="$(run wedged)"; RC=$?
check "7a rc 0: a non-agent branch wedges identically" "$RC" "0"
contains "7b names the PR" "$OUT" "103"

# --- 8. the founder hears about it, once, after the machine tier -------------
fresh_state 8; fixture "$WEDGED"
OUT="$(run wedged)"; SIG="$(printf '%s' "$OUT" | cut -f2)"
run mark-reviewed --pr 75 --signature "$SIG" >/dev/null
run wedged >/dev/null            # machine tier spent -> escalate
check "8a paged once" "$(pages)" "1"
contains "8b the page names the missing context" "$(cat "$NOTIFY_LOG")" "kipi/reviewer-approved"
run wedged >/dev/null            # and not again
check "8c not paged twice for one fact" "$(pages)" "1"

# --- 9. EACH half of the protection response is load-bearing -----------------
# Added because mutation testing killed nothing here: with both halves populated
# (which is what GitHub sends today) a reader of EITHER one passes every case
# above, so "both halves are read" was an unpinned claim. Deleting the
# `contexts` loop survived the whole suite. These two cases are the only thing
# that makes the claim real, and they are why the reader may not be "simplified"
# back to one half later.
PROT_LEGACY_ONLY='{"required_status_checks":{"strict":false,
  "contexts":["validate","kipi/reviewer-approved"],"checks":[]}}'
PROT_CHECKS_ONLY='{"required_status_checks":{"strict":false,
  "contexts":[],
  "checks":[{"context":"validate","app_id":null},
            {"context":"kipi/reviewer-approved","app_id":null}]}}'

fresh_state 9; fixture "$WEDGED"; prot_fixture "$PROT_LEGACY_ONLY"
OUT="$(run wedged)"; RC=$?
check "9a legacy contexts[] alone is honoured" "$RC" "0"
contains "9b names the missing context" "$(cat "$TMP/err")" "kipi/reviewer-approved"

fresh_state 10; fixture "$WEDGED"; prot_fixture "$PROT_CHECKS_ONLY"
OUT="$(run wedged)"; RC=$?
check "10a checks[] alone is honoured" "$RC" "0"
contains "10b names the missing context" "$(cat "$TMP/err")" "kipi/reviewer-approved"

# --- 11. AN UNPROTECTED BASE MUST NOT BLIND THE WHOLE SWEEP ------------------
# The first live run of this detector died exactly here:
#   ci-redrive: could not read branch protection for sana/block-expiry
#     (rc 1): gh: Branch not protected (HTTP 404) -- nothing was claimed.  rc 2
# A stacked PR based on another agent's branch is ordinary in this fleet, and
# one unprotected base returned rc 2 for the ENTIRE sweep -- reintroducing the
# silence the detector exists to end. 404 is a DEFINITE answer: no protection,
# nothing required, that PR cannot wedge. The wedged PR on `main` must still be
# found in the same pass.
STACKED='[
 {"number":90,"headRefName":"sana/ask-320","isDraft":false,
  "baseRefName":"sana/block-expiry",
  "headRefOid":"5555555555555555555555555555555555555555",
  "url":"https://github.com/assafkip/kipi-system/pull/90",
  "title":"stacked on an unprotected base (ASK-320)",
  "statusCheckRollup":[]},
 {"number":75,"headRefName":"sana/ask-311","isDraft":false,"baseRefName":"main",
  "headRefOid":"1111111111111111111111111111111111111111",
  "url":"https://github.com/assafkip/kipi-system/pull/75",
  "title":"feat(guard): when Opus is stuck, Fable triages (ASK-311)",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"validate","status":"COMPLETED",
     "conclusion":"SUCCESS","workflowName":"Skeleton Validation"}]}]'

fresh_state 11; fixture "$STACKED"; PROT_404_BRANCH="sana/block-expiry"
OUT="$(run wedged)"; RC=$?
check "11a rc 0: an unprotected base does not kill the sweep" "$RC" "0"
contains "11b the wedged PR on main is still found" "$OUT" "75"
lacks "11c the stacked PR is not called wedged" "$OUT" "90"

# --- 12. 403 IS STILL INDEFINITE ---------------------------------------------
# The discrimination case for 11. A token that cannot READ protection must not
# be read as a repo that REQUIRES nothing -- that is the original defect.
fresh_state 12; fixture "$WEDGED"; PROT_RC=1
OUT="$(run wedged)"; RC=$?
check "12a rc 2: 403 stays indefinite" "$RC" "2"
contains "12b names the code it refused on" "$(cat "$TMP/err")" "403"

# --- 13. RED CI OUTRANKS A WEDGE ---------------------------------------------
# Real shape: PR #76, 2026-08-02, was BOTH red on `validate` AND missing
# `kipi/reviewer-approved`. The redrive tier owns a red PR; reviewing it here
# would buy a codex read of a tree that is about to change. Case 14 is the
# discrimination: the same PR IS this tier's business once CI goes green.
RED_AND_WEDGED='[
 {"number":76,"headRefName":"sana/ask-312","isDraft":false,"baseRefName":"main",
  "headRefOid":"6666666666666666666666666666666666666666",
  "url":"https://github.com/assafkip/kipi-system/pull/76",
  "title":"The review gate cannot go green on a review that never ran (ASK-312)",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"validate","status":"COMPLETED",
     "conclusion":"FAILURE","workflowName":"Skeleton Validation"}]}]'

fresh_state 13; fixture "$RED_AND_WEDGED"
OUT="$(run wedged)"; RC=$?
check "13a rc 1: a red PR is the redrive tier's, not this one's" "$RC" "1"
check "13b prints nothing" "$OUT" ""

# --- 14. ...AND IS PICKED UP THE MOMENT CI GOES GREEN ------------------------
# Without this, "skip everything with any check" would pass case 13.
GREEN_AND_WEDGED="${RED_AND_WEDGED/\"conclusion\":\"FAILURE\"/\"conclusion\":\"SUCCESS\"}"
fresh_state 14; fixture "$GREEN_AND_WEDGED"
OUT="$(run wedged)"; RC=$?
check "14a rc 0: green CI + absent required context is a wedge" "$RC" "0"
contains "14b names the PR" "$OUT" "76"

# --- 15. A CLAIMED ATTEMPT IS NOT A COMPLETED ATTEMPT ------------------------
# Found by codex reviewing THIS change (PR #78): "the second heartbeat falsely
# escalates a wedged PR while its detached reviewer is still running, then
# suppresses the later real alert."
#
# The reviewer is launched DETACHED and takes minutes; the heartbeat is 900s.
# So the very next run sees the ledger flag set, reads it as "the machine tier
# is spent", and pages the founder that the reviewer ran and the context is
# still absent -- while the reviewer is mid-flight. Worse, that page CLAIMS
# `wedged_escalated_<sig>`, so when the reviewer really does fail, the one page
# owed to the founder has already been burnt on a false alarm.
#
# cmd_redrive already guards exactly this and says why: "the founder would be
# paged that a still-running attempt had stopped -- burning the one page owed
# to him when it really does." That guard was not carried into this tier.
# The dispatcher's own WEDGED_PS check does NOT cover it: that only stops a
# SECOND reviewer being launched, and the escalation lives in here.
ps_fixture() { printf '%s\n' "$1" > "$TMP/ps-table"; PS_FIXTURE="$TMP/ps-table"; }

fresh_state 15; fixture "$WEDGED"
OUT="$(run wedged)"; SIG="$(printf '%s' "$OUT" | cut -f2)"
run mark-reviewed --pr 75 --signature "$SIG" >/dev/null
# the detached reviewer this run just launched is still going
ps_fixture "bash /Users/x/q-system/.q-system/scripts/pr-review-agent.sh 75 --post --engine codex"
run wedged >/dev/null; RC=$?
check "15a rc 1: nothing offered while its own reviewer is live" "$RC" "1"
check "15b NOT paged about a reviewer that is still running" "$(pages)" "0"
lacks "15c no escalation text" "$(cat "$NOTIFY_LOG")" "machine tier is spent"

# --- 16. ...AND THE REAL PAGE STILL FIRES ONCE THE REVIEWER IS GONE ----------
# The discrimination for 15. If 15 were implemented by simply never escalating,
# the founder would never hear about a wedge the machine could not fix.
ps_fixture ""                      # reviewer exited, context still absent
run wedged >/dev/null
check "16a paged once the reviewer is actually gone" "$(pages)" "1"
contains "16b and it names the missing context" "$(cat "$NOTIFY_LOG")" "kipi/reviewer-approved"

echo
printf 'wedged-pr: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
