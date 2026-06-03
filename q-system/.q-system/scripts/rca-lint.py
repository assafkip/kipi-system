#!/usr/bin/env python3
"""
rca-lint.py — Deterministic RCA / premortem structure enforcer.

Pairs with the canonical RCA template at
q-system/methodology/rca-template.md. Catches RCA docs that skip required
sections, bury action items in prose, assert fixes without evidence, omit
cause-type tags, or name people instead of system failures.

Usage:
    python3 rca-lint.py <file_path>     # CLI mode
    (no args)                           # hook mode: reads PostToolUse JSON on stdin

Exit codes:
    0 = clean (or out of scope)
    2 = violations found

Override:
    Add <!-- rca-lint-skip --> anywhere in the file to bypass.

Scope:
    Fires when the file is an RCA/premortem document, detected by EITHER:
      - path under q-system/output/rca/ , or filename rca-*.md / premortem-*.md
      - H1 starting with "# RCA:" or "# Premortem"
    Anything else exits 0.
"""

import json
import re
import sys
from pathlib import Path

SKIP_MARKER = "rca-lint-skip"

REQUIRED_RCA_SECTIONS = [
    "What happened",
    "Surface symptom",
    "Surface root cause",
    "Structural root cause",
    "Verification",
    "Contributing factors",
    "Fixes shipped",
    "Action items",
    "Lessons",
]

REQUIRED_PREMORTEM_SECTIONS = [
    "Findings by severity",
    "Recommended fix order",
    "What I did NOT find",
]

CAUSE_TYPES = {
    "code-defect", "config", "environmental-trigger", "missing-test",
    "implicit-contract", "process", "capacity",
}

# Evidence words that mark real verification (case-insensitive).
EVIDENCE_WORDS = re.compile(
    r"\b(ran|got|observed|confirmed|passed|output|exit\s*0|reproduced|green)\b", re.I
)

# Conservative blame patterns. Low false-positive: targets fault-attribution to
# a person, not system/contract/test failures.
BLAME_PATTERNS = [
    (re.compile(r"\bto blame\b", re.I), "person-blame phrase 'to blame'"),
    (re.compile(r"\bwhose fault\b", re.I), "person-blame phrase 'whose fault'"),
    (re.compile(r"'s fault\b", re.I), "person-blame phrase \"'s fault\""),
    (re.compile(r"\bhuman error\b", re.I), "blame phrase 'human error' (name the missing guardrail instead)"),
]


def is_rca_path(file_path):
    p = str(file_path)
    if "/output/rca/" in p:
        return True
    name = Path(p).name.lower()
    return name.startswith("rca-") or name.startswith("premortem-")


def extract_h1(body):
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return None


def doc_kind(file_path, text):
    """Return 'rca', 'premortem', or None (out of scope)."""
    h1 = extract_h1(text) or ""
    hl = h1.lower()
    if hl.startswith("premortem"):
        return "premortem"
    if hl.startswith("rca"):
        return "rca"
    # Path-based detection still classifies by filename.
    if is_rca_path(file_path):
        name = Path(str(file_path)).name.lower()
        return "premortem" if name.startswith("premortem-") else "rca"
    return None


def headers(text):
    """Set of normalized ## / ### header titles present."""
    found = set()
    for line in text.splitlines():
        m = re.match(r"#{2,3}\s+(.*?)\s*$", line)
        if m:
            found.add(m.group(1).strip())
    return found


def section_body(text, title):
    """Return the lines under a given ## section up to the next ## header."""
    lines = text.splitlines()
    out, capturing = [], False
    for line in lines:
        if re.match(r"##\s+", line):
            if capturing:
                break
            if re.match(r"##\s+" + re.escape(title) + r"\s*$", line):
                capturing = True
            continue
        if capturing:
            out.append(line)
    return "\n".join(out)


def header_present(found, title):
    """A required section is present if any header startswith its title.
    Allows 'Structural root cause' plus '### Root cause #1' style splits."""
    if title in found:
        return True
    low = title.lower()
    return any(h.lower().startswith(low) for h in found)


def lint_text(file_path, text):
    violations = []
    kind = doc_kind(file_path, text)
    if kind is None:
        return []  # out of scope

    # Metadata
    if not re.search(r"^\*\*Date:\*\*", text, re.M):
        violations.append({"rule": "missing-metadata", "detail": "missing **Date:** line"})
    if not re.search(r"^\*\*Trigger:\*\*", text, re.M):
        violations.append({"rule": "missing-metadata", "detail": "missing **Trigger:** line"})

    found = headers(text)
    required = REQUIRED_RCA_SECTIONS if kind == "rca" else REQUIRED_PREMORTEM_SECTIONS
    for sec in required:
        if not header_present(found, sec):
            violations.append({"rule": "missing-section", "detail": f"missing required section: ## {sec}"})

    if kind == "rca":
        # Structural root cause must carry at least one valid cause-type tag.
        struct = section_body(text, "Structural root cause")
        tags = re.findall(r"type:\s*([a-z-]+)", struct)
        valid = [t for t in tags if t in CAUSE_TYPES]
        if not valid:
            violations.append({
                "rule": "missing-cause-type",
                "detail": "Structural root cause has no valid 'type:' tag "
                          f"(one of: {', '.join(sorted(CAUSE_TYPES))})",
            })

        # Verification must contain evidence, not just an assertion.
        verif = section_body(text, "Verification")
        if "```" not in verif and not EVIDENCE_WORDS.search(verif):
            violations.append({
                "rule": "no-evidence",
                "detail": "Verification section has no evidence "
                          "(a code fence or words like ran/got/observed/passed)",
            })

        # Action items must be real checkboxes, not prose.
        actions = section_body(text, "Action items")
        if not re.search(r"^\s*-\s*\[[ xX]\]", actions, re.M):
            violations.append({
                "rule": "prose-action-items",
                "detail": "Action items must be checkboxes (- [ ] ...), not prose",
            })

    # Blameless (both kinds)
    for pat, msg in BLAME_PATTERNS:
        if pat.search(text):
            violations.append({"rule": "not-blameless", "detail": msg})

    return violations


def lint_file(file_path):
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except Exception as e:
        return [{"rule": "read-error", "detail": str(e)}]
    if SKIP_MARKER in text:
        return []
    return lint_text(file_path, text)


def format_report(file_path, violations):
    lines = [f"rca-lint: {len(violations)} violation(s) in {file_path}:"]
    for v in violations:
        lines.append(f"  [{v['rule']}] {v['detail']}")
    lines.append(f"Fix per q-system/methodology/rca-template.md, or add <!-- {SKIP_MARKER} --> to bypass.")
    return "\n".join(lines)


def hook_mode():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if payload.get("tool_name", "") not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)
    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not file_path or not str(file_path).endswith(".md"):
        sys.exit(0)
    violations = lint_file(file_path)
    if not violations:
        sys.exit(0)
    print(format_report(file_path, violations), file=sys.stderr)
    sys.exit(2)


def cli_mode(file_path):
    violations = lint_file(file_path)
    if not violations:
        print(f"rca-lint: clean ({file_path})")
        sys.exit(0)
    print(format_report(file_path, violations))
    sys.exit(2)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    elif len(sys.argv) == 2:
        cli_mode(sys.argv[1])
    else:
        print("Usage: rca-lint.py <file_path>", file=sys.stderr)
        sys.exit(1)
