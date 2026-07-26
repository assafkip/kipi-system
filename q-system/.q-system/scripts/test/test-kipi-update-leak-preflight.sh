#!/usr/bin/env bash
# The chokepoint: a leaked fact must stop `kipi update` BEFORE any instance is
# read or written, not be discovered afterwards across 23 repos.
#
# Detection after a fan-out is a post-mortem. Every instance already has the
# fact, and each one has it in a COMMIT, so cleanup is 23 history rewrites.
# Hence a preflight, and hence the two properties this file pins:
#
#   1. a NEW leak aborts the run with the instance byte-for-byte untouched;
#   2. the gate can never silently skip. A missing script, a missing baseline,
#      or a baseline built by a different classifier all ABORT. The adjacent
#      settings preflight wraps itself in `[ -f "$SYNC_CHECK" ]`, so deleting
#      its script turns a dead gate into a green run. This one must not.
#
# `--assert-no-silent-skip` runs only property 2 (the registered bypass check).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

GATE_REL="q-system/.q-system/scripts/propagation-leak-gate.py"
BASELINE_REL="q-system/.q-system/state/propagation-leak-baseline.json"

# A skeleton that is a real repo with a real instance registered against it.
# Everything the updater needs, nothing it does not.
build_skeleton() {
  local work="$1" sk="$work/skel" inst="$work/inst"
  mkdir -p "$sk/q-system/.q-system/scripts" "$sk/q-system/.q-system/state" \
           "$sk/q-system/marketing" "$sk/plugins"
  cp "$ROOT/kipi-update.sh" "$sk/kipi-update.sh"
  cp "$ROOT/kipi-update-preserve-scan.py" "$sk/kipi-update-preserve-scan.py"
  cp "$ROOT/$GATE_REL" "$sk/$GATE_REL"
  cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
     "$sk/q-system/.q-system/scripts/containment-targets.py"
  cp "$ROOT/validate-separation.py" "$sk/validate-separation.py"
  cp "$ROOT/$BASELINE_REL" "$sk/$BASELINE_REL"
  printf 'generic skeleton content\n' > "$sk/q-system/marketing/outreach.md"
  ( cd "$sk" && G init -q && G add -A -f && G commit -qm skel )
  printf '{"instances":[{"name":"testinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
    "$inst" > "$sk/instance-registry.json"

  mkdir -p "$inst/q-system" "$inst/.claude"
  printf 'instance state\n' > "$inst/q-system/tracked.md"
  ( cd "$inst" && G init -q && G add -A -f && G commit -qm inst )
}

instance_fingerprint() {
  # Every byte the updater could touch, plus the commit it is sitting on.
  ( cd "$1" && G rev-parse HEAD && G status --porcelain && \
    find . -path ./.git -prune -o -type f -print0 2>/dev/null | sort -z | xargs -0 shasum -a 256 2>/dev/null )
}

# ---------------------------------------------------------------- property 2
# A missing gate script, a missing baseline, and a classifier mismatch each
# ABORT. Silence here is the whole failure mode: a gate that skips when its
# script is gone reports success forever.
assert_no_silent_skip() {
  local work sk inst
  work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build_skeleton "$work"

  local before after out
  before="$(instance_fingerprint "$inst")"

  # (a) gate script deleted
  rm -f "$sk/$GATE_REL"
  out="$(bash "$sk/kipi-update.sh" 2>&1)" && fail "deleted gate script did not abort the run"
  echo "$out" | grep -qi "ABORT" || fail "deleted gate script aborted without saying so: $out"
  after="$(instance_fingerprint "$inst")"
  [ "$before" = "$after" ] || fail "instance was touched after a missing-gate abort"
  cp "$ROOT/$GATE_REL" "$sk/$GATE_REL"

  # (b) baseline file deleted
  rm -f "$sk/$BASELINE_REL"
  out="$(bash "$sk/kipi-update.sh" 2>&1)" && fail "missing baseline did not abort the run"
  echo "$out" | grep -qi "ABORT" || fail "missing baseline aborted without saying so: $out"
  after="$(instance_fingerprint "$inst")"
  [ "$before" = "$after" ] || fail "instance was touched after a missing-baseline abort"

  # (c) baseline stamped by a different classifier
  python3 -c "
import json,sys
p=sys.argv[1]
d=json.load(open('$ROOT/$BASELINE_REL'))
d['classifier_sha256']='0'*64
json.dump(d, open(p,'w'), indent=2)
" "$sk/$BASELINE_REL"
  out="$(bash "$sk/kipi-update.sh" 2>&1)" && fail "classifier mismatch did not abort the run"
  echo "$out" | grep -qi "ABORT" || fail "classifier mismatch aborted without saying so: $out"
  after="$(instance_fingerprint "$inst")"
  [ "$before" = "$after" ] || fail "instance was touched after a version-mismatch abort"

  echo "PASS: missing script, missing baseline and classifier mismatch each ABORT, no instance touched"
}

