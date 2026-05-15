#!/usr/bin/env python3
"""Measure progress against the planning-personas Phase 0 kill criterion.

This script implements the verdict logic described in
`.prd-os/prds/prd-planning-personas-2026-05-13.md`. It walks every PRD under
`cfg.prds_dir`, classifies each as `personas-applied` or `no-personas` based
on whether the PRD body contains a non-commented `## Persona Review` section
with at least one non-empty Skeptic answer, then aggregates the findings for
each group via `classify_findings.classify_jsonl`.

Verdict logic (the parent PRD's kill criterion, corrected per
prd-prd-os-receipts-and-phase0-measure-2026-05-14 finding-4):

  - personas_applied.rate <= 0.5 * no_personas.rate -> `kill`
    The template scaffold achieved the 50% reduction target. The
    `/prd-personas` command must NOT ship; the template-only experiment won.

  - personas_applied.rate >  0.5 * no_personas.rate -> `continue`
    The reduction was not achieved. Ship the `/prd-personas` command.

  - Either group has fewer than 3 PRDs with findings -> `insufficient-data`

Layout coupling (documented per finding-6 of the same PRD): the persona
detector depends on the exact section headings `## Persona Review` and
`### Skeptic`, plus the `A1:` / `A2:` / `A3:` answer-line convention. These
match the templates at `plugins/prd-os/templates/prd.md` and
`q-system/marketing/templates/prd.md`. If those templates change, this file
changes with them.

CLI:

  python3 plugins/prd-os/scripts/phase0_measure.py
      Emits JSON verdict to stdout. Appends one row to baseline.md.

Exit code: always 0 (measurement, not a gate).

Propagation: the baseline.md append target is instance-local. `kipi-update.sh`
excludes `memory/` from the rsync that propagates `q-system/` to instances,
so appended rows survive `kipi update`. See the Propagation contract section
in `q-system/memory/working/prd-personas-baseline.md` for the full contract.
The regression test at `plugins/prd-os/tests/test_propagation.py` binds it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

# Make sibling scripts importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_findings import classify_jsonl  # noqa: E402
from config import Config, load as load_config  # noqa: E402


__all__ = [
    "BASELINE_DOC_RELPATH",
    "MIN_PRDS_PER_GROUP",
    # Persona-detection primitives (promoted to public for cross-script reuse,
    # e.g. propose_skeptic_antipatterns.py reads Q-A pairs from PRD specs).
    "PERSONA_REVIEW_HEADING_RE",
    "CANONICAL_ANSWER_RE",
    "SKEPTIC_SUBSECTION_RE",
    "strip_html_comments",
    "has_canonical_answer",
    "has_bold_question_with_answer",
    "extract_skeptic_section",
    "has_personas_applied",
    # Aggregation + verdict.
    "classify_prds",
    "compute_verdict",
    "append_baseline_row",
    "run",
]


BASELINE_DOC_RELPATH = "q-system/memory/working/prd-personas-baseline.md"
MIN_PRDS_PER_GROUP = 3


# ---------------------------------------------------------------------------
# Persona detection
# ---------------------------------------------------------------------------


_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
PERSONA_REVIEW_HEADING_RE = re.compile(r"(?m)^## Persona Review\b")
# Canonical answer format used by the template scaffold: "A1: <text>"
CANONICAL_ANSWER_RE = re.compile(r"(?m)^A[123]:[ \t]*(\S.*)$")
# Alternate format used in earlier PRDs (bold question heading on its own line):
# "**Q1: ...?**" followed by a non-empty prose answer on the next non-blank line.
_BOLD_QUESTION_RE = re.compile(r"(?m)^\*\*Q[123]:.*\*\*\s*$")


def strip_html_comments(text: str) -> str:
    """Remove all HTML comment blocks. Used before persona detection so
    commented-out template scaffolds do not trigger a false positive."""
    return _HTML_COMMENT_RE.sub("", text)


def has_canonical_answer(stripped: str) -> bool:
    """Detect `A1:` / `A2:` / `A3:` lines with non-empty trailing text."""
    for match in CANONICAL_ANSWER_RE.finditer(stripped):
        if match.group(1).strip():
            return True
    return False


def has_bold_question_with_answer(stripped: str) -> bool:
    """Detect `**Q[123]: ...**` followed within 5 lines by a non-empty
    prose answer (not another question heading, not a markdown heading)."""
    lines = stripped.splitlines()
    for i, line in enumerate(lines):
        if not _BOLD_QUESTION_RE.match(line):
            continue
        for j in range(i + 1, min(i + 5, len(lines))):
            nxt = lines[j].strip()
            if not nxt:
                continue
            if nxt.startswith("**Q") or nxt.startswith("#"):
                break
            return True
    return False


SKEPTIC_SUBSECTION_RE = re.compile(
    r"(?ms)^### Skeptic\b.*?(?=^##\s|^### \S|\Z)"
)


def extract_skeptic_section(stripped: str) -> str | None:
    """Return the text of the ### Skeptic subsection inside the Persona Review
    block, or None if the section is missing. Bounds are: from the ### Skeptic
    heading to the next ## or ### heading, or end of document."""
    header = PERSONA_REVIEW_HEADING_RE.search(stripped)
    if header is None:
        return None
    body_after_header = stripped[header.end():]
    match = SKEPTIC_SUBSECTION_RE.search(body_after_header)
    return match.group(0) if match else None


