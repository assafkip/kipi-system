#!/usr/bin/env python3
"""End-to-end acceptance for memory auto-capture (issue autocapture-e2e-acceptance,
PRD prd-memory-autocapture-2026-07-04, finding-2).

Replaces the PRD's vague "signal good enough" language with a DETERMINISTIC
threshold: a design-partner-realistic session set, fed through the real capture
path (NOT manual record_outcome calls), must move memory_reflect's verdicts:
  - >= 1 memory reaches `preferred` (>= 2 distinct useful events), and
  - >= 1 memory reaches `dead_ends`,
using ONLY auto-captured outcomes. Exit 0 pass / 1 fail.

This is the whole point of the referee: prove the loop closes without a human
typing a CLI command.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import correction_outcome as co  # noqa: E402
import memory_autocapture as mac  # noqa: E402
import memory_outcomes as mo  # noqa: E402
import memory_reflect as mr  # noqa: E402
import session_recall as sr  # noqa: E402

_failures: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    print(f"PASS {name}" if cond else f"FAIL {name} {detail}")
    if not cond:
        _failures.append(name)


def _write_transcript(path: Path, read_paths: list[str]) -> None:
    import json
    lines = [{"message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": fp}}]}}
        for fp in read_paths]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


def _session(tmp: Path, log: Path, session_id: str, surfaced, read_paths, day) -> None:
    """One realistic session: surface memories, read some files, run capture."""
    recall = tmp / f"recall-{session_id}.json"
    transcript = tmp / f"t-{session_id}.jsonl"
    sr.record_surfaced(surfaced, session_id=session_id, path=recall,
                       surfaced_at=f"{day}T00:00:00Z")
    _write_transcript(transcript, read_paths)
    mac.capture(session_id=session_id, transcript_path=transcript,
                recall_path=recall, log_path=log, date=day)


def main() -> int:
    now = datetime(2026, 7, 4, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        log = tmp / "outcomes.jsonl"

        lean = ("mem_lean_on", "mem_lean_on.md")     # read in 2 sessions -> preferred
        dead = ("mem_dead_end", "mem_dead_end.md")   # surfaced, never read -> dead_end

        # Session 1: both surfaced; only mem_lean_on read.
        _session(tmp, log, "sess-1", [lean, dead],
                 ["/proj/q-system/memory/mem_lean_on.md"], "2026-07-04")
        # Session 2: mem_lean_on surfaced and read again (2nd distinct useful).
        _session(tmp, log, "sess-2", [lean],
                 ["/proj/q-system/memory/mem_lean_on.md"], "2026-07-04")

        # A corrected outcome via the correction path (also auto, no manual CLI).
        corr_recall = tmp / "recall-corr.json"
        sr.record_surfaced([("mem_corrected", "mem_corrected.md")],
                           session_id="sess-3", path=corr_recall,
                           surfaced_at="2026-07-04T00:00:00Z")
        co.record_correction("mem_corrected", session_id="sess-3",
                             recall_path=corr_recall, log_path=log, date="2026-07-04")

        events = mo.read_events(log)
        # Sanity: the log filled itself, only via the capture path.
        _check("log_filled_by_capture", len(events) >= 3, f"events={len(events)}")

        agg = mr.aggregate(events, now=now)
        preferred_ids = {e["memory_id"] for e in agg["preferred"]}
        dead_ids = {e["memory_id"] for e in agg["dead_ends"]}

        _check("preferred_move", "mem_lean_on" in preferred_ids,
               f"preferred={preferred_ids}")
        _check("dead_end_move", "mem_dead_end" in dead_ids, f"dead={dead_ids}")
        _check("corrected_is_negative", "mem_corrected" in dead_ids,
               f"dead={dead_ids}")
        # The trust move used only auto-captured outcomes: every event carries the
        # auto-capture note.
        _check("all_auto_captured",
               all("auto" in (e.get("note") or "").lower() for e in events),
               "an event lacked the auto-capture note")

    if _failures:
        print(f"\n{len(_failures)} FAILURES: {_failures}")
        return 1
    print("\nALL PASS -- the outcomes log filled itself and moved memory_reflect verdicts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
