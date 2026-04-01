from __future__ import annotations

import sqlite3
import zlib
from datetime import datetime, timedelta
from pathlib import Path

MAX_BODY_SIZE = 1_048_576  # 1MB
MAX_BODY_TRUNCATE = 250_000  # ~250K chars when over limit
MAX_SUMMARY_SIZE = 4_096
MAX_RECORDS_PER_SOURCE = 500

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS harvest_runs (
        run_id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        mode TEXT NOT NULL,
        parent_run_id TEXT,
        status TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS source_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL REFERENCES harvest_runs(run_id) ON DELETE CASCADE,
        source_name TEXT NOT NULL,
        method TEXT NOT NULL,
        status TEXT NOT NULL,
        records INTEGER DEFAULT 0,
        cursor_before TEXT,
        cursor_after TEXT,
        bus_file TEXT,
        error TEXT,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        apify_cost REAL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS harvest_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL REFERENCES harvest_runs(run_id) ON DELETE CASCADE,
        source_name TEXT NOT NULL,
        record_key TEXT,
        summary_json TEXT NOT NULL,
        cursor_value TEXT,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_hr_source_created ON harvest_records (source_name, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_hr_source_key ON harvest_records (source_name, record_key)",
    """CREATE TABLE IF NOT EXISTS harvest_bodies (
        record_id INTEGER PRIMARY KEY REFERENCES harvest_records(id) ON DELETE CASCADE,
        body BLOB NOT NULL,
        original_size INTEGER NOT NULL,
        CHECK (original_size <= 1048576)
    )""",
    """CREATE TABLE IF NOT EXISTS source_cursors (
        source_name TEXT PRIMARY KEY,
        cursor_value TEXT NOT NULL,
        cursor_field TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS apify_budget (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month TEXT NOT NULL UNIQUE,
        spent REAL NOT NULL DEFAULT 0,
        budget_limit REAL NOT NULL DEFAULT 5.0,
        approved_extra REAL NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS notion_write_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_json TEXT NOT NULL,
        source_agent TEXT NOT NULL,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER DEFAULT 0,
        last_error TEXT,
        completed_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS agent_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        run_id TEXT,
        agent_name TEXT NOT NULL,
        phase TEXT NOT NULL,
        model TEXT,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        duration_seconds REAL,
        records_read INTEGER DEFAULT 0,
        records_written INTEGER DEFAULT 0,
        status TEXT DEFAULT 'running'
    )""",
    """CREATE TABLE IF NOT EXISTS session_handoffs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        run_id TEXT NOT NULL,
        phases_completed TEXT NOT NULL,
        notes TEXT,
        created_at TEXT NOT NULL
    )""",
]

_TABLE_NAMES = [
    "harvest_runs", "source_runs", "harvest_records",
    "harvest_bodies", "source_cursors", "apify_budget",
    "notion_write_queue", "agent_metrics", "session_handoffs",
]


class HarvestStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def init_db(self) -> list[str]:
        conn = self._connect()
        try:
            for ddl in _SCHEMA:
                conn.execute(ddl)
            conn.commit()
        finally:
            conn.close()
        return list(_TABLE_NAMES)

    def create_run(self, mode: str, parent_run_id: str | None = None) -> dict:
        conn = self._connect()
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM harvest_runs WHERE run_id LIKE ?",
                (f"{today}-%",),
            ).fetchone()
            seq = (row["cnt"] or 0) + 1
            run_id = f"{today}-{seq:03d}"
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO harvest_runs (run_id, started_at, mode, parent_run_id, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_id, now, mode, parent_run_id, "running"),
            )
            conn.commit()
            return {"run_id": run_id, "started_at": now, "mode": mode, "status": "running"}
        finally:
            conn.close()

    def update_run(self, run_id: str, status: str, completed_at: str | None = None) -> dict:
        conn = self._connect()
        try:
            if completed_at is None:
                completed_at = datetime.now().isoformat()
            conn.execute(
                "UPDATE harvest_runs SET status = ?, completed_at = ? WHERE run_id = ?",
                (status, completed_at, run_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM harvest_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return dict(row)
        finally:
            conn.close()

    def get_run(self, run_id: str) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM harvest_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_latest_run(self) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM harvest_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def create_source_run(self, run_id: str, source_name: str, method: str) -> dict:
        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            cur = conn.execute(
                "INSERT INTO source_runs (run_id, source_name, method, status, started_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_id, source_name, method, "running", now),
            )
            conn.commit()
            return {
                "id": cur.lastrowid,
                "run_id": run_id,
                "source_name": source_name,
                "method": method,
                "status": "running",
                "started_at": now,
            }
        finally:
            conn.close()

    _ALLOWED_SOURCE_RUN_COLS = frozenset({
        "status", "records", "cursor_before", "cursor_after",
        "bus_file", "error", "completed_at", "apify_cost",
    })

    def update_source_run(self, id: int, **kwargs) -> dict:
        conn = self._connect()
        try:
            sets = []
            vals = []
            for k, v in kwargs.items():
                if k not in self._ALLOWED_SOURCE_RUN_COLS:
                    raise ValueError(f"Invalid column: {k}")
                sets.append(f"{k} = ?")
                vals.append(v)
            vals.append(id)
            conn.execute(
                f"UPDATE source_runs SET {', '.join(sets)} WHERE id = ?", vals
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM source_runs WHERE id = ?", (id,)
            ).fetchone()
            return dict(row)
        finally:
            conn.close()

    def store_record(
        self,
        run_id: str,
        source_name: str,
        record_key: str,
        summary_json: str,
        body_text: str | None = None,
        cursor_value: str | None = None,
    ) -> dict | None:
        if len(summary_json) > MAX_SUMMARY_SIZE:
            raise ValueError(
                f"summary_json exceeds {MAX_SUMMARY_SIZE} bytes "
                f"({len(summary_json)} bytes)"
            )

        conn = self._connect()
        try:
            # dedup check
            if record_key:
                existing = conn.execute(
                    "SELECT id FROM harvest_records WHERE source_name = ? AND record_key = ?",
                    (source_name, record_key),
                ).fetchone()
                if existing:
                    return {"deduped": True, "existing_id": existing["id"]}

            # max records check
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM harvest_records "
                "WHERE run_id = ? AND source_name = ?",
                (run_id, source_name),
            ).fetchone()["cnt"]
            if count >= MAX_RECORDS_PER_SOURCE:
                return None

            now = datetime.now().isoformat()
            cur = conn.execute(
                "INSERT INTO harvest_records "
                "(run_id, source_name, record_key, summary_json, cursor_value, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, source_name, record_key, summary_json, cursor_value, now),
            )
            record_id = cur.lastrowid
            result: dict = {"id": record_id}

            if body_text is not None:
                raw_size = len(body_text.encode("utf-8"))
                if raw_size > MAX_BODY_SIZE:
                    body_text = body_text[:MAX_BODY_TRUNCATE]
                    result["warning"] = f"body truncated from {raw_size} to {len(body_text.encode('utf-8'))} bytes"
                original_size = len(body_text.encode("utf-8"))
                compressed = zlib.compress(body_text.encode("utf-8"), 6)
                conn.execute(
                    "INSERT INTO harvest_bodies (record_id, body, original_size) "
                    "VALUES (?, ?, ?)",
                    (record_id, compressed, original_size),
                )
                result["compressed_size"] = len(compressed)
                result["original_size"] = original_size

            conn.commit()
            return result
        finally:
            conn.close()

    def get_records(
        self,
        source_name: str,
        days: int = 1,
        include_body: bool = False,
        limit: int = 50,
        after_id: int = 0,
    ) -> list[dict]:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        conn = self._connect()
        try:
            if include_body:
                sql = (
                    "SELECT r.*, b.body, b.original_size "
                    "FROM harvest_records r "
                    "LEFT JOIN harvest_bodies b ON b.record_id = r.id "
                    "WHERE r.source_name = ? AND r.id > ? AND r.created_at >= ? "
                    "ORDER BY r.id ASC LIMIT ?"
                )
            else:
                sql = (
                    "SELECT * FROM harvest_records "
                    "WHERE source_name = ? AND id > ? AND created_at >= ? "
                    "ORDER BY id ASC LIMIT ?"
                )
            rows = conn.execute(sql, (source_name, after_id, cutoff, limit)).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                if include_body:
                    blob = d.pop("body", None)
                    d.pop("original_size", None)
                    if blob:
                        d["body_text"] = zlib.decompress(blob).decode("utf-8")
                    else:
                        d["body_text"] = None
                results.append(d)
            return results
        finally:
            conn.close()

    def complete_source_run(self, run_id: str, source_name: str, records: int) -> dict:
        """Mark a source_run as complete. If all sources done, mark run complete."""
        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE source_runs SET status='complete', records=?, completed_at=? "
                "WHERE run_id=? AND source_name=? AND status IN ('pending', 'running')",
                (records, now, run_id, source_name),
            )
            conn.commit()

            if self.check_run_complete(run_id):
                self.update_run(run_id, "complete", completed_at=now)

            return {"source": source_name, "status": "complete", "records": records}
        finally:
            conn.close()

    def check_run_complete(self, run_id: str) -> bool:
        """Check if all source_runs for a run are complete."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN status='complete' THEN 1 ELSE 0 END) as done "
                "FROM source_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            return row["total"] > 0 and row["total"] == row["done"]
        finally:
            conn.close()

    def cleanup(self, days: int = 7) -> dict:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM harvest_runs WHERE started_at < ?", (cutoff,)
            )
            deleted = cur.rowcount
            conn.commit()
            return {"deleted_runs": deleted}
        finally:
            conn.close()

    def get_cursor(self, source_name: str) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM source_cursors WHERE source_name = ?",
                (source_name,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def set_cursor(self, source_name: str, cursor_value: str, cursor_field: str) -> dict:
        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO source_cursors "
                "(source_name, cursor_value, cursor_field, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (source_name, cursor_value, cursor_field, now),
            )
            conn.commit()
            return {
                "source_name": source_name,
                "cursor_value": cursor_value,
                "cursor_field": cursor_field,
            }
        finally:
            conn.close()

    def check_budget(self, month: str) -> dict:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM apify_budget WHERE month = ?", (month,)
            ).fetchone()
            if row is None:
                return {
                    "ok": True,
                    "spent": 0.0,
                    "limit": 5.0,
                    "approved_extra": 0.0,
                    "remaining": 5.0,
                }
            d = dict(row)
            total_allowed = d["budget_limit"] + d["approved_extra"]
            remaining = total_allowed - d["spent"]
            return {
                "ok": remaining > 0,
                "spent": d["spent"],
                "limit": d["budget_limit"],
                "approved_extra": d["approved_extra"],
                "remaining": remaining,
            }
        finally:
            conn.close()

    def record_spend(self, month: str, amount: float) -> dict:
        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            row = conn.execute(
                "SELECT * FROM apify_budget WHERE month = ?", (month,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO apify_budget (month, spent, updated_at) VALUES (?, ?, ?)",
                    (month, amount, now),
                )
            else:
                conn.execute(
                    "UPDATE apify_budget SET spent = spent + ?, updated_at = ? WHERE month = ?",
                    (amount, now, month),
                )
            conn.commit()
            return {"month": month, "amount": amount}
        finally:
            conn.close()

    def approve_extra(self, month: str, amount: float) -> dict:
        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            row = conn.execute(
                "SELECT * FROM apify_budget WHERE month = ?", (month,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO apify_budget (month, approved_extra, updated_at) VALUES (?, ?, ?)",
                    (month, amount, now),
                )
            else:
                conn.execute(
                    "UPDATE apify_budget SET approved_extra = approved_extra + ?, updated_at = ? "
                    "WHERE month = ?",
                    (amount, now, month),
                )
            conn.commit()
            return {"month": month, "approved_extra": amount}
        finally:
            conn.close()

    def harvest_summary(self, run_id: str) -> dict:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT source_name, COUNT(*) as cnt FROM harvest_records "
                "WHERE run_id = ? GROUP BY source_name",
                (run_id,),
            ).fetchall()
            return {row["source_name"]: row["cnt"] for row in rows}
        finally:
            conn.close()

    def harvest_health(self, run_id: str) -> dict:
        """Check harvest completeness for a run."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT source_name, method, status, records, error "
                "FROM source_runs WHERE run_id=?",
                (run_id,),
            ).fetchall()

            total_records = sum(r["records"] or 0 for r in rows)
            sources_complete = [r["source_name"] for r in rows if r["status"] == "complete"]
            sources_failed = [
                {"source": r["source_name"], "error": r["error"]}
                for r in rows if r["status"] in ("error", "failed")
            ]
            sources_pending = [r["source_name"] for r in rows if r["status"] == "pending"]
            sources_skipped = [r["source_name"] for r in rows if r["status"] == "skipped"]

            warnings = []
            if total_records < 10:
                warnings.append(f"Very few records harvested ({total_records}). Data may be incomplete.")
            if len(sources_failed) > 3:
                warnings.append(f"{len(sources_failed)} sources failed. Schedule will be incomplete.")

            return {
                "run_id": run_id,
                "total_records": total_records,
                "sources_complete": sources_complete,
                "sources_failed": sources_failed,
                "sources_pending": sources_pending,
                "sources_skipped": sources_skipped,
                "warnings": warnings,
                "healthy": len(warnings) == 0,
            }
        finally:
            conn.close()

    def queue_notion_write(self, action_json: str, source_agent: str) -> dict:
        """Queue a failed Notion write for retry."""
        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            cur = conn.execute(
                "INSERT INTO notion_write_queue (action_json, source_agent, created_at, status) "
                "VALUES (?, ?, ?, 'pending')",
                (action_json, source_agent, now),
            )
            conn.commit()
            return {"id": cur.lastrowid, "status": "pending", "created_at": now}
        finally:
            conn.close()

    def get_pending_notion_writes(self) -> list[dict]:
        """Get all pending Notion writes."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM notion_write_queue WHERE status='pending' ORDER BY created_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def update_notion_write(self, id: int, status: str, error: str = "") -> dict:
        """Update a queued write status (complete/failed)."""
        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            if status == "failed":
                conn.execute(
                    "UPDATE notion_write_queue SET status=?, last_error=?, attempts=attempts+1 "
                    "WHERE id=?",
                    (status, error, id),
                )
            else:
                conn.execute(
                    "UPDATE notion_write_queue SET status=?, completed_at=? WHERE id=?",
                    (status, now, id),
                )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM notion_write_queue WHERE id=?", (id,)
            ).fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

    def fail_stale_notion_writes(self, max_attempts: int = 3) -> dict:
        """Mark writes with 3+ failed attempts as permanently failed."""
        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            cur = conn.execute(
                "UPDATE notion_write_queue SET status='permanently_failed', completed_at=? "
                "WHERE status IN ('pending', 'failed') AND attempts >= ?",
                (now, max_attempts),
            )
            conn.commit()
            return {"marked_failed": cur.rowcount}
        finally:
            conn.close()

    # ── Agent Metrics ──

    def log_agent_metric(
        self, date: str, agent_name: str, phase: str, model: str = "",
        started_at: str = "", completed_at: str = "", duration_seconds: float = 0,
        records_read: int = 0, records_written: int = 0, status: str = "done",
        run_id: str = "",
    ) -> dict:
        """Log a single agent execution metric."""
        conn = self._connect()
        try:
            if not started_at:
                started_at = datetime.now().isoformat()
            cur = conn.execute(
                "INSERT INTO agent_metrics "
                "(date, run_id, agent_name, phase, model, started_at, completed_at, "
                "duration_seconds, records_read, records_written, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (date, run_id, agent_name, phase, model, started_at, completed_at,
                 duration_seconds, records_read, records_written, status),
            )
            conn.commit()
            return {
                "id": cur.lastrowid,
                "agent_name": agent_name,
                "phase": phase,
                "status": status,
            }
        finally:
            conn.close()

    def query_agent_metrics(self, days: int = 7) -> dict:
        """Query agent metrics for the last N days.

        Returns per-agent averages: avg_duration, total_runs, model, phase.
        """
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT agent_name, phase, model, "
                "AVG(duration_seconds) as avg_duration, "
                "COUNT(*) as total_runs, "
                "SUM(records_read) as total_read, "
                "SUM(records_written) as total_written "
                "FROM agent_metrics WHERE date >= ? "
                "GROUP BY agent_name",
                (cutoff,),
            ).fetchall()
            return {
                "days": days,
                "agents": [
                    {
                        "agent_name": r["agent_name"],
                        "phase": r["phase"],
                        "model": r["model"],
                        "avg_duration": round(r["avg_duration"] or 0, 2),
                        "total_runs": r["total_runs"],
                        "total_read": r["total_read"] or 0,
                        "total_written": r["total_written"] or 0,
                    }
                    for r in rows
                ],
            }
        finally:
            conn.close()

    # ── Session Handoffs ──

    def save_handoff(self, date: str, run_id: str, phases_completed: str, notes: str = "") -> dict:
        """Save a session handoff for resume."""
        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            cur = conn.execute(
                "INSERT INTO session_handoffs (date, run_id, phases_completed, notes, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (date, run_id, phases_completed, notes, now),
            )
            conn.commit()
            return {
                "id": cur.lastrowid,
                "date": date,
                "run_id": run_id,
                "phases_completed": phases_completed,
                "created_at": now,
            }
        finally:
            conn.close()

    def get_handoff(self, date: str) -> dict | None:
        """Get today's handoff if exists."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM session_handoffs WHERE date = ? ORDER BY created_at DESC LIMIT 1",
                (date,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
