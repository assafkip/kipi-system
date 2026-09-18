#!/usr/bin/env python3
"""TEST STAND-IN for design-gap-check.py. See design-standard-check.py beside this file.

STUB_GAP = pass (default) | below | cannot. Real contract: 0 every floored axis met,
2 an axis below floor or bad input. Writes checks/gap.json only with --write, like the real one.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

args = [a for a in sys.argv[1:] if not a.startswith("--")]
rd = Path(args[0]).resolve()
mode = os.environ.get("STUB_GAP", "pass")
if mode == "cannot":
    print("could not measure: stub says so", file=sys.stderr)
    sys.exit(2)
pages = {}
for p in sorted(rd.glob("*.html")):
    pages[p.name] = {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "axes": {},
                     "below_floor": ["stub axis below floor"] if mode == "below" else []}
if "--write" in sys.argv:
    (rd / "checks").mkdir(exist_ok=True)
    (rd / "checks" / "gap.json").write_text(json.dumps({"_stub": True, "pages": pages}, indent=2) + "\n")
sys.exit(2 if mode == "below" else 0)
