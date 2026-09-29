#!/usr/bin/env python3
"""Mutation check for the PR #469 review fixes (ASK-2011). Run by hand, not by pytest.

`feedback_check_must_be_able_to_fail`: a new guard needs the input that turns it
RED named, or it is decoration. One mutant per decision point this round added.

    python3 plugins/kipi-core/voiceloop/tests/mutate_check.py

Each mutant reverts one fix to its pre-review form and re-runs the suite. A
mutant that leaves the suite GREEN is a test that is not bound to its guard.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE.parent / "usage_ledger.py"

MUTANTS = {
    "M1 cap_args caps an unsized bot (the major)": (
        "    if sized_caps_for(bot) is None and not (\n"
        "            os.environ.get(TURNS_ENV) or os.environ.get(BUDGET_ENV)):\n"
        "        return []\n",
        "",
    ),
    "M2 write_caps uses a fixed tmp path (the race)": (
        'fd, tmp = tempfile.mkstemp(dir=parent or ".", '
        'prefix=os.path.basename(target) + ".", suffix=".tmp")',
        'tmp = target + ".tmp"\n'
        "    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)",
    ),
    # The json nit got two layers, so it needs two mutants to say which one the
    # test is bound to. M3 is the defect itself: registering `json` as a flag in
    # its own right. M3b is the second layer alone.
    "M3 json is registered as a flag again (the defect)": (
        "_ADDED_FLAGS = {TURNS_FLAG: True, BUDGET_FLAG: True, JSON_FLAGS[0]: True}",
        "_ADDED_FLAGS = {TURNS_FLAG: True, BUDGET_FLAG: True, "
        "**{f: False for f in JSON_FLAGS}}",
    ),
    "M3b the positional guard alone": (
        'if arg.startswith("--") and arg in _ADDED_FLAGS:',
        "if arg in _ADDED_FLAGS:",
    ),
    "M4 size_caps has no minimum-sample guard": (
        "        if len(bot_rows) < min_runs:\n            continue\n",
        "",
    ),
}


#: Mutants that SURVIVE on purpose, each with the reason. A survivor is normally
#: a test that is not bound to its guard; an entry here is the other case, a guard
#: that is redundant with another one. Naming them is the point -- an unexplained
#: survivor and a deliberate one look identical in a pass/fail count.
EXPECTED_SURVIVORS = {
    "M3b the positional guard alone":
        "redundant with M3. Once JSON_FLAGS is registered as ONE value-carrying "
        "flag, a name-only match no longer sees the bare word `json`, so nothing "
        "observes this guard. It stays as the second layer for the next valueless "
        "flag someone registers, and no test binds it.",
}


def suite() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, "-m", "pytest", str(HERE), "-q", "--no-header"],
                          capture_output=True, text=True, cwd=SRC.parent.parent.parent.parent)
    lines = [ln for ln in proc.stdout.splitlines()
             if ln.startswith("FAILED") or " passed" in ln or " failed" in ln]
    return proc.returncode, " | ".join(lines[-4:])


def main() -> int:
    clean = SRC.read_text()
    code, summary = suite()
    print(f"BASELINE: exit={code} {summary}")
    survivors = []
    try:
        for name, (old, new) in MUTANTS.items():
            if old not in clean:
                print(f"{name}: SKIP, the mutated text is gone from the source")
                survivors.append(name)
                continue
            SRC.write_text(clean.replace(old, new))
            code, summary = suite()
            verdict = "KILLED" if code != 0 else "SURVIVED"
            if code == 0:
                survivors.append(name)
            print(f"{name}: {verdict} exit={code} {summary}")
    finally:
        SRC.write_text(clean)
        print("restored clean source")
    unexpected = [s for s in survivors if s not in EXPECTED_SURVIVORS]
    for name in survivors:
        if name in EXPECTED_SURVIVORS:
            print(f"\nEXPECTED SURVIVOR {name}: {EXPECTED_SURVIVORS[name]}")
    if unexpected:
        print(f"\n{len(unexpected)} mutant(s) survived with no reason on file: {unexpected}")
        return 1
    print(f"\n{len(MUTANTS) - len(survivors)} of {len(MUTANTS)} mutants killed, "
          f"{len(survivors)} expected survivor(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
