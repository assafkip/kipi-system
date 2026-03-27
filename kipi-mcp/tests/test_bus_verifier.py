from __future__ import annotations

import json

import pytest

from kipi_mcp.bus_verifier import BusVerifier


@pytest.fixture
def verifier(tmp_path):
    return BusVerifier(tmp_path)


def _write(bus_dir, date, filename, data):
    d = bus_dir / date
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(json.dumps(data))


def test_phase0_all_required_present_and_valid(verifier, tmp_path):
    date = "2026-03-27"
    _write(tmp_path, date, "preflight.json", {"ready": True})
    _write(tmp_path, date, "energy.json", {"level": 3})
    result = verifier.verify(date, 0)
    assert result["pass"] is True
    assert result["phase"] == 0
    assert result["date"] == date
    assert all(r["status"] == "ok" for r in result["results"])


def test_phase0_missing_preflight(verifier, tmp_path):
    date = "2026-03-27"
    _write(tmp_path, date, "energy.json", {"level": 3})
    result = verifier.verify(date, 0)
    assert result["pass"] is False
    fail_results = [r for r in result["results"] if r["status"] == "fail"]
    assert any(r["file"] == "preflight.json" for r in fail_results)


def test_phase1_all_required_present(verifier, tmp_path):
    date = "2026-03-27"
    _write(tmp_path, date, "calendar.json", {"today": []})
    _write(tmp_path, date, "gmail.json", {"emails": []})
    _write(tmp_path, date, "notion.json", {"contacts": [], "actions": []})
    result = verifier.verify(date, 1)
    assert result["pass"] is True


def test_phase1_calendar_with_error_key(verifier, tmp_path):
    date = "2026-03-27"
    _write(tmp_path, date, "calendar.json", {"error": "auth failed"})
    _write(tmp_path, date, "gmail.json", {"emails": []})
    _write(tmp_path, date, "notion.json", {"contacts": [], "actions": []})
    result = verifier.verify(date, 1)
    warn_results = [r for r in result["results"] if r["status"] == "warn"]
    assert any(r["file"] == "calendar.json" for r in warn_results)


def test_phase3_missing_required(verifier, tmp_path):
    date = "2026-03-27"
    _write(tmp_path, date, "linkedin-posts.json", {"posts": []})
    result = verifier.verify(date, 3)
    assert result["pass"] is False
    fail_files = [r["file"] for r in result["results"] if r["status"] == "fail"]
    assert "linkedin-dms.json" in fail_files
    assert "dp-pipeline.json" in fail_files


def test_phase4_tuesday_tl_content_missing_fails(verifier, tmp_path):
    date = "2026-03-24"  # Tuesday
    _write(tmp_path, date, "signals.json", {"selected_signal": "test"})
    result = verifier.verify(date, 4)
    assert result["pass"] is False
    fail_results = [r for r in result["results"] if r["status"] == "fail"]
    assert any(r["file"] == "tl-content.json" for r in fail_results)


def test_phase4_wednesday_tl_content_missing_ok(verifier, tmp_path):
    date = "2026-03-25"  # Wednesday
    _write(tmp_path, date, "signals.json", {"selected_signal": "test"})
    result = verifier.verify(date, 4)
    assert result["pass"] is True
    skip_results = [r for r in result["results"] if r["status"] == "skip"]
    assert any(r["file"] == "tl-content.json" for r in skip_results)


def test_phase5_hitlist_empty_actions_fails(verifier, tmp_path):
    date = "2026-03-27"
    _write(tmp_path, date, "temperature.json", {"scores": []})
    _write(tmp_path, date, "leads.json", {})
    _write(tmp_path, date, "hitlist.json", {"actions": []})
    result = verifier.verify(date, 5)
    assert result["pass"] is False
    fail_results = [r for r in result["results"] if r["status"] == "fail"]
    assert any(r["file"] == "hitlist.json" for r in fail_results)


def test_unknown_phase_passes(verifier, tmp_path):
    date = "2026-03-27"
    (tmp_path / date).mkdir(parents=True, exist_ok=True)
    result = verifier.verify(date, 99)
    assert result["pass"] is True
    assert result["results"] == []


def test_bus_dir_missing_raises(verifier):
    result = verifier.verify("2099-01-01", 0)
    assert result["pass"] is False
    assert any("does not exist" in r["detail"] for r in result["results"])


def test_phase0_invalid_json(verifier, tmp_path):
    date = "2026-03-27"
    d = tmp_path / date
    d.mkdir(parents=True, exist_ok=True)
    (d / "preflight.json").write_text("{bad json")
    _write(tmp_path, date, "energy.json", {"level": 3})
    result = verifier.verify(date, 0)
    assert result["pass"] is False
    fail_results = [r for r in result["results"] if r["status"] == "fail"]
    assert any(r["file"] == "preflight.json" for r in fail_results)


def test_phase0_structure_check_fails(verifier, tmp_path):
    date = "2026-03-27"
    _write(tmp_path, date, "preflight.json", {"ready": False})
    _write(tmp_path, date, "energy.json", {"level": 3})
    result = verifier.verify(date, 0)
    assert result["pass"] is False
