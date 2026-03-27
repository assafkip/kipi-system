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
from kipi_mcp.git_ops import GitOps
from kipi_mcp.step_logger import StepLogger
from kipi_mcp.loop_tracker import LoopTracker
from kipi_mcp.template_manager import TemplateManager
from kipi_mcp.migrator import Migrator
from kipi_mcp.backup import BackupManager
from kipi_mcp.schedule_verifier import ScheduleVerifier
from kipi_mcp.bus_verifier import BusVerifier
from kipi_mcp.orchestrator_verifier import OrchestratorVerifier
from kipi_mcp.bus_bridge import BusBridge
from kipi_mcp.draft_scanner import DraftScanner
from kipi_mcp.morning_auditor import MorningAuditor
from kipi_mcp.metrics_store import MetricsStore

paths = KipiPaths()
paths.ensure_dirs()

# Warn if legacy layout detected — user should call kipi_migrate explicitly
if paths.detect_legacy_layout():
    logger.warning(
        "Legacy data layout detected (user data in git repo). "
        "Call the kipi_migrate tool to move data to XDG directories."
    )

mcp = FastMCP(
    "kipi",
    instructions=(
        "Kipi founder OS — instance management, morning routine logging, "
        "follow-up loop tracking, and content/schedule tools. "
        "Tool groups: kipi_* (instances, migration, validation), "
        "log_* (morning routine step logging), "
        "loop_* (follow-up loop tracking), "
        "kipi_build_schedule / kipi_create_template (content). "
        "kipi_backup / kipi_export / kipi_import (data portability). "
        "Resources: kipi://paths, kipi://status, kipi://instances, kipi://loops/open, "
        "kipi://loops/stats, kipi://backups. "
        "Read kipi://status first — if legacy_data_detected is true, prompt the user to migrate "
        "before doing anything else. Read kipi://paths for resolved directory paths."
    ),
)

# --- Service instantiation ---

registry = RegistryManager(paths.registry_path)

try:
    skeleton = registry.get_skeleton()
    skeleton_remote = skeleton["remote"]
except Exception:
    skeleton_remote = ""
    logger.warning("Could not load skeleton remote from registry")

git_ops = GitOps(skeleton_remote=skeleton_remote, skeleton_branch="main")

step_logger = StepLogger(output_dir=paths.output_dir)

