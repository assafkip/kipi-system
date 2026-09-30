#!/usr/bin/env python3
"""TEST STAND-IN for design-impeccable-check.py. Never shipped next to the real gate.

The real producer needs node and the impeccable detector. Tests copy design-chain-gate.py into a
temp bin directory beside THIS file and run that copy, so the gate's own rule (producers are
siblings of the gate) selects the stand-in with no override in shipped code (dc-02).

STUB_IMPECCABLE = pass (default) | flag | dead | cannot | silent. Exit codes match the real
contract (dc-04): 0 control fired and pages clean, 1 control did not fire, 2 could not run,
3 a page flagged. It writes checks/impeccable.txt the way the real one does, marked as a
stand-in so a test can tell it from a real run. The real producer is exercised by
test/test_dc_impeccable_exit.py.
"""
import argparse
import os
import sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("round")
ap.add_argument("--url-base", required=True)
ap.add_argument("--detector")
ap.add_argument("--control")
ap.add_argument("--page", action="append", default=[])
ap.add_argument("--config")
a = ap.parse_args()
mode = os.environ.get("STUB_IMPECCABLE", "pass")
if mode == "silent":
    sys.exit(0)
if mode == "cannot":
    print("could not measure: stub says so", file=sys.stderr)
    sys.exit(2)
rd = Path(a.round)
fired = mode != "dead"
flagged = ["Home-laptop.html"] if mode == "flag" else []
out = rd / "checks" / "impeccable.txt"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(f"STAND-IN impeccable receipt (test/stub_producers)\nurl-base: {a.url_base}\n"
               f"pages given: {a.page}\npages flagged: {flagged or 'none'}\ncontrol fired: {'YES' if fired else 'NO'}\n")
print(f"wrote {out}")
sys.exit(1 if not fired else (3 if flagged else 0))
