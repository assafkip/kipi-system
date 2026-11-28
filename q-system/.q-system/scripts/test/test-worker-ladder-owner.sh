#!/usr/bin/env bash
# The worker names cap-ladder.py as the owner of a review-capped PR (ASK-5844).
#
# WHY THIS EXISTS. On 2026-11-27 the worker's WIP pass labelled a capped PR
# "unreviewed ... the reviewer redrive owns it". The redrive correctly leaves
# capped PRs alone, so the line sent the reader to the wrong owner. The answer now
# comes from cap-ladder.py's ladder_owns(), whose cap_sigs() keys the review cap on
# THIS PR's .round-cap marker.
#
# Pinned through ladder_owner_why lifted from linear-worker.sh and the REAL
# cap-ladder.py, in a temp state dir:
#   1. this PR's marker present: the reason names cap-ladder;
#   2. another PR's marker only (the #899/#903 shared-commit case): no owner;
#   3. no marker: no owner;
#   4. wip_move_why's gate-20 case asks it.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SCRIPT_DIR="$ROOT/q-system/.q-system/scripts"
WORKER="${KIPI_WORKER_UNDER_TEST:-$SCRIPT_DIR/linear-worker.sh}"
PASS=0; FAIL=0
ok()  { PASS=$((PASS + 1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; [ -n "${2:-}" ] && printf '       %s\n' "$2"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
for f in ladder_owner_why unreviewed_reason; do
  FN="$(awk -v n="$f" '$0 ~ "^"n"\\(\\) \\{" {on=1} on {print} on && /^}/ {exit}' "$WORKER")"
  [ -n "$FN" ] || { echo "FATAL: $f() is not in $WORKER" >&2; exit 1; }
  eval "$FN"
done
LOG="$WORK/log"; : > "$LOG"
STATE_DIR="$WORK/state"; mkdir -p "$STATE_DIR/pr-reviews"
echo '{}' > "$STATE_DIR/linear-worker-attempts.json"
TARGET_SLUG="assafkip/kipi-system"
MARK_DIR="$STATE_DIR/pr-reviews"

touch "$MARK_DIR/.round-cap-assafkip_kipi-system-pr-899"
got="$(ladder_owner_why ASK-5799 899)"
printf '%s' "$got" | grep -q '^cap-ladder owns it: ASK-5799 holds reviewcap' \
  && ok "a PR with its own .round-cap marker is owned by cap-ladder" \
  || bad "own marker: got '$got'" "$(tail -3 "$LOG")"

got="$(ladder_owner_why ASK-5802 903)"
[ -z "$got" ] && ok "another PR's marker does not make this PR capped (#899 vs #903)" \
  || bad "another PR's marker: got '$got'"

got="$(ladder_owner_why ASK-5803 904)"
[ -z "$got" ] && ok "no marker, no owner" || bad "no marker: got '$got'"

got="$(unreviewed_reason ASK-5799 899)"
case "$got" in
  "unreviewed|no recorded review verdict; cap-ladder owns it"*) ok "the gate-20 reason for a capped PR names cap-ladder, kind unreviewed" ;;
  *) bad "capped PR reason: '$got'" ;;
esac
got="$(unreviewed_reason ASK-5803 904)"
case "$got" in
  "unreviewed|"*"(the worker starts its review at gate 20, review-redrive.py after that)") ok "an uncapped PR names the gate-20 start and the reviewer redrive (ASK-5846)" ;;
  *) bad "uncapped PR reason: '$got'" ;;
esac
awk '/^wip_move_why\(\) \{/ {on=1} on {print} on && /^}/ {exit}' "$WORKER" \
  | grep -q '^    20) unreviewed_reason "\$issue" "\$pr" ;;$' \
  && ok "wip_move_why's gate 20 uses unreviewed_reason" || bad "gate 20 does not call unreviewed_reason"

echo "PASS: $PASS  FAIL: $FAIL"
[ "$FAIL" = 0 ]
