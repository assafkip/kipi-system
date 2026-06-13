#!/usr/bin/env python3
"""
voice-lint.py — Deterministic voice rule enforcer (v2).

Pairs with the assaf-voice / founder-voice skill.

v2 additions over v1:
- Comma-triplets within a single sentence (3-item parallel comma lists)
- Cross-paragraph fragment chains (3+ consecutive short single-sentence paragraphs)
- Mandatory contractions ("do not" / "is not" etc. flagged in prose)
- Hedge word density (>1 per 500 words triggers)
- Single-sentence-paragraph requirement (at least one in the document)
- Sentence-length uniformity (3 consecutive sentences with similar length)
- Bold-title bullet restatement (**X** followed by "X is/are/means..." restatement)

Usage:
    python3 voice-lint.py <file_path>

Exit codes:
    0 = clean, OR only heuristic WARN-class rules fired (printed to stderr,
        non-blocking)
    2 = a deterministic BLOCK-class violation found (PostToolUse hook
        contract — Claude must fix). See WARN_RULES for the warn-only set.

Override:
    Add <!-- voice-lint-skip --> anywhere in the file to bypass entirely.

Scope:
    Only fires on files matching published-content paths. See is_published_path().
"""

import json
import os
import re
import sys
from pathlib import Path

PUBLISHED_PATH_PATTERNS = [
    # q-system canonical content paths (original scope)
    r"q-system/output/articles/.*\.md$",
    r"q-system/marketing/.*\.md$",
    r"q-system/output/.*-post-.*\.md$",
    r"q-system/output/.*-draft-.*\.md$",
    r"q-system/output/linkedin-.*\.md$",
    r"q-system/output/medium-.*\.md$",
    r"q-system/output/substack-.*\.md$",
    # Backstop scope for agent-pipeline content.
    r"agent-pipeline/bus/[^/]+/tl-content\.json$",
    r"agent-pipeline/bus/[^/]+/signals\.json$",
    r"agent-pipeline/bus/[^/]+/signal-outreach\.json$",
    r"agent-pipeline/bus/[^/]+/outreach-queue\.json$",
    r"agent-pipeline/bus/[^/]+/hitlist\.json$",
    r"agent-pipeline/bus/[^/]+/pipeline-followup\.json$",
    r"agent-pipeline/bus/[^/]+/dp-pipeline\.json$",
    # Generic published-content paths (any project, any depth).
    # These catch the typical places non-q-system instances publish from.
    r".*/articles/.*\.md$",
    r".*/blog/.*\.md$",
    r".*/posts/.*\.md$",
    r".*/newsletter/.*\.md$",
    r".*/launch/.*\.md$",
    r".*/outreach/.*\.md$",
    r".*/marketing/.*\.md$",
    r".*/social/.*\.md$",
    r".*/linkedin[^/]*\.md$",
    r".*/twitter[^/]*\.md$",
    r".*/x[-_][^/]*\.md$",
    r".*/medium[^/]*\.md$",
    r".*/substack[^/]*\.md$",
    r".*/email[-_][^/]*\.md$",
    r".*/dm[-_][^/]*\.md$",
    r".*/reply[-_][^/]*\.md$",
    r".*/post[-_][^/]*\.md$",
    r".*/draft[-_][^/]*\.md$",
    r".*[-_]post[-_].*\.md$",
    r".*[-_]draft[-_].*\.md$",
    r".*[-_]reply[-_].*\.md$",
]

SKIP_MARKER = "voice-lint-skip"

BANNED_WORDS = {
    "leverage", "robust", "transformative", "innovative", "cutting-edge",
    "groundbreaking", "delve", "tapestry", "synergy", "paradigm", "cornerstone",
    "linchpin", "testament", "vital", "pivotal", "crucial", "meticulous",
    "nuanced", "vibrant", "enduring", "unparalleled", "unwavering",
    "intricate", "comprehensive",
    "utilize", "optimize", "foster", "underscore", "embark", "garner",
    "bolster", "showcase", "empower", "unlock", "revolutionize",
    "streamline", "spearhead",
    "meticulously", "effectively", "efficiently", "strategically",
    "consistently", "seamlessly", "furthermore", "moreover", "additionally",
    "thrilled", "humbled",
}

