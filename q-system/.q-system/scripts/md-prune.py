#!/usr/bin/env python3
"""
Autonomous markdown pruning.

Runs on SessionStart. Checks line counts against budgets.
When a file exceeds its budget, archives oldest sections
(split by ## headers) to memory/archives/.

Exit 0 always (never blocks). Prints warnings to stdout.
"""

import re
import sys
from datetime import datetime
from pathlib import Path


# --- Line budgets per file (soft limit triggers archive) ---
BUDGETS = {
    # canonical/
    "canonical/decisions.md": 150,
    "canonical/discovery.md": 150,
    "canonical/market-intelligence.md": 200,
    "canonical/objections.md": 150,
    "canonical/talk-tracks.md": 150,
    "canonical/engagement-playbook.md": 150,
    "canonical/content-intelligence.md": 150,
    "canonical/verticals.md": 100,
    "canonical/pricing-framework.md": 100,
    "canonical/lead-lifecycle-rules.md": 100,
    # my-project/
    "my-project/relationships.md": 200,
    "my-project/competitive-landscape.md": 150,
    "my-project/current-state.md": 100,
    "my-project/progress.md": 100,
    "my-project/lead-sources.md": 100,
}

# Target: prune down to budget minus this many lines (buffer before next trigger)
PRUNE_BUFFER = 20


def get_qroot():
    """Resolve q-system root."""
    script_dir = Path(__file__).resolve().parent  # scripts/
    return script_dir.parent.parent  # q-system/


def split_sections(content):
    """Split markdown into sections by ## headers.

    Returns list of (header_line, body) tuples.
    First entry may have header_line=None (content before first ##).
    """
    sections = []
    current_header = None
    current_lines = []

    for line in content.split("\n"):
        if re.match(r"^## ", line):
            if current_header is not None or current_lines:
                sections.append((current_header, "\n".join(current_lines)))
            current_header = line
            current_lines = []
        else:
            current_lines.append(line)

    if current_header is not None or current_lines:
        sections.append((current_header, "\n".join(current_lines)))

    return sections


def archive_sections(qroot, rel_path, sections_to_archive):
    """Write archived sections to memory/archives/."""
    archive_dir = qroot / "memory" / "archives"
    archive_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = rel_path.replace("/", "-").replace(".md", "")
    archive_path = archive_dir / f"{safe_name}-{today}.md"

    header = f"# Archived from {rel_path} on {today}\n\n"
    content = header
    for section_header, section_body in sections_to_archive:
        if section_header:
            content += f"{section_header}\n"
        content += f"{section_body}\n\n"

    # Append if archive file already exists (multiple prunes same day)
    mode = "a" if archive_path.exists() else "w"
    with open(archive_path, mode) as f:
        f.write(content)

    return archive_path


def prune_file(qroot, rel_path, budget):
    """Check and prune a single file. Returns (pruned, message)."""
    file_path = qroot / rel_path
    if not file_path.exists():
        return False, None

    content = file_path.read_text()
    line_count = content.count("\n") + 1

    if line_count <= budget:
        return False, None

    sections = split_sections(content)

    # Never prune a file with 0-1 sections (no structure to split on)
    if len(sections) <= 1:
        return False, f"  WARN: {rel_path} is {line_count} lines (budget {budget}) but has no ## sections to split"

    # Calculate target line count (budget minus buffer)
    target = budget - PRUNE_BUFFER

    # Separate pinned vs unpinned sections
    # Pinned sections (contain <!-- pin -->) are never archived
    # Always keep the first section if it has no header (preamble/title)
    running_lines = 0

    # Preserve preamble (content before first ## header)
    preamble = None
    working_sections = list(sections)
    if working_sections and working_sections[0][0] is None:
        preamble = working_sections.pop(0)
        preamble_lines = preamble[1].count("\n") + 1
        running_lines += preamble_lines

    # Tag each section with its original index and whether it's pinned
    indexed = []
    for i, section in enumerate(working_sections):
        header_str = section[0] or ""
        body_str = section[1] or ""
        is_pinned = "<!-- pin -->" in header_str or "<!-- pin -->" in body_str
        section_lines = (section[1].count("\n") + 1)
        if section[0]:
            section_lines += 1
        indexed.append({
            "idx": i,
            "section": section,
            "pinned": is_pinned,
            "lines": section_lines,
        })

    # Count pinned lines (always kept)
    for entry in indexed:
        if entry["pinned"]:
            running_lines += entry["lines"]

    # Walk unpinned from end (newest first), keep until target
    unpinned = [e for e in indexed if not e["pinned"]]
    keep_indices = set()
    archive_entries = []

    for entry in reversed(unpinned):
        if running_lines + entry["lines"] <= target:
            keep_indices.add(entry["idx"])
            running_lines += entry["lines"]
        else:
            archive_entries.insert(0, entry)

    # If nothing to archive, skip
    if not archive_entries:
        return False, None

    # Archive old sections
    archive_path = archive_sections(
        qroot, rel_path, [e["section"] for e in archive_entries]
    )

    # Rebuild file preserving original document order
    # Keep: preamble, all pinned sections, kept unpinned sections
    rebuilt = ""
    if preamble:
        rebuilt += preamble[1].rstrip() + "\n\n"
    for entry in indexed:
        if entry["pinned"] or entry["idx"] in keep_indices:
            section_header, section_body = entry["section"]
            if section_header:
                rebuilt += f"{section_header}\n"
            rebuilt += section_body.rstrip() + "\n\n"

    file_path.write_text(rebuilt.rstrip() + "\n")

    archived_count = len(archive_entries)
    new_lines = rebuilt.count("\n") + 1
    return True, f"  PRUNED: {rel_path} ({line_count} -> {new_lines} lines, {archived_count} sections archived to {archive_path.name})"


def write_prune_log(qroot, messages):
    """Append prune events to persistent log file."""
    log_path = qroot / "memory" / "archives" / "prune-log.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(log_path, "a") as f:
        for msg in messages:
            f.write(f"[{today}] {msg.strip()}\n")


def main():
    qroot = get_qroot()
    pruned_any = False
    messages = []

    for rel_path, budget in BUDGETS.items():
        did_prune, msg = prune_file(qroot, rel_path, budget)
        if msg:
            messages.append(msg)
        if did_prune:
            pruned_any = True

    if messages:
        print("--- MD Prune Check ---")
        for msg in messages:
            print(msg)
        if pruned_any:
            write_prune_log(qroot, [m for m in messages if "PRUNED:" in m])
            print("  Old sections moved to memory/archives/. Review with: ls q-system/memory/archives/")
            print("  Prune history: q-system/memory/archives/prune-log.txt")
        print("")

    sys.exit(0)


if __name__ == "__main__":
    main()
