#!/bin/bash
# Regression test for kipi-update-preserve-scan.py (the warn+preserve guard).
# Builds fake skeleton + instance git repos and asserts the helper flags exactly the
# tracked instance-only file, and nothing else. Run: bash test-kipi-update-preserve-scan.sh
set -euo pipefail

HELPER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/kipi-update-preserve-scan.py"
T="$(mktemp -d)"
g() { git -c user.email=t@t -c user.name=t -c commit.gpgsign=false "$@"; }

# --- fake SKELETON: has skel.py; once had skeleton-deleted.py then removed it ---
SKEL="$T/skeleton"; mkdir -p "$SKEL/q-system/.q-system/scripts"; cd "$SKEL"; g init -q
echo skel > q-system/.q-system/scripts/skel.py
echo old  > q-system/.q-system/scripts/skeleton-deleted.py
g add -A; g commit -qm init
g rm -q q-system/.q-system/scripts/skeleton-deleted.py; g commit -qm "remove skeleton-deleted.py"

# --- skeleton ARCHIVE = current skeleton HEAD's q-system/ (what rsync syncs) ---
ARCH="$T/archive"; mkdir -p "$ARCH"
git -C "$SKEL" archive --format=tar HEAD -- q-system/ | tar -x -C "$ARCH"

# --- fake INSTANCE: synced copy + the four no-flag cases + the one preserve case ---
INST="$T/instance"; mkdir -p "$INST/q-system/.q-system/scripts" "$INST/q-system/output"; cd "$INST"; g init -q
echo skel > q-system/.q-system/scripts/skel.py             # in skeleton        -> keep, not flagged
echo MINE > q-system/.q-system/scripts/instance-only.py    # tracked instance-only -> PRESERVE (flag)
echo old  > q-system/.q-system/scripts/skeleton-deleted.py # skeleton removed it -> let go, not flagged
echo data > q-system/output/report.json                    # excluded dir       -> not flagged
g add -A; g commit -qm init
echo scratch > q-system/.q-system/scripts/untracked.py     # untracked          -> existing path handles

OUT="$(python3 "$HELPER" --skeleton-archive "$ARCH" --instance "$INST" --prefix q-system --skeleton-git "$SKEL" 2>/dev/null)"

fail=0
assert_in()    { echo "$OUT" | grep -qx "$1" && echo "  PASS flagged: $1"     || { echo "  FAIL not flagged: $1"; fail=1; }; }
assert_out()   { echo "$OUT" | grep -q  "$1" && { echo "  FAIL wrongly flagged: $1"; fail=1; } || echo "  PASS not flagged: $1"; }

echo "=== preserve-scan assertions ==="
assert_in  "q-system/.q-system/scripts/instance-only.py"
assert_out "skel.py"
assert_out "skeleton-deleted"
assert_out "untracked.py"
assert_out "report.json"

if [ "$fail" = 0 ]; then echo "ALL PASS"; exit 0; else echo "SOME FAILED"; exit 1; fi
