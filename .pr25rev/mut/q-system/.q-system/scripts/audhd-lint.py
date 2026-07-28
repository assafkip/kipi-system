#!/usr/bin/env python3
"""
audhd-lint.py — Enforces AUDHD executive function rules in founder-facing output.

Pairs with the audhd-executive-function skill.

Catches:
  - Banned shame language (overdue, missed, failed, forgot, dropped the ball, etc.)
  - Back-references that break working memory ("see above", "as mentioned", etc.)
  - Daily-schedule HTML missing time estimates per task block
  - Daily-schedule HTML missing clickable links per task block

Usage:
    python3 audhd-lint.py <file_path>

Exit codes:
    0 = clean (or out of scope)
    2 = violations found

Override:
    Add <!-- audhd-lint-skip --> (in HTML/md comment) or "audhd-lint-skip" (in JSON
    via a top-level _skip field) to bypass.

Scope:
    Founder-facing output that the founder will act on:
      - q-system/output/daily-schedule-*.html
      - q-system/output/morning-log-*.json
      - q-system/output/*-actions-*.md
      - q-system/output/*-tasks-*.md
      - Files with frontmatter kind: schedule|tasks|actions or audience: founder
"""

import json
import re
import sys
from pathlib import Path

SKIP_MARKER = "audhd-lint-skip"

# Heuristic / probabilistic rules with a real false-positive rate. WARN-only:
# they print to stderr but do NOT block (exit 0). Every other rule this linter
# emits is implicitly BLOCK (deterministic, ~0 false-positive): exit 2.
#
# This linter's rules are all deterministic — banned words/phrases (shame-word,
# back-reference), required structural elements (missing-time-estimate,
# missing-clickable-link, step-without-status), and read-error. None are fuzzy
# prose-cadence heuristics, so WARN_RULES is empty. It exists for consistency
# with the precision-tiered partition machinery used across the linters.
WARN_RULES = frozenset()


def _partition(violations):
    blocking = [v for v in violations if v.get("rule") not in WARN_RULES]
    warnings = [v for v in violations if v.get("rule") in WARN_RULES]
    return blocking, warnings


SCOPE_PATH_PATTERNS = [
    r"q-system/output/daily-schedule-.*\.html$",
    r"q-system/output/morning-log-.*\.json$",
    r"q-system/output/.*-actions-.*\.md$",
    r"q-system/output/.*-tasks-.*\.md$",
    r"q-system/output/.*-schedule-.*\.html$",
]

SHAME_WORDS = [
    (re.compile(r"\boverdue\b", re.IGNORECASE), "shame word: 'overdue' implies failure. Reframe as 'still open' or 'carried forward'"),
    (re.compile(r"\bmissed\b", re.IGNORECASE), "shame word: 'missed' implies failure. Reframe."),
    (re.compile(r"\bfailed\b", re.IGNORECASE), "shame word: 'failed' implies failure."),
    (re.compile(r"\bforgot\b", re.IGNORECASE), "shame word: 'forgot' implies failure."),
    (re.compile(r"\bforgotten\b", re.IGNORECASE), "shame word: 'forgotten' implies failure."),
    (re.compile(r"dropped the ball", re.IGNORECASE), "shame phrase: 'dropped the ball' is RSD trigger"),
    (re.compile(r"\bbehind on\b", re.IGNORECASE), "shame phrase: 'behind on' is RSD trigger"),
    (re.compile(r"you (need|should|must) (to )?have", re.IGNORECASE), "shame phrase: 'you should have' is RSD trigger"),
    (re.compile(r"you need to\b", re.IGNORECASE), "directive phrase: 'you need to' is RSD trigger. Use 'could' or just state the fact"),
    (re.compile(r"nobody responded", re.IGNORECASE), "outcome-shame: 'nobody responded' tracks outcome not effort"),
    (re.compile(r"\bghosted\b", re.IGNORECASE), "outcome-shame: 'ghosted' tracks outcome not effort"),
    (re.compile(r"\burgent(ly)?\b", re.IGNORECASE), "pressure word: 'urgent' triggers freeze response"),
    (re.compile(r"\bASAP\b"), "pressure word: 'ASAP' triggers freeze response"),
]

BACK_REFERENCES = [
    re.compile(r"\bsee above\b", re.IGNORECASE),
    re.compile(r"\bsee below\b", re.IGNORECASE),
    re.compile(r"\bsee section\b", re.IGNORECASE),
    re.compile(r"\bsee the previous\b", re.IGNORECASE),
    re.compile(r"\bas (mentioned|noted|discussed) (above|earlier)\b", re.IGNORECASE),
    re.compile(r"\bper (the )?above\b", re.IGNORECASE),
    re.compile(r"\brefer to (the )?above\b", re.IGNORECASE),
]

HTML_TASK_BLOCK_RE = re.compile(
    r"<(li|div)\b[^>]*\bclass\s*=\s*['\"][^'\"]*(task|item|action)[^'\"]*['\"][^>]*>(.*?)</\1>",
    re.DOTALL | re.IGNORECASE,
)
HTML_LI_RE = re.compile(r"<li\b[^>]*>(.*?)</li>", re.DOTALL | re.IGNORECASE)
LINK_RE = re.compile(r"<a\b[^>]*\bhref\s*=", re.IGNORECASE)
TIME_EST_RE = re.compile(r"\b(\d{1,3}\s*(min|hr|hour|m)\b|\(\s*\d+\s*(min|hr|m)\s*\))", re.IGNORECASE)
ENERGY_TAG_RE = re.compile(r"\b(quick win|deep focus|people|admin)\b", re.IGNORECASE)


