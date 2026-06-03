#!/usr/bin/env python3
"""
batch-uniformity-lint.py — Catches uniform openers across multiple post/comment blocks.

Pairs with the assaf-voice batch uniformity rule:
  "No more than 2 comments can share the same opening pattern."

Fires only on files containing 3+ post/comment blocks. Blocks detected via:
  - Headings like `### Comment 1`, `### Post N`, `### DM N`
  - `---` separators (3+ in a file)
  - Lists of structured items with consistent shape

Usage:
    python3 batch-uniformity-lint.py <file_path>

Exit codes:
    0 = clean (or out of scope)
    2 = violations found

Override:
    Add <!-- batch-uniformity-lint-skip --> to bypass.
"""

import json
import re
import sys
from pathlib import Path

SKIP_MARKER = "batch-uniformity-lint-skip"

SCOPE_PATH_PATTERNS = [
    r"q-system/output/.*hitlist.*\.md$",
    r"q-system/output/.*engagement.*\.md$",
    r"q-system/output/.*comments?.*\.md$",
    r"q-system/output/.*outreach.*\.md$",
    r"q-system/output/.*batch.*\.md$",
    r"q-system/output/.*dms?.*\.md$",
    r"q-system/output/.*posts?.*\.md$",
    r"q-system/marketing/.*\.md$",
]

BLOCK_HEADING_RE = re.compile(
    r"^#{2,4}\s+(comment|post|dm|message|reply|outreach|reaction)\s*\d*",
    re.IGNORECASE | re.MULTILINE,
)
HR_SEPARATOR_RE = re.compile(r"^---\s*$", re.MULTILINE)

FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


def is_scope_path(file_path):
    path_str = str(file_path)
    for pattern in SCOPE_PATH_PATTERNS:
        if re.search(pattern, path_str):
            return True
    return False


def strip_frontmatter(text):
    return FRONTMATTER_RE.sub("", text)


def extract_blocks(text):
    """Return list of block strings. A block is a chunk separated by H2-H4 heading or --- separator."""
    body = strip_frontmatter(text)
    heading_positions = [m.start() for m in BLOCK_HEADING_RE.finditer(body)]
    if len(heading_positions) >= 3:
        positions = heading_positions + [len(body)]
        blocks = []
        for i in range(len(positions) - 1):
            block_text = body[positions[i]:positions[i+1]].strip()
            block_lines = block_text.splitlines()
            content_lines = [l for l in block_lines[1:] if l.strip()]
            if content_lines:
                blocks.append("\n".join(content_lines))
        return blocks
    hr_positions = [m.start() for m in HR_SEPARATOR_RE.finditer(body)]
    if len(hr_positions) >= 3:
        positions = [0] + hr_positions + [len(body)]
        blocks = []
        for i in range(len(positions) - 1):
            chunk = body[positions[i]:positions[i+1]]
            chunk = re.sub(r"^---\s*$", "", chunk, flags=re.MULTILINE).strip()
            if chunk:
                blocks.append(chunk)
        return blocks
    return []


def opener_signature(block, n_words=4):
    """Return the first n_words of the block (normalized) as the opener signature."""
    words = re.findall(r"\b[\w']+\b", block.lower())
    return tuple(words[:n_words])


def short_opener_signature(block):
    """First lexical word, used as the opener pattern signature.
    Voice DNA rule: 'No more than 2 comments can share the same opening pattern.'
    First word is the simplest deterministic proxy for pattern.
    """
    words = re.findall(r"\b[\w']+\b", block.lower())
    return tuple(words[:1])


def word_count(text):
    return len(re.findall(r"\b[\w'-]+\b", text))


def check_opener_uniformity(blocks):
    if len(blocks) < 3:
        return []
    violations = []
    short_sigs = [short_opener_signature(b) for b in blocks]
    seen = {}
    for i, sig in enumerate(short_sigs):
        if not sig:
            continue
        seen.setdefault(sig, []).append(i)
    for sig, indices in seen.items():
        if len(indices) > 2:
            violations.append({
                "rule": "opener-uniformity",
                "line": 1,
                "detail": f"{len(indices)} blocks share the same opener pattern '{' '.join(sig)}' (max 2 allowed). Indices: {indices}",
            })
    return violations


def check_length_uniformity(blocks):
    if len(blocks) < 3:
        return []
    lengths = [word_count(b) for b in blocks]
    if max(lengths) - min(lengths) <= 3 and min(lengths) >= 5:
        return [{
            "rule": "length-uniformity",
            "line": 1,
            "detail": f"all {len(blocks)} blocks have nearly identical length ({lengths}). Vary block sizes.",
        }]
    return []


def lint_file(file_path):
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except Exception as e:
        return [{"rule": "read-error", "line": 0, "detail": str(e)}]

    if SKIP_MARKER in text:
        return []

    blocks = extract_blocks(text)
    if len(blocks) < 3:
        return []

    violations = []
    violations.extend(check_opener_uniformity(blocks))
    violations.extend(check_length_uniformity(blocks))
    return violations


def format_report(file_path, violations):
    if not violations:
        return ""
    lines = [f"batch-uniformity-lint: {len(violations)} violation(s) in {file_path}:"]
    for v in violations:
        lines.append(f"  [{v['rule']}] {v['detail']}")
    lines.append("")
    lines.append("Vary block openers and lengths, or add <!-- batch-uniformity-lint-skip --> to bypass.")
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
        print(f"batch-uniformity-lint: clean ({file_path})")
        sys.exit(0)
    print(format_report(file_path, violations))
    sys.exit(2)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    elif len(sys.argv) == 2:
        cli_mode(sys.argv[1])
    else:
        print("Usage: batch-uniformity-lint.py <file_path>", file=sys.stderr)
        sys.exit(1)
