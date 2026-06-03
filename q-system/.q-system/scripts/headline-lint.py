#!/usr/bin/env python3
"""
headline-lint.py — Deterministic headline pattern enforcer.

Pairs with the headline-engineering skill. Catches AI-style title shapes,
char-count violations, hedge words, gratitude tells, and first-7-words emptiness.

Usage:
    python3 headline-lint.py <file_path>

Exit codes:
    0 = clean (or out of scope)
    2 = violations found

Override:
    Add <!-- headline-lint-skip --> anywhere in the file to bypass.

Scope:
    Fires when:
      - File path matches q-system/output/articles/*.md or q-system/marketing/*.md
      - Or file frontmatter contains platform: x|reddit|linkedin|medium|substack
      - Or file frontmatter contains kind: post|article
"""

import json
import re
import sys
from pathlib import Path

SKIP_MARKER = "headline-lint-skip"

HEADLINE_PATH_PATTERNS = [
    r"q-system/output/articles/.*\.md$",
    r"q-system/marketing/.*\.md$",
    r"q-system/output/linkedin-.*\.md$",
    r"q-system/output/medium-.*\.md$",
    r"q-system/output/substack-.*\.md$",
    r"q-system/output/.*-post-.*\.md$",
]

PLATFORM_RANGES = {
    "x": (30, 110, 71, 100),
    "twitter": (30, 110, 71, 100),
    "reddit": (15, 100, 30, 66),
    "linkedin": (40, 150, 60, 100),
    "medium": (30, 100, 50, 90),
    "substack": (30, 110, 60, 90),
}

BANNED_TITLE_PATTERNS = [
    (re.compile(r"^the ultimate guide", re.IGNORECASE), "'The Ultimate Guide to X' is dead AI-listicle shape"),
    (re.compile(r"^\d+\s+(things|ways|tips|tricks|reasons|secrets)\b", re.IGNORECASE), "'N Things You Need to Know' listicle (unless N is unusual)"),
    (re.compile(r"^how to\b", re.IGNORECASE), "'How to X' is too soft for AI-savvy audiences"),
    (re.compile(r"^mastering\b", re.IGNORECASE), "'Mastering X' is content-marketer voice"),
    (re.compile(r"^unlocking\b", re.IGNORECASE), "'Unlocking the Power of X' is content-marketer voice"),
    (re.compile(r"^why .+ matters$", re.IGNORECASE), "'Why X Matters' without a number or scar is empty"),
    (re.compile(r":\s+a\s+comprehensive\b", re.IGNORECASE), "': A Comprehensive [Guide/Look/Analysis]' is consultancy shape"),
    (re.compile(r"\bin today'?s (fast-paced|rapidly evolving|digital|connected)", re.IGNORECASE), "'In Today's Fast-Paced World' is the AI tell"),
    (re.compile(r"\b(top|best|essential)\s+\d+\b", re.IGNORECASE), "Generic 'Top N / Best N / Essential N' listicle (unusual N might pass)"),
    (re.compile(r"\b(game[- ]?changer|game[- ]?changing)\b", re.IGNORECASE), "'Game-changer' is empty hype"),
]

HEDGE_WORDS_IN_TITLE = re.compile(r"\b(might|could|perhaps|maybe|possibly|arguably|somewhat)\b", re.IGNORECASE)
GRATITUDE_TELLS = re.compile(r"\b(excited|thrilled|humbled|proud)\b\s+(to|by|that)", re.IGNORECASE)

EMDASH_RE = re.compile(r"—")

STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "if", "of", "on", "in", "at", "to",
    "for", "with", "by", "from", "as", "is", "are", "was", "were", "be", "been",
    "this", "that", "these", "those", "it", "its", "i", "you", "we", "they",
    "my", "your", "our", "their", "his", "her",
    "what", "why", "how", "when", "where", "who",
}

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


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


def is_headline_path(file_path):
    path_str = str(file_path)
    for pattern in HEADLINE_PATH_PATTERNS:
        if re.search(pattern, path_str):
            return True
    return False


def should_lint(file_path, text):
    fields, _ = parse_frontmatter(text)
    if is_headline_path(file_path):
        return True, fields
    if fields.get("platform") in PLATFORM_RANGES:
        return True, fields
    if fields.get("kind") in {"post", "article"}:
        return True, fields
    return False, {}


