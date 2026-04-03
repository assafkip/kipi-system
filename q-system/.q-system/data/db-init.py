#!/usr/bin/env python3
"""Initialize the metrics SQLite database. Idempotent."""

import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "metrics.db")

SCHEMA = """
-- Content performance tracking
CREATE TABLE IF NOT EXISTS content_performance (
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
);

-- Outreach tracking
CREATE TABLE IF NOT EXISTS outreach_log (
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
);

-- Copy edit tracking
CREATE TABLE IF NOT EXISTS copy_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    action_type TEXT,
    original TEXT NOT NULL,
    edited TEXT NOT NULL DEFAULT '',
    edit_summary TEXT,
    outreach_log_id INTEGER REFERENCES outreach_log(id),
    UNIQUE(date, contact_name, action_type)
);

-- Behavioral signals from LinkedIn
CREATE TABLE IF NOT EXISTS behavioral_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_name TEXT NOT NULL,
    contact_notion_id TEXT,
    signal_type TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    source TEXT NOT NULL,
    weight INTEGER NOT NULL,
    processed INTEGER DEFAULT 0
);

-- Daily rollup metrics
CREATE TABLE IF NOT EXISTS daily_metrics (
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
);

-- A/B test definitions
CREATE TABLE IF NOT EXISTS ab_tests (
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
);

-- A/B test assignments
CREATE TABLE IF NOT EXISTS ab_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER REFERENCES ab_tests(id),
    outreach_log_id INTEGER REFERENCES outreach_log(id),
    variant TEXT NOT NULL,
    outcome TEXT
);
"""

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    db.commit()

    # Verify
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [t[0] for t in tables]
    db.close()

    print(f"Database: {DB_PATH}")
    print(f"Tables: {', '.join(table_names)}")
    return table_names

if __name__ == "__main__":
    tables = init_db()
    expected = {"ab_assignments", "ab_tests", "behavioral_signals",
                "content_performance", "copy_edits", "daily_metrics", "outreach_log"}
    missing = expected - set(tables)
    if missing:
        print(f"ERROR: Missing tables: {missing}", file=sys.stderr)
        sys.exit(1)
    print("All tables created.")
