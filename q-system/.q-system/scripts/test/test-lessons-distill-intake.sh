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

# PR #570 review: a nameless live entry must not crash the run, and a learning_sources
# codename must reach the scrub roster exactly like an instances[] one.
(T / "noname.json").write_text(json.dumps({"instances": [], "learning_sources": [
    {"path": str(side)}, {"name": "Acme_PI", "path": str(T / "x")}]}))
r2 = subprocess.run(cmd[:3] + [str(T / "noname.json")] + cmd[4:], capture_output=True, text=True)
check("a live entry with no name does not crash the distiller", r2.returncode == 0 and json.loads(r2.stdout)["scanned"] == 1)
sys.path.insert(0, str(Path(DISTILL).parent))
import importlib.util
sp = importlib.util.spec_from_file_location("ls", Path(DISTILL).parent / "lessons_scrub.py")
sc = importlib.util.module_from_spec(sp); sp.loader.exec_module(sc)
check("learning_sources codename enters the scrub roster", "Acme_PI" in sc.codenames_from_registry(str(T / "noname.json")))

# ASK-3516: `candidates` counts every source at intake, ledgered or not, so it is
# nonzero on a quiet night; it is zero only when the intake itself is empty.
check("candidates counts all 3 sources", out.get("candidates") == 3)
(T / "ledger.json").write_text(json.dumps({h_skel: {}, h_side: {}, h_inst: {}}))
r3 = subprocess.run(cmd, capture_output=True, text=True)
o3 = json.loads(r3.stdout)
check("a fully ledgered quiet night scans 0 but still reports candidates 3", o3["scanned"] == 0 and o3["candidates"] == 3)
(T / "empty.json").write_text(json.dumps({"instances": [{"name": "e", "path": str(T / "nope")}], "learning_sources": []}))
r4 = subprocess.run(cmd[:3] + [str(T / "empty.json")] + cmd[4:], capture_output=True, text=True)
check("an intake with no live dir reports candidates 0", json.loads(r4.stdout)["candidates"] == 0)

print("ALL PASS" if not fails else f"SOME FAILED: {fails}")
sys.exit(1 if fails else 0)
PY