def extract_h1(body):
    """Return (title, line_number) for the first H1, or (None, 0)."""
    for i, line in enumerate(body.splitlines(), start=1):
        match = H1_RE.match(line)
        if match:
            return match.group(1).strip(), i
    return None, 0


def first_n_words(title, n=7):
    return re.findall(r"\b[\w'-]+\b", title)[:n]


def has_specific_anchor(first_words):
    """Pass if any of the first 7 words contains a digit, a proper noun, or a long content word."""
    for word in first_words:
        if any(c.isdigit() for c in word):
            return True
        if len(word) >= 3 and word[0].isupper() and word.lower() not in STOP_WORDS:
            return True
        if len(word) >= 6 and word.lower() not in STOP_WORDS:
            return True
    return False


def check_banned_patterns(title):
    violations = []
    for pattern, label in BANNED_TITLE_PATTERNS:
        if pattern.search(title):
            violations.append({"rule": "banned-title-pattern", "detail": f"title matches banned shape: {label}"})
    return violations


def check_title_hedges(title):
    if HEDGE_WORDS_IN_TITLE.search(title):
        match = HEDGE_WORDS_IN_TITLE.search(title)
        return [{"rule": "title-hedge", "detail": f"hedge word in title: '{match.group()}'"}]
    return []


def check_gratitude_tell(title):
    if GRATITUDE_TELLS.search(title):
        match = GRATITUDE_TELLS.search(title)
        return [{"rule": "gratitude-tell", "detail": f"gratitude word in title: '{match.group()}'"}]
    return []


def check_emdash_title(title):
    if EMDASH_RE.search(title):
        return [{"rule": "title-emdash", "detail": "em dash in title (use comma, period, or hyphen instead)"}]
    return []


def check_char_count(title, fields):
    platform = fields.get("platform", "")
    if platform not in PLATFORM_RANGES:
        return []
    abs_min, abs_max, sweet_min, sweet_max = PLATFORM_RANGES[platform]
    length = len(title)
    if length < abs_min:
        return [{"rule": "title-too-short", "detail": f"title is {length} chars (platform {platform} minimum {abs_min})"}]
    if length > abs_max:
        return [{"rule": "title-too-long", "detail": f"title is {length} chars (platform {platform} maximum {abs_max})"}]
    if length < sweet_min or length > sweet_max:
        return [{"rule": "title-outside-sweet-spot", "detail": f"title is {length} chars (platform {platform} sweet spot {sweet_min}-{sweet_max})"}]
    return []


def check_first_seven_words(title):
    words = first_n_words(title, 7)
    if not has_specific_anchor(words):
        return [{
            "rule": "weak-first-seven",
            "detail": f"first 7 words ({' '.join(words)}) have no specific anchor (digit, proper noun, or content word). Front-load the punch.",
        }]
    return []


def lint_file(file_path):
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except Exception as e:
        return [{"rule": "read-error", "line": 0, "detail": str(e)}]

    if SKIP_MARKER in text:
        return []

    in_scope, fields = should_lint(file_path, text)
    if not in_scope:
        return []

    _, body = parse_frontmatter(text)
    if not body:
        body = text

    title, line_no = extract_h1(body)
    if not title:
        return []

    violations = []
    for v in check_banned_patterns(title):
        v["line"] = line_no
        violations.append(v)
    for v in check_title_hedges(title):
        v["line"] = line_no
        violations.append(v)
    for v in check_gratitude_tell(title):
        v["line"] = line_no
        violations.append(v)
    for v in check_emdash_title(title):
        v["line"] = line_no
        violations.append(v)
    for v in check_char_count(title, fields):
        v["line"] = line_no
        violations.append(v)
    for v in check_first_seven_words(title):
        v["line"] = line_no
        violations.append(v)
    return violations


def format_report(file_path, violations):
    if not violations:
        return ""
    lines = [f"headline-lint: {len(violations)} violation(s) in {file_path}:"]
    for v in violations:
        line_str = f"line {v.get('line', 0)} " if v.get("line") else ""
        lines.append(f"  {line_str}[{v['rule']}] {v['detail']}")
    lines.append("")
    lines.append("Fix the title in place, or add <!-- headline-lint-skip --> to bypass.")
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
        print(f"headline-lint: clean ({file_path})")
        sys.exit(0)
    print(format_report(file_path, violations))
    sys.exit(2)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    elif len(sys.argv) == 2:
        cli_mode(sys.argv[1])
    else:
        print("Usage: headline-lint.py <file_path>", file=sys.stderr)
        sys.exit(1)
