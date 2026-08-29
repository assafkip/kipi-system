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
 - an id that is not IN this ledger -> skip IN INSTANCE MODE ONLY. An instance
   that HAS a prd-os ledger has its OWN ids, so "unknown id" means "not my
   ledger to judge". In SKELETON mode the ledger is authoritative for the
   skeleton's own manifest, so an unknown id is a fabricated or typo'd pointer
   and goes RED (PR #224 review, minor).

WHERE THIS CHECK IS BLIND, STATED SO NOBODY COUNTS IT AS COVERAGE (PR #224
review, major): `.gitignore:43` excludes `*.jsonl` and un-ignores only
`receipts.jsonl`, so `.prd-os/spillover.jsonl` is NEVER in a fresh checkout.
`actions/checkout` in `.github/workflows/validate.yml` therefore takes the
no-ledger skip every run. CI cannot see a dead pointer. Liveness is enforced
where a ledger is readable -- the founder's skeleton checkout via `kipi check`,
and any worktree of it. Cases 8 and 10 pin that the skip is REPORTED rather than
silent, because a silent skip is the same silent-absence class this gate exists
to make loud.
"""

import importlib.util
import inspect
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


def build_repo(tmp, spillover_rows, inert_id="sp-fixture01", skeleton=False):
    """A minimal repo root: manifest + optional ledger. Deliberately NOT a git
    repo, so the ledger lookup falls back to this root. `skeleton=True` writes
    an instance-registry.json, which is the ONLY thing detect_mode() reads to
    call a checkout the skeleton."""
    root = Path(tmp)
    if skeleton:
        (root / "instance-registry.json").write_text(json.dumps({"instances": []}))
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


_SIG = inspect.signature(capgate.check_inert_spillover_live).parameters
for _p in ("notes", "mode"):
    if _p not in _SIG:
        fail(f"check_inert_spillover_live() takes no {_p!r} argument. Without it the "
             "check cannot report its own no-ledger skip (silent GREEN in CI, where "
             "*.jsonl is gitignored) and cannot treat an unknown id as RED in "
             "skeleton mode, where the ledger IS authoritative. PR #224 review.")


def run_check(spillover_rows, inert_id="sp-fixture01", skeleton=False):
    """Returns (errors, notes) from one direct call against a fixture repo."""
    with tempfile.TemporaryDirectory() as tmp:
        root, manifest = build_repo(tmp, spillover_rows, inert_id, skeleton=skeleton)
        errs, notes = [], []
        capgate.check_inert_spillover_live(
            root, manifest, errs, notes, "skeleton" if skeleton else "instance")
        return errs, notes


def errors_for(spillover_rows, inert_id="sp-fixture01", skeleton=False):
    return run_check(spillover_rows, inert_id, skeleton)[0]


def gate_rc(spillover_rows, inert_id="sp-fixture01", skeleton=False):
    with tempfile.TemporaryDirectory() as tmp:
        root, _ = build_repo(tmp, spillover_rows, inert_id, skeleton=skeleton)
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

# --- case 5: in INSTANCE mode an id absent from THIS ledger is not ours to judge
if errors_for([ROW_OTHER]):
    fail(f"an id absent from the ledger was judged in instance mode: "
         f"{errors_for([ROW_OTHER])}. an instance with its own prd-os ledger holds "
         "different ids; judging unknown ids turns every declared_inert entry RED "
         "fleet-wide, in 20+ instances at once")
ok("instance mode: a spillover id absent from this ledger is skipped, not judged")

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
if "check_inert_spillover_live(root, manifest, errors, notes, mode)" not in src:
    fail("main() no longer calls check_inert_spillover_live; this suite would "
         "be testing dead code")
subprocess.run([sys.executable, "-c", "import ast,sys; ast.parse(open(sys.argv[1]).read())",
                str(GATE)], check=True)
ok("wiring: main() calls check_inert_spillover_live and the gate parses")

# --- case 8: the no-ledger skip must be REPORTED, never silent -----------------
# This is the CI condition. `.gitignore:43` excludes `*.jsonl`, so a fresh
# actions/checkout has no spillover ledger and this check cannot fire there. A
# silent GREEN reads as "checked, clean"; it means "not checked". The gate has to
# say which.
errs, notes = run_check(None, skeleton=True)
if errs:
    fail(f"a repo with no ledger was judged: {errs}")
if not any("SKIPPED" in n and "spillover" in n.lower() for n in notes):
    fail(f"the no-ledger skip emitted no note: {notes}. CI takes this branch on "
         "EVERY run (*.jsonl is gitignored), so a silent skip lets the gate report "
         "GREEN on the exact dead-pointer manifest it was written to catch")
ok("the no-ledger skip is reported as SKIPPED in the gate's notes, not silent")

rc, out = gate_rc(None, skeleton=True)
if rc != 0:
    fail(f"gate went RED with no ledger, rc={rc}:\n{out}")
if "SKIPPED" not in out:
    fail(f"capability-gate.py --check-only printed no skip line with no ledger:\n{out}")
ok(f"capability-gate.py --check-only prints the skip and still exits {rc}")

# --- case 9: SKELETON mode, unknown id -> RED (the ledger is authoritative here)
errs, _ = run_check([ROW_OTHER], skeleton=True)
if not errs:
    fail("skeleton mode accepted a spillover_id that is in NO ledger row. In the "
         "skeleton the ledger IS this manifest's ledger, so an unknown id is a "
         "typo'd or fabricated pointer, not another ledger's business. All 19 real "
         "ids resolve today, so this reds zero real entries")
if "sp-fixture01" not in " ".join(errs):
    fail(f"the skeleton unknown-id error must name the id: {errs}")
ok("skeleton mode: a spillover id in NO ledger row is RED and names the id")

# --- case 10: mode is the ONLY difference between cases 5 and 9 ----------------
# Same fixture ledger, same manifest, different mode. If this pair ever agrees,
# either the fleet skip is gone (20+ instances RED) or the skeleton hole is back.
inst_errs, _ = run_check([ROW_OTHER], skeleton=False)
skel_errs, _ = run_check([ROW_OTHER], skeleton=True)
if bool(inst_errs) == bool(skel_errs):
    fail(f"instance and skeleton agree on an unknown id (instance={inst_errs}, "
         f"skeleton={skel_errs}); one of the two behaviours has been lost")
ok("unknown-id verdict differs by mode only: instance skips, skeleton reds")

# --- wiring: main() actually calls this, and the real manifest is clean -------
real_manifest = json.loads((ROOT / MANIFEST_REL).read_text())
real_errs, real_notes = [], []
capgate.check_inert_spillover_live(ROOT, real_manifest, real_errs, real_notes,
                                   capgate.detect_mode(ROOT, []))
if real_errs:
    fail("this repo's own capability-manifest.json has dead inert pointers: "
         + " | ".join(real_errs))
if any("SKIPPED" in n for n in real_notes):
    # Do NOT claim the manifest is clean when the ledger was never read. This is
    # what the assertion did in CI before PR #224 review: it printed "cites only
    # live spillover ids" while sitting on the three dead pointers.
    ok("this checkout has no spillover ledger, so manifest liveness was NOT "
       "checked here (expected in CI; run it where the ledger lives)")
else:
    ok("this repo's capability-manifest.json cites only live spillover ids "
       f"({len(real_manifest.get('declared_inert', []))} entries, ledger read)")

print(f"PASS: {PASS}/{PASS} declared_inert spillover-liveness checks")
