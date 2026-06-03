#!/usr/bin/env python3
"""
linkedin-format-lint.py — Deterministic LinkedIn format enforcer.

Pairs with the linkedin-brand skill. Catches deterministic violations the skill
relies on Claude remembering: CR 300-char limit, hashtag count, URL-in-body for
posts (links go in first comment), "I" opener for DMs/emails.

Usage:
    python3 linkedin-format-lint.py <file_path>

Exit codes:
    0 = clean (or scope skip)
    2 = violations found (PostToolUse hook contract — Claude must fix)

Override:
    Add <!-- linkedin-format-lint-skip --> anywhere in the file to bypass.

Scope:
    Fires when:
      - File path matches q-system/output/linkedin-*.md or similar LinkedIn output paths
      - Or file frontmatter contains platform: linkedin
      - Or file frontmatter contains kind: cr|dm|email|post|comment
"""

import json
import re
import sys
from pathlib import Path

SKIP_MARKER = "linkedin-format-lint-skip"

LINKEDIN_PATH_PATTERNS = [
    r"q-system/output/linkedin-.*\.md$",
    r"q-system/marketing/.*linkedin.*\.md$",
    r"q-system/output/.*-linkedin-.*\.md$",
]

CR_MAX_CHARS = 300
DM_EMAIL_MAX_HASHTAGS = 0
POST_MAX_HASHTAGS = 1

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
HASHTAG_RE = re.compile(r"(?<![A-Za-z0-9_])#[A-Za-z][A-Za-z0-9_]+")
URL_RE = re.compile(r"https?://[^\s)]+")


def parse_frontmatter(text):
    """Return dict of frontmatter fields. Empty dict if no frontmatter."""
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


def is_linkedin_path(file_path):
    """Return True if path matches LinkedIn output patterns."""
    path_str = str(file_path)
    for pattern in LINKEDIN_PATH_PATTERNS:
        if re.search(pattern, path_str):
            return True
    return False


def should_lint(file_path, text):
    """Decide whether this file is in scope based on path or frontmatter."""
    if is_linkedin_path(file_path):
        return True, parse_frontmatter(text)[0]
    fields, _ = parse_frontmatter(text)
    if fields.get("platform") == "linkedin":
        return True, fields
    if fields.get("kind") in {"cr", "dm", "email", "post", "comment"}:
        return True, fields
    return False, {}


def find_line_number(text, char_offset):
    return text[:char_offset].count("\n") + 1


def first_meaningful_line(body):
    """Return the first non-empty line of the body (skipping frontmatter)."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def check_cr_length(body, fields):
    """Connection request: max 300 chars in the body."""
    if fields.get("kind") != "cr":
        return []
    text_only = body.strip()
    length = len(text_only)
    if length > CR_MAX_CHARS:
        return [{
            "rule": "cr-length",
            "line": 1,
            "detail": f"Connection request is {length} chars (max {CR_MAX_CHARS}). Trim by {length - CR_MAX_CHARS}.",
        }]
    return []


def check_hashtags(body, fields):
    """Posts: at most 1 hashtag. DMs/emails/CRs: zero."""
    kind = fields.get("kind", "")
    hashtags = HASHTAG_RE.findall(body)
    if not hashtags:
        return []
    if kind in {"dm", "email", "cr", "comment"}:
        return [{
            "rule": "hashtag-in-non-post",
            "line": 1,
            "detail": f"{kind} contains hashtag(s) {hashtags}. Remove all hashtags from {kind}s.",
        }]
    if kind == "post" and len(hashtags) > POST_MAX_HASHTAGS:
        return [{
            "rule": "hashtag-overuse",
            "line": 1,
            "detail": f"Post contains {len(hashtags)} hashtags {hashtags} (max {POST_MAX_HASHTAGS}).",
        }]
    return []


def check_url_in_post_body(body, fields):
    """LinkedIn posts: URLs go in first comment, not the body."""
    if fields.get("kind") != "post":
        return []
    urls = URL_RE.findall(body)
    if urls:
        return [{
            "rule": "url-in-post-body",
            "line": 1,
            "detail": f"Post body contains URL(s) {urls}. Put external links in the first comment, not the post body.",
        }]
    return []


def check_dm_email_opener(body, fields):
    """DMs and emails must open with 'I' as the subject. No 'Name, ...' openers."""
    if fields.get("kind") not in {"dm", "email"}:
        return []
    opener = first_meaningful_line(body)
    if not opener:
        return []
    if opener.lower().startswith("subject:"):
        return []
    first_word = re.search(r"\b([A-Za-z']+)\b", opener)
    if not first_word:
        return []
    word = first_word.group(1)
    if word == "I":
        return []
    if word == "Hi" or word == "Hello" or word == "Hey":
        return [{
            "rule": "dm-greeting-opener",
            "line": 1,
            "detail": f"{fields.get('kind')} opens with greeting '{word}'. Start with 'I' as the subject instead.",
        }]
    if re.match(r"[A-Z][a-z]+,", opener):
        return [{
            "rule": "dm-name-opener",
            "line": 1,
            "detail": f"{fields.get('kind')} opens with 'Name, ...' pattern. Start with 'I' as the subject instead.",
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

    violations = []
    violations.extend(check_cr_length(body, fields))
    violations.extend(check_hashtags(body, fields))
    violations.extend(check_url_in_post_body(body, fields))
    violations.extend(check_dm_email_opener(body, fields))
    return violations


def format_report(file_path, violations):
    if not violations:
        return ""
    lines = [f"linkedin-format-lint: {len(violations)} violation(s) in {file_path}:"]
    for v in violations:
        lines.append(f"  [{v['rule']}] {v['detail']}")
    lines.append("")
    lines.append("Fix in place, or add <!-- linkedin-format-lint-skip --> to bypass.")
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
        print(f"linkedin-format-lint: clean ({file_path})")
        sys.exit(0)
    print(format_report(file_path, violations))
    sys.exit(2)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    elif len(sys.argv) == 2:
        cli_mode(sys.argv[1])
    else:
        print("Usage: linkedin-format-lint.py <file_path>", file=sys.stderr)
        sys.exit(1)
