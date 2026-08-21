#!/usr/bin/env bash
# enforced-claim-mutation-matrix: one fabricated input per BLOCKING CONDITION,
# with the case list DERIVED FROM THE LINT rather than hand-written (ASK-965,
# finding-14).
#
# WHY DERIVED. Gap class 20 asks a guard's test to enumerate its own target
# surface instead of trusting a list someone typed. A hand-written matrix passes
# forever after a new condition is added, because nothing notices the condition
# has no case -- the test would be describing the lint as it was on the day it
# was written. So this script reads the condition numbers straight out of
# `Violation(N, ...)` in the lint source, and FAILS if any of them has no
# fixture. Adding a condition without a case is a red build, not a silence.
#
# WHY IT EXISTS AT ALL. The founder's brief made this non-negotiable: a fabricated
# rule claiming ENFORCED with a fictional executable MUST go red before any green
# is trusted. The cautionary case is in the same repo -- the wired
# prompt-only-enforcement-guard.py passes a fictional hook name at exit 0,
# because it matches enforcement VOCABULARY rather than existence.
#
# Exit 0 = every derived condition has a case AND each case actually fires.
set -euo pipefail

# test/ -> scripts/ -> .q-system/ -> q-system/ -> repo root: four levels up.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
LINT="$ROOT/q-system/.q-system/scripts/enforced-claim-lint.py"

[ -f "$LINT" ] || { echo "FAIL: lint not found at $LINT"; exit 1; }

python3 - "$ROOT" "$LINT" <<'PYEOF'
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT, LINT = sys.argv[1], sys.argv[2]
SRC = Path(LINT).read_text()

# DERIVED, not typed: every condition the lint can actually emit.
DERIVED = sorted({int(m.group(1)) for m in re.finditer(r"Violation\(\s*(\d+)\s*,", SRC)})

DETECTOR = "#!/usr/bin/env python3\nimport sys\nprint('x')\nsys.exit(0)\n"
BLOCKER = "#!/usr/bin/env python3\nimport sys\nsys.exit(2)\n"
EXEC_REL = "q-system/scripts/real-lint.py"
TEST_REL = "q-system/scripts/test_real_lint.py"


def tree(d, *, block=None, heading="Cleanup Rule (ENFORCED)", src=BLOCKER,
         cmd=None, extra="", ledger=None, baseline=None, second_heading=None):
    """A repo-shaped fixture. Every knob here corresponds to something a real
    rule author can get wrong, which is why the fixtures are shaped like repos
    rather than like strings."""
    rules = Path(d) / ".claude" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    (Path(d) / EXEC_REL).parent.mkdir(parents=True, exist_ok=True)
    (Path(d) / EXEC_REL).write_text(src)
    (Path(d) / TEST_REL).write_text("# real-lint.py\n")
    command = cmd if cmd is not None else 'python3 "$CLAUDE_PROJECT_DIR/%s"' % EXEC_REL
    (Path(d) / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PostToolUse": [
        {"matcher": "Edit", "hooks": [{"type": "command", "command": command}]}]}}))
    body = "---\nd: f\n---\n\n# %s\n\nYou MUST do the thing.\n%s\n" % (heading, extra)
    if second_heading:
        body += "\n## %s\n\nMore.\n" % second_heading
    if block is not None:
        body += "\n<!-- enforcement -->\n```json\n%s\n```\n" % block
    (rules / "fixture.md").write_text(body)
    if ledger is not None:
        (Path(d) / ".prd-os").mkdir(parents=True, exist_ok=True)
        (Path(d) / ".prd-os" / "spillover.jsonl").write_text(ledger)
    if baseline is not None:
        bd = Path(d) / "q-system" / ".q-system"
        bd.mkdir(parents=True, exist_ok=True)
        (bd / "enforced-claim-baseline.json").write_text(json.dumps(baseline))
    return d


def entry(**kw):
    base = {"clause": "Cleanup Rule", "status": "ENFORCED", "exec": EXEC_REL,
            "config": ".claude/settings.json", "test": TEST_REL}
    base.update(kw)
    return base


OPEN_LEDGER = json.dumps({"id": "sp-abc123", "status": "open"}) + "\n"

