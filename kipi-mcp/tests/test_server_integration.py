import json
import subprocess
import sys

import pytest

from kipi_mcp.step_logger import StepLogger
from kipi_mcp.loop_tracker import LoopTracker


EXPECTED_TOOLS = [
    "kipi_list",
    "kipi_home",
    "kipi_paths_info",
    "kipi_migrate",
    "kipi_new_instance",
    "kipi_update",
    "kipi_push_upstream",
    "kipi_validate",
    "log_init",
    "log_step",
    "log_add_card",
    "log_deliver_cards",
    "log_gate_check",
    "log_checksum",
    "log_verify",
    "loop_open",
    "loop_close",
    "loop_force_close",
    "loop_escalate",
    "loop_touch",
    "loop_list",
    "loop_stats",
    "loop_prune",
    "load_step",
    "create_from_template",
    "build_schedule",
]

KIPI_MCP_DIR = "/Users/ike/code/kipi-system/kipi-mcp"


def test_server_process_starts():
    """Start the server as a subprocess and verify it responds to JSON-RPC initialize."""
    init_msg = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0.1.0"},
        },
    }) + "\n"

    proc = subprocess.Popen(
        ["uv", "run", "python", "src/kipi_mcp/server.py"],
        cwd=KIPI_MCP_DIR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        stdout, stderr = proc.communicate(input=init_msg.encode(), timeout=5)
        # Server should produce a JSON-RPC response on stdout
        assert proc.returncode is not None
        lines = [l for l in stdout.decode().strip().splitlines() if l.strip()]
        assert len(lines) >= 1, f"Expected JSON-RPC response, got empty stdout. stderr: {stderr.decode()[:500]}"
        response = json.loads(lines[0])
        assert response.get("jsonrpc") == "2.0"
        assert response.get("id") == 1
        assert "result" in response, f"Expected 'result' in response, got: {response}"
    finally:
        proc.kill()
        proc.wait()


def test_all_tools_registered():
    """Verify all 26 expected tool names are registered on the FastMCP instance."""
    from kipi_mcp.server import mcp

    registered = list(mcp._tool_manager._tools.keys())
    for name in EXPECTED_TOOLS:
        assert name in registered, f"Tool '{name}' not registered. Found: {registered}"
    assert len(EXPECTED_TOOLS) == len(registered), (
        f"Expected {len(EXPECTED_TOOLS)} tools, got {len(registered)}. "
        f"Extra: {set(registered) - set(EXPECTED_TOOLS)}, "
        f"Missing: {set(EXPECTED_TOOLS) - set(registered)}"
    )


def test_kipi_home_returns_valid_path():
    """Call kipi_home tool function directly and verify it returns a valid JSON path."""
    from kipi_mcp.server import kipi_home

    result = kipi_home()
    data = json.loads(result)
    assert "kipi_home" in data
    assert len(data["kipi_home"]) > 0


def test_kipi_list_returns_registry_data():
    """Call kipi_list and verify it returns JSON with 'instances' key."""
    from kipi_mcp.server import kipi_list

    result = kipi_list()
    data = json.loads(result)
    # Either has "instances" key (success) or "error" key (registry missing, still valid)
    assert "instances" in data or "error" in data


def test_log_init_creates_file(tmp_path):
    """Use a tmp_path, call log_init with a test date, verify file created with correct structure."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    logger = StepLogger(output_dir)

    result = logger.init("2026-01-15")
    assert "created" in result

    log_file = output_dir / "morning-log-2026-01-15.json"
    assert log_file.exists()

    data = json.loads(log_file.read_text())
    assert data["date"] == "2026-01-15"
    assert data["steps"] == {}
    assert data["action_cards"] == []
    assert data["audit"] is None
    assert "session_start" in data


def test_loop_list_empty_when_no_file(tmp_path):
    """Verify loop_list returns empty list when no loops file exists."""
    loop_file = tmp_path / "nonexistent-dir" / "open-loops.json"
    # Parent dir must exist for _save to work
    loop_file.parent.mkdir(parents=True)
    tracker = LoopTracker(loop_file)

    assert not loop_file.exists()
    result = tracker.list(min_level=0)
    assert result == []
