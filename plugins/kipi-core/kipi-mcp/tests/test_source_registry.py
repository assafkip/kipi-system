from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from kipi_mcp.source_registry import (
    ApifyConfig,
    ChromeConfig,
    HttpConfig,
    LocalConfig,
    McpConfig,
    SourceManifest,
    SourceRegistry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.dump(data, default_flow_style=False))
    return path


def _http_yaml() -> dict:
    return {
        "name": "linkedin-metrics",
        "method": "http",
        "http": {
            "url": "https://api.example.com/metrics",
            "verb": "GET",
            "headers": {"Authorization": "Bearer ${API_TOKEN}"},
            "records_path": ["data", "posts"],
        },
        "schedule": {"frequency": "daily"},
    }


def _apify_yaml() -> dict:
    return {
        "name": "x-scraper",
        "method": "apify",
        "apify": {
            "actor_id": "apify/twitter-scraper",
            "input": {"searchTerms": ["#marketing"]},
            "records_path": ["items"],
        },
    }


def _mcp_yaml() -> dict:
    return {
        "name": "notion-contacts",
        "method": "mcp",
        "mcp": {
            "server": "notion",
            "tool": "query_database",
            "calls": [{"database_id": "abc123"}],
        },
    }


def _chrome_yaml() -> dict:
    return {
        "name": "linkedin-feed",
        "method": "chrome",
        "chrome": {
            "actions_file": "linkedin-feed.md",
            "throttle_ms": 5000,
            "max_pages": 3,
        },
    }


def _local_yaml() -> dict:
    return {
        "name": "lead-list",
        "method": "local",
        "local": {
            "file_path": "${DATA_DIR}/leads.json",
            "format": "json",
        },
    }


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------

class TestModelValidation:
    def test_load_http_source(self, tmp_path):
        data = _http_yaml()
        _write_yaml(tmp_path / "http.yaml", data)
        raw = yaml.safe_load((tmp_path / "http.yaml").read_text())
        m = SourceManifest(**raw)
        assert m.name == "linkedin-metrics"
        assert m.method == "http"
        assert isinstance(m.http, HttpConfig)
        assert m.http.url == "https://api.example.com/metrics"
        assert m.http.verb == "GET"
        assert m.http.records_path == ["data", "posts"]

    def test_load_apify_source(self, tmp_path):
        data = _apify_yaml()
        _write_yaml(tmp_path / "apify.yaml", data)
        raw = yaml.safe_load((tmp_path / "apify.yaml").read_text())
        m = SourceManifest(**raw)
        assert m.method == "apify"
        assert isinstance(m.apify, ApifyConfig)
        assert m.apify.actor_id == "apify/twitter-scraper"

    def test_load_mcp_source(self, tmp_path):
        data = _mcp_yaml()
        _write_yaml(tmp_path / "mcp.yaml", data)
        raw = yaml.safe_load((tmp_path / "mcp.yaml").read_text())
        m = SourceManifest(**raw)
        assert m.method == "mcp"
        assert isinstance(m.mcp, McpConfig)
        assert m.mcp.server == "notion"
        assert m.mcp.tool == "query_database"

    def test_load_chrome_source(self, tmp_path):
        data = _chrome_yaml()
        _write_yaml(tmp_path / "chrome.yaml", data)
        raw = yaml.safe_load((tmp_path / "chrome.yaml").read_text())
        m = SourceManifest(**raw)
        assert m.method == "chrome"
        assert isinstance(m.chrome, ChromeConfig)
        assert m.chrome.actions_file == "linkedin-feed.md"
        assert m.chrome.throttle_ms == 5000
        assert m.chrome.max_pages == 3

    def test_load_local_source(self, tmp_path):
        data = _local_yaml()
        _write_yaml(tmp_path / "local.yaml", data)
        raw = yaml.safe_load((tmp_path / "local.yaml").read_text())
        m = SourceManifest(**raw)
        assert m.method == "local"
        assert isinstance(m.local, LocalConfig)
        assert m.local.file_path == "${DATA_DIR}/leads.json"
        assert m.local.format == "json"

    def test_invalid_source_fails_validation(self):
        """Config block missing for declared method raises ValidationError."""
        with pytest.raises(ValidationError):
            SourceManifest(name="bad", method="http")  # no http block

    def test_missing_required_fields(self):
        """Both name and method are required."""
        with pytest.raises(ValidationError):
            SourceManifest(method="http", http={"url": "https://x.com"})
        with pytest.raises(ValidationError):
            SourceManifest(name="no-method")

    def test_unknown_method_rejected(self):
        with pytest.raises(ValidationError):
            SourceManifest(
                name="ftp-source",
                method="ftp",
            )


