#!/bin/bash
# portability-lint-skip-file: this script is macOS-only BY DESIGN (launchd/plutil).
# Materialize a committed plist TEMPLATE and load it into launchd.
#
# Why this exists (ASK-191): three committed plists in this directory used two
# different conventions. com.kipi.openloops-heartbeat.plist carried __KIPI_REPO__
# and __HOME__ placeholders -- but NOTHING in the repo ever substituted them, so
# the convention was text in a file, not wiring: copying that plist into
# ~/Library/LaunchAgents produced a job that tried to exec `__KIPI_REPO__/...`.
# The other two (fleet-health, linear-dor) sidestepped the missing substituter by
# hardcoding the founder's home directory, which made the skeleton unusable on
# any other machine and failed validate-separation's Full skeleton sweep.
#
# One substituter, one convention, all three templates. A template is never
# loadable as-is; it is rendered here.
#
# Usage: bash q-system/.q-system/scripts/install-plist.sh <label> [--render-only <out>]
#   e.g. bash q-system/.q-system/scripts/install-plist.sh com.kipi.fleet-health
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# scripts/ -> .q-system/ -> q-system/ -> repo root
KIPI_REPO="$(cd "$SCRIPT_DIR/../../.." && pwd)"

usage() {
  echo "usage: install-plist.sh <label> [--render-only <output-path>]" >&2
  echo "labels available:" >&2
  for p in "$SCRIPT_DIR"/com.kipi.*.plist; do
    [ -e "$p" ] || continue
    echo "  $(basename "$p" .plist)" >&2
  done
}

if [ $# -lt 1 ]; then
  usage
  exit 2
fi

# --all: install EVERY committed template. Added 2026-08-14 (ASK-729, Codex review
# of #147/#143 major). Six templates were committed and NOTHING called the
# installer, so a merge taught no machine to run any of them -- every job ran only
# where somebody had typed the command by hand. A scheduled job that exists on one
# laptop is not a mechanism. This is the caller, so a fresh checkout can arm the
# fleet's jobs in one step, and each install still reports its own result rather
# than the loop reporting a single aggregate success.
if [ "$1" = "--all" ]; then
  # REFUSE FROM A WORKTREE. Measured the hard way 2026-08-14: running --all from a
  # git worktree rewrote every live job to point at that worktree, including the
  # dispatcher, seconds before the directory was to be deleted. One label is a
  # deliberate act on one job; --all is a fleet-wide rewrite, and aiming that at a
  # temporary checkout silently disarms every scheduled job on the machine.
  if [ -f "$KIPI_REPO/.git" ] || [ ! -d "$KIPI_REPO/.git" ]; then
    echo "REFUSED: --all only runs from the primary checkout, not a worktree." >&2
    echo "  resolved KIPI_REPO=$KIPI_REPO" >&2
    echo "  every installed job would point here and break when it is removed." >&2
    echo "  install a single label instead: install-plist.sh <label>" >&2
    exit 2
  fi
  rc=0
  for _p in "$SCRIPT_DIR"/com.kipi.*.plist; do
    [ -e "$_p" ] || continue
    _label="$(basename "$_p" .plist)"
    if bash "$0" "$_label"; then :; else rc=1; echo "  FAILED: $_label" >&2; fi
  done
  exit "$rc"
fi

LABEL="$1"
shift
TEMPLATE="$SCRIPT_DIR/$LABEL.plist"

if [ ! -f "$TEMPLATE" ]; then
  echo "ERROR: no plist template for label '$LABEL' at $TEMPLATE" >&2
  usage
  exit 2
fi

RENDER_ONLY=""
if [ "${1:-}" = "--render-only" ]; then
  if [ -z "${2:-}" ]; then
    echo "ERROR: --render-only needs an output path" >&2
    exit 2
  fi
  RENDER_ONLY="$2"
fi

# ASK-1170: __USER__ joined __KIPI_REPO__ and __HOME__ because a launchd job that
# shells the `claude` CLI needs USER/LOGNAME set. Measured 2026-08-30: with them
# absent the CLI answers "Not logged in - please run /login" (the keychain lookup
# needs them); with USER set, the same command returned a real calendar answer.
# Adding the token WITHOUT adding it to assert_rendered below would have been the
# worse half of the change: an unsubstituted placeholder that plutil accepts and
# launchd fails on at fire time, silently, which is the exact class assert_rendered
# was written for.
render() {
  # sed with | as the delimiter: the path replacements contain /.
  sed -e "s|__KIPI_REPO__|$KIPI_REPO|g" -e "s|__HOME__|$HOME|g" \
      -e "s|__USER__|$(id -un)|g" "$TEMPLATE"
}

# A template that still carries a placeholder after substitution is a broken
# render, and launchd would accept it silently and fail at fire time. Fail loud.
assert_rendered() {
  local rendered_file="$1"
  if grep -q "__KIPI_REPO__\|__HOME__\|__USER__" "$rendered_file"; then
    echo "ERROR: unsubstituted placeholder remains in $rendered_file" >&2
    exit 1
  fi
}

if [ -n "$RENDER_ONLY" ]; then
  mkdir -p "$(dirname "$RENDER_ONLY")"
  render > "$RENDER_ONLY"
  assert_rendered "$RENDER_ONLY"
  echo "rendered $LABEL -> $RENDER_ONLY (KIPI_REPO=$KIPI_REPO)"
  exit 0
fi

PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.config/kipi"
render > "$PLIST"
assert_rendered "$PLIST"

# plutil is the only thing that proves the rendered XML is a loadable plist.
if command -v plutil >/dev/null 2>&1; then
  plutil -lint "$PLIST" >/dev/null
fi

UID_="$(id -u)"
launchctl bootout "gui/$UID_/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_" "$PLIST"
echo "installed $LABEL -> $PLIST (KIPI_REPO=$KIPI_REPO)"
launchctl list | grep "$LABEL" || echo "  WARN: not loaded"
