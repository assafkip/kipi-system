#!/usr/bin/env python3
"""
Memory Freshness Check Hook.

Scans the auto-memory directory for memories marked `decay: fast` in their
frontmatter, and prints a freshness warning to stdout. Output appears in
the conversation as system context, ensuring the model sees which memories
require verification before acting.

Runs on SessionStart. Exit code 0 always (never blocks).

Why deterministic enforcement matters:
The .claude/rules/memory-freshness.md rule file does not auto-load reliably
because path-scoped rule loading targets project files, not the
auto-memory directory which lives outside the project tree. This script
reads memory file frontmatter directly and injects warnings, removing the
dependency on the model remembering to read a rules file.

Backed by .claude/rules/memory-freshness.md (the human-readable spec).
"""

import os
import sys
from pathlib import Path


def get_project_dir():
    return os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())


def get_memory_dir():
    """Compute the auto-memory directory path from project dir."""
    project_dir = get_project_dir()
    project_slug = project_dir.replace("/", "-")
    return Path.home() / ".claude" / "projects" / project_slug / "memory"


def parse_memory_file(file_path):
    """Extract decay value and name from frontmatter. Returns (decay, name)."""
    try:
        content = file_path.read_text()
    except (IOError, OSError):
        return ("slow", file_path.stem)

    if not content.startswith("---"):
        return ("slow", file_path.stem)

    parts = content.split("---", 2)
    if len(parts) < 3:
        return ("slow", file_path.stem)

    frontmatter = parts[1]
    decay = "slow"
    name = file_path.stem
    for line in frontmatter.split("\n"):
        stripped = line.strip()
        if stripped.startswith("decay:"):
            decay = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("name:"):
            name = stripped.split(":", 1)[1].strip()
    return (decay, name)


def main():
    memory_dir = get_memory_dir()
    if not memory_dir.exists():
        sys.exit(0)

    fast_memories = []
    for md_file in sorted(memory_dir.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue
        decay, name = parse_memory_file(md_file)
        if decay == "fast":
            fast_memories.append((name, md_file.name))

    if not fast_memories:
        sys.exit(0)

    print("MEMORY FRESHNESS WARNING (auto-injected by hook)")
    print("=" * 50)
    print("The following memories are marked decay: fast.")
    print("MUST verify before acting on their content.")
    print("Either tool-verify (Notion/PostHog/Calendar/file) OR ask founder.")
    print()
    for name, filename in fast_memories:
        print(f"  [FAST] {name} ({filename})")
    print()
    print("Skip verification only if action is informational, not asserting state.")
    print("=" * 50)

    sys.exit(0)


if __name__ == "__main__":
    main()
