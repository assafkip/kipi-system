#!/bin/bash
set -euo pipefail

# kipi-push-upstream.sh - Push generic improvements from an instance back to the skeleton
# Usage: Run from an instance directory that has a q-system/ subtree
#   ./kipi-push-upstream.sh

SKELETON_REMOTE="${KIPI_SKELETON_REMOTE:-https://github.com/assafkip/kipi-system.git}"
SKELETON_BRANCH="main"
PREFIX="q-system"

# Safety check: are we in a git repo?
if [ ! -d .git ]; then
  echo "ERROR: Not in a git repo. Run from the instance root."
  exit 1
fi

# Safety check: does the subtree prefix exist?
if [ ! -d "$PREFIX" ]; then
  echo "ERROR: $PREFIX/ directory not found. Is this a kipi instance?"
  exit 1
fi

# Safety check: warn if instance-specific content might be in the subtree
echo "=== Pre-push safety check ==="
INSTANCE_CONTENT=$(grep -ril "KTLYST\|ktlyst\|CISO\|re-breach\|Assaf\|/Users/" "$PREFIX/" 2>/dev/null | grep -v ".git/" | head -5 || true)
if [ -n "$INSTANCE_CONTENT" ]; then
  echo "WARNING: Instance-specific content found in $PREFIX/:"
  echo "$INSTANCE_CONTENT"
  echo ""
  echo "Pushing instance content to the skeleton will break other instances."
  echo "Remove instance-specific content first, then re-run."
  exit 1
fi

echo "  No instance-specific content detected in $PREFIX/"
echo ""
# === Lessons read-only guard (lessons are skeleton-authored; instances are consumers) ===
git fetch -q "$SKELETON_REMOTE" "$SKELETON_BRANCH" 2>/dev/null || true
if ! python3 - "$PREFIX" <<'PYGUARD'
import subprocess, sys
prefix = sys.argv[1]
def lessons(ref):
    try:
        out = subprocess.run(["git", "ls-tree", "-r", ref], capture_output=True, text=True, check=True).stdout
    except Exception:
        return None
    d = {}
    for line in out.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) < 3 or parts[1] != "blob":
            continue
        norm = "/" + path
        if "/lessons/" in norm and path.endswith(".md") and not path.endswith("/README.md"):
            d["lessons/" + norm.split("/lessons/", 1)[1]] = parts[2]
    return d
st = subprocess.run(["git", "status", "--porcelain", "--", prefix], capture_output=True, text=True).stdout
for line in st.splitlines():
    p = line[3:]
    if "/lessons/" in ("/" + p) and p.endswith(".md") and not p.endswith("/README.md"):
        sys.stderr.write("uncommitted change under lessons/: " + p + "\n")
        sys.exit(1)
inst = lessons("HEAD") or {}
if inst:
    skel = lessons("FETCH_HEAD")
    if skel is None:
        sys.stderr.write("cannot verify lessons/ against the skeleton (fetch failed); refusing push to prevent a lessons leak (fail-closed)\n")
        sys.exit(1)
    for rel, blob in inst.items():
        if skel.get(rel) != blob:
            sys.stderr.write("lessons/ differs from skeleton: " + rel + "\n")
            sys.exit(1)
    for rel in skel:
        if rel not in inst:
            sys.stderr.write("lessons/ deleted vs skeleton: " + rel + " (run kipi update first if merely out of date)\n")
            sys.exit(1)
sys.exit(0)
PYGUARD
then
  echo "ERROR: lessons are skeleton-authored only; instances are read-only consumers."
  echo "Revert local q-system/lessons/ changes (kipi update restores them), then re-run."
  exit 1
fi

# === Registry-type guard (client/confidential instances must not be direct-clone) ===
REG=""
[ -f instance-registry.json ] && REG=instance-registry.json
[ -z "$REG" ] && [ -f "$PREFIX/instance-registry.json" ] && REG="$PREFIX/instance-registry.json"
if [ -n "$REG" ]; then
  if ! python3 - "$REG" <<'PYREG'
import json, sys
try:
    reg = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
ALLOW = {"car-research"}
bad = [i.get("name") for i in reg.get("instances", []) if i.get("type") == "direct-clone" and i.get("name") not in ALLOW]
if bad:
    sys.stderr.write("non-allowlisted direct-clone instances: " + ", ".join(str(b) for b in bad) + "\n")
    sys.exit(1)
sys.exit(0)
PYREG
  then
    echo "ERROR: a client/confidential instance is registered type=direct-clone (bypasses the lessons push guard)."
    echo "Convert it to subtree, or add it to the registry-type-guard allowlist if non-client."
    exit 1
  fi
fi

echo "=== Pushing to skeleton ==="
echo "  Remote: $SKELETON_REMOTE"
echo "  Branch: $SKELETON_BRANCH"
echo "  Prefix: $PREFIX"
echo ""

git subtree push --prefix="$PREFIX" "$SKELETON_REMOTE" "$SKELETON_BRANCH"

echo ""
echo "=== Done ==="
echo "Changes pushed to skeleton. Run kipi-update.sh to propagate to other instances."
