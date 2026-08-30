#!/bin/bash
# Pairs with kipi-update.sh SYSTEM_NEVER_COMMIT (ASK-797).
#
# Enforces the rule that file's own comment states and its array did not keep:
# "One filter, past both, or it is not a fix." auto-commit.py can PROPOSE any
# path as system exhaust; SYSTEM_NEVER_COMMIT is the only thing that declines.
# A path the skeleton itself gitignores is one the skeleton has already ruled
# instance-local, so committing it in an INSTANCE is always wrong -- and when
# that path is volatile (a timestamp, a lock, a pid) committing it blocks the
# instance from every future update, because the dirty-tree guard then reads
# the system's own churn as founder work.
#
# That is not hypothetical. .claude-integrity-armed holds an arm timestamp, the
# 2026-08-14 fleet run committed it on 13 of 22 instances, the tripwire rewrote
# it hours later, and all 13 were blocked forever. The defect was NAMED in a
# comment above the array while the array stayed one entry short, which is
# exactly the failure a prose rule makes and an executable one does not.
#
# Asserts an INVARIANT, not one path: any future volatile state file the
# skeleton gitignores is caught the day it appears, without anyone remembering
# this incident.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FAILURES=0

note() { printf '%s\n' "$*"; }

# --- the check, as a function so the negative self-test can drive it ----------
# $1: "live" uses the array as written; "mutated" drops the armed marker, which
# is how we prove the check can actually fail. A detector that has never been
# watched go red is indistinguishable from one that always passes.
run_check() {
  local mode="$1"
  python3 - "$SCRIPT_DIR" "$mode" <<'PY'
import os
import pathlib
import re
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
mode = sys.argv[2]
updater = root / "kipi-update.sh"

text = updater.read_text(encoding="utf-8")
match = re.search(r"^SYSTEM_NEVER_COMMIT=\(\n(.*?)^\)", text, re.S | re.M)
if not match:
    print("FAIL: SYSTEM_NEVER_COMMIT not found in kipi-update.sh")
    sys.exit(1)

never = []
for line in match.group(1).splitlines():
    line = line.strip()
    # Comments carry the reasoning and must not be read as entries. The array is
    # heavily commented on purpose; a parser that swallowed a comment line would
    # silently "cover" a path nobody listed.
    if not line or line.startswith("#"):
        continue
    never.append(line.strip('"').strip("'"))

if mode == "mutated":
    never = [p for p in never if "claude-integrity-armed" not in p]

# Candidates: files under the synced prefix that the SKELETON gitignores. Those
# are paths the skeleton has already declared instance-local. `git check-ignore`
# is the authority, never a hand-read of .gitignore -- negation rules and
# directory patterns do not survive being eyeballed.
#
# SCOPED TO WHAT THE GUARD CAN ACTUALLY SEE, and the first draft was not. It
# flagged 9 paths, all false positives, because it asked "is this gitignored
# system state?" instead of "can this ever block an instance?":
#
#   q-system/memory/**            memory is an INSTANCE_OWNED_SUBTREE, so the
#                                 dirty-tree guard EXCLUDES it by pathspec. A
#                                 dirty file there has never blocked anything.
#   .pytest_cache/**              pruned by every copy walk in kipi-update.sh,
#                                 so the sync cannot deliver it to an instance
#                                 (test-kipi-update-cache-exclusion.sh owns it).
#
# Both exclusions are the guard's own, not conveniences invented to get green:
# the subtree list is parsed from the updater, and the prune set is the same
# four directories stage_config_sync prunes. Measured against the live fleet,
# the narrowed detector and the observed blockers agree exactly -- the broad
# one named 9 paths that had blocked zero instances.
owned_match = re.search(r"^INSTANCE_OWNED_SUBTREES=\(\n(.*?)^\)", text, re.S | re.M)
if not owned_match:
    print("FAIL: INSTANCE_OWNED_SUBTREES not found; cannot scope to the guard")
    sys.exit(1)
owned = [l.strip() for l in owned_match.group(1).splitlines() if l.strip()]
if not owned:
    print("FAIL: INSTANCE_OWNED_SUBTREES parsed empty")
    sys.exit(1)

candidates = []
for dirpath, dirnames, filenames in os.walk(root / "q-system"):
    dirnames[:] = [
        d for d in dirnames
        if d not in (".git", "__pycache__", ".pytest_cache", ".venv", "node_modules")
    ]
    for name in filenames:
        rel = (pathlib.Path(dirpath) / name).relative_to(root)
        if any(str(rel).startswith(f"q-system/{sub}/") for sub in owned):
            continue
        candidates.append(str(rel))

if not candidates:
    print("FAIL: walked q-system/ and found no files; the check would pass vacuously")
    sys.exit(1)

proc = subprocess.run(
    ["git", "-C", str(root), "check-ignore", "--stdin"],
    input="\n".join(candidates), capture_output=True, text=True,
)
ignored = [line.strip() for line in proc.stdout.splitlines() if line.strip()]

# Only VOLATILE ignored state matters here. A gitignored file that no instance
# ever tracks costs nothing; the ones that block a fleet are the ones the system
# rewrites. auto-commit.py's classifier is the same judge the updater uses, so
# the test and the code agree on "is this the system's own exhaust?" by sharing
# one implementation rather than by two lists staying in step.
classifier = root / "q-system" / "hooks" / "auto-commit.py"
if not classifier.is_file():
    print(f"FAIL: classifier missing at {classifier}; cannot judge system exhaust")
    sys.exit(1)

proc = subprocess.run(
    ["python3", str(classifier), "--system-state"],
    input="\n".join(ignored), capture_output=True, text=True, cwd=str(root),
)
system_state = {line.strip() for line in proc.stdout.splitlines() if line.strip()}

missing = sorted(p for p in system_state if p not in never)

print(f"  ignored under q-system/ : {len(ignored)}")
print(f"  classified system state : {len(system_state)}")
print(f"  SYSTEM_NEVER_COMMIT     : {len(never)}")

if not system_state:
    print("FAIL: no candidate classified as system state; the check cannot fail")
    sys.exit(1)

if missing:
    print("FAIL: skeleton-gitignored system state absent from SYSTEM_NEVER_COMMIT:")
    for path in missing:
        print(f"    {path}")
    print("  Committing these in an instance blocks it from every future update.")
    sys.exit(1)

print("  PASS: every gitignored system-state path is declined")
sys.exit(0)
PY
}

note "=== 1. live array must cover every gitignored system-state path ==="
if run_check live; then
  note "  ok"
else
  note "  FAILED"
  FAILURES=$((FAILURES + 1))
fi

note ""
note "=== 2. negative self-test: dropping the armed marker MUST go red ==="
# Without this, a check that silently classified nothing would report PASS
# forever and read exactly like a working one.
if run_check mutated >/dev/null 2>&1; then
  note "  FAILED: the check passed with .claude-integrity-armed removed."
  note "  It is not detecting anything, so its green means nothing."
  FAILURES=$((FAILURES + 1))
else
  note "  ok: the check goes red when the entry is missing"
fi

note ""
if [ "$FAILURES" -eq 0 ]; then
  note "ALL PASS"
  exit 0
fi
note "$FAILURES check(s) FAILED"
exit 1
