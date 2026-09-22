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

Scope: PostToolUse(Write|Edit|MultiEdit) on any `.md` under
`/investigation/findings/`, `/output/analyses/` or (added 2026-09-21) any
`/output/` directory. Everything else exits 0 on the first check. See SCOPES for
the blast-radius measurement that picked that widening and for the two
candidates it refused, with their numbers.

GRANDFATHERING: per scope, from the day that scope was added, measured before it
was added. Original two scopes, over every path in instance-registry.json on
2026-09-03: 246 in-scope files, 36 carry a null-shaped line with no control
label. All predate the rule. A gate red on its own population gets switched off,
and a gate that is off protects nothing (plan-lint.py made the same call). A
file is exempt when the date in its BASENAME is before CUTOFF, else when git
most recently added it before CUTOFF. Undated and untracked = in scope.
The first measurement of this population ran over a directory that does not
exist, returned zero in-scope files, and was read as "clean". That is scar
shape 5 in the rule, committed while building the gate for it.

HONEST BOUNDARY, four of them:
  1. Checks a control label EXISTS, never that the control is real, ran, or
     would have caught anything. `**Control:** n/a` passes.
  2. Reads a date in the BASENAME (else git history) for the exemption. A
     back-dated filename walks past this gate. The inverse costs too: an
     UNDATED and UNTRACKED file can never be exempt, which is why the widened
     scope left 3 of 7697 red rather than 0. Deliberate trade for a
     self-maintaining exemption over a hand-kept list.
  3. Cannot see a null result reported in chat and never written to a file.
     A PostToolUse hook sees the file that was written, never the claim that
     was spoken. This is where MOST of 2026-09-20's wrong numbers lived: "6
     gates, 100% have a red case", "0 of 0 known-need files ranked" and a Jev
     run whose 61 calls all returned HTTP 422 were said out loud before any of
     them reached a file. A wider SCOPES does not narrow this hole by one inch.
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

# (path fragment, cutoff). Each scope grandfathers the population it INHERITED on
# the day it was added, because a gate red on day one gets switched off and a gate
# that is off protects nothing (plan-lint.py made the same call).
#
# WIDENED 2026-09-21. The first cut guarded two directories, which is the failure
# this gate exists for wearing the gate's own clothes: the mechanism was scoped to
# the room it was built in. Three wrong numbers reported on 2026-09-20 were every
# one null-shaped, and the ONE of the three that reached a file landed outside
# those two directories. The other two were spoken and never written, which no
# file scope reaches; boundary 3 below is where that lives. Say it at that size:
# the scope moved because a written null claim could land in a directory nobody
# watched, never because widening a file scope could catch a spoken number.
# Measured before the tuple moved, current logic, every path in
# instance-registry.json (7697 .md files under an `/output/` anywhere):
#   /output/           7697 files  522 uncontrolled   3 red under a 2026-09-21 cutoff
#   /output/rca/        381         68                0
#   /output/plans/     2775         96                0
#   /investigation/    5287        149               37  EXCLUDED
#   /memory/            614         10                0 here, 12 in auto-memory  EXCLUDED
# `/investigation/` stays out because its 37 are scraped evidence `content.md`
# ("OCR ... returned 0 characters"), undated AND untracked, so the exemption
# structurally cannot fire and they are red forever. `/memory/` stays out because
# the fragment cannot tell an instance `memory/` (0 red) from `~/.claude/projects/
# */memory/` (12 red, also undated and untracked), and that is the highest-traffic
# write path in the system. `/investigation/findings/` is already in scope and
# stays there, which is the part of investigation that reports rather than captures.
SCOPES = (
    ("/investigation/findings/", "2026-09-04"),
    ("/output/analyses/", "2026-09-04"),
    ("/output/", "2026-09-21"),
)
SKIP_MARKER = "instrument-lint-skip"

