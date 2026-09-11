#!/usr/bin/env bash
# portability-lint-skip-file: this script is macOS-only BY DESIGN (launchd/plutil).
# Will codex actually review Sana's work on the next scheduled run? (ASK-221)
#
# WHY THIS EXISTS: on 2026-07-29 a guard was written, tested green, and reported as
# shipped. It had not shipped -- it sat uncommitted while four commits went past it,
# because shipped state was claimed from memory instead of read. This script is that
# claim, made executable.
#
# RETARGETED FROM ASK-253. The first version checked the Linear-agent DELEGATION
# path (`linear-sync.py delegate --agent Codex`). That path was rejected: its status
# was advisory, so it could not gate, and it added a third verdict reader. What ships
# is the ENGINE path -- linear-worker.sh calls pr-review-agent.sh --engine codex, and
# codex owns the REQUIRED `kipi/reviewer-approved` context. The load-path discipline
# below is the part worth keeping; only the assertions changed.
#
# THE CHECK THAT MATTERS MOST IS #3. The launchd job runs a FIXED PATH out of the
# plist, and that checkout sits on whatever branch it sits on. Wiring merged into a
# feature branch changes nothing about tomorrow. So this reads the ACTUAL FILES the
# scheduler will execute -- never a repo-relative path, never this branch's copy.
#
# WHAT IT CANNOT TELL YOU: that a review RAN. Wiring is a precondition, not a
# receipt. The receipt is a VERDICT RECORD (pr-<N>.verdict.json carrying
# engine=codex), which is the artifact the reviewer actually writes. Check 8 reads
# those records rather than asserting from the wiring.
#
# This header used to say the receipt was a dispatch-log line, and said it for a
# while after check 8 stopped reading one -- codex round 1 on PR #47 flagged the
# drift. Worth the note: the wrong doc was more convincing than the code, because
# a header is what a reader trusts when they are deciding whether to look further.
#
# Exit 0 = codex is wired into the next run. Non-zero = it is not, with the reason.
set -uo pipefail

PLIST="$HOME/Library/LaunchAgents/com.kipi.dispatch.plist"
LABEL="com.kipi.dispatch"
FAILED=0
pass() { printf '  PASS %s\n' "$1"; }
fail() { printf '  FAIL %s\n' "$1"; FAILED=$((FAILED+1)); }
info() { printf '  ---- %s\n' "$1"; }

echo "PR-review live-wiring check -- PRIMARY engine: claude ($(date -u +%Y-%m-%dT%H:%M:%SZ))"

# --- 1. the scheduler exists and is loaded -----------------------------------
# CAPTURE FIRST, then match. `launchctl list | grep -q "$LABEL"` under
# `set -o pipefail` reports FAILURE on a job that IS loaded: grep -q exits the
# instant it matches, launchctl dies on the closed pipe with SIGPIPE, and pipefail
# propagates that as the pipeline's status. This check gave a false NOT-LOADED the
# first time it ran, on a job `launchctl print` resolves fine.
LAUNCHCTL_LIST="$(launchctl list 2>/dev/null || true)"
if printf '%s\n' "$LAUNCHCTL_LIST" | grep -q "$LABEL"; then
  pass "launchd job $LABEL is loaded"
else
  fail "launchd job $LABEL is NOT loaded, so nothing runs on a schedule at all"
fi

[ -f "$PLIST" ] || { fail "no plist at $PLIST"; echo; echo "RESULT: NOT WIRED ($FAILED failed)"; exit 1; }

# --- 2. resolve the EXACT files the scheduler will execute -------------------
# Read the path out of the plist rather than assuming the conventional one: the
# whole point is to check the running system, not the one described in a doc.
DISPATCH="$(plutil -extract ProgramArguments.1 raw -o - "$PLIST" 2>/dev/null)"
if [ -n "$DISPATCH" ] && [ -f "$DISPATCH" ]; then
  pass "plist points at an existing dispatcher: $DISPATCH"
else
  fail "plist ProgramArguments.1 does not resolve to a file: '${DISPATCH:-<empty>}'"
  echo; echo "RESULT: NOT WIRED ($FAILED failed)"; exit 1
