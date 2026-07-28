#!/usr/bin/env python3
"""Memory Confidence Surfacer Hook.

Scans the auto-memory directory at SessionStart and prints a warning block for
memories whose trust is low: `confidence` below the threshold OR `provenance` in
{inferred, observed}. Output appears as session context so the model treats those
memories skeptically (verify before asserting), the same way the freshness hook
surfaces `decay: fast`.

Runs on SessionStart. Exit code 0 always (never blocks).

Pairs with .claude/rules/memory-confidence.md and PRD
prd-memory-confidence-provenance-2026-06-30. Sibling of memory-freshness-check.py;
shares its get_memory_dir() resolution because the auto-memory dir lives outside
the project tree (path-scoped rule loading does not reach it).

Scar: kipi auto-memory had no certainty signal, so a model-inferred guess and a
founder-stated fact were indistinguishable at recall. This is the recall-side push;
the validator is the write-side gate.
"""
import os
import sys
from pathlib import Path

LOW_CONFIDENCE_THRESHOLD = 0.5
LOW_TRUST_PROVENANCE = {"inferred", "observed"}


def get_project_dir():
    return os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())


def get_memory_dir():
    """Compute the auto-memory directory path from project dir."""
    project_dir = get_project_dir()
    project_slug = project_dir.replace("/", "-")
    return Path.home() / ".claude" / "projects" / project_slug / "memory"


def parse_memory_file(file_path):
    """Extract (name, confidence_or_None, provenance_or_None) from frontmatter."""
    try:
        content = file_path.read_text()
    except (IOError, OSError):
        return (file_path.stem, None, None)
    if not content.startswith("---"):
        return (file_path.stem, None, None)
    parts = content.split("---", 2)
    if len(parts) < 3:
        return (file_path.stem, None, None)

    name = file_path.stem
    confidence = None
    provenance = None
    for line in parts[1].split("\n"):
        if line[:1].isspace():  # skip nested keys (metadata:)
            continue
        stripped = line.strip()
        if stripped.startswith("name:"):
            name = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("confidence:"):
            raw = stripped.split(":", 1)[1].strip()
            try:
                confidence = float(raw)
            except ValueError:
                confidence = None
        elif stripped.startswith("provenance:"):
            provenance = stripped.split(":", 1)[1].strip()
    return (name, confidence, provenance)


def is_low_trust(confidence, provenance):
    if confidence is not None and confidence < LOW_CONFIDENCE_THRESHOLD:
        return True
    if provenance in LOW_TRUST_PROVENANCE:
        return True
    return False


def main():
    memory_dir = get_memory_dir()
    if not memory_dir.exists():
        sys.exit(0)

    flagged = []
    for md_file in sorted(memory_dir.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue
        name, confidence, provenance = parse_memory_file(md_file)
        if is_low_trust(confidence, provenance):
            flagged.append((name, confidence, provenance, md_file.name))

    if not flagged:
        sys.exit(0)

    print("MEMORY CONFIDENCE WARNING (auto-injected by hook)")
    print("=" * 50)
    print("These memories are low-trust (confidence < 0.5 or provenance inferred/observed).")
    print("Verify before asserting their content as fact.")
    print()
    for name, confidence, provenance, filename in flagged:
        tags = []
        if confidence is not None and confidence < LOW_CONFIDENCE_THRESHOLD:
            tags.append(f"conf={confidence}")
        if provenance in LOW_TRUST_PROVENANCE:
            tags.append(provenance)
        print(f"  [LOW-CONF {', '.join(tags)}] {name} ({filename})")
    print()
    print("Skip verification only if the action is informational, not asserting state.")
    print("=" * 50)
    sys.exit(0)


if __name__ == "__main__":
    main()
