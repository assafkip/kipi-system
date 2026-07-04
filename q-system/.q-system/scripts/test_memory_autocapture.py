#!/usr/bin/env python3
"""Reproducer-first tests for memory_autocapture.py (issue autocapture-capture-core,
PRD prd-memory-autocapture-2026-07-04, finding-4).

Proves the deterministic Stop-hook proxies against a synthetic session:
- useful when a surfaced memory's source_file was read      -> test_useful_when_read
- dead_end when surfaced and never touched                  -> test_dead_end_when_untouched
- edited-but-not-read yields NO deterministic signal        -> test_edit_only_no_signal
- idempotent replay writes zero new lines                   -> test_idempotent_replay
- silent-safe with no recall + no transcript                -> test_silent_safe
- all writes go through record_outcome (single writer)      -> test_only_record_outcome_writes
- self-gates OFF unless the instance is allowlisted         -> test_gate_default_off / on
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import memory_autocapture as mac  # noqa: E402
import memory_outcomes as mo  # noqa: E402
import session_recall as sr  # noqa: E402


def _write_transcript(path: Path, read_paths: list[str], edited_paths: list[str] | None = None) -> None:
    """Write a minimal session JSONL: one Read tool_use per read path, one Edit per edited."""
    lines = []
    for fp in read_paths:
        lines.append({"message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": fp}}]}})
    for fp in (edited_paths or []):
        lines.append({"message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": fp}}]}})
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


def _seed_recall(recall_path: Path, session_id: str, entries: list[tuple[str, str]]) -> None:
    sr.record_surfaced(entries, session_id=session_id, path=recall_path,
                       surfaced_at="2026-07-04T00:00:00Z")


def _run(tmp_path: Path, session_id, read_paths, surfaced, edited=None):
    recall = tmp_path / ".session-recall.json"
    log = tmp_path / "outcomes.jsonl"
    transcript = tmp_path / "transcript.jsonl"
    _seed_recall(recall, session_id, surfaced)
    _write_transcript(transcript, read_paths, edited)
    mac.capture(session_id=session_id, transcript_path=transcript,
                recall_path=recall, log_path=log, date="2026-07-04")
    return log


def _outcomes(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(l) for l in log.read_text().splitlines() if l.strip()]


def test_useful_when_read(tmp_path):
    log = _run(tmp_path, "s1",
               read_paths=["/x/q-system/memory/feedback_rate_floor_250.md"],
               surfaced=[("feedback_rate_floor_250", "feedback_rate_floor_250.md")])
    rows = _outcomes(log)
    assert len(rows) == 1
    assert rows[0]["memory_id"] == "feedback_rate_floor_250"
    assert rows[0]["outcome"] == "useful"


def test_dead_end_when_untouched(tmp_path):
    log = _run(tmp_path, "s2", read_paths=["/x/unrelated.md"],
               surfaced=[("project_chris_pi_deal", "project_chris_pi_deal.md")])
    rows = _outcomes(log)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "dead_end"


def test_edit_only_no_signal(tmp_path):
    # Edited but never read: ambiguous, left to the corrected path -> no write here.
    log = _run(tmp_path, "s3", read_paths=[],
               surfaced=[("mem_edited", "mem_edited.md")],
               edited=["/x/q-system/memory/mem_edited.md"])
    assert _outcomes(log) == []


def test_idempotent_replay(tmp_path):
    recall = tmp_path / ".session-recall.json"
    log = tmp_path / "outcomes.jsonl"
    transcript = tmp_path / "t.jsonl"
    _seed_recall(recall, "s4", [("m_a", "m_a.md")])
    _write_transcript(transcript, ["/x/m_a.md"], None)
    mac.capture(session_id="s4", transcript_path=transcript, recall_path=recall,
                log_path=log, date="2026-07-04")
    first = len(_outcomes(log))
    # Re-seed recall (capture consumed it) and re-run: event_id is session-stable.
    _seed_recall(recall, "s4", [("m_a", "m_a.md")])
    mac.capture(session_id="s4", transcript_path=transcript, recall_path=recall,
                log_path=log, date="2026-07-04")
    assert len(_outcomes(log)) == first == 1


def test_silent_safe(tmp_path):
    log = tmp_path / "outcomes.jsonl"
    # No recall file, no transcript file: must not raise, must not write.
    mac.capture(session_id="s5", transcript_path=tmp_path / "missing.jsonl",
                recall_path=tmp_path / "missing.json", log_path=log, date="2026-07-04")
    assert _outcomes(log) == []


def test_missing_transcript_preserves_recall(tmp_path):
    # An unreadable transcript must NOT emit dead_end for everything and must NOT
    # consume recall (so a retry can still classify). Codex adversarial finding-1/4.
    recall = tmp_path / ".session-recall.json"
    log = tmp_path / "outcomes.jsonl"
    _seed_recall(recall, "s7", [("m_x", "m_x.md")])
    mac.capture(session_id="s7", transcript_path=tmp_path / "does-not-exist.jsonl",
                recall_path=recall, log_path=log, date="2026-07-04")
    assert _outcomes(log) == []
    # recall still intact for a retry
    assert {e["memory_id"] for e in sr.read_recall("s7", path=recall)} == {"m_x"}


def test_only_record_outcome_writes(tmp_path):
    # Every written line must be a valid record_outcome event (has event_id).
    log = _run(tmp_path, "s6", read_paths=["/x/m_b.md"], surfaced=[("m_b", "m_b.md")])
    for row in _outcomes(log):
        assert row.get("event_id")
        assert row["outcome"] in mo.VALID_OUTCOMES


def test_gate_default_off(tmp_path):
    # No config -> disabled (design-partner-first, default off fleet-wide).
    assert mac.is_enabled(config_path=tmp_path / "none.json", instance_id="anything") is False


def test_gate_on_when_allowlisted(tmp_path):
    cfg = tmp_path / "autocapture_config.json"
    cfg.write_text(json.dumps({"enabled_instances": ["4_points_consulting"]}))
    assert mac.is_enabled(config_path=cfg, instance_id="4_points_consulting") is True
    assert mac.is_enabled(config_path=cfg, instance_id="some_other") is False
