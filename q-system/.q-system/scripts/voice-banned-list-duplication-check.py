#!/usr/bin/env python3
"""Fail when a skill file restates the banned-word list that draft_scanner.py owns.

Scar (2026-09-02 prompt audit, S-5 / S-13): the voice system had four sources of
truth for one list. `founder-voice/SKILL.md` and `linkedin-brand/SKILL.md` each
said the lists are enforced deterministically and must not be relied on from
memory, then reproduced ~40 of the words inline. `linkedin-brand/references/
voice-check.md` carried a third list that had ALREADY drifted: `facilitate`,
`harness`, `drive`, `unleash` and `I think` were in the doc and in no enforcer
(measured that day, zero hits each against draft_scanner.py). A reader following
the doc scrubs words the linter does not ban and trusts a doc the linter does not
back.

Two design choices, both deliberate:

1. The vocabulary is DERIVED by importing `DraftScanner`, never by copying it
   here. A checker that hardcodes the words is a fifth copy of the defect it
   exists to catch, and it goes stale the first time someone extends the linter.

2. It matches the SHAPE of a restatement -- a run of owned terms joined only by
   separators -- not a fixed set of forbidden strings. Naming two or three of the
   words in prose is legitimate and stays legal; transcribing the list is what
   breaks.

MAX_RUN is 3 because of a real legitimate case, not a round number:
`founder-voice/SKILL.md` names "Furthermore," "Moreover," "Additionally" to say
what the linter's `structural_opener` violation catches. That is a run of exactly
3 owned adverbs doing explanatory work. 4+ in a row is a transcription.

Exit 0 = no restatement. Exit 1 = at least one. Exit 2 = the check could not run
(the enforcer moved), which is loud on purpose: a checker that cannot find its
source of truth must not report green.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNER_SRC = REPO_ROOT / "plugins" / "kipi-core" / "kipi-mcp" / "src"

# Scope is part of the gate. These are the trees whose .md files are prose ABOUT
# the linter; widening this to all of plugins/ would pull in the linter's own
# tests and fixtures, where a long list of banned words is the point.
SCAN_ROOTS = [
    REPO_ROOT / "plugins" / "kipi-core" / "skills",
    REPO_ROOT / "plugins" / "kipi-design" / "skills",
    REPO_ROOT / "plugins" / "prd-os" / "skills",
]

MAX_RUN = 3

# Gap text allowed between two owned terms for them to count as one run: pure
# separators, optionally a coordinating word. Anything else (a real sentence)
# ends the run.
_GAP = re.compile(
    r"^[\s,;:/|\"'`*\-—()\[\]]*(?:and|or|plus)?[\s,;:/|\"'`*\-—()\[\]]*$",
    re.IGNORECASE,
)

# A BANNED_PHRASES entry is a regex source, not always a literal. Only literals
# can be looked for as text; a pattern like r"in today's \S+" is skipped rather
# than matched wrongly.
_REGEX_METACHARS = ("\\", ".+", ".*", "[", "(", "|", "?")

# Per-line bypass, and it must carry a reason: a marker with nothing after the
# colon is a mute button, not a decision. Line-scoped rather than file-scoped on
# purpose -- `voice-dna.md` legitimately enumerates cliches ONCE, as a corpus
# measurement ("0 of 27 across 11,563 words"), and a file-wide exemption there
# would stop the check seeing a real restatement added to the same file later.
# The reason must start with an alphanumeric. `\S+` was not enough: the comment
# terminator `-->` is non-space, so `<!-- banned-list-skip: -->` silently passed
# as a reasoned bypass. Caught by test_skip_marker_needs_a_reason, 2026-09-02.
_SKIP = re.compile(r"banned-list-skip:[ \t]*[A-Za-z0-9]")


def owned_terms():
    """The vocabulary, derived from the enforcer. Never a copy."""
    sys.path.insert(0, str(SCANNER_SRC))
    from kipi_mcp.draft_scanner import DraftScanner

    terms = set()
    for word in DraftScanner.TIER1_WORDS + DraftScanner.TIER1_VERBS + DraftScanner.TIER1_ADVERBS:
        terms.add(word.lower())
    for phrase in DraftScanner.BANNED_PHRASES:
        if any(m in phrase for m in _REGEX_METACHARS):
            continue
        terms.add(phrase.lower())
    return terms


def _term_pattern(terms):
    # Longest first so "cutting-edge" wins over a bare "edge"-like prefix and a
    # multi-word phrase is matched whole.
    ordered = sorted(terms, key=len, reverse=True)
    return re.compile(
        r"(?<![\w-])(?:" + "|".join(re.escape(t) for t in ordered) + r")(?![\w-])",
        re.IGNORECASE,
    )


def find_runs(text, pattern):
    """Maximal sequences of owned terms separated only by separator text."""
    matches = list(pattern.finditer(text))
    runs, current = [], []
    for m in matches:
        if current and _GAP.match(text[current[-1].end():m.start()]):
            current.append(m)
        else:
            if len(current) > MAX_RUN:
                runs.append(current)
            current = [m]
    if len(current) > MAX_RUN:
        runs.append(current)
    return runs


def scan_file(path, pattern):
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    findings = []
    for run in find_runs(text, pattern):
        line = text.count("\n", 0, run[0].start()) + 1
        # The marker may sit on the run's own line or the line above it (a bullet
        # is often too long to carry it inline).
        context = "\n".join(lines[max(0, line - 2):line])
        if _SKIP.search(context):
            continue
        findings.append({
            "line": line,
            "count": len(run),
            "sample": ", ".join(m.group(0) for m in run[:6]),
        })
    return findings


def main(argv=None):
    argv = argv or sys.argv[1:]
    roots = [Path(a).resolve() for a in argv] if argv else SCAN_ROOTS

    try:
        terms = owned_terms()
    except Exception as exc:  # noqa: BLE001 - see module docstring, exit 2 is loud
        print(f"FAIL(setup): cannot import DraftScanner from {SCANNER_SRC}: {exc}")
        return 2
    if not terms:
        print("FAIL(setup): DraftScanner exposed an empty vocabulary")
        return 2

    pattern = _term_pattern(terms)
    scanned = 0
    total = 0
    for root in roots:
        if not root.exists():
            continue
        for md in sorted(root.rglob("*.md")):
            scanned += 1
            for f in scan_file(md, pattern):
                total += 1
                rel = md.relative_to(REPO_ROOT) if REPO_ROOT in md.parents else md
                print(
                    f"FAIL {rel}:{f['line']}: {f['count']} banned terms in a row "
                    f"(max {MAX_RUN}) -- {f['sample']}..."
                )

    if total:
        print(
            f"\n{total} restatement(s) across {scanned} file(s). "
            f"The lists live in plugins/kipi-core/kipi-mcp/src/kipi_mcp/draft_scanner.py; "
            f"point at it instead of transcribing it."
        )
        return 1
    print(f"OK: {scanned} skill file(s), no banned-list restatement "
          f"({len(terms)} terms derived from draft_scanner.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
