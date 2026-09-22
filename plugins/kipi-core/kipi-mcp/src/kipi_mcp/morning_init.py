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
        "retired_sources": {},
        "valid": False,
        "validation_failed": [],
    }

    for key, dir_attr, filename, parse in _DIGEST_SOURCES:
        path = getattr(paths, dir_attr) / filename
        if not path.exists():
            digest["warnings"].append(f"{filename} not found")
            continue
        content = path.read_text()
        retirement = _retirement(content)
        if retirement is not None:
            # A retired source is NOT parsed into structured fields: its content
            # is history, and shipping it as current is the ASK-977 defect one
            # layer up. It is recorded instead, so a consumer can tell
            # empty-because-retired from empty-because-none. No warning --
            # warnings stay a missing-file signal.
            digest["retired_sources"][key] = retirement
            continue
        digest[key] = parse(content)

    digest["valid"], digest["validation_failed"] = _validate_digest(digest)
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


_HEADING_RE = re.compile(r"^(#+)[ \t]*(.*)$")

# Only the leading block of a file can retire it. Scanning the whole body would
# let a canonical file that DISCUSSES a retirement retire itself.
_RETIREMENT_HEADER_LINES = 15
_STATUS_SUPERSEDED_RE = re.compile(r"^\s*status\s*:\s*superseded\b", re.IGNORECASE | re.MULTILINE)
_SUPERSEDED_BANNER_RE = re.compile(r"\bSUPERSEDED\b")  # uppercase: a banner, not prose
_DECISION_REF_RE = re.compile(r"\bASK-\d+\b")

_ITEM_CAP = 10
_TEXT_CAP = 500

# Scar ASK-976: the live talk-tracks.md carries NO heading containing
# "definition" -- it names that same content `### One-liner` / `### Category`
# under `## Core Positioning`. Matching the word "definition" alone left the
# `talk_tracks: no definition` check permanently red against a file that does
# define the product, so `valid=True` was unreachable for a LIVE source (the
# thing ASK-977's retirement accounting deliberately refused to fake). These
# are explicit heading names, never a positional fallback, so an unrelated
# section can never satisfy the check by accident.
_DEFINITION_HEADINGS = ("definition", "one-liner", "one liner", "category")


def _heading_depth(line: str) -> int | None:
    """Depth of a markdown heading line, or None when the line is not one."""
    match = _HEADING_RE.match(line)
    return len(match.group(1)) if match else None


def _subtree_end(heads: list[tuple[int, int, str]], index: int) -> int | None:
    """Line index of the next heading at the same or shallower depth."""
    depth = heads[index][1]
    for start, later_depth, _ in heads[index + 1:]:
        if later_depth <= depth:
            return start
    return None


def _split_sections(content: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) with child sections NESTED in the parent.

    Scar ASK-977: the old split treated every heading line as a peer, so the
    live '## Unanswered Questions' -- whose 28 questions all sit under five ###
    children -- parsed to an empty body and the digest shipped questions=[]. A
    section's body now runs to the next heading of the SAME OR SHALLOWER depth,
    which is the ordinary document model. Child heading LINES are dropped from
    the parent body so list-item and [RULE] extraction see content only. A
    document whose headings are all one depth splits exactly as it did before.
    """
    lines = content.splitlines()
    heads = [
        (i, _heading_depth(line), _HEADING_RE.match(line).group(2).strip())
        for i, line in enumerate(lines)
        if _heading_depth(line) is not None
    ]

    sections: list[tuple[str, str]] = []
    preamble = lines[: heads[0][0]] if heads else lines
    if any(line.strip() for line in preamble):
        sections.append(("", "\n".join(preamble)))

    for index, (start, _depth, title) in enumerate(heads):
        end = _subtree_end(heads, index)
        span = lines[start + 1: len(lines) if end is None else end]
        sections.append((title, "\n".join(l for l in span if _heading_depth(l) is None)))
    return sections


def _retirement(content: str) -> dict | None:
    """{'decision': 'ASK-nnn'} when the source's header retires it, else None."""
    header = "\n".join(content.splitlines()[:_RETIREMENT_HEADER_LINES])
    if not (_STATUS_SUPERSEDED_RE.search(header) or _SUPERSEDED_BANNER_RE.search(header)):
        return None
    ref = _DECISION_REF_RE.search(header)
    return {"decision": ref.group(0) if ref else None}