def has_personas_applied(prd_body: str) -> bool:
    """Return True if the PRD body has a real (uncommented) Persona Review
    section AND an inner ### Skeptic subsection with at least one non-empty
    answer.

    Accepts two answer formats inside the Skeptic subsection:
      (a) Canonical template format: `A1: <answer text>`
      (b) Earlier PRD format: `**Q1: ...?**` followed by a prose answer

    Scoping to the ### Skeptic subsection prevents false positives from
    stray A1/A2/A3 lines elsewhere in the PRD body.
    """
    stripped = strip_html_comments(prd_body)
    skeptic_text = extract_skeptic_section(stripped)
    if skeptic_text is None:
        return False
    return has_canonical_answer(skeptic_text) or has_bold_question_with_answer(skeptic_text)


# ---------------------------------------------------------------------------
# Group aggregation
# ---------------------------------------------------------------------------


def _findings_path_for(cfg: Config, prd_id: str) -> Path:
    return cfg.findings_dir / f"{prd_id}-findings.jsonl"


def classify_prds(cfg: Config) -> tuple[list[dict], list[dict]]:
    """Walk cfg.prds_dir, return (personas_applied, no_personas) buckets.

    Each bucket is a list of dicts: {prd_id, vague, empty_ng, total}.
    """
    personas_applied: list[dict] = []
    no_personas: list[dict] = []

    if not cfg.prds_dir.is_dir():
        return personas_applied, no_personas

    for prd_path in sorted(cfg.prds_dir.glob("*.md")):
        prd_id = prd_path.stem
        body = prd_path.read_text()
        findings_path = _findings_path_for(cfg, prd_id)
        if not findings_path.is_file():
            continue
        counts = classify_jsonl(findings_path)
        entry = {
            "prd_id": prd_id,
            "vague": counts["vague-goal-class"],
            "empty_ng": counts["empty-non-goals-class"],
            "total": counts["total"],
        }
        if has_personas_applied(body):
            personas_applied.append(entry)
        else:
            no_personas.append(entry)
    return personas_applied, no_personas


def _group_summary(entries: list[dict]) -> dict:
    total_findings = sum(e["total"] for e in entries)
    vague_total = sum(e["vague"] for e in entries)
    empty_ng_total = sum(e["empty_ng"] for e in entries)
    concerning = vague_total + empty_ng_total
    rate = concerning / total_findings if total_findings else 0.0
    return {
        "prds": [e["prd_id"] for e in entries],
        "total_findings": total_findings,
        "concerning_findings": concerning,
        "vague_goal": vague_total,
        "empty_non_goals": empty_ng_total,
        "rate": rate,
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def compute_verdict(personas_applied: dict, no_personas: dict) -> tuple[str, str]:
    """Return (verdict, recommendation).

    See module docstring for the verdict logic.
    """
    if (
        len(personas_applied["prds"]) < MIN_PRDS_PER_GROUP
        or len(no_personas["prds"]) < MIN_PRDS_PER_GROUP
    ):
        return (
            "insufficient-data",
            (
                f"At least {MIN_PRDS_PER_GROUP} PRDs in each group are needed "
                "before the kill criterion can be evaluated. Continue running "
                "the template-only experiment and re-measure later."
            ),
        )
    if personas_applied["rate"] <= 0.5 * no_personas["rate"]:
        return (
            "kill",
            (
                "Template scaffold achieved the 50% reduction target. Do NOT "
                "ship the /prd-personas command; the template-only approach "
                "is sufficient."
            ),
        )
    return (
        "continue",
        (
            "Template scaffold did NOT achieve the 50% reduction target. "
            "Ship the /prd-personas command; manual scaffold alone is not "
            "enough."
        ),
    )


# ---------------------------------------------------------------------------
# Baseline append
# ---------------------------------------------------------------------------


def _today_iso_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _format_baseline_row(
    today: str,
    personas_applied: dict,
    no_personas: dict,
    verdict: str,
) -> str:
    """Format matches the documented schema in prd-personas-baseline.md:
    | <date> | measurement | <pers>/<no-pers> PRDs | <total> | <vague> | <empty-ng> | verdict=<v> |
    """
    total = personas_applied["total_findings"] + no_personas["total_findings"]
    vague = personas_applied["vague_goal"] + no_personas["vague_goal"]
    empty_ng = personas_applied["empty_non_goals"] + no_personas["empty_non_goals"]
    return (
        f"| {today} | measurement | "
        f"{len(personas_applied['prds'])}/{len(no_personas['prds'])} PRDs | "
        f"{total} | {vague} | {empty_ng} | verdict={verdict} |\n"
    )


def append_baseline_row(repo_root: Path, row: str) -> None:
    """Append the row to the baseline doc. Creates the file if absent."""
    baseline_path = repo_root / BASELINE_DOC_RELPATH
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    if not baseline_path.is_file():
        baseline_path.write_text("")
    with baseline_path.open("a") as fh:
        fh.write(row)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run(cfg: Optional[Config] = None) -> dict:
    """Pure function: produce the verdict dict. Side-effects in main()."""
    if cfg is None:
        cfg = load_config(strict=True)
    personas_applied_raw, no_personas_raw = classify_prds(cfg)
    personas_applied = _group_summary(personas_applied_raw)
    no_personas = _group_summary(no_personas_raw)
    verdict, recommendation = compute_verdict(personas_applied, no_personas)
    return {
        "personas_applied": personas_applied,
        "no_personas": no_personas,
        "verdict": verdict,
        "recommendation": recommendation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--no-baseline-append",
        action="store_true",
        help="Skip the baseline.md append side effect (useful for tests).",
    )
    args = parser.parse_args()

    cfg = load_config(strict=True)
    result = run(cfg)

    if not args.no_baseline_append:
        row = _format_baseline_row(
            _today_iso_date(),
            result["personas_applied"],
            result["no_personas"],
            result["verdict"],
        )
        append_baseline_row(cfg.repo_root, row)

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
