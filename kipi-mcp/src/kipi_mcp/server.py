import sys
import json
import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

from kipi_mcp.paths import KipiPaths
from kipi_mcp.registry import RegistryManager
from kipi_mcp.git_ops import GitOps
from kipi_mcp.step_logger import StepLogger
from kipi_mcp.loop_tracker import LoopTracker
from kipi_mcp.step_loader import StepLoader
from kipi_mcp.template_manager import TemplateManager
from kipi_mcp.migrator import Migrator

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
        "kipi_load_step / kipi_build_schedule / kipi_create_template (content). "
        "Resources: kipi://paths, kipi://instances, kipi://loops/open, "
        "kipi://loops/stats, kipi://steps/{step_id}. "
        "Read kipi://paths first to get resolved directory paths."
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

step_loader = StepLoader(
    steps_dir=paths.steps_dir,
    commands_file=paths.commands_file,
)

template_manager = TemplateManager(
    templates_dir=paths.templates_dir,
    output_dir=paths.output_dir,
    schedule_template=paths.schedule_template,
)

try:
    from kipi_mcp.validator import Validator
    validator = Validator(kipi_home=paths.repo_dir, registry=registry)
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
        "config_dir": str(paths.config_dir),
        "data_dir": str(paths.data_dir),
        "state_dir": str(paths.state_dir),
        "repo_dir": str(paths.repo_dir),
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


@mcp.resource("kipi://steps/{step_id}")
def resource_step(step_id: str) -> str:
    """Morning routine step definition by ID (e.g. "0a", "3", "5.9b", "11")."""
    return step_loader.load(step_id)


# ============================================================
# Instance Management (4 tools)
# ============================================================


@mcp.tool()
def kipi_migrate(dry_run: bool = True) -> str:
    """Migrate user data from git repo to XDG directories.

    Args:
        dry_run: If True, report what would happen without copying. Default True for safety.
    """
    try:
        m = Migrator(paths)
        return json.dumps(m.migrate(dry_run=dry_run))
    except Exception as e:
        logger.error("kipi_migrate failed", exc_info=True)
        raise ToolError(str(e))


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
def kipi_load_step(step_id: str) -> str:
    """Load a morning routine step definition by ID.

    Args:
        step_id: Step identifier (e.g. "0a", "3", "5.9b", "11").
    """
    try:
        return step_loader.load(step_id)
    except Exception as e:
        logger.error("kipi_load_step failed", exc_info=True)
        raise ToolError(str(e))


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


def main():
    """Entry point for the kipi MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