def _accumulate(existing: list[str], items: list[str], cap: int | None = _ITEM_CAP) -> list[str]:
    """Add items to a field instead of REPLACING it, deduped, capped.

    Scar ASK-977: assignment was last-match-wins, so '## Validation Gaps' (0
    items) was overwritten by '## Website Positioning Gap' (8 items) and the
    digest shipped March website notes labelled as validation gaps. Dedup also
    collapses the parent/child pair that nesting now produces.
    """
    merged = list(existing)
    for item in items:
        if item not in merged:
            merged.append(item)
    return merged if cap is None else merged[:cap]


def _accumulate_text(existing: str, body: str) -> str:
    """Append a section body to a TEXT field instead of REPLACING it.

    Scar ASK-977, same shape one field over: assignment was last-match-wins, so
    when two headings feed one field the later one silently erased the earlier.
    The live talk-tracks.md hits exactly that -- `One-liner` and `Category` both
    carry definition content -- so a plain assignment would ship the category
    line alone and drop the one-liner it was standing next to.
    """
    addition = body.strip()
    if not addition or addition in existing:
        return existing[:_TEXT_CAP]
    joined = f"{existing}\n\n{addition}" if existing else addition
    return joined[:_TEXT_CAP]


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
        elif any(name in hl for name in _DEFINITION_HEADINGS):
            result["definition"] = _accumulate_text(result["definition"], body)
        elif "wedge" in hl:
            result["wedge"] = body.strip()[:500]
        elif "banned" in hl:
            result["banned_phrases"] = _accumulate(
                result["banned_phrases"], _extract_list_items(body), cap=None
            )
        elif "detection" in hl or "framing" in hl:
            result["detection_rule"] = body.strip()[:500]
    return result


# A fenced block is literal text. A heading inside one is SAMPLE markup, not a
# section -- the canonical objections.md ships its record shape in a fence, and
# the old parser recorded that sample as a real objection (ASK-992).
_FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")

# A heading that is only a bracketed slot names no objection. The live template
# writes it quoted: ### "[Objection as they say it]".
_PLACEHOLDER_HEADING_RE = re.compile(r"^\[.*\]$")

# Body lines that are document chrome rather than an objection's response.
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_PARENTHETICAL_ONLY_RE = re.compile(r"^\(.*\)$")


def _drop_fenced_blocks(content: str) -> str:
    """Content with every fenced block, markers included, removed."""
    kept, inside = [], False
    for line in content.splitlines():
        if _FENCE_RE.match(line):
            inside = not inside
            continue
        if not inside:
            kept.append(line)
    return "\n".join(kept)


def _headings_with_children(content: str) -> list[bool]:
    """Per heading, in document order: is the next heading deeper than it?

    A heading with a deeper heading under it is a CONTAINER. Nesting (ASK-977)
    means a container also inherits its children's body text, so an empty-body
    test cannot tell the two apart -- the structure has to be read directly.
    """
    depths = [
        depth
        for line in content.splitlines()
        if (depth := _heading_depth(line)) is not None
    ]
    return [
        index + 1 < len(depths) and depths[index + 1] > depths[index]
        for index in range(len(depths))
    ]


def _objection_response(body: str) -> str:
    """Body with chrome (blockquotes, comments, parenthetical stubs) removed."""
    kept = []
    for line in body.splitlines():
        text = _HTML_COMMENT_RE.sub("", line).strip()
        if not text or text.startswith(">") or _PARENTHETICAL_ONLY_RE.match(text):
            continue
        kept.append(text)
    return "\n".join(kept).strip()


def _is_placeholder_heading(heading: str) -> bool:
    text = _HTML_COMMENT_RE.sub("", heading).strip().strip("\"'`").strip()
    return bool(_PLACEHOLDER_HEADING_RE.match(text))


def _parse_objections(content: str) -> list[dict]:
    """Real objection records only; containers, template slots and chrome are not.

    Scar ASK-992: `if heading and body.strip()` accepted every section, so this
    repo's own objections.md parsed to four records -- the document title, the
    `## Format` container, the heading inside the format fence, and
    `## Active Objections` -- and not one objection. Because the paired validity
    check is `len(objections) > 0`, a file holding no objections at all reported
    healthy, which is the reason the check exists and the one case it could not
    catch. It can now go RED for that reason.
    """
    stripped = _drop_fenced_blocks(content)
    flags = _headings_with_children(stripped)
    sections = _split_sections(stripped)
    # _split_sections prepends one ("", preamble) entry when the file opens with
    # text before its first heading; the rest are one per heading in document
    # order, which is exactly what flags indexes.
    heading_sections = sections[len(sections) - len(flags):]

    objections = []
    for (heading, body), has_children in zip(heading_sections, flags):
        if not heading or has_children or _is_placeholder_heading(heading):
            continue
        response = _objection_response(body)
        if not response:
            continue
        sentences = re.split(r"(?<=[.!?])\s+", response)
        objections.append(
            {"name": heading.strip(), "response": " ".join(sentences[:2])[:300]}
        )
    return objections


