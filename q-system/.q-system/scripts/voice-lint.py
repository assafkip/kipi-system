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

# CALIBRATED AGAINST THE FOUNDER'S OWN CORPUS, never grown by taste. "robust" and
# "foster" were dropped 2026-09-06. The one instance that holds his voice corpus
# had already removed both on 2026-08-27 (its PR #71) after counting the lemmas
# there (7 and 16), and the fleet sync put them back because the skeleton never
# learned. Re-measured whole-word on 2026-09-06, which is what this list
# matches: "robust" in 5 corpus rows ("a robust understanding of the
# attackers"), "foster" in 5, and "fosters" / "fostering" in 11 more that the
# whole-word match never saw. A word he demonstrably writes is not AI-sounding
# in his voice, and a ban list that refuses his real vocabulary is the six-word
# scar again. Two executables hold it: the instance's
# pipeline/tests/test_voice_list_audit.py pins this list's size, and
# q-system/.q-system/tests/test_voice_lint_calibration.py pins the size here
# and refuses the dropped words in every other copy of the list (scan-draft.py,
# compliance-check.py, the MCP DraftScanner), which is where the same two words
# survived the first removal.
BANNED_WORDS = {
    "leverage", "transformative", "innovative", "cutting-edge",
    "groundbreaking", "delve", "tapestry", "synergy", "paradigm", "cornerstone",
    "linchpin", "testament", "vital", "pivotal", "crucial", "meticulous",
    "nuanced", "vibrant", "enduring", "unparalleled", "unwavering",
    "intricate", "comprehensive",
    "utilize", "optimize", "underscore", "embark", "garner",
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
    "it's worth mentioning", "it is worth mentioning",
    "it's worth noting", "it is worth noting", "worth highlighting",
    # Consultant-report tells (2026-07-28, caught in a client email draft).
    "one flag", "one thing you should know", "here is where each one stands",
    "here's where each one stands", "a few things to flag", "quick flag",
    "wanted to flag", "at a high level", "net net", "net-net",
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

# --- capitalization -------------------------------------------------------
# WHY (2026-07-28): a client email shipped in all-lowercase because voice-dna.md
# says "Lowercase-default. Rarely capitalizes." That describes the founder's
# Slack/DM register, not published writing. Every rule above judges word choice;
# none judged casing, so nothing caught it. Published content gets real caps.
PROPER_NOUN_FILENAME = "proper-nouns.txt"

# Leading markdown that is not part of the sentence: blockquote, heading, list
# marker, emphasis. Stripped before the first letter is inspected.
LINE_PREFIX_RE = re.compile(r"^[\s>]*(?:#{1,6}\s+)?(?:(?:[-*+]|\d+[.)])\s+)?[*_]{0,2}")
URL_LINE_RE = re.compile(r"^\s*(?:https?://|www\.|!?\[)")
LIST_OR_HEADING_RE = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)")
TABLE_ROW_RE = re.compile(r"^\s*\|")
# A code-ish identifier: two or more lowercase alphanumeric segments joined by a
# hyphen or an underscore. Repo slugs, package names, CLI tools, skill names.
#
# THIS IS THE REPAIRER'S "LEAVE IT ALONE" TEST AND NOTHING ELSE. It does not exempt
# anything from the capitalization CHECK -- `check_capitalization` is untouched and
# every channel still blocks on a lowercase sentence start exactly as before.
#
# WHY THE SPLIT (2026-08-10, founder-directed): two different defects hide under one
# rule and they need opposite treatments. Conflating them is why this rule kept
# burning the retry budget.
#
#   - A correctly-lowercase IDENTIFIER ('pi-from-scratch', 'phone-harness',
#     'reverse-skill'). Capitalizing it CORRUPTS the tool's name, so it must never be
#     repaired. What it needs is a lane-level relaxation, which lives in the send
#     path's registry (voice_send_gate.DIGEST_DOWNGRADE), not in this fleet linter.
#   - A genuine lowercase ENGLISH sentence start. One correct answer exists and a
#     machine can produce it, so it is repaired in place and never costs a
#     regeneration.
#
# A shape, not a name list: a list needs an edit for every new tool, which is the
# same outage one release later.
CODE_ISH_TOKEN_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)+$")

