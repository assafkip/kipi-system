#!/usr/bin/env bash
# The skeleton remote is overridable at every site that CONSUMES it (GitHub issue #2).
#
# WHY. A fork of this skeleton carried a patchset of 20+ edits just to point the scripts at
# itself, and every upstream pull risked clobbering them. Three sites actually fetch or push a
# skeleton remote -- kipi-push-upstream.sh, kipi-update.sh, q-system/hooks/auto-update.sh -- and
# each now reads KIPI_SKELETON_REMOTE with the upstream URL as its default.
#
# WHAT THIS TEST USED TO LIE ABOUT (review round 2, major). An earlier version also asserted
# kipi-new-instance.sh and kipi-migrate.py "read" the variable and printed "all five sites".
# Both SEED from the local checkout and never touch a remote, so the variable was a dead write
# in each: assigned, never consumed. The test was green whether or not the value reached
# anything. It now proves the three consumers honour the override AND proves the two seeders
# carry no such dead write, so neither can creep back.
#
# Exit 0 when every consuming site is overridable and no seeder reintroduces a dead write,
# 1 with the first offender named.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT"

fail() { echo "FAIL: $*" >&2; exit 1; }

# 1. every CONSUMING shell site reads the variable with the upstream URL as its default
for f in kipi-push-upstream.sh kipi-update.sh q-system/hooks/auto-update.sh; do
  grep -qE 'KIPI_SKELETON_REMOTE:-https://github\.com/assafkip/kipi-system\.git' "$f" \
    || fail "$f does not read KIPI_SKELETON_REMOTE with the upstream default"
  # and nothing in the file still assigns the bare URL
  if grep -nE '^[A-Z_]*REMOTE="https://github\.com/assafkip/kipi-system\.git"' "$f"; then
    fail "$f still hardcodes the remote"
  fi
done

# 2. the two SEEDERS carry no KIPI_SKELETON_REMOTE dead write (review round 2, major).
#    Both seed from the local checkout; a read here is assigned-never-consumed and lies to the
#    fork maintainer. A negative check, so the dead write cannot creep back under a green suite.
#    Comment lines naturally NAME the variable (to explain why it is absent), so strip them
#    first and match only a real read: an assignment that expands it, or os.environ.get of it.
for f in kipi-new-instance.sh kipi-migrate.py; do
  if grep -vE '^[[:space:]]*#' "$f" | grep -nE 'KIPI_SKELETON_REMOTE'; then
    fail "$f reads KIPI_SKELETON_REMOTE but seeds from the local checkout -- dead write"
  fi
done

# 3. the shell scripts parse, and kipi-update.sh expands the override the same way
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

echo "PASS: KIPI_SKELETON_REMOTE is honoured at all three consuming sites; the two seeders carry no dead write"
