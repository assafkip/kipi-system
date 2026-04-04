#!/usr/bin/env python3
"""CLI query helper for the metrics database."""

import sqlite3
import json
import sys
import os
import hashlib
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "metrics.db")

def get_db():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}. Run db-init.py first.", file=sys.stderr)
        sys.exit(1)
    return sqlite3.connect(DB_PATH)

def content_performance(args):
    """Query content performance. Usage: content-performance [--last N] [--platform X]"""
    days = 30
    platform = None
    i = 0
    while i < len(args):
        if args[i] == "--last" and i + 1 < len(args):
            days = int(args[i + 1]); i += 2
        elif args[i] == "--platform" and i + 1 < len(args):
            platform = args[i + 1]; i += 2
        else:
            i += 1

    db = get_db()
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    query = "SELECT * FROM content_performance WHERE publish_date >= ?"
    params = [since]
    if platform:
        query += " AND platform = ?"
        params.append(platform)
    query += " ORDER BY publish_date DESC"
    rows = db.execute(query, params).fetchall()
    cols = [d[0] for d in db.execute(query, params).description] if rows else []
    db.close()
    print(json.dumps([dict(zip(cols, r)) for r in rows], indent=2))

def insert_content_metrics(args):
    """Insert content metrics from JSON file. Usage: insert-content-metrics <json_file>"""
    if not args:
        print("Usage: insert-content-metrics <json_file>", file=sys.stderr); sys.exit(1)
    with open(args[0]) as f:
        data = json.load(f)
    db = get_db()
    now = datetime.now().isoformat()
    count = 0
    for m in data.get("metrics", []):
        try:
            db.execute(
                "INSERT OR IGNORE INTO content_performance "
                "(post_id, platform, publish_date, post_type, impressions, likes, comments, reposts, engagement_rate, scraped_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (m.get("post_url", ""), "linkedin", m.get("post_date", ""), m.get("post_type", ""),
                 m.get("impressions", 0), m.get("likes", 0), m.get("comments", 0),
                 m.get("reposts", 0), m.get("engagement_rate", 0), now)
            )
            count += 1
        except Exception as e:
            print(f"WARN: Skipped row: {e}", file=sys.stderr)
    db.commit()
    db.close()
    print(f"Inserted {count} content performance records.")

def insert_behavioral_signals(args):
    """Insert behavioral signals from JSON file. Usage: insert-behavioral-signals <json_file>"""
    if not args:
        print("Usage: insert-behavioral-signals <json_file>", file=sys.stderr); sys.exit(1)
    with open(args[0]) as f:
        data = json.load(f)
    db = get_db()
    count = 0
    for s in data.get("signals", []):
        db.execute(
            "INSERT INTO behavioral_signals "
            "(contact_name, signal_type, signal_date, source, weight) "
            "VALUES (?, ?, ?, ?, ?)",
            (s["contact_name"], s["signal_type"], s["signal_date"],
             s.get("source", "chrome_scrape"), s.get("weight", 1))
        )
        count += 1
    db.commit()
    db.close()
    print(f"Inserted {count} behavioral signals.")

def insert_outreach(args):
    """Insert outreach log entry. Usage: insert-outreach <json_file>"""
    if not args:
        print("Usage: insert-outreach <json_file>", file=sys.stderr); sys.exit(1)
    with open(args[0]) as f:
        data = json.load(f)
    db = get_db()
    count = 0
    for item in data.get("actions", data.get("queue", [])):
        copy = item.get("copy", item.get("copy_text", item.get("message", "")))
        copy_hash = hashlib.sha256(copy.encode()).hexdigest()[:16] if copy else None
        db.execute(
            "INSERT INTO outreach_log "
            "(contact_name, channel, action_type, cr_style, copy_hash, copy_text, send_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item.get("contact_name", item.get("name", "")),
             item.get("channel", item.get("platform", "linkedin")),
             item.get("action_type", ""),
             item.get("cr_style"),
             copy_hash, copy, data.get("date", datetime.now().strftime("%Y-%m-%d")))
        )
        count += 1
    db.commit()
    db.close()
    print(f"Inserted {count} outreach log entries.")

