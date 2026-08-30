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
cp "$ROOT/kipi-update-deletion-guard.py" "$sk/kipi-update-deletion-guard.py"
  cp "$ROOT/$GATE_REL" "$sk/$GATE_REL"
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

# Every abort must be proven POSITIONALLY, not by the updater's exit code. This
# fixture always exits non-zero at the post-sync capability gate whether or not
# the preflight fired, so `run && fail` can never trigger and contributes no
# coverage at all. With the whole preflight deleted, the run synced and
# COMMITTED four files into the instance before any message assertion caught it.
assert_aborts_untouched() {
  local sk="$1" inst="$2" what="$3" before after out
  before="$(instance_fingerprint "$inst")"
  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  after="$(instance_fingerprint "$inst")"
  if echo "$out" | grep -q -- "--- testinst"; then
    fail "$what: the instance loop was ENTERED instead of aborting: $out"
  fi
  echo "$out" | grep -qi "ABORT" || fail "$what aborted without saying so: $out"
  [ "$before" = "$after" ] || fail "$what: instance was touched"
}

assert_no_silent_skip() {
  local work sk inst
  work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build_skeleton "$work"

  # (a) gate script deleted
  rm -f "$sk/$GATE_REL"
  assert_aborts_untouched "$sk" "$inst" "deleted gate script"
  cp "$ROOT/$GATE_REL" "$sk/$GATE_REL"

  # (a2) gate script TRUNCATED. `[ ! -f ]` proves the path exists, not that it
  # gates: a zero-byte .py is a valid program that exits 0, so an interrupted
  # write or a disk-full truncation turns the fleet chokepoint into a no-op
  # that emits nothing at all. Quieter, and likelier, than deletion.
  : > "$sk/$GATE_REL"
  assert_aborts_untouched "$sk" "$inst" "zero-byte gate script"
  printf '# nothing here\n' > "$sk/$GATE_REL"
  assert_aborts_untouched "$sk" "$inst" "comment-only gate script"
  cp "$ROOT/$GATE_REL" "$sk/$GATE_REL"

  # (b) baseline file deleted
  rm -f "$sk/$BASELINE_REL"
  assert_aborts_untouched "$sk" "$inst" "missing baseline"

  # (c) baseline stamped by a different classifier
  python3 -c "
import json,sys
p=sys.argv[1]
d=json.load(open('$ROOT/$BASELINE_REL'))
d['classifier_sha256']='0'*64
json.dump(d, open(p,'w'), indent=2)
" "$sk/$BASELINE_REL"
  assert_aborts_untouched "$sk" "$inst" "classifier mismatch"
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

  # (d) the skeleton is STAGED but not committed. The gate reads the index; the
  # updater copies HEAD via `git archive`. Any divergence means the gate clears
  # bytes that are not the bytes being propagated, and HEAD wins.
  printf -- '- Client: Northwind Trading\n' >> "$sk/q-system/marketing/outreach.md"
  ( cd "$sk" && G add -A -f && G commit -qm leak )
  printf 'generic skeleton content\n' > "$sk/q-system/marketing/outreach.md"
  ( cd "$sk" && G add q-system/marketing/outreach.md )   # staged fix, NOT committed
  assert_aborts_untouched "$sk" "$inst" "index and HEAD disagree"

  echo "PASS: deleted, truncated, comment-only, missing-baseline, version-mismatch and staged-not-committed each ABORT before the loop"
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

  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  after="$(instance_fingerprint "$inst")"
  [ "$before" = "$after" ] || fail "instance was written to despite the leak abort"

  # POSITIONAL, and the load-bearing assertion. The fingerprint above proves
  # "no tracked file changed", which is weaker than this file's own headline:
  # it prunes .git and skips non-regular files, so it is blind to index.lock
  # deletion, `git rebase --abort`, and the `git fetch`/`git pull --rebase` a
  # direct-clone instance gets at kipi-update.sh:565. Moving the whole preflight
  # INTO the loop left this test passing 4/4 until this line existed.
  if echo "$out" | grep -q -- "--- testinst"; then
    fail "the instance loop was ENTERED before the gate aborted: $out"
  fi
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

# ---------------------------------------------------------------- reporting
# The unarmed banner is the ONLY signal while the gate is not enforcing, so
# what it prints has to cover where a real fact would land. A sorted prefix did
# not: it printed the alphabetically-first 20 rows, which on the real repo were
# entirely .claude/ and plugins/ while 138 of 243 fingerprints sat under
# q-system/ and never appeared. Hence the per-area counts.
#
# This ran against the LIVE repo until 2026-07-25, when the baseline was armed
# and the live gate stopped reporting unarmed at all. A property has to be
# tested on a fixture that still has it.
assert_unarmed_report_covers_every_area() {
  local work sk out
  work="$(mktemp -d)"; sk="$work/skel"
  build_skeleton "$work"
  mkdir -p "$sk/plugins/demo"
  printf -- '- Client: Northwind Trading\n' > "$sk/plugins/demo/notes.md"
  printf -- '- Client: Northwind Trading\n' >> "$sk/q-system/marketing/outreach.md"
  ( cd "$sk" && G add -A -f && G commit -qm leaks )

  out="$(python3 "$sk/$GATE_REL" --check --repo-root "$sk" 2>&1)" || \
    fail "gate CLI failed on the fixture: $out"
  echo "$out" | grep -q "by area:" || \
    fail "unarmed report has no per-area counts: $out"
  echo "$out" | grep -q "q-system=" || \
    fail "unarmed report omits q-system, where real facts land: $out"
  echo "$out" | grep -q "plugins=" || \
    fail "unarmed report omits plugins: $out"
}

# A file carrying reviewed entries but a null stamp reads as armed to a human
# and enforces nothing. Silence there is worse than either state.
assert_entries_without_a_stamp_are_called_out() {
  local work sk out
  work="$(mktemp -d)"; sk="$work/skel"
  build_skeleton "$work"
  printf -- '- Client: Northwind Trading\n' >> "$sk/q-system/marketing/outreach.md"
  ( cd "$sk" && G add -A -f && G commit -qm leak )
  python3 - "$sk" <<'ARMPY'
import hashlib, importlib.util, json, sys
from pathlib import Path
sk = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location(
    "gate", sk / "q-system/.q-system/scripts/propagation-leak-gate.py")
gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
findings = gate.scan_propagation_sources(sk)
digest = hashlib.sha256((sk / "validate-separation.py").read_bytes()).hexdigest()
reasons = {k: f"reviewed: {k[0]} [{k[1]}] {k[3][:8]}"
           for k in gate.blocking_fingerprints(findings)}
doc = gate.build_baseline_document(findings, reasons, classifier_sha256=digest)
doc["classifier_sha256"] = None            # entries kept, stamp removed
path = sk / "q-system/.q-system/state/propagation-leak-baseline.json"
path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
ARMPY
  out="$(python3 "$sk/$GATE_REL" --check --repo-root "$sk" 2>&1)" || \
    fail "unstamped-with-entries run failed unexpectedly: $out"
  echo "$out" | grep -qi "IGNORED" || \
    fail "reviewed entries are silently inert while unstamped: $out"
}

# A baseline that is a JSON object but not a baseline must not slide into the
# not-enforcing branch, which is supposed to need an explicit unstamped file.
assert_a_junk_object_is_not_treated_as_unarmed() {
  local work sk out
  work="$(mktemp -d)"; sk="$work/skel"
  build_skeleton "$work"
  printf '{"hello": "world"}\n' > "$sk/$BASELINE_REL"
  out="$(python3 "$sk/$GATE_REL" --check --repo-root "$sk" 2>&1)" && \
    fail "a junk JSON object was accepted as an unarmed baseline: $out"
  echo "$out" | grep -qi "ABORT" || fail "junk baseline did not abort: $out"
}

if [ "${1:-}" = "--assert-no-silent-skip" ]; then
  assert_no_silent_skip
  assert_a_junk_object_is_not_treated_as_unarmed
  exit 0
fi

assert_no_silent_skip
assert_leak_aborts_before_any_instance_is_written
assert_unarmed_reports_and_says_so
assert_unarmed_report_covers_every_area
assert_entries_without_a_stamp_are_called_out
assert_a_junk_object_is_not_treated_as_unarmed
echo "PASS: report covers every area, unstamped entries are called out, junk aborts"
echo "PASS: kipi update leak preflight is fail-closed, version-locked, and explicit when unarmed"
