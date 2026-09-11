#!/usr/bin/env python3
"""
Tests for pitfall detection.

Covers: correction pattern matching, transcript parsing,
pitfall memory creation, deduplication.

Run: python3 tests/test_pitfalls.py
"""

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Import the module
import importlib.util
hook_path = os.path.join(os.path.dirname(__file__), "..", "hooks", "detect-pitfalls.py")
spec = importlib.util.spec_from_file_location("detect_pitfalls", hook_path)
pitfalls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pitfalls)

PASS = 0
FAIL = 0


def check(label, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}")


# --- Test: Correction pattern matching ---

def test_correction_patterns():
    print("\n--- Correction pattern matching ---")

    should_match = [
        "that's changed since last week",
        "that is outdated",
        "that has changed",
        "no, that's different now",
        "nope, it's not right",
        "that was last week",
        "actually, the deadline moved",
        "not anymore",
        "that's done",
        "that is over",
        "that's finished",
        "we already moved past that",
        "we no longer do that",
        "forget that",
        "ignore the memory about Josh",
        "update: the meeting was cancelled",
        "correction, he's different now",
        "we stopped doing that",
        "we dropped that approach",
    ]

    should_not_match = [
        "sounds good",
        "thanks for the update",
        "let's move forward",
        "can you check the memory?",
        "what does the memory say?",
        "I like that approach",
    ]

    for text in should_match:
        match = pitfalls.CORRECTION_RE.search(text)
        check(f"matches: \"{text[:50]}\"", match is not None)

    for text in should_not_match:
        match = pitfalls.CORRECTION_RE.search(text)
        check(f"no match: \"{text[:50]}\"", match is None)


# --- Test: Transcript parsing ---

def test_transcript_parsing():
    print("\n--- Transcript parsing ---")

    with tempfile.TemporaryDirectory() as tmp:
        transcript_path = Path(tmp) / "session.jsonl"

        # Simulate: Claude reads a memory file, then user corrects it
        entries = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Read",
                 "input": {"file_path": "/home/user/.claude/projects/-home-user-myproject/memory/project_demo.md"}}
            ]},
            {"role": "tool", "content": "---\nname: demo status\ndecay: fast\n---\nDemo is active."},
            {"role": "assistant", "content": "Based on the memory, the demo is still active."},
            {"role": "user", "content": "that's outdated, the demo ended last week"},
        ]

        transcript_path.write_text("\n".join(json.dumps(e) for e in entries))

        results = pitfalls.parse_transcript(transcript_path)
        check("finds pitfall", len(results) >= 1)
        if results:
            check("correct memory file", "project_demo.md" in results[0][0])
            check("captures correction text", "outdated" in results[0][1])


def test_no_false_positives():
    print("\n--- No false positives ---")

    with tempfile.TemporaryDirectory() as tmp:
        transcript_path = Path(tmp) / "session.jsonl"

        # User says "sounds good" after memory read - should NOT trigger
        entries = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Read",
                 "input": {"file_path": "/home/user/.claude/projects/-home-user-myproject/memory/project_demo.md"}}
            ]},
            {"role": "tool", "content": "---\nname: demo status\n---\nDemo is active."},
            {"role": "user", "content": "sounds good, let's continue"},
        ]

        transcript_path.write_text("\n".join(json.dumps(e) for e in entries))
        results = pitfalls.parse_transcript(transcript_path)
        check("no false positive on 'sounds good'", len(results) == 0)


def test_no_memory_read():
    print("\n--- No memory read context ---")

    with tempfile.TemporaryDirectory() as tmp:
        transcript_path = Path(tmp) / "session.jsonl"

        # User says "that's changed" but no memory was read - should NOT trigger
        entries = [
            {"role": "assistant", "content": "Let me check the code."},
            {"role": "user", "content": "that's changed since last week"},
        ]

        transcript_path.write_text("\n".join(json.dumps(e) for e in entries))
        results = pitfalls.parse_transcript(transcript_path)
        check("no pitfall without memory read", len(results) == 0)


# --- Test: Pitfall memory creation ---

def test_create_pitfall():
    print("\n--- Pitfall memory creation ---")

    with tempfile.TemporaryDirectory() as tmp:
        memory_dir = Path(tmp)
        today = datetime.now().strftime("%Y-%m-%d")

        result = pitfalls.create_pitfall_memory(
            memory_dir,
            "project_demo.md",
            "that's outdated, the demo ended last week"
        )

        check("returns filename", result is not None)
        check("filename has pitfall prefix", result.startswith("pitfall_"))

        pitfall_path = memory_dir / result
        check("file created", pitfall_path.exists())

        content = pitfall_path.read_text()
        check("has fast decay", "decay: fast" in content)
        check("has pitfall_detection origin", "origin: pitfall_detection" in content)
        check("references source memory", "project_demo.md" in content)
        check("includes correction text", "outdated" in content)


def test_no_duplicate_pitfall():
    print("\n--- No duplicate pitfalls ---")

    with tempfile.TemporaryDirectory() as tmp:
        memory_dir = Path(tmp)

        first = pitfalls.create_pitfall_memory(memory_dir, "project_demo.md", "changed")
        second = pitfalls.create_pitfall_memory(memory_dir, "project_demo.md", "changed again")

        check("first creation succeeds", first is not None)
        check("duplicate returns None", second is None)


# --- Run all ---

if __name__ == "__main__":
    test_correction_patterns()
    test_transcript_parsing()
    test_no_false_positives()
    test_no_memory_read()
    test_create_pitfall()
    test_no_duplicate_pitfall()

    print(f"\n{'=' * 50}")
    print(f"  PASS: {PASS}")
    print(f"  FAIL: {FAIL}")
    print(f"{'=' * 50}")

    if FAIL > 0:
        print(f"\n{FAIL} test(s) failed.")
        sys.exit(1)
    else:
        print("\nAll tests passed.")
        sys.exit(0)
