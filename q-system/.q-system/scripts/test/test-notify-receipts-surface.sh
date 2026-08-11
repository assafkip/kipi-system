#!/bin/bash
# Pairs with: notify-receipts-surface.py (the reader half of the notify sink).
#
# THE DEFECT THIS SUITE EXISTS FOR (PR #72 review, major). slack-notify.sh wrote
# every outcome to notify-receipts.jsonl and its own comment claimed
# "notify-receipts-surface.py reads it at SessionStart". That file did not exist
# and nothing in the repo opened the ledger. Three dispatch pages that mean the
# Linear loop is DEAD -- repo-missing, gh-missing, budget-day -- had been
# converted to `--kind receipt`, so they reached no human AND no machine, and
# page_once still wrote its dedupe marker because the sink exits 0.
#
# "Recorded, not delivered" is only defensible if something reads the record.
# This suite holds the reading end: the surfacer must PRINT an undelivered row,
# must not re-print it on the next session, and must never block a session.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$(cd "$HERE/.." && pwd)"
# BASH_SOURCE-derived, never $PWD: this suite tests the copy it ships beside.
SURFACE="$SCRIPTS/notify-receipts-surface.py"
NOTIFY="$SCRIPTS/slack-notify.sh"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# THE DEFECT, ASSERTED AS CASE ZERO. Before this PR the surfacer did not exist and
# every case below "passed" by never running -- the same class of false pass that
# cost this branch three cases already (rc=127 read as success). A missing engine
# is the finding, so it fails loudly here instead of silently skipping.
if [ ! -f "$SURFACE" ]; then
  echo "  FAIL THE DEFECT: the ledger has no reader -- $SURFACE does not exist"
  echo "-------- 0 passed, 1 failed --------"
  exit 1
fi

LEDGER="$WORK/notify-receipts.jsonl"
CURSOR="$LEDGER.cursor"
surface() { python3 "$SURFACE" --ledger "$LEDGER" 2>&1; }

# WHY THIS SUITE RUNS THE REAL NOTIFIER, AND WHY THAT IS STILL SAFE.
# fable-discipline-lint flags an unstubbed slack-notify.sh in a test, and it is
# right to: an unstubbed pager in a test is how the founder got paged live on
# 2026-08-01. Its suggested fix (KIPI_NOTIFY=/usr/bin/true) cannot apply here --
# the thing under test IS the row slack-notify.sh writes. A row I hand-author
# tests my assumption about the schema, not the schema (feedback_fixtures_from_
# producers: two green-but-wrong tests in one day came from exactly that).
#
# So the leak is closed structurally instead, three ways at once, and every one
# of them alone is sufficient:
#   1. curl is stubbed on PATH for the WHOLE suite, first line below. The
#      network is unreachable from here no matter what any case does.
#   2. KIPI_SLACK_WEBHOOK is unset per invocation.
#   3. HOME is redirected into $WORK, so ~/.config/kipi/slack-webhook resolves
#      to a file that does not exist.
# KIPI_LINEAR_API_URL is deliberately NOT set to loopback: the fixture guard
# exits before the ledger write, which would leave every case asserting against
# an empty file and passing for the wrong reason.
mkdir -p "$WORK/bin" "$WORK/home/.config/kipi"
cat > "$WORK/bin/curl" <<'STUB'
#!/bin/bash
# Never touch the network. Exit code is driven by the case via KIPI_TEST_CURL_RC.
exit "${KIPI_TEST_CURL_RC:-0}"
STUB
chmod +x "$WORK/bin/curl"
export PATH="$WORK/bin:$PATH"

write_row() {
  env -u KIPI_SLACK_WEBHOOK -u KIPI_LINEAR_API_URL \
      KIPI_NOTIFY_RECEIPTS="$LEDGER" HOME="$WORK/home" \
      bash "$NOTIFY" "$1" "${@:2}" >/dev/null 2>&1  # notify-kind-skip: every caller passes its own --kind  # fable-discipline-lint-skip: curl stubbed on PATH above
}

echo "== 1. an undelivered receipt is SURFACED =="
write_row "kipi dispatch: repo not found at /x -- the Linear loop is DEAD." --kind receipt
OUT="$(surface)"
case "$OUT" in
  *"the Linear loop is DEAD"*) ok "the receipt reaches the agent" ;;
  *) bad "the receipt reaches the agent" "got: $OUT" ;;
esac

echo "== 2. the same row is NOT surfaced twice =="
OUT2="$(surface)"
case "$OUT2" in
  *"Linear loop is DEAD"*) bad "already-surfaced rows stay quiet" "re-printed: $OUT2" ;;
  *) ok "already-surfaced rows stay quiet" ;;
esac

echo "== 3. a NEW row after the cursor is surfaced =="
write_row "kipi dispatch: gh CLI is not on PATH -- the loop is stalled." --kind receipt
OUT3="$(surface)"
case "$OUT3" in
  *"gh CLI is not on PATH"*) ok "the next receipt is picked up" ;;
  *) bad "the next receipt is picked up" "got: $OUT3" ;;
