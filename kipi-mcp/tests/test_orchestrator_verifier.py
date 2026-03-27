from __future__ import annotations

import json
import pytest
from kipi_mcp.orchestrator_verifier import OrchestratorVerifier
from kipi_mcp.step_logger import StepLogger


DATE = "2026-03-27"


@pytest.fixture
def dirs(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    bus_dir = tmp_path / "bus"
    bus_dir.mkdir()
    return output_dir, bus_dir


@pytest.fixture
def verifier(dirs):
    output_dir, bus_dir = dirs
    logger = StepLogger(output_dir)
    return OrchestratorVerifier(output_dir, bus_dir, logger)


@pytest.fixture
def init_log(dirs):
    """Create an initialized morning log and return the logger."""
    output_dir, _ = dirs
    logger = StepLogger(output_dir)
    logger.init(DATE)
    return logger


def _read_log(output_dir):
    return json.loads((output_dir / f"morning-log-{DATE}.json").read_text())


def _write_bus(bus_dir, filename, data):
    date_dir = bus_dir / DATE
    date_dir.mkdir(exist_ok=True)
    (date_dir / filename).write_text(json.dumps(data))


# ── Phase 0: session-start checksums ──


def test_phase0_checksums_present(verifier, init_log):
    init_log.checksum(DATE, "start", "canonical_file_count", "5")
    result = verifier.check_phase(DATE, 0)
    assert result["pass"] is True
    assert result["phase"] == 0
    assert result["issues"] == []


def test_phase0_missing_checksums(verifier, init_log):
    result = verifier.check_phase(DATE, 0)
    assert result["pass"] is False
    assert any("session-start checksums" in i for i in result["issues"])


def test_phase0_missing_checksums_fix(verifier, init_log, dirs):
    _, bus_dir = dirs
    _write_bus(bus_dir, "some-data.json", {"ok": True})
    result = verifier.check_phase(DATE, 0, fix=True)
    assert result["pass"] is True
    assert len(result["fixes_applied"]) > 0
    assert any("checksums" in f for f in result["fixes_applied"])


# ── Phase >= 1: gate check ──


def test_phase1_gate_logged(verifier, init_log):
    init_log.gate_check(DATE, "phase_1", True)
    result = verifier.check_phase(DATE, 1)
    assert result["pass"] is True
    assert result["issues"] == []


def test_phase1_missing_gate(verifier, init_log):
    result = verifier.check_phase(DATE, 1)
    assert result["pass"] is False
    assert any("Gate check not logged" in i for i in result["issues"])


# ── Phase 5: action cards from hitlist ──


def test_phase5_hitlist_with_cards(verifier, init_log, dirs):
    _, bus_dir = dirs
    _write_bus(bus_dir, "hitlist.json", {
        "actions": [
            {"rank": 1, "action_type": "comment", "contact_name": "Alice", "copy": "Great post!", "post_url": "https://li.com/1"}
        ]
    })
    init_log.add_card(DATE, "C1", "comment", "Alice", "Great post!", "https://li.com/1")
    init_log.gate_check(DATE, "phase_5", True)
    result = verifier.check_phase(DATE, 5)
    assert result["pass"] is True


def test_phase5_hitlist_no_cards(verifier, init_log, dirs):
    _, bus_dir = dirs
    _write_bus(bus_dir, "hitlist.json", {
        "actions": [
            {"rank": 1, "action_type": "comment", "contact_name": "Alice", "copy": "Great post!", "post_url": "https://li.com/1"}
        ]
    })
    init_log.gate_check(DATE, "phase_5", True)
    result = verifier.check_phase(DATE, 5)
    assert result["pass"] is False
    assert any("0 action cards" in i for i in result["issues"])


def test_phase5_fix_logs_cards(verifier, init_log, dirs):
    output_dir, bus_dir = dirs
    _write_bus(bus_dir, "hitlist.json", {
        "actions": [
            {"rank": 1, "action_type": "comment", "contact_name": "Alice", "copy": "Great post!", "post_url": "https://li.com/1"},
            {"rank": 2, "action_type": "DM", "contact_name": "Bob", "copy": "Hey Bob", "profile_url": "https://li.com/bob"},
        ]
    })
    init_log.gate_check(DATE, "phase_5", True)
    result = verifier.check_phase(DATE, 5, fix=True)
    assert result["pass"] is True
    assert any("2 action cards" in f for f in result["fixes_applied"])
    log = _read_log(output_dir)
    assert len(log["action_cards"]) == 2
    assert log["action_cards"][0]["id"] == "C1"
    assert log["action_cards"][1]["id"] == "DM2"


def test_phase5_tier_a_no_connection_requests(verifier, init_log, dirs):
    _, bus_dir = dirs
    _write_bus(bus_dir, "hitlist.json", {
        "actions": [
            {"rank": 1, "action_type": "comment", "contact_name": "Alice", "copy": "Great post!"}
        ]
    })
    _write_bus(bus_dir, "leads.json", {
        "qualified_leads": [
            {"name": "Carol", "tier": "A"}
        ]
    })
    init_log.add_card(DATE, "C1", "comment", "Alice", "Great post!")
    init_log.gate_check(DATE, "phase_5", True)
    result = verifier.check_phase(DATE, 5)
    assert any("0 connection requests" in i for i in result["issues"])


# ── Edge: no log file ──


def test_no_log_file(verifier):
    result = verifier.check_phase(DATE, 0)
    assert result["pass"] is False
    assert any("not found" in i for i in result["issues"])