def _parse_current_state(content: str) -> dict:
    result: dict[str, list[str]] = {"works_today": [], "validated": [], "unvalidated": []}
    for heading, body in _split_sections(content):
        hl = heading.lower()
        items = _extract_list_items(body)
        if "works" in hl and "today" in hl:
            result["works_today"] = _accumulate(result["works_today"], items)
        elif "unvalidated" in hl or "not yet" in hl:
            result["unvalidated"] = _accumulate(result["unvalidated"], items)
        elif "validated" in hl:
            result["validated"] = _accumulate(result["validated"], items)
    return result


def _parse_discovery(content: str) -> dict:
    result: dict[str, list[str]] = {"questions": [], "gaps": []}
    for heading, body in _split_sections(content):
        hl = heading.lower()
        items = _extract_list_items(body)
        if "gap" in hl:
            result["gaps"] = _accumulate(result["gaps"], items)
        elif any(k in hl for k in ("question", "q&a", "top")):
            result["questions"] = _accumulate(result["questions"], items)
    return result


def _parse_decisions(content: str) -> list[dict]:
    decisions: list[dict] = []
    seen: set[str] = set()

    def _add(rule: str, summary: str):
        # Nesting means a parent section can now restate a child's rule; dedup
        # by rule text so one rule never lands twice (ASK-977).
        if rule and rule not in seen:
            seen.add(rule)
            decisions.append({"rule": rule, "summary": summary})

    for heading, body in _split_sections(content):
        if "rule" in heading.lower():
            _add(heading.strip(), body.strip()[:300])
        for match in re.finditer(r"\[RULE\]\s*(.+?)(?:\n|$)", body):
            _add(match.group(1).strip(), "")
    return decisions


# (source key, KipiPaths attribute, filename, parser)
_DIGEST_SOURCES = (
    ("talk_tracks", "canonical_dir", "talk-tracks.md", _parse_talk_tracks),
    ("objections", "canonical_dir", "objections.md", _parse_objections),
    ("current_state", "my_project_dir", "current-state.md", _parse_current_state),
    ("discovery", "canonical_dir", "discovery.md", _parse_discovery),
    ("decisions", "canonical_dir", "decisions.md", _parse_decisions),
)


def _validity_checks(digest: dict) -> list[tuple[str | None, str, bool]]:
    """(source key this check depends on, reason if it fails, did it pass)."""
    return [
        ("talk_tracks", "talk_tracks: no metaphor", bool(digest["talk_tracks"].get("metaphor"))),
        ("talk_tracks", "talk_tracks: no definition", bool(digest["talk_tracks"].get("definition"))),
        ("objections", "objections: none parsed", len(digest["objections"]) > 0),
        ("current_state", "current_state: no works_today items",
         len(digest["current_state"].get("works_today", [])) > 0),
        ("discovery", "discovery: no questions parsed",
         len(digest["discovery"].get("questions", [])) > 0),
        ("decisions", "decisions: none parsed", len(digest["decisions"]) > 0),
        (None, "3 or more canonical files not found", len(digest["warnings"]) < 3),
    ]


def _validate_digest(digest: dict) -> tuple[bool, list[str]]:
    """(valid, reasons). Every failure names itself.

    Scar ASK-977: this returned a bare bool from `sum(checks) >= 5`, so a
    caller saw valid=False with nothing to act on. Worse, three of the seven
    checks read sources retired under ASK-510 (talk-tracks, current-state):
    they could never pass, which put the 5-of-7 bar out of reach and made
    valid=False permanent and meaningless. Checks whose source is retired drop
    out of the accounting entirely; every check that still APPLIES must pass.
    """
    retired = digest.get("retired_sources", {})
    failed = [
        reason
        for source, reason, passed in _validity_checks(digest)
        if source not in retired and not passed
    ]
    return not failed, failed
