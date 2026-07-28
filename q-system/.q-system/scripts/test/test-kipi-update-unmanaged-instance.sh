#!/usr/bin/env bash
# A registered instance that receives NOTHING must say so out loud.
#
# `reddit-build-radar` sat in instance-registry.json`s `instances` array with 0
# of its 28 capabilities originating from the skeleton, while every other
# instance carried 268-281. `kipi update` printed one quiet line -- "SKIP:
# standalone" -- and exited 0, so the fleet counted 24 governed instances when
# one of them had no token-guard, no .claude/rules/, no capability gate at all.
# Silent non-propagation has fleet precedent (the launchd income scanners, 6
# days). Hence the two properties this file pins:
#
#   1. a non-propagating instance that DECLARES itself (skeleton_managed:false)
#      is skipped quietly and named as declared -- the deliberate case, on the
#      record and machine-readable;
#   2. a non-propagating instance that does NOT declare itself is flagged in the
#      summary and fails the run. Quiet is the failure mode, so the absence of a
#      declaration cannot be the absence of a message.
#
# Property 3 runs against the REAL registry: every entry that receives nothing
# is declared. That is the assertion ASK-117 actually closes.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

GATE_REL="q-system/.q-system/scripts/propagation-leak-gate.py"
BASELINE_REL="q-system/.q-system/state/propagation-leak-baseline.json"

# The smallest skeleton kipi-update.sh will run: enough to clear its preflights
# and reach the instance loop, nothing more. No real instance directory is
# needed -- every entry here is one the updater must refuse to sync.
build_skeleton() {
  local sk="$1"
  mkdir -p "$sk/q-system/.q-system/scripts" "$sk/q-system/.q-system/state" \
           "$sk/q-system/marketing" "$sk/plugins"
  cp "$ROOT/kipi-update.sh" "$sk/kipi-update.sh"
  cp "$ROOT/kipi-update-preserve-scan.py" "$sk/kipi-update-preserve-scan.py"
  cp "$ROOT/$GATE_REL" "$sk/$GATE_REL"
  cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
     "$sk/q-system/.q-system/scripts/containment-targets.py"
  cp "$ROOT/validate-separation.py" "$sk/validate-separation.py"
  # Not the repo's committed baseline: that one is armed against THIS repo's
  # content and its permits refuse when loaded over a synthetic skeleton.
  cat > "$sk/$BASELINE_REL" <<'BASELINE_JSON'
{
  "schema_version": 1,
  "blocking_classes": [
    "case_proof_gap",
    "client_identity",
    "dated_interaction",
    "pricing",
    "relationship",
    "source_identity",
    "sourced_interaction"
  ],
  "classifier_sha256": null,
  "entries": []
}
BASELINE_JSON
  printf 'generic skeleton content\n' > "$sk/q-system/marketing/outreach.md"
  ( cd "$sk" && G init -q && G add -A -f && G commit -qm skel )
}

# Runs the updater against a registry written for this case. Exit code is
# captured, never allowed to abort the test, because both outcomes are data.
run_with_registry() {
  local sk="$1" registry_json="$2"
  printf '%s\n' "$registry_json" > "$sk/instance-registry.json"
  RUN_OUT="$(bash "$sk/kipi-update.sh" --dry-run 2>&1)" && RUN_RC=0 || RUN_RC=$?
}

# --------------------------------------------------------------- property 1
# The deliberate case. A declared entry is not a defect, so it must not shout,
# but it must be named as DECLARED -- "SKIP: standalone" alone reads the same
# whether a human decided it or nobody noticed.
assert_declared_is_quiet_and_named() {
  local work sk
  work="$(mktemp -d)"; sk="$work/skel"
  build_skeleton "$sk"
  mkdir -p "$work/declared"
  run_with_registry "$sk" '{"instances":[{"name":"declared","path":"'"$work"'/declared","subtree_prefix":null,"type":"standalone","skeleton_managed":false}]}'

  echo "$RUN_OUT" | grep -q "declared not skeleton-managed" || \
    fail "a declared non-propagating instance was not named as declared: $RUN_OUT"
  if echo "$RUN_OUT" | grep -q "UNDECLARED NON-PROPAGATING"; then
    fail "a declared instance was flagged as undeclared: $RUN_OUT"
  fi
  [ "$RUN_RC" -eq 0 ] || fail "a declared instance failed the run (rc=$RUN_RC): $RUN_OUT"

  echo "PASS: a declared non-propagating instance is named as declared and does not fail the run"
}

