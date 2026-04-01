from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Public API ──


def preflight(paths) -> dict:
    """Check file existence and content validity. Replaces 00-preflight agent."""
    required = {
        "talk_tracks": paths.canonical_dir / "talk-tracks.md",
        "objections": paths.canonical_dir / "objections.md",
        "relationships": paths.my_project_dir / "relationships.md",
    }
    optional = {
        "handoff": paths.memory_dir / "last-handoff.md",
    }

    files = {}
    content_warnings = []
    ready = True

    for name, path in required.items():
        if not path.exists():
            files[name] = False
            ready = False
        elif path.stat().st_size < 50:
            files[name] = "empty"
            content_warnings.append(f"{name} exists but appears empty ({path.stat().st_size} bytes). Re-run /q-setup.")
            ready = False
        else:
            files[name] = True

    for name, path in optional.items():
        files[name] = path.exists()

    return {
        "files": files,
        "ready": ready,
        "content_warnings": content_warnings,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }


def session_bootstrap(paths) -> dict:
    """Recover state from previous session. Replaces 00-session-bootstrap agent."""
    result = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "action_cards": [],
        "missed_debriefs": [],
        "loop_stats": {"open": 0, "level_0": 0, "level_1": 0, "level_2": 0, "level_3": 0},
        "stalls": [],
        "checksums": {},
    }

    # Action cards from last morning log
    logs = sorted(paths.output_dir.glob("morning-log-*.json"), reverse=True)
    if logs:
        try:
            data = json.loads(logs[0].read_text())
            cards = data.get("action_cards", [])
            result["action_cards"] = [c for c in cards if not c.get("confirmed", False)]
        except (json.JSONDecodeError, KeyError):
            pass

    # Loop stats
    loops_file = paths.output_dir / "open-loops.json"
    if loops_file.exists():
        try:
            loops = json.loads(loops_file.read_text())
            open_loops = [l for l in loops if l.get("status") == "open"]
            result["loop_stats"]["open"] = len(open_loops)
            for loop in open_loops:
                level = min(loop.get("escalation_level", 0), 3)
                result["loop_stats"][f"level_{level}"] += 1
        except (json.JSONDecodeError, KeyError):
            pass

    # Stall detection
    rel_file = paths.my_project_dir / "relationships.md"
    if rel_file.exists():
        content = rel_file.read_text()
        today = datetime.now()
        for match in re.finditer(
            r"(?:last.?contact|last_contact)[:\s]+(\d{4}-\d{2}-\d{2})",
            content,
            re.IGNORECASE,
        ):
            try:
                contact_date = datetime.strptime(match.group(1), "%Y-%m-%d")
                days_stale = (today - contact_date).days
                if days_stale > 14:
                    start = max(0, match.start() - 300)
                    context = content[start : match.start()]
                    name_match = re.search(
                        r"^#+\s*(.+?)$|^\*\*(.+?)\*\*", context, re.MULTILINE
                    )
                    name = "Unknown"
                    if name_match:
                        name = (name_match.group(1) or name_match.group(2)).strip()
                    result["stalls"].append(
                        {
                            "contact": name,
                            "last_contact": match.group(1),
                            "days_stale": days_stale,
                        }
                    )
            except ValueError:
                pass

    # Canonical checksums
    canonical_files = {
        "talk_tracks": paths.canonical_dir / "talk-tracks.md",
        "objections": paths.canonical_dir / "objections.md",
        "current_state": paths.my_project_dir / "current-state.md",
        "discovery": paths.canonical_dir / "discovery.md",
        "decisions": paths.canonical_dir / "decisions.md",
    }
    for name, path in canonical_files.items():
        if path.exists():
            result["checksums"][name] = hashlib.sha256(
                path.read_text().encode()
            ).hexdigest()[:16]

    # Cross-session drift detection
    drift = []
    logs = sorted(paths.output_dir.glob("morning-log-*.json"), reverse=True)
    if logs:
        try:
            prev_log = json.loads(logs[0].read_text())
            prev_checksums = prev_log.get("state_checksums", {}).get("session_end", {})
            if prev_checksums:
                for name, current_hash in result["checksums"].items():
                    prev_hash = prev_checksums.get(name)
                    if prev_hash and prev_hash != current_hash:
                        drift.append({"file": name, "previous": prev_hash, "current": current_hash})
        except (json.JSONDecodeError, KeyError):
            pass
    result["canonical_drift"] = drift

    # Recently closed loops for transparency
    try:
        from kipi_mcp.loop_tracker import LoopTracker
        lt = LoopTracker(db_path=paths.metrics_db)
        lt.init_db()
        recent = lt.recently_closed(days=2)
        result["recently_closed_loops"] = recent
        stats = lt.stats()
        if stats.get("open", 0) > 0 or stats.get("recently_closed", 0) > 0:
            result["loop_stats"] = stats
        else:
            result["loop_stats"]["recently_closed"] = stats.get("recently_closed", 0)
    except Exception:
        result["recently_closed_loops"] = []

    return result


