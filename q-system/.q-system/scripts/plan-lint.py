#!/usr/bin/env python3
"""plan-lint: the deterministic slice of `.claude/rules/quick-plan.md`.

WHY (ASK-136, CAP-22 sweep): quick-plan.md carried the word ENFORCED and named
no executable, so it was prompt-only. Per `skill-hook-pairing.md`'s decision
rule the rule splits in two:

  - DETERMINISTIC (this script): a plan file lives at
    `q-system/output/plans/<slug>-<YYYY-MM-DD>.md` and its body carries the five
    sections the rule names -- What/why, Approach, Files to touch, Acceptance
    criteria, Patterns to follow.
  - JUDGMENT (stays in the rule, and is NOT enforced): whether the quick-plan
    reflex fires at all. A PostToolUse hook sees a file that was written; it can
    never see the plan that was skipped.

Scope: PostToolUse(Write|Edit|MultiEdit) on `q-system/output/plans/*.md`.
Everything else exits 0 on the first check. The blast radius of this hook is
fleet-wide (it ships via `settings-template.json`), so the scope test is the
first thing it does and the widest thing it refuses to be.

GRANDFATHERING: 39 of the 57 plans on disk when this shipped were missing at
least one section -- they predate the rule's current wording. A gate that is red
on its own existing population gets switched off, and a gate that is off
protects nothing (`automated-filer-marking.md` made the same call for the same
reason). So a plan whose filename carries a date before CUTOFF is exempt.

HONEST BOUNDARY, three of them:
  1. This checks a section EXISTS, never that it is filled in or true.
     `## Acceptance criteria` followed by nothing passes.
  2. The grandfather cutoff reads the DATE IN THE FILENAME. Writing a new plan
     under a back-dated filename walks straight past this gate. That is a
     deliberate trade for a self-maintaining exemption over a hand-kept list.
  3. It cannot see a plan that was never written, which is the half of
     quick-plan.md that actually matters most. The rule says so in its own text
     rather than letting the label imply otherwise.

Bypass: put `plan-lint-skip` in the file.
Contract: reads hook JSON on stdin. exit 0 = pass, exit 2 = block. stdlib only.
Self-test: `python3 test_plan_lint.py`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCOPE = "q-system/output/plans/"
SKIP_MARKER = "plan-lint-skip"

# The day plan-lint shipped. Plans dated before this predate the gate.
CUTOFF = "2026-08-21"

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
DATED_NAME_RE = re.compile(r"^.+-\d{4}-\d{2}-\d{2}\.md$")

# A section counts when it appears as a LABEL -- a markdown heading, or a bold
# run at the start of a line (including inside a bullet). Matching bare prose
# would let the word "approach" anywhere in a paragraph satisfy the check, which
# is the decoration failure mode: a check that cannot go red for the reason you
# care about (lesson a-check-must-be-able-to-fail-for-the-reason-you-care-abou).
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*$")
BOLD_LABEL_RE = re.compile(r"^\s{0,6}(?:[-*+]\s*)?\*\*(.+?)\*\*")

# (display name, predicate over the lowercased label text)
SECTIONS: list[tuple[str, "re.Pattern[str]"]] = [
    ("What/why", re.compile(r"\bwhat\b")),
    ("Approach", re.compile(r"\bapproach")),
    ("Files to touch", re.compile(r"\bfiles?\b")),
    ("Acceptance criteria", re.compile(r"\bacceptance\b")),
    ("Patterns to follow", re.compile(r"\bpatterns?\b")),
]


def labels(body: str) -> list[str]:
    """Every heading / bold label in the document, lowercased."""
    out = []
    for line in body.splitlines():
        m = HEADING_RE.match(line) or BOLD_LABEL_RE.match(line)
        if m:
            out.append(m.group(1).lower())
    return out


def missing_sections(body: str) -> list[str]:
    """Display names of the required sections this plan does not label."""
    found = labels(body)
    return [name for name, pat in SECTIONS
            if not any(pat.search(lbl) for lbl in found)]


def filename_violation(name: str) -> str | None:
    """None when the name is `<slug>-<YYYY-MM-DD>.md`, else why it is not."""
    if DATED_NAME_RE.match(name):
        return None
    if DATE_RE.search(name):
        return ("the date must be the LAST element: "
                "`<slug>-<YYYY-MM-DD>.md`")
    return "no `-<YYYY-MM-DD>` date in the filename"


def is_grandfathered(name: str) -> bool:
    """True for a plan dated before CUTOFF, i.e. one that predates this gate."""
    dates = DATE_RE.findall(name)
    if not dates:
        return False
    return dates[-1] < CUTOFF


def violations(name: str, body: str) -> list[str]:
    if SKIP_MARKER in body or is_grandfathered(name):
        return []
    out = []
    fn = filename_violation(name)
    if fn:
        out.append(f"filename: {fn}")
    for section in missing_sections(body):
        out.append(f"missing section: {section}")
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    ti = payload.get("tool_input") or {}
    fp = (ti.get("file_path") or ti.get("path") or "").replace("\\", "/")
    if not fp or SCOPE not in fp or not fp.endswith(".md"):
        return 0

    path = Path(fp)
    try:
        body = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0

    bad = violations(path.name, body)
    if not bad:
        return 0

    listed = "\n".join(f"    - {b}" for b in bad)
    sys.stderr.write(
        "PLAN LINT (blocked): `.claude/rules/quick-plan.md` names five sections "
        "and a dated filename. This plan is short of that:\n" + listed + "\n\n"
        "  The shape:\n"
        "    q-system/output/plans/<slug>-<YYYY-MM-DD>.md\n"
        "    ## What/why             1-2 lines\n"
        "    ## Approach             the pick; name the options if there were 3\n"
        "    ## Files to touch       explicit paths\n"
        "    ## Acceptance criteria  checkboxes; for code, the reproducer\n"
        "    ## Patterns to follow   from this instance's own code\n\n"
        "  A plan is the checkpoint that survives context loss. On re-entry the "
        "next session resumes from the first unchecked criterion, so a plan "
        "with no criteria cannot be resumed -- it can only be re-derived.\n"
        f"  Checks the sections EXIST, not that they are filled in. Plans dated "
        f"before {CUTOFF} predate this gate and are exempt.\n"
        f"  Deliberate exception: add `{SKIP_MARKER}` to the file.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
