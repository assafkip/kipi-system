#!/usr/bin/env python3
"""TEST STAND-IN for design-gap-check.py. See design-standard-check.py beside this file.

STUB_GAP = pass (default) | below | cannot | silent. Real contract since dc-03: 0 every
floored axis met, 2 an axis BELOW the exemplar floor, 3 COULD NOT MEASURE (bad input, no
served round, served bytes differ). Writes checks/gap.json only with --write, like the real one.
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("round_dir")
ap.add_argument("--url-base")
ap.add_argument("--refs")
ap.add_argument("--write", action="store_true")
a = ap.parse_args()
rd = Path(a.round_dir).resolve()
mode = os.environ.get("STUB_GAP", "pass")
if mode == "silent":      # exits 0 and writes nothing
    sys.exit(0)
if mode == "cannot":
    print("could not measure: stub says so", file=sys.stderr)
    sys.exit(3)
if not a.url_base:
    print("could not measure: no --url-base, so there is no served round", file=sys.stderr)
    sys.exit(3)
pages = {}
for p in sorted(rd.glob("*.html")):
    local = hashlib.sha256(p.read_bytes()).hexdigest()
    served = hashlib.sha256(urllib.request.urlopen(f"{a.url_base}/{p.name}", timeout=10).read()).hexdigest()
    if served != local:
        print(f"could not measure: served bytes differ from {p.name}", file=sys.stderr)
        sys.exit(3)
    pages[p.name] = {"sha256": local, "axes": {},
                     "below_floor": ["stub axis below floor"] if mode == "below" else []}
if a.write:
    (rd / "checks").mkdir(exist_ok=True)
    (rd / "checks" / "gap.json").write_text(
        json.dumps({"_stub": True, "_url_base": a.url_base, "pages": pages}, indent=2) + "\n")
sys.exit(2 if mode == "below" else 0)
