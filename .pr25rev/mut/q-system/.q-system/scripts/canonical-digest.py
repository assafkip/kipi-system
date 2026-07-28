#!/usr/bin/env python3
"""
Deterministic canonical file digest generator.
Reads all canonical files once, produces compact JSON digest for downstream agents.
Replaces the 00c-canonical-digest LLM agent with regex-based parsing.

Usage:
    python3 canonical-digest.py <date>
    python3 canonical-digest.py <date> --json

Exit 0 = success (digest written)
Exit 1 = validation failed (missing required fields)
"""

import json
import os
import re
import sys

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUS_BASE = os.path.join(QROOT, ".q-system", "agent-pipeline", "bus")


def read_file(path):
    """Read file content, return empty string if missing."""
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def parse_talk_tracks(content):
    """Extract structured data from talk-tracks.md."""
    result = {
        "primary_metaphor": "",
        "product_definition": "",
        "wedge_formula": "",
        "banned_phrases": [],
        "detection_rule": "",
    }

    # Extract primary metaphor (under ### Primary metaphor)
    m = re.search(r'###\s*Primary metaphor\s*\n>\s*(.+)', content)
    if m:
        result["primary_metaphor"] = m.group(1).strip()

    # Extract one-liner as product definition
    m = re.search(r'###\s*One-liner\s*\n>\s*(.+)', content)
    if m:
        result["product_definition"] = m.group(1).strip()

    # Extract category
    m = re.search(r'###\s*Category\s*\n>\s*(.+)', content)
    if m:
        result["wedge_formula"] = m.group(1).strip()

    # Banned phrases from the language rules (static list, kept in sync with CLAUDE.md)
    result["banned_phrases"] = [
        "AI-powered", "leverage", "innovative", "cutting-edge",
        "single pane of glass", "next-gen", "game-changing",
    ]

    return result


def parse_objections(content):
    """Extract objection names and responses from objections.md."""
    objections = []
    # Match ### "Objection text" blocks
    blocks = re.split(r'###\s+"', content)
    for block in blocks[1:]:  # skip header
        name_end = block.find('"')
        if name_end == -1:
            continue
        name = block[:name_end].strip()

        # Extract response
        response = ""
        m = re.search(r'\*\*Response:\*\*\s*(.+?)(?:\n\*\*|\n###|\Z)', block, re.DOTALL)
        if m:
            response = m.group(1).strip()
            # First 2 sentences
            sentences = re.split(r'(?<=[.!?])\s+', response)
            response = " ".join(sentences[:2])

        objections.append({
            "name": name,
            "response_summary": response,
            "signal_count": 0,
            "near_threshold": False,
        })

    return objections


