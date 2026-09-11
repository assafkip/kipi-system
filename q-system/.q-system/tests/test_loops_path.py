#!/usr/bin/env python3
"""loops_path: missing must never render as empty.

The scar this pins (2026-08-08): four readers, three paths, none of them the
file that had the data. A prospect's direct question sat unanswered 46 days
inside a correctly-written ledger that nothing could find, and two more warm
leads sat beside it. `load_open_loops()` returned None and every caller treated
that as "no open loops".

So the tests that matter here are not "does it find the file". They are:
  - does MISSING stay distinguishable from EMPTY, all the way to the caller
  - does a malformed file count as MISSING and not as empty
  - does the failure message say something a human would act on
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts"))
import loops_path as lp  # noqa: E402

failures = []


def ok(name, cond):
    if not cond:
        failures.append(name)


def _qroot(tmp, rel=None, payload=None):
    """A fake QROOT. rel places the ledger; None places nothing."""
    root = Path(tmp) / "q-system"
    (root / "output").mkdir(parents=True, exist_ok=True)
    (root / "memory").mkdir(parents=True, exist_ok=True)
    (Path(tmp) / "q-consult" / "output").mkdir(parents=True, exist_ok=True)
    if rel:
        p = (root / rel).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload if payload is not None else
                                {"loops": [{"id": "L-1", "status": "open"}]}))
    return root


LOOP = {"id": "L-2026-06-08-001", "target": "James (Portant.co)",
        "status": "open", "opened": "2026-06-08"}


with tempfile.TemporaryDirectory() as tmp:
    # ── the defect, stated as a test ──
    root = _qroot(tmp)                       # no ledger anywhere
    loops, status = lp.open_loops(root)
    ok("a missing ledger reports MISSING, not empty", status == lp.MISSING)
    ok("a missing ledger still returns a list (callers do not crash)",
       loops == [])

    empty = _qroot(tmp + "/e", "output/open-loops.json", {"loops": []})
    loops2, status2 = lp.open_loops(empty)
    ok("a real EMPTY ledger reports FOUND", status2 == lp.FOUND)
    ok("empty and missing are distinguishable", status != status2)

with tempfile.TemporaryDirectory() as tmp:
    # ── each historical location is found ──
    for rel in ("output/open-loops.json", "memory/open-loops.json"):
        root = _qroot(tmp + "/" + rel.replace("/", "_"), rel,
                      {"loops": [LOOP]})
        loops, status = lp.open_loops(root)
        ok(f"finds the ledger at {rel}", status == lp.FOUND and len(loops) == 1)

with tempfile.TemporaryDirectory() as tmp:
    # ── the instance path, which is where the real file actually was ──
    root = Path(tmp) / "q-system"
    (root / "output").mkdir(parents=True)
    inst = Path(tmp) / "q-consult" / "output"
    inst.mkdir(parents=True)
    (inst / "open-loops.json").write_text(json.dumps({"loops": [LOOP]}))
    loops, status = lp.open_loops(root)
    ok("finds the instance-content ledger, the one that was orphaned",
       status == lp.FOUND and loops and loops[0]["target"] == "James (Portant.co)")

with tempfile.TemporaryDirectory() as tmp:
    # ── a corrupt ledger tells you nothing, so it must not claim emptiness ──
    root = _qroot(tmp, "output/open-loops.json")
    (root / "output" / "open-loops.json").write_text("{ this is not json")
    loops, status = lp.open_loops(root)
    ok("a malformed ledger is MISSING, not empty", status == lp.MISSING)

with tempfile.TemporaryDirectory() as tmp:
    root = _qroot(tmp)
    msg = lp.describe_missing(root)
    ok("the failure message says NOT FOUND", "NOT FOUND" in msg)
    ok("the failure message denies the empty reading",
       "not the same as having no open loops" in msg)
    ok("the failure message lists where it looked", str(root) in msg)

# ── negative self-test: prove these assertions can fail ──
ok("the check itself can fail", not (lp.FOUND == lp.MISSING))

if failures:
    print(f"test_loops_path: {len(failures)} FAILED")
    for f in failures:
        print(f"  FAIL  {f}")
    raise SystemExit(1)
print("test_loops_path: all checks passed")
