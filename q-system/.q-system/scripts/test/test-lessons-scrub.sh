#!/bin/bash
# Fail-closed tests for lessons_scrub.py (the client-data gate before autonomous publish).
# Run: bash q-system/.q-system/scripts/test/test-lessons-scrub.sh
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$DIR" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ls", sys.argv[1] + "/lessons_scrub.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

roster = ["Pure_spectrum_Q", "4_points_consulting", "ASK_AI_consultant"]
fails = []
def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'} {name}")
    if not cond: fails.append(name)

# HELD: every client-data class must fail is_clean (fail-closed)
check("static token KTLYST held",   not m.is_clean("The KTLYST re-breach taught us X"))
check("name Assaf held",            not m.is_clean("Assaf noticed the bug"))
check("abs path held",             not m.is_clean("edit /Users/assafkip/projects/x/y.py"))
check("generic abs path held",     not m.is_clean("the file at /etc/app/config.json broke"))
check("email held",                not m.is_clean("ping me at a.b@client.com about it"))
check("url held",                  not m.is_clean("see https://acmecorp.com/secret for detail"))
check("registry codename held",    not m.is_clean("Pure_spectrum_Q hit the wall", roster))

# CLEAN: a real HOW-only lesson passes
clean = ("Route every mutation of a shared resource through one writer and add a test that greps "
         "the tree to prove no caller bypasses it. Migrate call-sites one revertible edit at a time.")
check("clean HOW-only lesson passes", m.is_clean(clean, roster))

# SCRUB then re-gate: scrubbing an email makes the text clean
scrubbed, hits = m.scrub("contact a@b.com now", roster)
check("scrub replaces + result is clean", m.is_clean(scrubbed, roster) and len(hits) == 1)

# codename roster excludes generic role-name instances (no over-hold on plain English)
import json, tempfile, os
reg = {"instances": [{"name": "accountant"}, {"name": "negotiator"},
                     {"name": "Pure_spectrum_Q"}, {"name": "4_points_consulting"}]}
p = tempfile.mktemp(suffix=".json"); open(p, "w").write(json.dumps(reg))
names = m.codenames_from_registry(p); os.remove(p)
check("roster keeps codenames", "Pure_spectrum_Q" in names and "4_points_consulting" in names)
check("roster drops generic role names", "accountant" not in names and "negotiator" not in names)

print("ALL PASS" if not fails else f"SOME FAILED: {fails}")
sys.exit(1 if fails else 0)
PY
