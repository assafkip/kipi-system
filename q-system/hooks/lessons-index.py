#!/usr/bin/env python3
"""SessionStart consumer for the cross-instance lessons corpus.

Reads q-system/lessons/*.md frontmatter titles and injects them (titles only,
capped, bodies on demand) via hookSpecificOutput.additionalContext so every
instance sees the available lessons. Part of PRD prd-cross-instance-learning-2026-06-19.

Fail-closed and never-blocks: any error -> emit nothing, exit 0. The QROOT
resolution mirrors session-start.py get_qroot (flat + nested q-system/q-system/
subtree layout); the additionalContext shape mirrors voice-dna-loader.py:152 /
token-guard.py:336 (hookSpecificOutput.additionalContext); the SessionStart form additionally sets hookEventName. stdlib only.
"""
import json
import os
import sys
from pathlib import Path

CAP = 20


def get_qroot(project_dir):
    nested = Path(project_dir) / "q-system" / "q-system" / "canonical"
    if nested.exists():
        return Path(project_dir) / "q-system" / "q-system"
    return Path(project_dir) / "q-system"


def frontmatter(path):
    try:
        text = path.read_text()
    except Exception:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm = {}
    for line in text[3:end].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


def main():
    try:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
        lessons = get_qroot(project_dir) / "lessons"
        if not lessons.is_dir():
            sys.exit(0)
        items = []
        for f in sorted(lessons.glob("*.md")):
            if f.name == "README.md":
                continue
            fm = frontmatter(f)
            title = fm.get("title")
            if title:
                items.append((fm.get("date", ""), title))
        if not items:
            sys.exit(0)
        items.sort(key=lambda x: x[0], reverse=True)  # most recent date first
        titles = [t for _, t in items[:CAP]]
        body = "# Cross-instance lessons (titles only; read q-system/lessons/<file> for detail)\n" + \
            "\n".join("- " + t for t in titles)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": body}}))
        sys.exit(0)
    except Exception:
        sys.exit(0)  # never block session start


if __name__ == "__main__":
    main()