def is_scope_path(file_path):
    path_str = str(file_path)
    for pattern in SCOPE_PATH_PATTERNS:
        if re.search(pattern, path_str):
            return True
    return False


def find_line_number(text, char_offset):
    return text[:char_offset].count("\n") + 1


def check_shame_words(text):
    violations = []
    for pattern, label in SHAME_WORDS:
        for match in pattern.finditer(text):
            line = find_line_number(text, match.start())
            violations.append({
                "rule": "shame-word",
                "line": line,
                "detail": f"{label} — found '{match.group()}'",
            })
    return violations


def check_back_references(text):
    violations = []
    for pattern in BACK_REFERENCES:
        for match in pattern.finditer(text):
            line = find_line_number(text, match.start())
            violations.append({
                "rule": "back-reference",
                "line": line,
                "detail": f"back-reference '{match.group()}' breaks working memory. Repeat the content inline instead.",
            })
    return violations


def check_schedule_html_structure(text, file_path):
    """For daily-schedule HTML: each task block should have a time estimate and a link."""
    if not str(file_path).endswith(".html"):
        return []
    if "schedule" not in str(file_path):
        return []
    violations = []
    task_blocks = HTML_TASK_BLOCK_RE.findall(text)
    if not task_blocks:
        task_blocks_li = HTML_LI_RE.findall(text)
        task_blocks = [(None, None, content) for content in task_blocks_li]
    if not task_blocks:
        return []
    blocks_without_time = 0
    blocks_without_link = 0
    for block in task_blocks:
        content = block[-1] if isinstance(block, tuple) else block
        if not TIME_EST_RE.search(content):
            blocks_without_time += 1
        if not LINK_RE.search(content):
            blocks_without_link += 1
    if blocks_without_time > 0:
        violations.append({
            "rule": "missing-time-estimate",
            "line": 1,
            "detail": f"{blocks_without_time} of {len(task_blocks)} task blocks have no time estimate (e.g., '(5 min)' or '15min')",
        })
    if blocks_without_link > 0:
        violations.append({
            "rule": "missing-clickable-link",
            "line": 1,
            "detail": f"{blocks_without_link} of {len(task_blocks)} task blocks have no clickable link. AUDHD rule: if it cannot be clicked, copy-pasted, or checked off, it does not belong.",
        })
    return violations


def check_morning_log_completeness(text, file_path):
    """For morning-log JSON: each step should have completion status."""
    if not str(file_path).endswith(".json"):
        return []
    try:
        data = json.loads(text)
    except Exception:
        return []
    violations = []
    steps = data.get("steps") or data.get("phases") or []
    if isinstance(steps, list):
        steps_without_status = [
            i for i, s in enumerate(steps)
            if isinstance(s, dict) and not s.get("status")
        ]
        if steps_without_status:
            violations.append({
                "rule": "step-without-status",
                "line": 1,
                "detail": f"{len(steps_without_status)} step(s) without completion status at indices {steps_without_status[:5]}",
            })
    return violations


def lint_file(file_path):
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except Exception as e:
        return [{"rule": "read-error", "line": 0, "detail": str(e)}]

    if SKIP_MARKER in text:
        return []

    violations = []
    violations.extend(check_shame_words(text))
    violations.extend(check_back_references(text))
    violations.extend(check_schedule_html_structure(text, file_path))
    violations.extend(check_morning_log_completeness(text, file_path))
    return violations


def format_report(file_path, violations):
    if not violations:
        return ""
    lines = [f"audhd-lint: {len(violations)} violation(s) in {file_path}:"]
    violations.sort(key=lambda v: (v["line"], v["rule"]))
    for v in violations:
        lines.append(f"  line {v['line']} [{v['rule']}] {v['detail']}")
    lines.append("")
    lines.append("Fix in place, or add <!-- audhd-lint-skip --> to bypass.")
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
    blocking, warnings = _partition(violations)
    if blocking:
        print(format_report(file_path, blocking), file=sys.stderr)
        sys.exit(2)
    if warnings:
        print(
            "audhd-lint (warnings, non-blocking):\n"
            + format_report(file_path, warnings),
            file=sys.stderr,
        )
    sys.exit(0)


def cli_mode(file_path):
    violations = lint_file(file_path)
    blocking, warnings = _partition(violations)
    if not violations:
        print(f"audhd-lint: clean ({file_path})")
        sys.exit(0)
    if blocking:
        print(format_report(file_path, blocking))
        sys.exit(2)
    print(
        "audhd-lint (warnings, non-blocking):\n"
        + format_report(file_path, warnings)
    )
    sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    elif len(sys.argv) == 2:
        cli_mode(sys.argv[1])
    else:
        print("Usage: audhd-lint.py <file_path>", file=sys.stderr)
        sys.exit(1)