BANNED_PHRASES = [
    "in today's", "let's dive in", "let's explore", "let's unpack",
    "it's important to note", "it's crucial to note", "generally speaking",
    "in conclusion", "to sum up", "that said", "with that in mind",
    "this is where", "game-changer", "game changer",
    "let's face it", "great question", "hope this helps",
    "circling back", "just checking in", "following up on my last",
    "excited to announce", "excited to share", "proud to say",
]

NON_CONTRACTED_NEGATIONS = [
    r"\b(do not)\b", r"\b(does not)\b", r"\b(did not)\b",
    r"\b(is not)\b", r"\b(are not)\b", r"\b(was not)\b", r"\b(were not)\b",
    r"\b(have not)\b", r"\b(has not)\b", r"\b(had not)\b",
    r"\b(will not)\b", r"\b(would not)\b", r"\b(could not)\b",
    r"\b(should not)\b", r"\b(must not)\b",
    r"\b(can not)\b", r"\bcannot\b",
]

HEDGE_WORDS = re.compile(
    r"\b(might|could|perhaps|maybe|possibly|arguably|somewhat|generally|"
    r"often|sometimes|kind of|sort of|seem|seems|seemed)\b",
    re.IGNORECASE,
)

STAT_PATTERNS = [
    (re.compile(r"\b\d+\s*%"), "percentage figure"),
    (re.compile(r"\b\d+\s+percent\b", re.IGNORECASE), "percentage spelled out"),
    (re.compile(r"\b\d+x\s+(more|better|faster|higher)\b", re.IGNORECASE), "Xx multiplier claim"),
    (re.compile(r"according to (research|the survey|the study|a study)", re.IGNORECASE), "vendor-stat citation"),
    (re.compile(r"(survey|study|research) (found|showed|reported|revealed)", re.IGNORECASE), "vendor-stat citation"),
    (re.compile(r"Stack Overflow Developer Survey", re.IGNORECASE), "Stack Overflow citation"),
    (re.compile(r"Pew Research", re.IGNORECASE), "Pew Research citation"),
    (re.compile(r"McKinsey (says|found|reports|estimates)", re.IGNORECASE), "McKinsey citation"),
    (re.compile(r"HCLTech (says|found|reports)", re.IGNORECASE), "HCLTech citation"),
]

SLASH_COMMAND_RE = re.compile(r"`/q-[a-z][a-z0-9-]*`")
EMDASH_RE = re.compile(r"—")

CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
BLOCKQUOTE_RE = re.compile(r"^>\s.*$", re.MULTILINE)

# Heuristic/probabilistic rules with a real false-positive rate. These warn
# (exit 0 + stderr) instead of blocking. Every other rule is implicitly BLOCK
# (deterministic, ~0 false-positive) and exits 2.
WARN_RULES = frozenset({
    "rule-of-three",
    "rule-of-three-density",
    "comma-triplet",
    "cross-paragraph-fragments",
    "sentence-uniformity",
    "hedge-density",
    "no-single-sentence-paragraph",
    "bold-restatement",
    "missing-contraction",
})


def is_published_path(file_path):
    path_str = str(file_path)
    for pattern in PUBLISHED_PATH_PATTERNS:
        if re.search(pattern, path_str):
            return True
    return False


def strip_code_for_prose_check(text):
    """Remove code fences, inline code, frontmatter, and blockquotes."""
    text = FRONTMATTER_RE.sub("", text)
    text = CODE_FENCE_RE.sub("", text)
    text = INLINE_CODE_RE.sub("__CODE__", text)
    text = BLOCKQUOTE_RE.sub("", text)
    return text


def find_line_number(text, match_start):
    return text[:match_start].count("\n") + 1


def split_sentences(paragraph):
    parts = re.split(r"(?<=[.!?])\s+", paragraph.strip())
    return [p.strip() for p in parts if p.strip()]


def first_word(sentence):
    match = re.search(r"\b([A-Za-z']+)\b", sentence)
    return match.group(1).lower() if match else None


def word_count(sentence):
    return len(re.findall(r"\b[\w'-]+\b", sentence))


def check_banned_words(text):
    violations = []
    prose_text = strip_code_for_prose_check(text)
    for word in BANNED_WORDS:
        pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
        for match in pattern.finditer(prose_text):
            line = find_line_number(text, match.start())
            violations.append({"rule": "banned-word", "line": line, "detail": f"banned word: '{match.group()}'"})
    return violations


