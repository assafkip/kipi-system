#!/usr/bin/env python3
"""Reproducer-first tests for correction_outcome.py (issue autocapture-corrected-path,
PRD prd-memory-autocapture-2026-07-04, finding-6). Plain script: exit 0 pass / 1 fail.

The `corrected` outcome is the one semantic step. The helper stays conservative:
- a correction that maps to a surfaced memory_id records exactly one corrected line
  -> test_mapped_records_corrected
- a correction whose memory_id was NOT surfaced this session records nothing
  (no confident map, no write)  -> test_unmapped_no_write
- replay is idempotent  -> test_idempotent
- an out-of-scope memory_id never crashes and never writes  -> test_out_of_scope_safe
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import correction_outcome as co  # noqa: E402
import session_recall as sr  # noqa: E402

_failures: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    print(f"PASS {name}" if cond else f"FAIL {name} {detail}")
    if not cond:
        _failures.append(name)


def _outcomes(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(l) for l in log.read_text().splitlines() if l.strip()]


def _seed(recall: Path, session_id: str, ids: list[str]) -> None:
    sr.record_surfaced([(m, f"{m}.md") for m in ids], session_id=session_id,
                       path=recall, surfaced_at="2026-07-04T00:00:00Z")


def test_mapped_records_corrected() -> None:
    with tempfile.TemporaryDirectory() as d:
        recall, log = Path(d) / "r.json", Path(d) / "o.jsonl"
        _seed(recall, "s1", ["feedback_rate_floor_250"])
        res = co.record_correction("feedback_rate_floor_250", session_id="s1",
                                    recall_path=recall, log_path=log, date="2026-07-04")
        rows = _outcomes(log)
        _check("mapped_records_corrected",
               res is not None and len(rows) == 1 and rows[0]["outcome"] == "corrected",
               f"rows={rows}")


def test_unmapped_no_write() -> None:
    with tempfile.TemporaryDirectory() as d:
        recall, log = Path(d) / "r.json", Path(d) / "o.jsonl"
        _seed(recall, "s2", ["some_other_memory"])
        res = co.record_correction("feedback_rate_floor_250", session_id="s2",
                                   recall_path=recall, log_path=log, date="2026-07-04")
        _check("unmapped_no_write", res is None and _outcomes(log) == [],
               f"res={res} log={_outcomes(log)}")


def test_idempotent() -> None:
    with tempfile.TemporaryDirectory() as d:
        recall, log = Path(d) / "r.json", Path(d) / "o.jsonl"
        _seed(recall, "s3", ["mem_a"])
        co.record_correction("mem_a", session_id="s3", recall_path=recall,
                             log_path=log, date="2026-07-04")
        co.record_correction("mem_a", session_id="s3", recall_path=recall,
                             log_path=log, date="2026-07-04")
        _check("idempotent", len(_outcomes(log)) == 1, f"log={_outcomes(log)}")


def test_idempotent_across_midnight() -> None:
    # Same session, different UTC day on replay: must still dedup to one event
    # (event_id keys on session_id, not date). Codex adversarial finding-2.
    with tempfile.TemporaryDirectory() as d:
        recall, log = Path(d) / "r.json", Path(d) / "o.jsonl"
        _seed(recall, "s5", ["mem_a"])
        co.record_correction("mem_a", session_id="s5", recall_path=recall,
                             log_path=log, date="2026-07-04")
        _seed(recall, "s5", ["mem_a"])
        co.record_correction("mem_a", session_id="s5", recall_path=recall,
                             log_path=log, date="2026-07-05")  # next day
        _check("idempotent_across_midnight", len(_outcomes(log)) == 1,
               f"log={_outcomes(log)}")


def test_out_of_scope_safe() -> None:
    with tempfile.TemporaryDirectory() as d:
        recall, log = Path(d) / "r.json", Path(d) / "o.jsonl"
        # A path-shaped id is out of scope; helper must not crash and must not write.
        _seed(recall, "s4", ["mem_a"])
        try:
            res = co.record_correction("../evil", session_id="s4", recall_path=recall,
                                       log_path=log, date="2026-07-04")
        except Exception as exc:  # noqa: BLE001
            _check("out_of_scope_safe", False, f"raised {exc!r}")
            return
        _check("out_of_scope_safe", res is None and _outcomes(log) == [], f"res={res}")


def main() -> int:
    test_mapped_records_corrected()
    test_unmapped_no_write()
    test_idempotent()
    test_idempotent_across_midnight()
    test_out_of_scope_safe()
    if _failures:
        print(f"\n{len(_failures)} FAILURES: {_failures}")
        return 1
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