fi
LIVE_ROOT="$(cd "$(dirname "$DISPATCH")" && pwd)"
LIVE_SCRIPTS="$LIVE_ROOT/q-system/.q-system/scripts"
LIVE_WORKER="$LIVE_SCRIPTS/linear-worker.sh"
LIVE_REVIEWER="$LIVE_SCRIPTS/pr-review-agent.sh"
LIVE_LIB="$LIVE_SCRIPTS/pr-verdict-lib.sh"
info "live repo root: $LIVE_ROOT"
info "live branch:    $(git -C "$LIVE_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
info "live HEAD:      $(git -C "$LIVE_ROOT" rev-parse --short HEAD 2>/dev/null || echo '?')"

# --- 3. THE WIRING IS IN THE FILE THAT WILL RUN ------------------------------
if [ ! -f "$LIVE_WORKER" ]; then
  fail "no worker at $LIVE_WORKER"
else
  if grep -q -- '--engine claude' "$LIVE_WORKER"; then
    pass "the live worker dispatches the reviewer with --engine claude"
  else
    fail "the live worker never passes --engine claude, so the scheduled run does not dispatch the engine that owns the gate. If the wiring is on a branch, it has to reach $(git -C "$LIVE_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)."
  fi
  if grep -q 'pr-review-agent.sh' "$LIVE_WORKER"; then
    pass "the live worker routes review through pr-review-agent.sh"
  else
    fail "the live worker does not call pr-review-agent.sh at all, so no engine flag matters"
  fi
  bash -n "$LIVE_WORKER" 2>/dev/null && pass "the live worker parses" \
    || fail "the live worker does NOT parse; the whole run dies"
fi

# --- 4. the live reviewer makes claude THE GATE, not a second opinion --------
if [ ! -f "$LIVE_REVIEWER" ]; then
  fail "no reviewer at $LIVE_REVIEWER"
else
  if grep -qE 'KIPI_REVIEW_ENGINE:-claude' "$LIVE_REVIEWER"; then
    pass "the live reviewer defaults to the claude engine"
  else
    fail "the live reviewer's default engine is not claude, so a bare invocation does not review with the engine that owns the gate"
  fi
  if grep -qE 'KIPI_REVIEW_PRIMARY_ENGINE:-claude' "$LIVE_REVIEWER"; then
    pass "claude is the PRIMARY engine, so it owns kipi/reviewer-approved"
  else
    fail "claude is not the PRIMARY engine in the live copy, so its verdict lands on an ADVISORY context and gates nothing. Both KIPI_REVIEW_ENGINE and KIPI_REVIEW_PRIMARY_ENGINE must name the same engine or every open PR wedges."
  fi
  if grep -q 'kipi/reviewer-approved' "$LIVE_REVIEWER"; then
    pass "the live reviewer posts the required context kipi/reviewer-approved"
  else
    fail "the live reviewer posts no kipi/reviewer-approved status, so the verdict is invisible to GitHub and every PR waits on a human"
  fi
  # The ASK-221 provenance guard. A reviewer that reads one tree and diffs another
  # writes findings with false provenance, which is worse than a wrong verdict.
  if grep -q 'merge-base --is-ancestor' "$LIVE_REVIEWER"; then
    pass "the live reviewer has the tree-vs-PR-head guard"
  else
    fail "the LIVE reviewer has NO tree-vs-head guard. A scheduled run from the wrong worktree would review this tree's files against another PR's diff and stamp the findings with that PR's sha."
  fi
  bash -n "$LIVE_REVIEWER" 2>/dev/null && pass "the live reviewer parses" \
    || fail "the live reviewer does NOT parse"
fi

# --- 5. ONE findings-block reader in the LIVE lib ----------------------------
# sp-c0a9dac3. Comments are stripped first because findings_block's own comment
# QUOTES the sed expression it replaced -- assert on code, not on prose about code.
if [ ! -f "$LIVE_LIB" ]; then
  fail "no verdict lib at $LIVE_LIB"
else
  SEDS="$(grep -v '^[[:space:]]*#' "$LIVE_LIB" | grep -c 'FINDINGS:/,/' | tr -d ' ')"
  if [ "$SEDS" = "0" ] && grep -q '^findings_block()' "$LIVE_LIB"; then
    pass "the live lib has one findings_block reader and no sed findings-ranges in code"
  else
    fail "the live lib still has $SEDS sed findings-range extraction(s) / no findings_block. A quoted prior-round block concatenates onto the real one, so a refuted finding can set the gate."
  fi
  bash -n "$LIVE_LIB" 2>/dev/null && pass "the live lib parses" \
    || fail "the live lib does NOT parse, so every review dies at the source line"
fi

