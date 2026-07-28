#!/usr/bin/env python3
"""
voice-substance-lint.py - Positive-pattern voice enforcement.

The voice-lint catches deterministic AI fingerprints (banned words, em dashes,
rule-of-three, etc.). Those are what NOT to do. This script catches the
absence of what TO do: the cadence-without-substance failure mode.

A draft passes voice-lint if it avoids the banned patterns. But a draft can
have the SHAPE of voice (short declaratives, contrast pairs) without any
specific anchor and still read as AI cadence. That's the gap.

This script enforces presence of at least one anchor across three categories
for any prose over 200 words:

  1. WITNESS pattern: "I built", "I shipped", "I watched", "I ran", "I tested",
     "I engaged", "I wanted to", "I have been", "At [Company]", etc.
  2. SPECIFIC NAMED ENTITY: a proper noun that is dated or has context
     (e.g., "Google", "Meta", "Q3 2024", "iOS 17", "claudedaddy")
  3. CONCRETE NUMBER: a number tied to a real-world observation
     ($2k, 60 tools, 4 teams, 30 hours, 87%, etc.)

If the draft has ZERO of the three, it fires. Below 200 words the rule is
softer: requires at least 1 of the 3 above 80 words.

Stdlib only.

Usage:
    python3 voice-substance-lint.py <file_path>

Exit codes:
    0 = clean (has substance)
    2 = violation (cadence-without-substance pattern detected)

Override:
    Add `<!-- voice-lint-skip -->` anywhere in the file to bypass.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path


SKIP_MARKER = "voice-lint-skip"

# Heuristic / probabilistic rules with a real false-positive rate are WARN-class:
# they print a non-blocking warning and exit 0 rather than hard-blocking (exit 2).
# This linter emits only "no-substance-anchor" (a fuzzy first-N-words substance
# heuristic), so it is WARN-only and never hard-blocks. Every other rule this
# linter might emit is implicitly BLOCK.
WARN_RULES = frozenset({"no-substance-anchor"})

CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
BLOCKQUOTE_RE = re.compile(r"^>\s.*$", re.MULTILINE)

WITNESS_PHRASES = [
    r"\bI built\b", r"\bI shipped\b", r"\bI watched\b", r"\bI ran\b",
    r"\bI tested\b", r"\bI engaged\b", r"\bI wanted to\b",
    r"\bI have been\b", r"\bI was in\b", r"\bI was at\b",
    r"\bI worked\b", r"\bI saw\b", r"\bI did\b", r"\bI tried\b",
    r"\bAt \w+,?\s+I\b", r"\bI noticed\b", r"\bI argue\b",
    r"\bI suggest\b", r"\bI spent\b", r"\bI walked\b",
    r"\bI checked\b", r"\bI hit\b", r"\bI rolled\b",
    r"\bI sat\b", r"\bI broke\b", r"\bI started\b",
    r"\bwhen I\b", r"\bafter I\b", r"\bbefore I\b",
    r"\bI used\b", r"\bI deployed\b", r"\bI fixed\b",
    r"\bI patched\b", r"\bI launched\b", r"\bI rewrote\b",
    r"\bI dropped\b", r"\bI added\b", r"\bI cut\b",
]

WORD_RE = re.compile(r"\b[\w'-]+\b")
NUMBER_RE = re.compile(r"\b\d[\d,\.]*\b")
PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-zA-Z0-9]{2,}\b")

GENERIC_PROPER_NOUNS = {
    "Claude", "ChatGPT", "OpenAI", "Anthropic", "GitHub", "Linux",
    "Windows", "Python", "JavaScript", "TypeScript", "React",
    "AI", "API", "MCP", "URL", "JSON", "HTML", "CSS", "SQL",
    "True", "False", "None", "And", "But", "The", "This", "That",
    "When", "Where", "Why", "How", "What", "Who",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    "Saturday", "Sunday", "January", "February", "March", "April",
    "May", "June", "July", "August", "September", "October",
    "November", "December", "PostToolUse", "PreToolUse", "UserPromptSubmit",
    "Edit", "Write", "MultiEdit",
}


def strip_code_for_prose_check(text):
    text = FRONTMATTER_RE.sub("", text)
    text = CODE_FENCE_RE.sub("", text)
    text = INLINE_CODE_RE.sub(" ", text)
    text = BLOCKQUOTE_RE.sub("", text)
    return text


def word_count(text):
    return len(WORD_RE.findall(text))


def find_witness_matches(text):
    matches = []
    for pattern in WITNESS_PHRASES:
        for m in re.finditer(pattern, text):
            matches.append(m.group())
    return matches


def find_number_matches(text):
    return [m.group() for m in NUMBER_RE.finditer(text)]


SENTENCE_START_CAP_RE = re.compile(r'(?:\A|(?<=[.!?]\s)|(?<=\n\n))([A-Z])')


def find_specific_proper_nouns(text):
    """Find specific proper nouns, filtering out sentence-initial capitals.

    A specific proper noun is a capitalized word that is NOT just the first
    word of a sentence. Google in "I worked at Google" counts.
    Convergence in "Convergence happens" does not.

    Strategy: lowercase the first letter of every sentence, then look for
    surviving capitalized words. Anything still capitalized must be
    mid-sentence or otherwise non-initial.
    """
    normalized = SENTENCE_START_CAP_RE.sub(lambda m: m.group(1).lower(), text)
    found = []
    for m in PROPER_NOUN_RE.finditer(normalized):
        word = m.group()
        if word in GENERIC_PROPER_NOUNS:
            continue
        found.append(word)
    return found


def lint(text):
    if SKIP_MARKER in text:
        return []
    prose = strip_code_for_prose_check(text)
    total_words = word_count(prose)
    if total_words < 80:
        return []
    witnesses = find_witness_matches(prose)
    numbers = find_number_matches(prose)
    proper_nouns = find_specific_proper_nouns(prose)
    has_witness = len(witnesses) >= 1
    has_number = len(numbers) >= 1
    has_proper = len(proper_nouns) >= 1
    # H10: count TOTAL anchors (a single dropped brand name is not enough);
    # require >=2. Stays WARN-class (no-substance-anchor in WARN_RULES; never hard-blocks).
    anchor_count = len(witnesses) + len(numbers) + len(proper_nouns)
    if total_words >= 200:
        if anchor_count < 2:
            return [{
                "rule": "no-substance-anchor",
                "detail": (
                    f"draft has {total_words} words but fewer than 2 concrete anchors. "
                    "Needs at least one of: witness phrase (I built/I shipped/...), "
                    "specific named entity (not generic), or concrete number. "
                    "Cadence without substance reads as AI."
                ),
            }]
    elif total_words >= 80:
        if anchor_count < 2:
            return [{
                "rule": "no-substance-anchor",
                "detail": (
                    f"draft has {total_words} words and fewer than 2 concrete anchors. "
                    "Add a witness phrase, named entity, or concrete number."
                ),
            }]
    return []


def _partition(violations):
    blocking = [v for v in violations if v.get("rule") not in WARN_RULES]
    warnings = [v for v in violations if v.get("rule") in WARN_RULES]
    return blocking, warnings


def format_report(file_path, violations):
    if not violations:
        return ""
    lines = [f"voice-substance-lint: {len(violations)} violation(s) in {file_path}:"]
    for v in violations:
        lines.append(f"  [{v['rule']}] {v['detail']}")
    lines.append("")
    lines.append("Add a real anchor or add <!-- voice-lint-skip --> to bypass (intentional exception only).")
    return "\n".join(lines)


def _load_is_published_path():
    """Reuse voice-lint's published-path scope so both lints fire on exactly the same files."""
    try:
        vl_path = Path(__file__).resolve().parent / "voice-lint.py"
        spec = importlib.util.spec_from_file_location("voice_lint", vl_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.is_published_path
    except Exception:
        return lambda p: str(p).endswith(".md") and any(
            s in str(p)
            for s in ("/output/", "/marketing/", "/articles/", "/blog/", "/posts/", "/social/",
                      "linkedin", "medium", "substack")
        )


_is_published_path = _load_is_published_path()


def hook_mode():
    """PostToolUse entrypoint: self-scope to published content, exit 2 on violation."""
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if payload.get("tool_name", "") not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)
    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not file_path or not _is_published_path(file_path):
        sys.exit(0)
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except Exception:
        sys.exit(0)
    violations = lint(text)
    blocking, warnings = _partition(violations)
    if blocking:
        print(format_report(file_path, blocking), file=sys.stderr)
        sys.exit(2)
    if warnings:
        print(
            "voice-substance-lint (warnings, non-blocking):\n"
            + format_report(file_path, warnings),
            file=sys.stderr,
        )
    sys.exit(0)


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("Usage: voice-substance-lint.py <file_path>\n")
        sys.exit(1)
    file_path = sys.argv[1]
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except Exception as e:
        sys.stderr.write(f"voice-substance-lint: read error: {e}\n")
        sys.exit(0)
    violations = lint(text)
    blocking, warnings = _partition(violations)
    if blocking:
        print(format_report(file_path, blocking))
        sys.exit(2)
    if warnings:
        print(
            "voice-substance-lint (warnings, non-blocking):\n"
            + format_report(file_path, warnings)
        )
        sys.exit(0)
    print(f"voice-substance-lint: clean ({file_path})")
    sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    else:
        main()
