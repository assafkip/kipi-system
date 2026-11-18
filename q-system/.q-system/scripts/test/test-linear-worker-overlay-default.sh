#!/usr/bin/env bash
# A hand-run worker reads the same dispatch overlay the dispatcher does (ASK-5408).
#
# WHY: linear-worker.sh passed the overlay to registry_facts only when
# KIPI_DISPATCH_TARGETS was already exported. kipi-dispatch.sh exports it, a hand
# run does not, so `kipi work` (dry) printed "290 issues REFUSED (remote,
# credentials,branch-protection)" for repos the dispatcher enters. Same false
# alarm twice: ASK-3636 (canceled 2026-11-01 as operator error) and ASK-5408.
# Two occurrences means the instrument is the defect.
#
# Cases: 1 default applies when nothing is set; 2 explicit value wins, including
# empty; 3 NEGATIVE: a fixture skeleton or registry must never read the founder's
# live overlay; 4 the facts block actually calls the function (wiring).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKER="${KIPI_WORKER_UNDER_TEST:-$HERE/../linear-worker.sh}"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

# Extract the function by name from the script under test (no sourcing: the
# worker runs git and Linear at top level). HOME is a temp dir so no case can
# touch the real ~/.config.
FN="$(awk '/^dispatch_targets_default\(\) \{/{p=1} p{print} p&&/^}/{exit}' "$WORKER")"
if [ -z "$FN" ]; then
  bad "dispatch_targets_default exists in the worker" "function not found"
  echo "PASS=$PASS FAIL=$FAIL"; exit 1
fi
T="$(mktemp -d)"
call() { env -i HOME="$T" PATH="$PATH" "$@" bash -c "$FN"$'\n''dispatch_targets_default'; }

out="$(call)"
[ "$out" = "$T/.config/kipi/dispatch-targets.json" ] && ok "1 default is the live overlay when nothing is set" || bad "1 default" "got '$out'"
out="$(call KIPI_DISPATCH_TARGETS=/x/y.json)"
[ "$out" = "/x/y.json" ] && ok "2a explicit value wins" || bad "2a explicit" "got '$out'"
out="$(call KIPI_DISPATCH_TARGETS=)"
[ -z "$out" ] && ok "2b explicit empty means no overlay" || bad "2b explicit empty" "got '$out'"
out="$(call KIPI_SKEL=/fixture)"
[ -z "$out" ] && ok "3a NEGATIVE: fixture skeleton never reads the live overlay" || bad "3a" "got '$out'"
out="$(call KIPI_DISPATCH_REGISTRY=/fixture/r.json)"
[ -z "$out" ] && ok "3b NEGATIVE: fixture registry never reads the live overlay" || bad "3b" "got '$out'"
if grep -q 'OVERLAY="${KIPI_DISPATCH_TARGETS:-}"' "$WORKER"; then
  bad "4a wiring" "facts block still reads the raw variable"
else
  ok "4a facts block no longer reads the raw variable"
fi
if grep -q 'KIPI_DISPATCH_TARGETS="$(dispatch_targets_default)"' "$WORKER"; then
  ok "4b worker exports the defaulted overlay"
else
  bad "4b wiring" "no export of the function result"
fi
echo "PASS=$PASS FAIL=$FAIL"; [ "$FAIL" = 0 ]
