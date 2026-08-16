#!/usr/bin/env bash
# Pairs with review-redrive.py + park_labels.py (ASK-872): the three labels that
# PARK an issue stop the fresh-pick path in linear-worker.sh and did not stop the
# redrive.
#
# THE DEFECT, measured 2026-08-16:
#   $ grep -n "owner:assaf\|needs-scope\|blocked:capability" review-redrive.py
#   (no output)
# A third consumer dispatching the same agents at the same issues, reading none
# of the vocabulary the other two use to say "not this one".
#
# THE PROPERTY UNDER TEST is the DISCRIMINATION, same posture as
# test-review-redrive.sh: a selector that skips everything passes any test that
# only checks the three parked fixtures, so the fourth fixture -- identical in
# every field except its labels -- must still be offered. Without it the fix
# "skip all PRs" is green.
#
# ISOLATION. The park check reads labels from Linear, so every case here points
# KIPI_LINEAR_API_URL at a fixture HTTP server on 127.0.0.1. No case reaches the
# real board and no case needs a real API key.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SEL="$REPO_ROOT/q-system/.q-system/scripts/review-redrive.py"
[ -f "$SEL" ] || { echo "FATAL: review-redrive.py not found at $SEL" >&2; exit 1; }
SEL="${REVIEW_REDRIVE_UNDER_TEST:-$SEL}"

WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

RECORDS="$WORK/records"; mkdir -p "$RECORDS"
BIN="$WORK/bin"; mkdir -p "$BIN"

# --- the notify sink, stubbed for every case --------------------------------
# review-redrive escalates from inside `select`. With no stub that is the REAL
# slack-notify.sh: a live data path in a test suite, quiet only because no
# webhook resolves on this machine.
PAGES="$WORK/pages.txt"; : > "$PAGES"
cat > "$BIN/notify.sh" <<EOS
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$PAGES"
EOS
chmod +x "$BIN/notify.sh"

# --- the board, stubbed at the gh seam --------------------------------------
cat > "$BIN/gh" <<'EOS'
#!/usr/bin/env bash
cat "$BOARD"
EOS
chmod +x "$BIN/gh"

# --- fixture Linear: one label set per issue --------------------------------
# The four issues are byte-identical except for `labels`, which is the only
# field the park check may read.
#
# THE SERVER IS A COMMITTED FILE, NOT A HEREDOC. test-ci-redrive.sh drives the
# real dispatcher against the same reader and needs the same board, and a second
# copy of this fixture would drift exactly like a second copy of the label list.
FIXTURE_SRV="$(dirname "${BASH_SOURCE[0]}")/linear-park-fixture.py"
[ -f "$FIXTURE_SRV" ] || { echo "FATAL: fixture server not found at $FIXTURE_SRV" >&2; exit 1; }
LABELS_FILE="$WORK/labels.json"
set_labels() { printf '%s' "$1" > "$LABELS_FILE"; }
set_labels '{"ASK-901": ["owner:sana", "owner:assaf"],
             "ASK-902": ["owner:sana", "needs-scope"],
             "ASK-903": ["owner:sana", "blocked:capability"],
             "ASK-904": ["owner:sana"],
             "ASK-905": ["owner:sana"]}'
export LABELS_FILE
python3 "$FIXTURE_SRV" > "$WORK/port" 2> "$WORK/server.err" &
SRV_PID=$!
for _ in $(seq 1 100); do PORT="$(cat "$WORK/port" 2>/dev/null)"; [ -n "${PORT:-}" ] && break; sleep 0.1; done
[ -n "${PORT:-}" ] || { echo "fixture server did not start"; cat "$WORK/server.err"; exit 1; }

# A PR entry with a failing reviewer slot. Everything except pr/branch/sha is
# fixed, so a difference in outcome can only come from the issue's labels.
pr_entry() {   # pr_entry <number> <issue-lower> <sha>
  cat <<EOS
{"number": $1, "headRefName": "sana/$2", "headRefOid": "$3",
 "url": "https://example.invalid/pr/$1", "title": "work ($(echo "$2" | tr a-z A-Z))",
 "isDraft": false,
 "statusCheckRollup": [
   {"__typename": "StatusContext", "context": "kipi/reviewer-approved", "state": "FAILURE"},
   {"__typename": "CheckRun", "name": "validate", "status": "COMPLETED", "conclusion": "SUCCESS"}
 ]}
EOS
}