def check_banned_phrases(text):
    violations = []
    prose_text = strip_code_for_prose_check(text).lower()
    for phrase in BANNED_PHRASES:
        idx = prose_text.find(phrase)
        while idx != -1:
            line = find_line_number(text, idx)
            violations.append({"rule": "banned-phrase", "line": line, "detail": f"banned phrase: '{phrase}'"})
            idx = prose_text.find(phrase, idx + 1)
    return violations


def check_stats(text):
    violations = []
    prose_text = strip_code_for_prose_check(text)
    for pattern, label in STAT_PATTERNS:
        for match in pattern.finditer(prose_text):
            line = find_line_number(text, match.start())
            violations.append({"rule": "stats-citation", "line": line, "detail": f"{label}: '{match.group()}'"})
    return violations


def check_slash_commands(text):
    violations = []
    for match in SLASH_COMMAND_RE.finditer(text):
        line = find_line_number(text, match.start())
        violations.append({"rule": "slash-command", "line": line, "detail": f"slash command in published content: {match.group()} (use prose form like 'the X skill')"})
    return violations


def check_emdash(text):
    violations = []
    for match in EMDASH_RE.finditer(text):
        line = find_line_number(text, match.start())
        violations.append({"rule": "emdash", "line": line, "detail": "em dash (use comma, period, or hyphen instead)"})
    return violations


def check_contractions(text):
    violations = []
    prose_text = strip_code_for_prose_check(text)
    seen = set()
    for pattern in NON_CONTRACTED_NEGATIONS:
        regex = re.compile(pattern, re.IGNORECASE)
        for match in regex.finditer(prose_text):
            line = find_line_number(text, match.start())
            key = (line, match.group())
            if key in seen:
                continue
            seen.add(key)
            violations.append({
                "rule": "missing-contraction",
                "line": line,
                "detail": f"non-contracted negation '{match.group()}' (use the contracted form)",
            })
    return violations


def check_hedge_density(text):
    prose_text = strip_code_for_prose_check(text)
    total_words = max(word_count(prose_text), 1)
    hedges = HEDGE_WORDS.findall(prose_text)
    if total_words < 100:
        return []
    ratio = len(hedges) / total_words
    threshold = 1 / 500
    if ratio > threshold and len(hedges) >= 2:
        return [{
            "rule": "hedge-density",
            "line": 1,
            "detail": f"hedge density {len(hedges)} hedges per {total_words} words (max 1 per 500). Found: {hedges[:5]}{'...' if len(hedges) > 5 else ''}",
        }]
    return []


def check_single_sentence_paragraph(text):
    prose_text = strip_code_for_prose_check(text)
    paragraphs = [p.strip() for p in prose_text.split("\n\n") if p.strip()]
    content_paragraphs = [p for p in paragraphs if not p.startswith("#")]
    if not content_paragraphs:
        return []
    for p in content_paragraphs:
        sentences = split_sentences(p)
        if len(sentences) == 1:
            return []
    return [{
        "rule": "no-single-sentence-paragraph",
        "line": 1,
        "detail": f"document has {len(content_paragraphs)} content paragraphs, none single-sentence. Voice DNA mandates at least one.",
    }]


def check_comma_triplet(text):
    """Detect 3-item parallel comma lists within a single sentence."""
    violations = []
    prose_text = strip_code_for_prose_check(text)
    paragraphs = prose_text.split("\n\n")
    cursor = 0
    for para in paragraphs:
        para_start = prose_text.find(para, cursor)
        if para_start == -1:
            para_start = cursor
        cursor = para_start + len(para)
        sentences = split_sentences(para)
        for sentence in sentences:
            chunks = re.split(r",\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+", sentence)
            chunks = [c.strip() for c in chunks if c.strip() and c.strip()[-1] not in ".!?" or True]
            chunks = [c for c in chunks if c]
            if len(chunks) != 3:
                continue
            if not all(2 <= word_count(c) <= 8 for c in chunks):
                continue
            first_words = [first_word(c) for c in chunks]
            if first_words[0] and first_words[0] == first_words[1] == first_words[2]:
                line = find_line_number(text, para_start)
                violations.append({
                    "rule": "comma-triplet",
                    "line": line,
                    "detail": f"three parallel comma-separated phrases starting with '{first_words[0]}': '{sentence[:80]}...'",
                })
                continue
            lens = [word_count(c) for c in chunks]
            if max(lens) - min(lens) <= 1 and all(l <= 4 for l in lens):
                line = find_line_number(text, para_start)
                violations.append({
                    "rule": "comma-triplet",
                    "line": line,
                    "detail": f"three short parallel comma-separated items ({lens} words each) in: '{sentence[:80]}...'",
                })
    return violations