# The day instrument-lint shipped, and the cutoff for the two original scopes.
# Kept as a module constant because it is the DEFAULT for is_grandfathered, and
# because a path with no matching scope (a direct call from the test suite) has
# no cutoff of its own.
CUTOFF = "2026-09-04"

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Exemption reads the date from the BASENAME, else the most recent date git ADDED
# the file. Two rounds of review on PR #298 moved this: a basename-only read left
# 9 pre-existing undated files red on ship day, and the round-1 fix (a date
# anywhere in the path) exempted every NEW file written into an old dated
# directory forever. Same finding class twice, so the heuristic went and history
# took its place: git is the only source that knows a file is old, and the
# basename date survives only for untracked files, which git cannot answer for.

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
BOLD_LABEL_RE = re.compile(r"^\s{0,6}(?:(?:[-*+|>]|\d+[.)])\s*)?\*\*(.+?)\*\*")
# Anchored at the START of the label. Unanchored, `## Access control`, `## Command
# and control (C2)` and `**Quality control:**` all passed the gate, and threat-intel
# findings carry a C2 section as a matter of course (Codex, PR #298).
# The label ENDS at a colon or end of line, so `## Control plane` is not a
# control either (Codex round 2).
CONTROL_LABEL_RE = re.compile(
    r"(?i)^(?:(?:negative|positive) )?controls?(?::|\s*$)"
    r"|^known[- ]answer(?: case)?(?::|\s*$)|^calibration(?::|\s*$)")


def scope_cutoff(fp: str) -> str | None:
    """The cutoff governing this path, or None when the path is out of scope.

    The STRICTEST (earliest) cutoff of every scope the path matches. A file under
    `/output/analyses/` also sits under `/output/`; taking the widest scope's
    later cutoff would RELAX the two original scopes as a side effect of widening,
    which is a regression wearing a feature's clothes. min(), never first-match.
    """
    fp = fp.replace("\\", "/")
    if not fp.endswith(".md"):
        return None
    cuts = [c for frag, c in SCOPES if frag in fp]
    return min(cuts) if cuts else None


def in_scope(fp: str) -> bool:
    return scope_cutoff(fp) is not None


def null_claims(body: str) -> list[str]:
    """Every line carrying a null-shaped claim (fenced code excluded)."""
    out = []
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
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
    """YYYY-MM-DD of the MOST RECENT commit that added this path, or None
    (untracked, no repo, no git).

    mtime is useless here: this hook runs AFTER the write, so every file it
    inspects was modified seconds ago. Most recent add, not first: a file
    deleted and re-created after CUTOFF is a new file. No --follow: rename
    pairing let an unrelated old file lend its date (Codex round 2).
    """
    import subprocess
    try:
        out = subprocess.run(
            ["git", "log", "--diff-filter=A", "--format=%as", "--", path.name],
            cwd=path.parent, capture_output=True, text=True, timeout=3).stdout.split()
    except Exception:
        return None
    return out[0] if out else None


def is_grandfathered(fp: str, path: Path | None = None,
                    cutoff: str = CUTOFF) -> bool:
    """True for a file that predates its scope's cutoff: by a date in its
    BASENAME, else by the most recent date git added it. A directory date never
    counts. Undated AND untracked = NOT exempt."""
    dates = DATE_RE.findall(Path(fp.replace("\\", "/")).name)
    if dates:
        return dates[-1] < cutoff
    if path is not None:
        added = git_added_date(path)
        return bool(added) and added < cutoff
    return False


def violations(fp: str, body: str, path: Path | None = None,
               cutoff: str | None = None) -> list[str]:
    # Pure-string checks first; git runs only on a file that would block.
    claims = null_claims(body)
    if not claims or has_control_label(body) or SKIP_MARKER in body:
        return []
    # The scope decides the cutoff. A caller passing one explicitly wins, and a
    # path matching no scope falls back to the original CUTOFF rather than to
    # "exempt", so a direct call can never be silently relaxed by widening.
    if is_grandfathered(fp, path, cutoff or scope_cutoff(fp) or CUTOFF):
        return []
    return claims


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    ti = payload.get("tool_input") or {}
    fp = (ti.get("file_path") or ti.get("path") or "")
    if not fp:
        return 0
    path = Path(fp).resolve()  # a cwd-relative path must not fall out of scope
    fp = str(path)
    if not in_scope(fp):
        return 0
    try:
        body = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0

    # Resolved ONCE and reused, because the refusal QUOTES it. Printing the
    # module CUTOFF here told an /output/ author to date the file before
    # 2026-09-04 when 2026-09-21 is the date that would have exempted it: a
    # refusal that names the wrong escape is worse than a terse one, and this
    # gate's rule claims its stderr carries the whole fix (Codex reviewer,
    # skeleton PR #398, sp-6c0496a4).
    cutoff = scope_cutoff(fp) or CUTOFF
    bad = violations(fp, body, path, cutoff)
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
        f"  Files dated before {cutoff} predate THIS scope and are exempt.\n"
        f"  Deliberate exception: add `{SKIP_MARKER}` to the file.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