# --- 6. the engine binary the live reviewer will shell actually exists -------
# Wiring that names a binary the PATH does not have degrades to the Opus fallback
# on every run: the gate stays green and stops being a second lab's opinion.
if command -v claude >/dev/null 2>&1; then
  pass "claude is on PATH ($(command -v claude))"
else
  fail "claude is NOT on PATH and claude is the PRIMARY engine, so every scheduled review has no binary to shell and the gate cannot be answered."
fi
# codex is ADVISORY since 2026-09-06, so its absence is reported and does not fail.
# It is still worth printing: the day it comes back is the day independence is
# restorable, and nobody will notice from a silent check.
if command -v codex >/dev/null 2>&1; then
  printf '  NOTE codex is on PATH (%s); advisory engine, does not gate\n' "$(command -v codex)"
else
  printf '  NOTE codex is not on PATH; advisory engine, does not gate\n'
fi

# --- 7. the live copy's OWN tests pass against the live copy ------------------
# The load-path proof with teeth: run the test files that ship in the LIVE tree, so
# they resolve their target from their own location. Greping the live file for a
# string proves the text is there; this proves the behaviour is.
for t in test-review-tree-guard.sh test-findings-block-reader.sh; do
  if [ -f "$LIVE_SCRIPTS/test/$t" ]; then
    if bash "$LIVE_SCRIPTS/test/$t" >/dev/null 2>&1; then
      pass "live $t passes against the live tree"
    else
      fail "live $t FAILS against the live tree. Run it directly for the reason: bash $LIVE_SCRIPTS/test/$t"
    fi
  else
    fail "no $t in the live tree, so the guard it covers is unproven where it matters"
  fi
done

# --- 8. when does it next get a chance, and has it ever actually run? --------
# The receipt, as opposed to the wiring.
#
# THE RECEIPT IS THE RECORD, NOT A LOG LINE (sp-1d1ad606). This block used to
# grep dispatch.log for `engine: codex`. That string is real -- pr-review-agent.sh
# prints `round: N (engine: codex)` -- but it goes to the reviewer's STDOUT, which
# linear-worker.sh redirects into $STATE_DIR/linear-worker.log. dispatch.log is
# written by kipi-dispatch.sh and carries cadence lines only, so the receipt string
# could never appear there. Check 8 printed NO RECEIPT YET unconditionally, forever,
# including after a real dispatcher-driven codex review -- and that was the one line
# in this verifier the founder was reading as proof.
#
# So read the VERDICT RECORD, which is the artifact the reviewer actually writes and
# already carries `engine`, `head_sha` and `ts`. This is also what the rest of the
# loop does (`verdict_from_record`, "ONE reader of the verdict, never re-grep the
# prose") -- the old grep was the only place that reasoned about a review from a log.
INTERVAL="$(plutil -extract StartInterval raw -o - "$PLIST" 2>/dev/null || echo '?')"
info "StartInterval: ${INTERVAL}s"

# Honour KIPI_STATE_DIR. The old hardcoded $HOME path meant a run against a test
# state dir silently reported on the founder's real one -- a verifier reading a
# different installation than the one under test is worse than no verifier.
STATE_DIR="${KIPI_STATE_DIR:-$HOME/.config/kipi}"
# WHICH REPO THIS VERIFIER IS ANSWERING FOR. Derived from the LIVE checkout the
# plist actually points at, then keyed exactly the way pr-review-agent.sh keys its
# artifacts (repo-slug-lib.sh: artifact_key turns owner/name into owner_name). One
# definition of the shape, reproduced here rather than re-invented, because the
# scan below now depends on it to avoid answering off another repo's record.
# PURE PARAMETER EXPANSION, NOT sed -E. The first cut used a lazy `+?` quantifier,
# which BSD sed on macOS rejects outright ("repetition-operator operand invalid").
# stderr went to /dev/null, the slug came out EMPTY, and the scan below then matched
# NOTHING -- fail-closed, but silently, on the one machine this runs on. Caught by
# EXECUTING the script; `bash -n` parses a broken regex just fine.
_ru="$(git -C "$LIVE_ROOT" config --get remote.origin.url 2>/dev/null)"
_ru="${_ru%.git}"; _rn="${_ru##*/}"; _ro="${_ru%/*}"; _ro="${_ro##*[:/]}"
if [ -n "$_rn" ] && [ -n "$_ro" ] && [ "$_rn" != "$_ru" ]; then
  RECEIPT_SLUG="$(printf '%s_%s' "$_ro" "$_rn" | tr -c 'A-Za-z0-9._-' '_')"
