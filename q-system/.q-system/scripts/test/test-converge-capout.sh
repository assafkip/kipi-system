#!/usr/bin/env bash
# Reproducer + acceptance criteria for ASK-871: a converge cap-out is invisible
# to the redrives, so a stuck issue restarts forever.
#
# THE DEFECT IT CLOSES, measured 2026-08-16. ASK-830 ran six converge rounds and
# five Opus reviews in one morning and produced nothing mergeable:
#
#   15:59:53Z converge[ASK-830] STOP exit-2: hit the 3-round cap still at 'REQUEST CHANGES'
#   16:14:01Z red-CI redrive: handing ASK-830 back to its agent ahead of the fresh pick
#
# Fourteen minutes between "I give up" and "here, do it again". Both bounding
# mechanisms worked; they did not COMPOSE. converge.sh's cap-out announced itself
# to a human only -- a `say` line and a Slack ping -- and wrote nothing a machine
# reads, so the redrives had no way to learn the rounds were already spent.
#
# THE PROPERTY UNDER TEST IS THE COMPOSITION, and it is asserted in both
# directions on purpose. A gate that skips a capped issue is satisfied by a WALL
# -- code that skips everything -- and a wall converts today's runaway into
# silent parking, which is the strictly worse failure the issue's blast-radius
# note names. So every skip case is paired with a byte-identical case whose only
# difference is the cap-out record, and the un-capped twin must still be offered.
#
# BOTH REDRIVES, not just the one the DoR named. The 16:14:01Z line above is
# kipi-dispatch.sh:1141, which is the ci-redrive.py call site -- so gating only
# review-redrive.py would leave the measured incident live. Ci-redrive's
# exclusion of the reviewer verdict slots is untouched (that is the ASK-871
# not-doing list, and PR #73 is its scar); what is added is one more reason to
# refuse, read from the same ledger.
#
# Isolation: KIPI_STATE_DIR, KIPI_ATTEMPTS, KIPI_CONVERGE_WORKER, KIPI_NOTIFY,
# KIPI_GH and KIPI_PS all point into a mktemp dir. No real worker, no real gh,
# no real process table, no live Linear, no Slack.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
CONV="$ROOT/q-system/.q-system/scripts/converge.sh"
LEDGER="$ROOT/q-system/.q-system/scripts/attempts-ledger.py"
REVIEW_REDRIVE="$ROOT/q-system/.q-system/scripts/review-redrive.py"
CI_REDRIVE="$ROOT/q-system/.q-system/scripts/ci-redrive.py"
for f in "$CONV" "$LEDGER" "$REVIEW_REDRIVE" "$CI_REDRIVE"; do
  [ -f "$f" ] || { echo "FATAL: missing $f" >&2; exit 1; }
done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

mkdir -p "$WORK/bin" "$WORK/state/pr-reviews" "$WORK/records"
ATTEMPTS="$WORK/state/linear-worker-attempts.json"
PAGES="$WORK/pages.txt"; : > "$PAGES"

# The notify sink, stubbed for EVERY case. converge.sh pages on cap-out and both
# redrives escalate from inside their select paths; with no stub that is the real
# slack-notify.sh, quiet only because no webhook resolves on this machine.
# Quiet-because-unconfigured is not isolation.
cat > "$WORK/bin/notify.sh" <<EOS
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$PAGES"
EOS
chmod +x "$WORK/bin/notify.sh"

capout_of() {   # capout_of <issue> <key>
  python3 "$LEDGER" "$ATTEMPTS" get "$1" "$2" "" 2>/dev/null
}

echo "== converge cap-out is recorded where a machine reads it =="

# --- the converge half: same fake-worker harness test-converge.sh uses --------
cat > "$WORK/bin/gh" <<'EOS'
#!/usr/bin/env bash
case "${1:-} ${2:-}" in
  "pr list") cat "$FAKE_PR_FILE" 2>/dev/null ;;
  "pr view") cat "$FAKE_SHA_FILE" 2>/dev/null ;;
esac
exit 0
EOS
chmod +x "$WORK/bin/gh"

cat > "$WORK/bin/fakeworker" <<'EOS'
#!/usr/bin/env bash
N=$(( $(cat "$FAKE_ROUND_FILE" 2>/dev/null || echo 0) + 1 ))
echo "$N" > "$FAKE_ROUND_FILE"
ENTRY="$(echo "$FAKE_SEQ" | cut -d'|' -f"$N")"
[ -n "$ENTRY" ] || exit 0
V="${ENTRY%%;*}"; S="${ENTRY##*;}"
echo "$S" > "$FAKE_SHA_FILE"
PR="$(cat "$FAKE_PR_FILE")"
python3 -c "
import json,sys
json.dump({'pr':int(sys.argv[1]),'issue':sys.argv[4],'verdict':sys.argv[2],
           'review':'x','ts':'t'}, open(sys.argv[3],'w'))
