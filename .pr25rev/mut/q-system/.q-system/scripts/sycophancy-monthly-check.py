#!/usr/bin/env python3
"""Monthly sycophancy check - SessionStart hook.

Pairs with .claude/rules/sycophancy-core.md ("review it monthly on the 1st"):
this script is the deterministic form of that line. On the first session of
each calendar month it runs sycophancy-harness.py --standalone (pi over
canonical/decisions.md, no pipeline artifacts) and surfaces the verdict.
Every other session: silent, exit 0.

Why a month-stamp file instead of checking day == 1: the founder may not open
a session on the 1st. The stamp fires on the FIRST session at or after the
month boundary, whenever that is.

Always exits 0 - SessionStart context injection, never a block.
"""

import os
import subprocess
import sys
from datetime import datetime

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
STAMP_PATH = os.path.join(QROOT, "memory", ".sycophancy-monthly-stamp")
HARNESS = os.path.join(QROOT, ".q-system", "sycophancy-harness.py")


def read_stamp():
    try:
        with open(STAMP_PATH) as f:
            return f.read().strip()
    except OSError:
        return None


def main():
    current_month = datetime.now().strftime("%Y-%m")
    if read_stamp() == current_month:
        return 0
    if not os.path.isfile(HARNESS):
        return 0  # instance without the harness; nothing to run

    result = subprocess.run(
        [sys.executable, HARNESS, "--standalone"],
        capture_output=True, text=True, timeout=30,
    )
    print(f"[sycophancy-monthly-check] first session of {current_month}:")
    print(result.stdout.strip() or result.stderr.strip() or "(no output)")
    if result.returncode == 1:
        print(
            "[sycophancy-monthly-check] ALERT - surface this to the founder as "
            "a dedicated item, not an FYI line (sycophancy-core.md rule 3 "
            "framing: the system might be filtering, never shame)."
        )

    try:
        os.makedirs(os.path.dirname(STAMP_PATH), exist_ok=True)
        with open(STAMP_PATH, "w") as f:
            f.write(current_month)
    except OSError:
        pass  # unwritable memory/ must not break session start
    return 0


if __name__ == "__main__":
    sys.exit(main())
