#!/usr/bin/env python3
"""Fleet capability verify: run the capability gate in EVERY registered
instance and print one deterministic per-instance status line.

This is the propagation proof for prd-silent-absence-capability-gate-2026-07-23:
"the fix landed fleet-wide" is a table of exit codes, not a belief. The scar it
prevents: a skeleton-only test shipped to the whole fleet and crashed in every
instance for months, because nothing ever ran anything in the instances.

Statuses (finding-3, finding-16 — no instance-level acceptable-red exists):
  GREEN                 gate exited 0
  RED(gate)             gate exited non-zero (tail printed)
  RED(missing-gate)     subtree instance, synced tree present, gate script absent
  RED(missing-tree)     type=subtree but no q-system/.q-system dir — the sync
                        itself never delivered (AUDHD_KIDS class, found 2026-07-23)
  SKIPPED(standalone)   type=standalone — no skeleton subtree by design; printed
                        loudly, never silently passed
  SKIPPED(merged)       registry status starts with "merged" (tombstone entry)

Exit 0 iff zero RED rows. Skeleton-local tooling: lives at repo root, NOT in
the synced q-system/ tree (RULE-2026-06-30-A).
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
GATE_REL = "q-system/.q-system/scripts/capability-gate.py"


def verify_instance(inst, full):
    name = inst["name"]
    path = Path(inst["path"])
    if (inst.get("status") or "").startswith("merged"):
        return name, "SKIPPED(merged)", ""
    if inst.get("type", "subtree") == "standalone":
        return name, "SKIPPED(standalone)", "no skeleton subtree by design"
    if not (path / "q-system/.q-system").is_dir():
        return name, "RED(missing-tree)", "type=subtree but q-system/.q-system absent"
    gate = path / GATE_REL
    if not gate.is_file():
        return name, "RED(missing-gate)", f"{GATE_REL} not delivered"
    cmd = [sys.executable, str(gate), "--repo-root", str(path)]
    if not full:
        cmd.append("--check-only")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return name, "RED(gate)", "gate timed out (1800s)"
    if r.returncode != 0:
        tail = " | ".join((r.stdout + r.stderr).splitlines()[-4:])
        return name, "RED(gate)", tail
    return name, "GREEN", ""


def run_fleet(registry_path, full):
    """Every registry collection is enumerated. The verifier's first codex
    review caught it iterating only `instances` while `standalone` and
    `eliminated` collections were silently omitted — a silent absence inside
    the silent-absence verifier (2026-07-23)."""
    reg = json.loads(Path(registry_path).read_text())
    rows = [verify_instance(i, full) for i in reg["instances"]]
    for coll, label in (("standalone", "SKIPPED(standalone)"),
                        ("eliminated", "SKIPPED(eliminated)")):
        for i in reg.get(coll, []):
            rows.append((i.get("name", "?"), label, f"registry collection: {coll}"))
    if not rows:
        print("fleet-capability-verify: registry has zero entries")
        return 0
    width = max(len(n) for n, _, _ in rows) + 2
    reds = 0
    for name, status, detail in rows:
        print(f"{name:<{width}} {status}" + (f"  — {detail}" if detail else ""))
        if status.startswith("RED"):
            reds += 1
    mode = "full" if full else "check-only"
    print(f"\nfleet-capability-verify ({mode}): {len(rows)} instances, "
          f"{sum(1 for _, s, _ in rows if s == 'GREEN')} green, {reds} red, "
          f"{sum(1 for _, s, _ in rows if s.startswith('SKIPPED'))} skipped")
    return 1 if reds else 0


def self_test():
    """Sandbox proof of every status class — the verifier itself must be seen
    to fail before its green is trusted (fable-discipline negative self-test)."""
    failures = []

    def check(label, cond):
        print(("PASS: " if cond else "FAIL: ") + label)
        if not cond:
            failures.append(label)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        def mk_instance(name, gate_body=None, tree=True):
            p = tmp / name
            (p / "q-system/.q-system/scripts").mkdir(parents=True)
            if not tree:
                import shutil
                shutil.rmtree(p / "q-system/.q-system")
            elif gate_body is not None:
                (p / GATE_REL).write_text(gate_body)
            return {"name": name, "path": str(p), "type": "subtree"}

        instances = [
            mk_instance("green-i", "import sys; sys.exit(0)"),
            mk_instance("red-i", "import sys; print('boom'); sys.exit(1)"),
            mk_instance("nogate-i"),
            mk_instance("notree-i", tree=False),
            {"name": "standalone-i", "path": str(tmp / "sa"), "type": "standalone"},
            {"name": "merged-i", "path": str(tmp / "m"), "type": "subtree",
             "status": "merged-into-x"},
            {**mk_instance("nullstatus-i", "import sys; sys.exit(0)"), "status": None},
        ]
        regp = tmp / "registry.json"
        regp.write_text(json.dumps({
            "instances": instances,
            "standalone": [{"name": "coll-standalone-i", "path": str(tmp / "cs")}],
            "eliminated": [{"name": "coll-eliminated-i", "path": str(tmp / "ce")}],
        }))
        r = subprocess.run([sys.executable, __file__, "--registry", str(regp)],
                           capture_output=True, text=True, timeout=300)
        out = r.stdout

        def row_status(name):
            # per-ROW assertion: name and status on the SAME line (the
            # independent-substring version could not catch a swapped pair)
            for line in out.splitlines():
                if line.startswith(name + " "):
                    return line.split()[1] if len(line.split()) > 1 else ""
            return "<row missing>"

        check("exit non-zero with reds", r.returncode == 1)
        check("green instance row GREEN", row_status("green-i") == "GREEN")
        check("failing gate row RED(gate)", row_status("red-i") == "RED(gate)")
        check("missing gate row RED(missing-gate)", row_status("nogate-i") == "RED(missing-gate)")
        check("missing tree row RED(missing-tree)", row_status("notree-i") == "RED(missing-tree)")
        check("standalone row SKIPPED loudly", row_status("standalone-i") == "SKIPPED(standalone)")
        check("merged tombstone row SKIPPED", row_status("merged-i") == "SKIPPED(merged)")
        check("standalone COLLECTION enumerated", row_status("coll-standalone-i") == "SKIPPED(standalone)")
        check("eliminated COLLECTION enumerated", row_status("coll-eliminated-i") == "SKIPPED(eliminated)")
        check("null status tolerated", "AttributeError" not in r.stderr)
        # Closed vocabulary (finding-16 / sag-fleet-red-schema): there is no
        # instance-level acceptable-red and no status outside this set. A new
        # status string added without updating this pin fails here.
        allowed = {"GREEN", "RED(gate)", "RED(missing-gate)", "RED(missing-tree)",
                   "SKIPPED(standalone)", "SKIPPED(merged)", "SKIPPED(eliminated)"}
        statuses = {line.split()[1] for line in r.stdout.splitlines()
                    if line.strip() and not line.startswith("fleet-capability-verify")
                    and len(line.split()) > 1 and "—" not in line.split()[1]}
        check("status vocabulary is closed (no unknown statuses)",
              statuses <= allowed and len(statuses) >= 5)

        regp.write_text(json.dumps({"instances": []}))
        r = subprocess.run([sys.executable, __file__, "--registry", str(regp)],
                           capture_output=True, text=True, timeout=300)
        check("empty registry exits 0 without crash", r.returncode == 0)

        all_green = [mk_instance("only-green", "import sys; sys.exit(0)")]
        regp.write_text(json.dumps({"instances": all_green}))
        r = subprocess.run([sys.executable, __file__, "--registry", str(regp)],
                           capture_output=True, text=True, timeout=300)
        check("all-green fleet exits 0", r.returncode == 0)

    if failures:
        print(f"\n{len(failures)} FAILED: {failures}")
        return 1
    print("\nALL PASS")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default=str(SCRIPT_DIR / "instance-registry.json"))
    ap.add_argument("--full", action="store_true",
                    help="run each instance's full test suite (default: --check-only)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())
    sys.exit(run_fleet(args.registry, args.full))


if __name__ == "__main__":
    main()
