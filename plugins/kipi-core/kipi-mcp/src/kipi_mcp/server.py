import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

from kipi_mcp.paths import KipiPaths, generate_instance_name
from kipi_mcp.registry import RegistryManager
from kipi_mcp.step_logger import StepLogger
from kipi_mcp.loop_tracker import LoopTracker
from kipi_mcp.template_manager import TemplateManager
from kipi_mcp.backup import BackupManager
from kipi_mcp.schedule_verifier import ScheduleVerifier
from kipi_mcp.bus_verifier import BusVerifier
from kipi_mcp.orchestrator_verifier import OrchestratorVerifier
from kipi_mcp.bus_bridge import BusBridge
from kipi_mcp.draft_scanner import DraftScanner
from kipi_mcp.morning_auditor import MorningAuditor
from kipi_mcp.metrics_store import MetricsStore
from kipi_mcp.linter import Linter
from kipi_mcp.scorer import Scorer
from kipi_mcp.schema_gen import SchemaGenerator
from kipi_mcp.harvest_store import HarvestStore
from kipi_mcp.source_registry import SourceRegistry

paths = KipiPaths()
paths.ensure_dirs()

mcp = FastMCP(
    "kipi",
    instructions=(
        "Kipi founder OS — instance management, morning routine logging, "
        "follow-up loop tracking, content/schedule tools, and deterministic linters/scorers. "
        "Tool groups: kipi_* (instances, validation, linting, scoring, schema), "
        "log_* (morning routine step logging), "
        "loop_* (follow-up loop tracking), "
        "kipi_build_schedule / kipi_create_template (content). "
        "kipi_voice_lint / kipi_copy_edit_lint / kipi_validate_* (deterministic text validation). "
        "kipi_score_lead / kipi_ab_test_calc / kipi_churn_health_score / kipi_cancel_flow_offer / kipi_crack_detect (scoring). "
        "kipi_generate_schema (JSON-LD structured data). "
        "kipi_backup / kipi_export / kipi_import (data portability). "
        "Resources: kipi://paths, kipi://status, kipi://instances, kipi://loops/open, "
        "kipi://loops/stats, kipi://backups. "
        "Read kipi://paths for resolved directory paths."
    ),
)

# --- Service instantiation ---

registry = RegistryManager(paths.registry_path)

step_logger = StepLogger(output_dir=paths.output_dir)

loop_tracker = LoopTracker(
    db_path=paths.system_db,
    legacy_json_path=paths.output_dir / "open-loops.json",
)
loop_tracker.init_db()

