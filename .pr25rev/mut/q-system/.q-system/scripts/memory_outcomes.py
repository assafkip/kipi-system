"""Outcome event log for kipi memory earned-trust scoring.

The INPUT side of memory-outcome-scoring (parent PRD
prd-memory-outcome-scoring-2026-07-04). Records how a recalled memory performed
when it was actually used — `useful`, `dead_end`, or `corrected` — as an
append-only JSONL log at `q-system/memory/outcomes.jsonl`. `memory_reflect.py`
reads this log and scores each memory.

`record_outcome` is the SINGLE WRITER (single-writer-chokepoint lesson): the only
thing that appends to the log, so the on-disk shape stays one format and dedup is
enforced in exactly one place.

event_id dedup (finding-3 PRD): the corroboration gate in memory_reflect counts
DISTINCT useful outcomes to promote a memory to "preferred". If a caller replays
or double-writes the same outcome, that must not count twice. Every event carries
a caller-supplied stable `event_id` and a duplicate id is refused at the writer.

Issue-review hardening (Codex, memory-outcome-log):
- Dedup is check-then-append; without a lock two writers could both pass the
  existence check and both append. An flock makes read-check-append atomic so the
  single-writer invariant actually holds (findings 1 + 3-adversarial).
- A prior malformed/truncated line with no trailing newline would otherwise get
  the new JSON concatenated onto it and silently lost. We normalise the trailing
  newline under the same lock before appending (finding 3-adversarial).
- A parseable-but-incomplete line like `{"event_id":"e1"}` must not pollute dedup
  or be returned as an event. A single `_is_valid_event` predicate gates both the
  dedup id-set and read_events, so only fully-formed events count (finding 2).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import fcntl  # POSIX advisory locking (macOS/Linux — kipi's platforms)
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

# QROOT = the directory holding memory/ (this script lives at
# q-system/.q-system/scripts/, so ../.. == q-system/). Matches folder-structure.md.
QROOT = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")).resolve()

# The store this system scores. v1 scores ONLY q-system/memory (finding-1); the
# auto-memory store under ~/.claude/projects/<project>/memory is a named v2.
MEMORY_DIR = QROOT / "memory"
DEFAULT_LOG = MEMORY_DIR / "outcomes.jsonl"

VALID_OUTCOMES = ("useful", "dead_end", "corrected")


# A memory_id is a flat slug like `feedback_rate_floor_250` — the basename kipi
# gives its memory files. ALLOWLIST, not denylist (review finding, issue
# memory-scope-boundary): a denylist of "/" + leading-dot let fullwidth-Unicode
# separators (U+FF0F), NUL/control bytes, and trailing whitespace through, any of
# which could NFKC-normalise into a separator or traversal. Only ASCII
# [A-Za-z0-9_-] with an alphanumeric first char is a valid slug; everything else
# — paths, dotfiles, Unicode lookalikes, whitespace, control chars — fails.
_MEMORY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _is_in_scope_memory_id(memory_id: str) -> bool:
    """True only for a memory_id that names a single memory within the scored
    store (finding-1). v1 scores ONLY q-system/memory.

    Matched against the RAW value (no strip) so trailing/leading whitespace is
    itself a rejection, and the stored id is guaranteed clean.
    """
    return isinstance(memory_id, str) and bool(_MEMORY_ID_RE.match(memory_id))


def _is_valid_event(obj: object) -> bool:
    """True only for a fully-formed event dict.

    Requires a non-empty `event_id`, a non-empty `memory_id`, and an `outcome` in
    the enum. This is the SINGLE definition of "well-formed", shared by read_events
    and the dedup id-set, so a parseable-but-incomplete line can neither be
    returned as an event nor block a later valid event with the same id.
    """
    return (
        isinstance(obj, dict)
        and bool(obj.get("event_id"))
        and bool(obj.get("memory_id"))
        and obj.get("outcome") in VALID_OUTCOMES
    )


def _events_from_text(text: str) -> list[dict]:
    """Parse JSONL text into the list of well-formed events, in file order.

    Malformed or incomplete lines are skipped — a hand-appended or truncated line
    must never break scoring or dedup.
    """
    events: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if _is_valid_event(obj):
            events.append(obj)
    return events


def read_events(log_path: Path | None = None) -> list[dict]:
    """Return every well-formed event in the log, in file order. Missing => []."""
    log_path = Path(log_path) if log_path is not None else DEFAULT_LOG
    if not log_path.exists():
        return []
    return _events_from_text(log_path.read_text(encoding="utf-8"))


def record_outcome(memory_id: str, outcome: str, *, event_id: str,
                   date: str | None = None, note: str = "",
                   source_file: str | None = None,
                   log_path: Path | None = None) -> dict | None:
    """Append one outcome event to the log. The ONLY writer.

    Returns the appended event dict, or None if the `event_id` already exists in
    the log (deduped — idempotent, no second line). Raises ValueError on an
    invalid `outcome`, an empty `event_id`, or a list `source_file`.

    read-check-append runs under an exclusive file lock, so concurrent callers
    cannot both pass the dedup check and double-append.
    """
    if outcome not in VALID_OUTCOMES:
        raise ValueError(
            f"outcome must be one of {VALID_OUTCOMES}, got {outcome!r}")
    if not event_id or not str(event_id).strip():
        raise ValueError("event_id is required and must be non-empty")
    if not _is_in_scope_memory_id(memory_id):
        raise ValueError(
            f"memory_id {memory_id!r} is out of scope: v1 scores only flat "
            f"slugs within q-system/memory (no paths, traversal, or dotfiles)")
    if isinstance(source_file, (list, tuple)):
        # One source per memory in v1 (finding-4); a list is rejected so the
        # fingerprint resolver never has to guess which file to hash.
        raise ValueError("source_file must be a single path string, not a list")

    log_path = Path(log_path) if log_path is not None else DEFAULT_LOG
    event_id = str(event_id).strip()

    event: dict = {"memory_id": str(memory_id), "outcome": outcome,
                   "event_id": event_id}
    if date:
        event["date"] = str(date)
    if note:
        event["note"] = str(note)
    if source_file:
        event["source_file"] = str(source_file)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"

    # a+ opens at end; the lock covers the whole read-check-append so the dedup
    # decision and the write are one atomic step for the single writer.
    with log_path.open("a+", encoding="utf-8") as fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.seek(0)
            existing_text = fh.read()
            existing_ids = {e["event_id"] for e in _events_from_text(existing_text)}
            if event_id in existing_ids:
                return None  # duplicate — do not append
            # Normalise a missing trailing newline so the new JSON lands on its
            # own line instead of being concatenated onto a truncated last line.
            if existing_text and not existing_text.endswith("\n"):
                fh.write("\n")
            fh.write(line)
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return event


def _auto_event_id(memory_id: str, outcome: str, date: str, note: str) -> str:
    """Deterministic event_id from the event content, so re-running the same
    capture dedups instead of double-counting (idempotent CLI). 16 hex chars is
    ample collision resistance for a per-founder local log."""
    raw = f"{memory_id}|{outcome}|{date}|{note}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def main(argv: list[str] | None = None) -> int:
    """CLI capture path: record how a recalled memory performed.

        python3 memory_outcomes.py <memory_id> <useful|dead_end|corrected> \\
            [--note ...] [--date YYYY-MM-DD] [--source-file PATH] [--event-id ID]

    Without --event-id, a content hash of (memory_id, outcome, date, note) is
    used, so the same capture run twice is a no-op (deduped)."""
    ap = argparse.ArgumentParser(description="Record a memory-use outcome.")
    ap.add_argument("memory_id")
    ap.add_argument("outcome", choices=VALID_OUTCOMES)
    ap.add_argument("--note", default="")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--source-file", default=None)
    ap.add_argument("--event-id", default=None)
    args = ap.parse_args(argv)

    date = args.date or datetime.now().strftime("%Y-%m-%d")
    event_id = args.event_id or _auto_event_id(
        args.memory_id, args.outcome, date, args.note)
    try:
        ev = record_outcome(args.memory_id, args.outcome, event_id=event_id,
                            date=date, note=args.note, source_file=args.source_file)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"recorded {args.outcome} for {args.memory_id} (event_id {event_id})"
          if ev is not None else
          f"already recorded (deduped): {args.memory_id} event_id {event_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
