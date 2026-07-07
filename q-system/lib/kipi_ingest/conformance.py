#!/usr/bin/env python3
"""Conformance harness for the fleet ingestion coverage contract.

Reproducer-first: plants the exact silent losses the sibling audits found, then
asserts the contract + readers now CATCH each one (either the content survives in
a block, or the receipt reports it). Every adopter runs this against its own
wiring; the skeleton runs it as the contract's own regression gate.

Run:  python3 q-system/lib/kipi_ingest/conformance.py
Exit: 0 = all green, 1 = a conformance assertion failed.

This is the behavior gate. The DRIFT gate (instance copy == skeleton canonical)
is a separate check wired into kipi update.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Import exactly as an instance will: add q-system/lib to sys.path, then
# `import kipi_ingest`. This run also proves that shim works.
_LIB = Path(__file__).resolve().parents[1]  # .../q-system/lib
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from kipi_ingest import (  # noqa: E402
    Block,
    DuplicateBlockError,
    ReadResult,
    UngroundedReferenceError,
    UnreadUnitError,
    ground,
    index_blocks,
    make_block_id,
    reconcile,
)
from kipi_ingest.readers import read_csv, read_md  # noqa: E402

_results: list[tuple[bool, str]] = []


def check(cond: bool, label: str) -> None:
    _results.append((bool(cond), label))
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")


def raises(exc, fn, label: str) -> None:
    try:
        fn()
        check(False, f"{label} (expected {exc.__name__}, none raised)")
    except exc:
        check(True, label)
    except Exception as e:  # noqa: BLE001
        check(False, f"{label} (expected {exc.__name__}, got {type(e).__name__}: {e})")


# --------------------------------------------------------------------------- #
def test_counting_layer() -> None:
    print("\n== Layer 1: counting (recall, caps, reconciliation) ==")
    r = ReadResult(unit="page", attempted=10, captured=9, truncated=False)
    check(abs(r.recall() - 0.9) < 1e-9, "recall = captured/attempted")
    check(r.is_lossy(), "recall < 1.0 is lossy")
    check(ReadResult(unit="page", attempted=0, captured=0).recall() == 1.0,
          "empty source recall defined as 1.0")
    check(ReadResult(unit="page", attempted=5, captured=5, truncated=True).is_lossy(),
          "truncated is lossy even at full count (fail closed)")
    raises(ValueError,
           lambda: ReadResult(unit="page", attempted=3, captured=4),
           "captured > attempted rejected (reader miscount)")
    # reconcile names the miss instead of silently skipping.
    raises(UnreadUnitError,
           lambda: reconcile(["p1", "p2", "p3"], {"p1", "p3"}),
           "reconcile raises + names an unread enumerated unit")
    reconcile(["p1", "p2"], {"p1", "p2"})  # no raise
    check(True, "reconcile passes when every unit is captured")


def test_provenance_layer() -> None:
    print("\n== Layer 2: provenance (block ids, grounding gate) ==")
    check(make_block_id("t", 4, 2) == "t.p4.2", "block id format kind.pN.index")
    raises(ValueError, lambda: make_block_id("t", 4), "block id needs an index part")
    b = Block(block_id="t.p1.0", unit="page", page=1, text="real text")
    idx = index_blocks([b])
    check(ground("t.p1.0", idx) is b, "ground returns the read block")
    raises(UngroundedReferenceError, lambda: ground("t.p9.9", idx),
           "reference to an unread block raises (cannot fake coverage)")
    raises(DuplicateBlockError,
           lambda: index_blocks([b, Block("t.p1.0", "page", 1, "twin")]),
           "duplicate block_id fails closed")


def test_markdown_live_loss() -> None:
    print("\n== Reader: markdown (LIVE loss: fences + frontmatter stripped) ==")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "case.md"
        p.write_text(
            "---\ntitle: Case Notes\nowner: analyst-7\n---\n"
            "# Findings\nSuspect email jane@example.com\n\n"
            "```\nEVIDENCE\nwallet bc1qFENCEDwallet\nphone 415-555-0333\n```\n\nEnd.\n"
        )
        blocks, r = read_md(p)
        alltext = "\n".join(b.text for b in blocks)
        check("bc1qFENCEDwallet" in alltext, "wallet inside code fence survives")
        check("415-555-0333" in alltext, "phone inside code fence survives")
        check("analyst-7" in alltext, "owner in frontmatter survives")
        check("jane@example.com" in alltext, "prose email survives")
        check(any(b.unit == "fenced_block" for b in blocks), "fenced block is addressable")
        check(r.recall() == 1.0 and not r.is_lossy(), "receipt: nothing lost (recall 1.0)")


def test_csv_losses() -> None:
    print("\n== Reader: csv (header/1-row loss + silent cap) ==")
    with tempfile.TemporaryDirectory() as d:
        # Header-only / single-row file: header captured, not assumed away.
        p1 = Path(d) / "one.csv"
        p1.write_text("wallet,phone\n")
        b1, r1 = read_csv(p1)
        check(any("wallet" in b.text for b in b1), "single header row captured, not dropped")
        check(not r1.is_lossy(), "header-only file is not lossy")
        # Multi-row: every row captured.
        p2 = Path(d) / "many.csv"
        p2.write_text("wallet,phone\nbc1qAAA,415-555-0001\nbc1qBBB,415-555-0002\n")
        b2, r2 = read_csv(p2)
        t2 = "\n".join(b.text for b in b2)
        check("bc1qAAA" in t2 and "bc1qBBB" in t2, "every data row captured")
        check(r2.attempted == 3 and not r2.is_lossy(), "attempted counts header + all rows")
        # Row cap: truncation is COUNTED, not a silent break.
        b3, r3 = read_csv(p2, max_rows=1)
        check(r3.truncated and r3.is_lossy(), "row cap sets truncated + lossy")
        check(r3.dropped and "not read" in r3.dropped[0].reason, "cap records a drop reason")


def test_xlsx_losses() -> None:
    print("\n== Reader: xlsx (first-sheet-only + formula loss) ==")
    try:
        from openpyxl import Workbook
    except ImportError:
        print("  [SKIP] openpyxl absent")
        return
    from kipi_ingest.readers import read_xlsx  # via public API (guards the export)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "book.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "Visible"
        ws.append(["Item", "Qty", "Price", "Total"])
        ws.append(["Widget", 3, 100, "=B2*C2"])          # formula, no cached value
        s2 = wb.create_sheet("Second")
        s2.append(["contact"])
        s2.append(["bc1qSHEET2wallet"])                  # lives on a NON-first sheet
        wb.save(p)
        blocks, r = read_xlsx(p)
        alltext = "\n".join(b.text for b in blocks)
        check("bc1qSHEET2wallet" in alltext, "non-first sheet is read (first-sheet-only fixed)")
        check("=B2*C2" in alltext, "uncomputed formula cell preserved, not blanked")
        check("Item" in alltext, "header row captured")
        check(not r.is_lossy(), "receipt: nothing lost at full read")
        # sheet cap is counted, not silent.
        _, rc = read_xlsx(p, max_sheets=1)
        check(rc.truncated and any("not read" in dd.reason for dd in rc.dropped),
              "sheet cap sets truncated + records the skipped sheet")


def main() -> int:
    print("kipi_ingest conformance harness")
    test_counting_layer()
    test_provenance_layer()
    test_markdown_live_loss()
    test_csv_losses()
    test_xlsx_losses()
    passed = sum(1 for ok, _ in _results if ok)
    total = len(_results)
    print(f"\n=== {passed}/{total} checks passed ===")
    if passed != total:
        print("CONFORMANCE FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
