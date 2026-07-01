#!/bin/bash
# Tests for lessons-distill.py: gate publishes clean, scrubs client data, holds semantic flags,
# and is idempotent (ledger). Injects distillations so no `claude` spend. Run:
#   bash q-system/.q-system/scripts/test/test-lessons-distill.sh
set -euo pipefail
DISTILL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lessons-distill.py"

python3 - "$DISTILL" <<'PY'
import hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path
DISTILL = sys.argv[1]
T = Path(tempfile.mkdtemp())

# one fake instance with two RCAs
inst = T / "projects" / "acme"; rca = inst / "q-system" / "output" / "rca"; rca.mkdir(parents=True)
r1 = rca / "rca-1.md"; r1.write_text("# clean rca\n\n## Structural root cause\ngeneric cause.\n")
r2 = rca / "rca-2.md"; r2.write_text("# path rca\n\n## Structural root cause\nother cause.\n")
def h(p): return hashlib.sha1(p.read_text().encode()).hexdigest()[:16]
h1, h2 = h(r1), h(r2)

(T / "registry.json").write_text(json.dumps({"instances": [{"name": "acme", "path": str(inst)}]}))
# injected distillations: one clean, one carrying a /Users/ path (must be scrubbed, then published)
(T / "distilled.json").write_text(json.dumps({
    h1: {"title": "Guard shared mutations", "body": "Route every mutation through one writer; grep the tree.", "kind": "pattern"},
    h2: {"title": "Snapshot before delete", "body": "Snapshot files at /Users/x/proj/y before a destructive sync, then restore.", "kind": "pattern"},
}))
lessons = T / "lessons"; held = T / "held"; ledger = T / "ledger.json"

def run(extra):
    cmd = ["python3", DISTILL, "--registry", str(T/"registry.json"), "--lessons-dir", str(lessons),
           "--held-dir", str(held), "--ledger", str(ledger), "--distilled-file", str(T/"distilled.json")] + extra
    return json.loads(subprocess.run(cmd, capture_output=True, text=True).stdout)

fails = []
def check(n, c): print(f"  {'PASS' if c else 'FAIL'} {n}"); fails.append(n) if not c else None

# run 1: verify=clean so both pass semantic; expect 2 published
out = run(["--test-verify", "clean"])
check("2 published", len(out["published"]) == 2)
files = sorted(p.name for p in lessons.glob("*.md"))
check("2 lesson files written", len(files) == 2)
scrubbed = "".join((lessons / f).read_text() for f in files)
check("client path scrubbed from published lesson", "/Users/" not in scrubbed and "[PATH]" in scrubbed)

# run 2: idempotent — nothing new
out2 = run(["--test-verify", "clean"])
check("idempotent second run (0 published)", out2["scanned"] == 0 and out2["published"] == [])

# held path: new RCA, verify=held -> held, not published
r3 = rca / "rca-3.md"; r3.write_text("# third\n\n## Structural root cause\ncause three.\n")
h3 = hashlib.sha1(r3.read_text().encode()).hexdigest()[:16]
d = json.loads((T/"distilled.json").read_text())
d[h3] = {"title": "Third lesson", "body": "some generic body.", "kind": "pattern"}
(T/"distilled.json").write_text(json.dumps(d))
before = len(list(lessons.glob("*.md")))
out3 = run(["--test-verify", "held"])
check("held lesson not published", len(list(lessons.glob("*.md"))) == before)
check("held lesson written to held dir", any(held.glob("held-*.md")))
check("summary reports 1 held", len(out3["held"]) == 1)

print("ALL PASS" if not fails else f"SOME FAILED: {fails}")
sys.exit(1 if fails else 0)
PY
