#!/usr/bin/env python3
"""TEMPORARY, ASK-1914, reverted before merge. Where does the capability gate's
822 seconds actually go?

Measured 2026-09-20 on run 35488448685: a selected run of 73 of 236 declared
tests took 699s against the full suite's 822s. So 31% of the artifacts carry 85%
of the cost, and a test SELECTOR can never help, because the 72 expensive ones
are exactly the tree-walkers that no selection may skip.

This times every declared artifact individually, using the SAME invocation
capability-gate.py run_tests() uses (pytest / python3 / bash, per the fragment's
own `runner`), so the numbers are comparable to the gate's own step. It reports
cost per artifact, and splits the total by whether change-size.py calls the
artifact a scanner.

It runs tests. It runs them in CI, never on the founder's machine.
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("REPO_ROOT", ".")).resolve()
FRAGS = ROOT / "q-system/.q-system/capability/expected_tests"
# THE SAME CAP THE GATE USES, and this is the whole reason the first run was
# thrown away. capability-gate.py caps each artifact at its fragment's
# `timeout_s` or DEFAULT_TIMEOUT_S = 60. The first cut of this script used a flat
# 420s, so a test the gate KILLS at 60s ran here for 420 and would have topped
# the "most expensive" table with 360 seconds the gate never pays. That does not
# just inflate the total, which is easy to discount: it ranks the wrong files
# first, which is the one thing this table exists to get right. Cancelled run
# 35489169103 at 16m04s against the gate's 822s, and fixed here.
DEFAULT_TIMEOUT_S = 60
# LIMIT exists so this can be smoke-tested on a handful of artifacts without
# running the sweep it is built to measure. Unset in CI, where the whole point
# is the full 236.
LIMIT = int(os.environ.get("LIMIT", "0")) or None


def load_classifier():
    path = ROOT / "q-system/.q-system/scripts/change-size.py"
    spec = importlib.util.spec_from_file_location("cs", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def command_for(entry: dict, full: Path) -> list[str]:
    """Byte-for-byte the gate's own dispatch (capability-gate.py run_tests)."""
    runner = entry.get("runner", "")
    if runner == "pytest":
        return ["python3", "-m", "pytest", str(full), "-q", "-p", "no:cacheprovider"]
    if runner == "python3":
        return ["python3", str(full)]
    return ["bash", str(full)]


def main() -> int:
    cs = load_classifier()
    env = dict(os.environ, QROOT=str(ROOT / "q-system"))
    rows = []
    for frag in sorted(FRAGS.glob("*.json")):
        try:
            entry = json.loads(frag.read_text())
        except (OSError, ValueError):
            continue
        rel = entry.get("path", "")
        full = ROOT / rel
        if not rel or not full.is_file():
            continue
        if entry.get("quarantine"):
            continue
        text = full.read_text(errors="ignore")
        is_scanner = cs.scans_the_tree(text)
        cmd = command_for(entry, full)
        timeout = entry.get("timeout_s", DEFAULT_TIMEOUT_S)
        start = time.time()
        timed_out = False
        try:
            r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True,
                               text=True, timeout=timeout)
            rc = r.returncode
        except subprocess.TimeoutExpired:
            rc, timed_out = -1, True
        secs = time.time() - start
        rows.append({"path": rel, "secs": round(secs, 2), "rc": rc,
                     "scanner": is_scanner, "timed_out": timed_out,
                     "timeout_s": timeout, "runner": entry.get("runner", "")})
        print(f"{secs:7.2f}s  rc={rc:<4} {'SCAN' if is_scanner else '    '}  "
              f"{'TIMEOUT ' if timed_out else ''}{rel}", flush=True)
        if LIMIT and len(rows) >= LIMIT:
            print(f"(LIMIT={LIMIT} reached, stopping early -- smoke run, not a measurement)")
            break

    total = sum(r["secs"] for r in rows)
    scan = [r for r in rows if r["scanner"]]
    other = [r for r in rows if not r["scanner"]]
    scan_s = sum(r["secs"] for r in scan)
    other_s = sum(r["secs"] for r in other)

    print("\n" + "=" * 72)
    print(f"artifacts timed      : {len(rows)}")
    print(f"total seconds        : {total:.0f}")
    print(f"scanners             : {len(scan)} artifacts, {scan_s:.0f}s "
          f"({100 * scan_s / total:.1f}% of the time)" if total else "")
    print(f"everything else      : {len(other)} artifacts, {other_s:.0f}s "
          f"({100 * other_s / total:.1f}% of the time)" if total else "")
    if scan:
        print(f"mean per scanner     : {scan_s / len(scan):.2f}s")
    if other:
        print(f"mean per other       : {other_s / len(other):.2f}s")

    print("\nTHE 25 MOST EXPENSIVE ARTIFACTS")
    for r in sorted(rows, key=lambda r: -r["secs"])[:25]:
        flag = "SCAN" if r["scanner"] else "    "
        print(f"  {r['secs']:7.2f}s  {flag}  rc={r['rc']:<4} {r['path']}")

    cum, cutoff = 0.0, None
    for i, r in enumerate(sorted(rows, key=lambda r: -r["secs"]), 1):
        cum += r["secs"]
        if cutoff is None and total and cum >= 0.8 * total:
            cutoff = i
    print(f"\n{cutoff} of {len(rows)} artifacts carry 80% of the total.")

    # A TIMED-OUT ROW IS A FLOOR, NOT A COST. It was killed at its cap, so its
    # real duration is unknown and unknowable from this run. Said out loud
    # because the gate pays exactly the cap, which is what the table is for, but
    # "this test would be 9s if it worked" is a different and unanswered question.
    tmo = [r for r in rows if r["timed_out"]]
    if tmo:
        print(f"\nTIMED OUT at their cap ({len(tmo)}); each cost the gate its cap, "
              "and its true duration is not measured here")
        for r in sorted(tmo, key=lambda r: -r["secs"]):
            print(f"  capped at {r['timeout_s']:>4}s  {r['path']}")

    failing = [r for r in rows if r["rc"] != 0 and not r["timed_out"]]
    print(f"\nnon-zero exits, excluding timeouts (not the point here, but recorded): {len(failing)}")
    for r in failing[:15]:
        print(f"  rc={r['rc']:<4} {r['path']}")

    out = ROOT / "ask1914-scanner-cost.json"
    out.write_text(json.dumps(rows, indent=1))
    print(f"\nrows written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