# --------------------------------------------------------------- property 2
# The whole point. An entry that receives nothing and says nothing about it is
# the reddit-build-radar shape, and it has to be impossible to miss: named in
# the summary AND non-zero exit. A message alone is not enough -- `kipi update`
# prints ~40 lines per instance and the founder reads the summary.
assert_undeclared_is_flagged_and_fails() {
  local work sk
  work="$(mktemp -d)"; sk="$work/skel"
  build_skeleton "$sk"
  mkdir -p "$work/undeclared"
  run_with_registry "$sk" '{"instances":[{"name":"undeclared","path":"'"$work"'/undeclared","subtree_prefix":null,"type":"standalone"}]}'

  echo "$RUN_OUT" | grep -q "UNDECLARED NON-PROPAGATING" || \
    fail "an undeclared non-propagating instance was skipped quietly: $RUN_OUT"
  echo "$RUN_OUT" | grep -q "undeclared" || \
    fail "the flag did not name the instance: $RUN_OUT"
  [ "$RUN_RC" -ne 0 ] || \
    fail "an undeclared non-propagating instance exited 0: $RUN_OUT"

  echo "PASS: an undeclared non-propagating instance is flagged in the summary and fails the run"
}

# A missing path is a DIFFERENT skip and must keep its own message. Folding it
# into the non-propagation flag would make a moved directory read as an
# ungoverned instance, which is a false alarm on a real and common state.
assert_missing_path_is_not_the_same_flag() {
  local work sk
  work="$(mktemp -d)"; sk="$work/skel"
  build_skeleton "$sk"
  run_with_registry "$sk" '{"instances":[{"name":"gone","path":"'"$work"'/does-not-exist","subtree_prefix":"q-system","type":"subtree"}]}'

  echo "$RUN_OUT" | grep -q "does not exist" || \
    fail "a missing instance path lost its own message: $RUN_OUT"
  if echo "$RUN_OUT" | grep -q "UNDECLARED NON-PROPAGATING"; then
    fail "a missing path was misreported as an undeclared non-propagating instance: $RUN_OUT"
  fi

  echo "PASS: a missing instance path keeps its own message and is not the non-propagation flag"
}

# --------------------------------------------------------------- property 3
# The live registry. A fixture proves the mechanism; this proves the fleet is
# actually clean under it, which is what ASK-117 asked the registry to state.
assert_real_registry_declares_every_non_propagating_instance() {
  python3 - "$ROOT/instance-registry.json" <<'PY' || fail "the real registry has an undeclared non-propagating instance (above)"
import json, sys

registry = json.load(open(sys.argv[1], encoding="utf-8"))
undeclared = []
for entry in registry["instances"]:
    receives_nothing = (
        entry.get("type", "subtree") == "standalone"
        or not entry.get("subtree_prefix")
    )
    if receives_nothing and entry.get("skeleton_managed") is not False:
        undeclared.append(entry["name"])

if undeclared:
    print("undeclared non-propagating instances: " + ", ".join(undeclared))
    print('Add "skeleton_managed": false to each, or give it a subtree_prefix.')
    sys.exit(1)
print("real registry: every non-propagating instance is declared")
PY
  echo "PASS: the live instance-registry.json declares every entry that receives no propagation"
}

# reddit-build-radar by name, because the generic invariant above would also be
# satisfied by deleting the entry, and deleting it is not the recorded decision.
assert_reddit_build_radar_is_recorded() {
  python3 - "$ROOT/instance-registry.json" <<'PY' || fail "reddit-build-radar is not recorded as deliberately unmanaged (above)"
import json, sys

registry = json.load(open(sys.argv[1], encoding="utf-8"))
match = [e for e in registry["instances"] if e["name"] == "reddit-build-radar"]
if not match:
    print("reddit-build-radar is no longer in instances[]")
    sys.exit(1)
entry = match[0]
if entry.get("skeleton_managed") is not False:
    print("reddit-build-radar lacks \"skeleton_managed\": false")
    sys.exit(1)
if not entry.get("note"):
    print("reddit-build-radar has no note explaining why it is unmanaged")
    sys.exit(1)
print("reddit-build-radar: skeleton_managed=false, reason on the record")
PY
  echo "PASS: reddit-build-radar is on the record as deliberately not skeleton-managed"
}

assert_declared_is_quiet_and_named
assert_undeclared_is_flagged_and_fails
assert_missing_path_is_not_the_same_flag
assert_real_registry_declares_every_non_propagating_instance
assert_reddit_build_radar_is_recorded
echo "PASS: a registered instance that receives nothing either declares it or fails the run"
