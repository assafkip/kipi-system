#!/usr/bin/env bash
# Pairs with review-redrive.py (ASK-352): a PR whose REVIEWER refused has no
# selector that re-enters it, and `failure` on that slot means two opposite
# things.
#
# THE PROPERTY UNDER TEST is the DISCRIMINATION, not either branch alone. A
# selector that answers `rework` for everything passes any test that only checks
# #82; a selector that answers `re-review` for everything passes any test that
# only checks #80. Every case below is therefore paired against its opposite,
# and the pairs are built to be byte-identical everywhere except the one field
# that is supposed to decide.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SEL="$REPO_ROOT/q-system/.q-system/scripts/review-redrive.py"
[ -f "$SEL" ] || { echo "FATAL: review-redrive.py not found at $SEL" >&2; exit 1; }
SEL="${REVIEW_REDRIVE_UNDER_TEST:-$SEL}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

RECORDS="$WORK/records"; mkdir -p "$RECORDS"
BIN="$WORK/bin"; mkdir -p "$BIN"

# --- the notify sink, stubbed for EVERY case in this file --------------------
# NOT just for the escalation cases. review-redrive escalates from inside
# `select`, so any case that reaches a spent attempt calls the sink. With no
# stub that is the REAL slack-notify.sh -- a live data path in a test suite,
# quiet only because no webhook resolves on this machine. Quiet-because-
# unconfigured is not isolation; it is a leak waiting for the day a webhook
# exists. The fable-discipline lint blocks this class, and it caught me here.
PAGES="$WORK/pages.txt"; : > "$PAGES"
cat > "$BIN/notify.sh" <<EOS
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$PAGES"
EOS
chmod +x "$BIN/notify.sh"
pages_count() { wc -l < "$PAGES" | tr -d ' '; }

# --- the board, stubbed at the gh seam --------------------------------------
# review-redrive reads PRs through ci-redrive's list_prs, which shells `gh`. The
# stub prints whatever board the case under test set up, so no case can reach
# GitHub and no case depends on the real board's state at the moment it runs.
cat > "$BIN/gh" <<'EOS'
#!/usr/bin/env bash
cat "$BOARD"
EOS
chmod +x "$BIN/gh"

# A PR entry with a failing reviewer slot. Everything except pr/branch/sha is
# fixed, so a difference in outcome can only come from the verdict record.
pr_entry() {   # pr_entry <number> <issue-lower> <sha>
  cat <<EOS
{"number": $1, "headRefName": "sana/$2", "headRefOid": "$3",
 "url": "https://example.invalid/pr/$1", "title": "work ($(echo "$2" | tr a-z A-Z))",
 "isDraft": false,
 "statusCheckRollup": [
   {"__typename": "StatusContext", "context": "kipi/codex-approved", "state": "FAILURE"},
   {"__typename": "CheckRun", "name": "validate", "status": "COMPLETED", "conclusion": "SUCCESS"}
 ]}
EOS
}

record() {   # record <pr> <verdict> <stated> <usable-json> <head-sha> [review-file]
  python3 - "$RECORDS/pr-$1.verdict.json" "$1" "$2" "$3" "$4" "$5" "${6:-}" <<'PY'
import json, sys
out, pr, verdict, stated, usable, sha, review = sys.argv[1:8]
rec = {"pr": int(pr), "issue": "ASK-TEST", "verdict": verdict, "stated": stated,
       "derived": "", "source": "findings", "engine": "codex",
       "round": 1, "review": review, "head_sha": sha, "ts": "now"}
if usable != "omit":
    rec["usable"] = (usable == "true")
json.dump(rec, open(out, "w"), indent=2)
PY
}

select_all() {
  env PATH="$BIN:$PATH" BOARD="$WORK/board.json" KIPI_NOTIFY="$BIN/notify.sh" \
    python3 "$SEL" --repo-dir "$WORK" --records-dir "$RECORDS" select --all 2>/dev/null
}
action_for() {   # action_for <pr>
  select_all | awk -F'\t' -v pr="$1" '$3 == pr {print $1}'
}

echo "== review-redrive =="

# --- pair 1: the #80 / #82 collision, the reason this script exists ----------
# BOTH records say verdict REQUEST CHANGES and BOTH say stated REQUEST CHANGES,
# because #80's stated verdict was read out of the prompt's own echoed grading
# rule. The ONLY difference is `usable`. If the selector reads the verdict, or
# the status, both come out the same and one of them is wrong.
printf '[%s,%s]\n' "$(pr_entry 80 ask-317 aaaa1111)" "$(pr_entry 82 ask-315 bbbb2222)" > "$WORK/board.json"
record 80 "REQUEST CHANGES" "REQUEST CHANGES" false aaaa1111
record 82 "REQUEST CHANGES" "REQUEST CHANGES" true  bbbb2222
A80="$(action_for 80)"; A82="$(action_for 82)"
[ "$A80" = "re-review" ] && ok "a phantom REQUEST CHANGES routes to re-review (#80 shape)" \
  || bad "phantom REQUEST CHANGES routed to '$A80', want re-review"
