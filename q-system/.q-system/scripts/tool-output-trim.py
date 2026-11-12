#!/usr/bin/env python3
"""tool-output-trim.py -- PostToolUse hook (matcher Bash) that shortens large
command output before the model reads it, and saves the full text to a file.

ASK-4649. Pairs with no skill; it is a cost control. Measured need: one build
made 11,725 Bash calls and 37 MB of tool results.

Ported from Sagargupta16/claude-cost-optimizer, hooks/output_trim.py
(MIT License, Copyright (c) Sagar Gupta). The line selection, the folding of
repeated lines and the "act only if 20% shorter" gate come from there. This
file was written from a read of that source, not copied or run. Changes:
  - no runner allowlist: every Bash output is a candidate, since the target
    was a 11,725-call build and not only test runners;
  - failure blocks are kept WHOLE and uncapped (the original caps signal hits
    at 40, which would drop failure 41 of a 60-failure run);
  - git diff / git show output is never touched, by command AND by content;
  - the spill path is ~/.local/state/kipi/tool-output/<session>-<n>.txt.

How it works (verified live on Claude Code 2.1.322, ASK-4649 probe): a
PostToolUse hook may print
  {"hookSpecificOutput":{"hookEventName":"PostToolUse","updatedToolOutput":{...}}}
and Claude reads that instead of the tool result. For Bash the value must be
the Bash output OBJECT {stdout, stderr, interrupted, isImage}. A bare string is
silently ignored and the original output stands (that was the probe's first
failed attempt, so do not "simplify" the value to a string).

Fail-open contract: any exception, any malformed input, any refusal prints
NOTHING and exits 0, so the original output stands. This hook never exits 2.

Off switch: KIPI_OUTPUT_TRIM=0.
Test seam: KIPI_TOOL_OUTPUT_DIR overrides the spill directory so tests never
touch the live state dir.

Scope note: Claude Code fires PostToolUse for Bash runs that exited 0. A run
that failed goes to PostToolUseFailure, which cannot rewrite output, so a
failing pytest run reaches the model untrimmed. The failure-keeping rules
below still matter: a passing run can print failure text (a tolerated xfail
traceback, a retry log), and a --exitfirst-less wrapper can exit 0.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

MIN_CHARS = 2000
MIN_SAVING = 0.20
HEAD_LINES = 30
TAIL_LINES = 40
CONTEXT_LINES = 2
FOLD_IDENTICAL = 3

ANSI_RE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)?|[@-Z\\-_])"
)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SIGNAL_RE = re.compile(
    r"\b(?:err|error|errors|fail|failed|failure|failures|fatal|panic|exception|"
    r"traceback|warn|warning|warnings|deprecated|assert\w*)\b|^E\s{3}",
    re.IGNORECASE,
)
SUMMARY_RE = re.compile(
    r"\b\d+ (?:passed|passing|failed|skipped|deselected|error|errors)\b"
    r"|^Ran \d+ tests? in\b|^OK\b|^(?:Tests|Test Suites):"
)
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", re.MULTILINE)
GIT_DIFF_CMD_RE = re.compile(r"\bgit\b[^|;&\n]*?\s(?:diff|show)\b")

PYTEST_SECTION_RE = re.compile(r"^=+ (FAILURES|ERRORS) =+$")
PYTEST_ANY_HEADER_RE = re.compile(r"^=+ .+ =+$")
TRACEBACK_RE = re.compile(r"^\s*Traceback \(most recent call last\):")
JEST_FAIL_RE = re.compile(r"^\s*● (?!Console)\S")
JEST_END_RE = re.compile(r"^(?:Test Suites|Tests):")


def clean_lines(text: str) -> list[str]:
    """Strip ANSI and control chars; keep the last redraw of a carriage-return line."""
    text = CONTROL_RE.sub("", ANSI_RE.sub("", text.replace("\r\n", "\n")))
    # Why: a bare-CR file (Excel-for-Mac CSV) has no LF at all, so the redraw rule
    # below kept 1 of 801 rows and the footer said nothing was dropped (PR 764
    # round 2, major). Output with CRs and no LF is records, not a redraw.
    if "\r" in text and "\n" not in text.rstrip("\r"):
        text = text.replace("\r", "\n")
    lines = []
    for raw in text.split("\n"):
        parts = [p for p in raw.split("\r") if p.strip()]
        lines.append((parts[-1] if parts else "").rstrip())
    if lines and not lines[-1]:
        lines.pop()
    return lines


def failure_indexes(lines: list[str]) -> set[int]:
    """Line indexes inside a failure block. Every one of them is kept, uncapped.

    Why whole blocks: a trimmer that keeps "the error line" of a failing test
    and drops the locals, the diff and the assertion above it makes the model
    re-run the suite to see what the trim removed, which costs more than it
    saved.
    """
    keep: set[int] = set()
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        if PYTEST_SECTION_RE.match(line):
            j = i + 1
            while j < n and not PYTEST_ANY_HEADER_RE.match(lines[j]):
                j += 1
            keep.update(range(i, j))
            i = j
            continue
        if TRACEBACK_RE.match(line):
            j = i + 1
            while j < n and (not lines[j] or lines[j][:1] in " \t"):
                j += 1
            keep.update(range(i, min(n, j + 1)))
            i = j + 1
            continue
        if JEST_FAIL_RE.match(line):
            j = i + 1
            while j < n and not JEST_FAIL_RE.match(lines[j]) and not JEST_END_RE.match(lines[j]):
                j += 1
            keep.update(range(i, j))
            i = j
            continue
        i += 1
    return keep


# Only IDENTICAL lines fold. The reference also folded lines that differ in
# digits; that hid "file1.py" vs "file2.py" and "test 7" vs "test 8" and made the
# head of a log disappear, so the digit fold is gone (ASK-4649 test round 1).
def _fold_run(run: list[str]) -> list[str]:
    count = len(run)
    if not run[0].strip():
        return run[:1]
    if all(line == run[0] for line in run):
        if count >= FOLD_IDENTICAL:
            return [run[0], f"[trim: previous line repeated {count - 1} more times]"]
        return run
    return run


def fold_runs(lines: list[str], protected: set[int]) -> tuple[list[str], set[int]]:
    """Fold repeated runs, never inside a protected failure block.

    Returns the new lines and the protected set re-indexed onto them.
    """
    out: list[str] = []
    new_protected: set[int] = set()
    i = 0
    n = len(lines)
    while i < n:
        if i in protected:
            new_protected.add(len(out))
            out.append(lines[i])
            i += 1
            continue
        j = i + 1
        while j < n and j not in protected and lines[j] == lines[i]:
            j += 1
        out.extend(_fold_run(lines[i:j]))
        i = j
    return out, new_protected


def select_lines(lines: list[str], protected: set[int]) -> list[str]:
    n = len(lines)
    if n <= HEAD_LINES + TAIL_LINES:
        return lines
    keep = set(range(HEAD_LINES)) | set(range(n - TAIL_LINES, n)) | protected
    for i in range(HEAD_LINES, n - TAIL_LINES):
        if SIGNAL_RE.search(lines[i]):
            keep.update(range(max(0, i - CONTEXT_LINES), min(n, i + CONTEXT_LINES + 1)))
        if SUMMARY_RE.search(lines[i]):
            keep.add(i)
    out: list[str] = []
    i = 0
    while i < n:
        if i in keep:
            out.append(lines[i])
            i += 1
            continue
        j = i
        while j < n and j not in keep:
            j += 1
        out.append(f"[trim: {j - i} lines omitted]")
        i = j
    return out


def trim_stream(text: str) -> tuple[str, int, int]:
    """(trimmed text, lines before, lines after)."""
    lines = clean_lines(text)
    protected = failure_indexes(lines)
    folded, protected = fold_runs(lines, protected)
    kept = select_lines(folded, protected)
    return "\n".join(kept), len(lines), len(kept)


def state_dir() -> Path:
    override = os.environ.get("KIPI_TOOL_OUTPUT_DIR")
    if override:
        return Path(override)
    return Path.home() / ".local" / "state" / "kipi" / "tool-output"


def _safe(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or ""))[:80].strip(".") or "nosession"


RETENTION_DAYS = 7


def prune_old(folder: Path) -> None:
    """Best-effort: unlink spill files older than RETENTION_DAYS (Codex P2, PR 764).

    Only <name>-<n>.txt files this hook wrote; never raises, since a failed prune
    must not cost the model its trimmed output.
    """
    try:
        cutoff = time.time() - RETENTION_DAYS * 86400
        for f in folder.glob("*-*.txt"):
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
    except OSError:
        pass


def write_full(session: str, body: str) -> Path | None:
    """Save the full output as <session>-<n>.txt. O_EXCL makes the counter race-free."""
    folder = state_dir()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    prune_old(folder)
    for n in range(1, 100000):
        path = folder / f"{session}-{n}.txt"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8", errors="replace", newline="") as fh:
            fh.write(body)
        return path
    return None


def is_diff_output(command: str, out: str, err: str) -> bool:
    """git diff/show output is never touched: a dropped hunk is a silent wrong edit.

    Checked on the command AND on the content, because `git -C x diff`, an alias
    or a wrapper script defeat any command parse, and a hunk header does not.
    """
    if GIT_DIFF_CMD_RE.search(command or ""):
        return True
    # ANSI stripped first: `git diff --color=always` starts every hunk header with an
    # escape code, which defeated the anchored regex (Codex P1, PR 764).
    return bool(HUNK_RE.search(ANSI_RE.sub("", out)) or HUNK_RE.search(ANSI_RE.sub("", err)))


def process(payload: dict) -> dict | None:
    if os.environ.get("KIPI_OUTPUT_TRIM") == "0":
        return None
    if payload.get("tool_name") != "Bash":
        return None
    response = payload.get("tool_response")
    if not isinstance(response, dict) or response.get("interrupted") or response.get("isImage"):
        return None
    if response.get("backgroundTaskId"):
        return None
    out = response.get("stdout")
    err = response.get("stderr") or ""
    if not isinstance(out, str) or not isinstance(err, str):
        return None
    before = len(out) + len(err)
    if before < MIN_CHARS:
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if is_diff_output(command if isinstance(command, str) else "", out, err):
        return None

    new_out, out_lines, out_kept = trim_stream(out)
    new_err, err_lines, err_kept = trim_stream(err)
    footer_stub = "[trim: showing {k} of {t} lines; full output ({c} chars) is in {p}]"
    # Size the gate on a footer with a realistic path, then write the file only
    # once the trim is known to pay, so a no-op never litters the state dir.
    probe = footer_stub.format(
        k=out_kept + err_kept, t=out_lines + err_lines, c=before, p=str(state_dir() / ("x" * 40 + "-99999.txt"))
    )
    after = len(new_out) + len(new_err) + len(probe) + 1
    if after > before * (1 - MIN_SAVING):
        return None
    session = _safe(payload.get("session_id"))
    path = write_full(session, f"{out}\n--- stderr ---\n{err}" if err else out)
    if path is None:
        return None
    footer = footer_stub.format(
        k=out_kept + err_kept, t=out_lines + err_lines, c=before, p=path.as_posix()
    )
    if new_err:
        new_err = f"{new_err}\n{footer}"
    else:
        new_out = f"{new_out}\n{footer}" if new_out else footer
    updated = dict(response)
    updated["stdout"] = new_out
    updated["stderr"] = new_err
    return updated


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
        updated = process(payload) if isinstance(payload, dict) else None
        if updated is not None:
            sys.stdout.write(
                json.dumps(
                    {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": updated}}
                )
            )
    except Exception:  # fail open: a hook bug must never change or block a tool result
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