record() {   # record <pr> <issue> <sha>
  python3 - "$RECORDS/pr-$1.verdict.json" "$1" "$2" "$3" <<'PY'
import json, sys
out, pr, issue, sha = sys.argv[1:5]
json.dump({"pr": int(pr), "issue": issue, "verdict": "REQUEST CHANGES",
           "stated": "REQUEST CHANGES", "derived": "", "source": "findings",
           "engine": "codex", "round": 1, "review": "", "usable": True,
           "head_sha": sha, "ts": "now"}, open(out, "w"), indent=2)
PY
}

# KIPI_ATTEMPTS IS PINNED AT A TEMP PATH FOR EVERY CASE. Without it the ledger
# ops below write to the real attempts ledger -- a live data path inside a test
# suite, and one that would silently spend a real PR's one machine attempt.
LEDGER="$WORK/attempts.json"

run_select() {   # run_select   (RR_URL / RR_BOARD override the two sources)
  env PATH="$BIN:$PATH" BOARD="${RR_BOARD:-$WORK/board.json}" KIPI_NOTIFY="$BIN/notify.sh" \
    KIPI_ATTEMPTS="$LEDGER" \
    KIPI_LINEAR_API_URL="${RR_URL:-http://127.0.0.1:$PORT/graphql}" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    python3 "$SEL" --repo-dir "$WORK" --records-dir "$RECORDS" select --all \
    > "$WORK/out.txt" 2> "$WORK/err.txt"
  echo $?
}

run_mark() {   # run_mark <issue> <action> <pr> <sha>
  env PATH="$BIN:$PATH" BOARD="$WORK/board.json" KIPI_NOTIFY="$BIN/notify.sh" \
    KIPI_ATTEMPTS="$LEDGER" \
    KIPI_LINEAR_API_URL="${RR_URL:-http://127.0.0.1:$PORT/graphql}" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    python3 "$SEL" --repo-dir "$WORK" --records-dir "$RECORDS" mark-dispatched \
    --issue "$1" --action "$2" --pr "$3" --head-sha "$4" \
    > "$WORK/mout.txt" 2> "$WORK/merr.txt"
  echo $?
}

echo "== review-redrive park labels =="

printf '[%s,%s,%s,%s]\n' \
  "$(pr_entry 90 ask-901 aaaa1111)" "$(pr_entry 91 ask-902 bbbb2222)" \
  "$(pr_entry 92 ask-903 cccc3333)" "$(pr_entry 93 ask-904 dddd4444)" \
  > "$WORK/board.json"
record 90 ASK-901 aaaa1111
record 91 ASK-902 bbbb2222
record 92 ASK-903 cccc3333
record 93 ASK-904 dddd4444

RC="$(run_select)"
OUT="$(cat "$WORK/out.txt")"
ERR="$(cat "$WORK/err.txt")"

# --- the three parked issues --------------------------------------------------
for pair in "90:owner:assaf" "91:needs-scope" "92:blocked:capability"; do
  PR="${pair%%:*}"; LABEL="${pair#*:}"
  if printf '%s' "$OUT" | awk -F'\t' -v pr="$PR" '$3 == pr {found=1} END {exit !found}'; then
    bad "PR #$PR is parked by $LABEL and was still offered"
  else
    ok "PR #$PR is parked by $LABEL and is not offered"
  fi
  case "$ERR" in
    *"$LABEL"*) ok "the run names $LABEL as what stopped PR #$PR" ;;
    *) bad "nothing in stderr names $LABEL -- a silent skip is the same park, quieter" ;;
  esac
done

# --- the negative fixture: the fix must not be "skip everything" -------------
if printf '%s' "$OUT" | awk -F'\t' -v pr="93" '$3 == pr {found=1} END {exit !found}'; then
  ok "PR #93 carries none of the three and is still offered"
