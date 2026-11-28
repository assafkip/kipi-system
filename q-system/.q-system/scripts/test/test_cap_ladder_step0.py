#!/usr/bin/env python3
"""cap-ladder.py rung 0 and the step0:already-built sweep (ASK-5802).

The cases live in test_cap_ladder.py (case_step0, with its fixture world).
They run from this file, under their own capability-manifest entry, because
inside test_cap_ladder.py they were the longest case and pushed that file's
wall time past its own runtime bound (PR #910 round 1, minor 3).

Run: python3 q-system/.q-system/scripts/test/test_cap_ladder_step0.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    spec = importlib.util.spec_from_file_location("test_cap_ladder_cases", str(HERE / "test_cap_ladder.py"))
    cases = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cases)
    print("test_cap_ladder_step0.py")
    if not cases.LADDER.exists():
        print(f"FAIL: no {cases.LADDER}")
        return 1
    cases.case_step0()
    print(f"\n{'FAIL' if cases.FAILS else 'PASS'}: {len(cases.FAILS)} failed")
    return 1 if cases.FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
