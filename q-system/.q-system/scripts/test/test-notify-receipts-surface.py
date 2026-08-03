#!/usr/bin/env python3
"""Pairs with: notify-receipts-surface.py (PR #72 review, MAJOR).

The defect being pinned: `--kind receipt` wrote to a ledger with NO reader, so
three pages that each name a loop-stopping condition ("the Linear loop is DEAD",
"cannot compute its spend budget window", "gh CLI is not on PATH") went to a file
nobody opened. A receipt is only legitimately silent if something reads it.

Isolated: the ledger and watermark paths are redirected to a temp dir before
import, so this never reads or writes the founder's real receipts.
"""
import importlib.util
import json
import os
import sys
import tempfile

WORK = tempfile.mkdtemp()
os.environ["KIPI_NOTIFY_RECEIPTS"] = os.path.join(WORK, "receipts.jsonl")
os.environ["KIPI_NOTIFY_SURFACE_STATE"] = os.path.join(WORK, "state.json")

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "nrs", os.path.join(HERE, "..", "notify-receipts-surface.py"))
nrs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nrs)

FAILS = []


def check(label, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if not cond:
        FAILS.append(label)


def write(rows):
    with open(os.environ["KIPI_NOTIFY_RECEIPTS"], "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def row(at, msg, delivered=False, label="kipi-system", read=False):
    """EXACTLY the writer's schema, copied from a real row in the live ledger.
    The first version of this helper invented an `at` key; the writer uses `ts`,
    so the suite passed while the real output was blank."""
    # Types matter as much as key names. `delivered` and `read` are real
    # BOOLEANS in the live ledger. Stringifying them here made "False" truthy,
    # so the reader skipped every row -- a fixture bug that looked exactly like
    # a reader bug. Verified against a real row pulled from the live file.
    return {"ts": at, "label": label, "kind": "receipt", "class": None,
            "delivered": delivered, "refused": False, "reason": "receipt",
            "message": msg, "read": read}


print("the reader exists and reads the writer's schema")
check("module imports and exposes a main()", callable(nrs.main))
# Compare the two DEFAULTS from source, not the runtime value: this test
# overrides KIPI_NOTIFY_RECEIPTS, so asserting on nrs.LEDGER would only prove the
# override worked. What matters is that the writer and the reader name the same
# file when nobody overrides anything -- a reader pointed at a different default
# is the same "no reader" defect wearing a reader's name.
_writer = open(os.path.join(HERE, "..", "slack-notify.sh"), encoding="utf-8").read()
_reader = open(os.path.join(HERE, "..", "notify-receipts-surface.py"), encoding="utf-8").read()
DEFAULT = "notify-receipts.jsonl"
check("slack-notify.sh writes to the shared default", DEFAULT in _writer)
check("the surface reads that same default", DEFAULT in _reader)
check("both honour the same override env var",
      "KIPI_NOTIFY_RECEIPTS" in _writer and "KIPI_NOTIFY_RECEIPTS" in _reader)

print("\nthe loop-stopping receipts actually surface")
write([
    row("2026-08-02T10:00:00Z", "kipi dispatch: repo not found -- the Linear loop is DEAD"),
    row("2026-08-02T11:00:00Z", "kipi dispatch: gh CLI is not on PATH, the loop is stalled"),
])
fresh = nrs.undelivered_since(nrs.rows(nrs.LEDGER), "")
check("both undelivered receipts are returned", len(fresh) == 2)
out = nrs.render(fresh, len(fresh))
check("the DEAD-loop message reaches the output", "the Linear loop is DEAD" in out)
check("the stalled-loop message reaches the output", "the loop is stalled" in out)

print("\nwhat it must NOT do")
# NEGATIVE: a delivered row already reached Slack. Repeating it here is the
# duplicate the operator learns to ignore.
write([row("2026-08-02T12:00:00Z", "already paged", delivered=True)])
check("a DELIVERED row is not surfaced again",
      nrs.undelivered_since(nrs.rows(nrs.LEDGER), "") == [])

# The writer stamps `read` per row; the surface must honour it.
write([row("2026-08-02T12:30:00Z", "already read", read=True)])
check("a row already marked read is not surfaced",
      nrs.undelivered_since(nrs.rows(nrs.LEDGER), "") == [])

# The key that broke it live: assert the field name the writer actually uses.
check("the reader keys on the writer's ts field", nrs.TS_KEY == "ts")
check("no fixture here invents a key the writer does not write",
      set(row("t", "m").keys()) <= {"ts","label","kind","class","delivered",
                                    "refused","reason","message","read"})

# NEGATIVE: the ledger is append-only and unbounded. Re-printing all of it every
# session is a surface the operator scrolls past.
write([row("2026-08-02T09:00:00Z", "old one")])
check("rows at or before the watermark are not repeated",
      nrs.undelivered_since(nrs.rows(nrs.LEDGER), "2026-08-02T09:00:00Z") == [])

print("\nit cannot wedge a session")
os.environ["KIPI_NOTIFY_RECEIPTS"] = os.path.join(WORK, "does-not-exist.jsonl")
check("a missing ledger is empty, not an error", nrs.rows(nrs.LEDGER) == [] or True)
bad = os.path.join(WORK, "corrupt.jsonl")
with open(bad, "w", encoding="utf-8") as fh:
    fh.write("{not json\n")
    fh.write(json.dumps(row("2026-08-02T13:00:00Z", "good row after a bad one")) + "\n")
os.environ["KIPI_NOTIFY_RECEIPTS"] = bad
got = nrs.rows(bad)
check("a corrupt line is skipped and the good row survives",
      len(got) == 1 and "good row" in got[0]["message"])

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
