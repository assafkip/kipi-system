#!/usr/bin/env python3
"""Reproducer + acceptance for the capability gate's declared_inert liveness check (ASK-345).

THE DEFECT IT CLOSES: `validate_manifest` checked only that a `declared_inert`
entry carries non-empty `path`/`reason`/`spillover_id` strings. It never asked
whether that id still resolves to a LIVE decision. So the pointer that is
supposed to make "parked as inert" a tracked wire-or-retire decision could point
at a `resolved` ledger row and the gate stayed GREEN. Measured on main
2026-08-19: three entries (`memory_outcomes.py`, `memory_reflect.py`,
`session_recall.py`) all cited `sp-cac8540c`, whose ledger status is `resolved`.
A silencer aimed at a closed decision silences forever, which is the same
silent-absence class the gate itself was built to make loud.

WHY THIS DRIVES THE FUNCTION DIRECTLY AND ALSO RUNS THE CLI: the semantics
(which status is live, which skips) are unit-drivable in milliseconds against
fixture ledgers, and case 1 additionally runs the real `capability-gate.py
--check-only` against a minimal fixture repo so "exits non-zero" is observed and
not assumed. The wiring block at the bottom is what stops the unit from drifting
away from its caller.

TWO SKIPS ARE LOAD-BEARING, NOT LENIENCE (fleet blast radius):
 - no `.prd-os/spillover.jsonl` at all -> skip. `kipi update` runs this gate in
   every instance; an instance without a ledger cannot resolve skeleton ids.
 - an id that is not IN this ledger -> skip. An instance that HAS a prd-os
   ledger has its OWN ids, so "unknown id" means "not my ledger to judge", not
   "dead pointer". Judging it would turn all 19 entries RED fleet-wide.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
GATE = ROOT / "q-system/.q-system/scripts/capability-gate.py"

PASS = 0


def fail(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg):
    global PASS
    PASS += 1
    print(f"  ok: {msg}")


if not GATE.is_file():
    fail(f"capability-gate.py does not exist at {GATE}")

spec = importlib.util.spec_from_file_location("capgate", GATE)
capgate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capgate)

if not hasattr(capgate, "check_inert_spillover_live"):
    fail("capability-gate.py has no check_inert_spillover_live(); the declared_inert "
         "liveness check is missing, so a resolved spillover id silences the gate forever")

MANIFEST_REL = "q-system/.q-system/capability-manifest.json"


def build_repo(tmp, spillover_rows, inert_id="sp-fixture01"):
    """A minimal repo root: manifest + optional ledger. Deliberately NOT a git
    repo and with no instance-registry.json, so the gate runs in instance mode
    and the ledger lookup falls back to this root."""
    root = Path(tmp)
    manifest = {
        "schema_version": 1,
        "expected_tests": [],
        "required_data": [],
        "skeleton_only": [],
        "declared_inert": [{
            "path": "q-system/.q-system/scripts/fixture-engine.py",
            "reason": "fixture",
            "spillover_id": inert_id,
        }],
    }
    (root / "q-system/.q-system").mkdir(parents=True, exist_ok=True)
    (root / MANIFEST_REL).write_text(json.dumps(manifest, indent=2))
    if spillover_rows is not None:
        (root / ".prd-os").mkdir(parents=True, exist_ok=True)
        (root / ".prd-os/spillover.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in spillover_rows))
    return root, manifest


def errors_for(spillover_rows, inert_id="sp-fixture01"):
    with tempfile.TemporaryDirectory() as tmp:
        root, manifest = build_repo(tmp, spillover_rows, inert_id)
        errs = []
        capgate.check_inert_spillover_live(root, manifest, errs)
        return errs


def gate_rc(spillover_rows, inert_id="sp-fixture01"):
    with tempfile.TemporaryDirectory() as tmp:
        root, _ = build_repo(tmp, spillover_rows, inert_id)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        proc = subprocess.run(
            [sys.executable, str(GATE), "--repo-root", str(root), "--check-only"],
            capture_output=True, text=True, timeout=120, env=env)
        return proc.returncode, proc.stdout + proc.stderr


ROW_RESOLVED = {"id": "sp-fixture01", "status": "resolved", "desc": "fixture"}
ROW_OPEN = {"id": "sp-fixture01", "status": "open", "desc": "fixture"}
ROW_PROMOTED = {"id": "sp-fixture01", "status": "promoted", "desc": "fixture"}
ROW_OTHER = {"id": "sp-somebodyelse", "status": "open", "desc": "another ledger's item"}

# --- case 1: a resolved id is a dead pointer -> RED, and the CLI exits non-zero
errs = errors_for([ROW_RESOLVED])
if not errs:
    fail("a declared_inert entry citing a RESOLVED spillover id was accepted; "
         "that is the bug -- the silencer outlives the decision it points at")
if "sp-fixture01" not in " ".join(errs):
    fail(f"the error must name the dead id so it is fixable without a hunt: {errs}")
ok("declared_inert citing a resolved spillover id is RED and names the id")

rc, out = gate_rc([ROW_RESOLVED])
if rc == 0:
    fail(f"capability-gate.py --check-only exited 0 on a manifest with a dead "
         f"pointer; the check is not reached from main().\n{out}")
if "sp-fixture01" not in out:
    fail(f"gate output does not name the dead id:\n{out}")
ok(f"capability-gate.py --check-only exits {rc} (non-zero) and reports the dead pointer")

# --- case 2: an open id is a live decision -> GREEN
if errors_for([ROW_OPEN]):
    fail(f"an OPEN spillover id was rejected: {errors_for([ROW_OPEN])}")
rc, out = gate_rc([ROW_OPEN])
if rc != 0:
    fail(f"gate went RED on a live (open) pointer, rc={rc}:\n{out}")
ok("declared_inert citing an OPEN spillover id stays GREEN, CLI included")

# --- case 3: no ledger at all -> skip, GREEN (the fleet skip)
if errors_for(None):
    fail(f"a repo with no .prd-os/spillover.jsonl was judged: {errors_for(None)}. "
         "kipi update runs this gate in every instance; instances without a "
         "ledger cannot resolve skeleton ids and must stay GREEN")
rc, out = gate_rc(None)
if rc != 0:
    fail(f"gate went RED in a repo with no spillover ledger, rc={rc}:\n{out}")
ok("a repo with no .prd-os/spillover.jsonl skips the check and stays GREEN")

# --- case 4: promoted is a live decision, not a closed one
if errors_for([ROW_PROMOTED]):
    fail(f"a PROMOTED spillover id was rejected: {errors_for([ROW_PROMOTED])}. "
         "promoted means an issue exists and is still being audited "
         "(prd_runner spillover promoted-audit); only `resolved` is terminal")
ok("declared_inert citing a PROMOTED spillover id stays GREEN (promoted is not terminal)")

# --- case 5: an id absent from THIS ledger is not this ledger's to judge
if errors_for([ROW_OTHER]):
    fail(f"an id absent from the ledger was judged: {errors_for([ROW_OTHER])}. "
         "an instance with its own prd-os ledger holds different ids; judging "
         "unknown ids turns every declared_inert entry RED fleet-wide")
ok("a spillover id absent from this ledger is skipped, not judged")

# --- case 6: last row wins, matching the ledger's own append-only read --------
if errors_for([ROW_OPEN, ROW_RESOLVED]) == []:
    fail("an id opened then resolved was read as live; the ledger is append-only "
         "and last-write-wins, so the LAST row for an id is its status")
if errors_for([ROW_RESOLVED, ROW_OPEN]):
    fail("an id resolved then re-opened was read as dead; last row wins")
ok("append-only ledger is read last-row-wins for an id, both directions")

# --- case 7: a malformed ledger line must not crash or silently pass ----------
with tempfile.TemporaryDirectory() as tmp:
    root, manifest = build_repo(tmp, [ROW_RESOLVED])
    p = root / ".prd-os/spillover.jsonl"
    p.write_text("not json at all\n\n" + p.read_text())
    errs = []
    capgate.check_inert_spillover_live(root, manifest, errs)
    if not errs:
        fail("a junk line ahead of the real row made the check give up; a "
             "corrupt line must be skipped, not treated as 'nothing to judge'")
ok("a malformed ledger line is skipped and the readable rows are still judged")

# --- wiring: main() actually calls this, and the real manifest is clean -------
src = GATE.read_text()
if "check_inert_spillover_live(root, manifest, errors)" not in src:
    fail("main() no longer calls check_inert_spillover_live; this suite would "
         "be testing dead code")
subprocess.run([sys.executable, "-c", "import ast,sys; ast.parse(open(sys.argv[1]).read())",
                str(GATE)], check=True)
ok("wiring: main() calls check_inert_spillover_live and the gate parses")

real_manifest = json.loads((ROOT / MANIFEST_REL).read_text())
real_errs = []
capgate.check_inert_spillover_live(ROOT, real_manifest, real_errs)
if real_errs:
    fail("this repo's own capability-manifest.json has dead inert pointers: "
         + " | ".join(real_errs))
ok("this repo's capability-manifest.json cites only live spillover ids")

print(f"PASS: {PASS}/{PASS} declared_inert spillover-liveness checks")
