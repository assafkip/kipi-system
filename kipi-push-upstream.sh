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
# The term list lives in q-system/.q-system/scripts/tripwire-terms.txt, shared with
# kipi-promote.sh's scrub (issue lr-promote-scrub-source); it used to be inline here.
# The tripwire file itself carries the terms, so it is excluded from its own scan.
TRIPWIRE_FILE="$PREFIX/.q-system/scripts/tripwire-terms.txt"
# one python read, not a grep pipeline: under set -e + pipefail a missing file
# aborted the pipeline before the fail-closed message below could print
TRIPWIRE="$(python3 -c 'import sys; print("|".join(l.strip() for l in open(sys.argv[1]) if l.strip() and not l.startswith("#")))' "$TRIPWIRE_FILE" 2>/dev/null || true)"
[ -n "$TRIPWIRE" ] || { echo "ERROR: tripwire term list missing or empty at $TRIPWIRE_FILE (fail-closed)"; exit 1; }
# -E: the terms are joined with '|', which basic grep reads as a literal pipe.
# Codex (issue lr-promote-scrub-source) caught the first version matching
# nothing at all; test_push_script_blocks_a_planted_term pins this.
INSTANCE_CONTENT=$(grep -rilE "$TRIPWIRE" "$PREFIX/" 2>/dev/null | grep -v ".git/" | grep -v "tripwire-terms.txt" | head -5 || true)
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
import json, subprocess, sys
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
def receipts():
    """Promotion receipts, read from the SKELETON at FETCH_HEAD, never from this
    instance's tree (issue lr-promote-receipt-hash-binding; the location rule is
    issue 11). Only rows with status done count, keyed by the guard's own
    lessons/<name> form and holding the set of blessed blobs. A receipt that
    cannot be read means no receipt: fail-closed."""
    import os
    override = os.environ.get("KIPI_PROMOTIONS_FILE")
    if override and not os.environ.get("PYTEST_CURRENT_TEST"):
        # the seam exists so a test can hand the guard a receipts file without a
        # bare skeleton; outside pytest it is a way to bless your own lesson
        sys.stdout.write("KIPI_PROMOTIONS_FILE is honoured only under pytest; reading receipts from FETCH_HEAD\n")
        override = None
    try:
        if override:
            with open(override, encoding="utf-8") as fh:
                raw = fh.read()
        else:
            raw = subprocess.run(["git", "show", "FETCH_HEAD:q-system/.q-system/promotions.receipts"],
                                 capture_output=True, text=True, check=True).stdout
    except Exception:
        return {}
    out = {}
    for line in raw.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue  # a damaged line is no receipt, never a traceback that blocks every push
        if row.get("status") != "done" or not isinstance(row.get("blob"), str) or not row["blob"]:
            continue
        base = row.get("base", "")
        if not isinstance(base, str):
            continue
        p = "/" + str(row.get("path", ""))
        if "/lessons/" not in p:
            continue
        out.setdefault("lessons/" + p.split("/lessons/", 1)[1], set()).add((row["blob"], base))
    return out
def blob_at(ref, path):
    """The blob of one path at a ref, "" when absent."""
    try:
        out = subprocess.run(["git", "ls-tree", ref, "--", path], capture_output=True, text=True, check=True).stdout.split()
        return out[2] if len(out) >= 3 else ""
    except Exception:
        return ""
# The receipts file itself ships inside the pushed subtree, so an instance could
# append its own row and push it (Claude adversarial review, issue 9). Receipts
# are skeleton-authored: any instance-side difference in that file refuses.
RECEIPTS_PATH = prefix.rstrip("/") + "/.q-system/promotions.receipts"
if blob_at("HEAD", RECEIPTS_PATH) != blob_at("FETCH_HEAD", RECEIPTS_PATH):
    sys.stderr.write("promotions.receipts differs from skeleton: receipts are skeleton-authored, run kipi update\n")
    sys.exit(1)
inst = lessons("HEAD") or {}
if inst:
    skel = lessons("FETCH_HEAD")
    if skel is None:
        sys.stderr.write("cannot verify lessons/ against the skeleton (fetch failed); refusing push to prevent a lessons leak (fail-closed)\n")
        sys.exit(1)
    blessed = receipts()
    for rel, blob in inst.items():
        if skel.get(rel) != blob:
            # a divergent lesson passes ONLY on a done receipt for exactly this blob
            # whose recorded base is what the skeleton holds NOW: once the skeleton
            # moved past the promotion the receipt is spent, and a stale instance
            # cannot push the receipted version back over the newer one
            if (blob, skel.get(rel, "")) in blessed.get(rel, ()):
                sys.stdout.write("promotion receipt honoured: " + rel + " (blob " + blob[:12] + ")\n")
                continue
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