" "$PR" "$V" "$FAKE_STATE/pr-reviews/pr-$PR.verdict.json" "$FAKE_ISSUE"
exit 0
EOS
chmod +x "$WORK/bin/fakeworker"

run_converge() {   # run_converge <issue> <pr> <seq> <max-rounds>
  echo "$2" > "$WORK/pr"; echo "0" > "$WORK/round"; : > "$WORK/sha"
  rm -f "$WORK/state/pr-reviews"/*.verdict.json
  env PATH="$WORK/bin:$PATH" \
      KIPI_STATE_DIR="$WORK/state" \
      KIPI_CONVERGE_WORKER="$WORK/bin/fakeworker" \
      KIPI_NOTIFY="$WORK/bin/notify.sh" \
      FAKE_STATE="$WORK/state" FAKE_ISSUE="$1" \
      FAKE_PR_FILE="$WORK/pr" FAKE_SHA_FILE="$WORK/sha" FAKE_ROUND_FILE="$WORK/round" \
      FAKE_SEQ="$3" \
    bash "$CONV" --issue "$1" --max-rounds "$4" > "$WORK/conv.out" 2>&1
  echo $?
}

RC="$(run_converge ASK-9871 301 "REQUEST CHANGES;s1|REQUEST CHANGES;s2|REQUEST CHANGES;s3|REQUEST CHANGES;s4" 3)"
[ "$RC" = "2" ] && ok "a never-approving reviewer still hits the round cap (exit 2)" \
  || bad "cap-out did not exit 2, got rc=$RC: $(cat "$WORK/conv.out")"

[ "$(capout_of ASK-9871 capout)" = "True" ] \
  && ok "the cap-out is written to the attempts ledger, where a machine reads it" \
  || bad "no cap-out record for ASK-9871 after exit 2 -- the redrives cannot see it"

CAPOUT_WHY="$(capout_of ASK-9871 capout_why)"
case "$CAPOUT_WHY" in
  *"3-round cap"*) ok "the record says WHY: $CAPOUT_WHY" ;;
  *) bad "capout_why does not name the round cap: '$CAPOUT_WHY'" ;;
esac
[ -n "$(capout_of ASK-9871 capout_at)" ] \
  && ok "the record is timestamped" || bad "capout_at is empty"

# The founder-facing half. The Slack line is the ONE alarm for this fact, and a
# park a human cannot clear is a permanent park -- so the page has to carry the
# clearing command, not just the news.
grep -q "clear-capout" "$PAGES" \
  && ok "the cap-out page names the command that clears the park" \
  || bad "the page does not tell the founder how to un-park it: $(cat "$PAGES")"

# THE PAIRED NEGATIVE. Without it, "always record a cap-out" passes every assert
# above and parks every converged issue on the board.
RC="$(run_converge ASK-9872 302 "APPROVE;s1" 3)"
[ "$RC" = "1" ] && [ -z "$(capout_of ASK-9872 capout)" ] \
  && ok "a converge that reaches its goal records NO cap-out" \
  || bad "APPROVE run (rc=$RC) left capout='$(capout_of ASK-9872 capout)' -- it parks healthy issues"

echo "== the redrives refuse an issue whose cap-out is uncleared =="

# --- the board, stubbed at the gh seam ---------------------------------------
cat > "$WORK/bin/gh-board" <<'EOS'
#!/usr/bin/env bash
cat "$BOARD"
EOS
chmod +x "$WORK/bin/gh-board"

# Two PRs identical in every field that either selector reads, except the issue
# id -- which is the only thing the ledger is keyed on.
reviewer_pr() {   # reviewer_pr <number> <issue-lower> <sha>
  cat <<EOS
{"number": $1, "headRefName": "sana/$2", "headRefOid": "$3",
 "url": "https://example.invalid/pr/$1", "title": "work ($(echo "$2" | tr a-z A-Z))",
 "isDraft": false,
 "statusCheckRollup": [
   {"__typename": "StatusContext", "context": "kipi/reviewer-approved", "state": "FAILURE"}
 ]}
EOS
}
ci_pr() {         # ci_pr <number> <issue-lower> <sha>
  cat <<EOS
{"number": $1, "headRefName": "sana/$2", "headRefOid": "$3",
 "url": "https://example.invalid/pr/$1", "title": "work ($(echo "$2" | tr a-z A-Z))",
 "isDraft": false,
 "statusCheckRollup": [
   {"__typename": "CheckRun", "name": "validate", "status": "COMPLETED", "conclusion": "FAILURE"}
 ]}
EOS
}
record() {        # record <pr> <issue> <sha>
  python3 - "$WORK/records/pr-$1.verdict.json" "$1" "$2" "$3" <<'PY'
import json, sys
out, pr, issue, sha = sys.argv[1:5]
json.dump({"pr": int(pr), "issue": issue, "verdict": "REQUEST CHANGES",
           "stated": "REQUEST CHANGES", "derived": "", "source": "findings",
           "engine": "codex", "round": 1, "review": "", "head_sha": sha,
           "usable": True, "ts": "now"}, open(out, "w"), indent=2)
PY
}

# KIPI_PS is a table with nothing of ours in it: no converge and no reviewer is
# live, so neither in-flight gate can be what suppresses an offer.
select_review() {
  env BOARD="$WORK/board.json" KIPI_GH="$WORK/bin/gh-board" \
      KIPI_ATTEMPTS="$ATTEMPTS" KIPI_NOTIFY="$WORK/bin/notify.sh" \
      KIPI_PS="echo /usr/sbin/syslogd" \
    python3 "$REVIEW_REDRIVE" --repo-dir "$WORK" --records-dir "$WORK/records" \
      select 2>"$WORK/rr.err"
}
select_ci() {
  env BOARD="$WORK/board.json" KIPI_GH="$WORK/bin/gh-board" \
      KIPI_ATTEMPTS="$ATTEMPTS" KIPI_NOTIFY="$WORK/bin/notify.sh" \
      KIPI_PS="echo /usr/sbin/syslogd" \
    python3 "$CI_REDRIVE" --repo-dir "$WORK" redrive 2>"$WORK/ci.err"
}

# --- review-redrive: the capped issue is FIRST on the board ------------------
# Order matters. The selector offers the first eligible candidate and stops, so
# putting the capped one first means a missing gate offers ASK-8710 (fail) and a
# wall offers nothing at all (also fail). Only a real gate yields ASK-8711.
printf '[%s,%s]\n' "$(reviewer_pr 310 ask-8710 aaaa1111)" \
                   "$(reviewer_pr 311 ask-8711 bbbb2222)" > "$WORK/board.json"
record 310 ASK-8710 aaaa1111
record 311 ASK-8711 bbbb2222
python3 "$LEDGER" "$ATTEMPTS" record-capout ASK-8710 \
  "hit the 3-round cap still at 'REQUEST CHANGES' on PR #310" >/dev/null 2>&1

PICK="$(select_review | cut -f2)"
[ "$PICK" = "ASK-8711" ] \
  && ok "review-redrive skips the capped issue and still offers its un-capped twin" \
  || bad "review-redrive offered '$PICK', want ASK-8711 (empty = a wall, ASK-8710 = no gate)"
grep -q "ASK-8710" "$WORK/rr.err" && grep -q "clear-capout" "$WORK/rr.err" \
  && ok "review-redrive says WHY it skipped and how to un-park it" \
  || bad "review-redrive skipped silently: $(cat "$WORK/rr.err")"

# --- ci-redrive: the same pair, red on CI rather than on the verdict slot -----
printf '[%s,%s]\n' "$(ci_pr 320 ask-8712 cccc3333)" \
                   "$(ci_pr 321 ask-8713 dddd4444)" > "$WORK/board.json"
python3 "$LEDGER" "$ATTEMPTS" record-capout ASK-8712 \
  "hit the 3-round cap still at 'REQUEST CHANGES' on PR #320" >/dev/null 2>&1

PICK="$(select_ci | cut -f1)"
[ "$PICK" = "ASK-8713" ] \
  && ok "ci-redrive skips the capped issue and still offers its un-capped twin" \
  || bad "ci-redrive offered '$PICK', want ASK-8713 -- this is the path that re-entered ASK-830"
grep -q "ASK-8712" "$WORK/ci.err" && grep -q "clear-capout" "$WORK/ci.err" \
  && ok "ci-redrive says WHY it skipped and how to un-park it" \
  || bad "ci-redrive skipped silently: $(cat "$WORK/ci.err")"

echo "== a human clears the park, and only a human =="

# The park must be exitable, or the fix trades a runaway for a permanent stall.
python3 "$LEDGER" "$ATTEMPTS" clear-capout ASK-8710 >/dev/null 2>&1
[ -z "$(capout_of ASK-8710 capout)" ] \
  && ok "clear-capout removes the record" \
  || bad "capout survived clear-capout: '$(capout_of ASK-8710 capout)'"

printf '[%s]\n' "$(reviewer_pr 310 ask-8710 aaaa1111)" > "$WORK/board.json"
PICK="$(select_review | cut -f2)"
[ "$PICK" = "ASK-8710" ] \
  && ok "once cleared, the issue is redriven again -- the park is not permanent" \
  || bad "cleared issue was still refused: '$PICK'"

# And clearing is per issue, not a global reset: the OTHER capped issue stays parked.
printf '[%s]\n' "$(ci_pr 320 ask-8712 cccc3333)" > "$WORK/board.json"
[ -z "$(select_ci)" ] \
  && ok "clearing one issue does not un-park the others" \
  || bad "clear-capout ASK-8710 also released ASK-8712"

echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
