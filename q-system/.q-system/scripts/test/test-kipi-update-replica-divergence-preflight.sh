#!/usr/bin/env bash
# The chokepoint: a replica that has drifted AHEAD of the skeleton must stop
# `kipi update` BEFORE any instance is written.
#
# plugins/ rsyncs with `--delete`. A line that exists only in an instance's copy
# is not "inconsistent", it is scheduled for deletion -- and rsync's whole job is
# to make the destination match, so the loss is silent by design: no diff, no
# conflict, no prompt. Detection afterwards is a post-mortem across 23 repos.
#
# Live when this was armed (2026-09-02): prd_runner.py was identical in 25 roots
# and different in consulting, and the difference was `_reject_unrunnable_gate`,
# the only copy in 29 roots. An update run would have deleted the fleet's sole
# enforcer of a-gate-that-cannot-run-must-not-pass.
#
# Properties pinned here:
#   1. divergence between two replicas ABORTS with both instances untouched;
#   2. the gate can never silently skip -- deleted, zero-byte and comment-only
#      copies each ABORT, because `[ -f ]` proves a path exists, not that it
#      gates (the adjacent settings preflight has exactly that hole);
#   3. a declared path that resolves in NO root ABORTS rather than reporting
#      green over coverage it never had (exit 3, its own repair);
#   4. agreeing replicas let the run through -- a gate that cannot go green is
#      not a gate, it is an outage.
#
# `--assert-no-silent-skip` runs only property 2 (the registered bypass check).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

GATE_REL="q-system/.q-system/scripts/fleet-replica-divergence.py"
LEAK_REL="q-system/.q-system/scripts/propagation-leak-gate.py"
BASELINE_REL="q-system/.q-system/state/propagation-leak-baseline.json"
# The path the gate compares across roots. Named here rather than derived: this
# fixture must ARM the gate, and a gate whose declared paths resolve in no root
# disarms by design (see the DISARMED branch). A fixture that silently disarmed
# would pass every case below against a gate that never ran.
REPLICA_REL="plugins/prd-os/scripts/prd_runner.py"

build_skeleton() {
  local work="$1" sk="$work/skel" a="$work/inst-a" b="$work/inst-b"
  mkdir -p "$sk/q-system/.q-system/scripts" "$sk/q-system/.q-system/state" \
           "$sk/q-system/marketing" "$sk/plugins"
  cp "$ROOT/kipi-update.sh" "$sk/kipi-update.sh"
  cp "$ROOT/kipi-update-preserve-scan.py" "$sk/kipi-update-preserve-scan.py"
  cp "$ROOT/kipi-update-deletion-guard.py" "$sk/kipi-update-deletion-guard.py"
  cp "$ROOT/$GATE_REL" "$sk/$GATE_REL"
  cp "$ROOT/$LEAK_REL" "$sk/$LEAK_REL"
  cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
     "$sk/q-system/.q-system/scripts/containment-targets.py"
  cp "$ROOT/validate-separation.py" "$sk/validate-separation.py"
  # NOT the repo's committed baseline: that one is ARMED against THIS repo's
  # content, so its permits refuse when loaded over a synthetic skeleton.
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
  printf '{"instances":[{"name":"insta","path":"%s","subtree_prefix":"q-system","type":"subtree"},{"name":"instb","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
    "$a" "$b" > "$sk/instance-registry.json"

  local inst
  for inst in "$a" "$b"; do
    mkdir -p "$inst/q-system" "$inst/.claude"
    printf 'instance state\n' > "$inst/q-system/tracked.md"
    # EVERY declared path, read from the gate itself rather than listed here.
    # The first draft created only prd_runner.py; the other two declared paths
    # then resolved in 0 of 2 roots and the gate REFUSED (exit 3) on a fixture
    # meant to be green. A hardcoded list would go stale the same way the moment
    # DEFAULT_REPLICATED changes, and that failure would read as a gate bug.
    python3 - "$sk/$GATE_REL" "$inst" <<'SEED_PY'
import importlib.util, sys
from pathlib import Path
src, inst = Path(sys.argv[1]), Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("gate", src)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
for rel in mod.DEFAULT_REPLICATED:
    target = inst / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("shared replica content\n")
SEED_PY
    ( cd "$inst" && G init -q && G add -A -f && G commit -qm inst )
  done
}

instance_fingerprint() {
  ( cd "$1" && G rev-parse HEAD && G status --porcelain && \
    find . -path ./.git -prune -o -type f -print0 2>/dev/null \
      | sort -z | xargs -0 shasum -a 256 2>/dev/null )
}

