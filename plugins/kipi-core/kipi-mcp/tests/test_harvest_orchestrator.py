from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from kipi_mcp.executors import ExecutorResult
from kipi_mcp.harvest_store import HarvestStore
from kipi_mcp.source_registry import SourceRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.dump(data, default_flow_style=False))
    return path


def _http_source(name: str = "test-http", **overrides) -> dict:
    d = {
        "name": name,
        "method": "http",
        "http": {
            "url": "https://api.example.com/data",
            "verb": "GET",
            "headers": {},
            "records_path": ["items"],
        },
        "schedule": {"frequency": "daily"},
        "incremental": {"cursor_field": "updated_at", "state_key": name},
        "output": {"full_text": False},
    }
    d.update(overrides)
    return d


def _local_source(name: str = "test-local", file_path: str = "/tmp/data.json") -> dict:
    return {
        "name": name,
        "method": "local",
        "local": {"file_path": file_path, "format": "json"},
        "schedule": {"frequency": "daily"},
    }


def _apify_source(name: str = "test-apify") -> dict:
    return {
        "name": name,
        "method": "apify",
        "apify": {
            "actor_id": "apify/test-actor",
            "input": {},
            "records_path": [],
        },
        "schedule": {"frequency": "daily"},
    }


def _chrome_source(name: str = "test-chrome") -> dict:
    return {
        "name": name,
        "method": "chrome",
        "chrome": {
            "actions_file": "test-chrome.md",
            "throttle_ms": 3000,
            "max_pages": 1,
        },
        "schedule": {"frequency": "daily"},
        "output": {"schema": {"title": "str", "url": "str"}},
    }


