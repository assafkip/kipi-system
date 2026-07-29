#!/usr/bin/env python3
"""
format-lint.py — Generic DM and email format enforcer.

Pairs broadly with assaf-voice. Catches:
  - Emails without a subject line (frontmatter or "Subject:" line)
  - DMs and emails opening with "Name, ..." or "Hi/Hello/Hey" instead of "I"

Distinct from linkedin-format-lint which handles LinkedIn-specific rules
(CR 300-char limit, hashtag count, URL in post body).

Usage:
    python3 format-lint.py <file_path>

Exit codes:
    0 = clean (or out of scope)
    2 = violations found

Override:
    Add <!-- format-lint-skip --> to bypass.

Scope:
    Fires when:
      - File path matches *-email-*.md or *-dm-*.md under q-system/output/
      - Or file frontmatter contains kind: email or kind: dm
"""

import json
import re
import sys
from pathlib import Path

SKIP_MARKER = "format-lint-skip"

SCOPE_PATH_PATTERNS = [
    r"q-system/output/.*-email-.*\.md$",
    r"q-system/output/.*-dm-.*\.md$",
    r"q-system/output/emails?/.*\.md$",
    r"q-system/output/dms?/.*\.md$",
]

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SUBJECT_LINE_RE = re.compile(r"^subject\s*:\s*\S", re.IGNORECASE | re.MULTILINE)


def parse_frontmatter(text):
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    fields = {}
    for line in raw.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip().lower()] = value.strip().strip('"').strip("'").lower()
    body = text[match.end():]
    return fields, body


def is_scope_path(file_path):
    path_str = str(file_path)
    for pattern in SCOPE_PATH_PATTERNS:
        if re.search(pattern, path_str):
            return True
    return False


def should_lint(file_path, fields):
    if is_scope_path(file_path):
        return True
    if fields.get("kind") in {"email", "dm"}:
        return True
    return False


def first_meaningful_line(body):
    for line in body.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def check_email_subject(text, fields, body):
    if fields.get("kind") != "email":
        return []
    if fields.get("subject"):
        return []
    if SUBJECT_LINE_RE.search(text):
        return []
    return [{
        "rule": "missing-subject",
        "line": 1,
        "detail": "email draft has no Subject line (add 'subject:' to frontmatter or 'Subject: X' to the body)",
    }]


def check_dm_email_opener(fields, body):
    kind = fields.get("kind", "")
    if kind not in {"email", "dm"}:
        return []
    opener = first_meaningful_line(body)
    if not opener:
        return []
    if opener.lower().startswith("subject:"):
        body_after_subject = "\n".join(body.splitlines()[1:])
        opener = first_meaningful_line(body_after_subject)
        if not opener:
            return []
    first_word_match = re.search(r"\b([A-Za-z']+)\b", opener)
    if not first_word_match:
        return []
    first = first_word_match.group(1)
    if first == "I":
        return []
    if first in {"Hi", "Hello", "Hey", "Greetings", "Dear"}:
        return [{
            "rule": "greeting-opener",
            "line": 1,
            "detail": f"{kind} opens with greeting '{first}'. Start with 'I' as the subject instead.",
        }]
    if re.match(r"[A-Z][a-z]+,", opener):
        return [{
            "rule": "name-opener",
            "line": 1,
            "detail": f"{kind} opens with 'Name, ...' pattern. Start with 'I' as the subject instead.",
        }]
    return []


def lint_file(file_path):
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except Exception as e:
        return [{"rule": "read-error", "line": 0, "detail": str(e)}]

    if SKIP_MARKER in text:
        return []

    fields, body = parse_frontmatter(text)
    if not body:
        body = text

    if not should_lint(file_path, fields):
        return []

    violations = []
    violations.extend(check_email_subject(text, fields, body))
    violations.extend(check_dm_email_opener(fields, body))
    return violations


def format_report(file_path, violations):
    if not violations:
        return ""
    lines = [f"format-lint: {len(violations)} violation(s) in {file_path}:"]
    for v in violations:
        lines.append(f"  [{v['rule']}] {v['detail']}")
    lines.append("")
    lines.append("Fix in place, or add <!-- format-lint-skip --> to bypass.")
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

    violations = lint_file(file_path)
    if not violations:
        sys.exit(0)

    print(format_report(file_path, violations), file=sys.stderr)
    sys.exit(2)


def cli_mode(file_path):
    violations = lint_file(file_path)
    if not violations:
        print(f"format-lint: clean ({file_path})")
        sys.exit(0)
    print(format_report(file_path, violations))
    sys.exit(2)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    elif len(sys.argv) == 2:
        cli_mode(sys.argv[1])
    else:
        print("Usage: format-lint.py <file_path>", file=sys.stderr)
        sys.exit(1)
