import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from kipi_mcp.loop_tracker import LoopTracker


@pytest.fixture
def tracker(tmp_path):
    db = tmp_path / "test.db"
    t = LoopTracker(db)
    t.init_db()
    return t


def test_init_db_creates_table(tracker):
    conn = sqlite3.connect(str(tracker.db_path))
    conn.row_factory = sqlite3.Row
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='loops'"
    ).fetchall()
    conn.close()
    assert len(tables) == 1


def test_init_db_idempotent(tmp_path):
    db = tmp_path / "test.db"
    t = LoopTracker(db)
    t.init_db()
    t.init_db()  # should not raise
    conn = sqlite3.connect(str(db))
    tables = conn.execute(
        "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='loops'"
    ).fetchone()
    conn.close()
    assert tables[0] == 1


def test_open_new_loop(tracker):
    result = tracker.open("email_sent", "Bob", "outreach")
    assert result["action"] == "opened"
    assert result["loop_id"].startswith("L-")


def test_open_duplicate_updates(tracker):
    tracker.open("email_sent", "Carol", "first touch")
    result = tracker.open("email_sent", "Carol", "second touch", follow_up_text="ping again")
    assert result["action"] == "updated"
    assert result["touch_count"] == 2
    conn = sqlite3.connect(str(tracker.db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT follow_up_text FROM loops WHERE target='Carol'").fetchone()
    conn.close()
    assert row["follow_up_text"] == "ping again"


def test_close_loop(tracker):
    opened = tracker.open("email_sent", "Dan", "intro")
    result = tracker.close(opened["loop_id"], "replied", "system")
    assert result["closed"] is True
    assert result["loop_id"] == opened["loop_id"]
    conn = sqlite3.connect(str(tracker.db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT status FROM loops WHERE id=?", (opened["loop_id"],)).fetchone()
    conn.close()
    assert row["status"] == "closed"


def test_close_nonexistent(tracker):
    result = tracker.close("L-9999-999", "no reason", "system")
    assert result["closed"] is False
    assert "error" in result


def test_force_close_park(tracker):
    opened = tracker.open("linkedin_sent", "Eve", "dm")
    result = tracker.force_close(opened["loop_id"], "park")
    assert result["force_closed"] is True
    conn = sqlite3.connect(str(tracker.db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT status FROM loops WHERE id=?", (opened["loop_id"],)).fetchone()
    conn.close()
    assert row["status"] == "parked"


def test_force_close_kill(tracker):
    opened = tracker.open("linkedin_sent", "Frank", "dm")
    result = tracker.force_close(opened["loop_id"], "kill")
    assert result["force_closed"] is True
    conn = sqlite3.connect(str(tracker.db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT status FROM loops WHERE id=?", (opened["loop_id"],)).fetchone()
    conn.close()
    assert row["status"] == "killed"


def test_escalate(tracker):
    tracker.open("email_sent", "Grace", "old loop")
    # Backdate Grace to 15 days ago
    conn = sqlite3.connect(str(tracker.db_path))
    old_date = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
    conn.execute("UPDATE loops SET opened=? WHERE target='Grace'", (old_date,))
    conn.commit()
    conn.close()

    tracker.open("email_sent", "Hank", "medium loop")
    conn = sqlite3.connect(str(tracker.db_path))
    mid_date = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d")
    conn.execute("UPDATE loops SET opened=? WHERE target='Hank'", (mid_date,))
    conn.commit()
    conn.close()

    tracker.open("email_sent", "Ivy", "new loop")

    result = tracker.escalate()
    assert result["total_open"] == 3
    assert result["levels"]["3"] == 1  # Grace: 15 days
    assert result["levels"]["2"] == 1  # Hank: 8 days
    assert result["levels"]["0"] == 1  # Ivy: today


def test_touch(tracker):
    opened = tracker.open("email_sent", "Jack", "intro")
    result = tracker.touch(opened["loop_id"])
    assert result["touch_count"] == 2
    result = tracker.touch(opened["loop_id"])
    assert result["touch_count"] == 3


def test_list_filters_by_level(tracker):
    tracker.open("email_sent", "Kate", "loop1")
    tracker.open("email_sent", "Leo", "loop2")

    conn = sqlite3.connect(str(tracker.db_path))
    old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    conn.execute("UPDATE loops SET opened=? WHERE target='Kate'", (old_date,))
    conn.commit()
    conn.close()

    tracker.escalate()

    all_loops = tracker.list(min_level=0)
    assert len(all_loops) == 2

    high_loops = tracker.list(min_level=2)
    assert len(high_loops) == 1
    assert high_loops[0]["target"] == "Kate"


def test_stats(tracker):
    tracker.open("email_sent", "Mike", "intro")
    tracker.open("email_sent", "Nancy", "intro")
    opened = tracker.open("email_sent", "Oscar", "intro")
    tracker.close(opened["loop_id"], "replied", "system")

    result = tracker.stats()
    assert result["open"] == 2
    assert result["closed_today"] == 1
    assert result["levels"]["0"] == 2


def test_prune(tracker):
    tracker.open("email_sent", "Pat", "old closed")
    opened = tracker.open("email_sent", "Quinn", "recent closed")
    tracker.open("email_sent", "Rose", "still open")

    # Close and backdate Pat's loop
    conn = sqlite3.connect(str(tracker.db_path))
    old_date = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
    conn.execute(
        "UPDATE loops SET status='closed', closed=? WHERE target='Pat'",
        (old_date,),
    )
    conn.commit()
    conn.close()

    tracker.close(opened["loop_id"], "done", "system")

    result = tracker.prune(days=30)
    assert result["pruned"] == 1
    assert result["remaining"] == 2


def test_recently_closed_returns_recent(tracker):
    opened = tracker.open("email_sent", "Zara", "intro")
    tracker.close(opened["loop_id"], "replied", "system")
    recent = tracker.recently_closed(days=2)
    assert len(recent) == 1
    assert recent[0]["target"] == "Zara"
    assert recent[0]["closed_reason"] == "replied"


def test_recently_closed_excludes_old(tracker):
    opened = tracker.open("email_sent", "Yuki", "old close")
    tracker.close(opened["loop_id"], "replied", "system")
    # Backdate closed to 10 days ago
    conn = sqlite3.connect(str(tracker.db_path))
    old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    conn.execute("UPDATE loops SET closed=? WHERE target='Yuki'", (old_date,))
    conn.commit()
    conn.close()
    recent = tracker.recently_closed(days=2)
    assert len(recent) == 0


def test_stats_includes_recently_closed(tracker):
    opened = tracker.open("email_sent", "Wes", "intro")
    tracker.close(opened["loop_id"], "done", "system")
    tracker.open("email_sent", "Vera", "still open")
    result = tracker.stats()
    assert "recently_closed" in result
    assert result["recently_closed"] >= 1


def test_migration_from_json(tmp_path):
    json_path = tmp_path / "open-loops.json"
    legacy_data = {
        "schema_version": 1,
        "loops": [
            {
                "id": "L-2025-01-01-001",
                "type": "email_sent",
                "target": "Alice",
                "target_notion_id": None,
                "opened": "2025-01-01",
                "opened_by": "morning_routine",
                "action_card_id": None,
                "context": "intro email",
                "channel": "email",
                "touch_count": 2,
                "follow_up_text": None,
                "escalation_level": 1,
                "last_escalated": "2025-01-04",
                "status": "open",
                "closed": None,
                "closed_by": None,
                "closed_reason": None,
            },
            {
                "id": "L-2025-01-01-002",
                "type": "linkedin_sent",
                "target": "Bob",
                "target_notion_id": "abc123",
                "opened": "2025-01-01",
                "opened_by": "morning_routine",
                "action_card_id": "card-1",
                "context": "linkedin dm",
                "channel": "linkedin",
                "touch_count": 1,
                "follow_up_text": "follow up",
                "escalation_level": 0,
                "last_escalated": None,
                "status": "closed",
                "closed": "2025-01-05",
                "closed_by": "system",
                "closed_reason": "replied",
            },
        ],
    }
    json_path.write_text(json.dumps(legacy_data))

    db = tmp_path / "test.db"
    t = LoopTracker(db, legacy_json_path=json_path)
    t.init_db()

    # JSON should be renamed
    assert not json_path.exists()
    assert (tmp_path / "open-loops.json.bak").exists()

    # Data should be in SQLite
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM loops ORDER BY id").fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[0]["id"] == "L-2025-01-01-001"
    assert rows[0]["target"] == "Alice"
    assert rows[0]["touch_count"] == 2
    assert rows[1]["id"] == "L-2025-01-01-002"
    assert rows[1]["status"] == "closed"
    assert rows[1]["closed_reason"] == "replied"