def _mcp_source(name: str = "test-mcp") -> dict:
    return {
        "name": name,
        "method": "mcp",
        "mcp": {
            "server": "notion",
            "tool": "query_database",
            "calls": [{"database_id": "abc123"}],
        },
        "schedule": {"frequency": "daily"},
        "output": {"schema": {"name": "str"}},
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = HarvestStore(db_path=tmp_path / "test.db")
    s.init_db()
    return s


@pytest.fixture
def sources_dir(tmp_path):
    d = tmp_path / "sources"
    d.mkdir()
    (d / "chrome").mkdir()
    return d


@pytest.fixture
def registry(sources_dir):
    return SourceRegistry(plugin_sources_dir=sources_dir)


def _make_orchestrator(store, sources_dir, extra_yamls=None, apify_token=None):
    from kipi_mcp.harvest_orchestrator import HarvestOrchestrator

    if extra_yamls:
        for name, data in extra_yamls.items():
            _write_yaml(sources_dir / f"{name}.yaml", data)

    reg = SourceRegistry(plugin_sources_dir=sources_dir)
    return HarvestOrchestrator(store=store, registry=reg, apify_token=apify_token)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFullHarvestPythonSources:
    @pytest.mark.asyncio
    async def test_full_harvest_python_sources(self, store, sources_dir):
        orch = _make_orchestrator(store, sources_dir, {
            "http1": _http_source("src-http"),
            "local1": _local_source("src-local"),
        })

        http_result = ExecutorResult(
            records=[{"id": "r1", "title": "Post A"}, {"id": "r2", "title": "Post B"}],
            cursor_after="cursor-abc",
        )
        local_result = ExecutorResult(
            records=[{"id": "r3", "value": "local data"}],
        )

        with patch("kipi_mcp.harvest_orchestrator.http_executor") as mock_http, \
             patch("kipi_mcp.harvest_orchestrator.local_executor") as mock_local:
            mock_http.execute = AsyncMock(return_value=http_result)
            mock_local.execute = MagicMock(return_value=local_result)

            result = await orch.harvest(mode="full")

        assert result.run_id is not None
        assert "src-http" in result.python_results
        assert "src-local" in result.python_results
        assert result.python_results["src-http"]["records"] == 2
        assert result.python_results["src-local"]["records"] == 1

        # Records persisted in DB
        recs = store.get_records("src-http", days=1)
        assert len(recs) == 2
        recs_local = store.get_records("src-local", days=1)
        assert len(recs_local) == 1

        # Run completed
        run = store.get_run(result.run_id)
        assert run["status"] == "complete"


class TestIncrementalUsesCursors:
    @pytest.mark.asyncio
    async def test_incremental_uses_cursors(self, store, sources_dir):
        store.set_cursor("src-http", "old-cursor-val", "updated_at")

        orch = _make_orchestrator(store, sources_dir, {
            "http1": _http_source("src-http"),
        })

        http_result = ExecutorResult(records=[{"id": "x"}], cursor_after="new-cursor")

        with patch("kipi_mcp.harvest_orchestrator.http_executor") as mock_http:
            mock_http.execute = AsyncMock(return_value=http_result)
            await orch.harvest(mode="incremental")
            mock_http.execute.assert_awaited_once()
            call_args = mock_http.execute.call_args
            assert call_args[1].get("cursor") == "old-cursor-val" or \
                   (len(call_args[0]) > 1 and call_args[0][1] == "old-cursor-val")


class TestFullModeIgnoresCursors:
    @pytest.mark.asyncio
    async def test_full_mode_ignores_cursors(self, store, sources_dir):
        store.set_cursor("src-http", "existing-cursor", "updated_at")

        orch = _make_orchestrator(store, sources_dir, {
            "http1": _http_source("src-http"),
        })

        http_result = ExecutorResult(records=[{"id": "x"}])

        with patch("kipi_mcp.harvest_orchestrator.http_executor") as mock_http:
            mock_http.execute = AsyncMock(return_value=http_result)
            await orch.harvest(mode="full")
            call_args = mock_http.execute.call_args
            cursor_val = call_args[1].get("cursor") if "cursor" in (call_args[1] or {}) else call_args[0][1] if len(call_args[0]) > 1 else None
            assert cursor_val is None


class TestResumeContinuesPartialRun:
    @pytest.mark.asyncio
    async def test_resume_continues_partial_run(self, store, sources_dir):
        orch = _make_orchestrator(store, sources_dir, {
            "http1": _http_source("src-a"),
            "http2": _http_source("src-b"),
        })

        # Create a prior run with src-a complete and src-b partial
        run = store.create_run("incremental")
        sr_a = store.create_source_run(run["run_id"], "src-a", "http")
        store.update_source_run(sr_a["id"], status="complete", records=5,
                                completed_at=datetime.now().isoformat())
        sr_b = store.create_source_run(run["run_id"], "src-b", "http")
        store.update_source_run(sr_b["id"], status="partial",
                                completed_at=datetime.now().isoformat())
        store.update_run(run["run_id"], "partial")

        http_result = ExecutorResult(records=[{"id": "z"}], cursor_after="c1")

        with patch("kipi_mcp.harvest_orchestrator.http_executor") as mock_http:
            mock_http.execute = AsyncMock(return_value=http_result)
            result = await orch.harvest(mode="resume")

        # Only src-b should have been re-run
        assert "src-b" in result.python_results
        assert "src-a" not in result.python_results


class TestSkipIfRecent:
    @pytest.mark.asyncio
    async def test_skip_if_recent(self, store, sources_dir):
        src = _http_source("src-recent")
        src["schedule"]["skip_if_hours"] = 20

        orch = _make_orchestrator(store, sources_dir, {"http1": src})

        recent = (datetime.now() - timedelta(hours=5)).isoformat()
        store.set_cursor("src-recent", "val", "updated_at")
        # Manually update the cursor updated_at to be recent
        conn = store._connect()
        try:
            conn.execute(
                "UPDATE source_cursors SET updated_at = ? WHERE source_name = ?",
                (recent, "src-recent"),
            )
            conn.commit()
        finally:
            conn.close()

        with patch("kipi_mcp.harvest_orchestrator.http_executor") as mock_http:
            mock_http.execute = AsyncMock(return_value=ExecutorResult(records=[]))
            result = await orch.harvest(mode="incremental")

        assert "src-recent" in result.skipped


class TestBudgetBlocksApify:
    @pytest.mark.asyncio
    async def test_budget_blocks_apify(self, store, sources_dir):
        orch = _make_orchestrator(store, sources_dir, {
            "apify1": _apify_source("src-apify"),
        }, apify_token="tok_test")

        # Set budget to exhausted
        month = datetime.now().strftime("%Y-%m")
        store.record_spend(month, 10.0)

        with patch("kipi_mcp.harvest_orchestrator.apify_executor") as mock_apify:
            mock_apify.execute = AsyncMock(
                return_value=ExecutorResult(error="budget_exceeded")
            )
            result = await orch.harvest(mode="full")

        assert "src-apify" in result.errors


class TestPartialFailureContinuesOthers:
    @pytest.mark.asyncio
    async def test_partial_failure_continues_others(self, store, sources_dir):
        orch = _make_orchestrator(store, sources_dir, {
            "http1": _http_source("src-ok"),
            "http2": _http_source("src-fail"),
        })

        ok_result = ExecutorResult(records=[{"id": "1"}])
        fail_result = ExecutorResult(records=[], error="connection refused")

        with patch("kipi_mcp.harvest_orchestrator.http_executor") as mock_http:
            async def route_execute(config, cursor=None):
                url = config.get("url", "")
                # Both use same URL, differentiate by call order
                return fail_result if route_execute.call_count % 2 == 0 else ok_result
            route_execute.call_count = 0

            async def side_effect(config, cursor=None):
                route_execute.call_count += 1
                return await route_execute(config, cursor)

            # Simpler: just map by source name via the orchestrator internals
            call_count = {"n": 0}

            async def ordered_results(config, cursor=None):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return ok_result
                return fail_result

            mock_http.execute = AsyncMock(side_effect=ordered_results)
            result = await orch.harvest(mode="full")

        run = store.get_run(result.run_id)
        assert run["status"] == "partial"
        assert len(result.errors) >= 1


class TestRunStatePersisted:
    @pytest.mark.asyncio
    async def test_run_state_persisted(self, store, sources_dir):
        orch = _make_orchestrator(store, sources_dir, {
            "http1": _http_source("src-state"),
        })

        with patch("kipi_mcp.harvest_orchestrator.http_executor") as mock_http:
            mock_http.execute = AsyncMock(
                return_value=ExecutorResult(records=[{"id": "s1"}])
            )
            result = await orch.harvest(mode="full")

        run = store.get_run(result.run_id)
        assert run is not None
        assert run["mode"] == "full"
        assert run["status"] == "complete"
        assert run["completed_at"] is not None

        # source_run rows
        conn = store._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM source_runs WHERE run_id = ?", (result.run_id,)
            ).fetchall()
            assert len(rows) == 1
            sr = dict(rows[0])
            assert sr["source_name"] == "src-state"
            assert sr["method"] == "http"
            assert sr["status"] == "complete"
            assert sr["records"] == 1
        finally:
            conn.close()