else
  bad "PR #93 carries none of the three and was dropped -- the fix skips everything"
fi

# --- an unreadable board is not an empty one ---------------------------------
# Same posture as GhUnavailable: if the park state cannot be read, the run must
# not decide that nothing is parked. It refuses and says so.
#
# 127.0.0.1:1 is chosen over an unroutable address on purpose: a closed port on
# loopback refuses the connection immediately, so this case cannot hang on a
# 30s socket timeout.
RC2="$(RR_URL="http://127.0.0.1:1/graphql" run_select)"
OUT2="$(cat "$WORK/out.txt")"
[ "$RC2" = "3" ] && ok "an unreadable park state exits 3, not 0" \
  || bad "an unreadable park state exited '$RC2' -- the caller reads that as a verdict"
[ -z "$OUT2" ] && ok "an unreadable park state offers nothing" \
  || bad "an unreadable park state still offered: $OUT2"

# THE OTHER HALF OF THAT CODE, and without it "return 3 for everything" passes.
# The selector reads TWO sources and the dispatcher prints a different sentence
# per source, so the codes have to discriminate: gh down is still 2, Linear down
# is 3. Both being 2 is what made a Linear outage read as a GitHub outage on the
# operator's only surface (PR #201 review, minor).
RC3="$(RR_BOARD="$WORK/no-such-board.json" run_select)"
[ "$RC3" = "2" ] && ok "a gh outage still exits 2, distinct from the park code" \
  || bad "a gh outage exited '$RC3' -- the dispatcher cannot tell the two sources apart"

# --- the claim re-reads the park: a label that lands AFTER select -------------
# FINDING 1 (PR #201 review, major). `select` and `mark-dispatched` are separate
# processes with the dispatcher's own guards running between them. The park was
# read only in the first, so a label applied in that window was invisible at the
# point the work actually launches.
#
# The sequence below IS the window, played out: offer it, park it, then claim.
echo
echo "== the park is re-read at the atomic claim =="

printf '[%s]\n' "$(pr_entry 94 ask-905 eeee5555)" > "$WORK/board.json"
record 94 ASK-905 eeee5555

# 1. unparked, so it is genuinely selectable. Without this the case below could
#    pass because the PR was never a candidate at all.
RCS="$(run_select)"
if printf '%s' "$(cat "$WORK/out.txt")" | awk -F'\t' '$3 == "94" {f=1} END {exit !f}'; then
  ok "PR #94 is offered while ASK-905 carries no park label"
else
  bad "PR #94 was not offered even unparked (rc=$RCS) -- the case below proves nothing"
fi

# 2. the label lands in the window between the offer and the claim.
set_labels '{"ASK-905": ["owner:sana", "blocked:capability"]}'
RCM="$(run_mark ASK-905 rework 94 eeee5555)"
MERR="$(cat "$WORK/merr.txt")"
[ "$RCM" = "4" ] && ok "a park that lands after select refuses the claim (rc 4)" \
  || bad "the claim returned '$RCM' -- the dispatcher launches work on a parked issue"
case "$MERR" in
  *blocked:capability*) ok "the refusal names blocked:capability as what stopped it" ;;
  *) bad "nothing in stderr names the label -- a silent refusal is unreadable in dispatch.log" ;;
esac

# 3. THE ATTEMPT MUST STILL BE UNSPENT. The flag is one attempt per PR per action
#    per head sha. Claiming and then refusing would burn it on work that never
#    ran, and lifting the park would not give it back -- the next redrive would
#    skip PR #94 for having "already had its one attempt". Lifting the park and
#    getting rc 0 is the only thing that proves the ordering.
set_labels '{"ASK-905": ["owner:sana"]}'
RCM2="$(run_mark ASK-905 rework 94 eeee5555)"
[ "$RCM2" = "0" ] && ok "the refused claim left the attempt unspent: it claims once the park lifts" \
  || bad "after the park lifted the claim returned '$RCM2' -- the refusal spent the attempt"

