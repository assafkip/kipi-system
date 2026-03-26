#!/usr/bin/env python3
"""
Deterministic anti-AI scanner for bus files.
Greps JSON copy fields for banned words/phrases from founder-voice.
LLMs miss their own banned words. This script does not.

Usage:
    python3 scan-draft.py <bus-file.json>
    python3 scan-draft.py <bus-file.json> --json

Exit 0 = pass (no violations)
Exit 1 = fail (violations found)
"""

import json
import re
import sys
import os

# --- Banned words (from founder-voice SKILL.md) ---

TIER1_WORDS = [
    "delve", "comprehensive", "crucial", "vital", "pivotal", "robust",
    "innovative", "transformative", "intricate", "meticulous", "nuanced",
    "vibrant", "enduring", "unparalleled", "unwavering", "cutting-edge",
    "groundbreaking", "unprecedented", "tapestry", "synergy", "realm",
    "beacon", "interplay", "treasure trove", "paradigm", "cornerstone",
    "catalyst", "linchpin", "testament",
]

TIER1_VERBS = [
    "leverage", "utilize", "optimize", "foster", "underscore", "embark",
    "garner", "bolster", "showcase", "enhance", "empower", "unlock",
    "revolutionize", "streamline", "spearhead",
]

TIER1_ADVERBS = [
    "meticulously", "effectively", "efficiently", "strategically",
    "consistently", "seamlessly", "furthermore", "moreover",
    "additionally", "indeed",
]

BANNED_PHRASES = [
    "in today's world", "in today's fast-paced", "in today's era",
    "let's dive in", "let's explore", "let's unpack",
    "it's important to note", "it's crucial to note", "it's worth noting",
    "generally speaking",
    "in conclusion", "to sum up",
    "that said", "with that in mind",
    "this is where .+ comes in",
    "game-changer", "unlock the potential", "revolutionize the way",
    "a pivotal moment", "new era", "let's face it",
    "great question", "that's a really interesting point",
    "i hope this helps",
    "circling back", "just checking in", "following up on my last message",
    "i'm excited to", "thrilled to share", "proud to say", "humbled by",
]

HEDGING_WORDS = ["might", "could", "perhaps", "generally", "somewhat", "arguably"]

EMDASH = "\u2014"

# --- Compile patterns ---

ALL_BANNED = TIER1_WORDS + TIER1_VERBS + TIER1_ADVERBS
WORD_PATTERNS = [re.compile(r'\b' + re.escape(w) + r'\b', re.IGNORECASE) for w in ALL_BANNED]
PHRASE_PATTERNS = [re.compile(p, re.IGNORECASE) for p in BANNED_PHRASES]
HEDGE_PATTERNS = [re.compile(r'\b' + re.escape(w) + r'\b', re.IGNORECASE) for w in HEDGING_WORDS]


def extract_text_fields(data, prefix=""):
    """Recursively extract all string fields that look like copy."""
    texts = []
    if isinstance(data, dict):
        for key, val in data.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(val, str) and key in (
                "copy", "linkedin_draft", "x_thread", "rewritten_copy",
                "full_post_text", "dm_text", "cr_text", "comment_text",
                "email_body", "subject", "body", "text", "draft",
            ):
                texts.append((path, val))
            elif isinstance(val, (dict, list)):
                texts.extend(extract_text_fields(val, path))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            texts.extend(extract_text_fields(item, f"{prefix}[{i}]"))
    return texts


def scan_text(field_path, text):
    """Scan a single text field. Return list of violations."""
    violations = []

    for pattern in WORD_PATTERNS:
        for match in pattern.finditer(text):
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            violations.append({
                "type": "banned_word",
                "word": match.group(),
                "field": field_path,
                "context": text[start:end].replace("\n", " "),
            })

    for pattern in PHRASE_PATTERNS:
        for match in pattern.finditer(text):
            start = max(0, match.start() - 20)
            end = min(len(text), match.end() + 20)
            violations.append({
                "type": "banned_phrase",
                "word": match.group(),
                "field": field_path,
                "context": text[start:end].replace("\n", " "),
            })

    emdash_count = text.count(EMDASH)
    if emdash_count > 0:
        violations.append({
            "type": "emdash",
            "word": "emdash",
            "field": field_path,
            "context": f"{emdash_count} emdash(es) found",
        })

    return violations


def compute_hedging_density(all_text):
    """Count hedging words per 500 words across all text."""
    words = all_text.split()
    word_count = len(words)
    if word_count == 0:
        return 0.0, 0

    hedge_count = 0
    for pattern in HEDGE_PATTERNS:
        hedge_count += len(pattern.findall(all_text))

    density = hedge_count / (word_count / 500) if word_count >= 50 else 0.0
    return density, hedge_count


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scan-draft.py <bus-file.json> [--json]", file=sys.stderr)
        sys.exit(2)

    filepath = sys.argv[1]
    json_output = "--json" in sys.argv

    if not os.path.exists(filepath):
        print(f"File not found: {filepath}", file=sys.stderr)
        sys.exit(2)

    with open(filepath) as f:
        data = json.load(f)

    text_fields = extract_text_fields(data)

    all_violations = []
    all_text = ""

    for field_path, text in text_fields:
        all_text += " " + text
        violations = scan_text(field_path, text)
        all_violations.extend(violations)

    hedging_density, hedge_count = compute_hedging_density(all_text)
    hedging_fail = hedging_density > 1.0

    if hedging_fail:
        all_violations.append({
            "type": "hedging_density",
            "word": f"{hedge_count} hedging words",
            "field": "all_fields",
            "context": f"Density: {hedging_density:.1f} per 500 words (max 1.0)",
        })

    passed = len(all_violations) == 0
    word_count = len(all_text.split())

    result = {
        "pass": passed,
        "file": os.path.basename(filepath),
        "fields_scanned": len(text_fields),
        "words_scanned": word_count,
        "violation_count": len(all_violations),
        "hedging_density": round(hedging_density, 2),
        "violations": all_violations,
    }

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        if passed:
            print(f"PASS  {os.path.basename(filepath)}  ({word_count} words, {len(text_fields)} fields)")
        else:
            print(f"FAIL  {os.path.basename(filepath)}  ({len(all_violations)} violations)")
            for v in all_violations:
                print(f"  [{v['type']}] \"{v['word']}\" in {v['field']}")
                print(f"    ...{v['context']}...")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
