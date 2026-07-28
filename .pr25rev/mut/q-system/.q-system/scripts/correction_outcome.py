#!/usr/bin/env python3
"""Record a `corrected` memory outcome (issue autocapture-corrected-path,
PRD prd-memory-autocapture-2026-07-04, finding-6).

The deterministic half of the ONE semantic outcome. Choosing WHICH surfaced
memory a founder correction refers to is the interpretive judgment made upstream
in the learn-from-correction flow; this helper holds the part that must be exact:

- Conservative rule: record `corrected` ONLY when the chosen memory_id was
  actually surfaced (recalled) this session. No confident map -> no write. A
  missed correction is safe; a wrong one would be a spurious -1. (The surfaced-set
  membership IS the confident map.)
- All writes go through record_outcome (the single writer). Never touches
  outcomes.jsonl directly.
- Session-stable content-hash event_id, so a replay of the same correction dedups.
- Reads the recall set WITHOUT consuming it (read_recall, not read_and_clear):
  the Stop-hook capture owns consumption; a mid-session correction must not steal
  the surfaced set from the useful/dead_end pass.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(HERE))

import memory_outcomes as mo  # noqa: E402
import session_recall as sr  # noqa: E402


def _was_surfaced(memory_id: str, session_id: str, recall_path: Path | None) -> str | None:
    """Return the surfaced record's source_file for memory_id if it was recalled
    this session, else None. The conservative map."""
    for entry in sr.read_recall(session_id, path=recall_path):
        if entry.get("memory_id") == memory_id:
            return entry.get("source_file")
    return None


def record_correction(memory_id: str, *, session_id: str,
                      recall_path: Path | None = None, log_path: Path | None = None,
                      date: str | None = None, note: str = "") -> dict | None:
    """Record one `corrected` outcome for memory_id, or return None without writing
    when there is no confident map (the memory was not surfaced this session).

    The surfaced-set check is not optional: there is no bypass parameter, so no
    caller can record a corrected outcome for a memory that was not recalled
    (Codex adversarial finding-1).

    Idempotent: the same correction in the same session dedups at the writer."""
    source_file = _was_surfaced(memory_id, session_id, recall_path)
    if source_file is None:
        return None  # no confident map -> no write

    day = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # event_id keys on session_id, NOT the day: a session replayed across UTC
    # midnight must still dedup to one corrected event (finding-2). The written
    # `date` field is still today; only the dedup identity is date-free.
    event_id = mo._auto_event_id(memory_id, "corrected", session_id, "autocapture-correction")
    full_note = note or f"auto-capture correction session={session_id}"
    try:
        return mo.record_outcome(
            memory_id, "corrected", event_id=event_id, date=day, note=full_note,
            source_file=source_file, log_path=log_path)
    except ValueError:
        # Out-of-scope memory_id or bad input: never crash the correction flow.
        return None


if __name__ == "__main__":
    # CLI for the skill / manual use: correction_outcome.py <memory_id> [<session_id>]
    # session_id is optional: when omitted it resolves the same id the producer and
    # the Stop-hook consumer use (sr.resolve_session_id), so the skill does not have
    # to know the session UUID.
    if len(sys.argv) >= 2:
        sid = sys.argv[2] if len(sys.argv) >= 3 else sr.resolve_session_id()
        result = record_correction(sys.argv[1], session_id=sid)
        print("recorded" if result else "no-op (memory not surfaced this session)")
    else:
        print("usage: correction_outcome.py <memory_id> [<session_id>]", file=sys.stderr)
        raise SystemExit(2)
