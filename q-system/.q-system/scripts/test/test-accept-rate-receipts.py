#!/usr/bin/env python3
"""Pairs with accept-rate.py load_receipts.

sp-4c5a00f3 / ASK-988 round 4 (codex): receipt state is resolved by EVENT
TIMESTAMP, never by physical line order. A union merge can interleave appended
rows, so an out-of-order reopen must still win over an older close. This file
also pins the negative: if load_receipts stops reading rows (e.g. replaced by
an always-empty stub), these checks fail loudly instead of passing vacuously.

Run: python3 test-accept-rate-receipts.py   (exit 0 = pass)
"""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "ar", HERE.parent / "accept-rate.py")
ar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ar)

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")
    else:
        print(f"  ok: {name}")


def ledger(rows):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "receipts.jsonl")
    with open(p, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return d


CLOSE_F1 = {"prd_id": "P", "finding_id": "f1",
            "closed_at": "2026-01-01T00:00:00Z"}
REOPEN_F1 = {"prd_id": "P", "finding_id": "f1", "issue_id": "i",
             "reopened_at": "2026-02-01T00:00:00Z"}
RECLOSE_F1 = {"prd_id": "P", "finding_id": "f1",
              "closed_at": "2026-03-01T00:00:00Z"}

# 1. a plain close counts.
check("close row counts closed",
      ar.load_receipts(ledger([CLOSE_F1])), {("P", "f1")})

# 2. a later reopen uncounts it (the crtc-test-manifest case).
check("later reopen uncounts the pair",
      ar.load_receipts(ledger([CLOSE_F1, REOPEN_F1])), set())

# 3. a re-close after reopen re-earns closure.
check("reclose after reopen counts again",
      ar.load_receipts(ledger([CLOSE_F1, REOPEN_F1, RECLOSE_F1])),
      {("P", "f1")})

# 4. THE MERGE CASE: rows physically out of order, newest timestamp wins.
#    Union merge lands the reopen ABOVE the close it undoes; the reopen is
#    still the later event and must win.
check("timestamp wins over line order (reopen listed first)",
      ar.load_receipts(ledger([REOPEN_F1, CLOSE_F1])), set())
check("timestamp wins over line order (newer reclose listed before older reopen)",
      ar.load_receipts(ledger([RECLOSE_F1, REOPEN_F1])), {("P", "f1")})

# 5. unrelated findings are independent; malformed rows are skipped safely.
OTHER = {"prd_id": "P", "finding_id": "f2", "closed_at": "2026-01-02T00:00:00Z"}
check("malformed row skipped, other finding unaffected",
      ar.load_receipts(ledger(["{not json", OTHER])), {("P", "f2")})

# 6. MUTATION GUARD: an always-empty loader must fail these checks. Proves the
#    suite can go red for the reason this file exists (codex round 4).
stub = tempfile.mkdtemp()  # directory with NO receipts.jsonl at all
check("mutation guard: empty-loader shape is detectable as wrong",
      ar.load_receipts(ledger([CLOSE_F1])) == ar.load_receipts(stub), False)

if failures:
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)
print("PASS: accept-rate receipt contract holds")
sys.exit(0)
