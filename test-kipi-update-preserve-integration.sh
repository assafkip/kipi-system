#!/bin/bash
# End-to-end proof for the warn+preserve guard in kipi-update.sh.
# RED: a raw `rsync --delete` deletes a tracked instance-only script (reproduces the
#      2026-06-24 fractional-cxo failure).
# GREEN: the snapshot -> preserve-scan -> rsync --delete -> restore sequence (lifted
#      verbatim from kipi-update.sh) keeps the file.
# Run: bash test-kipi-update-preserve-integration.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRESERVE_SCAN="$SCRIPT_DIR/kipi-update-preserve-scan.py"
T="$(mktemp -d)"
g() { git -c user.email=t@t -c user.name=t -c commit.gpgsign=false "$@"; }
prefix="q-system"

build_fixtures() {
  local root="$1"
  SKEL="$root/skeleton"; mkdir -p "$SKEL/q-system/.q-system/scripts"; ( cd "$SKEL"
    g init -q; echo skel > q-system/.q-system/scripts/skel.py; g add -A; g commit -qm init )
  ARCHIVE_TMP="$root/archive"; mkdir -p "$ARCHIVE_TMP"
  git -C "$SKEL" archive --format=tar HEAD -- q-system/ | tar -x -C "$ARCHIVE_TMP"
  path="$root/instance"; mkdir -p "$path/q-system/.q-system/scripts"; ( cd "$path"
    g init -q
    echo skel > q-system/.q-system/scripts/skel.py
    echo MINE > q-system/.q-system/scripts/instance-only.py
    g add -A; g commit -qm init )
}

TARGET="q-system/.q-system/scripts/instance-only.py"

echo "=== RED: raw rsync --delete (no guard) ==="
build_fixtures "$T/red"
rsync -a --delete "$ARCHIVE_TMP/q-system/" "$path/$prefix/" 2>/dev/null
if [ -f "$path/$TARGET" ]; then echo "  unexpected: file survived"; exit 1
else echo "  REPRODUCED: $TARGET was deleted"; fi

echo ""
echo "=== GREEN: snapshot -> preserve-scan -> rsync --delete -> restore ==="
build_fixtures "$T/green"
SNAP="$ARCHIVE_TMP/.snap"; mkdir -p "$SNAP/f"
( cd "$path" && git ls-files -z --others -- "$prefix/" 2>/dev/null ) > "$SNAP/list" || true
python3 "$PRESERVE_SCAN" --skeleton-archive "$ARCHIVE_TMP" --instance "$path" \
  --prefix "$prefix" --skeleton-git "$SKEL" > "$SNAP/tracked" 2>"$SNAP/warn" || true
[ -s "$SNAP/warn" ] && cat "$SNAP/warn"
if [ -s "$SNAP/tracked" ]; then
  while IFS= read -r tf; do [ -n "$tf" ] && printf '%s\0' "$tf"; done < "$SNAP/tracked" >> "$SNAP/list"
fi
( cd "$path" && while IFS= read -r -d '' uf; do
    mkdir -p "$SNAP/f/$(dirname "$uf")" && cp -a "$uf" "$SNAP/f/$uf" 2>/dev/null || true
  done < "$SNAP/list" )
rsync -a --delete "$ARCHIVE_TMP/q-system/" "$path/$prefix/" 2>/dev/null
( cd "$path" && while IFS= read -r -d '' uf; do
    if ! { [ -e "$uf" ] || [ -L "$uf" ]; } && { [ -e "$SNAP/f/$uf" ] || [ -L "$SNAP/f/$uf" ]; }; then
      mkdir -p "$(dirname "$uf")" && cp -a "$SNAP/f/$uf" "$uf" && echo "  restored: $uf"
    fi
  done < "$SNAP/list" )

if [ -f "$path/$TARGET" ] && [ "$(cat "$path/$TARGET")" = "MINE" ]; then
  echo "  GREEN: $TARGET preserved with original content"; exit 0
else
  echo "  FAIL: $TARGET not preserved"; exit 1
fi
