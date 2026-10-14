#!/usr/bin/env bash
# The skeleton remote is overridable at every site that names it (GitHub issue #2).
#
# WHY. A fork of this skeleton carried a patchset of 20+ edits just to point the scripts at
# itself, and every upstream pull risked clobbering them. Two scripts already honoured
# KIPI_SKELETON_REMOTE; three more hardcoded the URL. This holds all five to the same shape
# and proves the Python one reads the variable at import, not only that the text says so.
#
# Exit 0 when every site is overridable, 1 with the first offender named.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT"

fail() { echo "FAIL: $*" >&2; exit 1; }

# 1. every shell site reads the variable with the upstream URL as its default
for f in kipi-new-instance.sh kipi-push-upstream.sh kipi-update.sh q-system/hooks/auto-update.sh; do
  grep -qE '\$\{KIPI_SKELETON_REMOTE:-https://github\.com/assafkip/kipi-system\.git\}' "$f" \
    || fail "$f does not read KIPI_SKELETON_REMOTE with the upstream default"
  # and nothing in the file still assigns the bare URL
  if grep -nE '^[A-Z_]*REMOTE="https://github\.com/assafkip/kipi-system\.git"' "$f"; then
    fail "$f still hardcodes the remote"
  fi
done

# 2. the Python site reads it at import time
got="$(KIPI_SKELETON_REMOTE=https://example.invalid/fork.git python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("km", "kipi-migrate.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.SKELETON_REMOTE)')"
[ "$got" = "https://example.invalid/fork.git" ] || fail "kipi-migrate.py ignored KIPI_SKELETON_REMOTE (got $got)"
got="$(env -u KIPI_SKELETON_REMOTE python3 -c '
import importlib.util
spec = importlib.util.spec_from_file_location("km", "kipi-migrate.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.SKELETON_REMOTE)')"
[ "$got" = "https://github.com/assafkip/kipi-system.git" ] || fail "kipi-migrate.py default changed (got $got)"

# 3. the shell scripts parse, and the instance creator expands the variable the same way
for f in kipi-new-instance.sh kipi-update.sh; do bash -n "$f" || fail "$f does not parse"; done
got="$(KIPI_SKELETON_REMOTE=https://example.invalid/fork.git bash -c '
line=$(grep -E "^SKELETON_REMOTE=" kipi-update.sh); eval "$line"; echo "$SKELETON_REMOTE"')"
[ "$got" = "https://example.invalid/fork.git" ] || fail "kipi-update.sh assignment did not expand the override (got $got)"

# 4. the updater's provenance proof fetches the CONFIGURED remote, not the checkout's origin
#    (review round 1, major): two bare repos, a checkout whose origin is A, the override at B.
PROV="q-system/.q-system/scripts/skeleton-provenance.sh"
grep -q 'skeleton-provenance.sh"$' kipi-update.sh \
  || fail "kipi-update.sh does not name skeleton-provenance.sh"
grep -q 'bash "$PROVENANCE" "$SCRIPT_DIR" "$SKELETON_REMOTE" "$SKELETON_BRANCH"' kipi-update.sh \
  || fail "kipi-update.sh does not hand the configured remote to skeleton-provenance.sh"
if grep -n 'rev-parse "refs/remotes/origin/\$SKELETON_BRANCH"' kipi-update.sh; then
  fail "kipi-update.sh still resolves origin/<branch> as the provenance reference"
fi
grep -q 'PROVENANCE_OK=1' kipi-update.sh || fail "the proof does not tell fleet_ship_ref that HEAD is the proven ref"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
git init -q --bare "$T/A.git"; git init -q --bare "$T/B.git"
git init -q "$T/work"; git -C "$T/work" -c user.name=t -c user.email=t@t commit -q --allow-empty -m one
git -C "$T/work" branch -M main
git -C "$T/work" remote add origin "$T/A.git"; git -C "$T/work" push -q origin main
git -C "$T/work" push -q "$T/B.git" main
# checkout AT both: OK against B (the override), and its sha is HEAD
out="$(bash "$PROV" "$T/work" "$T/B.git" main)"
[ "$out" = "provenance: OK $(git -C "$T/work" rev-parse HEAD)" ] || fail "provenance did not pass at the override remote: $out"
# B moves ahead while origin (A) stays at HEAD: a fetch of origin would say AT; the override must say drift
git -C "$T/work" -c user.name=t -c user.email=t@t commit -q --allow-empty -m two
git -C "$T/work" push -q "$T/B.git" main
git -C "$T/work" reset -q --hard HEAD~1
bash "$PROV" "$T/work" "$T/A.git" main >/dev/null || fail "still AT origin, yet provenance against A failed"
if bash "$PROV" "$T/work" "$T/B.git" main >/dev/null 2>&1; then
  fail "provenance against the override remote passed while it is one commit behind it"
fi
# an unreachable remote fails closed
if bash "$PROV" "$T/work" "$T/nowhere.git" main >/dev/null 2>&1; then fail "an unreachable remote passed"; fi

# 5. no BSD-only sed -i in the instance creator (issue #1's shape)
if grep -nE "sed -i ''" kipi-new-instance.sh; then fail "kipi-new-instance.sh uses BSD-only sed -i ''"; fi  # portability-lint-skip (the pattern, not a use)

echo "PASS: KIPI_SKELETON_REMOTE is honoured at all five sites"
