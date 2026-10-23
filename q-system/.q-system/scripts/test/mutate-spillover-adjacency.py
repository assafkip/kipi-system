#!/usr/bin/env python3
"""Mutation harness for spillover-adjacency-classify.py (ASK-2014).

WHY: a green suite proves nothing until it has been seen to go red. One mutant per
decision point the classifier adds, each bound to the assertion that should catch
it. Run it after any change to the classifier's gate logic.

Each mutant is applied to the real file, the suite is run, and the file is restored
from git in a `finally`, so an interrupted run cannot leave a mutated classifier on
disk.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "q-system/.q-system/scripts/spillover-adjacency-classify.py"
SUITE = ROOT / "q-system/.q-system/scripts/test/test_spillover_adjacency_classify.py"

MUTANTS = [
    ("M1 severity gate never fires",
     'if rank[sev] > rank["medium"]:', 'if False:'),
    ("M2 a path outside the changed files counts as adjacent",
     'if state == "outside":', 'if False:'),
    ("M3 the line cap is ignored",
     'if n > max_lines:', 'if False:'),
    ("M4 an unmeasured patch is treated as zero lines",
     'return "UNDECIDABLE", (\n            f"adjacent:{state} ({detail}) but size unmeasured: the row carries no "\n            "resolution_commit, so there is no patch to count")',
     'return "FIX_IN_PLACE", "size unmeasured, assumed small"'),
    ("M5 the severity order is a hand-typed copy",
     "found = None", 'return ("low", "minor", "medium", "high", "major", "blocker")\n    found = None'),
]

original = SCRIPT.read_text()
killed, survived = [], []
try:
    for name, old, new in MUTANTS:
        if old not in original:
            print(f"SKIP {name}: anchor not found, the harness has drifted from "
                  "the classifier")
            survived.append(name + " (anchor missing)")
            continue
        SCRIPT.write_text(original.replace(old, new, 1))
        p = subprocess.run([sys.executable, str(SUITE)],
                           capture_output=True, text=True)
        if p.returncode == 0:
            print(f"SURVIVED {name}: the suite stayed green")
            survived.append(name)
        else:
            first = [ln for ln in (p.stdout + p.stderr).splitlines()
                     if ln.startswith("FAIL")]
            print(f"KILLED   {name} -> {first[0] if first else 'non-zero exit'}")
            killed.append(name)
finally:
    SCRIPT.write_text(original)

print(f"\nMUTATION {len(killed)}/{len(MUTANTS)} killed")
if survived:
    print("SURVIVORS (each is an assertion this suite does not have):")
    for s in survived:
        print("  " + s)
sys.exit(1 if survived else 0)