def canonical_digest(paths) -> dict:
    """Extract structured data from canonical files. Replaces 00c-canonical-digest agent."""
    digest = {
        "talk_tracks": {},
        "objections": [],
        "current_state": {},
        "discovery": {},
        "decisions": [],
        "warnings": [],
        "valid": False,
    }

    tt_path = paths.canonical_dir / "talk-tracks.md"
    if tt_path.exists():
        digest["talk_tracks"] = _parse_talk_tracks(tt_path.read_text())
    else:
        digest["warnings"].append("talk-tracks.md not found")

    obj_path = paths.canonical_dir / "objections.md"
    if obj_path.exists():
        digest["objections"] = _parse_objections(obj_path.read_text())
    else:
        digest["warnings"].append("objections.md not found")

    cs_path = paths.my_project_dir / "current-state.md"
    if cs_path.exists():
        digest["current_state"] = _parse_current_state(cs_path.read_text())
    else:
        digest["warnings"].append("current-state.md not found")

    disc_path = paths.canonical_dir / "discovery.md"
    if disc_path.exists():
        digest["discovery"] = _parse_discovery(disc_path.read_text())
    else:
        digest["warnings"].append("discovery.md not found")

    dec_path = paths.canonical_dir / "decisions.md"
    if dec_path.exists():
        digest["decisions"] = _parse_decisions(dec_path.read_text())
    else:
        digest["warnings"].append("decisions.md not found")

    digest["valid"] = _validate_digest(digest)
    return digest


def _check_db_integrity(db_path: Path) -> dict:
    """Run PRAGMA integrity_check on SQLite database."""
    import sqlite3
    if not db_path.exists():
        return {"status": "no_db"}
    conn = sqlite3.connect(str(db_path))
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        return {"status": "ok" if result == "ok" else "corrupted", "detail": result}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
    finally:
        conn.close()


def auto_backup(backup_manager, max_backups: int = 5) -> dict:
    """Create a backup and rotate old ones."""
    try:
        result = backup_manager.backup()
        rotate_result = backup_manager.rotate(max_backups)
        return {"backup": result, "rotation": rotate_result}
    except Exception as e:
        return {"error": str(e)}


def retry_notion_queue(harvest_store) -> dict:
    """Check for pending Notion writes from previous failed runs."""
    if harvest_store is None:
        return {"pending": 0}
    try:
        pending = harvest_store.get_pending_notion_writes()
    except (AttributeError, Exception):
        return {"pending": 0}
    return {
        "pending": len(pending),
        "items": [{"id": p["id"], "agent": p["source_agent"], "attempts": p["attempts"]} for p in pending],
    }


def morning_init(paths, energy_level: int, harvest_store=None, backup_manager=None) -> dict:
    """Combined init: preflight + bootstrap + digest + cleanup + energy.

    THE one call that replaces phases 0-0.7 of the old orchestrator.
    """
    date = datetime.now().strftime("%Y-%m-%d")

    # Auto-cleanup transient data
    cleanup_result = {}
    if harvest_store:
        cleanup_result = harvest_store.cleanup(days=7)
    _clean_old_files(paths.output_dir, "morning-log-*.json", days=10)
    _clean_old_files(paths.output_dir, "schedule-data-*.json", days=10)
    _clean_old_files(paths.output_dir, "daily-schedule-*.html", days=10)

    # DB integrity check (all three databases)
    db_integrity = {
        "metrics": _check_db_integrity(paths.metrics_db),
        "harvest": _check_db_integrity(paths.harvest_db),
        "system": _check_db_integrity(paths.system_db),
    }

    # Auto-backup with rotation (after all other init)
    backup_result = {}
    if backup_manager:
        backup_result = auto_backup(backup_manager)

    # Check for today's handoff (session resume)
    resume_from = None
    if harvest_store:
        try:
            handoff = harvest_store.get_handoff(date)
            if handoff:
                resume_from = handoff
        except (AttributeError, Exception):
            pass

    return {
        "date": date,
        "preflight": preflight(paths),
        "bootstrap": session_bootstrap(paths),
        "canonical_digest": canonical_digest(paths),
        "energy": _energy_table(energy_level),
        "cleanup": cleanup_result,
        "db_integrity": db_integrity,
        "backup": backup_result,
        "notion_queue": retry_notion_queue(harvest_store),
        "resume_from": resume_from,
    }


