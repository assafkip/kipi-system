from datetime import datetime, timedelta

import pytest

from kipi_mcp.metrics_store import MetricsStore


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "metrics.db"
    s = MetricsStore(db_path=db)
    s.init_db()
    return s


def test_init_db_creates_all_tables(tmp_path):
    db = tmp_path / "metrics.db"
    s = MetricsStore(db_path=db)
    tables = s.init_db()
    assert len(tables) == 7
    expected = {
        "content_performance", "outreach_log", "copy_edits",
        "behavioral_signals", "daily_metrics", "ab_tests", "ab_assignments",
    }
    assert set(tables) == expected


def test_init_db_idempotent(tmp_path):
    db = tmp_path / "metrics.db"
    s = MetricsStore(db_path=db)
    t1 = s.init_db()
    t2 = s.init_db()
    assert t1 == t2


def test_insert_content_metrics_single(store):
    today = datetime.now().strftime("%Y-%m-%d")
    records = [{
        "post_id": "p1", "platform": "linkedin", "publish_date": today,
        "impressions": 100, "engagement_rate": 5.2, "scraped_at": today,
    }]
    result = store.insert_content_metrics(records)
    assert result["inserted"] == 1

    rows = store.query_content_performance(days=1)
    assert len(rows) == 1
    assert rows[0]["post_id"] == "p1"
    assert rows[0]["impressions"] == 100


def test_insert_content_metrics_batch(store):
    today = datetime.now().strftime("%Y-%m-%d")
    records = [
        {"post_id": f"p{i}", "platform": "linkedin", "publish_date": today,
         "scraped_at": today}
        for i in range(3)
    ]
    result = store.insert_content_metrics(records)
    assert result["inserted"] == 3


def test_insert_content_metrics_unique_constraint(store):
    today = datetime.now().strftime("%Y-%m-%d")
    record = {
        "post_id": "dup1", "platform": "linkedin", "publish_date": today,
        "scraped_at": today,
    }
    store.insert_content_metrics([record])
    result = store.insert_content_metrics([record])
    assert result["inserted"] == 0

    rows = store.query_content_performance(days=1)
    post_ids = [r["post_id"] for r in rows]
    assert post_ids.count("dup1") == 1


def test_insert_behavioral_signals(store):
    today = datetime.now().strftime("%Y-%m-%d")
    signals = [{
        "contact_name": "Alice", "signal_type": "profile_view",
        "signal_date": today, "source": "linkedin", "weight": 3,
    }]
    result = store.insert_behavioral_signals(signals)
    assert result["inserted"] == 1

    rows = store.query_behavioral_signals(days=1)
    assert len(rows) == 1
    assert rows[0]["contact_name"] == "Alice"


def test_insert_outreach_log(store):
    today = datetime.now().strftime("%Y-%m-%d")
    result = store.insert_outreach_log(
        contact_name="Bob", channel="email", action_type="cold_email",
        copy_text="Hi Bob", send_date=today,
    )
    assert "id" in result
    assert result["id"] >= 1


def test_insert_copy_edit(store):
    today = datetime.now().strftime("%Y-%m-%d")
    result = store.insert_copy_edit(
        original_text="leverage synergies",
        edited_text="combine strengths",
        edit_date=today,
        diff_summary="removed jargon",
        context="outreach",
    )
    assert "id" in result
    assert result["id"] >= 1


