#!/usr/bin/env python3
"""Session-scoped recall record for kipi memory auto-capture (issue
autocapture-recall-artifact, PRD prd-memory-autocapture-2026-07-04, finding-5).

The MISSING ARTIFACT the referee needs: which memories were actually surfaced
(recalled) this session. Capture can only score a memory that was recalled, and
nothing recorded that until now.

- Producer: the SessionStart surface scripts (memory-scores-surface.py,
  memory-confidence-surface.py) call `record_surfaced` with the ids they printed.
- Consumer: the Stop-hook capture (memory_autocapture.py) calls `read_recall` for
  the candidate set, then `clear_session` to rotate.

Why a session-keyed MAP and not a flat single-session file (Codex finding-5):
overlapping Claude sessions share this one path. A flat `{session_id, surfaced}`
file would let one session truncate another's recall on write. So the on-disk
shape is `{ "<session_id>": {session_id, surfaced:[...]}, ... }` and every write
is a read-merge-write held under one advisory lock (mirrors the single-writer
chokepoint in memory_outcomes.py), then swapped in atomically with os.replace so
a crash mid-write never leaves a half-file. This is the single writer for the
artifact: dedup and merge live in exactly one place.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl  # POSIX advisory locking (macOS/Linux — kipi's platforms)
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

# QROOT = the directory holding memory/ (this script lives at
# q-system/.q-system/scripts/, so ../.. == q-system/). Matches folder-structure.md.
QROOT = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")).resolve()
DEFAULT_PATH = QROOT / "memory" / ".session-recall.json"


def resolve_session_id() -> str:
    """The current session's id, from the env Claude Code sets for hooks. MUST
    match the `session_id` the Stop-hook consumer reads from its stdin payload,
    or the producer keys recall under one id and the consumer reads another and
    captures nothing.

    Claude Code exports the session UUID as `CLAUDE_CODE_SESSION_ID` (verified:
    it equals the Stop payload session_id and the transcript filename). The old
    `CLAUDE_SESSION_ID` name does NOT exist in the hook env, so it is kept only as
    a defensive alias. Falls back to a per-process token so a missing id never
    crashes the producer (that fallback simply never matches a real read)."""
    for var in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID", "KIPI_SESSION_ID"):
        val = os.environ.get(var)
        if val and val.strip():
            return val.strip()
    return f"no-session-{os.getpid()}"


def _normalize_entry(entry: object, surfaced_at: str) -> dict | None:
    """Coerce a producer-supplied entry into the stored record shape, or None if
    it has no usable memory_id. Accepts (memory_id, source_file) tuples or dicts."""
    if isinstance(entry, (tuple, list)) and entry:
        memory_id = entry[0]
        source_file = entry[1] if len(entry) > 1 else None
    elif isinstance(entry, dict):
        memory_id = entry.get("memory_id")
        source_file = entry.get("source_file")
    else:
        return None
    if not memory_id or not str(memory_id).strip():
        return None
    record = {"memory_id": str(memory_id).strip(), "surfaced_at": surfaced_at}
    if source_file:
        record["source_file"] = str(source_file)
    return record


def _merge_session(bucket: dict, session_id: str, records: list[dict]) -> dict:
    """Return the bucket with `records` merged into `session_id`, de-duplicated by
    memory_id (first surfaced_at wins). Pure — no I/O — so it is unit-obvious."""
    existing = bucket.get(session_id, {}).get("surfaced", [])
    by_id: dict[str, dict] = {r["memory_id"]: r for r in existing}
    for record in records:
        by_id.setdefault(record["memory_id"], record)
    bucket[session_id] = {"session_id": session_id, "surfaced": list(by_id.values())}
    return bucket


def _load_bucket(path: Path) -> dict:
    """Load the whole session-keyed map, or {} if absent/malformed. Never raises —
    a corrupt sidecar must not break SessionStart."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _atomic_write(path: Path, bucket: dict) -> None:
    """Write the map, temp+rename so readers never see a half-file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(bucket, ensure_ascii=False, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)  # atomic on POSIX


def record_surfaced(entries: list, *, session_id: str, path: Path | None = None,
                    surfaced_at: str | None = None) -> int:
    """Append the surfaced entries to `session_id`'s bucket. THE single writer for
    the recall artifact. Returns the count of ids now recorded for the session.

    read-merge-write runs under one exclusive lock so two surface scripts writing
    the same session cannot lose each other's ids (finding-5)."""
    path = Path(path) if path is not None else DEFAULT_PATH
    stamp = surfaced_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records = [r for r in (_normalize_entry(e, stamp) for e in entries) if r]
    if not records:
        return len(read_recall(session_id, path=path))

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("w") as lock_fh:
        if fcntl is not None:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            bucket = _load_bucket(path)
            bucket = _merge_session(bucket, session_id, records)
            _atomic_write(path, bucket)
            return len(bucket[session_id]["surfaced"])
        finally:
            if fcntl is not None:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def read_recall(session_id: str, *, path: Path | None = None) -> list[dict]:
    """The surfaced records for `session_id` (the Stop-hook candidate set), or []."""
    path = Path(path) if path is not None else DEFAULT_PATH
    bucket = _load_bucket(path)
    entry = bucket.get(session_id) or {}
    surfaced = entry.get("surfaced")
    return list(surfaced) if isinstance(surfaced, list) else []


def read_and_clear(session_id: str, *, path: Path | None = None) -> list[dict]:
    """Return `session_id`'s surfaced records AND drop the bucket, both under one
    lock. The Stop-hook consumer uses this instead of read_recall + clear_session:
    a producer append that lands between a separate read and clear would otherwise
    be deleted unconsumed (Codex adversarial finding-1). This snapshot-then-delete
    is atomic, so whatever is returned is exactly what is removed."""
    path = Path(path) if path is not None else DEFAULT_PATH
    if not path.exists():
        return []
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("w") as lock_fh:
        if fcntl is not None:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            bucket = _load_bucket(path)
            entry = bucket.pop(session_id, None) or {}
            if entry:
                _atomic_write(path, bucket)
            surfaced = entry.get("surfaced")
            return list(surfaced) if isinstance(surfaced, list) else []
        finally:
            if fcntl is not None:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def clear_session(session_id: str, *, path: Path | None = None) -> None:
    """Drop `session_id`'s bucket after the consumer has read it (rotate). Held
    under the same lock so it never races a producer append."""
    path = Path(path) if path is not None else DEFAULT_PATH
    if not path.exists():
        return
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("w") as lock_fh:
        if fcntl is not None:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            bucket = _load_bucket(path)
            if session_id in bucket:
                del bucket[session_id]
                _atomic_write(path, bucket)
        finally:
            if fcntl is not None:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    # Tiny CLI for manual inspection: `session_recall.py read <session_id>`.
    if len(sys.argv) >= 3 and sys.argv[1] == "read":
        print(json.dumps(read_recall(sys.argv[2]), indent=2))
    else:
        print("usage: session_recall.py read <session_id>", file=sys.stderr)
        raise SystemExit(2)
