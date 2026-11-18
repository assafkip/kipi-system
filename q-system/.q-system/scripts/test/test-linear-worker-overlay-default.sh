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
trap 'rm -rf "$T"' EXIT
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
# 4 BEHAVIOUR, NOT GREP (PR #838 review, minor 1). Run the worker's real facts
# block (defaulting line through the closing paren of REGISTRY_FACTS) against a
# fixture registry and overlay in a temp HOME, then read what the worker would
# hand to preflight. A grep stayed green with the export deleted and with
# OVERLAY="" ; this fails on both.
BLOCK="$(awk '/^KIPI_DISPATCH_TARGETS="\$\(dispatch_targets_default\)"/{p=1} p{print} p&&/^\)"$/{exit}' "$WORKER")"
if [ -z "$BLOCK" ]; then
  bad "4 facts block found in the worker" "could not cut the block"
else
  mkdir -p "$T/skel" "$T/cl" "$T/.config/kipi"
  printf '{"skeleton":{"name":"s","path":"%s"},"instances":[{"name":"cl","path":"%s","linear_project":"cl"}]}' "$T/skel" "$T/cl" > "$T/skel/instance-registry.json"
  printf '{"instances":[{"name":"cl","path":"%s","linear_project":"cl","dispatch":{"enabled":true,"expected_remote":"https://example.invalid/o/cl.git"}}]}' "$T/cl" > "$T/.config/kipi/dispatch-targets.json"
  TAIL='printf "%s\n" "$REGISTRY_FACTS"; printf "CHILD=%s\n" "$(bash -c '"'"'printf %s "$KIPI_DISPATCH_TARGETS"'"'"')"'
  run4() { env -i HOME="$T" PATH="$PATH" SCRIPT_DIR="$HERE/.." SKEL="$T/skel" TARGET_REPO="$T/skel" "$@" \
    bash -c "$FN"$'\n'"$BLOCK"$'\n'"$TAIL"; }
  out="$(run4)"
  if printf '%s' "$out" | grep -q '"remote": "https://example.invalid/o/cl.git"'; then
    ok "4a hand run: the overlay pin reaches local_repos[].remote"
  else
    bad "4a" "$out"
  fi
  if printf '%s' "$out" | grep -q "CHILD=$T/.config/kipi/dispatch-targets.json"; then
    ok "4b hand run: child processes (preflight, slug lib) inherit the overlay"
  else
    bad "4b" "$out"
  fi
  out="$(run4 KIPI_DISPATCH_TARGETS=)"
  if printf '%s' "$out" | grep -q 'example.invalid'; then
    bad "4c NEGATIVE: explicit empty must mean no overlay" "$out"
  else
    ok "4c NEGATIVE: explicit empty leaves the remote unpinned"
  fi
fi
echo "PASS=$PASS FAIL=$FAIL"; [ "$FAIL" = 0 ]
