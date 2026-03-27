import json
from datetime import datetime, timedelta

import pytest

from kipi_mcp.loop_tracker import LoopTracker


@pytest.fixture
def tracker(tmp_path):
    return LoopTracker(tmp_path / "open-loops.json")


def test_init_creates_file(tracker):
    tracker.open("email_sent", "Alice", "intro email")
    assert tracker._path.exists()
    data = json.loads(tracker._path.read_text())
    assert data["schema_version"] == 1
    assert len(data["loops"]) == 1


def test_open_new_loop(tracker):
    result = tracker.open("email_sent", "Bob", "outreach")
    assert result["action"] == "opened"
    assert result["loop_id"].startswith("L-")


def test_open_duplicate_updates(tracker):
    tracker.open("email_sent", "Carol", "first touch")
    result = tracker.open("email_sent", "Carol", "second touch", follow_up_text="ping again")
    assert result["action"] == "updated"
    assert result["touch_count"] == 2
    data = json.loads(tracker._path.read_text())
    loop = data["loops"][0]
    assert loop["follow_up_text"] == "ping again"


def test_close_loop(tracker):
    opened = tracker.open("email_sent", "Dan", "intro")
    result = tracker.close(opened["loop_id"], "replied", "system")
    assert result["closed"] is True
    assert result["loop_id"] == opened["loop_id"]
    data = json.loads(tracker._path.read_text())
    loop = data["loops"][0]
    assert loop["status"] == "closed"


def test_close_nonexistent(tracker):
    result = tracker.close("L-9999-999", "no reason", "system")
    assert result["closed"] is False
    assert "error" in result


def test_force_close_park(tracker):
    opened = tracker.open("linkedin_sent", "Eve", "dm")
    result = tracker.force_close(opened["loop_id"], "park")
    assert result["force_closed"] is True
    data = json.loads(tracker._path.read_text())
    assert data["loops"][0]["status"] == "parked"


def test_force_close_kill(tracker):
    opened = tracker.open("linkedin_sent", "Frank", "dm")
    result = tracker.force_close(opened["loop_id"], "kill")
    assert result["force_closed"] is True
    data = json.loads(tracker._path.read_text())
    assert data["loops"][0]["status"] == "killed"


def test_escalate(tracker):
    tracker.open("email_sent", "Grace", "old loop")
    data = json.loads(tracker._path.read_text())
    # Set opened date to 15 days ago
    data["loops"][0]["opened"] = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
    tracker._path.write_text(json.dumps(data, indent=2))

    tracker.open("email_sent", "Hank", "medium loop")
    data = json.loads(tracker._path.read_text())
    data["loops"][1]["opened"] = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d")
    tracker._path.write_text(json.dumps(data, indent=2))

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
    data = json.loads(tracker._path.read_text())
    data["loops"][0]["opened"] = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    tracker._path.write_text(json.dumps(data, indent=2))
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

    # Close Pat's loop and backdate it
    data = json.loads(tracker._path.read_text())
    data["loops"][0]["status"] = "closed"
    data["loops"][0]["closed"] = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
    tracker._path.write_text(json.dumps(data, indent=2))

    tracker.close(opened["loop_id"], "done", "system")

    result = tracker.prune(days=30)
    assert result["pruned"] == 1
    assert result["remaining"] == 2
