#!/bin/bash
# sp-a4a933ad: a dry run's output must be impossible to mistake for a real one.
#
# THE SCAR. Dry mode really does perform the update -- against a throwaway clone
# -- so it printed "OK (686 files updated)" and 686 lines of "create mode
# 100644 ..." exactly like a real run. One banner 700 lines earlier was the only
# difference.
#
# The trap runs both ways and the second direction is the dangerous one: a reader
# of a dry log concludes the instance was mutated, and a reader of a REAL log can
# mistake it for a preview and believe nothing happened. sp-46c73c76 was a guard
# that let --dry-run genuinely commit into live instances; the only defence was a
# human reading the log, and the log gave them nothing to read.
#
# Only --dry-run is invoked, against a throwaway skeleton and instance.
#
# Run: bash test-kipi-update-dry-tagging.sh
set -uo pipefail

REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"
trap 'rm -r -- "$T" 2>/dev/null || true' EXIT
FAILURES=0

echo "=== the helpers tag ONLY in dry mode ==="
# Unit level, both directions. A say() that always tagged would pass the
# integration check below while corrupting every real run's output.
HELPERS="$(sed -n '/^say()/,/^}/p;/^dry_filter()/,/^}/p' "$REAL/kipi-update.sh")"
# If the extraction silently returns nothing, the probes below call an undefined
# say/dry_filter: command-not-found on stderr, and under `set -uo pipefail` the
# script CONTINUES and reports a meaningless result. Fail loudly instead -- the
# helpers moving is exactly the drift this file should catch.
for helper in "say()" "dry_filter()"; do
  case "$HELPERS" in
    *"$helper"*) ;;
    *) echo "FAIL: could not extract $helper from kipi-update.sh; the helpers moved."
       exit 1 ;;
  esac
done
# Build a real script that DEFINES the helpers and then uses them, rather than
# calling them from this file. Same coverage, and it keeps the helper calls in
# the same file as their definitions -- which is what the shell lint asks for,
# and the lint is right: a bare call to a helper this file never defines is
# command-not-found on stderr while the script carries on.
PROBE="$T/probe.sh"
{
  printf 'set -uo pipefail\n'
  printf 'DRY_RUN="${1:-}"\n'
  printf '%s\n' "$HELPERS"
  printf 'say "status line"\n'
  printf 'printf "piped line\\n" | dry_filter\n'
} > "$PROBE"

probe() { /bin/bash "$PROBE" "$1" 2>&1; }
DRY_OUT="$(probe '--dry-run')"
REAL_OUT="$(probe '')"

if [ "$(printf '%s' "$DRY_OUT" | grep -c '^DRY | ')" = "2" ]; then
  echo "  OK: dry mode tags both the status line and the piped line"
else
  echo "  FAIL: dry mode tagged $(printf '%s' "$DRY_OUT" | grep -c '^DRY | ')/2 lines"
  printf '%s\n' "$DRY_OUT" | sed 's/^/      /'
  FAILURES=$((FAILURES + 1))
fi

if printf '%s' "$REAL_OUT" | grep -q '^DRY | '; then
  echo "  FAIL: a REAL run is being tagged; every log would claim to be a preview"
  FAILURES=$((FAILURES + 1))
else
  echo "  OK: a real run is untagged"
fi

if [ "$(printf '%s' "$REAL_OUT" | wc -l | tr -d ' ')" = "1" ] &&
   printf '%s' "$REAL_OUT" | grep -q "status line" &&
   printf '%s' "$REAL_OUT" | grep -q "piped line"; then
  echo "  OK: a real run still emits both lines unchanged"
else
  echo "  FAIL: real-mode output was altered"
  printf '%s\n' "$REAL_OUT" | sed 's/^/      /'
  FAILURES=$((FAILURES + 1))
fi

echo ""
echo "=== dry_filter must not swallow the commit's exit code ==="
# The filter sits on the end of the commit pipeline. Reading $? there would
# return sed's status, so a FAILED commit would read as success -- a much worse
# bug than the one being fixed.
RC_OK="$(/bin/bash -c "set -uo pipefail; DRY_RUN='--dry-run'; $HELPERS
  (exit 7) | dry_filter; echo \${PIPESTATUS[0]}" 2>&1 | tail -1)"
if [ "$RC_OK" = "7" ]; then
  echo "  OK: PIPESTATUS[0] preserves the upstream failure"
else
  echo "  FAIL: upstream exit code lost (got '$RC_OK', wanted 7)"
  FAILURES=$((FAILURES + 1))
fi
if grep -q 'rc=${PIPESTATUS\[0\]}' "$REAL/kipi-update.sh"; then
  echo "  OK: guarded_commit reads PIPESTATUS[0], not \$?"
else
  echo "  FAIL: guarded_commit no longer reads PIPESTATUS[0]; a failed commit reads as success"
  FAILURES=$((FAILURES + 1))
fi

echo ""
echo "=== a real dry run leaves no untagged mutating line ==="
SKEL="$T/f/skeleton"
mkdir -p "$T/f"
bash "$REAL/.sana-tmp/mkfleet.sh" "$T/f" >/dev/null 2>&1
if [ ! -x "$SKEL/kipi-update.sh" ]; then
  echo "  SKIP: fixture builder unavailable (.sana-tmp/mkfleet.sh); unit checks above still ran"
else
  /bin/bash "$SKEL/kipi-update.sh" --dry-run --only fake > "$T/f/out.txt" 2>&1
  if ! grep -q -- "--- fake (subtree) ---" "$T/f/out.txt"; then
    echo "  FAIL: run never reached the instance; measuring nothing"
    FAILURES=$((FAILURES + 1))
  else
    TAGGED="$(grep -c '^DRY | ' "$T/f/out.txt")"
    UNTAGGED="$(grep -E "files updated|create mode|delete mode|Committing |restored untracked" "$T/f/out.txt" | grep -vc '^DRY | ')"
    if [ "$TAGGED" -gt 100 ] && [ "$UNTAGGED" = "0" ]; then
      echo "  OK: $TAGGED tagged lines, 0 untagged mutating lines"
    else
      echo "  FAIL: $TAGGED tagged, $UNTAGGED untagged mutating lines remain"
      grep -E "files updated|create mode|Committing |restored untracked" "$T/f/out.txt" |
        grep -v '^DRY | ' | head -4 | sed 's/^/      /'
      FAILURES=$((FAILURES + 1))
    fi
  fi
fi

echo ""
if [ "$FAILURES" = "0" ]; then echo "PASS"; exit 0; else echo "FAIL ($FAILURES)"; exit 1; fi