[ "$A82" = "rework" ] && ok "a real REQUEST CHANGES routes to rework (#82 shape)" \
  || bad "real REQUEST CHANGES routed to '$A82', want rework"
[ -n "$A80" ] && [ "$A80" != "$A82" ] && ok "identical verdicts, opposite actions -- usable is what decided" \
  || bad "both routed to '$A80' -- the selector is not discriminating"

# --- pair 2: an unusable APPROVE is still a review that never ran ------------
# 11 merged PRs carried exactly this. An approval nobody wrote must not read as
# terminal just because the word is APPROVE.
printf '[%s,%s]\n' "$(pr_entry 60 ask-260 cccc3333)" "$(pr_entry 67 ask-267 dddd4444)" > "$WORK/board.json"
record 60 "APPROVE" "REQUEST CHANGES" false cccc3333
record 67 "APPROVE WITH NITS" "APPROVE WITH NITS" true dddd4444
A60="$(action_for 60)"; A67="$(action_for 67)"
[ "$A60" = "re-review" ] && ok "an unusable APPROVE routes to re-review" \
  || bad "unusable APPROVE routed to '$A60', want re-review"
[ -z "$A67" ] && ok "a usable approval is terminal here and is not offered" \
  || bad "usable approval routed to '$A67' -- this script must not touch the merge side"

# --- pair 3: drift outranks the verdict -------------------------------------
# Same usable record, same REQUEST CHANGES; only the head sha differs from what
# was reviewed. A verdict about a diff that is no longer there is not a spec.
printf '[%s,%s]\n' "$(pr_entry 90 ask-290 eeee5555)" "$(pr_entry 91 ask-291 ffff6666)" > "$WORK/board.json"
record 90 "REQUEST CHANGES" "REQUEST CHANGES" true 0000dead
record 91 "REQUEST CHANGES" "REQUEST CHANGES" true ffff6666
A90="$(action_for 90)"; A91="$(action_for 91)"
[ "$A90" = "re-review" ] && ok "a verdict at a stale sha routes to re-review" \
  || bad "stale-sha verdict routed to '$A90', want re-review"
[ "$A91" = "rework" ] && ok "the same verdict at the current sha routes to rework" \
  || bad "current-sha verdict routed to '$A91', want rework"

# --- case 4: no record at all is ABSENT and belongs to another issue ---------
# The refusal is the point. Manufacturing a review for a PR whose producer never
# ran would hide the missing producer, which is the harder bug (ASK-318).
#
# THE RECORDLESS PR SHARES ITS BOARD WITH A NORMAL ONE, AND THAT IS THE ASSERTION.
# The first cut put PR #95 on a board by itself and asserted the output was
# EMPTY. A mutant that dropped the `record is None` guard SURVIVED it: passing
# None into classify() raises, the whole select run dies, and a dead run prints
# exactly the same empty output as a correct skip. Absence is not evidence of a
# mechanism. With #97 alongside, the skip has to be a SKIP -- the run must
# survive #95 and still reach #97 -- so a crash now fails the case instead of
# satisfying it.
printf '[%s,%s]\n' "$(pr_entry 95 ask-295 7777aaaa)" "$(pr_entry 97 ask-297 7777bbbb)" > "$WORK/board.json"
rm -f "$RECORDS/pr-95.verdict.json"
record 97 "REQUEST CHANGES" "REQUEST CHANGES" true 7777bbbb
A95="$(action_for 95)"; A97="$(action_for 97)"
[ -z "$A95" ] && ok "a failing slot with NO verdict record is left to ASK-318" \
  || bad "absent record routed to '$A95' -- it must be left alone"
[ "$A97" = "rework" ] && ok "the recordless PR is SKIPPED, not fatal -- the run reaches #97" \
  || bad "after the recordless PR the run yielded '$A97' for #97 -- it died instead of skipping"