# Every abort is proven POSITIONALLY, not by the updater's exit code. This
# fixture exits non-zero later anyway (the post-sync capability gate), so
# `run && fail` can never trigger and would contribute no coverage at all.
assert_aborts_untouched() {
  local sk="$1" a="$2" b="$3" what="$4" before_a after_a before_b after_b out
  before_a="$(instance_fingerprint "$a")"; before_b="$(instance_fingerprint "$b")"
  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  after_a="$(instance_fingerprint "$a")"; after_b="$(instance_fingerprint "$b")"
  if echo "$out" | grep -q -- "--- insta"; then
    fail "$what: the instance loop was ENTERED instead of aborting:
$out"
  fi
  echo "$out" | grep -qi "ABORT" || fail "$what aborted without saying so:
$out"
  [ "$before_a" = "$after_a" ] || fail "$what: inst-a was touched"
  [ "$before_b" = "$after_b" ] || fail "$what: inst-b was touched"
}

# --------------------------------------------------------------- property 2
assert_no_silent_skip() {
  local work sk a b
  work="$(mktemp -d)"; sk="$work/skel"; a="$work/inst-a"; b="$work/inst-b"
  build_skeleton "$work"
  # Arm the divergence so the run has something to abort on if the gate runs at
  # all -- then break the gate. Without this the cases below would pass against
  # an agreeing fleet, which proves nothing about the gate.
  printf 'shared replica content\n# drift only in b\n' > "$b/$REPLICA_REL"
  ( cd "$b" && G add -A -f && G commit -qm drift )

  rm -f "$sk/$GATE_REL"
  assert_aborts_untouched "$sk" "$a" "$b" "deleted gate script"

  # `[ ! -f ]` proves the path exists, not that it gates: a zero-byte .py is a
  # valid program that exits 0 emitting nothing. An interrupted write is both
  # quieter and likelier than a deletion, which is why the verdict line exists.
  : > "$sk/$GATE_REL"
  assert_aborts_untouched "$sk" "$a" "$b" "zero-byte gate script"
  printf '# nothing here\n' > "$sk/$GATE_REL"
  assert_aborts_untouched "$sk" "$a" "$b" "comment-only gate script"

  # A declared path that resolves in no root, ALONGSIDE one that does. Not the
  # all-dead case, which disarms by design; this is the shape that was live --
  # partial coverage reported as full.
  cp "$ROOT/$GATE_REL" "$sk/$GATE_REL"
  python3 - "$sk/$GATE_REL" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1]); t = p.read_text()
old = '    "plugins/kipi-core/skills/rca/scripts/rca-lint.py",\n'
assert t.count(old) == 1, "fixture anchor missing; the gate's default set moved"
p.write_text(t.replace(old, '    "plugins/nowhere/does-not-exist.py",\n'))
PY
  assert_aborts_untouched "$sk" "$a" "$b" "declared path resolving in no root"

  echo "PASS: deleted, zero-byte, comment-only and unresolvable-path each ABORT before the loop"
}

# --------------------------------------------------------------- property 1
assert_divergence_aborts_before_any_instance_is_written() {
  local work sk a b
  work="$(mktemp -d)"; sk="$work/skel"; a="$work/inst-a"; b="$work/inst-b"
  build_skeleton "$work"
  printf 'shared replica content\n# a line that exists ONLY here\n' > "$b/$REPLICA_REL"
  ( cd "$b" && G add -A -f && G commit -qm drift )
  assert_aborts_untouched "$sk" "$a" "$b" "diverged replica"
  echo "PASS: a replica ahead of the skeleton aborts with both instances byte-identical"
}

# --------------------------------------------------------------- property 4
# A gate that cannot go green is an outage, not a gate. This is the negative
# control for every case above: same fixture, replicas agreeing, and the run
# must get PAST the preflight.
assert_agreeing_replicas_pass_the_preflight() {
  local work sk a b out
  work="$(mktemp -d)"; sk="$work/skel"; a="$work/inst-a"; b="$work/inst-b"
  build_skeleton "$work"
  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  echo "$out" | grep -q "^fleet replica divergence: OK" \
    || fail "agreeing replicas did not produce an OK verdict:
$out"
  # The gate must be ARMED, not disarmed. A fixture whose declared paths resolve
  # nowhere would print DISARMED and pass every assertion above without the
  # comparison ever running.
  if echo "$out" | grep -q "fleet replica divergence: DISARMED"; then
    fail "the fixture disarmed the gate; nothing was actually compared:
$out"
  fi
  echo "$out" | grep -q "ABORT: a replica has drifted ahead" \
    && fail "agreeing replicas were reported as divergence:
$out"
  echo "PASS: agreeing replicas produce an armed OK verdict and the run continues"
}

case "${1:-}" in
  --assert-no-silent-skip) assert_no_silent_skip ;;
  *)
    assert_no_silent_skip
    assert_divergence_aborts_before_any_instance_is_written
    assert_agreeing_replicas_pass_the_preflight
    ;;
esac