def gate_check(paths, phase: int, date: str = "") -> dict:
    """Check if all prior phases are logged before a gate phase.

    Reads the morning log and verifies every phase before the gate
    is logged as done or skipped.
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    log_file = paths.output_dir / f"morning-log-{date}.json"
    if not log_file.exists():
        return {"passed": False, "error": "morning log not found", "missing": []}

    try:
        log = json.loads(log_file.read_text())
    except json.JSONDecodeError:
        return {"passed": False, "error": "morning log invalid JSON", "missing": []}

    steps = log.get("steps", {})

    expected_phases = {
        6: ["phase_0_init", "phase_1_harvest", "phase_2_analysis",
            "phase_3_content", "phase_4_pipeline", "phase_5_compliance"],
        7: ["phase_0_init", "phase_1_harvest", "phase_2_analysis",
            "phase_3_content", "phase_4_pipeline", "phase_5_compliance",
            "phase_6_synthesis"],
        8: ["phase_0_init", "phase_1_harvest", "phase_2_analysis",
            "phase_3_content", "phase_4_pipeline", "phase_5_compliance",
            "phase_6_synthesis", "phase_7_build"],
    }

    required = expected_phases.get(phase, [])
    missing = []
    for step_id in required:
        step = steps.get(step_id)
        if not step or step.get("status") not in ("done", "skipped"):
            missing.append(step_id)

    return {
        "passed": len(missing) == 0,
        "gate_phase": phase,
        "missing": missing,
        "phases_checked": len(required),
    }


def deliverables_check(paths, date: str = "", harvest_store=None) -> dict:
    """Check that required deliverables exist in the harvest ledger.

    Queries harvest_records for expected agent outputs based on day of week.
    Returns pass/fail with details on what's missing.
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    day_of_week = datetime.strptime(date, "%Y-%m-%d").strftime("%A").lower()

    result = {
        "date": date,
        "day": day_of_week,
        "passed": True,
        "missing": [],
        "checked": [],
    }

    def _check_agent(source_name: str, label: str = ""):
        desc = label or source_name
        if harvest_store is None:
            result["missing"].append(f"{desc} (no harvest store)")
            result["passed"] = False
            return
        records = harvest_store.get_records(source_name=source_name, days=1, limit=1)
        if not records:
            result["missing"].append(desc)
            result["passed"] = False
        else:
            result["checked"].append(desc)

    # Day-invariant deliverables
    _check_agent("agent:pipeline-followup", "pipeline follow-ups")
    _check_agent("agent:engagement-hitlist", "engagement hitlist")
    _check_agent("agent:outbound-detection", "outbound detection")
    _check_agent("agent:loop-review", "loop review")

    # Content deliverables by day
    if day_of_week in ("monday", "wednesday", "friday"):
        _check_agent("agent:signals-content", "signals content (Mon/Wed/Fri)")
    if day_of_week in ("tuesday", "thursday"):
        _check_agent("agent:signals-content", "TL content (Tue/Thu)")
    if day_of_week == "monday":
        _check_agent("agent:content-intel", "content intelligence (Monday)")

    # Value routing
    _check_agent("agent:value-routing", "value routing")

    return result


# ── Helpers ──


_ENERGY_TABLES = {
    1: {"level": 1, "label": "wiped", "max_hitlist": 3, "skip_deep_focus": True, "batch_quick_wins": True},
    2: {"level": 2, "label": "low", "max_hitlist": 5, "skip_deep_focus": True, "batch_quick_wins": True},
    3: {"level": 3, "label": "okay", "max_hitlist": 10, "skip_deep_focus": False, "batch_quick_wins": False},
    4: {"level": 4, "label": "good", "max_hitlist": 15, "skip_deep_focus": False, "batch_quick_wins": False},
    5: {"level": 5, "label": "locked_in", "max_hitlist": 999, "skip_deep_focus": False, "batch_quick_wins": False},
}


