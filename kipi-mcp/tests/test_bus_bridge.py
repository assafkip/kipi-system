from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from kipi_mcp.bus_bridge import BusBridge


@pytest.fixture
def bridge(tmp_path):
    bus_dir = tmp_path / "bus"
    output_dir = tmp_path / "output"
    bus_dir.mkdir()
    output_dir.mkdir()
    return BusBridge(bus_dir, output_dir)


def _write(bus_dir, date, filename, data):
    d = bus_dir / date
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(json.dumps(data))


def test_all_files_present_all_done(bridge, tmp_path):
    date = "2026-03-27"
    bus_dir = tmp_path / "bus"
    output_dir = tmp_path / "output"
    all_bus_files = [
        "preflight.json", "calendar.json", "gmail.json", "notion.json",
        "meeting-prep.json", "linkedin-posts.json", "linkedin-dms.json",
        "dp-pipeline.json", "signals.json", "temperature.json", "leads.json",
        "hitlist.json", "compliance.json", "positioning.json",
        "canonical-digest.json", "content-metrics.json", "copy-diffs.json",
        "behavioral-signals.json", "prospect-activity.json",
        "outreach-queue.json", "loop-review.json", "pipeline-followup.json",
        "notion-push.json", "daily-checklists.json", "kipi-promo.json",
        "value-routing.json",
    ]
    for f in all_bus_files:
        _write(bus_dir, date, f, {"ok": True})
    (output_dir / f"schedule-data-{date}.json").write_text("{}")
    (output_dir / f"daily-schedule-{date}.html").write_text("<html></html>")

    result = bridge.bridge(date)
    assert result["done"] == result["total"]
    assert result["date"] == date
    log = json.loads((output_dir / f"morning-log-{date}.json").read_text())
    assert log["date"] == date
    assert all(s["status"] == "done" for s in log["steps"].values())


def test_missing_files_logged_as_skipped(bridge, tmp_path):
    date = "2026-03-27"
    bus_dir = tmp_path / "bus"
    _write(bus_dir, date, "preflight.json", {"ok": True})

    result = bridge.bridge(date)
    assert result["done"] < result["total"]
    output_dir = tmp_path / "output"
    log = json.loads((output_dir / f"morning-log-{date}.json").read_text())
    skipped = [k for k, v in log["steps"].items() if v["status"] == "skipped"]
    assert len(skipped) > 0


def test_error_key_logged_as_failed(bridge, tmp_path):
    date = "2026-03-27"
    bus_dir = tmp_path / "bus"
    _write(bus_dir, date, "calendar.json", {"error": "auth failed"})

    result = bridge.bridge(date)
    output_dir = tmp_path / "output"
    log = json.loads((output_dir / f"morning-log-{date}.json").read_text())
    assert log["steps"]["1_calendar"]["status"] == "failed"


def test_invalid_json_logged_as_failed(bridge, tmp_path):
    date = "2026-03-27"
    bus_dir = tmp_path / "bus"
    d = bus_dir / date
    d.mkdir(parents=True, exist_ok=True)
    (d / "calendar.json").write_text("{bad json")

    result = bridge.bridge(date)
    output_dir = tmp_path / "output"
    log = json.loads((output_dir / f"morning-log-{date}.json").read_text())
    assert log["steps"]["1_calendar"]["status"] == "failed"


def test_no_bus_directory_raises(bridge):
    with pytest.raises(ValueError, match="No bus directory"):
        bridge.bridge("2099-01-01")


def test_schedule_and_html_present(bridge, tmp_path):
    date = "2026-03-27"
    bus_dir = tmp_path / "bus"
    output_dir = tmp_path / "output"
    (bus_dir / date).mkdir(parents=True)
    (output_dir / f"schedule-data-{date}.json").write_text("{}")
    (output_dir / f"daily-schedule-{date}.html").write_text("<html></html>")

    result = bridge.bridge(date)
    log = json.loads((output_dir / f"morning-log-{date}.json").read_text())
    assert log["steps"]["8_briefing_output"]["status"] == "done"
    assert log["steps"]["11_html_output"]["status"] == "done"
    assert log["steps"]["8.5_start_here"]["status"] == "done"


def test_date_defaults_to_today(bridge, tmp_path):
    today = datetime.now().strftime("%Y-%m-%d")
    bus_dir = tmp_path / "bus"
    (bus_dir / today).mkdir(parents=True)

    result = bridge.bridge()
    assert result["date"] == today
