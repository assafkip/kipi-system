#!/usr/bin/env python3
"""One mutant per decision point in mutate.py, driven THROUGH mutate.py.

The harness proving itself. Run from the repo root:

    python3 plugins/prd-os/tests/mutants_of_mutate.py

Every row must print 0 / KILLED. A row printing 1 / SURVIVED means the guard it
names is decoration: no test in test_mutate.py can tell whether it is there.
A row printing 2 / FAILED-TO-APPLY means the anchor drifted and the run measured
nothing -- re-anchor it, never loosen it.

This is a self-proof, not a pytest case: it rewrites mutate.py in place, so it is
run deliberately and never collected by the suite.
"""
import subprocess
import sys

MUTATE = "plugins/prd-os/scripts/mutate.py"
SUITE = "plugins/prd-os/tests/test_mutate.py"

MUTANTS = [
    ("D1  no-op experiment guard off",
     "    if anchor == replacement:",
     "    if anchor is None:"),
    ("D2  exactly-once loosened to at-least-once",
     "    if matches != 1:",
     "    if matches < 1:"),
    ("D3  dirty tree accepted as a result",
     "    if not restored:",
     "    if restored is None:"),
    ("D4  bytecode writing re-enabled",
     'env["PYTHONDONTWRITEBYTECODE"] = "1"',
     'env["PYTHONDONTWRITEBYTECODE"] = "0"'),
    ("D5  read-side cache prefix dropped",
     '    env["PYTHONPYCACHEPREFIX"] = cache_prefix',
     '    env.pop("PYTHONPYCACHEPREFIX", None)'),
    ("D6  verdict hardcoded to KILLED",
     '    verdict = "KILLED" if run_exit != 0 else "SURVIVED"',
     '    verdict = "KILLED"'),
]

# Two guards are deliberately NOT in the table above, and the reason is written
# down rather than left as a silent gap (a survivor is either an equivalent
# mutant you explain or a test you rewrite; these are the first kind):
#
#   mutate.py  `if on_disk != digest_after:`   -- read-back after the mutant write
#   mutate.py  `return sha256(fh.read()) == sha256(original)`  -- inside _restore
#
# Both compare what was written against what came back. Their false branch needs
# a filesystem that accepts a write and returns different bytes: a short write on
# a full disk, a truncated flush, a racing writer. That is real in production and
# unreachable from a test without a lying-filesystem seam, and a seam that exists
# only for a test is production code serving no production caller. The REACHABLE
# half of the same concern -- a restore that fails outright -- is covered by
# test_unrestorable_tree_is_failed_experiment and by mutant D3 above.


def main() -> int:
    # A mutation table run against an ALREADY-RED suite kills every mutant
    # trivially and reads as a perfect score. Hit live while building this file
    # 2026-09-27: one broken test turned a 7-row table all-KILLED, including the
    # two rows that had SURVIVED minutes earlier. Same family as the scar the
    # harness exists for -- the instrument failing in the reassuring direction.
    baseline = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", SUITE], capture_output=True, text=True
    )
    if baseline.returncode != 0:
        print("REFUSED: baseline suite is not green; every mutant would read KILLED.",
              file=sys.stderr)
        print(baseline.stdout[-1500:], file=sys.stderr)
        return 2

    worst = 0
    for label, anchor, replacement in MUTANTS:
        proc = subprocess.run(
            [sys.executable, MUTATE, "--label", label, "--file", MUTATE,
             "--anchor", anchor, "--replacement", replacement,
             "--", sys.executable, "-m", "pytest", "-q", SUITE],
            capture_output=True, text=True,
        )
        verdicts = [ln for ln in proc.stdout.splitlines() if ln.startswith("verdict:")]
        verdict = verdicts[-1] if verdicts else proc.stdout.strip()[-60:]
        print(f"exit={proc.returncode}  {verdict:<40}  {label}")
        worst = max(worst, proc.returncode)
    return worst


if __name__ == "__main__":
    sys.exit(main())