# Migrate loops from old metrics.db to system.db if needed
if paths.metrics_db.exists() and paths.system_db != paths.metrics_db:
    try:
        import sqlite3 as _sql
        _old = _sql.connect(str(paths.metrics_db))
        _tables = [r[0] for r in _old.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "loops" in _tables:
            _rows = _old.execute("SELECT * FROM loops").fetchall()
            if _rows:
                _ALLOWED_LOOP_COLS = {
                    "id", "type", "target", "target_notion_id", "opened",
                    "opened_by", "action_card_id", "context", "channel",
                    "touch_count", "follow_up_text", "escalation_level",
                    "last_escalated", "status", "closed", "closed_by", "closed_reason",
                }
                _raw_cols = [d[0] for d in _old.execute("SELECT * FROM loops LIMIT 1").description]
                _cols = [c for c in _raw_cols if c in _ALLOWED_LOOP_COLS]
                _col_indices = [i for i, c in enumerate(_raw_cols) if c in _ALLOWED_LOOP_COLS]
                _new = _sql.connect(str(paths.system_db))
                for _r in _rows:
                    _vals = tuple(_r[i] for i in _col_indices)
                    _placeholders = ",".join("?" * len(_cols))
                    _new.execute(f"INSERT OR IGNORE INTO loops ({','.join(_cols)}) VALUES ({_placeholders})", _vals)
                _new.commit()
                _new.close()
                _old.execute("DROP TABLE loops")
                _old.commit()
                logger.info("Migrated %d loops from metrics.db to system.db", len(_rows))
        _old.close()
    except Exception as _e:
        logger.warning("Loop migration from metrics.db failed: %s", _e)

schedule_verifier = ScheduleVerifier()

template_manager = TemplateManager(
    templates_dir=paths.templates_dir,
    output_dir=paths.output_dir,
    schedule_template=paths.schedule_template,
    verify_schedule_fn=schedule_verifier.verify,
)

backup_manager = BackupManager(paths)

bus_verifier = BusVerifier(bus_dir=paths.bus_dir)
orchestrator_verifier = OrchestratorVerifier(
    output_dir=paths.output_dir, bus_dir=paths.bus_dir, step_logger=step_logger,
)
bus_bridge = BusBridge(bus_dir=paths.bus_dir, output_dir=paths.output_dir)
draft_scanner = DraftScanner()
morning_auditor = MorningAuditor()
metrics_store = MetricsStore(db_path=paths.metrics_db)
metrics_store.init_db()

linter = Linter()
scorer = Scorer()
schema_generator = SchemaGenerator()

harvest_store = HarvestStore(db_path=paths.harvest_db)
harvest_store.init_db()

source_registry = SourceRegistry(
    plugin_sources_dir=paths.sources_dir,
    instance_sources_dir=paths.instance_sources_dir,
)

try:
    from kipi_mcp.validator import Validator
    validator = Validator(paths=paths, registry=registry)
except ImportError:
    validator = None
    logger.info("Validator module not available, kipi_validate tool will be disabled")


# ============================================================
# Resources (read-only data)
# ============================================================


@mcp.resource("kipi://paths")
def resource_paths() -> str:
    """All resolved kipi directory paths (config, data, state, repo)."""
    return json.dumps({
        "instance": paths.instance,
        "config_dir": str(paths.config_dir),
        "data_dir": str(paths.data_dir),
        "state_dir": str(paths.state_dir),
        "global_dir": str(paths.global_dir),
        "repo_dir": str(paths.repo_dir),
    })


@mcp.resource("kipi://status")
def resource_status() -> str:
    """System status: setup state, data health."""
    profile = paths.founder_profile
    setup_needed = True
    if profile.exists():
        setup_needed = "{{SETUP_NEEDED}}" in profile.read_text()

    legacy = False
    old_profile = paths.repo_dir / "q-system" / "my-project" / "founder-profile.md"
    if old_profile.exists():
        legacy = "{{SETUP_NEEDED}}" not in old_profile.read_text()

    return json.dumps({
        "legacy_data_detected": legacy,
        "setup_needed": setup_needed,
        "instance_name": paths.instance,
        "plugin_mode": bool(os.environ.get("KIPI_PLUGIN_DATA")),
        "config_dir_exists": paths.config_dir.exists(),
        "data_dir_exists": paths.data_dir.exists(),
        "state_dir_exists": paths.state_dir.exists(),
    })


@mcp.resource("kipi://instances")
def resource_instances() -> str:
    """All kipi instances, excluded projects, and eliminated projects."""
    return json.dumps({
        "instances": registry.list_instances(),
        "excluded": registry.list_excluded(),
        "eliminated": registry.list_eliminated(),
    })


@mcp.resource("kipi://loops/open")
def resource_loops_open() -> str:
    """All currently open follow-up loops."""
    return json.dumps(loop_tracker.list(min_level=0))


@mcp.resource("kipi://loops/stats")
def resource_loops_stats() -> str:
    """Summary statistics for open and recently closed loops."""
    return json.dumps(loop_tracker.stats())



# ============================================================
# Instance Management (2 tools)
# ============================================================


@mcp.tool()
def kipi_suggest_instance_name(company: str) -> str:
    """Generate a Discord-style instance name from a company name.

    Returns a suggested name like "eqbit-dragon12". Call this during /q-setup
    to suggest an instance name, then let the user override.

    Args:
        company: Company or project name to derive the slug from.
    """
    try:
        existing = _get_existing_instance_names()
        suggestion = generate_instance_name(company, existing)
        return json.dumps({"suggested": suggestion, "existing": sorted(existing)})
    except Exception as e:
        logger.error("kipi_suggest_instance_name failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_set_instance_name(name: str) -> str:
    """Set the active instance name by writing active-instance file.

    Validates the name isn't already taken by another instance.
    After setting, the server must be restarted for the new name to take effect.

    Args:
        name: The instance name to set (e.g. "eqbit-dragon12").
    """
    try:
        existing = _get_existing_instance_names()
        if name in existing and name != paths.instance:
            raise ToolError(
                f"Instance name '{name}' is already taken. "
                f"Existing: {sorted(existing)}"
            )
        marker = paths._base / "active-instance"
        marker.write_text(name + "\n")
        return json.dumps({"set": True, "name": name, "file": str(marker)})
    except ToolError:
        raise
    except Exception as e:
        logger.error("kipi_set_instance_name failed", exc_info=True)
        raise ToolError(str(e))


def _get_existing_instance_names() -> set[str]:
    """Collect all instance names from registry + instances/ directories."""
    names: set[str] = set()
    for inst in registry.list_instances():
        if "name" in inst:
            names.add(inst["name"])
    # Also scan the instances/ directory for names on disk
    instances_dir = paths._base / "instances"
    if instances_dir.exists():
        for child in instances_dir.iterdir():
            if child.is_dir():
                names.add(child.name)
    return names




# ============================================================
# Validation (1 tool)
# ============================================================


@mcp.tool()
def kipi_validate(phase: int = 5, verbose: bool = False) -> str:
    """Run the kipi validation suite.

    Phases: 0=registry, 1=skeleton integrity, 2=instance checks,
    3=eliminated cleanup, 4=instance health, 5=documentation.

    Args:
        phase: Validation phase to run (0-5, default 5 = all phases).
        verbose: Include detailed output per check.
    """
    if validator is None:
        raise ToolError("Validator module not available — check server startup logs")
    try:
        results = validator.run(phase=phase, verbose=verbose)
        return json.dumps(results)
    except ToolError:
        raise
    except Exception as e:
        logger.error("kipi_validate failed", exc_info=True)
        raise ToolError(str(e))


# ============================================================
# Step Logger (7 tools)
# ============================================================


@mcp.tool()
def log_init(date: str) -> str:
    """Initialize a morning log file for the given date.

    Args:
        date: Date string in YYYY-MM-DD format.
    """
    try:
        return json.dumps(step_logger.init(date))
    except Exception as e:
        logger.error("log_init failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def log_step(date: str, step_id: str, status: str, result: str = "", error: str = "") -> str:
    """Log a step's completion status in the morning log.

    Args:
        date: Date string in YYYY-MM-DD format.
        step_id: Step identifier (e.g. "0a", "3.8", "11").
        status: Status value (e.g. "done", "skipped", "failed").
        result: Optional result summary.
        error: Optional error message if step failed.
    """
    try:
        return json.dumps(step_logger.log_step(date, step_id, status, result, error))
    except Exception as e:
        logger.error("log_step failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def log_add_card(date: str, card_id: str, card_type: str, target: str, draft_text: str, url: str = "") -> str:
    """Add an action card to the morning log.

    Args:
        date: Date string in YYYY-MM-DD format.
        card_id: Unique card identifier.
        card_type: Card type (e.g. "email", "linkedin_comment", "dm").
        target: Who this card targets (person or company name).
        draft_text: Draft copy-paste text for the action (truncated to 200 chars).
        url: Optional URL associated with the action.
    """
    try:
        return json.dumps(step_logger.add_card(date, card_id, card_type, target, draft_text, url))
    except Exception as e:
        logger.error("log_add_card failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def log_deliver_cards(date: str) -> str:
    """Mark all undelivered action cards as delivered.

    Args:
        date: Date string in YYYY-MM-DD format.
    """
    try:
        return json.dumps(step_logger.deliver_cards(date))
    except Exception as e:
        logger.error("log_deliver_cards failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def log_gate_check(date: str, gate_step: str, all_prior_done: bool, missing: str = "") -> str:
    """Record a gate check (verifying prior steps completed before proceeding).

    Args:
        date: Date string in YYYY-MM-DD format.
        gate_step: The gate step being checked (e.g. "8").
        all_prior_done: Whether all prerequisite steps are complete.
        missing: Comma-separated list of missing step IDs, if any.
    """
    try:
        return json.dumps(step_logger.gate_check(date, gate_step, all_prior_done, missing))
    except Exception as e:
        logger.error("log_gate_check failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def log_checksum(date: str, phase: str, key: str, value: str) -> str:
    """Record a state checksum for drift detection between session start and end.

    Args:
        date: Date string in YYYY-MM-DD format.
        phase: Either "start" or "end".
        key: The key being checksummed (e.g. a canonical file name).
        value: The checksum value (e.g. hash or line count).
    """
    try:
        return json.dumps(step_logger.checksum(date, phase, key, value))
    except Exception as e:
        logger.error("log_checksum failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def log_verify(date: str, claim: str, source: str, verified: bool, result: str = "") -> str:
    """Log a claim verification result.

    Args:
        date: Date string in YYYY-MM-DD format.
        claim: The claim being verified.
        source: Source file the claim was checked against.
        verified: Whether the claim was verified as true.
        result: Optional verification result details.
    """
    try:
        return json.dumps(step_logger.verify(date, claim, source, verified, result))
    except Exception as e:
        logger.error("log_verify failed", exc_info=True)
        raise ToolError(str(e))


# ============================================================
# Loop Tracker (5 tools — read ops moved to resources)
# ============================================================


@mcp.tool()
def loop_open(loop_type: str, target: str, context: str, notion_id: str = "", card_id: str = "", follow_up_text: str = "") -> str:
    """Open a new follow-up loop or update an existing one for the same target/type.

    Args:
        loop_type: Type of loop (e.g. "email_sent", "linkedin_comment_posted", "dm_sent").
        target: Person or company this loop tracks.
        context: Brief context for why this loop was opened.
        notion_id: Optional Notion page ID for the contact.
        card_id: Optional action card ID that triggered this loop.
        follow_up_text: Optional follow-up message text.
    """
    try:
        return json.dumps(loop_tracker.open(loop_type, target, context, notion_id, card_id, follow_up_text))
    except Exception as e:
        logger.error("loop_open failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def loop_close(loop_id: str, reason: str, closed_by: str) -> str:
    """Close an open loop (response received, meeting booked, etc.).

    Args:
        loop_id: The loop ID (e.g. "L-2026-03-26-001").
        reason: Why the loop is being closed.
        closed_by: Who closed it (e.g. "founder", "morning_routine").
    """
    try:
        return json.dumps(loop_tracker.close(loop_id, reason, closed_by))
    except Exception as e:
        logger.error("loop_close failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def loop_force_close(loop_id: str, action: str) -> str:
    """Force-close a loop with a specific action (park, kill, defer).

    Args:
        loop_id: The loop ID to force close.
        action: Action taken (e.g. "park", "kill", "defer").
    """
    try:
        return json.dumps(loop_tracker.force_close(loop_id, action))
    except Exception as e:
        logger.error("loop_force_close failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def loop_escalate() -> str:
    """Run escalation logic on all open loops based on age.

    Bumps escalation levels: 0 (new) -> 1 (3+ days) -> 2 (7+ days) -> 3 (14+ days).
    Higher levels signal need for stronger follow-up action.
    """
    try:
        return json.dumps(loop_tracker.escalate())
    except Exception as e:
        logger.error("loop_escalate failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def loop_touch(loop_id: str) -> str:
    """Increment touch count on an open loop (another interaction happened).

    Args:
        loop_id: The loop ID to touch.
    """
    try:
        return json.dumps(loop_tracker.touch(loop_id))
    except Exception as e:
        logger.error("loop_touch failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def loop_prune(days: int = 30) -> str:
    """Remove closed loops older than the specified number of days.

    Args:
        days: Age threshold in days for pruning closed loops (default 30).
    """
    try:
        return json.dumps(loop_tracker.prune(days))
    except Exception as e:
        logger.error("loop_prune failed", exc_info=True)
        raise ToolError(str(e))


# ============================================================
# Content Tools (3 tools — namespaced)
# ============================================================



@mcp.tool()
def kipi_create_template(template_name: str, output_name: str) -> str:
    """Create a new output directory from a template.

    Args:
        template_name: Name of the template folder in agent-pipeline/templates/.
        output_name: Name for the output directory to create.
    """
    try:
        return json.dumps(template_manager.create(template_name, output_name))
    except Exception as e:
        logger.error("kipi_create_template failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_build_schedule(json_file: str, output_file: str = "") -> str:
    """Build an HTML schedule from a JSON data file.

    Always provide output_file to write to disk — omitting it returns the full
    HTML in the response, which can be very large.

    Args:
        json_file: Path to the schedule JSON data file.
        output_file: Path for the output HTML file. Strongly recommended.
    """
    try:
        return json.dumps(template_manager.build_schedule(json_file, output_file))
    except Exception as e:
        logger.error("kipi_build_schedule failed", exc_info=True)
        raise ToolError(str(e))


# ============================================================
# Backup & Restore (3 tools + 1 resource)
# ============================================================


@mcp.resource("kipi://backups")
def resource_backups() -> str:
    """List all existing backup archives."""
    return json.dumps(backup_manager.list_backups())


@mcp.tool()
def kipi_backup(output_path: str = "") -> str:
    """Create a tar.gz backup of all kipi user data (config, data, state).

    Same archive format as kipi_export — can be restored with kipi_import.
    Runs automatically after /q-morning by default.

    Args:
        output_path: Where to write the archive. Defaults to output dir with timestamp.
    """
    try:
        p = Path(output_path) if output_path else None
        return json.dumps(backup_manager.backup(output_path=p))
    except Exception as e:
        logger.error("kipi_backup failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_export(output_path: str = "") -> str:
    """Export all kipi user data as a portable tar.gz archive.

    Same as kipi_backup — use this when moving data to another machine.
    Restore with kipi_import.

    Args:
        output_path: Where to write the archive. Defaults to output dir with timestamp.
    """
    try:
        p = Path(output_path) if output_path else None
        return json.dumps(backup_manager.backup(output_path=p))
    except Exception as e:
        logger.error("kipi_export failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_import(archive_path: str, dry_run: bool = True) -> str:
    """Import/restore kipi user data from a tar.gz archive.

    Archives created by kipi_backup or kipi_export are portable across
    platforms — paths are resolved to the current platform's directories.

    Args:
        archive_path: Path to the backup archive to restore from.
        dry_run: If True, show what would be restored without writing. Default True for safety.
    """
    try:
        return json.dumps(backup_manager.restore(Path(archive_path), dry_run=dry_run))
    except FileNotFoundError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error("kipi_import failed", exc_info=True)
        raise ToolError(str(e))


# ============================================================
# Verification & Audit (6 tools)
# ============================================================


@mcp.tool()
def kipi_verify_schedule(json_file: str, day: str = "") -> str:
    """Verify a schedule JSON file before HTML build.

    Checks pipeline follow-ups, day-specific content, section ordering,
    and energy tags. Blocks HTML build if required sections are missing.

    Args:
        json_file: Path to the schedule-data JSON file.
        day: Day of week (monday, tuesday, etc.). Derived from data if omitted.
    """
    try:
        data = json.loads(Path(json_file).read_text())
        return json.dumps(schedule_verifier.verify(data, day))
    except Exception as e:
        logger.error("kipi_verify_schedule failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_verify_bus(date: str, phase: int) -> str:
    """Verify bus files exist and are valid for a pipeline phase.

    Run between phases to ensure expected JSON outputs were produced.

    Args:
        date: Date string (YYYY-MM-DD).
        phase: Pipeline phase number (0-9).
    """
    try:
        return json.dumps(bus_verifier.verify(date, phase))
    except Exception as e:
        logger.error("kipi_verify_bus failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_verify_orchestrator(date: str, phase: int, fix: bool = False) -> str:
    """Verify orchestrator housekeeping between pipeline phases.

    Checks gate logs, session checksums, and action card tracking.
    Use fix=True to auto-generate missing log entries from bus data.

    Args:
        date: Date string (YYYY-MM-DD).
        phase: Pipeline phase number.
        fix: Auto-fix missing entries if data exists. Default False.
    """
    try:
        return json.dumps(orchestrator_verifier.check_phase(date, phase, fix=fix))
    except Exception as e:
        logger.error("kipi_verify_orchestrator failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_bus_to_log(date: str = "") -> str:
    """Bridge bus JSON files to morning-log.json for the audit harness.

    Maps bus file presence/status to step IDs and writes the morning log.

    Args:
        date: Date string (YYYY-MM-DD). Defaults to today.
    """
    try:
        return json.dumps(bus_bridge.bridge(date))
    except Exception as e:
        logger.error("kipi_bus_to_log failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_scan_draft(json_file: str) -> str:
    """Scan a bus JSON file for banned AI words and phrases.

    Deterministic anti-AI scanner that greps copy fields for banned words,
    phrases, emdashes, and hedging density. LLMs miss their own banned
    words — this script does not.

    Args:
        json_file: Path to the bus JSON file to scan.
    """
    try:
        data = json.loads(Path(json_file).read_text())
        return json.dumps(draft_scanner.scan(data))
    except Exception as e:
        logger.error("kipi_scan_draft failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_audit_morning(log_file: str) -> str:
    """Audit a morning routine log for completeness.

    Checks step completion, gate compliance, action cards, state drift,
    and verification queue. Returns a verdict (COMPLETE, MOSTLY COMPLETE,
    PARTIAL, or INCOMPLETE).

    Args:
        log_file: Path to morning-log-YYYY-MM-DD.json.
    """
    try:
        log = json.loads(Path(log_file).read_text())
        return json.dumps(morning_auditor.audit(log))
    except Exception as e:
        logger.error("kipi_audit_morning failed", exc_info=True)
        raise ToolError(str(e))


# ============================================================
# Metrics Store (8 tools)
# ============================================================


@mcp.tool()
def kipi_init_db() -> str:
    """Initialize the metrics database (idempotent). Returns list of table names."""
    try:
        tables = metrics_store.init_db()
        return json.dumps({"tables": tables})
    except Exception as e:
        logger.error("kipi_init_db failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_insert_content_metrics(metrics_json: str) -> str:
    """Insert content performance metrics from a JSON array of records.

    Args:
        metrics_json: JSON array of metric objects with keys: post_id, platform, publish_date, scraped_at, and optional impressions, engagement_rate, clicks, likes, comments, reposts, reach.
    """
    try:
        records = json.loads(metrics_json)
        return json.dumps(metrics_store.insert_content_metrics(records))
    except json.JSONDecodeError as e:
        raise ToolError(f"Invalid JSON: {e}")
    except Exception as e:
        logger.error("kipi_insert_content_metrics failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_insert_behavioral_signals(signals_json: str) -> str:
    """Insert behavioral signals from a JSON array.

    Args:
        signals_json: JSON array of signal objects with keys: contact_name, signal_type, signal_date, source, weight.
    """
    try:
        signals = json.loads(signals_json)
        return json.dumps(metrics_store.insert_behavioral_signals(signals))
    except json.JSONDecodeError as e:
        raise ToolError(f"Invalid JSON: {e}")
    except Exception as e:
        logger.error("kipi_insert_behavioral_signals failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_insert_outreach(
    contact_name: str, channel: str, action_type: str,
    copy_text: str, send_date: str,
) -> str:
    """Insert a single outreach log record.

    Args:
        contact_name: Name of the contact.
        channel: Communication channel (email, linkedin, etc.).
        action_type: Type of action (cold_email, dm, follow_up, etc.).
        copy_text: The outreach copy text sent.
        send_date: Date sent in YYYY-MM-DD format.
    """
    try:
        return json.dumps(metrics_store.insert_outreach_log(
            contact_name, channel, action_type, copy_text, send_date,
        ))
    except Exception as e:
        logger.error("kipi_insert_outreach failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_insert_copy_edit(
    original_text: str, edited_text: str,
    diff_summary: str = "", context: str = "",
) -> str:
    """Insert a copy edit record for learning analysis.

    Args:
        original_text: The original draft text.
        edited_text: The edited/final text.
        diff_summary: Brief description of what changed.
        context: Where this edit happened (outreach, content, etc.).
    """
    try:
        edit_date = datetime.now().strftime("%Y-%m-%d")
        return json.dumps(metrics_store.insert_copy_edit(
            original_text, edited_text, edit_date, diff_summary, context,
        ))
    except Exception as e:
        logger.error("kipi_insert_copy_edit failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_query(query_type: str, days: int = 30) -> str:
    """Query metrics data. Types: content, outreach, signals, edits, top_posts.

    Args:
        query_type: One of "content", "outreach", "signals", "edits", "top_posts".
        days: Number of days to look back (default 30).
    """
    try:
        if query_type == "content":
            return json.dumps(metrics_store.query_content_performance(days=days))
        elif query_type == "outreach":
            return json.dumps(metrics_store.query_outreach_stats(days=days))
        elif query_type == "signals":
            return json.dumps(metrics_store.query_behavioral_signals(days=days))
        elif query_type == "edits":
            return json.dumps(metrics_store.query_copy_edits(days=days))
        elif query_type == "top_posts":
            return json.dumps(metrics_store.query_top_posts(limit=days))
        else:
            raise ToolError(f"Unknown query_type: {query_type}. Use: content, outreach, signals, edits, top_posts")
    except ToolError:
        raise
    except Exception as e:
        logger.error("kipi_query failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_daily_metrics(
    date: str, posts_published: int = 0, outreach_sent: int = 0,
    responses_received: int = 0, meetings_booked: int = 0,
    energy_level: int = 0, routine_completion_pct: float = 0.0,
) -> str:
    """Upsert daily metrics for a given date.

    Args:
        date: Date in YYYY-MM-DD format.
        posts_published: Number of posts published.
        outreach_sent: Number of outreach messages sent.
        responses_received: Number of responses received.
        meetings_booked: Number of meetings booked.
        energy_level: Self-reported energy level (1-10).
        routine_completion_pct: Morning routine completion percentage (0-100).
    """
    try:
        return json.dumps(metrics_store.upsert_daily_metrics(
            date,
            posts_published=posts_published,
            outreach_sent=outreach_sent,
            responses_received=responses_received,
            meetings_booked=meetings_booked,
            energy_level=energy_level,
            routine_completion_pct=routine_completion_pct,
        ))
    except Exception as e:
        logger.error("kipi_daily_metrics failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_monthly_learnings(days: int = 30) -> str:
    """Generate a monthly learnings report from copy edit patterns.

    Args:
        days: Number of days to analyze (default 30).
    """
    try:
        return json.dumps(metrics_store.generate_monthly_learnings(days=days))
    except Exception as e:
        logger.error("kipi_monthly_learnings failed", exc_info=True)
        raise ToolError(str(e))



# ============================================================
# Linter Tools (9 tools — deterministic text validation + LinkedIn cadence)
# ============================================================


@mcp.tool()
def kipi_voice_lint(text: str) -> str:
    """Lint text for AI writing patterns, banned words, and voice violations.

    Deterministic check — catches banned words LLMs miss in their own output.
    Run on all draft copy before publishing.

    Args:
        text: The text to lint.
    """
    try:
        return json.dumps(linter.voice_lint(text))
    except Exception as e:
        logger.error("kipi_voice_lint failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_validate_schedule(sections_json: str, day: str = "") -> str:
    """Validate a morning schedule for AUDHD compliance and content rules.

    Checks section ordering, pipeline follow-up quality, day-specific content,
    energy tags, and quick wins presence.

    Args:
        sections_json: JSON array of schedule sections.
        day: Lowercase weekday name (monday-sunday). Derived from schedule if omitted.
    """
    try:
        sections = json.loads(sections_json)
        return json.dumps(linter.validate_schedule(sections, day))
    except json.JSONDecodeError as e:
        raise ToolError(f"Invalid JSON: {e}")
    except Exception as e:
        logger.error("kipi_validate_schedule failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_validate_ad_copy(platform: str, headlines_json: str, descriptions_json: str) -> str:
    """Validate ad copy against platform character limits.

    Platforms: google, meta, linkedin, twitter, tiktok.

    Args:
        platform: Ad platform name.
        headlines_json: JSON array of headline strings.
        descriptions_json: JSON array of description strings.
    """
    try:
        headlines = json.loads(headlines_json)
        descriptions = json.loads(descriptions_json)
        return json.dumps(linter.validate_ad_copy(platform, headlines, descriptions))
    except json.JSONDecodeError as e:
        raise ToolError(f"Invalid JSON: {e}")
    except Exception as e:
        logger.error("kipi_validate_ad_copy failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_seo_check(
    title: str = "", meta: str = "",
    headings_json: str = "[]", cwv_json: str = "{}",
) -> str:
    """Check SEO basics: title/meta length, heading hierarchy, Core Web Vitals.

    Args:
        title: Page title tag text.
        meta: Meta description text.
        headings_json: JSON array of {"level": int, "text": str} objects.
        cwv_json: JSON object with optional lcp (seconds), inp (ms), cls (score).
    """
    try:
        headings = json.loads(headings_json) if headings_json else []
        cwv = json.loads(cwv_json) if cwv_json else {}
        return json.dumps(linter.seo_check(title, meta, headings or None, cwv or None))
    except json.JSONDecodeError as e:
        raise ToolError(f"Invalid JSON: {e}")
    except Exception as e:
        logger.error("kipi_seo_check failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_validate_cold_email(subject: str, body: str) -> str:
    """Validate a cold email for deliverability and response rate best practices.

    Checks subject line length/words, body length, reading level, AI patterns,
    and CTA count.

    Args:
        subject: Email subject line.
        body: Email body text.
    """
    try:
        return json.dumps(linter.validate_cold_email(subject, body))
    except Exception as e:
        logger.error("kipi_validate_cold_email failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_copy_edit_lint(text: str) -> str:
    """Lint text for plain English: complex words, filler, passive voice.

    Returns suggested replacements and flagged patterns.

    Args:
        text: The text to lint.
    """
    try:
        return json.dumps(linter.copy_edit_lint(text))
    except Exception as e:
        logger.error("kipi_copy_edit_lint failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_linkedin_gate(
    draft: str,
    kind: str = "post",
    day_of_week: str = "",
    override_day: bool = False,
) -> str:
    """Run the full LinkedIn pre-publish gate on a draft.

    Wraps kipi_voice_lint + kipi_copy_edit_lint plus LinkedIn-specific checks.
    Voice, copy, and hashtag rules apply to every kind. Body-link and
    day-of-week rules apply only when kind="post" (reach-sensitive).

    Args:
        draft: The full LinkedIn draft text.
        kind: "post" (default), "comment", "dm", or "about". Controls which
            post-only rules apply.
        day_of_week: Ship-day weekday for a post (e.g. "tue"). Blank = skip.
            Ignored unless kind="post".
        override_day: Set true to bypass the day-of-week gate on a post.
    """
    try:
        return json.dumps(
            linter.linkedin_gate(draft, kind, day_of_week, override_day)
        )
    except ValueError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error("kipi_linkedin_gate failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_log_linkedin_activity(
    kind: str, url: str, pillar: str = "", activity_date: str = "",
) -> str:
    """Log a shipped LinkedIn post or comment for cadence tracking.

    Call after publishing a post or a 2nd-degree engagement comment.

    Args:
        kind: "post" or "comment".
        url: Link to the post or comment.
        pillar: Optional pillar tag (e.g. "scar", "founder-op", "AI/visibility").
        activity_date: ISO date (YYYY-MM-DD). Defaults to today.
    """
    try:
        return json.dumps(metrics_store.log_linkedin_activity(
            kind=kind,
            url=url,
            pillar=pillar or None,
            activity_date=activity_date or None,
        ))
    except Exception as e:
        logger.error("kipi_log_linkedin_activity failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_linkedin_cadence_check(today: str = "") -> str:
    """Report LinkedIn cadence: posts this week, engage ratio, last post day.

    Advisory only. Always returns pass=True. Surfaces weekly post cap and
    engage-ratio signals in warnings[] for the caller to display; never blocks.

    Args:
        today: ISO date (YYYY-MM-DD). Defaults to today. Week = Mon–Sun.
    """
    try:
        return json.dumps(metrics_store.linkedin_cadence_check(today or None))
    except Exception as e:
        logger.error("kipi_linkedin_cadence_check failed", exc_info=True)
        raise ToolError(str(e))


# ============================================================
# Scorer Tools (5 tools — deterministic scoring and calculation)
# ============================================================


@mcp.tool()
def kipi_score_lead(attributes_json: str, signals_json: str, model: str = "hybrid") -> str:
    """Score a lead using fit + engagement + negative scoring with decay.

    Models: plg (30/70 fit/engage, MQL 60), enterprise (60/40, MQL 75),
    hybrid (50/50, MQL 65).

    Args:
        attributes_json: JSON object with company_size, industry, revenue, title,
            department, role, tech, negatives (list of negative signal names).
        signals_json: JSON array of {"type": str, "age_days": int} objects.
        model: Scoring model name (plg, enterprise, hybrid).
    """
    try:
        attributes = json.loads(attributes_json)
        signals = json.loads(signals_json)
        return json.dumps(scorer.score_lead(attributes, signals, model))
    except json.JSONDecodeError as e:
        raise ToolError(f"Invalid JSON: {e}")
    except ValueError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error("kipi_score_lead failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_ab_test_calc(baseline: float, mde: float, traffic: int, variants: int = 2) -> str:
    """Calculate A/B test sample size, duration, and feasibility.

    Args:
        baseline: Current conversion rate (e.g. 0.03 for 3%).
        mde: Minimum detectable effect as relative lift (e.g. 0.1 for 10% lift).
        traffic: Daily traffic (visitors per day).
        variants: Number of test variants (default 2).
    """
    try:
        return json.dumps(scorer.ab_test_calc(baseline, mde, traffic, variants))
    except Exception as e:
        logger.error("kipi_ab_test_calc failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_churn_health_score(signals_json: str) -> str:
    """Calculate customer health score (0-100) with tier and risk flags.

    Args:
        signals_json: JSON object with component scores (0-100): login_frequency,
            feature_usage, support_sentiment, billing_health, engagement. Optional
            boolean flags: login_drop_50pct, feature_usage_stopped,
            support_spike_then_stop, billing_page_visits, seats_removed,
            data_export, nps_below_6.
    """
    try:
        signals = json.loads(signals_json)
        return json.dumps(scorer.churn_health_score(signals))
    except json.JSONDecodeError as e:
        raise ToolError(f"Invalid JSON: {e}")
    except Exception as e:
        logger.error("kipi_churn_health_score failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_cancel_flow_offer(reason: str, mrr: float = 0) -> str:
    """Map a cancel reason to the best save offer and MRR-based routing.

    Reasons: too_expensive, not_using, missing_feature, switching_competitor,
    technical_issues, temporary, business_closed.

    Args:
        reason: Cancel reason key.
        mrr: Monthly recurring revenue of the account (for routing tier).
    """
    try:
        return json.dumps(scorer.cancel_flow_offer(reason, mrr))
    except Exception as e:
        logger.error("kipi_cancel_flow_offer failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_crack_detect(contacts_json: str, loops_json: str = "[]") -> str:
    """Detect follow-up gaps: overdue contacts, stalled deals, stale loops.

    Args:
        contacts_json: JSON array of {"name": str, "last_contact_days": int,
            "touches": int, "status": str} objects.
        loops_json: Optional JSON array of {"id": str, "age_days": int,
            "status": str} objects.
    """
    try:
        contacts = json.loads(contacts_json)
        loops = json.loads(loops_json) if loops_json else []
        return json.dumps(scorer.crack_detect(contacts, loops or None))
    except json.JSONDecodeError as e:
        raise ToolError(f"Invalid JSON: {e}")
    except Exception as e:
        logger.error("kipi_crack_detect failed", exc_info=True)
        raise ToolError(str(e))


# ============================================================
# Schema Generator (1 tool — JSON-LD structured data)
# ============================================================


@mcp.tool()
def kipi_generate_schema(page_type: str, data_json: str) -> str:
    """Generate JSON-LD structured data for a page type.

    Page types: organization, website, article, blog_posting, product,
    software_application, faq, howto, breadcrumb, local_business, event.

    Args:
        page_type: Schema type to generate.
        data_json: JSON object with required and optional fields for the type.
    """
    try:
        data = json.loads(data_json)
        return json.dumps(schema_generator.generate(page_type, data))
    except json.JSONDecodeError as e:
        raise ToolError(f"Invalid JSON: {e}")
    except ValueError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error("kipi_generate_schema failed", exc_info=True)
        raise ToolError(str(e))


# ============================================================
# Harvest Tools (7 tools)
# ============================================================


@mcp.tool()
async def kipi_harvest(
    sources: str = "all",
    mode: str = "incremental",
    methods: str = "all",
) -> str:
    """Run data harvest from configured sources.

    For http/apify/local sources: executes in Python (zero tokens).
    For chrome/mcp sources: returns generated agent prompts to spawn.

    Args:
        sources: "all" or comma-separated source names.
        mode: "incremental" (use cursors), "full" (ignore cursors), or "resume" (continue last run).
        methods: "all" or filter to "http", "apify", "chrome", "mcp", "local".
    """
    try:
        from kipi_mcp.harvest_orchestrator import HarvestOrchestrator
        orchestrator = HarvestOrchestrator(
            store=harvest_store,
            registry=source_registry,
            apify_token=os.environ.get("APIFY_TOKEN"),
        )
        result = await orchestrator.harvest(
            sources=sources, mode=mode, methods=methods,
            env=dict(os.environ),
        )
        return json.dumps({
            "run_id": result.run_id,
            "python_results": result.python_results,
            "chrome_agent_prompt": result.chrome_agent_prompt,
            "mcp_agent_prompt": result.mcp_agent_prompt,
            "skipped": result.skipped,
            "errors": result.errors,
        })
    except Exception as e:
        logger.error("kipi_harvest failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_store_harvest(source_name: str, records_json: str, run_id: str = "") -> str:
    """Store harvested records from an agent.

    Called by Chrome/MCP harvest agents after extracting data.
    Each record should have a unique key field (url, id, etc).

    Args:
        source_name: Source identifier (e.g. "linkedin-feed").
        records_json: JSON array of record objects.
        run_id: The harvest run ID this data belongs to.
    """
    try:
        records = json.loads(records_json)

        # Validate records have usable content
        if not records:
            return json.dumps({"stored": 0, "deduped": 0, "source": source_name, "warning": "empty_records"})

        valid_records = []
        for record in records:
            if not isinstance(record, dict):
                continue
            if source_name.startswith("agent:"):
                has_key = any(record.get(k) for k in ("id", "url", "name", "title", "contact_name", "action"))
                if not has_key:
                    logger.warning("Skipping record with no identifiable key from %s", source_name)
                    continue
            valid_records.append(record)
        records = valid_records

        stored = 0
        deduped = 0
        for record in records:
            key = record.get("url") or record.get("id") or record.get("record_key", "")
            summary = json.dumps({k: v for k, v in record.items() if k != "body_text" and k != "full_text"})
            body = record.get("body_text") or record.get("full_text") or record.get("text")
            result = harvest_store.store_record(
                run_id=run_id,
                source_name=source_name,
                record_key=str(key),
                summary_json=summary,
                body_text=body,
            )
            if result is None:
                break
            if result.get("deduped"):
                deduped += 1
            else:
                stored += 1
        # Mark source_run complete if run_id provided
        if run_id:
            harvest_store.complete_source_run(run_id, source_name, stored)

        return json.dumps({"stored": stored, "deduped": deduped, "source": source_name})
    except json.JSONDecodeError as e:
        raise ToolError(f"Invalid JSON: {e}")
    except Exception as e:
        logger.error("kipi_store_harvest failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_get_harvest(
    source_name: str,
    days: int = 1,
    include_body: bool = False,
    limit: int = 50,
    after_id: int = 0,
) -> str:
    """Get harvested records for a source.

    Returns summary data by default. Set include_body=True for full text
    (decompresses from storage -- slower, more tokens).

    Args:
        source_name: Source to query (e.g. "linkedin-feed").
        days: Look back N days (default 1).
        include_body: Include full text body (default False).
        limit: Max records to return (default 50).
        after_id: Return records with id > this value (for pagination).
    """
    try:
        records = harvest_store.get_records(
            source_name=source_name,
            days=days,
            include_body=include_body,
            limit=limit,
            after_id=after_id,
        )
        return json.dumps({"records": records, "count": len(records), "source": source_name})
    except Exception as e:
        logger.error("kipi_get_harvest failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_harvest_status(run_id: str = "") -> str:
    """Check harvest run status.

    Args:
        run_id: Specific run ID. If empty, returns latest run.
    """
    try:
        if run_id:
            run = harvest_store.get_run(run_id)
        else:
            run = harvest_store.get_latest_run()
        if not run:
            return json.dumps({"error": "no_runs_found"})
        return json.dumps(run)
    except Exception as e:
        logger.error("kipi_harvest_status failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_harvest_summary(run_id: str = "") -> str:
    """Get record counts per source for a harvest run.

    Args:
        run_id: Specific run ID. If empty, uses latest run.
    """
    try:
        if not run_id:
            latest = harvest_store.get_latest_run()
            if not latest:
                return json.dumps({"error": "no_runs_found"})
            run_id = latest["run_id"]
        summary = harvest_store.harvest_summary(run_id)
        return json.dumps(summary)
    except Exception as e:
        logger.error("kipi_harvest_summary failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_harvest_cleanup(days: int = 7) -> str:
    """Delete harvest data older than N days.

    Bodies are cascade-deleted with their parent records.

    Args:
        days: Age threshold in days (default 7).
    """
    try:
        return json.dumps(harvest_store.cleanup(days))
    except Exception as e:
        logger.error("kipi_harvest_cleanup failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_approve_apify_budget(month: str, extra: float) -> str:
    """Approve additional Apify spend for a month.

    Call this when a harvest is blocked by budget limits.

    Args:
        month: Month in YYYY-MM format (e.g. "2026-04").
        extra: Additional dollars to approve.
    """
    try:
        return json.dumps(harvest_store.approve_extra(month, extra))
    except Exception as e:
        logger.error("kipi_approve_apify_budget failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_harvest_health(run_id: str = "") -> str:
    """Check harvest completeness. Shows sources complete/failed/pending.

    Call after Phase 1 harvest to verify data quality before processing.

    Args:
        run_id: Harvest run ID. If empty, uses latest run.
    """
    try:
        if not run_id:
            latest = harvest_store.get_latest_run()
            if not latest:
                return json.dumps({"error": "no_runs_found"})
            run_id = latest["run_id"]
        return json.dumps(harvest_store.harvest_health(run_id))
    except Exception as e:
        logger.error("kipi_harvest_health failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_queue_notion_write(action_json: str, source_agent: str) -> str:
    """Queue a Notion write that failed for retry on next morning.

    Called by 09-notion-push when a Notion API write fails.

    Args:
        action_json: JSON of the action that failed to write.
        source_agent: Which agent produced this action.
    """
    try:
        return json.dumps(harvest_store.queue_notion_write(action_json, source_agent))
    except Exception as e:
        logger.error("kipi_queue_notion_write failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_get_notion_queue() -> str:
    """Get all pending Notion writes awaiting retry."""
    try:
        pending = harvest_store.get_pending_notion_writes()
        return json.dumps({"pending": pending, "count": len(pending)})
    except Exception as e:
        logger.error("kipi_get_notion_queue failed", exc_info=True)
        raise ToolError(str(e))


# ============================================================
# Agent Metrics & Session Handoff (3 tools)
# ============================================================


@mcp.tool()
def kipi_log_agent_metric(
    agent_name: str, phase: str, model: str = "",
    started_at: str = "", completed_at: str = "",
    duration_seconds: float = 0, status: str = "done",
    records_read: int = 0, records_written: int = 0,
) -> str:
    """Log agent execution timing for performance analysis.

    Args:
        agent_name: Name of the agent (e.g. "01-harvest", "03-content").
        phase: Pipeline phase (e.g. "phase_1", "phase_3").
        model: Model used (e.g. "haiku", "sonnet").
        started_at: ISO timestamp when agent started.
        completed_at: ISO timestamp when agent finished.
        duration_seconds: Wall-clock seconds for the run.
        status: Outcome (done, failed, skipped).
        records_read: Number of records consumed.
        records_written: Number of records produced.
    """
    try:
        date = datetime.now().strftime("%Y-%m-%d")
        result = harvest_store.log_agent_metric(
            date=date, agent_name=agent_name, phase=phase, model=model,
            started_at=started_at, completed_at=completed_at,
            duration_seconds=duration_seconds, status=status,
            records_read=records_read, records_written=records_written,
        )
        return json.dumps(result)
    except Exception as e:
        logger.error("kipi_log_agent_metric failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_agent_metrics(days: int = 7) -> str:
    """Query per-agent performance averages over N days.

    Args:
        days: Number of days to look back (default 7).
    """
    try:
        return json.dumps(harvest_store.query_agent_metrics(days))
    except Exception as e:
        logger.error("kipi_agent_metrics failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_session_handoff(run_id: str, phases_completed: str, notes: str = "") -> str:
    """Save a session handoff for resume. Called when context is running low.

    Args:
        run_id: Current harvest run ID.
        phases_completed: Comma-separated list of completed phases.
        notes: Free-text notes for the next session.
    """
    try:
        date = datetime.now().strftime("%Y-%m-%d")
        result = harvest_store.save_handoff(date, run_id, phases_completed, notes)
        return json.dumps(result)
    except Exception as e:
        logger.error("kipi_session_handoff failed", exc_info=True)
        raise ToolError(str(e))


# ============================================================
# Morning Init Tools (4 tools — deterministic Python)
# ============================================================


@mcp.tool()
def kipi_preflight() -> str:
    """Check system readiness: required files exist, system is configured.

    Replaces the 00-preflight agent with deterministic Python checks.
    Returns file existence status and overall ready flag.
    """
    try:
        from kipi_mcp.morning_init import preflight
        return json.dumps(preflight(paths))
    except Exception as e:
        logger.error("kipi_preflight failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_session_bootstrap() -> str:
    """Recover state from previous session.

    Replaces the 00-session-bootstrap agent. Recovers unconfirmed action
    cards, computes loop stats, detects stalls (>14 days no contact),
    and checksums canonical files.
    """
    try:
        from kipi_mcp.morning_init import session_bootstrap
        return json.dumps(session_bootstrap(paths))
    except Exception as e:
        logger.error("kipi_session_bootstrap failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_canonical_digest() -> str:
    """Parse canonical markdown files into structured JSON digest.

    Replaces the 00c-canonical-digest agent. Reads talk-tracks, objections,
    current-state, discovery, and decisions files. Extracts key fields and
    runs a 7-point validation gate. Saves ~40-60K tokens vs agents reading
    full canonical files.
    """
    try:
        from kipi_mcp.morning_init import canonical_digest
        return json.dumps(canonical_digest(paths))
    except Exception as e:
        logger.error("kipi_canonical_digest failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_morning_init(energy_level: int = 3) -> str:
    """Combined morning initialization: preflight + bootstrap + digest + bus setup.

    THE one call that replaces phases 0-0.7 of the old orchestrator.
    Creates today's bus directory, cleans old ones, runs all init checks,
    and returns the complete init bundle.

    Args:
        energy_level: Founder's energy level (1-5). Governs downstream compression.
    """
    try:
        from kipi_mcp.morning_init import morning_init
        return json.dumps(morning_init(paths, energy_level, harvest_store=harvest_store, backup_manager=backup_manager))
    except Exception as e:
        logger.error("kipi_morning_init failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_gate_check(phase: int, date: str = "") -> str:
    """Check if all prior phases are logged before a gate phase.

    Call this before Phases 6, 7, or 8. Reads the morning log and
    verifies every prior phase is logged as done or skipped.

    Args:
        phase: The gate phase number (6, 7, or 8).
        date: Date in YYYY-MM-DD format. Defaults to today.
    """
    try:
        from kipi_mcp.morning_init import gate_check
        return json.dumps(gate_check(paths, phase, date))
    except Exception as e:
        logger.error("kipi_gate_check failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_deliverables_check(date: str = "") -> str:
    """Check that required deliverables exist for today.

    Verifies bus files contain expected outputs based on day of week.
    Call this before synthesis (Phase 6) to catch missing work.

    Args:
        date: Date in YYYY-MM-DD format. Defaults to today.
    """
    try:
        from kipi_mcp.morning_init import deliverables_check
        return json.dumps(deliverables_check(paths, date, harvest_store=harvest_store))
    except Exception as e:
        logger.error("kipi_deliverables_check failed", exc_info=True)
        raise ToolError(str(e))


def main():
    """Entry point for the kipi MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