# "i" alone. i.e. is excluded; inline code is already stripped upstream.
BARE_I_RE = re.compile(r"\bi\b(?!\.e\.)")
# A period that ends a sentence, not one inside an abbreviation or a decimal.
SENTENCE_END_RE = re.compile(r"(?<![A-Z])(?<!\b[a-z])[.!?]['\")\]]*\s+")
ABBREVIATIONS = {
    "e.g", "i.e", "vs", "etc", "mr", "mrs", "ms", "dr", "prof", "st", "ave",
    "blvd", "inc", "ltd", "co", "jr", "sr", "approx", "no", "fig", "al",
}

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
    "emphasis-opener",
    "rhetorical-qa",
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


def load_proper_nouns(file_path):
    """Read the nearest `canonical/proper-nouns.txt` above the linted file.

    Opt-in by construction: an instance that has not written the file gets no
    proper-noun checking at all. Same switch shape as the evidence gate, and for
    the same reason -- blocking every unknown capitalized word in the first draft
    an instance ever writes teaches people to reach for the bypass.
    """
    try:
        current = Path(file_path).resolve().parent
    except Exception:
        return []
    for directory in [current, *current.parents]:
        candidate = directory / "canonical" / PROPER_NOUN_FILENAME
        if candidate.is_file():
            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
            except Exception:
                return []
            return [
                line.strip()
                for line in lines
                if line.strip() and not line.lstrip().startswith("#")
            ]
    return []


def strip_code_preserving_lines(text):
    """strip_code_for_prose_check, but every removed span keeps its newlines.

    WHY: the plain stripper collapses code fences, so a violation's reported line
    number drifts from the source file by however many fenced lines preceded it.
    A line number that does not match the file is worse than no line number --
    it sends the reader to the wrong place.
    """
    def blanked(match):
        return "\n" * match.group().count("\n")

    text = FRONTMATTER_RE.sub(blanked, text)
    text = CODE_FENCE_RE.sub(blanked, text)
    text = INLINE_CODE_RE.sub("__CODE__", text)
    text = BLOCKQUOTE_RE.sub("", text)
    return text


def _ends_a_sentence(line):
    """Does this line end on a real sentence terminator?"""
    stripped = line.rstrip().rstrip("*_`)\"'")
    if not stripped:
        return False
    if stripped[-1] not in ".!?":
        return False
    last = stripped.split()[-1].rstrip(".!?").lower()
    return last not in ABBREVIATIONS


def _is_sentence_break(line, index):
    """Is the terminator at `index` a real break, or punctuation inside a quote?"""
    if line[:index].count('"') % 2 == 1:
        return False
    preceding = line[:index].split()
    if preceding and preceding[-1].rstrip(".!?").lower() in ABBREVIATIONS:
        return False
    return True


def _sentence_start_offsets(text):
    """Offsets in `text` where a sentence begins.

    A line start only counts when the line opens a block (list item, heading,
    post-blank-line paragraph) or the previous line closed a sentence. Without
    that test every soft-wrapped continuation line reads as a new sentence, which
    is most of the prose in this repo.
    """
    offsets = []
    lines = text.split("\n")
    cursor = 0
    previous = ""
    for line in lines:
        start = cursor
        cursor += len(line) + 1
        if not line.strip() or URL_LINE_RE.match(line) or TABLE_ROW_RE.match(line):
            previous = line
            continue
        opens_block = bool(LIST_OR_HEADING_RE.match(line)) or not previous.strip()
        if opens_block or _ends_a_sentence(previous):
            prefix = LINE_PREFIX_RE.match(line)
            offsets.append(start + (prefix.end() if prefix else 0))
        for end in SENTENCE_END_RE.finditer(line):
            if _is_sentence_break(line, end.start()):
                offsets.append(start + end.end())
        previous = line
    return offsets


