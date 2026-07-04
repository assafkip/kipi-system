"""Tests for memory_outcomes.py — the outcome event log + single-writer.

Issue memory-outcome-log (finding-3): event_id dedup so a replayed/duplicate
write cannot inflate the corroboration count. Reproducer-first: the `dedup`
test is the bypass_check.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import memory_outcomes as mo


def _read(log: Path) -> list[dict]:
    return [json.loads(l) for l in log.read_text().splitlines() if l.strip()]


def test_record_appends_one_line(tmp_path):
    log = tmp_path / "outcomes.jsonl"
    ev = mo.record_outcome("feedback_rate_floor_250", "useful", event_id="e1",
                           date="2026-07-04", note="drove the pricing reply",
                           log_path=log)
    assert ev is not None
    rows = _read(log)
    assert len(rows) == 1
    assert rows[0]["memory_id"] == "feedback_rate_floor_250"
    assert rows[0]["outcome"] == "useful"
    assert rows[0]["event_id"] == "e1"


def test_invalid_outcome_rejected(tmp_path):
    log = tmp_path / "outcomes.jsonl"
    with pytest.raises(ValueError):
        mo.record_outcome("m1", "helpful", event_id="e1", log_path=log)
    assert not log.exists() or _read(log) == []


def test_missing_event_id_rejected(tmp_path):
    log = tmp_path / "outcomes.jsonl"
    with pytest.raises(ValueError):
        mo.record_outcome("m1", "useful", event_id="", log_path=log)


def test_dedup_duplicate_event_id_not_appended(tmp_path):
    """A second write with the same event_id must not add a second line."""
    log = tmp_path / "outcomes.jsonl"
    first = mo.record_outcome("m1", "useful", event_id="dup", log_path=log)
    second = mo.record_outcome("m1", "useful", event_id="dup", log_path=log)
    assert first is not None
    assert second is None  # deduped
    assert len(_read(log)) == 1


def test_distinct_event_ids_both_appended(tmp_path):
    log = tmp_path / "outcomes.jsonl"
    mo.record_outcome("m1", "useful", event_id="a", log_path=log)
    mo.record_outcome("m1", "useful", event_id="b", log_path=log)
    assert len(_read(log)) == 2


def test_read_events_skips_malformed(tmp_path):
    log = tmp_path / "outcomes.jsonl"
    mo.record_outcome("m1", "useful", event_id="a", log_path=log)
    with log.open("a") as fh:
        fh.write("{ not json\n")
    mo.record_outcome("m1", "dead_end", event_id="b", log_path=log)
    events = mo.read_events(log)
    assert len(events) == 2  # malformed line skipped, both valid kept


def test_incomplete_dict_not_counted_as_event(tmp_path):
    """A parseable-but-incomplete line (has event_id, missing memory_id/outcome)
    must not be returned by read_events NOR block a later real event with that id
    (review finding-2)."""
    log = tmp_path / "outcomes.jsonl"
    with log.open("w") as fh:
        fh.write('{"event_id": "e1"}\n')  # incomplete
    assert mo.read_events(log) == []
    ev = mo.record_outcome("m1", "useful", event_id="e1", log_path=log)
    assert ev is not None  # not blocked by the incomplete line
    assert len(mo.read_events(log)) == 1


@pytest.mark.parametrize("bad_id", [
    "a/b", "../evil", "/etc/passwd", "a\\b", "..", "",
    "fooÿbar", "foo／bar", "．．secret", "foo\x00bar",
    "m1 ", " m1", ".hidden", "foo bar",
])
def test_scope_rejects_out_of_scope_memory_id(tmp_path, bad_id):
    """record_outcome refuses a memory_id that escapes the scored store, so the
    log never accumulates outcomes the surface cannot cover (finding-1)."""
    log = tmp_path / "outcomes.jsonl"
    with pytest.raises(ValueError):
        mo.record_outcome(bad_id, "useful", event_id="e1", log_path=log)
    assert not log.exists() or _read(log) == []


def test_scope_accepts_normal_slug(tmp_path):
    log = tmp_path / "outcomes.jsonl"
    ev = mo.record_outcome("feedback_rate_floor_250", "useful", event_id="e1", log_path=log)
    assert ev is not None


def test_append_after_line_without_trailing_newline(tmp_path):
    """A prior line with no trailing newline must not swallow the new event
    (review finding-3 adversarial)."""
    log = tmp_path / "outcomes.jsonl"
    mo.record_outcome("m1", "useful", event_id="a", log_path=log)
    # Corrupt: strip the trailing newline the writer added.
    log.write_text(log.read_text().rstrip("\n"))
    ev = mo.record_outcome("m1", "dead_end", event_id="b", log_path=log)
    assert ev is not None
    assert len(mo.read_events(log)) == 2  # both survive, not concatenated/lost
