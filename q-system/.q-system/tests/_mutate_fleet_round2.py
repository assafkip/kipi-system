#!/usr/bin/env python3
"""Re-runnable RED proof for PR #717 review round 2 (ASK-4311).

WHY A MUTANT AND NOT A SENTENCE. "Observed RED before green" is only checkable
afterwards if the pre-fix code can be put back on demand. This reverses each of
the three fixes in a COPY of the tree, runs the two suites against the copy, and
reports how many cases go red per mutation. Nothing here touches the working
tree: every edit lands in a tmpdir, and the suites are run from there.

The three mutations, each named for the finding it undoes:

  1. probe-ignores-keys   -- `probe` asks `usable_slot()` only, so it answers
     green with nothing in the Keychain (finding 1).
  2. no-watchdog-handler  -- SIGTERM is left at its default action, so a run the
     worker kills at 1800s leaves no ledger row (finding 2).
  3. report-filters-no_key -- `no_key` drops out of STATE_CHANGE_KINDS and the
     unmetered caveat is removed, so a keyless day and a killed run both read as
     an ordinary one. This is the LAYER-ABOVE half: fixing the detector without
     it leaves the report telling the same lie.
  4. clock-says-2025      -- the suite clock goes back to the epoch literal
     1762700400, which is 2025-11-09 (finding 3).

Usage:  python3 q-system/.q-system/tests/_mutate_fleet_round2.py
Exit 0 when every mutation kills at least one case, 1 when any is survived --
a mutation nothing notices means the cases do not cover the fix.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
QSYS = os.path.normpath(os.path.join(HERE, ".."))

#: (name, relative path, old, new). `old` must appear exactly once.
#: Re-anchored in the ASK-4311 lane after the cycle and auto-reload changes moved
#: every anchor: a harness whose anchors moved reports COULD NOT APPLY, which is
#: a survivor, not a pass.
MUTATIONS = [
    ("probe-ignores-keys", "scripts/fleet_api_key.py",
     """        if unconfirmed or missing:""",
     """        if False:"""),
    ("no-watchdog-handler", "scripts/fleet_api_key.py",
     """    _arm_watchdog_handler()
    _IN_FLIGHT["run"] = {"slot": slot, "actor": actor, "proc": None}""",
     """    _IN_FLIGHT["run"] = {"slot": slot, "actor": actor, "proc": None}"""),
    ("report-filters-no_key", "scripts/fleet-api-report.py",
     """STATE_CHANGE_KINDS = ("pause", "resume", "failover", "no_key", "unconfirmed")""",
     """STATE_CHANGE_KINDS = ("pause", "resume", "failover")"""),
    ("report-drops-the-floor-caveat", "scripts/fleet-api-report.py",
     """    if unmetered:
        lines.append(""",
     """    if False:
        lines.append("""),
    ("clock-says-2025", "tests/test_fleet_api_credit.py",
     """NOW_DT = dt.datetime(2026, 11, 9, 12, 0, 0)""",
     """NOW_DT = dt.datetime.fromtimestamp(1762700400)"""),
    # ASK-4311 lane, orchestrator ruling 2026-11-10: no run on a key whose
    # auto-reload is not confirmed off.
    ("billable-ignores-auto-reload", "scripts/fleet_api_spend.py",
     """    return configured(slot, facts, at) and bool((facts.get(slot) or {}).get("confirmed_at"))""",
     """    return configured(slot, facts, at)"""),
    # Round 3, minor 3: a run nobody could price is not booked free.
    ("parse-error-booked-free", "scripts/fleet_api_key.py",
     """    spend.record(slot, cost, actor=actor, ok=ok, note=note,
                 unmetered=not metered)""",
     """    spend.record(slot, cost, actor=actor, ok=ok, note=note)"""),
    # Round 3, minor 2 and the facts ruling: the cycle end is the Console's
    # expiry, and a past expiry is unknown, never "still the old cycle".
    ("past-expiry-still-live", "scripts/fleet_api_spend.py",
     """    return (at or now()) < row["expires_at"]""",
     """    return True"""),
]

SUITES = ("tests/test_fleet_api_credit.py", "tests/test_fleet_api_report.py")

REPO = os.path.normpath(os.path.join(QSYS, "..", ".."))
GATE_TEST = os.path.join(QSYS, "scripts", "test", "test-dispatch-api-key-gate.sh")

#: The dispatcher half, run through KIPI_DISPATCH_UNDER_TEST rather than by
#: editing the real file. (name, old, new); `old` must appear exactly once.
GATE_MUTATIONS = [
    ("gate-cannot-tell-the-two-apart",
     '''    "4:no key"*)''',
     '''    "4:no key-NEVER"*)'''),
    ("gate-leaves-the-other-marker",
     '''    [ "$k" = "$1" ] || page_clear "$k"''',
     '''    :'''),
    # Round 3, major: a crashed helper must not wear the pause page.
    ("gate-crash-reads-as-pause",
     '''    "4:paused")''',
     '''    [1-9]*)'''),
]


def _gate_reds(dispatch_path):
    """(failed_case_count, lines) for the shell gate test against one dispatcher."""
    env = dict(os.environ, KIPI_DISPATCH_UNDER_TEST=dispatch_path)
    out = subprocess.run(["bash", GATE_TEST], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, universal_newlines=True, env=env)
    lines = [l.strip() for l in (out.stdout or "").splitlines()
             if l.strip().startswith("FAIL")]
    return len(lines), lines


def _reds(root):
    """How many cases fail across both suites in `root`, and their names."""
    total, names = 0, []
    for suite in SUITES:
        out = subprocess.run([sys.executable, os.path.join(root, suite)],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True)
        for line in (out.stdout or "").splitlines():
            m = re.match(r"^(?:FAIL|ERROR): (\S+)", line)
            if m:
                total += 1
                names.append(m.group(1))
    return total, names


def main():
    base = tempfile.mkdtemp(prefix="fleet-round2-mutant-")
    try:
        root = os.path.join(base, "q-system")
        shutil.copytree(QSYS, root, symlinks=True,
                        ignore=shutil.ignore_patterns("output", "__pycache__"))
        clean, clean_names = _reds(root)
        if clean:
            print("BASELINE IS NOT GREEN: %d red before any mutation: %s"
                  % (clean, ", ".join(clean_names[:6])))
            return 1
        print("baseline: both suites green in the copy")

        survived = []
        for name, rel, old, new in MUTATIONS:
            path = os.path.join(root, rel)
            with open(path) as fh:
                src = fh.read()
            if src.count(old) != 1:
                print("  %-30s COULD NOT APPLY (anchor moved in %s)" % (name, rel))
                survived.append(name)
                continue
            with open(path, "w") as fh:
                fh.write(src.replace(old, new))
            red, red_names = _reds(root)
            with open(path, "w") as fh:
                fh.write(src)
            verdict = "killed by %d case(s)" % red if red else "SURVIVED"
            print("  %-30s %s" % (name, verdict))
            for n in red_names[:4]:
                print("      red: %s" % n)
            if not red:
                survived.append(name)

        # --- the dispatcher half -------------------------------------------
        # Run through KIPI_DISPATCH_UNDER_TEST, which the gate test already
        # honours, so the real file is never edited.
        dispatch = os.path.join(REPO, "kipi-dispatch.sh")
        if not os.path.exists(GATE_TEST) or not os.path.exists(dispatch):
            print("  %-30s COULD NOT RUN (gate test or dispatcher missing)"
                  % "dispatch-gate")
            survived.append("dispatch-gate")
        else:
            with open(dispatch) as fh:
                real = fh.read()
            clean_gate, clean_gate_lines = _gate_reds(dispatch)
            if clean_gate:
                print("GATE BASELINE IS NOT GREEN: %d red: %s"
                      % (clean_gate, "; ".join(clean_gate_lines[:3])))
                return 1
            print("gate baseline: green against the shipped dispatcher")
            for name, old, new in GATE_MUTATIONS:
                if real.count(old) != 1:
                    print("  %-30s COULD NOT APPLY (anchor moved)" % name)
                    survived.append(name)
                    continue
                path = os.path.join(base, name + ".sh")
                with open(path, "w") as fh:
                    fh.write(real.replace(old, new))
                red, red_lines = _gate_reds(path)
                print("  %-30s %s" % (name,
                                      "killed by %d case(s)" % red if red else "SURVIVED"))
                for l in red_lines[:4]:
                    print("      red: %s" % l)
                if not red:
                    survived.append(name)

        if survived:
            print("\nMUTANT SURVIVED: %s -- the cases do not cover that fix"
                  % ", ".join(survived))
            return 1
        print("\nMUTANT: every one of the %d mutations is killed"
              % (len(MUTATIONS) + len(GATE_MUTATIONS)))
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
