import json
import subprocess
import sys

import pytest

from kipi_mcp.step_logger import StepLogger
from kipi_mcp.loop_tracker import LoopTracker


EXPECTED_TOOLS = [
    "kipi_migrate",
    "kipi_suggest_instance_name",
    "kipi_set_instance_name",
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
    "loop_prune",
    "kipi_create_template",
    "kipi_build_schedule",
    "kipi_backup",
    "kipi_export",
    "kipi_import",
    "kipi_verify_schedule",
    "kipi_verify_bus",
    "kipi_verify_orchestrator",
    "kipi_bus_to_log",
    "kipi_scan_draft",
    "kipi_audit_morning",
]

EXPECTED_RESOURCES = [
    "kipi://paths",
    "kipi://status",
    "kipi://instances",
    "kipi://loops/open",
    "kipi://loops/stats",
    "kipi://backups",
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
    """Verify all expected tool names are registered on the FastMCP instance."""
    from kipi_mcp.server import mcp

    registered = list(mcp._tool_manager._tools.keys())
    for name in EXPECTED_TOOLS:
        assert name in registered, f"Tool '{name}' not registered. Found: {registered}"
    assert len(EXPECTED_TOOLS) == len(registered), (
        f"Expected {len(EXPECTED_TOOLS)} tools, got {len(registered)}. "
        f"Extra: {set(registered) - set(EXPECTED_TOOLS)}, "
        f"Missing: {set(EXPECTED_TOOLS) - set(registered)}"
    )


def test_all_resources_registered():
    """Verify all expected resource URIs are registered."""
    from kipi_mcp.server import mcp

    # Resource manager stores resources by URI
    resources = list(mcp._resource_manager._resources.keys())
    for uri in EXPECTED_RESOURCES:
        assert uri in resources, f"Resource '{uri}' not registered. Found: {resources}"


def test_resource_paths_returns_dirs():
    """Verify kipi://paths resource returns all 4 directory keys."""
    from kipi_mcp.server import resource_paths

    result = json.loads(resource_paths())
    assert "config_dir" in result
    assert "data_dir" in result
    assert "state_dir" in result
    assert "repo_dir" in result


def test_resource_instances_returns_structure():
    """Verify kipi://instances resource returns expected keys."""
    from kipi_mcp.server import resource_instances

    result = json.loads(resource_instances())
    assert "instances" in result or "error" in result


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
    loop_file.parent.mkdir(parents=True)
    tracker = LoopTracker(loop_file)

    assert not loop_file.exists()
    result = tracker.list(min_level=0)
    assert result == []


def test_main_entry_point_exists():
    """Verify the main() function exists for project.scripts entry point."""
    from kipi_mcp.server import main
    assert callable(main)
