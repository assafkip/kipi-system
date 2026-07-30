#!/usr/bin/env bash
# ci-shaped-run.sh -- run a test the way CI runs it, before pushing.
#
# WHY THIS EXISTS. On 2026-07-30 (ASK-221) SIX defects shipped green locally and
# red in CI, and every one was discovered the same way: push, wait ~8 minutes,
# read a runner log. The classes were different each time -- a BSD-only `mktemp`,
# a plugin version bump, a macOS-only `plutil`, a `sed -i ''`, a test reaching the
# real codex CLI, and a suite whose result depends on `~/.config/kipi` existing --
# but the DISCOVERY METHOD was identical, and it was the slowest one available.
#
# Fixing each defect stops that defect. This stops the seventh.
#
# DO NOT SKIP THE MANIFEST LOOKUP FOR SPEED. The first full sweep reported two
# .py tests as FAIL rc=2 because this script ran `bash` on everything and ignored
# the declared `runner`. rc=2 is "cannot execute" -- a harness bug wearing a test
# failure's clothes.
#
# That is worse than a wasted round: a checker that manufactures failures teaches
# you to distrust its output, and then a REAL failure reads as another harness
# bug. Three separate components hit this in one session -- a page firing 96 times
# a day, a lint whose findings were mostly its own prose, and this. A signal that
# cries wolf destroys the signal. Correctness of the harness outranks its speed.
#
# IT PAID FOR ITSELF BEFORE IT WAS FINISHED, and the number is the argument:
# it found in SECONDS what a full CI round could only report as `rc=1` after
# EIGHT MINUTES -- and in one case it overturned a fix that had already survived
# a CI round, because `rc=1` does not tell you WHICH assertion failed or why.
# Build the check at the level of the class, not the instance.
#
# WHAT CI HAS THAT A DEV MACHINE DOES NOT: a clean $HOME with no accumulated
# state, no `~/.config/kipi`, no KIPI_* environment, and a fresh checkout. Those
# are the differences a local `bash test-foo.sh` cannot see, because the machine
# you are typing on has been accumulating exactly that state all day.
#
# WHAT IT CANNOT SIMULATE, stated so nobody trusts it further than it goes: the
# KERNEL. CI is Linux/GNU, this is macOS/BSD. `mktemp -t`, `sed -i ''` and
# `plutil` divergences are invisible here no matter how clean the environment is.
# That half of the class belongs to portability-lint.sh, which greps for them.
# The two tools are complements, not alternatives -- neither alone covers the set.
#
# Usage:
#   ci-shaped-run.sh <test-path>...     run those tests CI-shaped
#   ci-shaped-run.sh --all              run every test in capability-manifest.json
#   ci-shaped-run.sh --diff <test>      run BOTH ways and report the divergence
#
# Exit 0 = all passed CI-shaped. Exit 1 = at least one failed.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE" && git rev-parse --show-toplevel 2>/dev/null || echo "$HERE/../../..")"
MANIFEST="$REPO/q-system/.q-system/capability-manifest.json"

# One sandbox HOME per invocation, discarded after. Never the real one: the whole
# point is that the real one is contaminated with the state under suspicion.
SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/ci-shaped.XXXXXX")"
cleanup() { [ -n "${SANDBOX:-}" ] && [ -d "$SANDBOX" ] && /bin/rm -rf "$SANDBOX"; }
trap cleanup EXIT

# HONOUR THE DECLARED RUNNER. The manifest carries `runner` per test (bash or
# python3) and the first cut of this script ran `bash` on everything -- so every
# .py test came back rc=2 ("cannot execute"), which reads as a failing test rather
# than a broken harness. A runner that misreports the thing it is checking is
# worse than no runner. Caught by its own first full sweep.
runner_for() {  # runner_for <abs-path> -> bash|python3
  local rel="${1#$REPO/}" r
  r="$(python3 -c "
import json,sys
try: m=json.load(open('$MANIFEST'))
except Exception: sys.exit()
for e in m.get('expected_tests',[]):
    if e.get('path')==sys.argv[1]: print(e.get('runner','')); break" "$rel" 2>/dev/null)"
  [ -n "$r" ] || case "$1" in *.py) r=python3 ;; *) r=bash ;; esac
  printf '%s' "$r"
}

