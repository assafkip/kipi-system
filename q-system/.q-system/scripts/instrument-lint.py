#!/usr/bin/env python3
"""instrument-lint: the deterministic slice of `.claude/rules/instrument-discipline.md`.

WHY (case-004, 2026-09-03): five defects in one investigation day, one shape. A
measurement whose instrument was never pointed at a case with a known answer:
a count of zero that was a property of the query set (rerun with other query
language: 18 hits), and a verification command that failed on a wrong path and
reported a clean zero indistinguishable from a clean result. Each was caught by
a human asking a question, never by a gate. The lesson
`every-measurement-needs-a-case-whose-answer-you-already-know` existed the whole
time. Per `skill-hook-pairing.md` the rule splits in two:

  - DETERMINISTIC (this script): a findings or analysis file that reports a
    NULL-SHAPED claim ("0 of", "none found", "no evidence of", "returned
    nothing", "zero matches") carries a CONTROL LABEL: a heading or bold label
    reading Control / Negative control / Known-answer case / Calibration.
    A label, never bare prose, so the word "control" inside a sentence cannot
    satisfy it (lesson a-check-must-be-able-to-fail-for-the-reason-you-care-abou).
  - JUDGMENT (stays in the rule, NOT enforced): whether the control is real,
    whether it ran, whether it would have caught the substitution. And the three
    case-004 shapes that are not null-shaped sentences at all: a control group
    whose DNS was never checked, a membership test never run against members it
    should exclude, a corpus shaped by its seed. Nothing measures those today:
    a trigger-eval fixture shipped in the first cut and was removed, because
    skill-trigger-eval.py runs a bare prompt from the repo root and a
    paths-scoped rule never loads there (Codex, PR #298; spillover captured).

Scope: PostToolUse(Write|Edit|MultiEdit) on `**/investigation/findings/*.md`
and `**/output/analyses/**/*.md`. Everything else exits 0 on the first check.
Most instances have neither path; the blast radius is the q-investigate
instances, and the scope test is the first and widest thing this refuses to be.

GRANDFATHERING: measured over every path in instance-registry.json on
2026-09-03: 246 in-scope files, 36 carry a null-shaped line with no control
label. All predate the rule. A gate red on its own population gets switched off,
and a gate that is off protects nothing (plan-lint.py made the same call). A
file is exempt when a date anywhere in its PATH is before CUTOFF, else when git
first saw it before CUTOFF. Undated and untracked = in scope (templates).
The first measurement of this population ran over a directory that does not
exist, returned zero in-scope files, and was read as "clean". That is scar
shape 5 in the rule, committed while building the gate for it.

HONEST BOUNDARY, four of them:
  1. Checks a control label EXISTS, never that the control is real, ran, or
     would have caught anything. `**Control:** n/a` passes.
  2. Reads a DATE IN THE PATH (else git history) for the exemption. A back-dated
     filename or directory walks past this gate. Deliberate trade for a
     self-maintaining exemption over a hand-kept list.
  3. Cannot see a null result reported in chat and never written to a file.
     A PostToolUse hook sees the file that was written, never the claim that
     was spoken.
  4. Catches case-004 shapes 2 and 5 (the null count, the failed checker
     reporting zero). Shapes 1, 3 and 4 are not null-shaped sentences and
     pass this gate untouched. The rule says so in its own text.
  5. A zero in a table cell is not matched (see NULL_CLAIM_RE). A finding that
     reports its null result only as a table value passes.

Bypass: put `instrument-lint-skip` in the file.
Contract: reads hook JSON on stdin. exit 0 = pass, exit 2 = block. stdlib only.
Self-test: `python3 test_instrument_lint.py`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCOPES = ("/investigation/findings/", "/output/analyses/")
SKIP_MARKER = "instrument-lint-skip"

# The day instrument-lint shipped. Files dated before this predate the gate.
CUTOFF = "2026-09-04"

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Exemption reads the date from the FULL PATH, not the basename. The instance
# with the most in-scope files names findings F-NNN-slug.md and dates its
# premortems in the directory (output/analyses/premortem-2026-08-13/premortem.md);
# a basename-only read left 9 pre-existing files red on ship day (Codex, PR #298).
# A path with no date at all falls back to the date git first saw the file.

# A null-shaped claim: the sentence shape a zero takes when it is reported as a
# fact about the world. Each alternative is individually load-bearing and has a
# red case in the test.
NULL_CLAIM_RE = re.compile(
    r"(?i)(?<![\w.$])(?<!step )(?<!stage )(?<!phase )(?<!attempt )(?<!round )("
    r"\b(?:0|zero) of\b"
    r"|\bnone (?:found|observed|detected|present)\b"
    r"|\bno evidence of\b"
    r"|\breturned (?:nothing|zero|0)\b"
    r"|\bzero (?:matches|results|hits|instances|occurrences)\b"
    r"|\bno (?:instances|matches|results|hits|occurrences) (?:found|of|in|for)\b"
    r")")

# NOT matched, on purpose: a bare 0 in a markdown table cell. It was in the first
# cut (the case-004 file writes `| Obfuscated URL | 0 | yes |`) and it fired on
# every profile-stats table in the fleet (`| Following | 0 |`, `| Posts | 199 |
# **0** |`), asking for a control on "this account follows nobody". A value is not
# a claim; the regex cannot tell them apart in a cell, so cells are out and the
# boundary says so. The lookbehinds drop ordinals: "Step 0 of 5" reports nothing.

# A control counts when it appears as a LABEL -- a markdown heading, or a bold
# run at the start of a line (including inside a bullet or table cell).
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*$")
BOLD_LABEL_RE = re.compile(r"^\s{0,6}(?:[-*+|]\s*)?\*\*(.+?)\*\*")
# Anchored at the START of the label. Unanchored, `## Access control`, `## Command
# and control (C2)` and `**Quality control:**` all passed the gate, and threat-intel
# findings carry a C2 section as a matter of course (Codex, PR #298).
CONTROL_LABEL_RE = re.compile(
    r"(?i)^(?:(?:negative|positive) )?controls?\b|^known[- ]answer|^calibration")


def in_scope(fp: str) -> bool:
    fp = fp.replace("\\", "/")
    return fp.endswith(".md") and any(s in fp for s in SCOPES)


def null_claims(body: str) -> list[str]:
    """Every line carrying a null-shaped claim (fenced code excluded)."""
    out = []
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if NULL_CLAIM_RE.search(line):
            out.append(line.strip())
    return out


def has_control_label(body: str) -> bool:
    for line in body.splitlines():
        m = HEADING_RE.match(line) or BOLD_LABEL_RE.match(line)
        if m and CONTROL_LABEL_RE.search(m.group(1)):
            return True
    return False


def git_added_date(path: Path) -> str | None:
    """YYYY-MM-DD git first saw this path, or None (untracked, no repo, no git).

    mtime was the obvious fallback and it is useless here: this hook runs AFTER
    the write, so every file it inspects was modified seconds ago. A typo fix to
    a months-old finding must stay exempt, and only history knows the file is old.
    """
    import subprocess
    try:
        out = subprocess.run(
            ["git", "log", "--diff-filter=A", "--follow", "--format=%as", "--", path.name],
            cwd=path.parent, capture_output=True, text=True, timeout=3).stdout.split()
    except Exception:
        return None
    return out[-1] if out else None


def is_grandfathered(fp: str, path: Path | None = None) -> bool:
    """True for a file that predates CUTOFF: by a date anywhere in its path, else
    by the date git first saw it. Undated AND untracked = NOT exempt."""
    dates = DATE_RE.findall(fp.replace("\\", "/"))
    if dates:
        return dates[-1] < CUTOFF
    if path is not None:
        added = git_added_date(path)
        return bool(added) and added < CUTOFF
    return False


def violations(fp: str, body: str, path: Path | None = None) -> list[str]:
    if SKIP_MARKER in body or is_grandfathered(fp, path):
        return []
    claims = null_claims(body)
    if not claims or has_control_label(body):
        return []
    return claims


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    ti = payload.get("tool_input") or {}
    fp = (ti.get("file_path") or ti.get("path") or "")
    if not fp or not in_scope(fp):
        return 0
    path = Path(fp)
    try:
        body = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0

    bad = violations(fp, body, path)
    if not bad:
        return 0

    listed = "\n".join(f"    - {b[:140]}" for b in bad[:6])
    sys.stderr.write(
        "INSTRUMENT LINT (blocked): this file reports a null result and names no "
        "control. A zero with no known-answer case is a property of the query, "
        "not of the world (case-004: 'absent' became 18 hits on rerun).\n"
        + listed + "\n\n"
        "  Add a labelled control, one of:\n"
        "    ## Control                 the case whose answer you already knew\n"
        "    **Negative control:**      the input that MUST return zero, and did\n"
        "    **Known-answer case:**     the input that MUST hit, and did\n"
        "  The label is what this checks. Whether the control is real is on you.\n"
        f"  Files dated before {CUTOFF} predate this gate and are exempt.\n"
        f"  Deliberate exception: add `{SKIP_MARKER}` to the file.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