# ---------------------------------------------------------------- property 1
# A new leak stops the run with the instance untouched. Requires an ARMED
# baseline: an unarmed one has nothing to measure a delta against.
assert_leak_aborts_before_any_instance_is_written() {
  local work sk inst before after out
  work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build_skeleton "$work"

  # Arm the baseline against the clean skeleton, then plant the leak.
  python3 - "$sk" <<'PY'
import hashlib, importlib.util, json, sys
from pathlib import Path
sk = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location(
    "gate", sk / "q-system/.q-system/scripts/propagation-leak-gate.py")
gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
findings = gate.scan_propagation_sources(sk)
digest = hashlib.sha256((sk / "validate-separation.py").read_bytes()).hexdigest()
reasons = {
    key: f"reviewed in fixture: {key[0]} [{key[1]}] {key[3][:8]}"
    for key in gate.blocking_fingerprints(findings)
}
document = gate.build_baseline_document(findings, reasons, classifier_sha256=digest)
path = sk / "q-system/.q-system/state/propagation-leak-baseline.json"
path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
PY
  ( cd "$sk" && G add -A -f && G commit -qm armed )

  # A clean armed run must pass the gate, or the gate is not deployable.
  # Assert on the GATE, not on the updater's overall exit code: this minimal
  # fixture trips an unrelated capability gate later in the run, and folding
  # that into the assertion would make this test pass or fail for reasons that
  # have nothing to do with leaks.
  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  echo "$out" | grep -q "propagation leak gate: clean" || \
    fail "armed clean run did not pass the leak gate: $out"
  if echo "$out" | grep -q "ABORT: a fact absent"; then
    fail "armed clean run was blocked by the leak gate"
  fi

  # Now the leak, in a file the updater really copies.
  printf -- '- Client: Northwind Trading\n' >> "$sk/q-system/marketing/outreach.md"
  ( cd "$sk" && G add -A -f && G commit -qm leak )
  before="$(instance_fingerprint "$inst")"

  out="$(bash "$sk/kipi-update.sh" 2>&1)" && fail "a new leaked fact did NOT abort the run"
  after="$(instance_fingerprint "$inst")"
  [ "$before" = "$after" ] || fail "instance was written to despite the leak abort"
  echo "$out" | grep -qi "ABORT" || fail "abort did not announce itself: $out"
  echo "$out" | grep -q "outreach.md" || fail "abort did not name the file: $out"
  echo "$out" | grep -q "client_identity" || fail "abort did not name the fact class: $out"

  echo "PASS: a new leak aborts before any instance is read or written, naming file and class"
}

# ---------------------------------------------------------------- unarmed
# The baseline ships EMPTY on purpose (populating it is a human review of 243
# entries). Arming is a property of that committed file, not a flag in this
# script. Unarmed must be LOUD and must not block the fleet -- but it must also
# never be reachable by deleting something, which is why (a) and (b) above
# abort rather than fall through to this state.
assert_unarmed_reports_and_says_so() {
  local work sk inst out
  work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build_skeleton "$work"
  printf -- '- Client: Northwind Trading\n' >> "$sk/q-system/marketing/outreach.md"
  ( cd "$sk" && G add -A -f && G commit -qm leak )

  # Same discipline as the armed case: assert on the GATE, not on the updater's
  # overall exit code, which this minimal fixture trips for unrelated reasons.
  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  echo "$out" | grep -qi "NOT ENFORCING" || fail "unarmed run did not announce itself: $out"
  echo "$out" | grep -q "client_identity" || fail "unarmed run did not report what it saw: $out"
  if echo "$out" | grep -q "ABORT: a fact absent"; then
    fail "an unarmed baseline blocked the run"
  fi

  echo "PASS: an unarmed baseline reports loudly and does not block"
}

if [ "${1:-}" = "--assert-no-silent-skip" ]; then
  assert_no_silent_skip
  exit 0
fi

assert_no_silent_skip
assert_leak_aborts_before_any_instance_is_written
assert_unarmed_reports_and_says_so
echo "PASS: kipi update leak preflight is fail-closed, version-locked, and explicit when unarmed"