# --- case 5: a green reviewer slot is never offered --------------------------
# Guards against a selector keyed on the record alone: a stale REQUEST CHANGES
# record next to a slot that has since gone green must not re-enter the PR.
cat > "$WORK/board.json" <<'EOS'
[{"number": 96, "headRefName": "sana/ask-296", "headRefOid": "8888bbbb",
  "url": "https://example.invalid/pr/96", "title": "work (ASK-296)", "isDraft": false,
  "statusCheckRollup": [
    {"__typename": "StatusContext", "context": "kipi/codex-approved", "state": "SUCCESS"}]}]
EOS
record 96 "REQUEST CHANGES" "REQUEST CHANGES" true 8888bbbb
A96="$(action_for 96)"
[ -z "$A96" ] && ok "a green reviewer slot is not re-entered on a stale record" \
  || bad "green slot routed to '$A96' -- the live status must win over the record"

# --- case 6: a legacy record with no usable key is probed, not assumed -------
# Records written before ASK-352 carry no key. The answer comes from the LIB
# against the real review file; a missing file is UNKNOWN and errs to re-review.
printf '[%s,%s]\n' "$(pr_entry 40 ask-240 9999cccc)" "$(pr_entry 41 ask-241 aaaadddd)" > "$WORK/board.json"
cat > "$WORK/phantom-legacy.md" <<'EOS'
FINDINGS:
severity|one-sentence claim|file:line
END FINDINGS
EOS
cat > "$WORK/real-legacy.md" <<'EOS'
FINDINGS:
major|the walker skips the exclusion set|walker.py:88
END FINDINGS
EOS
record 40 "REQUEST CHANGES" "REQUEST CHANGES" omit 9999cccc "$WORK/phantom-legacy.md"
record 41 "REQUEST CHANGES" "REQUEST CHANGES" omit aaaadddd "$WORK/real-legacy.md"
A40="$(action_for 40)"; A41="$(action_for 41)"
[ "$A40" = "re-review" ] && ok "a legacy record whose review file is a template echo -> re-review" \
  || bad "legacy phantom routed to '$A40', want re-review"
[ "$A41" = "rework" ] && ok "a legacy record whose review file has real findings -> rework" \
  || bad "legacy real review routed to '$A41', want rework"

record 42 "REQUEST CHANGES" "REQUEST CHANGES" omit bbbbeeee "$WORK/gone.md"
printf '[%s]\n' "$(pr_entry 42 ask-242 bbbbeeee)" > "$WORK/board.json"
A42="$(action_for 42)"
[ "$A42" = "re-review" ] && ok "a legacy record whose review file is gone -> re-review, not a guess" \
  || bad "vanished review file routed to '$A42', want re-review"

# --- case 7: the SINGLE-PICK path, and it must not write ---------------------
# THE PATH THE DISPATCHER ACTUALLY USES, and every case above missed it. They
# all call `select --all`, which returns before the ledger is ever touched, so
# 13 green cases said nothing about the code path that runs in production.
#
# THE DEFECT THIS PINS. `select` was documented read-only and asked the ledger
# "has this been claimed?" through ci-redrive's `ledger_recorded` -- which is a
# WRITE wearing a reader's name: it runs claim-flag and answers True on rc 0
# (just claimed) as well as rc 1 (already claimed). So the FIRST ever invocation
# claimed every candidate and then skipped all of them for having been claimed.
# Measured live before the fix: 14 PRs, all reported "already had its one
# attempt", nothing offered, on a ledger where none of them appeared. A selector
# that silently offers nothing looks exactly like the park it exists to end.
LEDGER="$WORK/attempts.json"; echo '{}' > "$LEDGER"
select_one() {
  env PATH="$BIN:$PATH" BOARD="$WORK/board.json" KIPI_ATTEMPTS="$LEDGER" \
      KIPI_NOTIFY="$BIN/notify.sh" \
    python3 "$SEL" --repo-dir "$WORK" --records-dir "$RECORDS" select 2>/dev/null
}
printf '[%s]\n' "$(pr_entry 98 ask-298 cccc9999)" > "$WORK/board.json"
record 98 "REQUEST CHANGES" "REQUEST CHANGES" true cccc9999

PICK1="$(select_one)"
[ "$(printf '%s' "$PICK1" | cut -f1)" = "rework" ] && ok "select (single pick) offers the candidate" \
  || bad "select offered '$PICK1' -- the dispatcher's own path returns nothing"

LEDGER_AFTER="$(cat "$LEDGER")"
[ "$LEDGER_AFTER" = '{}' ] && ok "select wrote NOTHING to the ledger -- the offer is not the claim" \
  || bad "select mutated the ledger: $LEDGER_AFTER"

