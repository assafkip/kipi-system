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


def _read_payload() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}


def _payload_path(tool_input: dict) -> Path | None:
    for key in ("file_path", "path", "notebook_path"):
        val = tool_input.get(key)
        if val:
            return Path(val)
    return None


def _diff_added_lines(old_string: str, new_string: str) -> set[str]:
    """The set of non-blank lines present in new_string but NOT in old_string — the lines an
    Edit actually ADDS. Content-based (stripped) so it is robust to indentation and to the
    code-fence stripping that _scan_text applies before it splits lines."""
    old = {ln.strip() for ln in (old_string or "").splitlines()}
    return {ln.strip() for ln in (new_string or "").splitlines()
            if ln.strip() and ln.strip() not in old}


def _payload_scan_inputs(tool_input: dict) -> tuple[str, set[str] | None]:
    """(text_to_scan, only_lines) for a PostToolUse payload. only_lines=None means scan the
    whole text (Write = a full new file); a set means report a finding ONLY on those added
    lines (Edit/MultiEdit), so pre-existing enforcement prose the change never touched is not
    re-flagged. This is the diff-awareness fix: the guard blocks NEWLY-added prompt-only
    enforcement claims, not the whole file (memory prompt-only-guard-false-positives)."""
    if "content" in tool_input:                      # Write — full new-file content
        return str(tool_input.get("content") or ""), None
    edits = tool_input.get("edits")
    if isinstance(edits, list):                      # MultiEdit — union of every edit's adds
        texts, added = [], set()
        for e in edits:
            if not isinstance(e, dict):
                continue
            new = str(e.get("new_string") or "")
            texts.append(new)
            added |= _diff_added_lines(str(e.get("old_string") or ""), new)
        return "\n".join(texts), added
    # Edit — the new side, gated to the lines it introduced over the old side.
    new = str(tool_input.get("new_string") or "")
    return new, _diff_added_lines(str(tool_input.get("old_string") or ""), new)


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


def _scan_text(path: Path, text: str, only_lines: set[str] | None) -> list[str]:
    """Report a finding per violating line. only_lines=None scans every line (whole file /
    Write new-file); a set restricts findings to those (added) lines — the diff-aware path,
    so pre-existing prose the change never touched is never re-flagged."""
    text = _strip_code_fences(text)
    lines = text.splitlines()
    findings: list[str] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if only_lines is not None and line.strip() not in only_lines:
            continue
        window_text = _window(lines, index)
        if _is_violation(window_text):
            findings.append(
                f"{path}:{index + 1}: prompt-only enforcement claim needs an executable blocker"
            )
    return findings


def scan(path: Path) -> list[str]:
    """Disk / CLI mode (argv): whole-file scan. The PostToolUse path uses the diff instead."""
    if not _is_target(path) or not path.exists() or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    if SKIP_MARKER in text:
        return []
    return _scan_text(path, text, None)


def _skip_marker_present(path: Path | None, added_text: str) -> bool:
    """A per-file skip marker anywhere in the change OR anywhere in the file on disk."""
    if SKIP_MARKER in added_text:
        return True
    if path is not None and path.exists() and path.is_file():
        try:
            return SKIP_MARKER in path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return False
    return False


def scan_payload(payload: dict) -> list[str]:
    """PostToolUse (Edit/Write/MultiEdit) mode: scan only the text the change ADDED, so the
    guard blocks newly-introduced prompt-only enforcement claims without re-flagging the rest
    of the file (memory prompt-only-guard-false-positives)."""
    tool_input = payload.get("tool_input") or {}
    path = _payload_path(tool_input)
    if path is None or not _is_target(path):
        return []
    text, only_lines = _payload_scan_inputs(tool_input)
    if _skip_marker_present(path, text):
        return []
    return _scan_text(path, text, only_lines)


def main(argv: list[str]) -> int:
    findings: list[str] = []
    if argv:                                   # CLI mode: whole-file scan of each path
        for path in (Path(arg) for arg in argv):
            findings.extend(scan(path))
    else:                                      # PostToolUse: diff-aware scan of the change
        findings.extend(scan_payload(_read_payload()))

    if findings:
        message = (
            "BLOCK: prompt-only enforcement is not allowed.\n"
            "Name or add the deterministic blocker: hook, script, test, lint, "
            "validator, required check, or executable code.\n"
            + "\n".join(findings)
        )
        # stderr, plain text: on exit 2 Claude Code feeds ONLY stderr back to
        # the model. The old json-to-stdout form surfaced every block as
        # "No stderr output" — a reasonless wall (sp-cd530cc7, 2026-07-02).
        print(message, file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
