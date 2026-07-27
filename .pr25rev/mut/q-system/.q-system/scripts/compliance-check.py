#!/usr/bin/env python3
"""
Deterministic compliance check for generated content.
Checks all bus output against canonical positioning rules and flags violations.
Replaces the 06-compliance-check LLM agent.

Reuses banned word lists from scan-draft.py.

Usage:
    python3 compliance-check.py <date>
    python3 compliance-check.py <date> --json

Exit 0 = pass (no auto-fail violations)
Exit 1 = fail (auto-fail violations found)
"""

import json
import os
import re
import sys
from glob import glob

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUS_BASE = os.path.join(QROOT, ".q-system", "agent-pipeline", "bus")

# Import banned words from scan-draft.py's definitions (kept in sync)
BANNED_WORDS = [
    "delve", "comprehensive", "crucial", "vital", "pivotal", "robust",
    "innovative", "transformative", "intricate", "meticulous", "nuanced",
    "vibrant", "enduring", "unparalleled", "unwavering", "cutting-edge",
    "groundbreaking", "unprecedented", "tapestry", "synergy", "realm",
    "beacon", "interplay", "treasure trove", "paradigm", "cornerstone",
    "catalyst", "linchpin", "testament",
    "leverage", "utilize", "optimize", "foster", "underscore", "embark",
    "garner", "bolster", "showcase", "enhance", "empower", "unlock",
    "revolutionize", "streamline", "spearhead",
]

BANNED_PHRASES = [
    "circling back", "just checking in", "following up on my last message",
    "game-changer", "game changing", "single pane of glass", "next-gen",
    "AI-powered",
]

HEDGING_WORDS = ["might", "could", "perhaps", "generally", "somewhat", "arguably"]

EMDASH = "\u2014"

# Compile patterns
WORD_PATTERNS = [re.compile(r'\b' + re.escape(w) + r'\b', re.IGNORECASE) for w in BANNED_WORDS]
PHRASE_PATTERNS = [re.compile(re.escape(p), re.IGNORECASE) for p in BANNED_PHRASES]
HEDGE_PATTERNS = [re.compile(r'\b' + re.escape(w) + r'\b', re.IGNORECASE) for w in HEDGING_WORDS]


def read_bus_file(bus_dir, filename):
    """Read JSON bus file, return None if missing."""
    path = os.path.join(bus_dir, filename)
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def read_file(path):
    """Read text file, return empty string if missing."""
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


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
                "message", "note",
            ):
                texts.append((path, val))
            elif isinstance(val, (dict, list)):
                texts.extend(extract_text_fields(val, path))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            texts.extend(extract_text_fields(item, f"{prefix}[{i}]"))
    return texts


def parse_is_not_list(current_state_content):
    """Extract 'What We Are NOT' items from current-state.md."""
    items = []
    m = re.search(r'##\s*What We Are NOT.*?\n(.*?)(?=\n##|\Z)', current_state_content, re.DOTALL)
    if m:
        for line in m.group(1).strip().split("\n"):
            line = line.strip()
            if line.startswith("- ") and not line.startswith("- ("):
                items.append(line[2:].strip().lower())
    return items


def parse_works_today(current_state_content):
    """Extract 'What Works Today' items."""
    items = []
    m = re.search(r'##\s*What Works Today.*?\n(.*?)(?=\n##|\Z)', current_state_content, re.DOTALL)
    if m:
        for line in m.group(1).strip().split("\n"):
            line = line.strip()
            if line.startswith("- ") and not line.startswith("- ("):
                items.append(line[2:].strip().lower())
    return items


def check_content(source_file, item_id, text, is_not_list, works_today):
    """Check a single text field against all rules. Return violations."""
    violations = []

    # Auto-fail: misclassification
    text_lower = text.lower()
    for term in is_not_list:
        if term in text_lower:
            violations.append({
                "source_file": source_file,
                "item_id": item_id,
                "severity": "auto-fail",
                "rule": "misclassification",
                "description": f"Content uses term from 'What We Are NOT' list: '{term}'",
                "suggested_fix": f"Remove or reframe reference to '{term}'",
            })

    # Auto-fail: overclaiming (says "built" or "live" for unvalidated things)
    overclaim_patterns = [
        (r'\b(built|live|works|running|deployed)\b', "overclaim"),
    ]
    for pattern, rule in overclaim_patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            # Check if the claim references something in works_today
            context = text[max(0, m.start()-50):m.end()+50].lower()
            found_in_works = any(w in context for w in works_today)
            if not found_in_works and "{{UNVALIDATED}}" not in text:
                violations.append({
                    "source_file": source_file,
                    "item_id": item_id,
                    "severity": "auto-fail",
                    "rule": "overclaim",
                    "description": f"Claims '{m.group()}' without matching works_today or {{{{UNVALIDATED}}}} marker",
                    "suggested_fix": "Add {{UNVALIDATED}} marker or verify against current-state.md",
                })

    # Warn: voice violations - banned words
    for pattern in WORD_PATTERNS:
        for m in pattern.finditer(text):
            violations.append({
                "source_file": source_file,
                "item_id": item_id,
                "severity": "warn",
                "rule": f"voice_banned_word_{m.group().lower()}",
                "description": f"Banned word: '{m.group()}'",
                "suggested_fix": f"Replace '{m.group()}' with plain language",
            })

    # Warn: voice violations - banned phrases
    for pattern in PHRASE_PATTERNS:
        for m in pattern.finditer(text):
            violations.append({
                "source_file": source_file,
                "item_id": item_id,
                "severity": "warn",
                "rule": "voice_banned_phrase",
                "description": f"Banned phrase: '{m.group()}'",
                "suggested_fix": f"Remove or rephrase '{m.group()}'",
            })

    # Warn: emdashes
    emdash_count = text.count(EMDASH)
    if emdash_count > 0:
        violations.append({
            "source_file": source_file,
            "item_id": item_id,
            "severity": "warn",
            "rule": "voice_emdash",
            "description": f"{emdash_count} emdash(es) found",
            "suggested_fix": "Replace emdashes with commas, periods, or dashes",
        })

    # Warn: DM/email starts with person's name
    if item_id and ("dm" in item_id.lower() or "email" in item_id.lower()):
        first_word = text.strip().split()[0] if text.strip() else ""
        if first_word and first_word[0].isupper() and first_word.lower() not in ("i", "i'm", "i've", "i'd"):
            # Might start with a name - flag it
            if not first_word.lower().startswith(("hey", "hi", "hello", "the", "a", "we", "our", "my")):
                violations.append({
                    "source_file": source_file,
                    "item_id": item_id,
                    "severity": "warn",
                    "rule": "voice_dm_starts_with_name",
                    "description": f"DM/email starts with '{first_word}' - should start with 'I'",
                    "suggested_fix": "Rewrite to start with 'I' not the person's name",
                })

    # Warn: hedging density
    words = text.split()
    if len(words) >= 50:
        hedge_count = sum(len(p.findall(text)) for p in HEDGE_PATTERNS)
        density = hedge_count / (len(words) / 500)
        if density > 1.0:
            violations.append({
                "source_file": source_file,
                "item_id": item_id,
                "severity": "warn",
                "rule": "voice_hedging",
                "description": f"Hedging density {density:.1f}/500w (max 1.0)",
                "suggested_fix": "Remove hedging words: might, could, perhaps, etc.",
            })

    return violations


