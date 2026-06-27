#!/usr/bin/env python3
"""
Block prompt-only enforcement claims.

This hook catches the failure mode where an agent records a behavior as
"enforced" by a prompt, skill, instruction, model, or persona without naming
an executable blocker. Guidance can explain a rule. Code has to enforce it.

Usage:
  python3 prompt-only-enforcement-guard.py path/to/file.md
  python3 prompt-only-enforcement-guard.py              # PostToolUse JSON on stdin

Exit codes:
  0 = pass
  2 = block

Override:
  Add <!-- prompt-only-enforcement-skip --> to the file.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


SKIP_MARKER = "prompt-only-enforcement-skip"
GUARD_FILENAME = "prompt-only-enforcement-guard.py"

TARGET_EXTENSIONS = {
    ".md",
    ".txt",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
}

PROMPT_ONLY_SUBJECTS = (
    "prompt",
    "prompts",
    "skill",
    "skills",
    "instruction",
    "instructions",
    "system prompt",
    "agent instruction",
    "llm",
    "model",
    "persona",
)

ENFORCEMENT_WORDS = (
    "enforce",
    "enforces",
    "enforced",
    "enforcing",
    "block",
    "blocks",
    "blocked",
    "blocking",
    "guard",
    "guards",
    "guarded",
    "guarding",
    "prevent",
    "prevents",
    "prevented",
    "preventing",
    "ensure",
    "ensures",
    "ensured",
    "ensuring",
    "guarantee",
    "guarantees",
    "guaranteed",
    "validate",
    "validates",
    "validated",
    "validating",
    "reject",
    "rejects",
    "rejected",
    "rejecting",
    "catch",
    "catches",
    "caught",
    "stop",
    "stops",
    "stopped",
)

NEGATION_TERMS = (
    "invalid",
    "no prompt-only",
    "prompt-only enforcement is invalid",
    "prompt-only fixes are invalid",
)

DETERMINISTIC_TERMS = (
    "hook",
    "posttooluse",
    "pretooluse",
    "script",
    "test",
    "pytest",
    "lint",
    "linter",
    "validator",
    "validation",
    "pre-commit",
    "required_check",
    "required check",
    "bypass_check",
    "bypass check",
    "gates.jsonl",
    "deterministic gate",
    "executable",
    "code change",
    "static check",
)

CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def _word_group(words: tuple[str, ...]) -> str:
    return "|".join(re.escape(word) for word in sorted(words, key=len, reverse=True))


SUBJECT_RE = _word_group(PROMPT_ONLY_SUBJECTS)
ACTION_RE = _word_group(ENFORCEMENT_WORDS)

SUBJECT_ENFORCES_RE = re.compile(
    rf"\b(?:{SUBJECT_RE})\b[\s\S]{{0,120}}\b(?:{ACTION_RE})\b",
    re.IGNORECASE,
)
ENFORCED_BY_SUBJECT_RE = re.compile(
    rf"\b(?:{ACTION_RE})\b[\s\S]{{0,120}}\b(?:by|via|through|with|using|in)\b"
    rf"[\s\S]{{0,80}}\b(?:{SUBJECT_RE})\b",
    re.IGNORECASE,
)
NEGATED_SUBJECT_RE = re.compile(
    rf"\b(?:not|never|cannot|can't|shouldn't|won't|doesn't|don't|isn't|aren't|"
    rf"must not|do not|without)\b[\s\S]{{0,100}}\b(?:{SUBJECT_RE})\b",
    re.IGNORECASE,
)
SUBJECT_NEGATED_RE = re.compile(
    rf"\b(?:{SUBJECT_RE})\b[\s\S]{{0,100}}\b(?:cannot|can't|shouldn't|won't|"
    rf"doesn't|don't|isn't|aren't|must not|do not|not enough|insufficient|invalid)\b",
    re.IGNORECASE,
)
DETERMINISTIC_RE = re.compile(
    r"\b(?:hook|posttooluse|pretooluse|script|test|pytest|lint|linter|"
    r"validator|validation|pre-commit|required_check|required check|"
    r"bypass_check|bypass check|gates\.jsonl|deterministic gate|executable|"
    r"code change|static check)\b",
    re.IGNORECASE,
)


def _hook_paths() -> list[Path]:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return []

    tool_input = payload.get("tool_input") or {}
    candidates = [
        tool_input.get("file_path"),
        tool_input.get("path"),
        tool_input.get("notebook_path"),
    ]
    return [Path(path) for path in candidates if path]


def _target_paths(argv: list[str]) -> list[Path]:
    if argv:
        return [Path(arg) for arg in argv]
    return _hook_paths()


def _is_target(path: Path) -> bool:
    return path.suffix.lower() in TARGET_EXTENSIONS


def _strip_code_fences(text: str) -> str:
    return CODE_FENCE_RE.sub("", text)


def _window(lines: list[str], index: int, radius: int = 2) -> str:
    start = max(0, index - radius)
    end = min(len(lines), index + radius + 1)
    return "\n".join(lines[start:end]).lower()


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _is_negated_prompt_only_warning(text: str) -> bool:
    return (
        _has_any(text, NEGATION_TERMS)
        or bool(NEGATED_SUBJECT_RE.search(text))
        or bool(SUBJECT_NEGATED_RE.search(text))
    )


def _is_violation(window_text: str) -> bool:
    if GUARD_FILENAME in window_text:
        return False
    if _is_negated_prompt_only_warning(window_text):
        return False
    if DETERMINISTIC_RE.search(window_text):
        return False
    return bool(
        SUBJECT_ENFORCES_RE.search(window_text)
        or ENFORCED_BY_SUBJECT_RE.search(window_text)
    )


def scan(path: Path) -> list[str]:
    if not _is_target(path) or not path.exists() or not path.is_file():
        return []

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    if SKIP_MARKER in text:
        return []

    text = _strip_code_fences(text)
    lines = text.splitlines()
    findings: list[str] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        window_text = _window(lines, index)
        if _is_violation(window_text):
            findings.append(
                f"{path}:{index + 1}: prompt-only enforcement claim needs an executable blocker"
            )
    return findings


def main(argv: list[str]) -> int:
    findings: list[str] = []
    for path in _target_paths(argv):
        findings.extend(scan(path))

    if findings:
        message = (
            "BLOCK: prompt-only enforcement is not allowed.\n"
            "Name or add the deterministic blocker: hook, script, test, lint, "
            "validator, required check, or executable code.\n"
            + "\n".join(findings)
        )
        print(json.dumps({"message": message}))
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
