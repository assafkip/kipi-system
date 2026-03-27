import json
import pytest
from kipi_mcp.step_logger import StepLogger


@pytest.fixture
def logger(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return StepLogger(output_dir)


DATE = "2026-03-26"


def _read_log(logger, date=DATE):
    return json.loads(logger._log_path(date).read_text())


def test_init_creates_file(logger):
    result = logger.init(DATE)
    assert "created" in result
    data = _read_log(logger)
    assert data["date"] == DATE
    assert data["steps"] == {}
    assert data["action_cards"] == []
    assert data["audit"] is None
    assert "session_start" in data


def test_log_step(logger):
    logger.init(DATE)
    result = logger.log_step(DATE, "step1", "done", result="ok")
    assert result == {"step_id": "step1", "status": "done"}
    data = _read_log(logger)
    assert data["steps"]["step1"]["status"] == "done"
    assert data["steps"]["step1"]["result"] == "ok"
    assert data["steps"]["step1"]["error"] is None


def test_log_step_overwrites(logger):
    logger.init(DATE)
    logger.log_step(DATE, "step1", "running")
    logger.log_step(DATE, "step1", "done", result="finished")
    data = _read_log(logger)
    assert data["steps"]["step1"]["status"] == "done"
    assert data["steps"]["step1"]["result"] == "finished"


def test_add_card(logger):
    logger.init(DATE)
    result = logger.add_card(DATE, "c1", "email", "alice", "Hi Alice")
    assert result == {"card_id": "c1", "target": "alice"}
    data = _read_log(logger)
    assert len(data["action_cards"]) == 1
    card = data["action_cards"][0]
    assert card["id"] == "c1"
    assert card["card_delivered"] is False


def test_add_card_truncates_draft(logger):
    logger.init(DATE)
    long_text = "x" * 300
    logger.add_card(DATE, "c2", "email", "bob", long_text)
    data = _read_log(logger)
    assert len(data["action_cards"][0]["draft_text"]) == 200


def test_deliver_cards(logger):
    logger.init(DATE)
    logger.add_card(DATE, "c1", "email", "alice", "Hi")
    logger.add_card(DATE, "c2", "email", "bob", "Hey")
    result = logger.deliver_cards(DATE)
    assert result == {"delivered": 2}
    data = _read_log(logger)
    assert all(c["card_delivered"] for c in data["action_cards"])
    # delivering again returns 0
    result2 = logger.deliver_cards(DATE)
    assert result2 == {"delivered": 0}


def test_gate_check_pass(logger):
    logger.init(DATE)
    result = logger.gate_check(DATE, "gate3", True)
    assert result == {"gate_step": "gate3", "passed": True}
    data = _read_log(logger)
    assert data["gates_checked"]["gate3"]["all_prior_done"] is True
    assert data["gates_checked"]["gate3"]["missing"] == []


def test_gate_check_fail_with_missing(logger):
    logger.init(DATE)
    result = logger.gate_check(DATE, "gate5", False, missing="step1,step2")
    assert result == {"gate_step": "gate5", "passed": False}
    data = _read_log(logger)
    gate = data["gates_checked"]["gate5"]
    assert gate["all_prior_done"] is False
    assert gate["missing"] == ["step1", "step2"]


def test_checksum_start(logger):
    logger.init(DATE)
    result = logger.checksum(DATE, "start", "relationships", "abc123")
    assert result == {"phase": "start", "key": "relationships", "value": "abc123"}
    data = _read_log(logger)
    assert data["state_checksums"]["session_start"]["relationships"] == "abc123"


def test_checksum_end_with_drift(logger):
    logger.init(DATE)
    logger.checksum(DATE, "start", "relationships", "abc123")
    logger.checksum(DATE, "end", "relationships", "def456")
    data = _read_log(logger)
    assert data["state_checksums"]["session_end"]["relationships"] == "def456"
    assert "relationships" in data["state_checksums"]["drift_detected"]


def test_checksum_end_no_drift(logger):
    logger.init(DATE)
    logger.checksum(DATE, "start", "relationships", "abc123")
    logger.checksum(DATE, "end", "relationships", "abc123")
    data = _read_log(logger)
    assert data["state_checksums"]["drift_detected"] == []


def test_verify_add_new(logger):
    logger.init(DATE)
    result = logger.verify(DATE, "supports RBAC", "current-state.md", True, result="confirmed")
    assert result == {"claim": "supports RBAC", "verified": True}
    data = _read_log(logger)
    assert len(data["verification_queue"]) == 1
    assert data["verification_queue"][0]["source_file"] == "current-state.md"


def test_verify_update_existing(logger):
    logger.init(DATE)
    logger.verify(DATE, "supports RBAC", "current-state.md", False)
    logger.verify(DATE, "supports RBAC", "talk-tracks.md", True, result="confirmed v2")
    data = _read_log(logger)
    assert len(data["verification_queue"]) == 1
    entry = data["verification_queue"][0]
    assert entry["verified"] is True
    assert entry["source_file"] == "talk-tracks.md"
    assert entry["result"] == "confirmed v2"
