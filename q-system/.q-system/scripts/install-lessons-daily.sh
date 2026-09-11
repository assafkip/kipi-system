#!/bin/bash
# Install/refresh the cross-instance learning heartbeat. SKELETON ONLY.
#
# Why the refusal (prd-lessons-rail-and-up-rail, issue lr-lessons-label-collision):
# this file lives under q-system/.q-system/scripts/, so `kipi update` copies it
# into every one of the 25 instances. Run there, the old version rebound the
# label com.kipi.lessons-daily to that instance's copy of lessons-daily.sh,
# which then shelled kipi-update.sh from a tree where it cannot work. The
# consulting checkout carried exactly that copy on 2026-09-01. Now the script
# reads instance-registry.json next to its own repo root and refuses (exit 2,
# nothing written) unless that root IS the registry's skeleton path. A worktree
# of the skeleton refuses too, on purpose: installing from one bakes the
# worktree path into launchd (the Phase 2 lesson).
#
# The plist itself is the template com.kipi.lessons-daily.plist, rendered by
# install-plist.sh, so the schedule has one source (Weekday 1, 06:00).
#
# Extra arguments pass through to install-plist.sh, so
#   bash install-lessons-daily.sh --render-only /tmp/out.plist
# renders without touching launchd (what the test uses). Seam (tests only):
# KIPI_REGISTRY_FILE overrides the registry path.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
REGISTRY="${KIPI_REGISTRY_FILE:-$ROOT/instance-registry.json}"

if [ ! -f "$REGISTRY" ]; then
  echo "install-lessons-daily: no instance-registry.json at $ROOT; this job is skeleton-only and this tree is not the skeleton" >&2
  exit 2
fi
SKELETON="$(python3 -c 'import json,sys,os; print(os.path.realpath(json.load(open(sys.argv[1]))["skeleton"]["path"]))' "$REGISTRY")"
if [ "$(cd "$ROOT" && pwd -P)" != "$SKELETON" ]; then
  echo "install-lessons-daily: refusing. This job is skeleton-only; the registry names $SKELETON and this tree is $ROOT (a worktree or an instance). Nothing written." >&2
  exit 2
fi

exec bash "$HERE/install-plist.sh" com.kipi.lessons-daily "$@"