def _energy_table(level: int) -> dict:
    return _ENERGY_TABLES.get(max(1, min(5, level)), _ENERGY_TABLES[3])


def _clean_old_files(directory: Path, pattern: str, days: int = 10):
    """Delete files matching glob pattern older than N days."""
    if not directory.exists():
        return
    cutoff = datetime.now() - timedelta(days=days)
    for f in directory.glob(pattern):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink()
        except (OSError, ValueError):
            pass


def _clean_old_bus(bus_dir: Path, days: int = 3):
    if not bus_dir.exists():
        return
    cutoff = datetime.now() - timedelta(days=days)
    for child in bus_dir.iterdir():
        if child.is_dir():
            try:
                dir_date = datetime.strptime(child.name, "%Y-%m-%d")
                if dir_date < cutoff:
                    shutil.rmtree(child)
            except ValueError:
                pass


def _split_sections(content: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading = ""
    body: list[str] = []
    for line in content.splitlines():
        if line.startswith("#"):
            if heading or body:
                sections.append((heading, "\n".join(body)))
            heading = line.lstrip("#").strip()
            body = []
        else:
            body.append(line)
    if heading or body:
        sections.append((heading, "\n".join(body)))
    return sections


def _extract_list_items(text: str) -> list[str]:
    return [
        line.lstrip("-*").strip()
        for line in text.strip().splitlines()
        if line.strip().startswith(("-", "*")) and line.lstrip("-*").strip()
    ]


def _parse_talk_tracks(content: str) -> dict:
    result = {"metaphor": "", "definition": "", "wedge": "", "banned_phrases": [], "detection_rule": ""}
    for heading, body in _split_sections(content):
        hl = heading.lower()
        if "metaphor" in hl:
            result["metaphor"] = body.strip()[:500]
        elif "definition" in hl:
            result["definition"] = body.strip()[:500]
        elif "wedge" in hl:
            result["wedge"] = body.strip()[:500]
        elif "banned" in hl:
            result["banned_phrases"] = _extract_list_items(body)
        elif "detection" in hl or "framing" in hl:
            result["detection_rule"] = body.strip()[:500]
    return result


def _parse_objections(content: str) -> list[dict]:
    objections = []
    for heading, body in _split_sections(content):
        if heading and body.strip():
            sentences = re.split(r"(?<=[.!?])\s+", body.strip())
            response = " ".join(sentences[:2])
            objections.append({"name": heading.strip(), "response": response[:300]})
    return objections


def _parse_current_state(content: str) -> dict:
    result: dict[str, list[str]] = {"works_today": [], "validated": [], "unvalidated": []}
    for heading, body in _split_sections(content):
        hl = heading.lower()
        items = _extract_list_items(body)
        if "works" in hl and "today" in hl:
            result["works_today"] = items
        elif "unvalidated" in hl or "not yet" in hl:
            result["unvalidated"] = items
        elif "validated" in hl:
            result["validated"] = items
    return result


def _parse_discovery(content: str) -> dict:
    result: dict[str, list[str]] = {"questions": [], "gaps": []}
    for heading, body in _split_sections(content):
        hl = heading.lower()
        items = _extract_list_items(body)
        if "gap" in hl:
            result["gaps"] = items[:10]
        elif any(k in hl for k in ("question", "q&a", "top")):
            result["questions"] = items[:10]
    return result


def _parse_decisions(content: str) -> list[dict]:
    decisions = []
    for heading, body in _split_sections(content):
        if "rule" in heading.lower():
            decisions.append({"rule": heading.strip(), "summary": body.strip()[:300]})
        for match in re.finditer(r"\[RULE\]\s*(.+?)(?:\n|$)", body):
            decisions.append({"rule": match.group(1).strip(), "summary": ""})
    return decisions


def _validate_digest(digest: dict) -> bool:
    checks = [
        bool(digest["talk_tracks"].get("metaphor")),
        bool(digest["talk_tracks"].get("definition")),
        len(digest["objections"]) > 0,
        len(digest["current_state"].get("works_today", [])) > 0,
        len(digest["discovery"].get("questions", [])) > 0,
        len(digest["decisions"]) > 0,
        len(digest["warnings"]) < 3,
    ]
    return sum(checks) >= 5