esac

echo "== 4. a REFUSED row is surfaced (a swallowed alert is the worst outcome) =="
write_row "producer used a class nobody allowlisted" --kind decision --class not-a-class
OUT4="$(surface)"
case "$OUT4" in
  *"nobody allowlisted"*) ok "refusals reach the agent" ;;
  *) bad "refusals reach the agent" "got: $OUT4" ;;
esac

echo "== 5. a DELIVERED row is not repeated to the agent =="
# Delivery needs a webhook AND a curl that succeeds. The webhook is a .invalid
# host and curl is the PATH stub from the top of the file, so "delivered" here
# means "slack-notify.sh believed it delivered", which is the state under test.
env -u KIPI_LINEAR_API_URL KIPI_TEST_CURL_RC=0 \
    KIPI_SLACK_WEBHOOK="https://hooks.example.invalid/not-real" \
    KIPI_NOTIFY_RECEIPTS="$LEDGER" HOME="$WORK/home" \
    bash "$NOTIFY" "a real founder decision that landed on his phone" \
    --kind decision --class spend >/dev/null 2>&1  # fable-discipline-lint-skip: curl stubbed on PATH above
OUT5="$(surface)"
case "$OUT5" in
  *"landed on his phone"*) bad "delivered rows are not re-surfaced" "got: $OUT5" ;;
  *) ok "delivered rows are not re-surfaced" ;;
esac

echo "== 6. a delivery that FAILED is surfaced (sp-21815b25: exit 0 hides it) =="
env -u KIPI_LINEAR_API_URL KIPI_TEST_CURL_RC=7 \
    KIPI_SLACK_WEBHOOK="https://hooks.example.invalid/not-real" \
    KIPI_NOTIFY_RECEIPTS="$LEDGER" HOME="$WORK/home" \
    bash "$NOTIFY" "this page never made it out of the machine" \
    --kind decision --class spend >/dev/null 2>&1  # fable-discipline-lint-skip: curl stubbed on PATH above
OUT6="$(surface)"
case "$OUT6" in
  *"never made it out of the machine"*) ok "a dropped page is not silently lost" ;;
  *) bad "a dropped page is not silently lost" "got: $OUT6" ;;
esac

echo "== 7. no ledger at all -> silent, exit 0 (a session must never be blocked) =="
OUT7="$(python3 "$SURFACE" --ledger "$WORK/does-not-exist.jsonl" 2>&1)"; RC=$?
if [ "$RC" -eq 0 ] && [ -z "$OUT7" ]; then
  ok "missing ledger is a silent no-op"
else
  bad "missing ledger is a silent no-op" "rc=$RC out=$OUT7"
fi

echo "== 8. a corrupt line does not take the session down =="
printf 'this is not json\n' >> "$LEDGER"
write_row "a good row written after the corrupt one" --kind receipt
OUT8="$(surface)"; RC=$?
if [ "$RC" -eq 0 ] && [ "${OUT8#*after the corrupt one}" != "$OUT8" ]; then
  ok "a malformed row is skipped, the good ones still arrive"
else
  bad "a malformed row is skipped, the good ones still arrive" "rc=$RC out=$OUT8"
fi

echo "== 9. a TRUNCATED ledger resets the cursor instead of going blind =="
# Rotation/truncation makes a byte cursor point past the end. Reading from a
# stale offset would silently skip every row written afterwards -- a reader that
# is quiet for the wrong reason is the same failure as having no reader.
: > "$LEDGER"
write_row "the first row after a rotation" --kind receipt
OUT9="$(surface)"
case "$OUT9" in
  *"first row after a rotation"*) ok "cursor resets when the file shrinks" ;;
  *) bad "cursor resets when the file shrinks" "got: $OUT9" ;;
esac

echo "== 10. NEGATIVE SELF-TEST: the suite can actually fail =="
# A cursor parked at the end of the file must produce silence. If this prints,
# every quiet assertion above is meaningless because the surfacer prints nothing
# under any condition.
write_row "a row that the cursor has already passed" --kind receipt
surface >/dev/null 2>&1          # advance the cursor past it
OUT10="$(surface)"
if [ -z "$OUT10" ]; then
  ok "silence is reachable, so the loud assertions above mean something"
else
  bad "silence is reachable" "surfacer printed with nothing new: $OUT10"
fi

echo "== 11. the cursor is the surfacer's OWN file; the ledger is untouched =="
BEFORE="$(wc -c < "$LEDGER")"
surface >/dev/null 2>&1
AFTER="$(wc -c < "$LEDGER")"
if [ "$BEFORE" = "$AFTER" ] && [ -f "$CURSOR" ]; then
  ok "single writer holds: slack-notify.sh owns the ledger, the surfacer owns the cursor"
else
  bad "single writer holds" "ledger $BEFORE -> $AFTER, cursor present: $([ -f "$CURSOR" ] && echo yes || echo no)"
fi

echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ]
