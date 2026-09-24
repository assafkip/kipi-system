#!/usr/bin/env python3
"""capability-claim-lint: an alerting claim in a rule or README names its emitter.

Pairs with `.claude/rules/founder-notifications.md` (the named-emitter clause)
and `.claude/rules/no-orphan-findings.md` (the uncaptured-commitment clause).

WHY (ASK-562): four times in one day a capability was reported by reading the
design instead of observing the behaviour. "I'll tell you either way" with
nothing computing it; "runs continuously every 4 hours" for a job that had
never run once. The cost is worse than a bug: the reader stops watching for the
thing because a sentence said something else is watching. The one question
that caught every case was "what runs that?". This lint asks it of files on
disk: a line that says something will alert, notify, page or tell you must have
an executable path (a `.py`, `.sh`, `.plist`, ...) on that line or within
WINDOW lines of it.

HONEST BOUNDARY:
  1. It sees FILES, never chat. A promise said to the founder in conversation
     is out of reach of any hook; `no-orphan-findings.md` carries that half.
  2. It checks that an emitter is NAMED near the claim, never that the named
     script exists, is wired, or actually fires. A wrong path passes.
  3. It matches a fixed phrase set. A new way of saying "someone is watching"
     walks past it until the set is widened.

Scope: `.claude/rules/*.md` and any `README*.md`. Everything else exits 0 on
the first check, because this ships fleet-wide via settings-template.json and a
false positive would block edits in every instance.

Bypass: put `capability-claim-lint-skip` in the file.
Contract: hook mode reads PostToolUse JSON on stdin; exit 0 pass, exit 2 block.
CLI: `capability-claim-lint.py FILE...` lints the named files (exit 2 on a hit);
`capability-claim-lint.py --scan ROOT...` lints every in-scope file under each
root and prints every hit (the population replay the gate was bounded by).
stdlib only. Self-test: `python3 test_capability_claim_lint.py`.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

SKIP_MARKER = "capability-claim-lint-skip"

# How far from the claim the emitter may sit: a sentence that wraps across a
# markdown paragraph. Measured 2026-09-23 on both populations (ASK-562 PR body):
# windows 1, 2 and 3 flag the same lines, so the tighter end is taken. A wide
# window lets an unrelated path three bullets away vouch for a claim.
WINDOW = 2

# The alerting phrases from ASK-562's own occurrences: a promise that someone or
# something will speak up. Deliberately NOT bare "alert"/"notify" as nouns:
# "alert fatigue" or "a notification" claims nothing about what runs. And NOT a
# present-tense "tells you": the replay flagged the skeleton README's "then it
# tells you what it found", which describes an answer in the session, not a
# watcher. The future form ("I'll tell you") is the promise and stays.
CLAIM_RE = re.compile(
    r"\b(?:will|would|'ll)\s+(?:alert|notify|page|ping|warn|flag)\b"
    r"|\b(?:will|would|'ll)\s+(?:tell|let)\s+you\b"
    r"|\b(?:alerts|notifies|pages|pings|warns|taps)\s+"
    r"(?:you|the\s+founder|the\s+operator|sana|him)\b"
    r"|\bnotifies\b"
    r"|\b(?:is|are|gets?|being|stays)\s+watched\b"
    r"|\bkeeps?\s+(?:an\s+)?eye\s+on\b",
    re.IGNORECASE,
)

# A negated claim is honest, not a promise: "nothing will alert you" is exactly
# the sentence this lint wants people to write.
NEGATION_RE = re.compile(
    r"\b(?:no|nothing|nobody|never|not|cannot|can't|won't|doesn't|does\s+not"
    r"|without|neither|nor)\b[^.;:]*$",
    re.IGNORECASE,
)

# An executable named: a script or unit file, or a module run with `-m`.
EMITTER_RE = re.compile(
    r"[\w./~$-]+\.(?:py|sh|bash|zsh|mjs|cjs|js|ts|plist)\b"
    r"|\bpython3?\s+-m\s+[\w.]+",
)

FENCE_RE = re.compile(r"^\s*(```|~~~)")


def in_scope(path: str) -> bool:
    p = path.replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    if not name.lower().endswith(".md"):
        return False
    if name.lower().startswith("readme"):
        return True
    parent = p.rsplit("/", 1)[0] if "/" in p else ""
    return parent.endswith("/.claude/rules") or parent == ".claude/rules"


def hits(body: str) -> list[tuple[int, str]]:
    """(1-based line, text) of every claim with no emitter within WINDOW."""
    if SKIP_MARKER in body:
        return []
    lines = body.splitlines()
    out = []
    fenced = False
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = CLAIM_RE.search(line)
        if not m:
            continue
        if NEGATION_RE.search(line[: m.start()]):
            continue
        lo, hi = max(0, i - WINDOW), min(len(lines), i + WINDOW + 1)
        if any(EMITTER_RE.search(lines[j]) for j in range(lo, hi)):
            continue
        out.append((i + 1, line.strip()))
    return out


def lint_file(path: Path) -> list[tuple[int, str]]:
    try:
        return hits(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return []


def scan(root: Path) -> list[Path]:
    """Every in-scope file under root, skipping VCS and dependency trees."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "node_modules", ".venv", "venv",
                                    "__pycache__")]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            if in_scope(rel):
                found.append(Path(full))
    return sorted(found)


def message(path: str, bad: list[tuple[int, str]]) -> str:
    listed = "\n".join(f"    {path}:{n}: {t[:160]}" for n, t in bad)
    return (
        "CAPABILITY CLAIM LINT (blocked): a line says something will alert, "
        "notify or tell you, and no executable is named within "
        f"{WINDOW} lines of it:\n{listed}\n\n"
        "  The question is \"what runs that?\". Name the script and the channel, "
        "e.g. `q-system/.q-system/scripts/slack-notify.sh` (Sana's Linear "
        "triage). If nothing runs it, say that instead (\"nothing alerts on "
        "this\"), or capture the missing detector with `spillover add`.\n"
        "  See .claude/rules/founder-notifications.md (named-emitter clause).\n"
        f"  Deliberate exception: add `{SKIP_MARKER}` to the file.\n")


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--scan":
        total = 0
        for root in argv[1:]:
            files = scan(Path(root))
            n = 0
            for f in files:
                for line, text in lint_file(f):
                    n += 1
                    print(f"{f}:{line}: {text[:200]}")
            print(f"# {root}: {len(files)} in-scope files, {n} hits",
                  file=sys.stderr)
            total += n
        return 2 if total else 0
    if argv:
        rc = 0
        for a in argv:
            bad = lint_file(Path(a))
            if bad:
                sys.stderr.write(message(a, bad))
                rc = 2
        return rc
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    ti = payload.get("tool_input") or {}
    fp = (ti.get("file_path") or ti.get("path") or "")
    if not fp or not in_scope(fp):
        return 0
    bad = lint_file(Path(fp))
    if not bad:
        return 0
    sys.stderr.write(message(fp, bad))
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
