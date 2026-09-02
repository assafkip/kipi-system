#!/bin/bash
# kipi promote <path>  --  move ONE general capability from this instance up to the skeleton.
#
# The up-rail (prd-lessons-rail-and-up-rail, Phase 4 of the morning-brief overhaul,
# founder-directed 2026-09-01: instances author general capabilities where the work
# happens; a capability is PROMOTED, it never lives in two places). Built in six
# slices; this file grows one slice per issue and refuses to promote for real until
# the scrub and the receipt slices exist (KIPI_PROMOTE_UNSCRUBBED=1 under pytest only).
#
# Slice 1 (issue lr-promote-path-containment, Codex finding-2 on the PRD):
#   containment. Anything but a plain relative path to a regular file whose REAL
#   path sits inside <instance>/q-system/ is refused with exit 2 and nothing is
#   copied. Refused: absolute input, any '..' segment, a symlink anywhere on the
#   path (the file or a parent), a directory, a device or fifo, anything outside
#   q-system/ (including the instance's own q-<name>/ tree). The destination is
#   the SAME relative path in the skeleton; parents are created.
#
# Trees (tests point both at tmp copies; production resolves them):
#   KIPI_PROMOTE_INSTANCE   the instance root (default: the current directory's repo root)
#   KIPI_PROMOTE_SKELETON   the skeleton root (default: instance-registry.json's skeleton path,
#                           read from the skeleton clone named by KIPI_HOME, the kipi CLI's home)
set -euo pipefail

usage() { echo "usage: kipi promote <relative path under q-system/>" >&2; }

if [ $# -lt 1 ] || [ -z "${1:-}" ]; then usage; exit 2; fi
REL="$1"

INSTANCE="${KIPI_PROMOTE_INSTANCE:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
if [ -z "${KIPI_PROMOTE_SKELETON:-}" ]; then
  KIPI_HOME_DIR="${KIPI_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
  KIPI_PROMOTE_SKELETON="$(python3 -c 'import json,sys,os; print(os.path.realpath(json.load(open(sys.argv[1]))["skeleton"]["path"]))' "$KIPI_HOME_DIR/instance-registry.json" 2>/dev/null || true)"
fi
SKELETON="${KIPI_PROMOTE_SKELETON:-}"
if [ -z "$SKELETON" ] || [ ! -d "$SKELETON/q-system" ]; then
  echo "kipi promote: cannot resolve the skeleton root (set KIPI_PROMOTE_SKELETON or a registry with a skeleton path)" >&2
  exit 2
fi

refuse() { echo "kipi promote: refused: $1" >&2; exit 2; }

# --- containment, checked on the INPUT before anything touches the disk ---
case "$REL" in
  /*) refuse "absolute paths are not promotable; give a path relative to the instance root ($REL)" ;;
esac
case "/$REL/" in
  */../*|*/./*) refuse "'.' and '..' segments are not allowed ($REL)" ;;
esac
case "$REL" in
  q-system/*) : ;;
  *) refuse "only files under q-system/ are promotable; instance-owned trees stay where they are ($REL)" ;;
esac

SRC="$INSTANCE/$REL"
# every component from the instance root down must be a real directory or file, never a link
_walk="$INSTANCE"
IFS='/' read -r -a _parts <<< "$REL"
for _part in "${_parts[@]}"; do
  _walk="$_walk/$_part"
  if [ -L "$_walk" ]; then refuse "symlink on the path: ${_walk#"$INSTANCE"/}"; fi
done
[ -e "$SRC" ] || refuse "no such file: $REL"
[ -d "$SRC" ] && refuse "directories are not promotable; promote one file at a time ($REL)"
[ -f "$SRC" ] || refuse "not a regular file (device, fifo or socket): $REL"
REAL="$(cd "$(dirname "$SRC")" && pwd -P)/$(basename "$SRC")"
case "$REAL" in
  "$(cd "$INSTANCE/q-system" && pwd -P)"/*) : ;;
  *) refuse "real path escapes q-system/: $REAL" ;;
esac

DEST="$SKELETON/$REL"

# --- scrub and receipt slices land in the next issues; until then this never promotes for real ---
# The seam needs THREE things: pytest's marker, the explicit opt-in, and an
# instance root under a temp directory. PYTEST_CURRENT_TEST alone is anyone's
# to set (Codex adversarial, issue lr-promote-path-containment); a real
# instance never lives under /tmp or /private/var/folders, so this cannot be
# turned into a working unscrubbed promoter for a real tree.
_tmp_rooted=0
case "$(cd "$INSTANCE" && pwd -P)" in
  /tmp/*|/private/tmp/*|/private/var/folders/*|/var/folders/*) _tmp_rooted=1 ;;
esac
if [ -z "${PYTEST_CURRENT_TEST:-}" ] || [ "${KIPI_PROMOTE_UNSCRUBBED:-}" != "1" ] || [ "$_tmp_rooted" != "1" ]; then
  echo "kipi promote: containment passed for $REL, but the scrub and receipt slices are not built yet; nothing copied" >&2
  exit 3
fi

# The copy IS the containment. The bash checks above give early, readable
# refusals; this walk is what holds: every component on both sides is opened
# with O_NOFOLLOW relative to the previous directory fd, so a symlink swapped
# in after the checks (source or destination) fails the open instead of being
# followed (Codex adversarial: TOCTOU and unchecked destination chain).
python3 - "$INSTANCE" "$SKELETON" "$REL" <<'PYCOPY' || refuse "contained copy failed for $REL (a component changed under us or is a symlink)"
import os, stat, sys
instance, skeleton, rel = sys.argv[1:4]
parts = rel.split("/")
def walk_dirs(root, names, create=False):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in names:
            if create:
                try:
                    os.mkdir(name, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            nfd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nfd
        return fd
    except OSError:
        os.close(fd)
        raise
sdir = walk_dirs(instance, parts[:-1])
try:
    sfd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=sdir)
finally:
    os.close(sdir)
try:
    if not stat.S_ISREG(os.fstat(sfd).st_mode):
        sys.exit(1)
    ddir = walk_dirs(skeleton, parts[:-1], create=True)
    try:
        dfd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, dir_fd=ddir, mode=0o644)
    finally:
        os.close(ddir)
    with os.fdopen(sfd, "rb") as src, os.fdopen(dfd, "wb") as dst:
        sfd = None
        while True:
            chunk = src.read(1 << 16)
            if not chunk:
                break
            dst.write(chunk)
finally:
    if sfd is not None:
        os.close(sfd)
PYCOPY
echo "promoted $REL -> $DEST"