# Read-only means REPEATABLE. A select that claimed on the way past would offer
# once and then go silent forever, which is how the defect hid: the first run
# looked fine in isolation.
PICK2="$(select_one)"
[ "$PICK2" = "$PICK1" ] && ok "a second select offers the same pick -- reading did not consume it" \
  || bad "second select offered '$PICK2' after '$PICK1' -- select is consuming its own candidates"

# And the claim, when it is made deliberately, DOES suppress the next offer.
# Without this the case above is satisfied by a cap that never fires at all.
env KIPI_ATTEMPTS="$LEDGER" python3 "$SEL" mark-dispatched \
  --issue ASK-298 --action rework --pr 98 --head-sha cccc9999 >/dev/null 2>&1
[ -z "$(select_one)" ] && ok "after mark-dispatched the pick is suppressed -- the cap is real" \
  || bad "the pick survived mark-dispatched -- the cap never fires"

# --- case 8: a spent attempt that is STILL failing escalates, exactly once ----
# Codex found this on PR #91 (major): the spent-attempt branch wrote a stderr
# line and moved on, so a PR that got its one redrive and stayed failing was
# silently ignored forever. That is the terminal-state-with-no-consumer defect
# this selector exists to kill, reintroduced inside the fix for it. A cap with no
# escalation is a quieter version of the 29-hour park.
#
# ASSERTED ON THE PAGE ITSELF, not on stderr. "It escalated OR it logged
# something" passes on the weak half and never tests the alarm; the notify sink
# is the alarm's own recorder, so that is what is counted.
# Case 7's suppression check already reached the spent-attempt branch once, so
# the page for THIS pr/action/sha is expected to be spent by now. Asserting an
# absolute count of 1 here would be asserting the order the cases happen to run
# in; the property is that the sink saw the page exactly once in total.
select_one >/dev/null
[ "$(pages_count)" = "1" ] && ok "a spent attempt still failing pages once" \
  || bad "spent attempt produced $(pages_count) pages, want 1"
grep -q "PR #98" "$PAGES" && grep -q "rework" "$PAGES" \
  && ok "the page names the PR and which action was already spent" \
  || bad "the page does not name the PR and the spent action: $(cat "$PAGES")"

# The dispatcher hits this state every heartbeat for as long as the PR sits
# failing. A page per run is a page every 15 minutes about one unchanged fact.
select_one >/dev/null
[ "$(pages_count)" = "1" ] && ok "a second pass does NOT page again -- once per PR per action per sha" \
  || bad "escalation paged $(pages_count) times across two passes"

# A new head sha is new information and earns its own attempt AND its own page.
# Without this the cap is permanent: a PR that pushes a real fix could never be
# re-entered and would never be reported again either.
python3 - "$WORK/board.json" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
open(p, "w").write(s.replace("cccc9999", "dddd0000"))
PY
record 98 "REQUEST CHANGES" "REQUEST CHANGES" true dddd0000
PICK3="$(select_one)"
[ "$(printf '%s' "$PICK3" | cut -f1)" = "rework" ] \
  && ok "a new head sha is offered again -- the cap is per sha, not permanent" \
  || bad "after a push the PR was not re-offered: '$PICK3'"

# --- case 9: a draft is the author saying not yet ----------------------------
# The docstring claimed drafts were excluded and the code did not do it (codex
# round 2 on PR #91). Paired against a non-draft that is otherwise identical, so
# a selector that ignores the flag cannot pass by luck, and a selector that
# returns nothing at all cannot pass either.
python3 - "$WORK/board.json" <<'PYEOF'
import json, sys
draft = {"number": 99, "headRefName": "sana/ask-299", "headRefOid": "eeee1111",
         "url": "https://example.invalid/pr/99", "title": "wip (ASK-299)",
         "isDraft": True,
         "statusCheckRollup": [{"__typename": "StatusContext",
                                "context": "kipi/codex-approved", "state": "FAILURE"}]}
ready = dict(draft, number=100, headRefName="sana/ask-300", headRefOid="eeee2222",
             url="https://example.invalid/pr/100", title="done (ASK-300)", isDraft=False)
json.dump([draft, ready], open(sys.argv[1], "w"))
PYEOF
record 99  "REQUEST CHANGES" "REQUEST CHANGES" true eeee1111
record 100 "REQUEST CHANGES" "REQUEST CHANGES" true eeee2222
A99="$(action_for 99)"; A100="$(action_for 100)"
[ -z "$A99" ] && ok "a draft PR is not re-entered"   || bad "draft PR routed to '$A99' -- a draft is the author saying not yet"
[ "$A100" = "rework" ] && ok "the non-draft beside it still is -- the flag is what decided"   || bad "non-draft routed to '$A100' -- the filter is eating everything"

echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
