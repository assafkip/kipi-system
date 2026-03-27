from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS content_performance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id TEXT,
        platform TEXT NOT NULL,
        publish_date TEXT NOT NULL,
        post_type TEXT,
        impressions INTEGER DEFAULT 0,
        engagement_rate REAL DEFAULT 0,
        clicks INTEGER DEFAULT 0,
        likes INTEGER DEFAULT 0,
        comments INTEGER DEFAULT 0,
        reposts INTEGER DEFAULT 0,
        reach INTEGER DEFAULT 0,
        scraped_at TEXT NOT NULL,
        UNIQUE(post_id, scraped_at)
    )""",
    """CREATE TABLE IF NOT EXISTS outreach_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contact_name TEXT NOT NULL,
        contact_notion_id TEXT,
        channel TEXT NOT NULL,
        action_type TEXT NOT NULL,
        cr_style TEXT,
        copy_hash TEXT,
        copy_text TEXT,
        send_date TEXT NOT NULL,
        response_date TEXT,
        response_type TEXT,
        stage_before TEXT,
        stage_after TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS copy_edits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        outreach_log_id INTEGER REFERENCES outreach_log(id),
        original_text TEXT NOT NULL,
        edited_text TEXT NOT NULL,
        edit_date TEXT NOT NULL,
        diff_summary TEXT,
        context TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS behavioral_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contact_name TEXT NOT NULL,
        contact_notion_id TEXT,
        signal_type TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        source TEXT NOT NULL,
        weight INTEGER NOT NULL,
        processed INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS daily_metrics (
        date TEXT PRIMARY KEY,
        followers_linkedin INTEGER,
        followers_x INTEGER,
        posts_published INTEGER DEFAULT 0,
        outreach_sent INTEGER DEFAULT 0,
        responses_received INTEGER DEFAULT 0,
        meetings_booked INTEGER DEFAULT 0,
        avg_engagement_rate REAL,
        top_performing_post_id TEXT,
        energy_level INTEGER,
        routine_completion_pct REAL
    )""",
    """CREATE TABLE IF NOT EXISTS ab_tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        variable TEXT NOT NULL,
        variant_a TEXT NOT NULL,
        variant_b TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT,
        status TEXT DEFAULT 'active',
        winner TEXT,
        sample_size_target INTEGER DEFAULT 20
    )""",
    """CREATE TABLE IF NOT EXISTS ab_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        test_id INTEGER REFERENCES ab_tests(id),
        outreach_log_id INTEGER REFERENCES outreach_log(id),
        variant TEXT NOT NULL,
        outcome TEXT
    )""",
]

_TABLE_NAMES = [
    "content_performance", "outreach_log", "copy_edits",
    "behavioral_signals", "daily_metrics", "ab_tests", "ab_assignments",
]


class MetricsStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
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

    def insert_content_metrics(self, records: list[dict]) -> dict:
        conn = self._connect()
        inserted = 0
        try:
            for r in records:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO content_performance
                    (post_id, platform, publish_date, post_type, impressions,
                     engagement_rate, clicks, likes, comments, reposts, reach, scraped_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        r.get("post_id"), r["platform"], r["publish_date"],
                        r.get("post_type"), r.get("impressions", 0),
                        r.get("engagement_rate", 0), r.get("clicks", 0),
                        r.get("likes", 0), r.get("comments", 0),
                        r.get("reposts", 0), r.get("reach", 0),
                        r["scraped_at"],
                    ),
                )
                inserted += cur.rowcount
            conn.commit()
        finally:
            conn.close()
        return {"inserted": inserted}

    def insert_behavioral_signals(self, signals: list[dict]) -> dict:
        conn = self._connect()
        inserted = 0
        try:
            for s in signals:
                conn.execute(
                    """INSERT INTO behavioral_signals
                    (contact_name, contact_notion_id, signal_type, signal_date, source, weight)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        s["contact_name"], s.get("contact_notion_id"),
                        s["signal_type"], s["signal_date"],
                        s["source"], s["weight"],
                    ),
                )
                inserted += 1
            conn.commit()
        finally:
            conn.close()
        return {"inserted": inserted}

    def insert_outreach_log(
        self, contact_name: str, channel: str, action_type: str,
        copy_text: str, send_date: str, **kwargs,
    ) -> dict:
        conn = self._connect()
        try:
            cur = conn.execute(
                """INSERT INTO outreach_log
                (contact_name, contact_notion_id, channel, action_type,
                 cr_style, copy_hash, copy_text, send_date,
                 response_date, response_type, stage_before, stage_after)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    contact_name, kwargs.get("contact_notion_id"),
                    channel, action_type,
                    kwargs.get("cr_style"), kwargs.get("copy_hash"),
                    copy_text, send_date,
                    kwargs.get("response_date"), kwargs.get("response_type"),
                    kwargs.get("stage_before"), kwargs.get("stage_after"),
                ),
            )
            conn.commit()
            return {"id": cur.lastrowid}
        finally:
            conn.close()

    def insert_copy_edit(
        self, original_text: str, edited_text: str, edit_date: str,
        diff_summary: str = "", context: str = "",
    ) -> dict:
        conn = self._connect()
        try:
            cur = conn.execute(
                """INSERT INTO copy_edits
                (original_text, edited_text, edit_date, diff_summary, context)
                VALUES (?, ?, ?, ?, ?)""",
                (original_text, edited_text, edit_date, diff_summary, context),
            )
            conn.commit()
            return {"id": cur.lastrowid}
        finally:
            conn.close()

    def upsert_daily_metrics(self, date: str, **kwargs) -> dict:
        conn = self._connect()
        try:
            cols = ["date"]
            vals: list = [date]
            for k in (
                "followers_linkedin", "followers_x", "posts_published",
                "outreach_sent", "responses_received", "meetings_booked",
                "avg_engagement_rate", "top_performing_post_id",
                "energy_level", "routine_completion_pct",
            ):
                if k in kwargs:
                    cols.append(k)
                    vals.append(kwargs[k])
            placeholders = ", ".join("?" for _ in cols)
            col_str = ", ".join(cols)
            conn.execute(
                f"INSERT OR REPLACE INTO daily_metrics ({col_str}) VALUES ({placeholders})",
                vals,
            )
            conn.commit()
        finally:
            conn.close()
        return {"date": date}

    def query_content_performance(
        self, days: int = 30, platform: str | None = None,
    ) -> list[dict]:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        conn = self._connect()
        try:
            sql = "SELECT * FROM content_performance WHERE publish_date >= ?"
            params: list = [cutoff]
            if platform:
                sql += " AND platform = ?"
                params.append(platform)
            sql += " ORDER BY publish_date DESC"
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def query_outreach_stats(self, days: int = 7) -> dict:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM outreach_log WHERE send_date >= ?", (cutoff,)
            ).fetchall()
            by_channel: dict[str, int] = {}
            by_action: dict[str, int] = {}
            for r in rows:
                ch = r["channel"]
                by_channel[ch] = by_channel.get(ch, 0) + 1
                at = r["action_type"]
                by_action[at] = by_action.get(at, 0) + 1
            return {
                "total": len(rows),
                "by_channel": by_channel,
                "by_action_type": by_action,
            }
        finally:
            conn.close()

    def query_top_posts(self, limit: int = 5) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM content_performance ORDER BY engagement_rate DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def query_behavioral_signals(self, days: int = 7) -> list[dict]:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM behavioral_signals WHERE signal_date >= ? ORDER BY signal_date DESC",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def query_copy_edits(self, days: int = 30) -> list[dict]:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM copy_edits WHERE edit_date >= ? ORDER BY edit_date DESC",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def generate_monthly_learnings(self, days: int = 30) -> dict:
        edits = self.query_copy_edits(days=days)
        if not edits:
            return {
                "edits_analyzed": 0,
                "avg_length_change_pct": 0.0,
                "edit_frequency_by_context": {},
                "common_patterns": [],
                "recommendations": [],
            }

        length_changes: list[float] = []
        context_counter: Counter[str] = Counter()
        diff_counter: Counter[str] = Counter()

        for e in edits:
            orig_len = len(e["original_text"])
            edit_len = len(e["edited_text"])
            if orig_len > 0:
                pct = ((edit_len - orig_len) / orig_len) * 100
                length_changes.append(pct)

            ctx = e.get("context") or "unknown"
            context_counter[ctx] += 1

            ds = e.get("diff_summary") or ""
            if ds:
                diff_counter[ds] += 1

        avg_change = sum(length_changes) / len(length_changes) if length_changes else 0.0
        common = [{"pattern": p, "count": c} for p, c in diff_counter.most_common(10)]

        recommendations: list[str] = []
        if avg_change < -20:
            recommendations.append("Drafts tend to be too long. Consider tighter initial copy.")
        if avg_change > 20:
            recommendations.append("Drafts tend to be too short. Add more substance in first pass.")
        top_ctx = context_counter.most_common(1)
        if top_ctx:
            recommendations.append(
                f"Most edits happen in '{top_ctx[0][0]}' context ({top_ctx[0][1]} edits). Focus voice training there."
            )

        return {
            "edits_analyzed": len(edits),
            "avg_length_change_pct": round(avg_change, 2),
            "edit_frequency_by_context": dict(context_counter),
            "common_patterns": common,
            "recommendations": recommendations,
        }
