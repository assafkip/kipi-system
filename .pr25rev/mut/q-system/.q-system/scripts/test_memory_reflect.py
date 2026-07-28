"""Tests for memory_reflect.py — the earned-trust scoring engine.

Ports graphify reflect.py's model to kipi's flat outcome log (finding-4 covers
the source-fingerprint resolver; the `fingerprint` test is the bypass_check).
Deterministic: every test pins `now` so output is byte-stable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import memory_outcomes as mo
import memory_reflect as mr

NOW = datetime(2026, 7, 4, tzinfo=timezone.utc)


def _log(tmp_path):
    return tmp_path / "outcomes.jsonl"


def _rec(log, memory_id, outcome, eid, date, **kw):
    return mo.record_outcome(memory_id, outcome, event_id=eid, date=date,
                             log_path=log, **kw)


def test_corroboration_promotes_after_two_distinct_useful(tmp_path):
    log = _log(tmp_path)
    _rec(log, "m1", "useful", "e1", "2026-07-01")
    _rec(log, "m1", "useful", "e2", "2026-07-02")
    agg = mr.aggregate(mo.read_events(log), now=NOW)
    pref = {e["memory_id"] for e in agg["preferred"]}
    assert "m1" in pref


def test_single_useful_is_tentative_not_preferred(tmp_path):
    log = _log(tmp_path)
    _rec(log, "m1", "useful", "e1", "2026-07-01")
    agg = mr.aggregate(mo.read_events(log), now=NOW)
    assert {e["memory_id"] for e in agg["tentative"]} == {"m1"}
    assert agg["preferred"] == []


def test_duplicate_event_ids_do_not_corroborate(tmp_path):
    """Two writes, same event_id -> dedup at the log -> only ONE distinct useful,
    so m1 stays tentative, never preferred."""
    log = _log(tmp_path)
    _rec(log, "m1", "useful", "same", "2026-07-01")
    _rec(log, "m1", "useful", "same", "2026-07-02")  # deduped by the log
    agg = mr.aggregate(mo.read_events(log), now=NOW)
    assert agg["preferred"] == []
    assert {e["memory_id"] for e in agg["tentative"]} == {"m1"}


def test_fresh_dead_end_outweighs_old_useful(tmp_path):
    log = _log(tmp_path)
    _rec(log, "m1", "useful", "e1", "2026-01-01")   # ~6 months old
    _rec(log, "m1", "dead_end", "e2", "2026-07-03")  # fresh
    agg = mr.aggregate(mo.read_events(log), now=NOW)
    contested = {e["memory_id"]: e for e in agg["contested"]}
    assert "m1" in contested
    assert contested["m1"]["verdict"] == "dead end"  # recency (score < 0)


def test_negative_only_is_dead_end(tmp_path):
    log = _log(tmp_path)
    _rec(log, "m1", "dead_end", "e1", "2026-07-01")
    agg = mr.aggregate(mo.read_events(log), now=NOW)
    assert "m1" in {e["memory_id"] for e in agg["dead_ends"]}
    assert agg["preferred"] == [] and agg["tentative"] == []


def test_sidecar_is_byte_stable(tmp_path):
    log = _log(tmp_path)
    _rec(log, "m1", "useful", "e1", "2026-07-01")
    _rec(log, "m1", "useful", "e2", "2026-07-02")
    scores = tmp_path / ".memory-scores.json"
    mr.write_sidecar(mo.read_events(log), scores, now=NOW)
    first = scores.read_bytes()
    mr.write_sidecar(mo.read_events(log), scores, now=NOW)
    assert scores.read_bytes() == first  # identical input + now => identical bytes


def test_fingerprint_marks_stale_when_source_changes(tmp_path):
    """bypass_check: a scored memory citing a file is stale after the file changes."""
    src = tmp_path / "thing.py"
    src.write_text("original\n")
    log = _log(tmp_path)
    _rec(log, "m1", "useful", "e1", "2026-07-01", source_file=str(src))
    _rec(log, "m1", "useful", "e2", "2026-07-02", source_file=str(src))
    scores = tmp_path / ".memory-scores.json"
    mr.write_sidecar(mo.read_events(log), scores, now=NOW, root=tmp_path)

    loaded = mr.load_sidecar(scores, root=tmp_path)
    assert loaded["m1"]["stale"] is False  # unchanged file

    src.write_text("CHANGED\n")
    loaded2 = mr.load_sidecar(scores, root=tmp_path)
    assert loaded2["m1"]["stale"] is True  # source content changed -> re-verify


def test_fingerprint_missing_file_is_stale(tmp_path):
    src = tmp_path / "gone.py"
    src.write_text("x\n")
    log = _log(tmp_path)
    _rec(log, "m1", "useful", "e1", "2026-07-01", source_file=str(src))
    _rec(log, "m1", "useful", "e2", "2026-07-02", source_file=str(src))
    scores = tmp_path / ".memory-scores.json"
    mr.write_sidecar(mo.read_events(log), scores, now=NOW, root=tmp_path)
    src.unlink()
    assert mr.load_sidecar(scores, root=tmp_path)["m1"]["stale"] is True


def test_engine_dedups_duplicate_event_id_in_score(tmp_path):
    """Feed the engine a raw log with a repeated event_id (foreign/hand-edited);
    the score must not double-count it (review finding)."""
    events = [
        {"memory_id": "m1", "outcome": "useful", "event_id": "e1", "date": "2026-07-01"},
        {"memory_id": "m1", "outcome": "useful", "event_id": "e1", "date": "2026-07-01"},
    ]
    one = mr.aggregate(events[:1], now=NOW)
    two = mr.aggregate(events, now=NOW)
    # Same single distinct event -> identical aggregate, still tentative not preferred.
    assert two["tentative"] and two["preferred"] == []
    assert two["tentative"][0]["score"] == one["tentative"][0]["score"]


def test_resolve_repo_root_relative_source(tmp_path):
    """A source_file recorded repo-root-relative (q-system/...) resolves against
    root.parent, independent of cwd (review finding)."""
    repo = tmp_path
    qroot = repo / "q-system"
    (qroot / "my-project").mkdir(parents=True)
    src = qroot / "my-project" / "cur.md"
    src.write_text("state\n")
    events = [
        {"memory_id": "m1", "outcome": "useful", "event_id": "e1", "date": "2026-07-01",
         "source_file": "q-system/my-project/cur.md"},
        {"memory_id": "m1", "outcome": "useful", "event_id": "e2", "date": "2026-07-02",
         "source_file": "q-system/my-project/cur.md"},
    ]
    scores = repo / "scores.json"
    mr.write_sidecar(events, scores, now=NOW, root=qroot)  # root=QROOT, path is repo-relative
    loaded = mr.load_sidecar(scores, root=qroot)
    assert loaded["m1"]["stale"] is False  # resolved via root.parent, not marked missing


def test_no_source_file_never_stale(tmp_path):
    log = _log(tmp_path)
    _rec(log, "m1", "useful", "e1", "2026-07-01")
    _rec(log, "m1", "useful", "e2", "2026-07-02")
    scores = tmp_path / ".memory-scores.json"
    mr.write_sidecar(mo.read_events(log), scores, now=NOW, root=tmp_path)
    assert mr.load_sidecar(scores, root=tmp_path)["m1"]["stale"] is False