# 4. and the ledger claim itself still works, so the fix did not turn
#    mark-dispatched into a park check that forgot its original job.
RCM3="$(run_mark ASK-905 rework 94 eeee5555)"
[ "$RCM3" = "1" ] && ok "a second claim on the same attempt is still refused as claimed" \
  || bad "the second claim returned '$RCM3' -- the one-attempt cap is broken"

# 5. an unreadable park state at the claim fails CLOSED, with its own code.
RCM4="$(RR_URL="http://127.0.0.1:1/graphql" run_mark ASK-905 re-review 94 ffff6666)"
[ "$RCM4" = "3" ] && ok "an unreadable park state at the claim exits 3, not 0" \
  || bad "an unreadable park state at the claim exited '$RCM4' -- it would dispatch"

# --- a lookup that answers nothing ------------------------------------------
# FINDING 2 (PR #201 review round 2, minor). `graphql` raises on an `errors`
# array, so the reader only ever sees a clean response -- but a clean response
# can still say nothing about an issue. Linear answers `null` for an id it does
# not resolve, and an alias can be absent from `data` outright. Both were read
# as "no park labels found", which is the module's stated defect one layer down:
# I COULD NOT ASK is not NOTHING IS PARKED.
echo
echo "== a lookup that answers nothing is unreadable, not unparked =="

printf '[%s]\n' "$(pr_entry 95 ask-906 99996666)" > "$WORK/board.json"
record 95 ASK-906 99996666

# The discrimination first, on the same PR: without it "exit 3 whenever the
# response is not a full label set" would pass every case below.
set_labels '{"ASK-906": ["owner:sana"]}'
RCP="$(run_select)"
if printf '%s' "$(cat "$WORK/out.txt")" | awk -F'\t' '$3 == "95" {f=1} END {exit !f}'; then
  ok "PR #95 is offered while ASK-906 answers normally"
else
  bad "PR #95 was not offered on a normal answer (rc=$RCP) -- the cases below prove nothing"
fi

# THE UNIT OF REFUSAL IS THE ISSUE, NOT THE RUN (PR #201 review round 4, major).
# Round 2 raised for the whole batch on a null lookup, which is why these two
# cases used to assert rc 3. That was over-wide: the id comes off the PR (branch
# tail, else title), so ONE badly-titled PR made the reader refuse the entire
# board, every heartbeat, permanently. The property is unchanged -- an
# unverifiable park is never read as unparked -- but it is enforced against the
# candidate that could not be verified, and nothing else. With a one-PR board
# that leaves nothing to offer, which is rc 1: nothing red, not a Linear outage.
set_labels '{"ASK-906": "__null__"}'
RCN="$(run_select)"
[ "$RCN" = "1" ] && ok "a null issue lookup leaves nothing offerable (rc 1)" \
  || bad "a null issue lookup exited '$RCN' -- want 1: the candidate is dropped, the run is not"
[ -z "$(cat "$WORK/out.txt")" ] && ok "a null issue lookup offers nothing" \
  || bad "a null issue lookup still offered: $(cat "$WORK/out.txt")"
case "$(cat "$WORK/err.txt")" in
  *ASK-906*) ok "the refusal names the issue Linear did not answer for" ;;
  *) bad "nothing in stderr names ASK-906 -- the operator cannot tell which id failed" ;;
esac

set_labels '{"ASK-906": "__omit__"}'
RCO="$(run_select)"
[ "$RCO" = "1" ] && ok "an alias missing from the response leaves nothing offerable (rc 1)" \
  || bad "a missing alias exited '$RCO' -- want 1: a dropped alias drops its candidate"
[ -z "$(cat "$WORK/out.txt")" ] && ok "a missing alias offers nothing" \
  || bad "a missing alias still offered: $(cat "$WORK/out.txt")"

# THE SAME AT THE CLAIM, which is where the attempt is at stake.
set_labels '{"ASK-906": "__null__"}'
RCMN="$(run_mark ASK-906 rework 95 99996666)"
[ "$RCMN" = "3" ] && ok "a null lookup at the claim exits 3, not 0" \
  || bad "a null lookup at the claim exited '$RCMN' -- it would dispatch"

