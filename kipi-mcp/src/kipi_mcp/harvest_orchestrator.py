from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from kipi_mcp.harvest_store import HarvestStore
from kipi_mcp.source_registry import SourceRegistry, SourceManifest
from kipi_mcp.executors import ExecutorResult
from kipi_mcp.executors import http_executor, apify_executor, local_executor
from kipi_mcp.executors.prompt_generator import generate_chrome_prompt, generate_mcp_prompt

logger = logging.getLogger(__name__)


@dataclass
class HarvestResult:
    run_id: str
    python_results: dict[str, dict] = field(default_factory=dict)
    chrome_agent_prompt: str | None = None
    mcp_agent_prompt: str | None = None
    skipped: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


def _record_key(record: dict) -> str:
    for k in ("url", "id", "link"):
        if k in record:
            return str(record[k])
    raw = json.dumps(record, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class HarvestOrchestrator:
    def __init__(
        self,
        store: HarvestStore,
        registry: SourceRegistry,
        apify_token: str | None = None,
    ):
        self.store = store
        self.registry = registry
        self.apify_token = apify_token

    async def harvest(
        self,
        sources: str = "all",
        mode: str = "incremental",
        methods: str = "all",
        energy_level: int | None = None,
        env: dict[str, str] | None = None,
    ) -> HarvestResult:
        env = env or {}

        # Full mode: always start fresh
        if mode == "full":
            run_info = self.store.create_run("full")
        elif mode == "resume":
            return await self._resume(sources, methods, energy_level, env)
        else:
            # Smart default: if latest run is partial/running, auto-resume
            latest = self.store.get_latest_run()
            if latest and latest.get("status") in ("partial", "running"):
                logger.info("Latest run %s is %s, auto-resuming", latest["run_id"], latest["status"])
                return await self._resume(sources, methods, energy_level, env)
            run_info = self.store.create_run("incremental")
        run_id = run_info["run_id"]

        # Build last_harvest_times for schedule filtering
        all_manifests = self.registry.load_all()
        last_harvest_times: dict[str, str] = {}
        for m in all_manifests:
            cursor = self.store.get_cursor(m.name)
            if cursor:
                last_harvest_times[m.name] = cursor["updated_at"]

        filter_method = methods if methods != "all" else None
        loaded = self.registry.load_all(
            filter_method=filter_method,
            energy_level=energy_level,
            last_harvest_times=last_harvest_times if mode == "incremental" else None,
        )

        # Filter by name
        if sources != "all":
            names = {n.strip() for n in sources.split(",")}
            loaded = [m for m in loaded if m.name in names]

        # Track skipped (sources in full manifest but filtered out by schedule)
        loaded_names = {m.name for m in loaded}
        for m in all_manifests:
            if m.name not in loaded_names and m.enabled:
                if filter_method and m.method != filter_method:
                    continue
                if sources != "all" and m.name not in {n.strip() for n in sources.split(",")}:
                    continue
                # Was filtered by schedule/skip_if_hours
                result_obj = HarvestResult(run_id=run_id)
                result_obj.skipped.append(m.name)

        # Resolve variables
        resolved: list[SourceManifest] = []
        for m in loaded:
            resolved.append(self.registry.resolve_variables(m, env))

        # Group by method
        python_sources = [m for m in resolved if m.method in ("http", "apify", "local")]
        chrome_sources = [m for m in resolved if m.method == "chrome"]
        mcp_sources = [m for m in resolved if m.method == "mcp"]

        result = HarvestResult(run_id=run_id)

        # Compute skipped from schedule filtering
        all_unfiltered = self.registry.load_all(filter_method=filter_method)
        if sources != "all":
            names_set = {n.strip() for n in sources.split(",")}
            all_unfiltered = [m for m in all_unfiltered if m.name in names_set]
        unfiltered_names = {m.name for m in all_unfiltered}
        for name in unfiltered_names:
            if name not in loaded_names:
                result.skipped.append(name)

        # Run python sources in parallel
        if python_sources:
            tasks = [
                self._execute_source(src, run_id, mode)
                for src in python_sources
            ]
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            for src, outcome in zip(python_sources, outcomes):
                if isinstance(outcome, Exception):
                    result.python_results[src.name] = {
                        "status": "error", "records": 0, "error": str(outcome),
                    }
                    result.errors[src.name] = str(outcome)
                else:
                    result.python_results[src.name] = outcome
                    if outcome.get("error"):
                        result.errors[src.name] = outcome["error"]

        # Generate chrome prompt
        if chrome_sources:
            chrome_dicts = []
            for m in chrome_sources:
                instructions = self.registry.load_chrome_instructions(m)
                d = m.model_dump(by_alias=True)
                d["chrome_instructions"] = instructions or ""
                chrome_dicts.append(d)
                sr = self.store.create_source_run(run_id, m.name, "chrome")
                self.store.update_source_run(sr["id"], status="pending",
                                             completed_at=datetime.now().isoformat())
            result.chrome_agent_prompt = generate_chrome_prompt(chrome_dicts, run_id)

        # Generate mcp prompt
        if mcp_sources:
            mcp_dicts = []
            for m in mcp_sources:
                d = m.model_dump(by_alias=True)
                mcp_dicts.append(d)
                sr = self.store.create_source_run(run_id, m.name, "mcp")
                self.store.update_source_run(sr["id"], status="pending",
                                             completed_at=datetime.now().isoformat())
            result.mcp_agent_prompt = generate_mcp_prompt(mcp_dicts, run_id)

        # Determine final status
        has_errors = bool(result.errors)
        has_pending = bool(chrome_sources or mcp_sources)
        if has_errors or has_pending:
            self.store.update_run(run_id, "partial")
        else:
            self.store.update_run(run_id, "complete")

        return result

    async def _execute_source(
        self, manifest: SourceManifest, run_id: str, mode: str,
    ) -> dict:
        sr = self.store.create_source_run(run_id, manifest.name, manifest.method)
        sr_id = sr["id"]

        cursor = None
        if mode != "full" and manifest.incremental:
            cursor_row = self.store.get_cursor(manifest.name)
            if cursor_row:
                cursor = cursor_row["cursor_value"]

        try:
            exec_result = await self._call_executor(manifest, cursor)
        except Exception as exc:
            self.store.update_source_run(
                sr_id, status="error", error=str(exc),
                completed_at=datetime.now().isoformat(),
            )
            return {"status": "error", "records": 0, "error": str(exc)}

        if exec_result.error:
            self.store.update_source_run(
                sr_id, status="error", error=exec_result.error,
                records=len(exec_result.records),
                completed_at=datetime.now().isoformat(),
            )
            return {
                "status": "error",
                "records": len(exec_result.records),
                "error": exec_result.error,
            }

        # Store records
        stored = 0
        for rec in exec_result.records:
            key = _record_key(rec)
            summary = json.dumps(rec, default=str)
            if len(summary) > 4096:
                # Trim body fields for summary
                trimmed = {k: v for k, v in rec.items() if k != "body"}
                summary = json.dumps(trimmed, default=str)[:4096]

            body_text = None
            if manifest.output.full_text and "body" in rec:
                body_text = str(rec["body"])

            cursor_val = None
            if manifest.incremental and manifest.incremental.cursor_field in rec:
                cursor_val = str(rec[manifest.incremental.cursor_field])

            result = self.store.store_record(
                run_id=run_id,
                source_name=manifest.name,
                record_key=key,
                summary_json=summary,
                body_text=body_text,
                cursor_value=cursor_val,
            )
            if result and not result.get("deduped"):
                stored += 1

        # Update cursor
        if mode == "incremental" and exec_result.cursor_after and manifest.incremental:
            self.store.set_cursor(
                manifest.name,
                exec_result.cursor_after,
                manifest.incremental.cursor_field,
            )

        self.store.update_source_run(
            sr_id,
            status="complete",
            records=stored,
            cursor_after=exec_result.cursor_after,
            completed_at=datetime.now().isoformat(),
            apify_cost=exec_result.cost,
        )

        return {"status": "complete", "records": stored}

    async def _call_executor(
        self, manifest: SourceManifest, cursor: str | None,
    ) -> ExecutorResult:
        if manifest.method == "http":
            config = manifest.http.model_dump()
            return await http_executor.execute(config, cursor=cursor)
        elif manifest.method == "apify":
            config = manifest.apify.model_dump()
            budget_fn = lambda: self.store.check_budget(datetime.now().strftime("%Y-%m"))
            return await apify_executor.execute(
                config, cursor=cursor,
                budget_check_fn=budget_fn,
                apify_token=self.apify_token,
            )
        elif manifest.method == "local":
            config = manifest.local.model_dump()
            return await asyncio.to_thread(local_executor.execute, config)
        else:
            return ExecutorResult(error=f"Unknown method: {manifest.method}")

    async def _resume(
        self,
        sources: str,
        methods: str,
        energy_level: int | None,
        env: dict[str, str],
    ) -> HarvestResult:
        latest = self.store.get_latest_run()
        if not latest:
            run_info = self.store.create_run("resume")
            self.store.update_run(run_info["run_id"], "complete")
            return HarvestResult(run_id=run_info["run_id"])

        parent_run_id = latest["run_id"]

        # Find incomplete source_runs
        conn = self.store._connect()
        try:
            rows = conn.execute(
                "SELECT source_name, status FROM source_runs WHERE run_id = ?",
                (parent_run_id,),
            ).fetchall()
        finally:
            conn.close()

        incomplete_names = {
            row["source_name"] for row in rows
            if row["status"] in ("partial", "pending", "error", "running")
        }

        if not incomplete_names:
            run_info = self.store.create_run("resume", parent_run_id=parent_run_id)
            self.store.update_run(run_info["run_id"], "complete")
            return HarvestResult(run_id=run_info["run_id"])

        run_info = self.store.create_run("resume", parent_run_id=parent_run_id)
        run_id = run_info["run_id"]

        filter_method = methods if methods != "all" else None
        loaded = self.registry.load_all(filter_method=filter_method, energy_level=energy_level)

        # Only re-run incomplete sources
        to_run = [m for m in loaded if m.name in incomplete_names]

        if sources != "all":
            names = {n.strip() for n in sources.split(",")}
            to_run = [m for m in to_run if m.name in names]

        resolved = [self.registry.resolve_variables(m, env) for m in to_run]

        python_sources = [m for m in resolved if m.method in ("http", "apify", "local")]
        chrome_sources = [m for m in resolved if m.method == "chrome"]
        mcp_sources = [m for m in resolved if m.method == "mcp"]

        result = HarvestResult(run_id=run_id)

        if python_sources:
            tasks = [self._execute_source(src, run_id, "incremental") for src in python_sources]
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            for src, outcome in zip(python_sources, outcomes):
                if isinstance(outcome, Exception):
                    result.python_results[src.name] = {
                        "status": "error", "records": 0, "error": str(outcome),
                    }
                    result.errors[src.name] = str(outcome)
                else:
                    result.python_results[src.name] = outcome
                    if outcome.get("error"):
                        result.errors[src.name] = outcome["error"]

        if chrome_sources:
            chrome_dicts = []
            for m in chrome_sources:
                instructions = self.registry.load_chrome_instructions(m)
                d = m.model_dump(by_alias=True)
                d["chrome_instructions"] = instructions or ""
                chrome_dicts.append(d)
            result.chrome_agent_prompt = generate_chrome_prompt(chrome_dicts, run_id)

        if mcp_sources:
            mcp_dicts = [m.model_dump(by_alias=True) for m in mcp_sources]
            result.mcp_agent_prompt = generate_mcp_prompt(mcp_dicts, run_id)

        has_errors = bool(result.errors)
        has_pending = bool(chrome_sources or mcp_sources)
        if has_errors or has_pending:
            self.store.update_run(run_id, "partial")
        else:
            self.store.update_run(run_id, "complete")

        return result
