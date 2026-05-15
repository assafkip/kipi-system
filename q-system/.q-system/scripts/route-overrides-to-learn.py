#!/usr/bin/env python3
"""Route engagement-hitlist overrides into learn-from-correction inputs.

Reads the most recent N (original, posted) pairs from the `copy_edits` table
in `q-system/.q-system/data/metrics.db` and emits a markdown inbox file
under `q-system/output/skill-proposals/_inbox/engagement-{ISO-date}.md`.

The inbox file is the shape the `learn-from-correction` skill consumes:
each section is a complete correction pair the founder can hand to the
skill verbatim. The skill never runs automatically; the founder picks
which corrections are worth proposing principle edits for.

This script never writes to canonical/, skill files, or persona files.
It only reads SQLite and writes one markdown file per run.

CLI:

  python3 q-system/.q-system/scripts/route-overrides-to-learn.py
      Emit the inbox file for the most recent 5 edited copy actions.

  python3 q-system/.q-system/scripts/route-overrides-to-learn.py --limit 10
      Override the default count.

  python3 q-system/.q-system/scripts/route-overrides-to-learn.py --dry-run
      Print the inbox markdown to stdout (no file write).

Exit codes:
  0  success (inbox written or printed)
  2  no edits available (db empty or no 'edited' rows)
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
QROOT = HERE.parent.parent
DB_PATH = QROOT / ".q-system" / "data" / "metrics.db"
INBOX_DIR_RELPATH = "output/skill-proposals/_inbox"
DEFAULT_LIMIT = 5


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------


def load_recent_edits(db_path: Path, limit: int) -> list[dict]:
    """Return the most recent N rows from copy_edits, newest first.

    Each row: {date, contact_name, action_type, original, edited, edit_summary}.
    """
    if not db_path.is_file():
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT date, contact_name, action_type, original, edited, edit_summary "
            "FROM copy_edits "
            "WHERE original IS NOT NULL AND original != '' "
            "AND edited IS NOT NULL AND edited != '' "
            "ORDER BY date DESC, id DESC "
            "LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_inbox(rows: list[dict], generated_at: str | None = None) -> str:
    """Render the inbox markdown."""
    header = _render_header(rows, generated_at or _now_iso())
    if not rows:
        return header + _render_empty_body()
    sections = [_render_correction_section(i, r) for i, r in enumerate(rows, start=1)]
    return header + "\n".join(sections) + _render_footer()


def _render_header(rows: list[dict], generated_at: str) -> str:
    return (
        "# Engagement override inbox\n\n"
        f"Generated: {generated_at}\n"
        f"Source: copy_edits SQLite table ({len(rows)} entries)\n\n"
        "Each section below is a complete (agent_output, human_output) pair "
        "the founder can hand to the `learn-from-correction` skill. Pick the "
        "ones worth proposing a principle edit for; ignore the rest.\n\n"
        "Recommended target skills:\n"
        "- `plugins/kipi-core/skills/founder-voice/SKILL.md` for voice / tone edits\n"
        "- `q-system/canonical/engagement-playbook.md` for engagement-strategy edits\n\n"
        "---\n\n"
    )


def _render_correction_section(index: int, row: dict) -> str:
    contact = row.get("contact_name", "(unknown)")
    action = row.get("action_type", "(unknown)")
    date = row.get("date", "(unknown date)")
    summary = row.get("edit_summary") or "(no summary)"
    original = row.get("original", "").rstrip()
    edited = row.get("edited", "").rstrip()
    return (
        f"## Correction {index}: {contact} ({action}, {date})\n\n"
        f"**Edit summary:** {summary}\n\n"
        f"**Agent output (drafted):**\n\n"
        f"```\n{original}\n```\n\n"
        f"**Human output (posted):**\n\n"
        f"```\n{edited}\n```\n\n"
        f"---\n\n"
    )


def _render_empty_body() -> str:
    return (
        "No edited engagement actions in the metrics database.\n\n"
        "This either means the founder used all drafts as-is, the Phase 1c agent "
        "has not run yet, or the copy_edits table is missing full original + "
        "edited text. Check `q-system/.q-system/agent-pipeline/agents/01c-copy-diff.md` "
        "for the capture contract.\n"
    )


def _render_footer() -> str:
    return (
        "## How to use this inbox\n\n"
        "1. Open a correction section worth learning from.\n"
        "2. Invoke the `learn-from-correction` skill with the agent_output, "
        "human_output, and target_skill from that section.\n"
        "3. The skill writes a proposal markdown to "
        "`q-system/output/skill-proposals/`. Review and merge through git.\n"
        "4. Delete this inbox file after processing; the next run produces a "
        "fresh one from the latest copy_edits rows.\n"
    )


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------


def write_inbox(qroot: Path, content: str, generated_at: str) -> Path:
    """Write the inbox markdown to output/skill-proposals/_inbox/."""
    out_dir = qroot / INBOX_DIR_RELPATH
    out_dir.mkdir(parents=True, exist_ok=True)
    iso_date = generated_at.split("T", 1)[0]
    out_path = out_dir / f"engagement-{iso_date}.md"
    out_path.write_text(content)
    return out_path


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"How many recent edits to include (default {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print to stdout instead of writing the inbox file.",
    )
    args = parser.parse_args()

    rows = load_recent_edits(DB_PATH, args.limit)
    generated_at = _now_iso()
    content = render_inbox(rows, generated_at=generated_at)

    if args.dry_run:
        sys.stdout.write(content)
        return 0 if rows else 2

    out_path = write_inbox(QROOT, content, generated_at)
    sys.stdout.write(f"{out_path}\n")
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
