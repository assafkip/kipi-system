#!/usr/bin/env python3
"""
Pitfall Detection (SessionStart).

Parses the most recent session transcript for patterns where:
1. Claude read a memory file
2. The user corrected the memory ("that changed", "that's outdated", etc.)

When detected, creates a fast-decay memory recording the correction
so future sessions know the fact was invalidated.

Borrowed from: claude-memory-engine's transcript pitfall detection
(retry loops, user corrections -> auto-recorded pitfalls).

Exit 0 always. Prints summary of detected pitfalls.
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


# Correction patterns the user might say after Claude acts on stale memory
CORRECTION_PATTERNS = [
    r"that('s| is| has) (changed|outdated|stale|old|wrong|not true|no longer|not accurate)",
    r"(no|nope),?\s+(that|it)('s| is| has) (changed|different|not right|wrong)",
    r"that was (last week|before|earlier|old)",
    r"(actually|update|correction|fyi|btw)[,:;]?\s+.*(changed|different|moved|cancelled|over|done|finished|ended)",
    r"not anymore",
    r"that('s| is) (done|over|finished|dead|killed|cancelled|postponed)",
    r"we (already|no longer|stopped|moved past|dropped)",
    r"forget (that|about|it)",
    r"(ignore|disregard) (that|the) (memory|fact|note)",
]

CORRECTION_RE = re.compile("|".join(CORRECTION_PATTERNS), re.IGNORECASE)

# Pattern to detect Claude reading a memory file
MEMORY_READ_PATTERN = re.compile(
    r"\.claude/projects/[^/]+/memory/([^\"'\s]+\.md)"
)


def get_memory_dir():
    """Compute the auto-memory directory from project dir."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    project_slug = project_dir.replace("/", "-")
    return Path.home() / ".claude" / "projects" / project_slug / "memory"


def get_project_dir():
    """Get the project directory."""
    return Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))


def find_latest_transcript():
    """Find the most recent session JSONL transcript."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    project_slug = project_dir.replace("/", "-")
    sessions_dir = Path.home() / ".claude" / "projects" / project_slug

    if not sessions_dir.exists():
        return None

    jsonl_files = sorted(
        sessions_dir.glob("*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    # Skip the current session (most recent), check the previous one
    if len(jsonl_files) >= 2:
        return jsonl_files[1]
    return None


def parse_transcript(transcript_path, max_lines=500):
    """Parse a JSONL transcript for memory reads followed by corrections.

    Returns list of (memory_filename, correction_text, user_message).
    """
    pitfalls = []

    try:
        lines = transcript_path.read_text().strip().split("\n")
    except (IOError, OSError):
        return []

    # Only check the last N lines to bound processing time
    lines = lines[-max_lines:]

    recent_memory_reads = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Track memory file reads
        content_str = json.dumps(entry)
        memory_matches = MEMORY_READ_PATTERN.findall(content_str)
        for mem_file in memory_matches:
            if mem_file != "MEMORY.md":
                recent_memory_reads.append(mem_file)

        # Check user messages for correction patterns
        if entry.get("role") == "user":
            user_text = ""
            if isinstance(entry.get("content"), str):
                user_text = entry["content"]
            elif isinstance(entry.get("content"), list):
                for block in entry["content"]:
                    if isinstance(block, dict) and block.get("type") == "text":
                        user_text += block.get("text", "")

            if user_text and CORRECTION_RE.search(user_text) and recent_memory_reads:
                # Found a correction after memory reads
                for mem_file in recent_memory_reads:
                    pitfalls.append((mem_file, user_text[:200]))
                recent_memory_reads = []

    return pitfalls


def create_pitfall_memory(memory_dir, memory_filename, correction_text):
    """Create a fast-decay memory recording that a fact was corrected."""
    today = datetime.now().strftime("%Y-%m-%d")
    slug = Path(memory_filename).stem
    pitfall_filename = f"pitfall_{slug}_{today}.md"
    pitfall_path = memory_dir / pitfall_filename

    # Don't create duplicate pitfalls for the same memory on the same day
    if pitfall_path.exists():
        return None

    content = f"""---
name: Pitfall - {slug} corrected
description: User corrected a fact from {memory_filename} on {today}
type: feedback
decay: fast
origin: pitfall_detection
---

The user corrected information from `{memory_filename}` on {today}.

User said: "{correction_text}"

**Action:** Read `{memory_filename}` and update it with the corrected information.
If the original memory is now fully outdated, archive it.
"""

    pitfall_path.write_text(content)
    return pitfall_filename


def update_memory_index(memory_dir):
    """Add new pitfall memories to MEMORY.md index."""
    index_path = memory_dir / "MEMORY.md"

    existing = ""
    if index_path.exists():
        existing = index_path.read_text()

    for md_file in sorted(memory_dir.glob("pitfall_*.md")):
        if md_file.name not in existing:
            # Parse frontmatter for description
            content = md_file.read_text()
            desc = ""
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    for line in parts[1].split("\n"):
                        if line.strip().startswith("description:"):
                            desc = line.split(":", 1)[1].strip()

            entry = f"- [fast] [Pitfall - {md_file.stem}]({md_file.name}) - {desc}\n"
            existing += entry

    index_path.write_text(existing)


def run_pitfall_detection():
    """Main entry point. Returns list of created pitfall filenames."""
    memory_dir = get_memory_dir()
    if not memory_dir.exists():
        return []

    transcript = find_latest_transcript()
    if transcript is None:
        return []

    # Check if we already processed this transcript
    state_file = memory_dir / ".memory-lifecycle-state.json"
    state = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
        except (json.JSONDecodeError, IOError):
            pass

    last_processed = state.get("last_pitfall_transcript")
    if last_processed == str(transcript):
        return []

    pitfalls = parse_transcript(transcript)
    created = []

    for memory_filename, correction_text in pitfalls:
        result = create_pitfall_memory(memory_dir, memory_filename, correction_text)
        if result:
            created.append(result)

    if created:
        update_memory_index(memory_dir)

    # Record that we processed this transcript
    state["last_pitfall_transcript"] = str(transcript)
    state_file.write_text(json.dumps(state, indent=2) + "\n")

    return created


if __name__ == "__main__":
    created = run_pitfall_detection()
    if created:
        print(f"PITFALL DETECTION: {len(created)} correction(s) from last session")
        for f in created:
            print(f"  -> {f}")
    sys.exit(0)
