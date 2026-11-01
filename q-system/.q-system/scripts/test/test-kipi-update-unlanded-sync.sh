#!/usr/bin/env bash
# unlanded_sync_scan counts updater commits on HEAD that origin lacks. ASK-3655 /
# ASK-3633: consulting held 12 unpushed, another instance 88.
# Tests the FUNCTION extracted from the updater (never runs the updater, which
# rsyncs the whole fleet), plus pins that the flag is parsed and the scan is
# called before the refusal. Negative self-test: pushed, human-only and
# no-upstream cases must report 0, so a scan that always says 1 fails here.
set -euo pipefail
ROOT="${UNLANDED_TEST_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)}"
UPD="$ROOT/kipi-update.sh"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }
eval "$(sed -n '/^unlanded_sync_scan() {/,/^}/p' "$UPD")"
UNLANDED_SYNC_COUNT=0
w="$(mktemp -d)"; inst="$w/inst"
G init -q --bare -b main "$w/origin.git"
G init -q -b main "$inst"; G -C "$inst" remote add origin "$w/origin.git"
echo a > "$inst/f"; G -C "$inst" add f; G -C "$inst" commit -qm base
G -C "$inst" push -q -u origin main
unlanded_sync_scan "$inst" >/dev/null; [ "$UNLANDED_SYNC_COUNT" = 0 ] || fail "pushed tree reported $UNLANDED_SYNC_COUNT"
echo b > "$inst/f"; G -C "$inst" commit -qam "human work"
unlanded_sync_scan "$inst" >/dev/null; [ "$UNLANDED_SYNC_COUNT" = 0 ] || fail "a human commit was judged: $UNLANDED_SYNC_COUNT"
echo c > "$inst/f"; G -C "$inst" commit -qam "chore: sync q-system from skeleton [no-issue: fleet updater skeleton sync]"
echo d > "$inst/f"; G -C "$inst" commit -qam "chore: commit system-written state [no-issue: fleet updater system-state commit]"
# Not $(...): a subshell would drop the count the function sets.
unlanded_sync_scan "$inst" > "$w/scan.out"; out="$(cat "$w/scan.out")"; [ "$UNLANDED_SYNC_COUNT" = 2 ] || fail "expected 2, got $UNLANDED_SYNC_COUNT"
echo "$out" | grep -q 'unlanded sync: 2 updater commit' || fail "not reported: $out"
G -C "$inst" push -q origin main
unlanded_sync_scan "$inst" >/dev/null; [ "$UNLANDED_SYNC_COUNT" = 0 ] || fail "still unlanded after push"
G init -q -b main "$w/noup"; unlanded_sync_scan "$w/noup" >/dev/null; [ "$UNLANDED_SYNC_COUNT" = 0 ] || fail "no upstream must be 0"
grep -q -- '--refuse-unlanded-sync) REFUSE_UNLANDED_SYNC=1' "$UPD" || fail "flag not parsed"
awk '/unlanded_sync_scan "\$path"/{a=NR} /refusing \(--refuse-unlanded-sync\)/{b=NR} END{exit !(a&&b&&a<b)}' "$UPD" || fail "scan not called before the refusal"
echo "PASS: counts only unlanded updater commits; zero when pushed, human-only or no upstream; flag wired"