set_labels '{"ASK-906": ["owner:sana"]}'
RCMU="$(run_mark ASK-906 rework 95 99996666)"
[ "$RCMU" = "0" ] && ok "the null-lookup refusal left the attempt unspent" \
  || bad "after a readable answer the claim returned '$RCMU' -- the refusal spent the attempt"

# --- one bad id must not suppress the batch ----------------------------------
# FINDING (PR #201 review round 4, major): "One invalid title-derived issue ID
# aborts the entire batched park lookup, suppressing every valid reviewer-redrive
# candidate."
#
# THE ID IS DERIVED FROM THE PR, so it is attacker-free but not trustworthy:
# ci-redrive's attribute() takes the branch tail when it is an issue id, else the
# ONE id the title names via `\b[A-Za-z]{2,6}-\d+\b`. "convert the log writer to
# UTF-8" satisfies that pattern. So a PR nobody wrote carelessly -- just titled
# in English -- yields the identifier `UTF-8`, Linear resolves nothing for it,
# and round 2's whole-batch raise then took the reviewer redrive offline for
# every OTHER PR on the board. Not transient: that title does not heal.
#
# The fixture uses that exact title rather than a sentinel id, because the id
# under test has to be one the producer really emits (fixtures-from-producers).
echo
echo "== one unresolvable id drops its own candidate, not the batch =="

# ask-907 on the branch tail -> a normal, verifiable candidate.
# A branch tail that is NOT an issue id -> attribute() falls through to the title.
cat > "$WORK/board.json" <<EOS
[$(pr_entry 96 ask-907 77771111),
 {"number": 97, "headRefName": "sana/encoding-fix", "headRefOid": "88882222",
  "url": "https://example.invalid/pr/97",
  "title": "convert the log writer to UTF-8 (no issue id here)",
  "isDraft": false,
  "statusCheckRollup": [
    {"__typename": "StatusContext", "context": "kipi/reviewer-approved", "state": "FAILURE"},
    {"__typename": "CheckRun", "name": "validate", "status": "COMPLETED", "conclusion": "SUCCESS"}
  ]}]
EOS
record 96 ASK-907 77771111
record 97 UTF-8 88882222

set_labels '{"ASK-907": ["owner:sana"], "UTF-8": "__null__"}'
RCB="$(run_select)"
OUTB="$(cat "$WORK/out.txt")"; ERRB="$(cat "$WORK/err.txt")"
[ "$RCB" = "0" ] && ok "a batch holding one unresolvable id still answers (rc 0)" \
  || bad "the batch exited '$RCB' -- one bad PR title suppressed every valid candidate"
if printf '%s' "$OUTB" | awk -F'\t' '$3 == "96" {f=1} END {exit !f}'; then
  ok "the valid candidate PR #96 survives a sibling Linear cannot resolve"
else
  bad "PR #96 was suppressed by PR #97's unresolvable id -- the finding, unfixed"
fi
if printf '%s' "$OUTB" | awk -F'\t' '$3 == "97" {f=1} END {exit !f}'; then
  bad "PR #97 was offered on a park nobody could verify"
else
  ok "PR #97, whose park state is unknown, is not offered"
fi
case "$ERRB" in
  *UTF-8*) ok "the run names UTF-8 as the id it could not resolve" ;;
  *) bad "nothing in stderr names UTF-8 -- the operator cannot find the mistitled PR" ;;
esac

# THE OTHER DIRECTION, and without it "drop the ones you cannot read" passes by
# reading nothing. A batch-level failure is still a batch-level refusal: the
# whole response is missing, so no candidate in it was verified.
RCB2="$(RR_URL="http://127.0.0.1:1/graphql" run_select)"
[ "$RCB2" = "3" ] && ok "a Linear outage still refuses the whole batch (rc 3)" \
  || bad "a Linear outage exited '$RCB2' -- per-issue isolation swallowed a real outage"
[ -z "$(cat "$WORK/out.txt")" ] && ok "a Linear outage offers nothing from the batch" \
  || bad "a Linear outage still offered: $(cat "$WORK/out.txt")"