loop_tracker = LoopTracker(loop_file=paths.output_dir / "open-loops.json")

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
    """System status: migration state, setup state, data health.

    IMPORTANT: If legacy_data_detected is true, tell the user their data
    is still in the git repo and offer to migrate. Migration steps:
    1. Call kipi_suggest_instance_name(company="<their company>") to generate a name.
    2. Let the user confirm or override the instance name.
    3. Call kipi_migrate(dry_run=True, instance_name="<name>") to preview.
    4. Call kipi_migrate(dry_run=False, instance_name="<name>") to execute.
    The instance_name is REQUIRED for legacy repos (no .kipi-instance file).
    """
    profile = paths.founder_profile
    setup_needed = True
    if profile.exists():
        setup_needed = "{{SETUP_NEEDED}}" in profile.read_text()

    has_marker = (paths.repo_dir / ".kipi-instance").exists()
    return json.dumps({
        "legacy_data_detected": paths.detect_legacy_layout(),
        "setup_needed": setup_needed,
        "instance_name": paths.instance,
        "has_instance_marker": has_marker,
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
# Instance Management (4 tools)
# ============================================================


@mcp.tool()
def kipi_migrate(dry_run: bool = True, instance_name: str | None = None) -> str:
    """Migrate user data from git repo to XDG directories.

    For legacy repos (no .kipi-instance file), you must provide instance_name.
    Use kipi_suggest_instance_name first to generate one, then let the user confirm.

    Args:
        dry_run: If True, report what would happen without copying. Default True for safety.
        instance_name: Instance name for this repo. Required if no .kipi-instance marker exists.
    """
    try:
        m = Migrator(paths, instance_name=instance_name)
        return json.dumps(m.migrate(dry_run=dry_run))
    except ValueError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error("kipi_migrate failed", exc_info=True)
        raise ToolError(str(e))


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
    """Set the instance name for the current repo by writing .kipi-instance.

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
        marker = paths.repo_dir / ".kipi-instance"
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
    instances_dir = paths._config_base / "instances"
    if instances_dir.exists():
        for child in instances_dir.iterdir():
            if child.is_dir():
                names.add(child.name)
    return names


@mcp.tool()
def kipi_new_instance(path: str, name: str) -> str:
    """Create a new kipi instance: init git repo, add q-system subtree, register it.

    Args:
        path: Filesystem path for the new instance directory.
        name: Human-readable name for the instance.
    """
    try:
        inst_path = Path(path)
        prefix = "q-system"

        inst_path.mkdir(parents=True, exist_ok=True)

        if not (inst_path / ".git").exists():
            res = git_ops.init_repo(inst_path)
            if not res["success"]:
                raise ToolError(f"git init failed: {res['stderr']}")

        res = git_ops.subtree_add(inst_path, prefix)
        if not res["success"]:
            raise ToolError(f"subtree add failed: {res['stderr']}")

        claude_md = inst_path / "CLAUDE.md"
        if not claude_md.exists():
            claude_md.write_text(
                f"# {name}\n\n"
                f"@q-system/CLAUDE.md\n\n"
                f"## Instance Notes\n\n"
                f"Add project-specific instructions here.\n"
            )

        git_ops.run_git(["add", "-A"], inst_path)
        git_ops.run_git(["commit", "-m", f"Initialize {name} with q-system skeleton"], inst_path)

        entry = registry.add_instance(
            name=name,
            path=str(inst_path),
            prefix=prefix,
            inst_type="subtree",
        )

        return json.dumps({"created": True, "instance": entry})
    except ToolError:
        raise
    except Exception as e:
        logger.error("kipi_new_instance failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_update(dry_run: bool = False, instance_name: str | None = None) -> str:
    """Pull latest skeleton into instances via subtree pull or git pull.

    Args:
        dry_run: If True, report what would happen without actually pulling.
        instance_name: If set, only update this instance. Otherwise update all.
    """
    try:
        instances = registry.list_instances()
        if instance_name:
            instances = [i for i in instances if i["name"] == instance_name]
            if not instances:
                raise ToolError(f"Instance '{instance_name}' not found")

        results = {}
        for inst in instances:
            inst_name = inst["name"]
            inst_path = Path(inst["path"])
            inst_type = inst.get("type", "subtree")
            prefix = inst.get("subtree_prefix", "q-system")

            if not inst_path.exists():
                results[inst_name] = {"status": "skipped", "reason": "path does not exist"}
                continue

            if dry_run:
                results[inst_name] = {"status": "dry_run", "type": inst_type}
                continue

            if inst_type == "direct-clone":
                res = git_ops.git_pull(inst_path)
            else:
                res = git_ops.subtree_pull(inst_path, prefix)

            results[inst_name] = {
                "status": "success" if res["success"] else "failed",
                "type": inst_type,
                "stdout": res["stdout"][:500],
                "stderr": res["stderr"][:500],
            }

        return json.dumps(results)
    except ToolError:
        raise
    except Exception as e:
        logger.error("kipi_update failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def kipi_push_upstream(instance_path: str) -> str:
    """Push instance's q-system changes upstream to the skeleton repo.

    Runs a safety check for instance-specific content before pushing.

    Args:
        instance_path: Filesystem path of the instance to push from.
    """
    try:
        inst_path = Path(instance_path)
        prefix = "q-system"
        prefix_path = inst_path / prefix

        if not prefix_path.is_dir():
            raise ToolError(f"No {prefix}/ directory at {inst_path}")

        matches = git_ops.check_instance_content(prefix_path)
        if matches:
            return json.dumps({
                "blocked": True,
                "reason": "Instance-specific content found in q-system/",
                "matched_files": matches,
            })

        res = git_ops.subtree_push(inst_path, prefix)
        return json.dumps({
            "pushed": res["success"],
            "stdout": res["stdout"][:500],
            "stderr": res["stderr"][:500],
        })
    except ToolError:
        raise
    except Exception as e:
        logger.error("kipi_push_upstream failed", exc_info=True)
        raise ToolError(str(e))


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
def ktlyst_init_db() -> str:
    """Initialize the metrics database (idempotent). Returns list of table names."""
    try:
        tables = metrics_store.init_db()
        return json.dumps({"tables": tables})
    except Exception as e:
        logger.error("ktlyst_init_db failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def ktlyst_insert_content_metrics(metrics_json: str) -> str:
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
        logger.error("ktlyst_insert_content_metrics failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def ktlyst_insert_behavioral_signals(signals_json: str) -> str:
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
        logger.error("ktlyst_insert_behavioral_signals failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def ktlyst_insert_outreach(
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
        logger.error("ktlyst_insert_outreach failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def ktlyst_insert_copy_edit(
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
        logger.error("ktlyst_insert_copy_edit failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def ktlyst_query(query_type: str, days: int = 30) -> str:
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
        logger.error("ktlyst_query failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def ktlyst_daily_metrics(
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
        logger.error("ktlyst_daily_metrics failed", exc_info=True)
        raise ToolError(str(e))


@mcp.tool()
def ktlyst_monthly_learnings(days: int = 30) -> str:
    """Generate a monthly learnings report from copy edit patterns.

    Args:
        days: Number of days to analyze (default 30).
    """
    try:
        return json.dumps(metrics_store.generate_monthly_learnings(days=days))
    except Exception as e:
        logger.error("ktlyst_monthly_learnings failed", exc_info=True)
        raise ToolError(str(e))


def main():
    """Entry point for the kipi MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
