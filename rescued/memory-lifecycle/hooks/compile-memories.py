#!/usr/bin/env python3
"""
Memory Compilation Candidate Finder.

Scans archived and active memories for compilation opportunities:
clusters of 3+ related memories that could be merged into a single
slow-decay summary.

This script is deterministic. It identifies candidates and prints
a compilation plan. The actual merging is done by Claude following
the rules in memory-freshness.md (requires LLM for summarization).

Borrowed from: claude-memory-compiler's daily-log -> knowledge-article
compilation pattern.

Usage: python3 compile-memories.py [--dry-run]
"""

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path


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


def get_body(content):
    """Extract body text after frontmatter."""
    if not content.startswith("---"):
        return content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return content
    return parts[2].strip()


def extract_cluster_key(filename, fm):
    """Extract a cluster key from filename and frontmatter.

    Groups memories by:
    1. Type prefix (project_, feedback_, user_, reference_)
    2. Subject extracted from name (first 2-3 meaningful words)
    """
    mem_type = fm.get("type", "unknown")
    name = fm.get("name", filename)

    # Extract subject words (skip common prefixes and version/status suffixes)
    skip_words = {"pitfall", "update", "status", "note", "re", "the", "a", "an",
                  "v1", "v2", "v3", "v4", "v5", "old", "new", "latest", "current",
                  "corrected", "compiled"}
    words = re.findall(r"[a-zA-Z]+", name.lower())
    subject_words = [w for w in words if w not in skip_words][:2]

    if not subject_words:
        return f"{mem_type}/_ungrouped"

    return f"{mem_type}/{'-'.join(subject_words)}"


def find_clusters(memory_dir):
    """Find groups of 3+ related memories that could be compiled.

    Searches both active memories and archived ones.
    """
    all_memories = defaultdict(list)

    # Scan active memories
    for md_file in sorted(memory_dir.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue
        try:
            content = md_file.read_text()
        except (IOError, OSError):
            continue

        fm = parse_frontmatter(content)
        key = extract_cluster_key(md_file.stem, fm)
        all_memories[key].append({
            "path": md_file,
            "filename": md_file.name,
            "name": fm.get("name", md_file.stem),
            "decay": fm.get("decay", "slow"),
            "type": fm.get("type", "unknown"),
            "location": "active",
            "body_preview": get_body(content)[:100],
        })

    # Scan archived memories
    archive_dir = memory_dir / "archived"
    if archive_dir.exists():
        for md_file in sorted(archive_dir.glob("*.md")):
            try:
                content = md_file.read_text()
            except (IOError, OSError):
                continue

            fm = parse_frontmatter(content)
            key = extract_cluster_key(md_file.stem, fm)
            all_memories[key].append({
                "path": md_file,
                "filename": md_file.name,
                "name": fm.get("name", md_file.stem),
                "decay": fm.get("decay", "slow"),
                "type": fm.get("type", "unknown"),
                "location": "archived",
                "body_preview": get_body(content)[:100],
            })

    # Filter to clusters of 3+
    clusters = {k: v for k, v in all_memories.items() if len(v) >= 3}
    return clusters


def print_compilation_plan(clusters):
    """Print a human-readable compilation plan."""
    if not clusters:
        print("No compilation candidates found.")
        print("Clusters need 3+ related memories to qualify.")
        return

    print(f"MEMORY COMPILATION CANDIDATES: {len(clusters)} cluster(s)")
    print("=" * 60)
    print()

    for key, memories in sorted(clusters.items()):
        mem_type, subject = key.split("/", 1)
        active_count = sum(1 for m in memories if m["location"] == "active")
        archived_count = sum(1 for m in memories if m["location"] == "archived")

        print(f"Cluster: {subject} ({mem_type})")
        print(f"  {len(memories)} memories ({active_count} active, {archived_count} archived)")
        print()

        for mem in memories:
            loc_tag = "[archived]" if mem["location"] == "archived" else f"[{mem['decay']}]"
            print(f"    {loc_tag} {mem['filename']}")
            print(f"           {mem['name']}")
            if mem["body_preview"]:
                preview = mem["body_preview"].replace("\n", " ")[:80]
                print(f"           \"{preview}...\"")
            print()

        print(f"  Suggested compiled name: {mem_type}_{subject.replace('-', '_')}_compiled.md")
        print(f"  Suggested decay: slow")
        print()
        print("-" * 60)
        print()


def generate_compilation_prompt(clusters):
    """Generate a prompt Claude can use to compile the memories."""
    if not clusters:
        return ""

    lines = []
    lines.append("## Memory Compilation Instructions")
    lines.append("")
    lines.append("For each cluster below, create ONE new slow-decay memory that captures")
    lines.append("the essential knowledge from all source memories. Then archive the sources.")
    lines.append("")

    for key, memories in sorted(clusters.items()):
        mem_type, subject = key.split("/", 1)
        lines.append(f"### Cluster: {subject}")
        lines.append(f"Type: {mem_type}")
        lines.append(f"Source files ({len(memories)}):")
        for mem in memories:
            lines.append(f"  - `{mem['path']}`")
        lines.append("")
        lines.append(f"Output file: `{mem_type}_{subject.replace('-', '_')}_compiled.md`")
        lines.append("Decay: slow")
        lines.append("")
        lines.append("Compilation rules:")
        lines.append("- Keep the most recent factual state, not the history")
        lines.append("- Preserve any decisions or lessons learned")
        lines.append("- Drop timestamps and status updates that are no longer relevant")
        lines.append("- If facts conflict between memories, keep the most recent one")
        lines.append("- Add `origin: compiled` to frontmatter")
        lines.append("")

    return "\n".join(lines)


def main():
    memory_dir = get_memory_dir()
    if not memory_dir.exists():
        print("No memory directory found.")
        sys.exit(0)

    dry_run = "--dry-run" in sys.argv

    clusters = find_clusters(memory_dir)

    if dry_run or not clusters:
        print_compilation_plan(clusters)
        sys.exit(0)

    # Print plan and compilation prompt
    print_compilation_plan(clusters)
    print()
    prompt = generate_compilation_prompt(clusters)
    if prompt:
        print(prompt)

    sys.exit(0)


if __name__ == "__main__":
    main()