else
  RECEIPT_SLUG=""
fi
# The legacy un-slugged pr-<N>.verdict.json records all belong to the HOME repo
# (repo-slug-lib.sh verdict_record_path says so), so only the home repo may count
# them. Anything else must match its own key or it is another repo's evidence.
RECEIPT_LEGACY_OK=0
case "$RECEIPT_SLUG" in *_kipi-system) RECEIPT_LEGACY_OK=1 ;; esac
# AN UNDERIVABLE SLUG IS ANNOUNCED, NOT ABSORBED. With no key and no legacy
# permission the scan matches nothing and prints "NO RECEIPT YET", which reads
# exactly like a healthy repo that has simply not been reviewed yet. That is the
# silent-wrong-answer shape this whole file exists to refuse.
if [ -z "$RECEIPT_SLUG" ]; then
  fail "cannot derive this repo slug from $LIVE_ROOT (remote.origin.url='${_ru:-<none>}'), so the receipt scan below would silently match no records and report NO RECEIPT for a repo that may well have one."
fi
RECEIPT="$(python3 - "$STATE_DIR/pr-reviews" "$RECEIPT_SLUG" "$RECEIPT_LEGACY_OK" <<'PY' 2>/dev/null
import glob, json, os, sys
newest = None
# Initialised beside `newest`, because the first cut did NOT initialise it: the loop
# raised NameError, the `2>/dev/null` on the command substitution swallowed it, and
# the verifier silently reported NO receipt at all. A test greping for
# 'dispatcher-driven receipt' then PASSED against the failure message. Same
# swallowed-exception shape as the ledger-root fix earlier tonight.
worker = None
# Both layouts: the PRIMARY engine writes its verdict record to the parent dir,
# a secondary engine to <dir>/<engine>/. Globbing only one would miss the receipt
# the moment KIPI_REVIEW_PRIMARY_ENGINE changes.
#
# SCOPED TO THIS REPO (review of PR #320, major). This scan used to glob every
# *.verdict.json in the store, which holds records for 3 repo slugs plus ~120
# legacy un-slugged ones. So a worker-driven review of a DIFFERENT repository
# satisfied the dispatcher-driven proof line for THIS one -- the exact defect
# repo-slug-lib.sh was written to end, quoting its own header: a gate could read
# an APPROVE earned by a different repository code. A verifier that answers
# "is THIS repo wired" off another repo record is worse than no verifier.
#
# The legacy un-slugged pr-<N>.verdict.json shape is accepted ONLY for the home
# repo, matching verdict_record_path in that same lib, which documents that all
# ~90 legacy records belong to the home repo.
key = sys.argv[2]                      # e.g. assafkip_kipi-system, or "" for legacy-only
legacy_ok = sys.argv[3] == "1"
def mine(path):
    b = os.path.basename(path)
    if key and b.startswith(key + "__"):
        return True
    return legacy_ok and "__" not in b
