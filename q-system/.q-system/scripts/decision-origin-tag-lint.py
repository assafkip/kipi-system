#!/usr/bin/env python3
"""
decision-origin-tag-lint.py — Enforces decision origin tagging rule.

Pairs with the sycophancy.md rule:
  "Every decision logged to canonical/decisions.md MUST include an origin tag"

Valid tags:
  [USER-DIRECTED]
  [CLAUDE-RECOMMENDED -> APPROVED]
  [CLAUDE-RECOMMENDED -> MODIFIED]
  [CLAUDE-RECOMMENDED -> REJECTED]
  [SYSTEM-INFERRED]
  [COUNCIL-DEBATED]

The hook fires on Edit|Write to any canonical/decisions.md across the cluster.
Verifies each decision section (H2 or H3 heading + content) contains a valid tag.

Usage:
    python3 decision-origin-tag-lint.py <file_path>

Exit codes:
    0 = clean (or out of scope)
    2 = violations found

Override:
    Add <!-- decision-tag-lint-skip --> in the file to bypass.
"""

import json
import re
import sys
from pathlib import Path

SKIP_MARKER = "decision-tag-lint-skip"

SCOPE_PATH_PATTERNS = [
    r"canonical/decisions\.md$",
    r"q-[a-z]+/canonical/decisions\.md$",
]

VALID_TAG_RE = re.compile(
    r"\[(USER-DIRECTED|"
    r"CLAUDE-RECOMMENDED\s*->\s*(APPROVED|MODIFIED|REJECTED)|"
    r"SYSTEM-INFERRED|"
    r"COUNCIL-DEBATED)\]"
)

SECTION_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)


def is_scope_path(file_path):
    path_str = str(file_path)
    for pattern in SCOPE_PATH_PATTERNS:
        if re.search(pattern, path_str):
            return True
    return False


def find_line_number(text, char_offset):
    return text[:char_offset].count("\n") + 1


def extract_sections(text):
    """Return list of (heading_line_no, heading_text, section_content) tuples.
    A section is a heading + everything until the next heading of equal or higher level.
    """
    headings = list(SECTION_HEADING_RE.finditer(text))
    sections = []
    for i, match in enumerate(headings):
        level = len(match.group(1))
        heading_text = match.group(2)
        start = match.end()
        end = len(text)
        for j in range(i + 1, len(headings)):
            next_level = len(headings[j].group(1))
            if next_level <= level:
                end = headings[j].start()
                break
        content = text[start:end]
        line_no = find_line_number(text, match.start())
        sections.append((line_no, heading_text, content))
    return sections


def is_decision_section(heading_text):
    """Heuristic: a decision section's heading either has a date or looks like a decision."""
    if re.search(r"\d{4}-\d{2}-\d{2}", heading_text):
        return True
    if re.match(r"^(Decision|Decided|Choice|Verdict)\b", heading_text, re.IGNORECASE):
        return True
    skip_patterns = [
        r"^(template|tag(ging)? format|origin tags?|legend|key|usage|how to|examples?)\b",
        r"^(table of contents|toc|index)\b",
    ]
    for pattern in skip_patterns:
        if re.match(pattern, heading_text.strip(), re.IGNORECASE):
            return False
    return True


def lint_file(file_path):
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except Exception as e:
        return [{"rule": "read-error", "line": 0, "detail": str(e)}]

    if SKIP_MARKER in text:
        return []

    sections = extract_sections(text)
    if not sections:
        return []

    violations = []
    for line_no, heading_text, content in sections:
        if not is_decision_section(heading_text):
            continue
        full_section = heading_text + "\n" + content
        if not VALID_TAG_RE.search(full_section):
            violations.append({
                "rule": "missing-origin-tag",
                "line": line_no,
                "detail": f"decision section '{heading_text[:60]}' has no valid origin tag. Add one of: [USER-DIRECTED], [CLAUDE-RECOMMENDED -> APPROVED/MODIFIED/REJECTED], [SYSTEM-INFERRED], [COUNCIL-DEBATED]",
            })
    return violations


def format_report(file_path, violations):
    if not violations:
        return ""
    lines = [f"decision-tag-lint: {len(violations)} violation(s) in {file_path}:"]
    violations.sort(key=lambda v: (v["line"], v["rule"]))
    for v in violations:
        lines.append(f"  line {v['line']} [{v['rule']}] {v['detail']}")
    lines.append("")
    lines.append("Tag each decision, or add <!-- decision-tag-lint-skip --> to bypass.")
    return "\n".join(lines)


def hook_mode():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)

    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not file_path:
        sys.exit(0)

    if not is_scope_path(file_path):
        sys.exit(0)

    violations = lint_file(file_path)
    if not violations:
        sys.exit(0)

    print(format_report(file_path, violations), file=sys.stderr)
    sys.exit(2)


def cli_mode(file_path):
    violations = lint_file(file_path)
    if not violations:
        print(f"decision-tag-lint: clean ({file_path})")
        sys.exit(0)
    print(format_report(file_path, violations))
    sys.exit(2)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    elif len(sys.argv) == 2:
        cli_mode(sys.argv[1])
    else:
        print("Usage: decision-origin-tag-lint.py <file_path>", file=sys.stderr)
        sys.exit(1)
