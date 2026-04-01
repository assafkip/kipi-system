import json
import subprocess
import sys

import pytest

from kipi_mcp.step_logger import StepLogger
from kipi_mcp.loop_tracker import LoopTracker


EXPECTED_TOOLS = [
    "kipi_suggest_instance_name",
    "kipi_set_instance_name",
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
    "kipi_init_db",
    "kipi_insert_content_metrics",
    "kipi_insert_behavioral_signals",
    "kipi_insert_outreach",
    "kipi_insert_copy_edit",
    "kipi_query",
    "kipi_daily_metrics",
    "kipi_monthly_learnings",
    # Linter tools
    "kipi_voice_lint",
    "kipi_validate_schedule",
    "kipi_validate_ad_copy",
    "kipi_seo_check",
    "kipi_validate_cold_email",
    "kipi_copy_edit_lint",
    # Scorer tools
    "kipi_score_lead",
    "kipi_ab_test_calc",
    "kipi_churn_health_score",
    "kipi_cancel_flow_offer",
    "kipi_crack_detect",
    # Schema generator
    "kipi_generate_schema",
    # Harvest tools
    "kipi_harvest",
    "kipi_store_harvest",
    "kipi_get_harvest",
    "kipi_harvest_status",
    "kipi_harvest_summary",
    "kipi_harvest_cleanup",
    "kipi_approve_apify_budget",
    "kipi_preflight",
    "kipi_session_bootstrap",
    "kipi_canonical_digest",
    "kipi_morning_init",
    "kipi_gate_check",
    "kipi_deliverables_check",
    "kipi_harvest_health",
    "kipi_queue_notion_write",
    "kipi_get_notion_queue",
    "kipi_log_agent_metric",
    "kipi_agent_metrics",
    "kipi_session_handoff",
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


def test_loop_list_empty_when_fresh_db(tmp_path):
    """Verify loop_list returns empty list on fresh database."""
    db_path = tmp_path / "test.db"
    tracker = LoopTracker(db_path=db_path)
    tracker.init_db()

    result = tracker.list(min_level=0)
    assert result == []


def test_main_entry_point_exists():
    """Verify the main() function exists for project.scripts entry point."""
    from kipi_mcp.server import main
    assert callable(main)
