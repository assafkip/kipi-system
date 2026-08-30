#!/usr/bin/env python3
"""
Memory Lifecycle Hook (SessionStart).

Three jobs, all deterministic, no LLM:
1. Freshness warnings - print [FAST] for fast-decay memories
2. Auto-archive - move stale memories to archived/
3. Decay promotion - promote verified memories to slower decay

Runs on SessionStart. Exit 0 always (never blocks).
"""

import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path


# --- Staleness thresholds (days without verification or update) ---
ARCHIVE_THRESHOLDS = {
    "fast": 14,
    "medium": 60,
    "slow": None,  # never auto-archive
}

# --- Promotion rules ---
# (current_decay, min_verify_count, min_age_days) -> new_decay
PROMOTION_RULES = [
    ("fast", 3, 30, "medium"),
    ("medium", 5, 60, "slow"),
]


def get_memory_dir():
    """Compute the auto-memory directory from project dir."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    project_slug = project_dir.replace("/", "-")
    return Path.home() / ".claude" / "projects" / project_slug / "memory"


def parse_frontmatter(content):
    """Extract frontmatter dict from markdown content."""
    if not content.startswith("---"):
        return {}

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}

    fm = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip()
    return fm


def update_frontmatter(content, updates):
    """Update frontmatter fields in markdown content. Returns new content."""
    if not content.startswith("---"):
        return content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return content

    lines = parts[1].strip().split("\n")
    updated_keys = set()

    new_lines = []
    for line in lines:
        if ":" in line:
            key = line.split(":", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}: {updates[key]}")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}: {val}")

    return f"---\n{chr(10).join(new_lines)}\n---{parts[2]}"


def get_file_age_days(file_path):
    """Get file age in days from mtime."""
    mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
    return (datetime.now() - mtime).days


def get_last_activity_date(fm, file_path):
    """Get the most recent activity date for a memory file."""
    dates = []

    if fm.get("last_verified"):
        try:
            dates.append(datetime.strptime(fm["last_verified"], "%Y-%m-%d"))
        except ValueError:
            pass

    dates.append(datetime.fromtimestamp(file_path.stat().st_mtime))

    return max(dates)


def load_state(memory_dir):
    """Load lifecycle state file."""
    state_file = memory_dir / ".memory-lifecycle-state.json"
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {"last_archive_run": None, "last_promotion_run": None, "archived": []}


def save_state(memory_dir, state):
    """Save lifecycle state file."""
    state_file = memory_dir / ".memory-lifecycle-state.json"
    state_file.write_text(json.dumps(state, indent=2) + "\n")


def update_memory_index(memory_dir):
    """Rebuild MEMORY.md index from current memory files."""
    index_path = memory_dir / "MEMORY.md"
    entries = []

    for md_file in sorted(memory_dir.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue

        content = md_file.read_text()
        fm = parse_frontmatter(content)
        name = fm.get("name", md_file.stem)
        desc = fm.get("description", "")
        decay = fm.get("decay", "slow")

        prefix = "[fast] " if decay == "fast" else ""
        hook = f" - {desc}" if desc else ""
        entries.append(f"- {prefix}[{name}]({md_file.name}){hook}")

    index_path.write_text("\n".join(entries) + "\n")


def check_freshness(memory_dir):
    """Print [FAST] warnings for fast-decay memories. Returns list of (name, filename)."""
    fast_memories = []

    for md_file in sorted(memory_dir.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue

        try:
            content = md_file.read_text()
        except (IOError, OSError):
            continue

        fm = parse_frontmatter(content)
        if fm.get("decay") == "fast":
            name = fm.get("name", md_file.stem)
            fast_memories.append((name, md_file.name))

    return fast_memories


def run_archive(memory_dir, state):
    """Archive stale memories. Returns list of archived filenames."""
    archive_dir = memory_dir / "archived"
    archived = []
    today = datetime.now()

    for md_file in sorted(memory_dir.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue

        try:
            content = md_file.read_text()
        except (IOError, OSError):
            continue

        fm = parse_frontmatter(content)
        decay = fm.get("decay", "slow")
        threshold = ARCHIVE_THRESHOLDS.get(decay)

        if threshold is None:
            continue

        last_activity = get_last_activity_date(fm, md_file)
        days_stale = (today - last_activity).days

        if days_stale >= threshold:
            archive_dir.mkdir(exist_ok=True)
            dest = archive_dir / md_file.name
            shutil.move(str(md_file), str(dest))
            archived.append(md_file.name)

    if archived:
        state["archived"] = state.get("archived", []) + archived
        state["last_archive_run"] = today.strftime("%Y-%m-%d")

    return archived


def run_promotion(memory_dir):
    """Promote verified memories to slower decay. Returns list of (filename, old, new)."""
    promoted = []

    for md_file in sorted(memory_dir.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue

        try:
            content = md_file.read_text()
        except (IOError, OSError):
            continue

        fm = parse_frontmatter(content)
        decay = fm.get("decay", "slow")
        verify_count = int(fm.get("verify_count", "0"))
        file_age = get_file_age_days(md_file)

        for rule_decay, min_count, min_age, new_decay in PROMOTION_RULES:
            if decay == rule_decay and verify_count >= min_count and file_age >= min_age:
                new_content = update_frontmatter(content, {"decay": new_decay})
                md_file.write_text(new_content)
                promoted.append((md_file.name, decay, new_decay))
                break

    return promoted


def main():
    memory_dir = get_memory_dir()
    if not memory_dir.exists():
        sys.exit(0)

    state = load_state(memory_dir)
    output_lines = []

    # 1. Freshness warnings
    fast_memories = check_freshness(memory_dir)
    if fast_memories:
        output_lines.append("MEMORY FRESHNESS WARNING")
        output_lines.append("=" * 50)
        output_lines.append("These memories are marked decay: fast.")
        output_lines.append("MUST verify before acting on their content.")
        output_lines.append("Either tool-verify OR ask the user.")
        output_lines.append("")
        for name, filename in fast_memories:
            output_lines.append(f"  [FAST] {name} ({filename})")
        output_lines.append("")

    # 2. Auto-archive stale memories
    archived = run_archive(memory_dir, state)
    if archived:
        output_lines.append(f"ARCHIVED {len(archived)} stale memories:")
        for filename in archived:
            output_lines.append(f"  -> archived/{filename}")
        output_lines.append("(Moved to memory/archived/. Reversible.)")
        output_lines.append("")

    # 3. Decay promotion
    promoted = run_promotion(memory_dir)
    if promoted:
        output_lines.append(f"PROMOTED {len(promoted)} verified memories:")
        for filename, old, new in promoted:
            output_lines.append(f"  {filename}: {old} -> {new}")
        output_lines.append("")

    # 4. Pitfall detection from last session
    try:
        from detect_pitfalls import run_pitfall_detection
        pitfalls = run_pitfall_detection()
    except ImportError:
        # detect-pitfalls.py not found (standalone run), try relative import
        try:
            hook_dir = os.path.dirname(os.path.abspath(__file__))
            sys.path.insert(0, hook_dir)
            from detect_pitfalls import run_pitfall_detection
            pitfalls = run_pitfall_detection()
        except ImportError:
            pitfalls = []

    if pitfalls:
        output_lines.append(f"PITFALL DETECTION: {len(pitfalls)} correction(s) from last session")
        for f in pitfalls:
            output_lines.append(f"  -> {f}")
        output_lines.append("(Auto-created fast-decay memories. Review and update the originals.)")
        output_lines.append("")

    # 5. Update index if anything changed
    if archived or promoted or pitfalls:
        update_memory_index(memory_dir)

    # 6. Save state
    save_state(memory_dir, state)

    # 7. Print output
    if output_lines:
        output_lines.append("=" * 50)
        print("\n".join(output_lines))

    sys.exit(0)


if __name__ == "__main__":
    main()
