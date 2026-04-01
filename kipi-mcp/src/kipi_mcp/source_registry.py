from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

log = logging.getLogger(__name__)

_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday"}
_VALID_METHODS = {"http", "apify", "mcp", "chrome", "local"}


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------

class HttpConfig(BaseModel):
    url: str
    verb: str = "GET"
    headers: dict[str, str] = {}
    body_template: dict | None = None
    records_path: list[str] = []
    pagination: dict | None = None
    is_rss: bool = False
    is_ga4: bool = False


class ApifyConfig(BaseModel):
    actor_id: str
    input: dict = {}
    records_path: list[str] = []


class McpConfig(BaseModel):
    server: str
    tool: str
    calls: list[dict] = []


class ChromeConfig(BaseModel):
    actions_file: str
    throttle_ms: int = 3000
    max_pages: int = 1


class LocalConfig(BaseModel):
    file_path: str
    format: str = "json"


class ScheduleConfig(BaseModel):
    frequency: str = "daily"
    skip_if_hours: int | None = None
    energy_gate: int | None = None


class IncrementalConfig(BaseModel):
    cursor_field: str
    state_key: str


class PersistConfig(BaseModel):
    method: str


class OutputConfig(BaseModel):
    model_config = {"populate_by_name": True}
    full_text: bool = False
    schema_def: dict = Field(default={}, alias="schema")


class SourceManifest(BaseModel):
    name: str
    enabled: bool = True
    schema_version: int = 1
    version_mismatch: bool = False
    method: str

    http: HttpConfig | None = None
    apify: ApifyConfig | None = None
    mcp: McpConfig | None = None
    chrome: ChromeConfig | None = None
    local: LocalConfig | None = None

    schedule: ScheduleConfig = ScheduleConfig()
    incremental: IncrementalConfig | None = None
    output: OutputConfig = OutputConfig()
    persist: PersistConfig | None = None
    on_error: str = "skip"

    @model_validator(mode="after")
    def _check_config_block(self):
        if self.method not in _VALID_METHODS:
            raise ValueError(f"Unknown method: {self.method!r}. Must be one of {_VALID_METHODS}")
        block = getattr(self, self.method)
        if block is None:
            raise ValueError(f"Method is {self.method!r} but the {self.method} config block is missing")
        return self


# ---------------------------------------------------------------------------
# Schedule matching
# ---------------------------------------------------------------------------

def _matches_schedule(
    schedule: ScheduleConfig,
    today: str,
    last_cursor_time: str | None,
) -> bool:
    freq = schedule.frequency.lower()

    if freq == "on_demand":
        return False
    if freq == "weekdays":
        if today.lower() not in _WEEKDAYS:
            return False
    elif freq != "daily":
        if today.lower() != freq:
            return False

    if schedule.skip_if_hours is not None and last_cursor_time:
        last_dt = datetime.fromisoformat(last_cursor_time)
        hours_ago = (datetime.now() - last_dt).total_seconds() / 3600
        if hours_ago < schedule.skip_if_hours:
            return False

    return True


# ---------------------------------------------------------------------------
# Variable resolution
# ---------------------------------------------------------------------------

_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _resolve_obj(obj, env: dict):
    if isinstance(obj, str):
        def replacer(m: re.Match) -> str:
            return env.get(m.group(1), "")
        return _VAR_RE.sub(replacer, obj)
    if isinstance(obj, dict):
        return {k: _resolve_obj(v, env) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_obj(item, env) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class SourceRegistry:
    def __init__(
        self,
        plugin_sources_dir: Path,
        instance_sources_dir: Path | None = None,
    ):
        self.plugin_dir = plugin_sources_dir
        self.instance_dir = instance_sources_dir

    def _load_yamls_raw(self, directory: Path) -> dict[str, dict]:
        raw_map: dict[str, dict] = {}
        if not directory.exists():
            return raw_map
        for fp in sorted(directory.glob("*.yaml")):
            try:
                raw = yaml.safe_load(fp.read_text())
                if raw is None:
                    continue
                raw_map[raw["name"]] = raw
            except Exception:
                log.warning("Failed to load source manifest: %s", fp, exc_info=True)
        return raw_map

    def _load_yamls(self, directory: Path) -> dict[str, SourceManifest]:
        manifests: dict[str, SourceManifest] = {}
        for name, raw in self._load_yamls_raw(directory).items():
            try:
                manifests[name] = SourceManifest(**raw)
            except Exception:
                log.warning("Failed to parse source manifest: %s", name, exc_info=True)
        return manifests

    def load_all(
        self,
        filter_method: str | None = None,
        filter_schedule: str | None = None,
        energy_level: int | None = None,
        last_harvest_times: dict[str, str] | None = None,
    ) -> list[SourceManifest]:
        plugin_raw = self._load_yamls_raw(self.plugin_dir)
        manifests: dict[str, SourceManifest] = {}
        for name, raw in plugin_raw.items():
            try:
                manifests[name] = SourceManifest(**raw)
            except Exception:
                log.warning("Failed to parse source manifest: %s", name, exc_info=True)

        if self.instance_dir:
            instance_raw = self._load_yamls_raw(self.instance_dir)
            for name, raw in instance_raw.items():
                try:
                    m = SourceManifest(**raw)
                    if name in plugin_raw:
                        plugin_ver = plugin_raw[name].get("schema_version", 1)
                        instance_ver = raw.get("schema_version", 1)
                        if plugin_ver != instance_ver:
                            log.warning(
                                "Source %s: instance override has schema_version %d, "
                                "plugin default has %d. Review your customization.",
                                name, instance_ver, plugin_ver,
                            )
                            m.version_mismatch = True
                    manifests[name] = m
                except Exception:
                    log.warning("Failed to parse source manifest: %s", name, exc_info=True)

        results: list[SourceManifest] = []
        for m in manifests.values():
            if not m.enabled:
                continue
            if filter_method and m.method != filter_method:
                continue

            last_time = (last_harvest_times or {}).get(m.name)
            if filter_schedule:
                if not _matches_schedule(m.schedule, filter_schedule, last_time):
                    continue
            elif last_time and m.schedule.skip_if_hours is not None:
                sched_check = ScheduleConfig(
                    frequency="daily",
                    skip_if_hours=m.schedule.skip_if_hours,
                )
                if not _matches_schedule(sched_check, "daily", last_time):
                    continue

            if energy_level is not None and m.schedule.energy_gate is not None:
                if energy_level < m.schedule.energy_gate:
                    continue
            results.append(m)
        return results

    def resolve_variables(self, manifest: SourceManifest, env: dict[str, str]) -> SourceManifest:
        data = manifest.model_dump(by_alias=True)
        resolved = _resolve_obj(data, env)
        return SourceManifest(**resolved)

    def load_chrome_instructions(self, manifest: SourceManifest) -> str | None:
        if manifest.chrome is None:
            return None
        md_path = self.plugin_dir / "chrome" / manifest.chrome.actions_file
        if self.instance_dir:
            override = self.instance_dir / "chrome" / manifest.chrome.actions_file
            if override.exists():
                md_path = override
        if not md_path.exists():
            return None
        return md_path.read_text()
