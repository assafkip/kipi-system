#!/usr/bin/env python3
"""TEST STAND-IN for design-standard-check.py. Never shipped next to the real gate.

The real producer needs playwright and chromium. Tests copy design-chain-gate.py into a
temp bin directory beside THIS file and run that copy, so the gate's own rule (producers
are siblings of the gate) selects the stand-in with no override in shipped code
(Sana, 2026-09-18, ASK-1796: no producer-directory override may exist in production).

STUB_STANDARD = pass (default) | fail | cannot | silent | crash | nomodule. Exit codes match
the real contract: 0 pass, 1 fail, 2 could not measure. Writes standard.json the way the real
one does, minus `measurements`, which is how a test tells a stand-in's output from a real run.

Like the real one (dc-03) it fetches --url and refuses when the SERVED bytes differ from the
local file, and it records the URL it was handed so a test can see what seal served.
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("page")
ap.add_argument("--url")
ap.add_argument("--config")
a = ap.parse_args()
page = Path(a.page).resolve()
mode = os.environ.get("STUB_STANDARD", "pass")
if mode == "silent":      # exits 0 and writes NOTHING: what a hijacked interpreter looks like
    sys.exit(0)
if mode == "nomodule":    # what a --user install under a custom user base looks like
    import dc02_module_that_does_not_exist  # noqa: F401
if mode == "crash":       # an unhandled exception exits 1, the same code as a judged FAIL
    raise RuntimeError("stub crashed before producing a verdict")
if mode == "cannot":
    print("could not measure: stub says so", file=sys.stderr)
    sys.exit(2)
local = hashlib.sha256(page.read_bytes()).hexdigest()
if a.url:
    try:
        served = hashlib.sha256(urllib.request.urlopen(a.url, timeout=10).read()).hexdigest()
    except OSError as e:
        print(f"could not measure: {a.url} is not being served: {e}", file=sys.stderr)
        sys.exit(2)
    if served != local:
        print(f"could not measure: served bytes differ from {page.name}", file=sys.stderr)
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
entries.append({"page": page.name, "sha256": local, "pass": ok, "_stub": True, "_fetched_url": a.url})
std.write_text(json.dumps(entries, indent=2) + "\n")
print(f"{page.name}: {'PASS' if ok else 'FAIL'} (stub)")
sys.exit(0 if ok else 1)
