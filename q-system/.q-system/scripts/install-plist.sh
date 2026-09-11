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

# THE ENUMERATOR. One function, and every caller below goes through it: --all, the
# usage listing, and the single-label lookup. Measured 2026-09-07: this used to be
# `"$SCRIPT_DIR"/com.kipi.*.plist` written out three times, so the promise in
# `kipi:22` ("install every committed launchd job") was scoped to ONE directory.
# 15 plists were committed, 12 installed, 2 announced as skipped, and
# automation/com.kipi.voice-refresh.plist was never mentioned at all -- the run
# exited 0. A partial install that reports success is worse than a failed one:
# detect_dark_jobs in fleet-health-daily.py enumerates ~/Library/LaunchAgents, so a
# job never installed even once is invisible to the watchdog as well.
#
# The set comes from the REPO (git ls-files), not from a directory listing, because
# "committed" is what the verb promises and only git knows it. The glob survives as
# the fallback for a tree that is not a git checkout (an extracted template), and
# the two are never silently interchangeable: templates_source() says which ran.
templates_source() {
  if git -C "$KIPI_REPO" rev-parse --git-dir >/dev/null 2>&1; then
    echo "git ls-files"
  else
    echo "directory glob (not a git checkout)"
  fi
}

# Emits absolute paths, one per line, sorted. A tracked-but-deleted file is dropped
# here rather than becoming a confusing "no template" error three functions later.
committed_templates() {
  if [ "$(templates_source)" = "git ls-files" ]; then
    git -C "$KIPI_REPO" ls-files -- '*/com.kipi.*.plist' 'com.kipi.*.plist' \
      | while IFS= read -r rel; do
          [ -f "$KIPI_REPO/$rel" ] && echo "$KIPI_REPO/$rel"
        done | sort
  else
    for p in "$SCRIPT_DIR"/com.kipi.*.plist; do
      [ -e "$p" ] && echo "$p"
    done | sort
  fi
}

# Resolve a label to its template path, from the same set --all walks. Before this,
# `install-plist.sh com.kipi.voice-refresh` answered "no plist template for label"
# about a template that was committed two directories away.
#
# No `| head -1` here, and that is the whole reason this is a loop with a `return`
# instead of a one-liner. `committed_templates | ... | head -1` closes the pipe as
# soon as it has its line, the upstream loop dies of SIGPIPE with status 141, and
# `set -o pipefail` hands that to the assignment, where `set -e` kills the script
# with no message. It looked like every template was broken: 12 of 13 labels failed
# and only com.kipi.weekly-improve, the alphabetically LAST one, survived, because
# it is the only label where head never closes the pipe early.
template_for_label() {
  local want="$1" p
  while IFS= read -r p; do
    if [ "$(basename "$p" .plist)" = "$want" ]; then
      echo "$p"
      return 0
    fi
  done <<EOF
$(committed_templates)
EOF
  return 0
}

