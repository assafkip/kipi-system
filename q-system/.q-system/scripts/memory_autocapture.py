#!/usr/bin/env python3
"""The referee: deterministic Stop-hook auto-capture of memory outcomes
(issue autocapture-capture-core, PRD prd-memory-autocapture-2026-07-04, finding-4).

Earned-trust scoring (parent PRD, PR #6) was live but inert: nothing fed
outcomes.jsonl except a manual CLI. This closes that loop for the two high-volume,
noise-tolerant outcomes, deterministically and with no LLM call:

- useful   = a surfaced memory's source_file was READ this session.
- dead_end = a surfaced memory whose source was NEVER touched this session.

The `corrected` outcome is NOT emitted here: it needs semantics and is owned by
the learn-from-correction path (issue autocapture-corrected-path).

Why deterministic proxies are enough (not a per-session LLM judge): memory_reflect
already filters noise (a >=2 distinct-event corroboration gate + signed time-decay
+ a contested bucket). Capture only has to be an approximately-unbiased signal
generator, so cheap read/never-touched proxies suffice.

Discipline:
- record_outcome is the SINGLE WRITER. Capture NEVER appends to outcomes.jsonl
  directly; a per-memory try/except means one bad id cannot abort the batch.
- event_id is session-stable (mo._auto_event_id keyed by session_id), so a replay
  of the same session dedups while the same memory being useful in a DIFFERENT
  session is a distinct event that can corroborate.
- Silent-safe: any missing input or error path returns 0 and writes nothing. A
  capture bug must never block a session close.
- Self-gated OFF unless the current instance is allowlisted (design-partner first).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(HERE))

import memory_outcomes as mo  # noqa: E402
import session_recall as sr  # noqa: E402

# QROOT = q-system/ (this script is at q-system/.q-system/scripts/).
QROOT = Path(os.path.join(str(HERE), "..", "..")).resolve()
DEFAULT_CONFIG = HERE / "autocapture_config.json"

# Tool calls that count as touching a file, and the subset that counts as reading.
_READ_TOOLS = {"Read"}
_TOUCH_TOOLS = {"Read", "Edit", "Write", "NotebookEdit"}


def _current_instance(instance_id: str | None = None) -> str:
    """The instance this session runs in. Env override wins; else the project dir
    name (q-system/..'s parent), e.g. `4_points_consulting` or `kipi-system`."""
    if instance_id:
        return instance_id
    env = os.environ.get("KIPI_INSTANCE")
    if env and env.strip():
        return env.strip()
    return QROOT.parent.name


def is_enabled(*, config_path: Path | None = None, instance_id: str | None = None) -> bool:
    """True only when the current instance is in the allowlist. DEFAULT OFF: a
    missing/malformed config, or an instance not listed, disables capture. This is
    the design-partner-first gate, so shipping the script fleet-wide via the
    skeleton leaves it inert everywhere except the allowlisted instance(s)."""
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    allow = cfg.get("enabled_instances") if isinstance(cfg, dict) else None
    if not isinstance(allow, list):
        return False
    return _current_instance(instance_id) in allow


def _touched_basenames(transcript_path: Path) -> tuple[set[str], set[str]]:
    """Return (read_basenames, touched_basenames) from the session transcript.

    The transcript is JSONL; each record's message.content may hold tool_use
    blocks. Read/Edit/Write/NotebookEdit carry input.file_path. We key by basename
    so a memory's `<slug>.md` matches regardless of the absolute path prefix.
    Never raises: a missing or malformed transcript yields empty sets."""
    reads: set[str] = set()
    touched: set[str] = set()
    try:
        text = Path(transcript_path).read_text(encoding="utf-8")
    except OSError:
        return reads, touched
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = rec.get("message") if isinstance(rec, dict) else None
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            fp = (block.get("input") or {}).get("file_path")
            if not fp or name not in _TOUCH_TOOLS:
                continue
            base = os.path.basename(str(fp))
            touched.add(base)
            if name in _READ_TOOLS:
                reads.add(base)
    return reads, touched


def _classify(source_file: str | None, reads: set[str], touched: set[str]) -> str | None:
    """The deterministic proxy. read -> useful; never touched -> dead_end;
    touched-but-not-read (e.g. edited only) -> None (ambiguous, no signal here)."""
    if not source_file:
        return None
    base = os.path.basename(str(source_file))
    if base in reads:
        return "useful"
    if base not in touched:
        return "dead_end"
    return None


def capture(*, session_id: str, transcript_path: Path,
            recall_path: Path | None = None, log_path: Path | None = None,
            date: str | None = None) -> int:
    """Emit useful/dead_end for this session's surfaced memories. Returns the count
    of outcomes actually written (new, non-duplicate). Silent-safe and idempotent."""
    # Bail BEFORE consuming recall if we cannot read the transcript at all: with no
    # transcript we cannot tell useful from dead_end, and defaulting everything to
    # dead_end would wrongly DEMOTE memories (dead_end carries real weight). Not
    # clearing recall here also lets a retry succeed (Codex adversarial finding-1/4).
    if not Path(transcript_path).is_file():
        return 0
    reads, touched = _touched_basenames(transcript_path)
    surfaced = sr.read_and_clear(session_id, path=recall_path)
    if not surfaced:
        return 0
    day = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    written = 0
    for entry in surfaced:
        memory_id = entry.get("memory_id")
        outcome = _classify(entry.get("source_file"), reads, touched)
        if not memory_id or outcome is None:
            continue
        # Session-stable, content-hash event_id keyed on session_id, NOT the day:
        # a session replayed across UTC midnight still dedups to one event, while a
        # DISTINCT session is a distinct corroborating event (amend: date-free key,
        # matching correction_outcome.py after the sibling adversarial finding-2).
        event_id = mo._auto_event_id(memory_id, outcome, session_id, f"autocapture-{outcome}")
        try:
            result = mo.record_outcome(
                memory_id, outcome, event_id=event_id, date=day,
                note=f"auto-capture session={session_id}",
                source_file=entry.get("source_file"), log_path=log_path)
        except ValueError:
            # Out-of-scope memory_id or bad input: skip this one, never abort the
            # batch or the session close.
            continue
        if result is not None:
            written += 1
    return written


def main() -> int:
    """Stop-hook entry. Reads the hook payload (session_id, transcript_path) from
    stdin, gates on the instance allowlist, then captures. ALWAYS exits 0."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not is_enabled():
        return 0
    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")
    if not session_id or not transcript_path:
        return 0
    try:
        capture(session_id=session_id, transcript_path=Path(transcript_path))
    except Exception:  # noqa: BLE001 - a capture bug must never break session close
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