def check_cross_paragraph_fragments(text):
    """Detect chains of 3+ consecutive short single-sentence paragraphs."""
    violations = []
    prose_text = strip_code_for_prose_check(text)
    paragraphs = prose_text.split("\n\n")
    short_para_indices = []
    cursor = 0
    para_positions = []
    for p in paragraphs:
        start = prose_text.find(p, cursor) if p else cursor
        if start == -1:
            start = cursor
        para_positions.append((start, p))
        cursor = start + len(p) + 2
    chain = []
    for start, para in para_positions:
        para_stripped = para.strip()
        if not para_stripped or para_stripped.startswith("#"):
            if len(chain) >= 3:
                first_start = chain[0][0]
                line = find_line_number(text, first_start)
                violations.append({
                    "rule": "cross-paragraph-fragments",
                    "line": line,
                    "detail": f"chain of {len(chain)} consecutive short single-sentence paragraphs starting line {line}",
                })
            chain = []
            continue
        sentences = split_sentences(para_stripped)
        if len(sentences) == 1 and word_count(sentences[0]) <= 7:
            chain.append((start, sentences[0]))
        else:
            if len(chain) >= 3:
                first_start = chain[0][0]
                line = find_line_number(text, first_start)
                violations.append({
                    "rule": "cross-paragraph-fragments",
                    "line": line,
                    "detail": f"chain of {len(chain)} consecutive short single-sentence paragraphs starting line {line}",
                })
            chain = []
    if len(chain) >= 3:
        first_start = chain[0][0]
        line = find_line_number(text, first_start)
        violations.append({
            "rule": "cross-paragraph-fragments",
            "line": line,
            "detail": f"chain of {len(chain)} consecutive short single-sentence paragraphs starting line {line}",
        })
    return violations


def check_sentence_uniformity(text):
    """Detect 3+ consecutive sentences with very similar word counts.

    v2: dropped the 5-word floor. AI's most common cadence tell is short
    clipped declaratives ("The X is Y. The Z isn't W."). Excluding sentences
    under 5 words let exactly those patterns pass undetected. Now flags
    triples within 1-word range across any length from 2 to 18.
    """
    violations = []
    prose_text = strip_code_for_prose_check(text)
    paragraphs = prose_text.split("\n\n")
    cursor = 0
    for para in paragraphs:
        para_start = prose_text.find(para, cursor) if para else cursor
        if para_start == -1:
            para_start = cursor
        cursor = para_start + len(para)
        sentences = split_sentences(para)
        if len(sentences) < 3:
            continue
        for i in range(len(sentences) - 2):
            counts = [word_count(s) for s in sentences[i:i+3]]
            if max(counts) - min(counts) <= 1 and 2 <= min(counts) <= 18:
                line = find_line_number(text, para_start)
                violations.append({
                    "rule": "sentence-uniformity",
                    "line": line,
                    "detail": f"three consecutive sentences with uniform length ({counts} words): '{sentences[i][:40]}...'",
                })
                break
    return violations


def check_rule_of_three(text):
    """Detect three-of-a-kind sentence-opener patterns.

    v2: in addition to the original 3-consecutive same-first-word check,
    now also flags repeated-opener DENSITY: 3+ sentences in any 5-sentence
    window starting with the same word. Catches the AI pattern of
    "The X. The Y. [longer]. [longer]. The Z." that the consecutive check
    misses.
    """
    violations = []
    prose_text = strip_code_for_prose_check(text)
    paragraphs = prose_text.split("\n\n")
    cursor = 0
    # density check across the whole document
    all_sentences = []
    for para in paragraphs:
        all_sentences.extend(split_sentences(para))
    seen_density = set()
    if len(all_sentences) >= 5:
        for start in range(len(all_sentences) - 4):
            window = all_sentences[start:start+5]
            firsts = [first_word(s) for s in window]
            from collections import Counter
            counts = Counter(w for w in firsts if w)
            for word, c in counts.items():
                if c >= 3 and word not in seen_density:
                    seen_density.add(word)
                    violations.append({
                        "rule": "rule-of-three-density",
                        "line": 1,
                        "detail": f"opener '{word}' appears {c} times in a 5-sentence window starting at sentence {start+1}",
                    })
    for para in paragraphs:
        para_start = prose_text.find(para, cursor) if para else cursor
        if para_start == -1:
            para_start = cursor
        cursor = para_start + len(para)
        sentences = split_sentences(para)
        for i in range(len(sentences) - 2):
            s1, s2, s3 = sentences[i], sentences[i+1], sentences[i+2]
            w1, w2, w3 = first_word(s1), first_word(s2), first_word(s3)
            if w1 and w1 == w2 == w3:
                line = find_line_number(text, para_start)
                violations.append({
                    "rule": "rule-of-three",
                    "line": line,
                    "detail": f"three consecutive sentences start with '{w1}': '{s1[:40]}...' / '{s2[:40]}...' / '{s3[:40]}...'",
                })
                continue
            words = [word_count(s) for s in (s1, s2, s3)]
            if all(w <= 3 for w in words) and all(s.endswith(".") for s in (s1, s2, s3)):
                line = find_line_number(text, para_start)
                violations.append({
                    "rule": "rule-of-three",
                    "line": line,
                    "detail": f"three consecutive single-noun sentences: '{s1}' / '{s2}' / '{s3}'",
                })
    return violations