for p in sorted(filter(mine,
        glob.glob(os.path.join(sys.argv[1], "*.verdict.json")) +
        glob.glob(os.path.join(sys.argv[1], "*", "*.verdict.json")))):
    try:
        r = json.load(open(p))
    except Exception:
        continue          # a corrupt record is not a receipt
    # ENGINE NAME CANNOT SEE WHICH CONTRACT A RECORD WAS WRITTEN UNDER (review of
    # PR #319 minor, corrected by the review of PR #320). The primary engine went
    # claude -> codex (2026-07-29) -> claude (2026-09-06), so in principle a claude
    # record could come from the current era, the pre-07-29 primary era, or a
    # 07-29..09-06 ADVISORY run.
    #
    # WHAT IS ACTUALLY MEASURED, 2026-09-07, replacing a causal sentence that was
    # asserted here and was FALSE. The earliest claude record in the store is dated
    # 2026-09-03, so ZERO exist from the pre-07-29 era and that era is unreachable
    # through this filter. The 4 claude records sitting at this ROOT are all dated
    # 09-03/09-04, i.e. from the codex-primary window, where claude was advisory --
    # 2 of them ALSO have a copy in the subdir, the fingerprint of a hand run with a
    # non-default primary. The earlier comment explained the root records by saying
    # claude was primary before 07-29. That was a story, not a measurement.
    #
    # SO THE REMAINING EXPOSURE IS NARROW AND IS STATED IN THE OUTPUT, not only
    # here: the ANY line can be satisfied by an advisory-era record. The
    # DISPATCHER-DRIVEN line additionally requires invoker=worker, and the scan is
    # now scoped to this repo, so it can no longer be answered by another repo.
    # The durable fix is a `gating` boolean on the record at write time (sp-bd35985f);
    # a date literal here would be the stale-safety-argument shape the PR #319 review
    # existed to remove.
    #
    # NO APOSTROPHES IN THIS BLOCK. It sits inside a quoted heredoc nested in a $( )
    # command substitution, where one lone apostrophe breaks shell parsing. The first
    # draft of this comment did exactly that and the file stopped parsing.
    r["_advisory"] = os.path.basename(os.path.dirname(p)) != os.path.basename(sys.argv[1].rstrip("/"))
    if r.get("engine") != "claude":
        continue
    if newest is None or str(r.get("ts", "")) > str(newest.get("ts", "")):
        newest = r
    # THE DISPATCHER-DRIVEN RECEIPT IS TRACKED SEPARATELY, not as "the newest one
    # that happens to be a worker run" (sp-53aad86f). A later HAND review must not
    # hide it: "has the dispatcher ever done this unattended" is not a question
    # about recency. A MISSING invoker key counts as manual -- every record written
    # before the field existed lacks it, and treating those as proof would
    # manufacture exactly the evidence this check exists to supply.
    if r.get("invoker") == "worker":
        if worker is None or str(r.get("ts", "")) > str(worker.get("ts", "")):
            worker = r
def line(r):
    # THE CAVEAT GOES IN THE OUTPUT (review of PR #320, minor). It used to live only
    # in a comment above, which the operator reading this banner never sees -- and a
    # comment is not a fix. A record written into an <engine>/ subdir is by
    # construction an ADVISORY one, so say so on the line itself.
    tag = " [ADVISORY-slot record, not a gating one]" if r.get("_advisory") else ""
    return "PR #%s %s verdict=%s head=%.12s at %s (invoker=%s)%s" % (
        r.get("pr"), r.get("issue", "?"), r.get("verdict"),
        str(r.get("head_sha", "")), r.get("ts"), r.get("invoker", "<absent>"), tag)
if newest:
    print("ANY|" + line(newest))
if worker:
    print("WORKER|" + line(worker))
PY
)"
ANY_RECEIPT="$(printf '%s\n' "$RECEIPT" | sed -n 's/^ANY|//p')"
WORKER_RECEIPT="$(printf '%s\n' "$RECEIPT" | sed -n 's/^WORKER|//p')"
if [ -n "$ANY_RECEIPT" ]; then
  info "RECEIPT FOUND: a review by the PRIMARY engine (claude) really ran -- $ANY_RECEIPT"
else
  info "NO RECEIPT YET: no pr-*.verdict.json under $STATE_DIR/pr-reviews carries engine=claude. Wiring is green; a real run has not been observed."
fi
# THE PROOF THE FOUNDER IS ACTUALLY WAITING ON. Reported as its own line because
# "a codex review ran" and "the dispatcher ran one unattended" are different
# claims, and only the second closes the loop. Conflating them is what let every
# earlier proof carry a hole.
if [ -n "$WORKER_RECEIPT" ]; then
  info "DISPATCHER-DRIVEN RECEIPT FOUND: the scheduled loop reviewed a PR unattended -- $WORKER_RECEIPT"
else
  info "NO DISPATCHER-DRIVEN RECEIPT YET: no claude record carries invoker=worker. A hand-run review does not count, and a record with no invoker key reads as manual."
fi

LOG="$STATE_DIR/dispatch.log"
if [ -f "$LOG" ]; then
  # Cadence only. This log answers "when does it next get a chance", never
  # "did a review happen" -- that is the record above.
  info "last dispatch line: $(tail -1 "$LOG")"
  if tail -5 "$LOG" | grep -q "DAILY CAP"; then
    info "daily cap is spent; the next real dispatch is after the 07:00 local reset"
  fi
else
  info "no dispatch log yet at $LOG"
fi

echo
if [ "$FAILED" -eq 0 ]; then
  echo "RESULT: WIRED -- claude reviews the next PR the dispatcher picks up."
  exit 0
fi
echo "RESULT: NOT WIRED ($FAILED check(s) failed). The PRIMARY engine will NOT review on the next run."
exit 1
