from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS loops (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        target TEXT NOT NULL,
        target_notion_id TEXT,
        opened TEXT NOT NULL,
        opened_by TEXT NOT NULL DEFAULT 'morning_routine',
        action_card_id TEXT,
        context TEXT,
        channel TEXT,
        touch_count INTEGER DEFAULT 1,
        follow_up_text TEXT,
        escalation_level INTEGER DEFAULT 0,
        last_escalated TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        closed TEXT,
        closed_by TEXT,
        closed_reason TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_loops_status ON loops(status)",
    "CREATE INDEX IF NOT EXISTS idx_loops_target ON loops(target, type, status)",
]


class LoopTracker:
    def __init__(self, db_path: Path, legacy_json_path: Path | None = None):
        self.db_path = db_path
        self._legacy_json_path = legacy_json_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def init_db(self) -> None:
        conn = self._connect()
        try:
            for ddl in _SCHEMA:
                conn.execute(ddl)
            conn.commit()
        finally:
            conn.close()

        if self._legacy_json_path and self._legacy_json_path.exists():
            self._migrate_from_json(self._legacy_json_path)

    def _migrate_from_json(self, json_path: Path) -> None:
        data = json.loads(json_path.read_text())
        conn = self._connect()
        try:
            for lp in data.get("loops", []):
                conn.execute(
                    "INSERT OR IGNORE INTO loops "
                    "(id, type, target, target_notion_id, opened, opened_by, "
                    "action_card_id, context, channel, touch_count, follow_up_text, "
                    "escalation_level, last_escalated, status, closed, closed_by, closed_reason) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        lp["id"], lp["type"], lp["target"],
                        lp.get("target_notion_id"), lp["opened"],
                        lp.get("opened_by", "morning_routine"),
                        lp.get("action_card_id"), lp.get("context"),
                        lp.get("channel"), lp.get("touch_count", 1),
                        lp.get("follow_up_text"), lp.get("escalation_level", 0),
                        lp.get("last_escalated"), lp.get("status", "open"),
                        lp.get("closed"), lp.get("closed_by"),
                        lp.get("closed_reason"),
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        json_path.rename(json_path.with_suffix(".json.bak"))

    def open(
        self,
        loop_type: str,
        target: str,
        context: str,
        notion_id: str = "",
        card_id: str = "",
        follow_up_text: str = "",
    ) -> dict:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id, touch_count FROM loops "
                "WHERE target = ? AND type = ? AND status = 'open'",
                (target, loop_type),
            ).fetchone()

            if row:
                new_count = row["touch_count"] + 1
                if follow_up_text:
                    conn.execute(
                        "UPDATE loops SET touch_count = ?, follow_up_text = ? WHERE id = ?",
                        (new_count, follow_up_text, row["id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE loops SET touch_count = ? WHERE id = ?",
                        (new_count, row["id"]),
                    )
                conn.commit()
                return {"action": "updated", "loop_id": row["id"], "touch_count": new_count}

            today = datetime.now().strftime("%Y-%m-%d")
            cnt = conn.execute(
                "SELECT COUNT(*) as cnt FROM loops WHERE id LIKE ?",
                (f"L-{today}-%",),
            ).fetchone()["cnt"]
            counter = cnt + 1
            channel = loop_type.replace("_sent", "").replace("_posted", "").replace("_created", "").replace("_sourced", "")
            loop_id = f"L-{today}-{counter:03d}"

            conn.execute(
                "INSERT INTO loops "
                "(id, type, target, target_notion_id, opened, opened_by, "
                "action_card_id, context, channel, touch_count, follow_up_text, "
                "escalation_level, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    loop_id, loop_type, target,
                    notion_id or None, today, "morning_routine",
                    card_id or None, context, channel,
                    1, follow_up_text or None, 0, "open",
                ),
            )
            conn.commit()
            return {"action": "opened", "loop_id": loop_id}
        finally:
            conn.close()

    def close(self, loop_id: str, reason: str, closed_by: str) -> dict:
        conn = self._connect()
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            cur = conn.execute(
                "UPDATE loops SET status = 'closed', closed = ?, closed_by = ?, closed_reason = ? "
                "WHERE id = ? AND status = 'open'",
                (today, closed_by, reason, loop_id),
            )
            conn.commit()
            if cur.rowcount > 0:
                return {"closed": True, "loop_id": loop_id}
            return {"closed": False, "error": "not found or already closed"}
        finally:
            conn.close()

    def force_close(self, loop_id: str, action: str) -> dict:
        conn = self._connect()
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            status = f"{action}ed"
            cur = conn.execute(
                "UPDATE loops SET status = ?, closed = ?, closed_by = 'founder', closed_reason = ? "
                "WHERE id = ? AND status = 'open'",
                (status, today, action, loop_id),
            )
            conn.commit()
            if cur.rowcount > 0:
                return {"force_closed": True, "loop_id": loop_id, "action": action}
            return {"force_closed": False, "loop_id": loop_id, "action": action}
        finally:
            conn.close()

    def escalate(self) -> dict:
        conn = self._connect()
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            today_dt = datetime.strptime(today, "%Y-%m-%d")
            rows = conn.execute(
                "SELECT id, opened, escalation_level FROM loops WHERE status = 'open'"
            ).fetchall()

            levels = {"0": 0, "1": 0, "2": 0, "3": 0}
            total_open = len(rows)

            for row in rows:
                opened_dt = datetime.strptime(row["opened"], "%Y-%m-%d")
                age = (today_dt - opened_dt).days
                if age >= 14:
                    new_level = 3
                elif age >= 7:
                    new_level = 2
                elif age >= 3:
                    new_level = 1
                else:
                    new_level = 0

                current_level = row["escalation_level"]
                if new_level > current_level:
                    conn.execute(
                        "UPDATE loops SET escalation_level = ?, last_escalated = ? WHERE id = ?",
                        (new_level, today, row["id"]),
                    )
                    levels[str(new_level)] += 1
                else:
                    levels[str(current_level)] += 1

            conn.commit()
            return {"total_open": total_open, "levels": levels}
        finally:
            conn.close()

    def touch(self, loop_id: str) -> dict:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT touch_count FROM loops WHERE id = ? AND status = 'open'",
                (loop_id,),
            ).fetchone()
            if row:
                new_count = row["touch_count"] + 1
                conn.execute(
                    "UPDATE loops SET touch_count = ? WHERE id = ?",
                    (new_count, loop_id),
                )
                conn.commit()
                return {"loop_id": loop_id, "touch_count": new_count}
            return {"loop_id": loop_id, "error": "not found or not open"}
        finally:
            conn.close()

    def list(self, min_level: int = 0) -> list[dict]:
        conn = self._connect()
        try:
            today_dt = datetime.now()
            rows = conn.execute(
                "SELECT id, type, target, opened, escalation_level, touch_count, context "
                "FROM loops WHERE status = 'open' AND escalation_level >= ? "
                "ORDER BY escalation_level DESC",
                (min_level,),
            ).fetchall()

            result = []
            for row in rows:
                opened_dt = datetime.strptime(row["opened"], "%Y-%m-%d")
                age = (today_dt - opened_dt).days
                result.append({
                    "id": row["id"],
                    "type": row["type"],
                    "target": row["target"],
                    "age_days": age,
                    "escalation_level": row["escalation_level"],
                    "touch_count": row["touch_count"],
                    "context": row["context"],
                })
            return result
        finally:
            conn.close()

    def recently_closed(self, days: int = 2) -> list[dict]:
        """Get loops closed in the last N days (for transparency display)."""
        conn = self._connect()
        try:
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            rows = conn.execute(
                "SELECT id, type, target, closed, closed_by, closed_reason "
                "FROM loops WHERE status != 'open' AND closed >= ? "
                "ORDER BY closed DESC",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def stats(self) -> dict:
        conn = self._connect()
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            today_dt = datetime.now()

            rows = conn.execute("SELECT * FROM loops").fetchall()
            open_count = 0
            closed_today = 0
            levels = {"0": 0, "1": 0, "2": 0, "3": 0}
            oldest_days = 0

            for row in rows:
                if row["status"] == "open":
                    open_count += 1
                    levels[str(row["escalation_level"])] += 1
                    opened_dt = datetime.strptime(row["opened"], "%Y-%m-%d")
                    age = (today_dt - opened_dt).days
                    if age > oldest_days:
                        oldest_days = age
                elif row["closed"] == today:
                    closed_today += 1

            recently_closed = len(self.recently_closed(days=2))
            return {
                "open": open_count,
                "closed_today": closed_today,
                "levels": levels,
                "oldest_days": oldest_days,
                "recently_closed": recently_closed,
            }
        finally:
            conn.close()

    def prune(self, days: int = 30) -> dict:
        conn = self._connect()
        try:
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            # Delete non-open loops closed before the cutoff
            cur = conn.execute(
                "DELETE FROM loops WHERE status != 'open' AND closed IS NOT NULL AND closed < ?",
                (cutoff,),
            )
            pruned = cur.rowcount
            remaining = conn.execute("SELECT COUNT(*) as cnt FROM loops").fetchone()["cnt"]
            conn.commit()
            return {"pruned": pruned, "remaining": remaining}
        finally:
            conn.close()