def check_bold_restatement(text):
    """Detect **X** followed by a sentence restating X."""
    violations = []
    bold_pattern = re.compile(r"\*\*([^*\n]{2,50})\*\*\s*[:\.]?\s*\n?([^\n]+)")
    for match in bold_pattern.finditer(text):
        bold_text = match.group(1).strip().rstrip(".:")
        following = match.group(2).strip()
        first_word_of_bold = first_word(bold_text)
        first_word_of_following = first_word(following)
        if first_word_of_bold and first_word_of_following == first_word_of_bold:
            line = find_line_number(text, match.start())
            violations.append({
                "rule": "bold-restatement",
                "line": line,
                "detail": f"bold title '**{bold_text}**' is restated in the following sentence (AI fingerprint)",
            })
    return violations


def lint_file(file_path):
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except Exception as e:
        return [{"rule": "read-error", "line": 0, "detail": str(e)}]

    if SKIP_MARKER in text:
        return []

    all_violations = []
    all_violations.extend(check_emdash(text))
    all_violations.extend(check_banned_words(text))
    all_violations.extend(check_banned_phrases(text))
    all_violations.extend(check_stats(text))
    all_violations.extend(check_slash_commands(text))
    all_violations.extend(check_contractions(text))
    all_violations.extend(check_rule_of_three(text))
    all_violations.extend(check_comma_triplet(text))
    all_violations.extend(check_cross_paragraph_fragments(text))
    all_violations.extend(check_sentence_uniformity(text))
    all_violations.extend(check_hedge_density(text))
    all_violations.extend(check_single_sentence_paragraph(text))
    all_violations.extend(check_bold_restatement(text))
    return all_violations


def _partition(violations):
    blocking = [v for v in violations if v.get("rule") not in WARN_RULES]
    warnings = [v for v in violations if v.get("rule") in WARN_RULES]
    return blocking, warnings


def format_report(file_path, violations):
    if not violations:
        return ""
    lines = [f"voice-lint: {len(violations)} violation(s) in {file_path}:"]
    violations.sort(key=lambda v: (v["line"], v["rule"]))
    for v in violations:
        lines.append(f"  line {v['line']} [{v['rule']}] {v['detail']}")
    lines.append("")
    lines.append("Fix in place, or add <!-- voice-lint-skip --> to bypass (intentional exception only).")
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

    if not is_published_path(file_path):
        sys.exit(0)

    violations = lint_file(file_path)
    blocking, warnings = _partition(violations)
    if blocking:
        print(format_report(file_path, blocking), file=sys.stderr)
        sys.exit(2)
    if warnings:
        print(
            "voice-lint (warnings, non-blocking):\n"
            + format_report(file_path, warnings),
            file=sys.stderr,
        )
    sys.exit(0)


def cli_mode(file_path):
    violations = lint_file(file_path)
    blocking, warnings = _partition(violations)
    if not violations:
        print(f"voice-lint: clean ({file_path})")
        sys.exit(0)
    if blocking:
        print(format_report(file_path, blocking))
    if warnings:
        print(
            "voice-lint (warnings, non-blocking):\n"
            + format_report(file_path, warnings)
        )
    sys.exit(2 if blocking else 0)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    elif len(sys.argv) == 2:
        cli_mode(sys.argv[1])
    else:
        print("Usage: voice-lint.py <file_path>", file=sys.stderr)
        sys.exit(1)
