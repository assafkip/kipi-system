#!/usr/bin/env python3
"""Propose Skeptic anti-pattern additions from Codex findings on an archived PRD.

After a PRD archives, the Codex findings that were accepted during review
represent gaps the Skeptic persona did NOT catch up front. This script
reads those findings + the Skeptic Q-A pairs the founder recorded during
/prd-personas, then renders a proposal markdown file with:

 - Each accepted finding (severity blocker/major) the Skeptic missed
 - The Skeptic answer for the question that should have caught it
 - A templated anti-pattern phrasing the founder can edit + merge into
    `plugins/prd-os/personas/skeptic.md`

The script never auto-edits skeptic.md. It writes a proposal file the
founder reviews, edits, and commits through normal git flow so Codex review
fires on the diff (same gate as any other code change).

CLI:

  python3 plugins/prd-os/scripts/propose_skeptic_antipatterns.py <prd-id>
      Writes the proposal to q-system/output/skeptic-proposals/<prd-id>-proposal.md

  python3 plugins/prd-os/scripts/propose_skeptic_antipatterns.py <prd-id> --dry-run
      Prints the proposal to stdout (no file write). Used by tests.

Exit codes:
  0  success (proposal written or printed)
  2  user error (missing PRD id, spec not found)

The script is invoked best-effort from prd_runner.cmd_archive. If anything
raises, the archive still succeeds; only the proposal generation fails.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make sibling scripts importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_findings import classify_body  # noqa: E402
from config import Config, load as load_config  # noqa: E402
from phase0_measure import (  # noqa: E402
    extract_skeptic_section,
    strip_html_comments,
)


PROPOSAL_DIR_RELPATH = "q-system/output/skeptic-proposals"

SKEPTIC_QUESTIONS = {
    "Q1": "What is the strongest argument against doing this?",
    "Q2": "What is the smallest experiment that would disprove the thesis?",
    "Q3": "What is the cheapest non-build alternative?",
}

# class -> Skeptic question the founder should have answered to catch it.
CLASS_TO_QUESTION = {
    "vague-goal-class": "Q1",
    "empty-non-goals-class": "Q3",
}

ANTIPATTERN_TEMPLATES = {
    "vague-goal-class": (
        "When the success metric uses implementation language ('add X', "
        "'ship Y') instead of outcome language with a measurable threshold, "
        "treat the answer as unanswered and re-ask the Skeptic question."
    ),
    "empty-non-goals-class": (
        "When Q3 is answered with 'no alternative exists' or scope is left "
        "implicit, treat the answer as unanswered and re-ask with concrete "
        "non-build paths (template change, checklist, founder discipline)."
    ),
}

ACCEPTED_SEVERITIES = {"blocker", "major"}
ACCEPTED_SOURCE = "codex-review"
ACCEPTED_DISPOSITION = "accepted"


# ---------------------------------------------------------------------------
# Spec + findings IO
# ---------------------------------------------------------------------------


def find_spec_path(cfg: Config, prd_id: str) -> Path:
    """Resolve the PRD spec path under cfg.prds_dir. Raises FileNotFoundError."""
    spec_path = cfg.prds_dir / f"{prd_id}.md"
    if not spec_path.is_file():
        raise FileNotFoundError(f"PRD spec not found: {spec_path}")
    return spec_path


def find_findings_path(cfg: Config, prd_id: str) -> Path:
    """Resolve the findings JSONL path. Missing file is OK (empty findings)."""
    return cfg.findings_dir / f"{prd_id}-findings.jsonl"


def load_findings(findings_path: Path) -> list[dict]:
    """Read JSONL findings. Silently skips malformed lines (same policy as
    classify_findings.classify_jsonl). Returns empty list if file missing."""
    if not findings_path.is_file():
        return []
    out: list[dict] = []
    for raw in findings_path.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ---------------------------------------------------------------------------
# Skeptic Q-A extraction
# ---------------------------------------------------------------------------


_QUESTION_INDEX_RE = re.compile(r"^\*\*Q([123]):.*?\*\*$")
_CANONICAL_INDEX_RE = re.compile(r"^A([123]):\s*(.*)$")


def parse_skeptic_answers(spec_text: str) -> dict[str, str]:
    """Extract {Q1, Q2, Q3} -> answer text from the spec's Skeptic subsection.

    Accepts both formats the templates document:
      (a) `A1: <single line>` (canonical scaffold)
      (b) `**Q1: ...?**` followed by a prose paragraph (used in early PRDs)
    Canonical wins when both appear. Missing answers are absent from the dict.
    """
    stripped = strip_html_comments(spec_text)
    skeptic = extract_skeptic_section(stripped)
    if skeptic is None:
        return {}

    answers: dict[str, str] = {}
    for line in skeptic.splitlines():
        match = _CANONICAL_INDEX_RE.match(line.strip())
        if match is None:
            continue
        text = match.group(2).strip()
        if text:
            answers[f"Q{match.group(1)}"] = text

    lines = skeptic.splitlines()
    for i, raw in enumerate(lines):
        match = _QUESTION_INDEX_RE.match(raw.strip())
        if match is None:
            continue
        key = f"Q{match.group(1)}"
        if key in answers:
            continue
        prose = _collect_bold_answer_prose(lines, i + 1)
        if prose:
            answers[key] = prose
    return answers


def _collect_bold_answer_prose(lines: list[str], start: int) -> str:
    """Gather prose lines after a `**Q[123]: ...**` heading until the next
    Q heading, markdown heading, or end of section."""
    prose: list[str] = []
    for j in range(start, len(lines)):
        nxt = lines[j].rstrip()
        if _QUESTION_INDEX_RE.match(nxt.strip()):
            break
        if nxt.startswith("#"):
            break
        prose.append(nxt)
    return "\n".join(prose).strip()


# ---------------------------------------------------------------------------
# Finding selection
# ---------------------------------------------------------------------------


def select_findings_for_review(records: list[dict]) -> list[dict]:
    """Keep only findings worth proposing anti-patterns from."""
    selected: list[dict] = []
    for rec in records:
        if rec.get("disposition") != ACCEPTED_DISPOSITION:
            continue
        if rec.get("severity") not in ACCEPTED_SEVERITIES:
            continue
        if rec.get("source") != ACCEPTED_SOURCE:
            continue
        selected.append(rec)
    return selected


def route_to_question(classes: set[str]) -> str | None:
    """Return the Skeptic question that should have caught this finding,
    or None if no known class matches (caller routes to 'uncategorized')."""
    for cls in sorted(classes):
        question = CLASS_TO_QUESTION.get(cls)
        if question:
            return question
    return None


def propose_antipattern_phrasing(classes: set[str]) -> str:
    """Templated anti-pattern phrasing for the founder to edit."""
    snippets = [
        ANTIPATTERN_TEMPLATES[c] for c in sorted(classes)
        if c in ANTIPATTERN_TEMPLATES
    ]
    if snippets:
        return "\n\n".join(snippets)
    return (
        "Codex flagged this issue but it does not match any pre-defined "
        "anti-pattern class. Treat this as a candidate for a new Skeptic "
        "question or a different persona (PM, Architect, UX)."
    )


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_proposal(
    prd_id: str,
    skeptic_answers: dict[str, str],
    findings: list[dict],
    generated_at: str | None = None,
) -> str:
    """Render the proposal markdown."""
    parts: list[str] = []
    parts.append(f"# Skeptic anti-pattern proposal - {prd_id}\n")
    parts.append(f"Generated: {generated_at or _now_iso()}\n")
    parts.append(_render_findings_section(findings))
    parts.append(_render_skeptic_answers_section(skeptic_answers))
    parts.append(_render_merge_guidance())
    return "\n".join(parts)


def _render_findings_section(findings: list[dict]) -> str:
    if not findings:
        return (
            "## Findings the Skeptic did not catch\n\n"
            "Codex flagged no accepted findings of severity blocker or major. "
            "Nothing to learn from this round.\n"
        )
    lines: list[str] = ["## Findings the Skeptic did not catch\n"]
    for rec in findings:
        lines.append(_render_one_finding(rec))
    return "\n".join(lines)


def _render_one_finding(rec: dict) -> str:
    classes = classify_body(rec.get("body", ""))
    question = route_to_question(classes)
    bucket_label = question or "uncategorized"
    class_label = ", ".join(sorted(classes)) if classes else "no-known-class"
    body = rec.get("body", "(no body)").strip()
    return (
        f"### {rec.get('id', 'finding-?')} "
        f"({rec.get('severity', '?')}, routed to {bucket_label}, "
        f"class: {class_label})\n\n"
        f"{body}\n\n"
        f"**Proposed anti-pattern phrasing:**\n\n"
        f"{propose_antipattern_phrasing(classes)}\n"
    )


def _render_skeptic_answers_section(answers: dict[str, str]) -> str:
    lines = ["## Skeptic Q-A pairs captured\n"]
    for key, question in SKEPTIC_QUESTIONS.items():
        answer = answers.get(key, "(missing or skipped)")
        lines.append(f"**{key}:** {question}\n\n{answer}\n")
    return "\n".join(lines)


def _render_merge_guidance() -> str:
    return (
        "## How to merge\n\n"
        "1. Read each finding above. The 'routed to Qx' label tells you which "
        "Skeptic question should have surfaced it.\n"
        "2. Edit the proposed anti-pattern phrasing to match your voice.\n"
        "3. Append accepted anti-patterns to `plugins/prd-os/personas/skeptic.md` "
        "under '## Anti-patterns the Skeptic watches for'.\n"
        "4. Commit through normal git flow so Codex review fires on the diff.\n"
    )


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------


def propose(cfg: Config, prd_id: str) -> tuple[str, Path | None]:
    """Generate the proposal text and write it to disk. Returns (text, path).

    Path is None when called with write=False (used by tests via main()).
    """
    spec_path = find_spec_path(cfg, prd_id)
    spec_text = spec_path.read_text()
    skeptic_answers = parse_skeptic_answers(spec_text)

    findings_path = find_findings_path(cfg, prd_id)
    records = load_findings(findings_path)
    selected = select_findings_for_review(records)

    text = render_proposal(prd_id, skeptic_answers, selected)
    output_path = write_proposal(cfg.repo_root, prd_id, text)
    return text, output_path


def write_proposal(repo_root: Path, prd_id: str, content: str) -> Path:
    """Write proposal markdown to q-system/output/skeptic-proposals/."""
    out_dir = repo_root / PROPOSAL_DIR_RELPATH
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{prd_id}-proposal.md"
    out_path.write_text(content)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("prd_id", help="The archived PRD id (no .md suffix)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the proposal to stdout instead of writing to disk.",
    )
    args = parser.parse_args()

    cfg = load_config(strict=True)
    try:
        spec_path = find_spec_path(cfg, args.prd_id)
    except FileNotFoundError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    spec_text = spec_path.read_text()
    skeptic_answers = parse_skeptic_answers(spec_text)
    findings_path = find_findings_path(cfg, args.prd_id)
    records = load_findings(findings_path)
    selected = select_findings_for_review(records)
    text = render_proposal(args.prd_id, skeptic_answers, selected)

    if args.dry_run:
        sys.stdout.write(text)
        return 0

    out_path = write_proposal(cfg.repo_root, args.prd_id, text)
    print(json.dumps({"proposal_written": str(out_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