usage() {
  echo "usage: install-plist.sh <label> [--render-only <output-path>]" >&2
  echo "labels available (from $(templates_source)):" >&2
  committed_templates | while IFS= read -r p; do
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
  # SKELETON-ONLY templates are skipped outside the skeleton. A template that
  # carries the marker `kipi-scope: skeleton-only` (com.kipi.lessons-daily: its
  # job shells kipi-update.sh, which only works in the skeleton) must never be
  # armed by --all from an instance checkout; that would rebind the label to the
  # instance and recreate the collision the marker exists to prevent (Codex
  # adversarial review, issue lr-lessons-label-collision). Skeleton-ness is the
  # registry's word, not the directory's: instance-registry.json at this root
  # naming this root as the skeleton.
  _skeleton=""
  if [ -f "$KIPI_REPO/instance-registry.json" ]; then
    _skeleton="$(python3 -c 'import json,sys,os; print(os.path.realpath(json.load(open(sys.argv[1]))["skeleton"]["path"]))' "$KIPI_REPO/instance-registry.json" 2>/dev/null || true)"
  fi
  rc=0
  _n_installed=0
  _n_skipped=0
  _n_failed=0
  _failed_labels=""
  echo "install-jobs: enumerating committed templates via $(templates_source)"
  while IFS= read -r _p; do
    [ -e "$_p" ] || continue
    _label="$(basename "$_p" .plist)"
    if grep -q "kipi-scope: skeleton-only" "$_p" && [ "$(cd "$KIPI_REPO" && pwd -P)" != "$_skeleton" ]; then
      echo "  skipped (skeleton-only): $_label"
      _n_skipped=$((_n_skipped + 1))
      continue
    fi
    if bash "$0" "$_label"; then
      _n_installed=$((_n_installed + 1))
    else
      rc=1
      _n_failed=$((_n_failed + 1))
      _failed_labels="$_failed_labels $_label"
      echo "  FAILED: $_label" >&2
    fi
  done <<EOF
$(committed_templates)
EOF

  # THE COUNT IS THE POINT. Before 2026-09-07 this loop ended at `exit "$rc"` and
  # printed no total, so a run that installed 12 of 15 committed jobs looked exactly
  # like a run that installed all of them: a wall of per-job success lines and exit
  # 0. The founder's only signal was silence. Every committed label now lands in
  # exactly one of these three counts, and a template that could not be installed
  # is named and carries the exit code out.
  echo "install-jobs: $_n_installed installed, $_n_skipped skipped, $_n_failed failed (of $((_n_installed + _n_skipped + _n_failed)) committed)"
  if [ "$_n_failed" -gt 0 ]; then
    echo "install-jobs: could not install:$_failed_labels" >&2
  fi
  exit "$rc"
fi

LABEL="$1"
shift
TEMPLATE="$(template_for_label "$LABEL")"

if [ -z "$TEMPLATE" ] || [ ! -f "$TEMPLATE" ]; then
  echo "ERROR: no committed plist template for label '$LABEL' (searched via $(templates_source))" >&2
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

# ASK-1178: __USER__ joined __KIPI_REPO__ and __HOME__ because a launchd job that
# shells the `claude` CLI needs USER/LOGNAME set. Measured 2026-08-30: with them
# absent the CLI answers "Not logged in - please run /login" (the keychain lookup
# needs them); with USER set, the same command returned a real calendar answer.
# Adding the token WITHOUT adding it to assert_rendered below would have been the
# worse half of the change: an unsubstituted placeholder that plutil accepts and
# launchd fails on at fire time, silently, which is the exact class assert_rendered
# was written for.
# ONE LINE, and it has to stay one line. test-install-plist.sh builds its negative
# self-test by neutering the substituter with `sed -i 's|^  sed -e .*$|  cat ...|'`.
# The first version of the __USER__ change wrapped this onto a second line; the
# harness replaced line one and left `      -e "s|__USER__|..."` dangling, so the
# CONTROL case exited 127 and the whole probe proved nothing. The test was right
# and the code was wrong: a renderer whose shape the harness depends on is part of
# the harness contract.
# __ROOT__ joined the set 2026-09-07 with the enumerator widening. It is
# automation/com.kipi.voice-refresh.plist's spelling of the repo root: that template
# was written against its own installer (automation/install-voice-refresh.sh) while
# it sat outside the glob, so it never had to agree with anything. Now that --all
# reaches it, one substituter handles both spellings rather than the file being
# reachable and unrenderable, which is a louder failure than the silence it replaces
# but still a failure.
RENDER_USER="$(id -un)"
render() {
  # sed with | as the delimiter: the path replacements contain /.
  sed -e "s|__KIPI_REPO__|$KIPI_REPO|g" -e "s|__ROOT__|$KIPI_REPO|g" -e "s|__HOME__|$HOME|g" -e "s|__USER__|$RENDER_USER|g" "$TEMPLATE"
}

# A template that still carries a placeholder after substitution is a broken
# render, and launchd would accept it silently and fail at fire time. Fail loud.
#
# The pattern is the CLASS (__ANY_TOKEN__), not the four names this script
# substitutes. Measured 2026-09-07: an allowlist of known tokens passes any
# template written against a fifth spelling -- exactly how __ROOT__ went four weeks
# unnoticed. Catching the shape means a new token is a loud failure on the first
# run instead of a job that plutil accepts and launchd fails at fire time.
assert_rendered() {
  local rendered_file="$1"
  local left
  # `|| true` is load-bearing, not defensive noise. grep exits 1 when it matches
  # NOTHING, which here is the healthy case; under `set -e` the assignment then
  # killed the script with exit 1 and no message at all. Caught 2026-09-07 by the
  # reproducer going from 1 failing label to 13, which is what a guard that fires
  # on every input looks like from the outside.
  left="$(grep -o '__[A-Z][A-Z0-9_]*__' "$rendered_file" | sort -u | tr '\n' ' ' || true)"
  if [ -n "$left" ]; then
    echo "ERROR: unsubstituted placeholder remains in $rendered_file: $left" >&2
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

# STAGE, VALIDATE, THEN MOVE. This used to render straight onto $PLIST and check
# afterwards, so a template that failed either check left the broken copy sitting in
# LaunchAgents -- and on a REinstall it had already overwritten a job that worked.
# The move is last, so a refusal leaves the machine exactly as it was.
STAGED="$(mktemp "${TMPDIR:-/tmp}/kipi-plist-XXXXXX")"
trap 'rm -f "$STAGED"' EXIT
render > "$STAGED"
assert_rendered "$STAGED"

# plutil is the only thing that proves the rendered XML is a loadable plist.
if command -v plutil >/dev/null 2>&1; then
  plutil -lint "$STAGED" >/dev/null
fi
mv "$STAGED" "$PLIST"

UID_="$(id -u)"
# KIPI_LAUNCHCTL is a test seam only (test_lessons_daily_label.py runs --all in a
# tmp tree with a tmp HOME and must never bootstrap a real job); production
# never sets it.
"${KIPI_LAUNCHCTL:-launchctl}" bootout "gui/$UID_/$LABEL" 2>/dev/null || true
"${KIPI_LAUNCHCTL:-launchctl}" bootstrap "gui/$UID_" "$PLIST"
echo "installed $LABEL -> $PLIST (KIPI_REPO=$KIPI_REPO)"
"${KIPI_LAUNCHCTL:-launchctl}" list | grep "$LABEL" || echo "  WARN: not loaded"