# One fabricated input per condition. The KEY is the condition number, so a new
# condition with no key here is a failure below rather than an omission.
CASES = {
    0: dict(block=json.dumps([entry()]),
            baseline={"initial_count": 0, "uncovered_markers": ["ghost.md::gone"]},
            why="baseline entry that is no longer an undispositioned marker"),
    1: dict(block=None, why="a marker with no disposition at all"),
    2: dict(block=json.dumps([entry(clause="Cleanup Rule"),
                              entry(clause="cleanup   rule")]),
            why="two entries colliding onto one clause key"),
    3: dict(block=json.dumps([entry(clause="A Heading That Is Not There")]),
            why="a disposition matching no marked heading"),
    4: dict(block='[{"clause": "Cleanup Rule",}]', why="malformed JSON"),
    5: dict(block=json.dumps([entry(exec="q-system/scripts/totally-imaginary-lint.py")]),
            why="THE BRIEF'S CASE: ENFORCED naming a fictional executable"),
    6: dict(block=json.dumps([entry()]), cmd="python3 other.py",
            why="the named config invokes something else, so the claim is an orphan"),
    7: dict(block=json.dumps([entry()]),
            cmd='python3 "$CLAUDE_PROJECT_DIR/%s" || true' % EXEC_REL,
            why="wired but neutered, so it can never block"),
    8: dict(block=json.dumps([entry()]), src=DETECTOR,
            why="ENFORCED naming a script that exits 0 on every path"),
    9: dict(block=json.dumps([entry(test="q-system/scripts/test_ghost.py")]),
            why="ENFORCED whose named test receipt does not exist"),
    10: dict(block=json.dumps([{"clause": "Cleanup Rule", "status": "DETECTED",
                                "exec": EXEC_REL, "config": ".claude/settings.json"}]),
             why="DETECTED understating a script that can block"),
    11: dict(block=json.dumps([{"clause": "Cleanup Rule", "status": "ADVISORY",
                                "note": "n"}]),
             why="ADVISORY under a live marker with no removal ticket"),
    12: dict(block=json.dumps([{"clause": "Cleanup Rule", "status": "ADVISORY",
                                "note": "n", "marker_removal_ref": "sp-abc123",
                                "directives": 99}]),
             ledger=OPEN_LEDGER,
             why="a declared directive count the section does not match"),
}

missing = [c for c in DERIVED if c not in CASES]
if missing:
    print("FAIL: the lint can emit condition(s) %s with no fixture in this matrix."
          % missing)
    print("      The case list is DERIVED from the lint on purpose: adding a")
    print("      condition without a case must be a red build, not a silence.")
    sys.exit(1)

stale = [c for c in CASES if c not in DERIVED]
if stale:
    print("FAIL: matrix has case(s) %s the lint can no longer emit. Remove them; a "
          "case for a dead condition is a test describing a lint that is gone."
          % stale)
    sys.exit(1)

failures = []
for cond in DERIVED:
    spec = dict(CASES[cond])
    why = spec.pop("why")
    with tempfile.TemporaryDirectory() as d:
        tree(d, **spec)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=d)
        r = subprocess.run([sys.executable, LINT, "--all"],
                           capture_output=True, text=True, env=env)
        tag = "[C%d]" % cond
        if r.returncode == 0:
            failures.append("C%d (%s): expected a violation, got exit 0" % (cond, why))
        elif tag not in r.stderr:
            failures.append("C%d (%s): blocked, but %s never appeared. stderr: %s"
                            % (cond, why, tag, r.stderr.strip()[:200]))
        else:
            print("  RED as required  %-4s %s" % (tag, why))

# THE CONTROL. Without it every line above could be satisfied by a lint that
# refuses all input, which is a matrix that cannot tell a gate from a wall.
with tempfile.TemporaryDirectory() as d:
    tree(d, block=json.dumps([entry(directives=1)]))
    env = dict(os.environ, CLAUDE_PROJECT_DIR=d)
    r = subprocess.run([sys.executable, LINT, "--all"],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        failures.append("CONTROL: an honest ENFORCED rule was rejected. %s"
                        % (r.stderr.strip()[:300]))
    else:
        print("  GREEN as required     an honest ENFORCED rule passes")

if failures:
    print("\nFAIL: %d case(s):" % len(failures))
    for f in failures:
        print("  - %s" % f)
    sys.exit(1)

print("\nPASS: %d derived condition(s), each with a fixture that fires, plus the "
      "honest-rule control." % len(DERIVED))
PYEOF
