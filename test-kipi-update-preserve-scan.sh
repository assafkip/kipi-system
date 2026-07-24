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

# --- fake INSTANCE: four no-flag cases + file and directory-symlink preserves ---
INST="$T/instance"; mkdir -p "$INST/q-system/.q-system/scripts" "$INST/q-system/output"; cd "$INST"; g init -q
echo skel > q-system/.q-system/scripts/skel.py             # in skeleton        -> keep, not flagged
echo MINE > q-system/.q-system/scripts/instance-only.py    # tracked instance-only -> PRESERVE (flag)
mkdir "$INST/private-target"
ln -s ../../../private-target q-system/.q-system/scripts/instance-link
echo old  > q-system/.q-system/scripts/skeleton-deleted.py # skeleton removed it -> let go, not flagged
echo data > q-system/output/report.json                    # excluded dir       -> not flagged
g add -A; g commit -qm init
echo scratch > q-system/.q-system/scripts/untracked.py     # untracked          -> existing path handles

OUT_FILE="$T/candidates.txt"
RECEIPT="$T/receipt.json"
python3 "$HELPER" --skeleton-archive "$ARCH" --instance "$INST" \
  --prefix q-system --skeleton-git "$SKEL" --receipt "$RECEIPT" \
  > "$OUT_FILE" 2>/dev/null
OUT="$(cat "$OUT_FILE")"

fail=0
assert_in()    { echo "$OUT" | grep -qx "$1" && echo "  PASS flagged: $1"     || { echo "  FAIL not flagged: $1"; fail=1; }; }
assert_out()   { echo "$OUT" | grep -q  "$1" && { echo "  FAIL wrongly flagged: $1"; fail=1; } || echo "  PASS not flagged: $1"; }

echo "=== preserve-scan assertions ==="
assert_in  "q-system/.q-system/scripts/instance-only.py"
assert_in  "q-system/.q-system/scripts/instance-link"
assert_out "skel.py"
assert_out "skeleton-deleted"
assert_out "untracked.py"
assert_out "report.json"
python3 - "$RECEIPT" "$OUT_FILE" <<'PY' || fail=1
import hashlib
import json
import pathlib
import sys

receipt = json.loads(pathlib.Path(sys.argv[1]).read_text())
output = pathlib.Path(sys.argv[2]).read_bytes()
assert receipt == {
    "candidate_count": 2,
    "complete": True,
    "schema_version": 1,
    "stdout_sha256": hashlib.sha256(output).hexdigest(),
}
print("  PASS verified completion receipt")
PY
python3 - "$HELPER" "$ARCH" <<'PY' || fail=1
import importlib.util
import pathlib
import sys
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("preserve_scan", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

module.subprocess.run = lambda *args, **kwargs: SimpleNamespace(returncode=128)
try:
    module.git_tracked("/repo", "q-system/file")
except RuntimeError:
    pass
else:
    raise AssertionError("git process error was treated as untracked")

def failed_walk(*args, **kwargs):
    kwargs["onerror"](PermissionError("fixture traversal failure"))

module.os.walk = failed_walk
try:
    module.skeleton_files(pathlib.Path(sys.argv[2]))
except PermissionError:
    pass
else:
    raise AssertionError("walk error produced a complete inventory")

print("  PASS scan errors fail closed")
PY

if [ "$fail" = 0 ]; then echo "ALL PASS"; exit 0; else echo "SOME FAILED"; exit 1; fi
