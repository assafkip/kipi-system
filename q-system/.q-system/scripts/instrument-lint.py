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
    should exclude, a corpus shaped by its seed. Those are measured by the
    advisory fixture `skill-evals/instrument-discipline.json`, never by a hook.

Scope: PostToolUse(Write|Edit|MultiEdit) on `**/investigation/findings/*.md`
and `**/output/analyses/**/*.md`. Everything else exits 0 on the first check.
Most instances have neither path; the blast radius is the q-investigate
instances, and the scope test is the first and widest thing this refuses to be.

GRANDFATHERING: 16 of the 61 in-scope files across the fleet (all in one instance)
carry a null-shaped line with no control label and predate the rule. A gate red on its own
population gets switched off, and a gate that is off protects nothing
(plan-lint.py made the same call). A file whose filename carries a date before
CUTOFF is exempt. A filename with no date is NOT exempt: templates and undated
findings are in scope.

HONEST BOUNDARY, four of them:
  1. Checks a control label EXISTS, never that the control is real, ran, or
     would have caught anything. `**Control:** n/a` passes.
  2. Reads the DATE IN THE FILENAME for the exemption. A back-dated filename
     walks past this gate. Deliberate trade for a self-maintaining exemption.
  3. Cannot see a null result reported in chat and never written to a file.
     A PostToolUse hook sees the file that was written, never the claim that
     was spoken.
  4. Catches case-004 shapes 2 and 5 (the null count, the failed checker
     reporting zero). Shapes 1, 3 and 4 are not null-shaped sentences and
     pass this gate untouched. The rule says so in its own text.

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

# A null-shaped claim: the sentence shape a zero takes when it is reported as a
# fact about the world. Each alternative is individually load-bearing and has a
# red case in the test.
NULL_CLAIM_RE = re.compile(
    r"(?i)(?<![\w.$])("
    r"\b(?:0|zero) of\b"
    r"|\bnone (?:found|observed|detected|present)\b"
    r"|\bno evidence of\b"
    r"|\breturned (?:nothing|zero|0)\b"
    r"|\bzero (?:matches|results|hits|instances|occurrences)\b"
    r"|\bno (?:instances|matches|results|hits|occurrences) (?:found|of|in|for)\b"
    r"|\|\s*\**0\**\s*\|"
    r")")

# The last alternative is a bare 0 in a markdown table cell. The case-004 file
# that held the misclassification wrote three of its zeros that way
# (`| Obfuscated URL | 0 | yes |`), and the first cut of this regex, written from
# an invented fixture, passed that file clean. Shapes come from the producer
# (memory: fixtures-come-from-producers), and the producer writes tables.

# A control counts when it appears as a LABEL -- a markdown heading, or a bold
# run at the start of a line (including inside a bullet or table cell).
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*$")
BOLD_LABEL_RE = re.compile(r"^\s{0,6}(?:[-*+|]\s*)?\*\*(.+?)\*\*")
CONTROL_LABEL_RE = re.compile(
    r"(?i)\b(?:negative control|positive control|control(?:s)?|known[- ]answer|calibration)\b")


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


def is_grandfathered(name: str) -> bool:
    """True for a file dated before CUTOFF. No date at all = NOT exempt."""
    dates = DATE_RE.findall(name)
    return bool(dates) and dates[-1] < CUTOFF


def violations(name: str, body: str) -> list[str]:
    if SKIP_MARKER in body or is_grandfathered(name):
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

    bad = violations(path.name, body)
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
