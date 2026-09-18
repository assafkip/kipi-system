#!/usr/bin/env python3
"""TEST STAND-IN for design-standard-check.py. Never shipped next to the real gate.

The real producer needs playwright and chromium. Tests copy design-chain-gate.py into a
temp bin directory beside THIS file and run that copy, so the gate's own rule (producers
are siblings of the gate) selects the stand-in with no override in shipped code
(Sana, 2026-09-18, ASK-1796: no producer-directory override may exist in production).

STUB_STANDARD = pass (default) | fail | cannot. Exit codes match the real contract:
0 pass, 1 fail, 2 could not measure. Writes standard.json the way the real one does,
minus `measurements`, which is how a test tells a stand-in's output from a real run.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

page = Path(sys.argv[1]).resolve()
mode = os.environ.get("STUB_STANDARD", "pass")
if mode == "cannot":
    print("could not measure: stub says so", file=sys.stderr)
    sys.exit(2)
ok = mode == "pass"
std = page.parent / "standard.json"
entries = []
if std.is_file():
    try:
        prev = json.loads(std.read_text())
        entries = prev if isinstance(prev, list) else [prev]
    except ValueError:
        entries = []
entries = [e for e in entries if e.get("page") != page.name]
entries.append({"page": page.name, "sha256": hashlib.sha256(page.read_bytes()).hexdigest(),
                "pass": ok, "_stub": True})
std.write_text(json.dumps(entries, indent=2) + "\n")
print(f"{page.name}: {'PASS' if ok else 'FAIL'} (stub)")
sys.exit(0 if ok else 1)
