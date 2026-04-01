from __future__ import annotations

import sqlite3
import zlib
from datetime import datetime, timedelta

import pytest

from kipi_mcp.harvest_store import HarvestStore


def test_init_creates_all_tables(tmp_path):
    db = tmp_path / "harvest.db"
    s = HarvestStore(db_path=db)
    tables = s.init_db()
    assert len(tables) == 7
    expected = {
        "harvest_runs", "source_runs", "harvest_records",
        "harvest_bodies", "source_cursors", "apify_budget",
        "notion_write_queue",
    }
    assert set(tables) == expected


def test_init_idempotent(tmp_path):
    db = tmp_path / "harvest.db"
    s = HarvestStore(db_path=db)
    t1 = s.init_db()
    t2 = s.init_db()
    assert t1 == t2


def test_create_run(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    assert run["mode"] == "incremental"
    assert run["status"] == "running"
    assert "run_id" in run
    today = datetime.now().strftime("%Y-%m-%d")
    assert run["run_id"].startswith(today)


def test_update_run(tmp_harvest_store):
    run = tmp_harvest_store.create_run("full")
    completed = datetime.now().isoformat()
    updated = tmp_harvest_store.update_run(run["run_id"], "complete", completed_at=completed)
    assert updated["status"] == "complete"
    assert updated["completed_at"] == completed


def test_get_run(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    fetched = tmp_harvest_store.get_run(run["run_id"])
    assert fetched is not None
    assert fetched["run_id"] == run["run_id"]
    assert fetched["mode"] == "incremental"
    assert tmp_harvest_store.get_run("nonexistent") is None


def test_get_latest_run(tmp_harvest_store):
    tmp_harvest_store.create_run("full")
    r2 = tmp_harvest_store.create_run("incremental")
    latest = tmp_harvest_store.get_latest_run()
    assert latest is not None
    assert latest["run_id"] == r2["run_id"]


def test_create_source_run(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    sr = tmp_harvest_store.create_source_run(run["run_id"], "linkedin", "api")
    assert sr["source_name"] == "linkedin"
    assert sr["method"] == "api"
    assert sr["status"] == "running"
    assert "id" in sr


def test_update_source_run(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    sr = tmp_harvest_store.create_source_run(run["run_id"], "linkedin", "api")
    updated = tmp_harvest_store.update_source_run(
        sr["id"], status="complete", records=42, cursor_after="abc123"
    )
    assert updated["status"] == "complete"
    assert updated["records"] == 42
    assert updated["cursor_after"] == "abc123"


def test_store_record_basic(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    result = tmp_harvest_store.store_record(
        run["run_id"], "linkedin", "post-1", '{"title": "test"}'
    )
    assert "id" in result
    assert result.get("deduped") is not True
    records = tmp_harvest_store.get_records("linkedin", days=1)
    assert len(records) == 1
    assert records[0]["summary_json"] == '{"title": "test"}'


def test_store_record_with_body_compression(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    body_text = "Hello world " * 100
    result = tmp_harvest_store.store_record(
        run["run_id"], "linkedin", "post-2", '{"title": "test"}',
        body_text=body_text,
    )
    assert "id" in result
    assert result["compressed_size"] > 0
    assert result["original_size"] == len(body_text.encode("utf-8"))

    records = tmp_harvest_store.get_records("linkedin", days=1, include_body=True)
    assert len(records) == 1
    assert records[0]["body_text"] == body_text


def test_store_record_dedup(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    r1 = tmp_harvest_store.store_record(
        run["run_id"], "linkedin", "dup-key", '{"a": 1}'
    )
    r2 = tmp_harvest_store.store_record(
        run["run_id"], "linkedin", "dup-key", '{"a": 2}'
    )
    assert r2["deduped"] is True
    assert r2["existing_id"] == r1["id"]
    records = tmp_harvest_store.get_records("linkedin", days=1)
    assert len(records) == 1


def test_store_record_body_size_limit(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    big_body = "x" * 2_000_000  # > 1MB
    result = tmp_harvest_store.store_record(
        run["run_id"], "linkedin", "big-body", '{"a": 1}',
        body_text=big_body,
    )
    assert "id" in result
    assert result.get("warning") is not None

    records = tmp_harvest_store.get_records("linkedin", days=1, include_body=True)
    assert len(records) == 1
    assert len(records[0]["body_text"]) <= 260_000


def test_store_record_summary_size_limit(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    big_summary = "x" * 4097
    with pytest.raises(ValueError, match="summary_json"):
        tmp_harvest_store.store_record(
            run["run_id"], "linkedin", "big-summary", big_summary
        )


def test_store_record_max_per_source(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    for i in range(500):
        result = tmp_harvest_store.store_record(
            run["run_id"], "linkedin", f"rec-{i}", '{"i": ' + str(i) + '}'
        )
        assert result is not None and "id" in result

    overflow = tmp_harvest_store.store_record(
        run["run_id"], "linkedin", "rec-overflow", '{"overflow": true}'
    )
    assert overflow is None


def test_get_records_without_body(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    tmp_harvest_store.store_record(
        run["run_id"], "linkedin", "rec-1", '{"title": "test"}',
        body_text="some body content",
    )
    records = tmp_harvest_store.get_records("linkedin", days=1, include_body=False)
    assert len(records) == 1
    assert "body_text" not in records[0]
    assert records[0]["summary_json"] == '{"title": "test"}'


def test_get_records_with_body(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    body = "detailed body text here"
    tmp_harvest_store.store_record(
        run["run_id"], "linkedin", "rec-1", '{"title": "test"}',
        body_text=body,
    )
    records = tmp_harvest_store.get_records("linkedin", days=1, include_body=True)
    assert len(records) == 1
    assert records[0]["body_text"] == body


def test_get_records_keyset_pagination(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    ids = []
    for i in range(5):
        r = tmp_harvest_store.store_record(
            run["run_id"], "linkedin", f"page-{i}", f'{{"i": {i}}}'
        )
        ids.append(r["id"])

    after = ids[2]
    records = tmp_harvest_store.get_records("linkedin", days=1, after_id=after)
    returned_ids = [r["id"] for r in records]
    assert all(rid > after for rid in returned_ids)
    assert len(returned_ids) == 2


def test_get_records_days_filter(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    tmp_harvest_store.store_record(
        run["run_id"], "linkedin", "recent", '{"fresh": true}'
    )

    conn = sqlite3.connect(str(tmp_harvest_store.db_path))
    old_date = (datetime.now() - timedelta(days=10)).isoformat()
    conn.execute(
        "INSERT INTO harvest_records (run_id, source_name, record_key, summary_json, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (run["run_id"], "linkedin", "old-rec", '{"old": true}', old_date),
    )
    conn.commit()
    conn.close()

    records = tmp_harvest_store.get_records("linkedin", days=3)
    keys = [r["record_key"] for r in records]
    assert "recent" in keys
    assert "old-rec" not in keys


def test_cleanup_deletes_old_runs(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    tmp_harvest_store.store_record(
        run["run_id"], "linkedin", "rec-1", '{"a": 1}', body_text="body"
    )
    tmp_harvest_store.create_source_run(run["run_id"], "linkedin", "api")

    conn = sqlite3.connect(str(tmp_harvest_store.db_path))
    old_date = (datetime.now() - timedelta(days=30)).isoformat()
    conn.execute(
        "UPDATE harvest_runs SET started_at = ? WHERE run_id = ?",
        (old_date, run["run_id"]),
    )
    conn.commit()
    conn.close()

    result = tmp_harvest_store.cleanup(days=7)
    assert result["deleted_runs"] >= 1
    assert tmp_harvest_store.get_run(run["run_id"]) is None
    records = tmp_harvest_store.get_records("linkedin", days=365)
    assert len(records) == 0


def test_cursor_read_write(tmp_harvest_store):
    assert tmp_harvest_store.get_cursor("linkedin") is None
    tmp_harvest_store.set_cursor("linkedin", "2026-03-30T00:00:00", "published_at")
    cursor = tmp_harvest_store.get_cursor("linkedin")
    assert cursor is not None
    assert cursor["cursor_value"] == "2026-03-30T00:00:00"
    assert cursor["cursor_field"] == "published_at"


def test_cursor_update_existing(tmp_harvest_store):
    tmp_harvest_store.set_cursor("linkedin", "2026-03-29", "published_at")
    tmp_harvest_store.set_cursor("linkedin", "2026-03-30", "published_at")
    cursor = tmp_harvest_store.get_cursor("linkedin")
    assert cursor["cursor_value"] == "2026-03-30"


def test_budget_check_under_limit(tmp_harvest_store):
    tmp_harvest_store.record_spend("2026-03", 1.50)
    result = tmp_harvest_store.check_budget("2026-03")
    assert result["ok"] is True
    assert result["spent"] == 1.50
    assert result["remaining"] > 0


def test_budget_check_over_limit(tmp_harvest_store):
    tmp_harvest_store.record_spend("2026-03", 5.50)
    result = tmp_harvest_store.check_budget("2026-03")
    assert result["ok"] is False
    assert result["remaining"] <= 0


def test_budget_approve_extra(tmp_harvest_store):
    tmp_harvest_store.record_spend("2026-03", 4.5)
    tmp_harvest_store.approve_extra("2026-03", 3.0)
    result = tmp_harvest_store.check_budget("2026-03")
    assert result["ok"] is True
    assert result["limit"] == 5.0
    assert result["approved_extra"] == pytest.approx(3.0)
    assert result["remaining"] == pytest.approx(3.5)


def test_harvest_summary_counts(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    for i in range(3):
        tmp_harvest_store.store_record(
            run["run_id"], "linkedin", f"li-{i}", f'{{"i": {i}}}'
        )
    for i in range(2):
        tmp_harvest_store.store_record(
            run["run_id"], "twitter", f"tw-{i}", f'{{"i": {i}}}'
        )
    summary = tmp_harvest_store.harvest_summary(run["run_id"])
    assert summary["linkedin"] == 3
    assert summary["twitter"] == 2


def test_complete_source_run(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    sr = tmp_harvest_store.create_source_run(run["run_id"], "linkedin", "chrome")
    # Source starts as "running"
    assert sr["status"] == "running"
    # Complete it
    result = tmp_harvest_store.complete_source_run(run["run_id"], "linkedin", 5)
    assert result["status"] == "complete"
    assert result["records"] == 5


def test_check_run_complete_all_done(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    tmp_harvest_store.create_source_run(run["run_id"], "src-a", "http")
    tmp_harvest_store.create_source_run(run["run_id"], "src-b", "mcp")
    # Complete both
    tmp_harvest_store.complete_source_run(run["run_id"], "src-a", 3)
    tmp_harvest_store.complete_source_run(run["run_id"], "src-b", 2)
    assert tmp_harvest_store.check_run_complete(run["run_id"]) is True
    # Run should be auto-marked complete
    r = tmp_harvest_store.get_run(run["run_id"])
    assert r["status"] == "complete"


def test_check_run_complete_partial(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    tmp_harvest_store.create_source_run(run["run_id"], "src-a", "http")
    tmp_harvest_store.create_source_run(run["run_id"], "src-b", "chrome")
    # Only complete one
    tmp_harvest_store.complete_source_run(run["run_id"], "src-a", 3)
    assert tmp_harvest_store.check_run_complete(run["run_id"]) is False


# ============================================================
# Harvest health tests
# ============================================================


def test_harvest_health_complete_run(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    tmp_harvest_store.create_source_run(run["run_id"], "linkedin", "chrome")
    tmp_harvest_store.create_source_run(run["run_id"], "twitter", "api")
    tmp_harvest_store.complete_source_run(run["run_id"], "linkedin", 20)
    tmp_harvest_store.complete_source_run(run["run_id"], "twitter", 15)

    health = tmp_harvest_store.harvest_health(run["run_id"])
    assert health["healthy"] is True
    assert health["total_records"] == 35
    assert set(health["sources_complete"]) == {"linkedin", "twitter"}
    assert health["sources_failed"] == []
    assert health["sources_pending"] == []
    assert health["warnings"] == []


def test_harvest_health_with_failures(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    tmp_harvest_store.create_source_run(run["run_id"], "linkedin", "chrome")
    tmp_harvest_store.create_source_run(run["run_id"], "twitter", "api")
    tmp_harvest_store.complete_source_run(run["run_id"], "linkedin", 20)
    tmp_harvest_store.update_source_run(
        tmp_harvest_store.create_source_run(run["run_id"], "broken", "api")["id"],
        status="error", error="timeout",
    )

    health = tmp_harvest_store.harvest_health(run["run_id"])
    assert "linkedin" in health["sources_complete"]
    assert len(health["sources_failed"]) == 1
    assert health["sources_failed"][0]["source"] == "broken"
    assert health["sources_failed"][0]["error"] == "timeout"


def test_harvest_health_low_records_warning(tmp_harvest_store):
    run = tmp_harvest_store.create_run("incremental")
    tmp_harvest_store.create_source_run(run["run_id"], "linkedin", "chrome")
    tmp_harvest_store.complete_source_run(run["run_id"], "linkedin", 3)

    health = tmp_harvest_store.harvest_health(run["run_id"])
    assert health["healthy"] is False
    assert any("Very few records" in w for w in health["warnings"])


# ============================================================
# Notion write queue tests
# ============================================================


def test_queue_notion_write(tmp_harvest_store):
    result = tmp_harvest_store.queue_notion_write('{"action": "create_page"}', "09-notion-push")
    assert "id" in result
    assert result["status"] == "pending"
    assert result["created_at"]


def test_get_pending_notion_writes(tmp_harvest_store):
    tmp_harvest_store.queue_notion_write('{"a": 1}', "agent-a")
    tmp_harvest_store.queue_notion_write('{"a": 2}', "agent-b")
    pending = tmp_harvest_store.get_pending_notion_writes()
    assert len(pending) == 2
    assert pending[0]["source_agent"] == "agent-a"
    assert pending[1]["source_agent"] == "agent-b"


def test_update_notion_write_complete(tmp_harvest_store):
    queued = tmp_harvest_store.queue_notion_write('{"a": 1}', "agent-a")
    updated = tmp_harvest_store.update_notion_write(queued["id"], "complete")
    assert updated["status"] == "complete"
    assert updated["completed_at"] is not None
    # Should no longer appear in pending
    assert len(tmp_harvest_store.get_pending_notion_writes()) == 0


def test_fail_stale_notion_writes(tmp_harvest_store):
    q1 = tmp_harvest_store.queue_notion_write('{"a": 1}', "agent-a")
    # Simulate 3 failed attempts
    for _ in range(3):
        tmp_harvest_store.update_notion_write(q1["id"], "failed", error="api_error")
    # Reset to pending so fail_stale can pick it up
    conn = sqlite3.connect(str(tmp_harvest_store.db_path))
    conn.execute("UPDATE notion_write_queue SET status='pending' WHERE id=?", (q1["id"],))
    conn.commit()
    conn.close()

    result = tmp_harvest_store.fail_stale_notion_writes(max_attempts=3)
    assert result["marked_failed"] == 1
    # Should no longer be pending
    assert len(tmp_harvest_store.get_pending_notion_writes()) == 0
