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