def check_capitalization(text, file_path=""):
    """Published prose uses real capitalization. Three deterministic checks."""
    violations = []
    prose = strip_code_preserving_lines(text)

    for offset in _sentence_start_offsets(prose):
        rest = prose[offset:]
        token = re.match(r"[A-Za-z][\w'-]*", rest)
        if not token or token.group() == "__CODE__":
            continue
        word = token.group()
        if word[0].isupper():
            continue
        violations.append({
            "rule": "capitalization",
            "line": find_line_number(prose, offset),
            "detail": f"sentence starts lowercase: '{word}' (published content uses real caps)",
        })

    for match in BARE_I_RE.finditer(prose):
        violations.append({
            "rule": "capitalization",
            "line": find_line_number(prose, match.start()),
            "detail": "bare 'i' (use 'I')",
        })

    for noun in load_proper_nouns(file_path):
        pattern = re.compile(r"\b" + re.escape(noun).replace(r"\ ", r"\s+") + r"\b", re.IGNORECASE)
        for match in pattern.finditer(prose):
            seen = match.group()
            if seen == noun or seen.isupper():
                continue
            violations.append({
                "rule": "capitalization",
                "line": find_line_number(prose, match.start()),
                "detail": f"proper noun miscased: '{seen}' should be '{noun}'",
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


EMPHASIS_OPENERS = {"importantly", "notably", "crucially", "significantly"}

RHETORICAL_ANSWER_LEAD_RE = re.compile(
    r"^(because|so|yes|no|simple|the answer|that's|it's|here's|turns out|nope|exactly|none|short answer)\b",
    re.IGNORECASE,
)
# Real reader-directed questions are NOT rhetorical setups; do not flag them.
READER_DIRECTED_Q_RE = re.compile(
    r"\b(what do you|how do you|have you|did you|can you|would you|are you|do you)\b",
    re.IGNORECASE,
)


def check_emphasis_opener(text):
    """Sentence-initial emphasis openers ('Importantly,'/'Notably,'/...). AI cadence
    tell. WARN-class: anchored to sentence start + trailing comma so 'runs significantly
    faster' (mid-sentence) does not flag. (H8-remainder.)"""
    violations = []
    prose_text = strip_code_for_prose_check(text)
    paragraphs = prose_text.split("\n\n")
    cursor = 0
    for para in paragraphs:
        para_start = prose_text.find(para, cursor)
        if para_start == -1:
            para_start = cursor
        cursor = para_start + len(para)
        if para.lstrip().startswith("#"):
            continue
        for sentence in split_sentences(para):
            m = re.match(r"([A-Za-z]+),", sentence)
            if m and m.group(1).lower() in EMPHASIS_OPENERS:
                line = find_line_number(text, para_start)
                violations.append({
                    "rule": "emphasis-opener",
                    "line": line,
                    "detail": f"sentence-initial emphasis opener: '{m.group(1)},' (AI cadence tell; rephrase or drop)",
                })
    return violations


def check_rhetorical_qa(text):
    """Short rhetorical question answered by the next short/connector-led sentence
    ('The result? A cleaner pipeline.'). AI cadence tell. WARN-class: suppresses real
    reader-directed questions and #-headings to bound false positives. (H9.)"""
    violations = []
    prose_text = strip_code_for_prose_check(text)
    paragraphs = prose_text.split("\n\n")
    cursor = 0
    for para in paragraphs:
        para_start = prose_text.find(para, cursor)
        if para_start == -1:
            para_start = cursor
        cursor = para_start + len(para)
        if para.lstrip().startswith("#"):
            continue
        sentences = split_sentences(para)
        for i in range(len(sentences) - 1):
            q = sentences[i].strip()
            a = sentences[i + 1].strip()
            if not q.endswith("?"):
                continue
            if word_count(q) > 9:
                continue
            if READER_DIRECTED_Q_RE.search(q):
                continue
            if word_count(a) <= 8 or RHETORICAL_ANSWER_LEAD_RE.match(a):
                line = find_line_number(text, para_start)
                violations.append({
                    "rule": "rhetorical-qa",
                    "line": line,
                    "detail": f"rhetorical question answered by the next sentence: '{q[:40]}' -> '{a[:40]}' (AI cadence tell)",
                })
    return violations


_LOWERCASE_START_RE = re.compile(r"sentence starts lowercase: \'([^\']+)\'")


def repair_capitalization(text):
    """(repaired_text, [words_fixed], [words_left_alone]). Pure: no file IO.

    REPAIR-FIRST (founder 2026-08-03: "we need to fix that earlier in the loop so
    things get capitalized and not blocked ... and not continuously blocked because
    the capitalization doesn't work", restated 2026-08-10: "the rule was that you
    dont reject - you fix until it can come out").

    That directive lived for a week as a CODE COMMENT above a call to a `--fix` mode
    that did not exist, whose exit code was discarded. The loop quietly went back to
    reject-and-regenerate and nobody could see it. This is the executable.

    It repairs exactly what `check_capitalization` FLAGS -- the violation list is the
    input -- so the repairer can never disagree with the checker about what a
    sentence start is. Two derivations of one rule is how a repair loop starts fixing
    things the gate does not care about and missing the ones it does.

    It edits by LINE NUMBER, which `strip_code_preserving_lines` preserves on
    purpose, and never by character offset, which that function does NOT preserve
    (it blanks fences to newlines and swaps inline code for a different-length
    token). An offset-based repair would land in the wrong place in any file
    containing a code fence.

    SCOPED to the first flagged word on its line. A mid-line sentence start is left
    for the gate rather than rewritten, because editing inside a line is where a URL
    or a code span would get corrupted, and a repairer that is sometimes wrong is
    worse than one that is sometimes silent.
    """
    lines = text.split("\n")
    fixed, left = [], []
    for violation in check_capitalization(text):
        found = _LOWERCASE_START_RE.search(violation.get("detail", ""))
        if not found:
            continue
        word = found.group(1)
        # THE SPLIT. An identifier is correct as written; capitalizing it would
        # corrupt a tool name, which is a worse outcome than the block.
        if CODE_ISH_TOKEN_RE.match(word):
            left.append(word)
            continue
        index = violation.get("line", 0) - 1
        if not 0 <= index < len(lines):
            continue
        pattern = re.compile(r"(?<![\w'-])" + re.escape(word) + r"(?![\w'-])")
        replaced, count = pattern.subn(word[0].upper() + word[1:], lines[index], 1)
        if count:
            lines[index] = replaced
            fixed.append(word)
    return "\n".join(lines), fixed, left


def fix_file(file_path):
    """Repair casing in place. Returns (fixed, left_alone). Writes only on a change."""
    with open(file_path, encoding="utf-8") as handle:
        text = handle.read()
    repaired, fixed, left = repair_capitalization(text)
    if repaired != text:
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(repaired)
    return fixed, left


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
    all_violations.extend(check_capitalization(text, file_path))
    all_violations.extend(check_rule_of_three(text))
    all_violations.extend(check_comma_triplet(text))
    all_violations.extend(check_cross_paragraph_fragments(text))
    all_violations.extend(check_sentence_uniformity(text))
    all_violations.extend(check_hedge_density(text))
    all_violations.extend(check_single_sentence_paragraph(text))
    all_violations.extend(check_bold_restatement(text))
    all_violations.extend(check_emphasis_opener(text))
    all_violations.extend(check_rhetorical_qa(text))
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


def fix_mode(file_path):
    """`--fix`: repair what can be repaired, report what was deliberately not.

    Exit 0 on success, whether or not anything needed repairing -- "nothing to fix"
    is a success, and a caller that treats it as failure would hold every clean
    draft. Exit 1 only when the file cannot be read or written, which is a real
    fault the caller must see. Scar 2026-08-10: this mode did not exist, the call
    hit the usage branch, exited 1, and the caller discarded it, so a repair step
    that never ran once looked identical to one that worked.
    """
    try:
        fixed, left = fix_file(file_path)
    except OSError as exc:
        print(f"voice-lint --fix: cannot repair {file_path}: {exc}", file=sys.stderr)
        return 1
    if fixed:
        print(f"voice-lint --fix: capitalized {len(fixed)} sentence start(s): "
              f"{', '.join(fixed)}")
    if left:
        print(f"voice-lint --fix: left {len(left)} identifier(s) alone (correct as "
              f"written): {', '.join(left)}")
    if not fixed and not left:
        print(f"voice-lint --fix: nothing to repair ({file_path})")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    elif len(sys.argv) == 2:
        cli_mode(sys.argv[1])
    elif len(sys.argv) == 3 and sys.argv[1] == "--fix":
        sys.exit(fix_mode(sys.argv[2]))
    else:
        print("Usage: voice-lint.py [--fix] <file_path>", file=sys.stderr)
        sys.exit(1)