# ---------------------------------------------------------------------------
# Chrome .md loading
# ---------------------------------------------------------------------------

class TestChromeMarkdown:
    def test_chrome_source_loads_md_file(self, tmp_sources_dir):
        md_content = "# LinkedIn Feed\n1. Open feed\n2. Scroll down\n3. Extract posts"
        (tmp_sources_dir / "chrome" / "linkedin-feed.md").write_text(md_content)

        data = _chrome_yaml()
        _write_yaml(tmp_sources_dir / "linkedin-feed.yaml", data)

        registry = SourceRegistry(plugin_sources_dir=tmp_sources_dir)
        m = SourceManifest(**data)
        result = registry.load_chrome_instructions(m)
        assert result == md_content


# ---------------------------------------------------------------------------
# Schedule filtering
# ---------------------------------------------------------------------------

class TestScheduleFilter:
    def test_schedule_filter_daily(self):
        m = SourceManifest(**_http_yaml())
        assert m.schedule.frequency == "daily"
        # daily passes on any day
        data_mon = _http_yaml()
        data_mon["schedule"] = {"frequency": "daily"}
        m2 = SourceManifest(**data_mon)
        # Verify via load_all with filter_schedule
        # We test the internal logic: daily always matches
        from kipi_mcp.source_registry import ScheduleConfig, _matches_schedule
        sched = ScheduleConfig(frequency="daily")
        assert _matches_schedule(sched, "monday", None) is True
        assert _matches_schedule(sched, "friday", None) is True
        assert _matches_schedule(sched, "saturday", None) is True

    def test_schedule_filter_monday(self):
        from kipi_mcp.source_registry import ScheduleConfig, _matches_schedule
        sched = ScheduleConfig(frequency="monday")
        assert _matches_schedule(sched, "monday", None) is True
        assert _matches_schedule(sched, "tuesday", None) is False
        assert _matches_schedule(sched, "sunday", None) is False

    def test_skip_if_hours_logic(self):
        from kipi_mcp.source_registry import ScheduleConfig, _matches_schedule
        sched = ScheduleConfig(frequency="daily", skip_if_hours=20)

        recent = (datetime.now() - timedelta(hours=10)).isoformat()
        assert _matches_schedule(sched, "monday", recent) is False

        old = (datetime.now() - timedelta(hours=25)).isoformat()
        assert _matches_schedule(sched, "monday", old) is True


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------