def test_upsert_daily_metrics(store):
    date = "2026-03-27"
    store.upsert_daily_metrics(date, posts_published=2, outreach_sent=5)
    store.upsert_daily_metrics(date, posts_published=3, outreach_sent=5)

    import sqlite3
    conn = sqlite3.connect(str(store.db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM daily_metrics WHERE date = ?", (date,)).fetchone()
    conn.close()
    assert row["posts_published"] == 3


def test_query_content_performance_date_filter(store):
    old_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
    recent_date = datetime.now().strftime("%Y-%m-%d")

    store.insert_content_metrics([
        {"post_id": "old", "platform": "x", "publish_date": old_date, "scraped_at": old_date},
        {"post_id": "new", "platform": "x", "publish_date": recent_date, "scraped_at": recent_date},
    ])
    rows = store.query_content_performance(days=30)
    post_ids = [r["post_id"] for r in rows]
    assert "new" in post_ids
    assert "old" not in post_ids


def test_query_content_performance_platform_filter(store):
    today = datetime.now().strftime("%Y-%m-%d")
    store.insert_content_metrics([
        {"post_id": "li1", "platform": "linkedin", "publish_date": today, "scraped_at": today},
        {"post_id": "x1", "platform": "x", "publish_date": today, "scraped_at": today},
    ])
    rows = store.query_content_performance(days=30, platform="linkedin")
    assert all(r["platform"] == "linkedin" for r in rows)
    assert len(rows) == 1


def test_query_outreach_stats(store):
    today = datetime.now().strftime("%Y-%m-%d")
    store.insert_outreach_log("Alice", "email", "cold_email", "hi", today)
    store.insert_outreach_log("Bob", "linkedin", "dm", "hey", today)
    store.insert_outreach_log("Carol", "email", "follow_up", "bump", today)

    stats = store.query_outreach_stats(days=7)
    assert stats["total"] == 3
    assert stats["by_channel"]["email"] == 2
    assert stats["by_channel"]["linkedin"] == 1
    assert stats["by_action_type"]["cold_email"] == 1


def test_query_top_posts(store):
    today = datetime.now().strftime("%Y-%m-%d")
    store.insert_content_metrics([
        {"post_id": f"tp{i}", "platform": "linkedin", "publish_date": today,
         "scraped_at": today, "engagement_rate": float(i)}
        for i in range(10)
    ])
    top = store.query_top_posts(limit=5)
    assert len(top) == 5
    rates = [r["engagement_rate"] for r in top]
    assert rates == sorted(rates, reverse=True)


def test_query_behavioral_signals_date_filter(store):
    old_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    recent_date = datetime.now().strftime("%Y-%m-%d")

    store.insert_behavioral_signals([
        {"contact_name": "Old", "signal_type": "view", "signal_date": old_date,
         "source": "linkedin", "weight": 1},
        {"contact_name": "New", "signal_type": "view", "signal_date": recent_date,
         "source": "linkedin", "weight": 1},
    ])
    rows = store.query_behavioral_signals(days=7)
    names = [r["contact_name"] for r in rows]
    assert "New" in names
    assert "Old" not in names


def test_query_copy_edits(store):
    today = datetime.now().strftime("%Y-%m-%d")
    store.insert_copy_edit("old text", "new text", today, "fixed tone", "outreach")

    rows = store.query_copy_edits(days=30)
    assert len(rows) == 1
    assert rows[0]["original_text"] == "old text"


def test_generate_monthly_learnings_no_data(store):
    report = store.generate_monthly_learnings(days=30)
    assert report["edits_analyzed"] == 0
    assert report["avg_length_change_pct"] == 0.0
    assert report["edit_frequency_by_context"] == {}
    assert report["common_patterns"] == []
    assert report["recommendations"] == []


def test_generate_monthly_learnings_with_edits(store):
    today = datetime.now().strftime("%Y-%m-%d")
    store.insert_copy_edit("short", "much longer text here", today, "expanded", "outreach")
    store.insert_copy_edit("verbose wordy text", "concise", today, "trimmed", "outreach")
    store.insert_copy_edit("foo bar", "baz qux quux", today, "rewrite", "content")

    report = store.generate_monthly_learnings(days=30)
    assert report["edits_analyzed"] == 3
    assert isinstance(report["avg_length_change_pct"], float)
    assert "outreach" in report["edit_frequency_by_context"]
    assert report["edit_frequency_by_context"]["outreach"] == 2