run_ci_shaped() {  # run_ci_shaped <test-path> -> rc
  local t="$1" home="$SANDBOX/home-$(basename "$t" | tr -c 'a-zA-Z0-9' '_')"
  mkdir -p "$home"
  # `env -i` would also drop PATH and break the shell. So scrub the things that
  # actually differ -- HOME and every KIPI_* knob -- and keep PATH. A KIPI_* var
  # left set is the same contamination as a stale state file, just in a different
  # store: it makes the suite answer a question CI will not ask it.
  local unsets=()
  while IFS= read -r v; do [ -n "$v" ] && unsets+=("$v"); done < <(env | grep -oE '^KIPI_[A-Z_]+' || true)
  ( cd "$REPO" && env "${unsets[@]/#/--unset=}" HOME="$home" \
      "$(runner_for "$t")" "$t" ) >"$SANDBOX/$(basename "$t").out" 2>&1
  return $?
}

run_normal() {  # run_normal <test-path> -> rc
  ( cd "$REPO" && "$(runner_for "$1")" "$1" ) >"$SANDBOX/$(basename "$1").normal.out" 2>&1
  return $?
}

MODE="run"
case "${1:-}" in
  --all)  MODE="all"; shift ;;
  --diff) MODE="diff"; shift ;;
  "")     echo "usage: ci-shaped-run.sh [--all|--diff] <test-path>..." >&2; exit 2 ;;
esac

TESTS=()
if [ "$MODE" = "all" ]; then
  while IFS= read -r p; do TESTS+=("$REPO/$p"); done < <(
    python3 -c "
import json,sys
m=json.load(open('$MANIFEST'))
for e in m.get('expected_tests',[]): print(e['path'])" 2>/dev/null || true)
else
  for a in "$@"; do TESTS+=("$a"); done
fi

[ "${#TESTS[@]}" -gt 0 ] || { echo "no tests to run" >&2; exit 2; }

FAILED=0
DIVERGED=0
echo "ci-shaped-run: ${#TESTS[@]} test(s), sandbox HOME under $SANDBOX"
echo

for t in "${TESTS[@]}"; do
  [ -f "$t" ] || { printf '%-58s SKIP (not found)\n' "$(basename "$t")"; continue; }
  run_ci_shaped "$t"; rc_ci=$?
  if [ "$MODE" = "diff" ]; then
    run_normal "$t"; rc_norm=$?
    if [ "$rc_ci" != "$rc_norm" ]; then
      DIVERGED=$((DIVERGED+1))
      printf '%-58s DIVERGES  normal=%s ci-shaped=%s\n' "$(basename "$t")" "$rc_norm" "$rc_ci"
      echo "    the local pass depends on machine state CI will not have."
      echo "    ci-shaped output: $SANDBOX/$(basename "$t").out"
      # Show the first failure line, which is usually the whole diagnosis.
      grep -iE '^\s*(FAIL|not ok)' "$SANDBOX/$(basename "$t").out" 2>/dev/null | head -2 | sed 's/^/      /'
    else
      printf '%-58s same     rc=%s\n' "$(basename "$t")" "$rc_ci"
    fi
  else
    if [ "$rc_ci" -eq 0 ]; then
      printf '%-58s PASS\n' "$(basename "$t")"
    else
      printf '%-58s FAIL rc=%s\n' "$(basename "$t")" "$rc_ci"
      grep -iE '^\s*(FAIL|not ok)' "$SANDBOX/$(basename "$t").out" 2>/dev/null | head -2 | sed 's/^/      /'
    fi
  fi
  [ "$rc_ci" -eq 0 ] || FAILED=$((FAILED+1))
done

echo
# Keep the outputs when something is wrong -- the sandbox is deleted on exit, so
# a failure the operator cannot read is a failure they will re-run to see.
if [ "$FAILED" -gt 0 ] || [ "$DIVERGED" -gt 0 ]; then
  KEEP="$REPO/q-system/output/ci-shaped-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$KEEP" 2>/dev/null && cp "$SANDBOX"/*.out "$KEEP/" 2>/dev/null \
    && echo "outputs kept: $KEEP"
fi
[ "$DIVERGED" -eq 0 ] || echo "ci-shaped-run: $DIVERGED test(s) DIVERGE between normal and CI-shaped runs"
[ "$FAILED" -eq 0 ] || { echo "ci-shaped-run: $FAILED test(s) FAILED CI-shaped"; exit 1; }
echo "ci-shaped-run: clean"