class TestRegistryLoading:
    def test_instance_override_wins(self, tmp_path):
        plugin_dir = tmp_path / "plugin_sources"
        plugin_dir.mkdir()
        (plugin_dir / "chrome").mkdir()
        instance_dir = tmp_path / "instance_sources"
        instance_dir.mkdir()
        (instance_dir / "chrome").mkdir()

        plugin_data = _http_yaml()
        plugin_data["schedule"] = {"frequency": "daily"}
        _write_yaml(plugin_dir / "linkedin.yaml", plugin_data)

        instance_data = _http_yaml()
        instance_data["schedule"] = {"frequency": "monday"}
        _write_yaml(instance_dir / "linkedin.yaml", instance_data)

        registry = SourceRegistry(
            plugin_sources_dir=plugin_dir,
            instance_sources_dir=instance_dir,
        )
        sources = registry.load_all()
        assert len(sources) == 1
        assert sources[0].schedule.frequency == "monday"

    def test_disabled_source_excluded(self, tmp_sources_dir):
        data = _http_yaml()
        data["enabled"] = False
        _write_yaml(tmp_sources_dir / "disabled.yaml", data)
        _write_yaml(tmp_sources_dir / "active.yaml", _apify_yaml())

        registry = SourceRegistry(plugin_sources_dir=tmp_sources_dir)
        sources = registry.load_all()
        assert len(sources) == 1
        assert sources[0].name == "x-scraper"

    def test_last_harvest_times_skip(self, tmp_sources_dir):
        """load_all with last_harvest_times skips recently-harvested sources."""
        data = _http_yaml()
        data["schedule"] = {"frequency": "daily", "skip_if_hours": 20}
        _write_yaml(tmp_sources_dir / "http.yaml", data)

        registry = SourceRegistry(plugin_sources_dir=tmp_sources_dir)

        recent = (datetime.now() - timedelta(hours=5)).isoformat()
        sources = registry.load_all(last_harvest_times={"linkedin-metrics": recent})
        assert len(sources) == 0

        old = (datetime.now() - timedelta(hours=25)).isoformat()
        sources = registry.load_all(last_harvest_times={"linkedin-metrics": old})
        assert len(sources) == 1


# ---------------------------------------------------------------------------
# Variable resolution
# ---------------------------------------------------------------------------

class TestVariableResolution:
    def test_variable_resolution(self, tmp_sources_dir):
        data = _local_yaml()
        registry = SourceRegistry(plugin_sources_dir=tmp_sources_dir)
        m = SourceManifest(**data)
        resolved = registry.resolve_variables(m, env={"DATA_DIR": "/opt/data"})
        assert resolved.local.file_path == "/opt/data/leads.json"

    def test_variable_resolution_env(self, tmp_sources_dir):
        data = _apify_yaml()
        data["apify"]["input"]["token"] = "${APIFY_TOKEN}"

        registry = SourceRegistry(plugin_sources_dir=tmp_sources_dir)
        m = SourceManifest(**data)
        resolved = registry.resolve_variables(m, env={"APIFY_TOKEN": "tok_abc123"})
        assert resolved.apify.input["token"] == "tok_abc123"

    def test_unresolved_variable_replaced_empty(self, tmp_sources_dir):
        data = _http_yaml()
        registry = SourceRegistry(plugin_sources_dir=tmp_sources_dir)
        m = SourceManifest(**data)
        resolved = registry.resolve_variables(m, env={})
        assert resolved.http.headers["Authorization"] == "Bearer "


# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------

class TestSchemaVersioning:
    def test_schema_version_defaults_to_1(self):
        data = _http_yaml()
        m = SourceManifest(**data)
        assert m.schema_version == 1
        assert m.version_mismatch is False

    def test_version_mismatch_flagged(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()

        plugin_data = _http_yaml()
        plugin_data["schema_version"] = 2
        _write_yaml(plugin_dir / "linkedin.yaml", plugin_data)

        instance_data = _http_yaml()
        instance_data["schema_version"] = 1
        _write_yaml(instance_dir / "linkedin.yaml", instance_data)

        registry = SourceRegistry(
            plugin_sources_dir=plugin_dir,
            instance_sources_dir=instance_dir,
        )
        sources = registry.load_all()
        assert len(sources) == 1
        assert sources[0].version_mismatch is True

    def test_same_version_no_flag(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()

        plugin_data = _http_yaml()
        plugin_data["schema_version"] = 1
        _write_yaml(plugin_dir / "linkedin.yaml", plugin_data)

        instance_data = _http_yaml()
        instance_data["schema_version"] = 1
        instance_data["schedule"] = {"frequency": "monday"}
        _write_yaml(instance_dir / "linkedin.yaml", instance_data)

        registry = SourceRegistry(
            plugin_sources_dir=plugin_dir,
            instance_sources_dir=instance_dir,
        )
        sources = registry.load_all()
        assert len(sources) == 1
        assert sources[0].version_mismatch is False
        assert sources[0].schedule.frequency == "monday"