def check_recurring(date, violations):
    """Check last 5 days for recurring warn-level violations."""
    try:
        current = __import__("datetime").datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return []

    # Collect warn rules from this run
    today_warns = {}
    for v in violations:
        if v["severity"] == "warn":
            rule = v["rule"]
            today_warns[rule] = today_warns.get(rule, 0) + 1

    # Check previous days
    rule_history = {rule: 1 for rule in today_warns}  # Count today
    for i in range(1, 6):
        prev_date = (current - __import__("datetime").timedelta(days=i)).strftime("%Y-%m-%d")
        prev_path = os.path.join(BUS_BASE, prev_date, "compliance.json")
        if not os.path.isfile(prev_path):
            continue
        try:
            with open(prev_path) as f:
                prev_data = json.load(f)
            for v in prev_data.get("violations", []):
                if v.get("severity") == "warn":
                    rule = v.get("rule", "")
                    if rule in rule_history:
                        rule_history[rule] += 1
        except (json.JSONDecodeError, OSError):
            continue

    # Flag rules that appeared 3+ of last 5 days
    candidates = []
    for rule, count in rule_history.items():
        if count >= 3:
            candidates.append({
                "rule": rule,
                "occurrences": f"{count} of last 5 days",
                "recommendation": "Promote to auto-fail",
            })

    return candidates


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 compliance-check.py <date> [--json]", file=sys.stderr)
        sys.exit(2)

    date = sys.argv[1]
    json_output = "--json" in sys.argv
    bus_dir = os.path.join(BUS_BASE, date)

    if not os.path.isdir(bus_dir):
        print(f"Bus directory not found: {bus_dir}", file=sys.stderr)
        sys.exit(1)

    # Read canonical files
    current_state = read_file(os.path.join(QROOT, "my-project", "current-state.md"))
    is_not_list = parse_is_not_list(current_state)
    works_today = parse_works_today(current_state)

    # Read content bus files
    content_files = [
        ("signals.json", read_bus_file(bus_dir, "signals.json")),
        ("value-routing.json", read_bus_file(bus_dir, "value-routing.json")),
        ("hitlist.json", read_bus_file(bus_dir, "hitlist.json")),
    ]

    all_violations = []
    passed_items = []
    items_checked = 0

    for source_file, data in content_files:
        if data is None:
            continue

        text_fields = extract_text_fields(data)
        for field_path, text in text_fields:
            items_checked += 1
            violations = check_content(source_file, field_path, text, is_not_list, works_today)
            if violations:
                all_violations.extend(violations)
            else:
                passed_items.append({
                    "source_file": source_file,
                    "item_id": field_path,
                    "note": "clean",
                })

    # Check for auto-fail
    has_auto_fail = any(v["severity"] == "auto-fail" for v in all_violations)

    # Recurring violation check
    promotion_candidates = check_recurring(date, all_violations)

    result = {
        "date": date,
        "overall_pass": not has_auto_fail,
        "items_checked": items_checked,
        "violations": all_violations,
        "passed_items": passed_items,
        "promotion_candidates": promotion_candidates,
    }

    # Write output
    output_path = os.path.join(bus_dir, "compliance.json")
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        auto_fails = sum(1 for v in all_violations if v["severity"] == "auto-fail")
        warns = sum(1 for v in all_violations if v["severity"] == "warn")
        print(f"Compliance check ({date}):")
        print(f"  Items checked: {items_checked}")
        print(f"  Auto-fail: {auto_fails}, Warn: {warns}")
        print(f"  Overall: {'PASS' if not has_auto_fail else 'FAIL'}")
        if promotion_candidates:
            print(f"  Promotion candidates: {len(promotion_candidates)}")
        print(f"  Written to {output_path}")

    sys.exit(0 if not has_auto_fail else 1)


if __name__ == "__main__":
    main()
