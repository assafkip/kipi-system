#!/usr/bin/env bash
# An outage is bounded, quiet after its first word, and blames nobody (ASK-2009).
#
# PR #421 round 1 found that the halt from ASK-873 stopped CHARGING issues for a
# dead account but still made noise per tick. Each case below is the reviewer's
# own reproducer, kept verbatim under env-halt-bounds/ (only its repo-root line
# moved with it), and this driver asserts the number each one prints. Every
# number was measured RED on the code before the fix:
#
#   comment-spam2   3 halted runs, 1 outage -> "Not attempted" Linear comments.
#                   Was 3 (one per tick). Must be 1.
#   codex-loop      a Codex outage over two ticks -> pages. Was 0 (silent, exit 0,
#                   re-dispatched forever). Must be 1.
#   codex-limit     a Codex outage with --limit 1 on a 3-issue board. Was: one run
#                   walked ASK-811, 812 and 813. Must stop at ASK-811.
#   converge-page   converge after the worker's env halt -> pages. Was 1 (an
#                   exit-7 "Sana could not open a PR" per issue per tick). Must be 0.
#   leak            orphan per-pid files left by dead runs, after one healthy run.
#                   Was 2. Must be 0.
#   unmute-on-skip  one outage, with a middle tick that skipped every issue and
#                   never ran the runner. Was 2 pages and 2 comments. Must be 1
#                   and 1, and a tick where the runner answers must still free
#                   the claim so the NEXT outage pages (2 pages across 2).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
B="$HERE/env-halt-bounds"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

run() { bash "$B/$1.sh" 2>&1 | grep -v 'Terminated'; }

echo "== one outage, one Linear comment"
OUT="$(run repro-comment-spam2)"
N="$(printf '%s\n' "$OUT" | grep -A1 "commentCreate calls carrying 'Not attempted'" | tail -1 | tr -dc '0-9')"
P="$(printf '%s\n' "$OUT" | sed -n 's/.*pages fired across 3 halted runs (deduped): \([0-9]*\).*/\1/p')"
if [ "${P:-x}" = "1" ] && [ "${N:-x}" = "1" ]; then
  ok "3 halted runs in one outage: 1 page and 1 'Not attempted' comment"
else
  bad "one outage writes one comment and one page" "pages=${P:-?} comments=${N:-?}: $(printf '%s' "$OUT" | tail -4 | tr '\n' '|')"
fi

echo "== a Codex outage halts and pages once"
OUT="$(run repro-codex-loop)"
P="$(printf '%s\n' "$OUT" | sed -n 's/^  pages fired: *\([0-9]*\).*/\1/p' | tail -1)"
if [ "${P:-x}" = "1" ]; then
  ok "a Codex outage over two ticks pages exactly once"
else
  bad "a Codex outage pages once" "pages=${P:-?}: $(printf '%s' "$OUT" | tail -4 | tr '\n' '|')"
fi

echo "== a Codex outage does not walk the queue past --limit"
OUT="$(run repro-codex-limit)"
if grep -q "ASK-811 the second runner is unavailable" <<<"$OUT" \
   && ! grep -qE "ASK-81[23] the second runner is unavailable" <<<"$OUT"; then
  ok "--limit 1 on a 3-issue board stops at ASK-811"
else
  bad "the run stops at the first Codex refusal" "$(grep -E 'second runner' <<<"$OUT" | tr '\n' '|' | cut -c1-400)"
fi

echo "== converge does not page for a machine outage"
OUT="$(run repro-converge-page)"
P="$(printf '%s\n' "$OUT" | sed -n 's/^--- page count: \([0-9]*\).*/\1/p' | tail -1)"
if [ "${P:-x}" = "0" ]; then
  ok "converge after an env halt files no exit-7 ticket"
else
  bad "converge stays quiet on an env halt" "page count=${P:-?}"
fi

echo "== a Codex outage after an honest Codex refusal still pages"
# PR #421 round 2: the claim was released only on a committing Codex run, so an
# honest refusal left it held and the NEXT Codex outage paged nobody.
OUT="$(run repro-codex-mute)"
P1="$(printf '%s\n' "$OUT" | sed -n 's/^run1-codex-outage .*PAGES SENT=\([0-9]*\).*/\1/p')"
P3="$(printf '%s\n' "$OUT" | sed -n 's/^run3-codex-outage-again .*PAGES SENT=\([0-9]*\).*/\1/p')"
if [ "${P1:-x}" = "1" ] && [ "${P3:-x}" = "1" ]; then
  ok "two Codex outages around an honest refusal page twice, once each"
else
  bad "every Codex outage pages once" "run1=${P1:-?} run3=${P3:-?}"
fi

