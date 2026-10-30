#!/bin/bash
# Pins the INTAKE of lessons-distill.py (ASK-3403): it reads the registry's
# `skeleton` entry and every `learning_sources` repo, not only `instances[]`, and it
# counts the dead paths it skips.
#
# THE SCAR. load_instances() read only data["instances"]. The skeleton sits under its own
# key, so its 23 RCAs and learnings were never scanned (22 had no ledger row), and
# the 2026-10-26 run logged "scanned": 0. chief was in no list at all. 8 of 20
# registry paths did not exist and were skipped without a count.
#
# Hermetic: temp registry, injected distillations, --dry, no claude spend.
#   bash q-system/.q-system/scripts/test/test-lessons-distill-intake.sh
set -euo pipefail
DISTILL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lessons-distill.py"

python3 - "$DISTILL" <<'PY'
import hashlib, json, subprocess, sys, tempfile
from pathlib import Path
DISTILL = sys.argv[1]
T = Path(tempfile.mkdtemp())

def note(root, name, body):
    d = root / "q-system" / "output" / "learnings"; d.mkdir(parents=True, exist_ok=True)
    p = d / name; p.write_text(body)
    return hashlib.sha1(p.read_text().encode()).hexdigest()[:16]

skel, side, inst = T / "skel", T / "side", T / "inst"
h_skel = note(skel, "a.md", "# skeleton note\n\nbody a.\n")
h_side = note(side, "b.md", "# side repo note\n\nbody b.\n")
h_inst = note(inst, "c.md", "# instance note\n\nbody c.\n")

reg = {"skeleton": {"path": str(skel)},
       "instances": [{"name": "i1", "path": str(inst)}, {"name": "gone", "path": str(T / "nope")}],
       "learning_sources": [{"name": "side", "path": str(side)}, {"name": "gone2", "path": str(T / "nope2")}]}
(T / "registry.json").write_text(json.dumps(reg))
(T / "distilled.json").write_text(json.dumps(
    {h: {"title": f"L {h}", "body": "Route every mutation through one writer.", "kind": "pattern"}
     for h in (h_skel, h_side, h_inst)}))

cmd = ["python3", DISTILL, "--registry", str(T / "registry.json"), "--lessons-dir", str(T / "lessons"),
       "--held-dir", str(T / "held"), "--ledger", str(T / "ledger.json"),
       "--distilled-file", str(T / "distilled.json"), "--test-verify", "clean", "--dry"]
r = subprocess.run(cmd, capture_output=True, text=True)
out = json.loads(r.stdout)

fails = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'} {n}")
    if not c: fails.append(n)

check("reads the skeleton, the learning_sources repo and the instance (scanned 3)", out["scanned"] == 3)
check("counts the dead paths it skipped (2)", out.get("skipped_dead") == 2)
check("logs the dead-path count on stderr", "skipped 2 dead" in r.stderr)

print("ALL PASS" if not fails else f"SOME FAILED: {fails}")
sys.exit(1 if fails else 0)
PY