def outreach_stats(args):
    """Outreach stats. Usage: outreach-stats [--last N]"""
    days = 7
    if "--last" in args:
        idx = args.index("--last")
        if idx + 1 < len(args): days = int(args[idx + 1])
    db = get_db()
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    stats = {
        "total_sent": db.execute("SELECT COUNT(*) FROM outreach_log WHERE send_date >= ?", (since,)).fetchone()[0],
        "responded": db.execute("SELECT COUNT(*) FROM outreach_log WHERE send_date >= ? AND response_type = 'replied'", (since,)).fetchone()[0],
        "by_channel": {},
        "by_action_type": {},
    }
    for row in db.execute("SELECT channel, COUNT(*) FROM outreach_log WHERE send_date >= ? GROUP BY channel", (since,)):
        stats["by_channel"][row[0]] = row[1]
    for row in db.execute("SELECT action_type, COUNT(*) FROM outreach_log WHERE send_date >= ? GROUP BY action_type", (since,)):
        stats["by_action_type"][row[0]] = row[1]
    db.close()
    print(json.dumps(stats, indent=2))

def top_posts(args):
    """Top performing posts. Usage: top-posts [--limit N]"""
    limit = 5
    if "--limit" in args:
        idx = args.index("--limit")
        if idx + 1 < len(args): limit = int(args[idx + 1])
    db = get_db()
    rows = db.execute(
        "SELECT post_id, platform, publish_date, post_type, impressions, engagement_rate, likes, comments "
        "FROM content_performance ORDER BY engagement_rate DESC LIMIT ?", (limit,)
    ).fetchall()
    cols = ["post_id", "platform", "publish_date", "post_type", "impressions", "engagement_rate", "likes", "comments"]
    db.close()
    print(json.dumps([dict(zip(cols, r)) for r in rows], indent=2))

def ab_test(args):
    """A/B test results. Usage: ab-test --name <test_name>"""
    name = None
    if "--name" in args:
        idx = args.index("--name")
        if idx + 1 < len(args): name = args[idx + 1]
    db = get_db()
    if name:
        test = db.execute("SELECT * FROM ab_tests WHERE name = ?", (name,)).fetchone()
        if not test:
            print(f"No test found: {name}"); db.close(); return
        cols = [d[0] for d in db.execute("SELECT * FROM ab_tests LIMIT 0").description]
        test_dict = dict(zip(cols, test))
        assignments = db.execute(
            "SELECT variant, outcome, COUNT(*) FROM ab_assignments WHERE test_id = ? GROUP BY variant, outcome",
            (test[0],)
        ).fetchall()
        test_dict["results"] = [{"variant": a[0], "outcome": a[1], "count": a[2]} for a in assignments]
        print(json.dumps(test_dict, indent=2))
    else:
        rows = db.execute("SELECT id, name, status, winner FROM ab_tests").fetchall()
        print(json.dumps([{"id": r[0], "name": r[1], "status": r[2], "winner": r[3]} for r in rows], indent=2))
    db.close()

def daily_rollup(args):
    """Insert or update daily metrics. Usage: daily-rollup <date> <json_file>"""
    if len(args) < 2:
        print("Usage: daily-rollup <date> <json_file>", file=sys.stderr); sys.exit(1)
    date, json_file = args[0], args[1]
    with open(json_file) as f:
        data = json.load(f)
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO daily_metrics "
        "(date, posts_published, outreach_sent, responses_received, meetings_booked, "
        "energy_level, routine_completion_pct) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (date, data.get("posts_published", 0), data.get("outreach_sent", 0),
         data.get("responses_received", 0), data.get("meetings_booked", 0),
         data.get("energy_level"), data.get("routine_completion_pct"))
    )
    db.commit()
    db.close()
    print(f"Daily metrics saved for {date}.")

COMMANDS = {
    "content-performance": content_performance,
    "insert-content-metrics": insert_content_metrics,
    "insert-behavioral-signals": insert_behavioral_signals,
    "insert-outreach": insert_outreach,
    "outreach-stats": outreach_stats,
    "top-posts": top_posts,
    "ab-test": ab_test,
    "daily-rollup": daily_rollup,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: {sys.argv[0]} <command> [args]")
        print(f"Commands: {', '.join(COMMANDS.keys())}")
        sys.exit(1)
    COMMANDS[sys.argv[1]](sys.argv[2:])
