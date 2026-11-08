"""TEMPORARY ASK-3968 probe. Runs one command through capability-gate.py's own
run_contained (Popen, start_new_session, stdin /dev/null, env + QROOT), the way
the gate runs every earned test, and prints the FAIL lines WITH the line after
each one, which is where bad() prints the winner count.

Usage: python3 contained.py <repo-root> <label> <cmd...>
"""
import importlib.util
import os
import sys

root, label, cmd = sys.argv[1], sys.argv[2], sys.argv[3:]
spec = importlib.util.spec_from_file_location(
    "kipi_gate", os.path.join(root, "q-system/.q-system/scripts/capability-gate.py"))
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
env = dict(os.environ, QROOT=os.path.join(root, "q-system"))
r = gate.run_contained(cmd, root, env, 300)
lines = (r.stdout + r.stderr).splitlines()
print(f"[{label}] rc={r.returncode} timed_out={r.timed_out}")
if os.environ.get("PROBE_RAW"):
    for ln in lines:
        print(f"[{label}] {ln}")
    sys.exit(0)
for i, ln in enumerate(lines):
    if ln.startswith("  FAIL"):
        print(f"[{label}] {ln}")
        if i + 1 < len(lines):
            print(f"[{label}] {lines[i + 1][:300]}")
for ln in lines:
    if ln.strip().endswith("failed") and "passed," in ln:
        print(f"[{label}] {ln.strip()}")