# AND A RESPONSE THAT MIS-FILES ONE ALIAS IS ALSO BATCH-WIDE, deliberately: a
# bad INPUT id makes one issue unknown, but an alias answering about a different
# issue means the response mapping itself cannot be trusted, so nothing in it may
# be filed. Two failure shapes, two blast radii, and the split is the whole fix.
set_labels '{"ASK-907": "__wrong__", "UTF-8": "__null__"}'
RCB3="$(run_select)"
[ "$RCB3" = "3" ] && ok "an alias answering for another issue refuses the batch (rc 3)" \
  || bad "a mis-filed alias exited '$RCB3' -- park state was filed under the wrong issue"

# --- park-check: the read-only answer the dispatcher asks for ----------------
# FINDING (PR #201 review round 4, major): "Park labels do not stop the
# higher-priority red-CI redrive, so a parked issue with red CI is still
# dispatched." kipi-dispatch.sh runs ci-redrive.py FIRST and only reaches the
# reviewer redrive when it offered nothing, so everything this file proves about
# select/mark-dispatched was bypassed whenever a parked issue also had red CI.
#
# The dispatcher needs the park answer for an issue it did not select here, so
# this is a subcommand and not a flag on select. READ-ONLY: it must never touch
# the attempts ledger, or asking the question would spend the answer.
echo
echo "== park-check: one issue, one answer, no writes =="

run_check() {   # run_check <issue>
  env PATH="$BIN:$PATH" KIPI_NOTIFY="$BIN/notify.sh" KIPI_ATTEMPTS="$LEDGER" \
    KIPI_LINEAR_API_URL="${RR_URL:-http://127.0.0.1:$PORT/graphql}" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    python3 "$SEL" park-check --issue "$1" \
    > "$WORK/cout.txt" 2> "$WORK/cerr.txt"
  echo $?
}

set_labels '{"ASK-910": ["owner:sana"],
             "ASK-911": ["owner:sana", "owner:assaf"],
             "ASK-912": ["owner:sana", "blocked:capability"],
             "ASK-913": "__null__"}'

LEDGER_BEFORE="$(cat "$LEDGER" 2>/dev/null || echo absent)"

RCC="$(run_check ASK-910)"
[ "$RCC" = "0" ] && ok "an unparked issue answers 0 -- the redrive may proceed" \
  || bad "an unparked issue exited '$RCC' (stderr: $(cat "$WORK/cerr.txt"))"

RCC2="$(run_check ASK-911)"
[ "$RCC2" = "4" ] && ok "an issue parked by owner:assaf answers 4" \
  || bad "a parked issue exited '$RCC2' -- the dispatcher would redrive it"
case "$(cat "$WORK/cout.txt")" in
  *owner:assaf*) ok "park-check prints the label on stdout so the say line can name it" ;;
  *) bad "park-check printed no label -- dispatch.log would say 'parked' and not by what" ;;
esac

RCC3="$(run_check ASK-912)"
[ "$RCC3" = "4" ] && ok "an issue parked by blocked:capability answers 4" \
  || bad "blocked:capability exited '$RCC3' -- the sharpest case, an agent that cannot finish"

RCC4="$(run_check ASK-913)"
[ "$RCC4" = "3" ] && ok "an id Linear cannot resolve answers 3, not 0" \
  || bad "an unresolvable id exited '$RCC4' -- the dispatcher would read that as unparked"

RCC5="$(RR_URL="http://127.0.0.1:1/graphql" run_check ASK-910)"
[ "$RCC5" = "3" ] && ok "a Linear outage answers 3, not 0" \
  || bad "a Linear outage exited '$RCC5' -- an unreadable source read as permission"

LEDGER_AFTER="$(cat "$LEDGER" 2>/dev/null || echo absent)"
[ "$LEDGER_BEFORE" = "$LEDGER_AFTER" ] \
  && ok "five park-checks wrote nothing to the attempts ledger" \
  || bad "park-check moved the ledger -- asking the question spent an attempt"

echo
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
