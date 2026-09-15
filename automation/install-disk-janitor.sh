#!/bin/bash
# install-disk-janitor.sh: put disk_janitor.py where launchd can always find it.
#
# The job runs from ~/.config/kipi/disk_janitor.py, NOT from this checkout. The
# repo checkout at ~/projects/kipi-system switches branches (203 worktrees on
# 2026-09-11), and a committed file vanishes from the working tree the moment
# another branch is checked out; com.kipi.pr86-review already uses ~/.config/kipi
# for the same reason. The repo copy is the source of truth; `--check` reports
# drift between the two so the installed copy cannot silently age.
#
#   install-disk-janitor.sh            copy script + plist, (re)bootstrap the job
#   install-disk-janitor.sh --check    exit 1 if the installed copy differs
#   install-disk-janitor.sh --kick     run the job now (launchd, --apply)
set -euo pipefail

# macOS-only by design: launchd is the scheduler this job lives in. On Linux
# (CI) there is nothing to install, so say so and exit clean.
if ! command -v launchctl >/dev/null 2>&1; then
  echo "install-disk-janitor: no launchd on this host, macOS-only, nothing to do" >&2
  exit 0
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/disk_janitor.py"
PLIST_SRC="$HERE/com.kipi.disk-janitor.plist"
DST_DIR="$HOME/.config/kipi"
DST="$DST_DIR/disk_janitor.py"
PLIST_DST="$HOME/Library/LaunchAgents/com.kipi.disk-janitor.plist"
LABEL="com.kipi.disk-janitor"
DOMAIN="gui/$(id -u)"

case "${1:-}" in
  --check)
    rc=0
    cmp -s "$SRC" "$DST" || { echo "DRIFT: $DST differs from $SRC"; rc=1; }
    cmp -s "$PLIST_SRC" "$PLIST_DST" || { echo "DRIFT: $PLIST_DST differs from $PLIST_SRC"; rc=1; }
    launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || { echo "NOT LOADED: $LABEL"; rc=1; }  # portability-lint-skip
    [ "$rc" = 0 ] && echo "ok: installed copy matches repo, job loaded"
    exit "$rc"
    ;;
  --kick)
    launchctl kickstart -k "$DOMAIN/$LABEL"  # portability-lint-skip
    echo "kicked $LABEL; output in $DST_DIR/disk-janitor.out"
    exit 0
    ;;
  "")
    ;;
  *)
    echo "usage: $0 [--check|--kick]" >&2; exit 2 ;;
esac

mkdir -p "$DST_DIR" "$(dirname "$PLIST_DST")"
install -m 0755 "$SRC" "$DST"
install -m 0644 "$PLIST_SRC" "$PLIST_DST"
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true  # portability-lint-skip
launchctl bootstrap "$DOMAIN" "$PLIST_DST"  # portability-lint-skip
launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 && echo "installed + loaded: $LABEL (daily 04:30, --apply)"  # portability-lint-skip
