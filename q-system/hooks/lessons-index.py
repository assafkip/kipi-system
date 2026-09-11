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

# CAP IS GONE. It was 20, and the corpus is 146, so 126 lessons (86%) were
# invisible in every session. Worse than the cap was HOW it chose: the sort key is
# date only, so at the cutoff date a group of same-day lessons competes for the
# remaining slots and Python's stable sort breaks the tie by ALPHABETICAL FILENAME.
# Measured 2026-08-21 in the consulting instance (153 lessons): the four lessons
# that exactly describe that week's failures ranked 93, 27, 57 and 24 against a
# cutoff of 20. All four had aged out. Write rate is 2.61/day, giving any lesson a
# 7.7-day shelf life.
#
# No relevance ranking replaced it, deliberately: a wrong rank looks identical to a
# right one and fails silently, which is the same class of failure as the
# alphabetical tiebreak it would replace.
#
# MEASURED COST, not estimated: 146 titles is 9,933 chars, about 2,483 tokens
# (chars/4). The old cap cost 379. So full injection costs roughly +2,100 tokens
# per session, once, at SessionStart.
#
# The ceiling below replaces the cap and does the opposite job. A cap silently
# drops content; the ceiling never drops anything, it FAILS A TEST so the growth
# becomes a decision someone makes on purpose. Unbounded growth and a silent cap
# are the same defect pointed in opposite directions.
PAYLOAD_CEILING_CHARS = 20000


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


def build_body(titles):
    """The SessionStart payload. One place, so the test measures what ships."""
    return ("# Cross-instance lessons (titles only; read q-system/lessons/<file> "
            "for detail)\n" + "\n".join("- " + t for t in titles))


def collect_titles(lessons_dir):
    """Every lesson title, newest first, ties broken by title.

    Split out from main so the ceiling test can measure the REAL corpus rather
    than a fixture. A fixture I invent would test my assumption about how big the
    payload is; the corpus is the thing that actually grows.
    """
    items = []
    for f in sorted(Path(lessons_dir).glob("*.md")):
        if f.name == "README.md":
            continue
        fm = frontmatter(f)
        title = fm.get("title")
        if title:
            items.append((fm.get("date", ""), title))
    items.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [t for _, t in items]


def main():
    try:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
        lessons = get_qroot(project_dir) / "lessons"
        if not lessons.is_dir():
            sys.exit(0)
        # ONE reader, called by both the hook and its test. main() used to carry
        # its own copy of this loop, which is two readers free to drift: the
        # ceiling test would have measured collect_titles while the hook shipped
        # main's version, and the number in the test would stop describing the
        # payload without anything going red. Same defect class the rest of this
        # PRD kept finding (two heading regexes, two marker predicates).
        titles = collect_titles(lessons)
        if not titles:
            sys.exit(0)
        body = build_body(titles)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": body}}))
        sys.exit(0)
    except Exception:
        sys.exit(0)  # never block session start


if __name__ == "__main__":
    main()
