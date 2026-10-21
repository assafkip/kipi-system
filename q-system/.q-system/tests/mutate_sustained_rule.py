#!/usr/bin/env python3
"""Mutate the sustained-failure rule and prove its checks can go RED (ASK-2013).

A guard nobody has watched fail is decoration. Three mutants, each a plausible
wrong version of the rule that ships:

  1. threshold 2 -> 1      (the rule is present but files on one failure anyway)
  2. wrong fingerprint     (the rule points at a shape nobody measured)
  3. drop the fp check     (the rule quietly widens to EVERY shape -- the exact
                            global version the 45-day replay refused)

Restores the file in a `finally`, so a failed run leaves nothing mutated.

    python3 q-system/.q-system/tests/mutate_sustained_rule.py
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
TARGET = ROOT / "q-system" / ".q-system" / "scripts" / "alert-to-linear.py"
SUITE = "q-system/.q-system/tests/test_alert_to_linear.py"
REPLAY = "q-system/.q-system/tests/replay_alert_sustained_rule.py"

MUTANTS = [
    ("threshold 2 -> 1",
     "SUSTAINED_MIN_OBSERVATIONS = 2",
     "SUSTAINED_MIN_OBSERVATIONS = 1"),
    ("fingerprint -> a shape nobody measured",
     'SUSTAINED_FINGERPRINT = "b9e91e84bf2bdfd6"',
     'SUSTAINED_FINGERPRINT = "0000000000000000"'),
    ("rule widened to every fingerprint",
     "return fp == SUSTAINED_FINGERPRINT and observations < SUSTAINED_MIN_OBSERVATIONS",
     "return observations < SUSTAINED_MIN_OBSERVATIONS"),
]


def _run(argv: list) -> tuple:
    proc = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    return proc.returncode, (lines[-1] if lines else "")


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    killed = 0
    try:
        for name, before, after in MUTANTS:
            if before not in original:
                print(f"MUTANT {name}: SOURCE LINE NOT FOUND -- mutant never "
                      f"applied, which is not a result")
                return 1
            TARGET.write_text(original.replace(before, after), encoding="utf-8")
            suite_code, suite_line = _run([sys.executable, "-m", "pytest", SUITE, "-q"])
            replay_code, _ = _run([sys.executable, REPLAY])
            dead = suite_code != 0 or replay_code != 0
            killed += dead
            print(f"MUTANT {name}: {'KILLED' if dead else 'SURVIVED'} "
                  f"(suite exit {suite_code}: {suite_line}; replay exit {replay_code})")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    suite_code, suite_line = _run([sys.executable, "-m", "pytest", SUITE, "-q"])
    print(f"RESTORED: suite exit {suite_code}: {suite_line}")
    print(f"{killed}/{len(MUTANTS)} mutants killed")
    return 0 if killed == len(MUTANTS) and suite_code == 0 else 1


if __name__ == "__main__":
    os.chdir(ROOT)
    raise SystemExit(main())