echo "== one Codex outage, one 'Not parked' comment"
# PR #421 round 4: the Codex branch deduped its page but posted its
# "Not parked: the second runner was unavailable" note on every tick.
OUT="$(run repro-codex-comment-spam)"
N="$(printf '%s\n' "$OUT" | sed -n "s/.*commentCreate calls carrying 'Not parked: the second runner was unavailable': \([0-9]*\).*/\1/p" | tail -1)"
P="$(printf '%s\n' "$OUT" | sed -n 's/.*pages fired across 3 ticks of ONE Codex outage (deduped): \([0-9]*\).*/\1/p' | tail -1)"
if [ "${N:-x}" = "1" ] && [ "${P:-x}" = "1" ]; then
  ok "3 ticks of one Codex outage: 1 page and 1 'Not parked' comment"
else
  bad "one Codex outage writes one comment" "pages=${P:-?} comments=${N:-?}"
fi

echo "== the CLI's hook-teardown lines never sink a real outage"
# Every hook event the noise rule names, at column 0 and indented by 3 (PR #421
# rounds 3 and 4: the widening had no case of its own, and the rule was
# column-0 anchored while the marker rule tolerates 3 spaces).
LIB="$HERE/../env-failure-lib.sh"
LIMIT="You've hit your weekly limit · resets Sep 22 at 2pm (America/Los_Angeles)"
MISSED=""
for ev in SessionEnd SessionStart Stop SubagentStop PreCompact Notification UserPromptSubmit PreToolUse PostToolUse; do
  for pad in "" "   "; do
    payload="$(printf '%s\n%s%s hook [node "x.mjs"] failed: Hook cancelled' "$LIMIT" "$pad" "$ev")"
    ( . "$LIB"; is_environmental "$payload" ) || MISSED="$MISSED ${ev}(pad=${#pad})"
  done
done
if [ -z "$MISSED" ]; then
  ok "a limit line beside any of 9 hook-teardown lines, at column 0 or indented 3, is an outage"
else
  bad "hook teardown noise is ignored for every event" "charged anyway:$MISSED"
fi
OUT="$(run repro-indent-noise)"
if grep -q "^3-space indent *-> OUTAGE" <<<"$OUT"; then
  ok "the reviewer's indented-teardown reproducer reads as an outage"
else
  bad "an indented teardown line does not sink an outage" "$(grep -E 'indent' <<<"$OUT" | tr '\n' '|')"
fi
# and the negative: a hook-failure line ALONE is not an outage (a timeout kill)
if ( . "$LIB"; is_environmental 'Stop hook [node "x.mjs"] failed: Hook cancelled' ); then
  bad "hook noise alone is not an outage" "a lone teardown line was excused"
else
  ok "a lone teardown line (a timeout kill) is still the issue's"
fi

echo "== a tick that never reached the runner does not re-arm the page"
# PR #421 round 5, major: the release after the loop was unconditional, so a
# tick that skipped every issue (attempt cap, --issue onto a capped issue)
# re-armed the page mid-outage.
OUT="$(run repro-unmute-on-skip)"
P1="$(printf '%s\n' "$OUT" | sed -n 's/^=== PAGES for ONE continuous outage: \([0-9]*\).*/\1/p')"
C1="$(printf '%s\n' "$OUT" | sed -n "s/^=== permanent Linear comments carrying 'Not attempted': \([0-9]*\).*/\1/p")"
P2="$(printf '%s\n' "$OUT" | sed -n 's/^=== PAGES across two outages split by a healthy tick: \([0-9]*\).*/\1/p')"
if [ "${P1:-x}" = "1" ] && [ "${C1:-x}" = "1" ]; then
  ok "a skipped tick inside one outage: still 1 page and 1 'Not attempted' comment"
else
  bad "a tick that never ran the runner keeps the outage claim" "pages=${P1:-?} comments=${C1:-?}"
fi
if [ "${P2:-x}" = "2" ]; then
  ok "a tick where the runner answers frees the claim: the next outage pages again"
else
  bad "the claim is released once the runner answers" "pages across two outages=${P2:-?} (1 = a permanent mute)"
fi

echo "== a dead run's per-pid files are swept"
OUT="$(run repro-leak)"
A="$(printf '%s\n' "$OUT" | sed -n 's/^after: *\([0-9]*\) orphan.*/\1/p')"
BEF="$(printf '%s\n' "$OUT" | sed -n 's/^before: *\([0-9]*\) orphan.*/\1/p')"
if [ "${BEF:-x}" = "2" ] && [ "${A:-x}" = "0" ]; then
  ok "2 planted orphans from dead pids are gone after one healthy run"
else
  bad "orphans are swept" "before=${BEF:-?} after=${A:-?}"
fi

echo
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
