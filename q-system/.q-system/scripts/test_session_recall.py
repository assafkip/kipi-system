#!/usr/bin/env python3
"""Reproducer-first tests for session_recall.py (issue autocapture-recall-artifact,
finding-5). Plain-script test: exits 0 on pass, 1 on failure, so the required_check
`python3 test_session_recall.py` gates the issue.

What finding-5 asked for and each test proves:
- The surfaced set is keyed by session_id and overlapping sessions never mix or
  truncate each other  -> test_two_sessions_do_not_mix.
- A single-writer merge that does not lose an update when two surface scripts
  write the same session  -> test_second_writer_merges_not_clobbers.
- Exactly the surfaced ids are recorded, de-duplicated  -> test_records_exact_ids,
  test_dedup_within_session.
- Atomic write leaves valid JSON  -> test_file_always_valid_json.
- The surface script producer path records the ids  -> test_surface_producer_emits.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import session_recall as sr  # noqa: E402


def _load_hyphenated(module_name: str, filename: str):
    """Import a hyphenated script (memory-scores-surface.py) by path."""
    spec = importlib.util.spec_from_file_location(module_name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_failures: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {detail}")
        _failures.append(name)


def test_records_exact_ids() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".session-recall.json"
        sr.record_surfaced(
            [("feedback_rate_floor_250", "feedback_rate_floor_250.md"),
             ("project_chris_pi_deal", "project_chris_pi_deal.md")],
            session_id="sess-A", path=p, surfaced_at="2026-07-04T00:00:00Z")
        got = {e["memory_id"] for e in sr.read_recall("sess-A", path=p)}
        _check("records_exact_ids",
               got == {"feedback_rate_floor_250", "project_chris_pi_deal"},
               f"got={got}")


def test_two_sessions_do_not_mix() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".session-recall.json"
        sr.record_surfaced([("mem_a", "mem_a.md")], session_id="sess-A", path=p)
        sr.record_surfaced([("mem_b", "mem_b.md")], session_id="sess-B", path=p)
        a = {e["memory_id"] for e in sr.read_recall("sess-A", path=p)}
        b = {e["memory_id"] for e in sr.read_recall("sess-B", path=p)}
        _check("two_sessions_do_not_mix",
               a == {"mem_a"} and b == {"mem_b"}, f"a={a} b={b}")


def test_second_writer_merges_not_clobbers() -> None:
    # Two surface scripts (scores + confidence) write the SAME session; the
    # second write must not drop the first writer's ids.
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".session-recall.json"
        sr.record_surfaced([("from_scores", "from_scores.md")],
                           session_id="sess-A", path=p)
        sr.record_surfaced([("from_confidence", "from_confidence.md")],
                           session_id="sess-A", path=p)
        got = {e["memory_id"] for e in sr.read_recall("sess-A", path=p)}
        _check("second_writer_merges_not_clobbers",
               got == {"from_scores", "from_confidence"}, f"got={got}")


def test_dedup_within_session() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".session-recall.json"
        sr.record_surfaced([("mem_a", "mem_a.md")], session_id="sess-A", path=p)
        sr.record_surfaced([("mem_a", "mem_a.md")], session_id="sess-A", path=p)
        rows = sr.read_recall("sess-A", path=p)
        _check("dedup_within_session", len(rows) == 1, f"rows={rows}")


def test_file_always_valid_json() -> None:
    import json
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".session-recall.json"
        for i in range(5):
            sr.record_surfaced([(f"mem_{i}", f"mem_{i}.md")],
                               session_id=f"sess-{i % 2}", path=p)
        data = json.loads(p.read_text())
        _check("file_always_valid_json", isinstance(data, dict), f"type={type(data)}")


def test_read_missing_is_empty() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".session-recall.json"
        _check("read_missing_is_empty",
               sr.read_recall("nope", path=p) == [], "expected []")


def test_read_and_clear_is_atomic_snapshot() -> None:
    # read_and_clear returns exactly what it removes; a later read is empty.
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".session-recall.json"
        sr.record_surfaced([("mem_a", "mem_a.md"), ("mem_b", "mem_b.md")],
                           session_id="sess-A", path=p)
        snap = {e["memory_id"] for e in sr.read_and_clear("sess-A", path=p)}
        after = sr.read_recall("sess-A", path=p)
        _check("read_and_clear_is_atomic_snapshot",
               snap == {"mem_a", "mem_b"} and after == [],
               f"snap={snap} after={after}")


def test_read_and_clear_missing_is_empty() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".session-recall.json"
        _check("read_and_clear_missing_is_empty",
               sr.read_and_clear("nope", path=p) == [], "expected []")


def test_surface_producer_emits() -> None:
    # The surface script, given surfaced scores, records their ids into the
    # session-recall file via the single-writer helper (producer wiring).
    surface = _load_hyphenated("memory_scores_surface", "memory-scores-surface.py")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".session-recall.json"
        scores = {
            "feedback_rate_floor_250": {"status": "preferred"},
            "project_chris_pi_deal": {"status": "contested"},
        }
        surface.record_surfaced_from_scores(scores, session_id="sess-X", recall_path=p)
        got = {e["memory_id"] for e in sr.read_recall("sess-X", path=p)}
        _check("surface_producer_emits",
               got == {"feedback_rate_floor_250", "project_chris_pi_deal"},
               f"got={got}")


def main() -> int:
    test_records_exact_ids()
    test_two_sessions_do_not_mix()
    test_second_writer_merges_not_clobbers()
    test_dedup_within_session()
    test_file_always_valid_json()
    test_read_missing_is_empty()
    test_read_and_clear_is_atomic_snapshot()
    test_read_and_clear_missing_is_empty()
    test_surface_producer_emits()
    if _failures:
        print(f"\n{len(_failures)} FAILURES: {_failures}")
        return 1
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