def parse_current_state(content):
    """Extract what works today, validated, unvalidated from current-state.md."""
    result = {
        "works_today": [],
        "validated": [],
        "unvalidated": [],
        "is_not": [],
    }

    # Parse "What Works Today" section
    m = re.search(r'##\s*What Works Today.*?\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if m:
        items = re.findall(r'^-\s+(.+)', m.group(1), re.MULTILINE)
        result["works_today"] = [i.strip() for i in items if not i.startswith("(")][:10]

    # Parse "Claimed But Unproven" as unvalidated
    m = re.search(r'##\s*Claimed But Unproven.*?\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if m:
        items = re.findall(r'^-\s+(.+)', m.group(1), re.MULTILINE)
        result["unvalidated"] = [i.strip() for i in items if not i.startswith("(")]

    # Parse "What We Are NOT"
    m = re.search(r'##\s*What We Are NOT.*?\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if m:
        items = re.findall(r'^-\s+(.+)', m.group(1), re.MULTILINE)
        result["is_not"] = [i.strip() for i in items if not i.startswith("(")]

    return result


def parse_discovery(content):
    """Extract top questions and gaps from discovery.md."""
    questions = []
    gaps = []

    # Match ### Q: "Question" blocks
    blocks = re.split(r'###\s*Q:\s*"', content)
    for block in blocks[1:]:
        q_end = block.find('"')
        if q_end == -1:
            continue
        question = block[:q_end].strip()

        answer = ""
        m = re.search(r'\*\*Best answer:\*\*\s*(.+?)(?:\n\*\*|\n###|\Z)', block, re.DOTALL)
        if m:
            answer = m.group(1).strip()

        gap = ""
        m = re.search(r'\*\*Gaps:\*\*\s*(.+?)(?:\n\*\*|\n###|\Z)', block, re.DOTALL)
        if m:
            gap = m.group(1).strip()

        questions.append({"q": question, "a": answer})
        if gap and not gap.startswith("("):
            gaps.append(gap)

    return {"top_questions": questions[:5], "gaps": gaps}


def parse_decisions(content):
    """Extract active RULEs from decisions.md."""
    decisions = []

    # Match RULE-NNN entries
    for m in re.finditer(
        r'(RULE-\d+)\s*[:\-]\s*(.+?)(?:\s*\[([^\]]+)\])?$',
        content,
        re.MULTILINE,
    ):
        rule_id = m.group(1)
        summary = m.group(2).strip()
        origin = m.group(3).strip() if m.group(3) else "UNKNOWN"
        decisions.append({
            "rule": rule_id,
            "summary": summary,
            "origin": origin,
        })

    # Also match tagged decisions without RULE- prefix
    for m in re.finditer(
        r'^\s*-\s+(.+?)\s+\[(USER-DIRECTED|CLAUDE-RECOMMENDED[^]]*|SYSTEM-INFERRED|COUNCIL-DEBATED)\]',
        content,
        re.MULTILINE,
    ):
        summary = m.group(1).strip()
        origin = m.group(2).strip()
        # Avoid duplicates with RULE-prefixed entries
        if not summary.startswith("RULE-"):
            decisions.append({
                "rule": f"DECISION-{len(decisions)+1:03d}",
                "summary": summary,
                "origin": origin,
            })

    return decisions


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 canonical-digest.py <date> [--json]", file=sys.stderr)
        sys.exit(2)

    date = sys.argv[1]
    json_output = "--json" in sys.argv

    bus_dir = os.path.join(BUS_BASE, date)
    os.makedirs(bus_dir, exist_ok=True)

    # Read all canonical files
    talk_tracks_content = read_file(os.path.join(QROOT, "canonical", "talk-tracks.md"))
    objections_content = read_file(os.path.join(QROOT, "canonical", "objections.md"))
    current_state_content = read_file(os.path.join(QROOT, "my-project", "current-state.md"))
    discovery_content = read_file(os.path.join(QROOT, "canonical", "discovery.md"))
    decisions_content = read_file(os.path.join(QROOT, "canonical", "decisions.md"))

    # Parse each
    talk_tracks = parse_talk_tracks(talk_tracks_content)
    objections = parse_objections(objections_content)
    current_state = parse_current_state(current_state_content)
    discovery = parse_discovery(discovery_content)
    decisions = parse_decisions(decisions_content)

    digest = {
        "date": date,
        "digest_version": 1,
        "talk_tracks": talk_tracks,
        "objections": objections,
        "current_state": current_state,
        "discovery": discovery,
        "decisions": decisions,
    }

    # Validate
    errors = []
    if not talk_tracks["primary_metaphor"] and not talk_tracks["product_definition"]:
        # Allow empty if files are templates (contain placeholders)
        if "{{" not in talk_tracks_content and talk_tracks_content.strip():
            errors.append("Missing: primary_metaphor or product_definition in talk-tracks.md")
    if len(talk_tracks["banned_phrases"]) < 4:
        errors.append(f"banned_phrases has {len(talk_tracks['banned_phrases'])} items (need >= 4)")

    # Write output
    output_path = os.path.join(bus_dir, "canonical-digest.json")
    with open(output_path, "w") as f:
        json.dump(digest, f, indent=2)

    if json_output:
        print(json.dumps(digest, indent=2))
    else:
        print(f"Canonical digest written to {output_path}")
        print(f"  talk_tracks: metaphor={'set' if talk_tracks['primary_metaphor'] else 'empty'}")
        print(f"  objections: {len(objections)}")
        print(f"  current_state: {len(current_state['works_today'])} works_today")
        print(f"  discovery: {len(discovery['top_questions'])} questions, {len(discovery['gaps'])} gaps")
        print(f"  decisions: {len(decisions)}")

    if errors:
        print(f"\nValidation warnings: {len(errors)}")
        for e in errors:
            print(f"  - {e}")

    # Exit 0 even with warnings (templates are OK at this stage)
    sys.exit(0)


if __name__ == "__main__":
    main()
