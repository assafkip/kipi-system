#!/bin/bash
# Deploys the versioned janitor to the path the launchd plists run
# (~/.config/kipi/disk_janitor.py). Until ASK-4234 the live file had no copy in
# any repo, so a rule could only be edited in place, untested. This keeps the
# previous file as .prev and refuses a copy that does not byte-match or does not
# list its rules under the system python3 the plists use.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)/disk_janitor.py"
DST="${KIPI_JANITOR_DST:-$HOME/.config/kipi/disk_janitor.py}"
/usr/bin/python3 "$SRC" --list >/dev/null || { echo "install-disk-janitor: --list failed under /usr/bin/python3" >&2; exit 1; }
[ -f "$DST" ] && cp "$DST" "$DST.prev"
cp "$SRC" "$DST.new" && mv "$DST.new" "$DST"
cmp -s "$SRC" "$DST" || { echo "install-disk-janitor: deployed copy differs" >&2; exit 1; }
echo "install-disk-janitor: $DST == $SRC ($(shasum "$DST" | cut -c1-12))"
