#!/usr/bin/env python3
"""The documentation coverage gate: every functionality surface the code exposes is
named in the docs, every systems page carries the two diagrams and their captions, every
concepts page carries its reader section, and the generated reference matches the code.

Exit 0 = complete. Exit 2 = the missing names, printed one per line, so the fix is a list.

WHY THIS SHAPE. The founder's goal was "triple check that literally every functionality is
in the documentation". A human triple-check of 718 surfaces is a glance that generalizes
(lesson: classify the fetched artifact against the goal). This makes the check a script
that enumerates from the code (docs/inventory.py, shared with the generator) and fails red
with names. Run it three times and record the exits; that is the triple check.

What counts as documented, per class:
  script/test/hook   the filename appears in docs/systems/*.md (a filename is the token a
                     reader can open; docs/reference is generated and does NOT count, or a
                     generated list would satisfy its own gate)
  mcp_tool/resource  the tool name or URI appears in docs/systems/*.md
  command            the /name appears in docs/systems/*.md
  skill/agent/style  the name appears in docs/systems/*.md
  job                the com.kipi.* label appears in docs/systems/*.md
  rule               the rule filename appears in docs/systems/*.md
  cli_verb           the verb appears in a backticked `kipi <verb>` in docs/systems/*.md

Honest boundary: this proves each surface is NAMED in a systems page, and that the page
has the diagrams and sections. It cannot prove the prose is true or complete; that is the
review's job. It can prove nothing was silently skipped, which is the thing that was missing.

Self-test: docs/test_check_coverage.py mutates copies and asserts the gate goes red with the
right name in each direction. Usage: python3 docs/check_coverage.py [--docs DIR] [--quiet]
"""
from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import inventory  # noqa: E402

MERMAID_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.S)
CAPTION_MIN_CHARS = 80
READER_SECTION = "## What this means for you"
COMPONENT_KINDS = ("flowchart", "graph ")
FLOW_KINDS = ("sequenceDiagram", "stateDiagram", "flowchart", "graph ")


def systems_text(docs: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in sorted((docs / "systems").glob("*.md")))


def check_surfaces(docs: Path, surfaces: list[inventory.Surface]) -> list[str]:
    text = systems_text(docs)
    missing = []
    for s in surfaces:
        if s.cls == "cli_verb":
            ok = re.search(r"`kipi\s+" + re.escape(s.name) + r"\b", text) is not None
        elif s.cls == "command":
            ok = re.search(re.escape(s.name) + r"\b", text) is not None
        else:
            # Not a bare substring: `lint.py` must not ride on `voice-lint.py` (Codex, PR #306).
            # A path separator or backtick before the name still counts; a word char, dot or
            # hyphen before it means this is the tail of a longer name.
            ok = re.search(r"(?<![\w.-])" + re.escape(s.name) + r"(?!\w)", text) is not None
        if not ok:
            missing.append(f"{s.cls}: {s.name}  ({s.path})")
    return missing


def check_diagrams(docs: Path) -> list[str]:
    problems = []
    for p in sorted((docs / "systems").glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        blocks = MERMAID_RE.findall(text)
        kinds = [b.strip().splitlines()[0].strip() if b.strip() else "" for b in blocks]
        has_component = any(k.startswith(COMPONENT_KINDS) for k in kinds)
        has_flow = any(k.startswith(("sequenceDiagram", "stateDiagram")) for k in kinds) or \
            sum(1 for k in kinds if k.startswith(FLOW_KINDS)) >= 2
        if not has_component:
            problems.append(f"diagram: {p.name} has no component diagram (flowchart/graph)")
        if not has_flow:
            problems.append(f"diagram: {p.name} has no flow diagram (sequenceDiagram/stateDiagram, or a second flowchart)")
        for m in MERMAID_RE.finditer(text):
            after = text[m.end():m.end() + 1200].strip()
            caption = after.split("\n\n")[0].strip() if after else ""
            if caption.startswith("#") or caption.startswith("```") or len(caption) < CAPTION_MIN_CHARS:
                line = text[:m.start()].count("\n") + 1
                problems.append(f"caption: {p.name}:{line} mermaid block is not followed by a plain-English caption of {CAPTION_MIN_CHARS}+ chars")
    return problems


def check_concepts(docs: Path) -> list[str]:
    problems = []
    for p in sorted((docs / "concepts").glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        if READER_SECTION not in text:
            problems.append(f"concept: {p.name} lacks the section '{READER_SECTION}'")
        if not MERMAID_RE.search(text):
            problems.append(f"concept: {p.name} has no diagram")
    return problems


def check_reference(docs: Path) -> list[str]:
    gen = HERE / "generate_reference.py"
    if not gen.is_file():
        return ["reference: docs/generate_reference.py is missing"]
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, str(gen), "--out", tmp], check=True, capture_output=True)
        problems = []
        for fresh in sorted(Path(tmp).glob("*.md")):
            shipped = docs / "reference" / fresh.name
            if not shipped.is_file():
                problems.append(f"reference: {fresh.name} not present in docs/reference (run generate_reference.py)")
                continue
            a, b = shipped.read_text().splitlines(), fresh.read_text().splitlines()
            if a != b:
                diff = list(difflib.unified_diff(a, b, "shipped", "fresh", lineterm="", n=0))[:8]
                problems.append(f"reference: {fresh.name} drifted from the code:\n    " + "\n    ".join(diff))
    return problems


def check_retired(docs: Path) -> list[str]:
    text = systems_text(docs)
    return [] if "## Retired" in text else ["retired: no systems page carries a '## Retired' heading"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default=str(HERE))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    docs = Path(args.docs)
    surfaces = inventory.enumerate_surfaces()
    problems = []
    problems += check_surfaces(docs, surfaces)
    problems += check_diagrams(docs)
    problems += check_concepts(docs)
    problems += check_reference(docs)
    problems += check_retired(docs)
    if problems:
        sys.stderr.write(f"docs coverage: {len(problems)} problem(s) across {len(surfaces)} surfaces\n")
        for p in problems:
            sys.stderr.write(f"  - {p}\n")
        return 2
    if not args.quiet:
        by = {}
        for s in surfaces:
            by[s.cls] = by.get(s.cls, 0) + 1
        print("docs coverage: COMPLETE. " + ", ".join(f"{c} {n}" for c, n in by.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