class TestChromePromptGenerated:
    @pytest.mark.asyncio
    async def test_chrome_prompt_generated(self, store, sources_dir):
        # Write chrome instructions file
        (sources_dir / "chrome" / "test-chrome.md").write_text("Navigate to site. Extract posts.")

        orch = _make_orchestrator(store, sources_dir, {
            "chrome1": _chrome_source("src-chrome"),
        })

        result = await orch.harvest(mode="full")

        assert result.chrome_agent_prompt is not None
        assert "src-chrome" in result.chrome_agent_prompt
        assert "Navigate to site" in result.chrome_agent_prompt


class TestMcpPromptGenerated:
    @pytest.mark.asyncio
    async def test_mcp_prompt_generated(self, store, sources_dir):
        orch = _make_orchestrator(store, sources_dir, {
            "mcp1": _mcp_source("src-mcp"),
        })

        result = await orch.harvest(mode="full")

        assert result.mcp_agent_prompt is not None
        assert "src-mcp" in result.mcp_agent_prompt
        assert "notion" in result.mcp_agent_prompt


class TestFilterByMethod:
    @pytest.mark.asyncio
    async def test_filter_by_method(self, store, sources_dir):
        orch = _make_orchestrator(store, sources_dir, {
            "http1": _http_source("src-http"),
            "local1": _local_source("src-local"),
            "apify1": _apify_source("src-apify"),
        })

        with patch("kipi_mcp.harvest_orchestrator.http_executor") as mock_http:
            mock_http.execute = AsyncMock(
                return_value=ExecutorResult(records=[{"id": "1"}])
            )
            result = await orch.harvest(mode="full", methods="http")

        assert "src-http" in result.python_results
        assert "src-local" not in result.python_results
        assert "src-apify" not in result.python_results
