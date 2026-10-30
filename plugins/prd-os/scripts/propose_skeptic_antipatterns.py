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

The script never auto-edits skeptic.md. It writes a proposal file, then files
ONE Linear issue for Sana naming that file, so the proposal enters the normal
triage path and the persona edit ships through a reviewed PR like any other
code change.

ASK-3406: the proposal used to end at "the founder reviews, edits, and
commits". Measured 2026-10-29: three proposals written Aug-Sep were still
unmerged, and skeptic.md had not changed since 2026-05-14. The writer worked;
the merge step was a person nobody reminded. Editing a persona file is a
technical call, so it does not wait on the founder.

CLI:

  python3 plugins/prd-os/scripts/propose_skeptic_antipatterns.py <prd-id>
      Writes the proposal to cfg.skeptic_proposals_dir/<prd-id>-proposal.md

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
import importlib.util
import json
import os
import re
import subprocess
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
# Every source that represents a real independent review pass, not just Codex's
# standard one. Was the single literal "codex-review", which silently dropped
# `codex-adversarial` too. Found by adversarial review 2026-07-26: during a spell
# when Codex was unavailable, 100% of reviews were `claude-*`, so this loop
# was discarding every finding and printing "Nothing to learn from this round"
# -- a false claim, not an empty one.
ACCEPTED_SOURCES = (
    "codex-review",
    "codex-adversarial",
    "claude-review",
    "claude-adversarial",
)
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
        if rec.get("source") not in ACCEPTED_SOURCES:
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
            "The reviewer flagged no accepted findings of severity blocker or major. "
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
        "## How to merge (Sana, through the normal issue flow)\n\n"
        "1. Read each finding above. The 'routed to Qx' label tells you which "
        "Skeptic question should have surfaced it.\n"
        "2. Rewrite the proposed phrasing so it reads as a watched-for pattern, "
        "not as a template.\n"
        "3. Append accepted anti-patterns to `plugins/prd-os/personas/skeptic.md` "
        "under '## Anti-patterns the Skeptic watches for'.\n"
        "4. Open a PR so Codex review fires on the diff, then merge it. Reject a "
        "finding here by saying why in the PR; a rejection is an outcome, an "
        "unread proposal is not.\n"
    )


# ---------------------------------------------------------------------------
# Filing (ASK-3406)
# ---------------------------------------------------------------------------

FLEET_FILER_RELPATH = Path("q-system") / ".q-system" / "scripts" / "spillover-linear-check.py"
FILER_TIMEOUT_SECONDS = 60


def _fleet_filer_module(cfg: Config):
    """The fleet's shared reader of alert-to-linear's answer, or None.

    Same loader shape as `prd_runner._spillover_linear_filer`, and for the same
    reason: how an alert-to-linear reply becomes a link is defined ONCE, in
    `spillover-linear-check.py`, and every producer reads it from there rather
    than re-deriving the regex. prd-os ships into repos with no q-system tree,
    so absence is an ordinary state, never an error.
    """
    path = Path(cfg.repo_root) / FLEET_FILER_RELPATH
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("skeptic_fleet_filer", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001
        return None


def message_for_proposal(prd_id: str, proposal_path: Path, findings: list[dict]) -> str:
    """The alert text. The title is its first ~110 chars, so the PRD id leads."""
    severities = ", ".join(
        sorted({str(r.get("severity") or "?") for r in findings})
    )
    return (
        f"skeptic proposal {prd_id}: {len(findings)} finding(s) ({severities}) the "
        f"Skeptic did not catch. Review {proposal_path}, then open a PR editing "
        f"plugins/prd-os/personas/skeptic.md, or reject with a reason."
    )


def file_review_issue(
    cfg: Config, prd_id: str, proposal_path: Path, findings: list[dict]
) -> dict | None:
    """File ONE Linear issue for Sana per proposal that has something to merge.

    Never raises, and that is a contract two callers depend on: archive is the
    load-bearing step (`_propose_skeptic_antipatterns_best_effort`) and `main()`
    documents exit 0 / `{"proposal_written": ...}`. The proposal file is already
    on disk before this runs, so a filing failure is recorded as a receipt row
    and loses nothing.

    Returns the filer's answer plus a `receipt` key: `"written"` when the row
    landed, `"failed"` (with `receipt_detail`) when the receipt IO itself blew
    up. That second case is the one failure this function can hit AFTER the
    work succeeded, so it degrades to a stderr line rather than a raise -- the
    receipt cannot be the one record whose loss destroys the round it records.

    An empty proposal files nothing on purpose: "the reviewer flagged no accepted
    findings" is a signal about the round, not a queue item. Volume from one
    detector is a signal about the detector (`automated-filer-marking.md`).
    """
    if not findings:
        return None
    link: dict
    shared = _fleet_filer_module(cfg)
    if shared is None:
        link = {"state": "no-filer", "exit": None, "identifier": None,
                "at": _now_iso(),
                "detail": f"no {FLEET_FILER_RELPATH} in {cfg.repo_root}"}
    else:
        link = _run_fleet_filer(shared, cfg, prd_id, proposal_path, findings)
    # The receipt is the LAST thing that happens, and the only one whose failure
    # can cost nothing: the proposal is on disk and the Linear issue may already
    # exist. Letting its IO escape made `main()` exit nonzero with a traceback
    # against its documented exit-0 contract, reporting a round that in fact
    # succeeded as a total failure (PR #566 minor).
    try:
        _append_filing_receipt(cfg, prd_id, proposal_path, findings, link)
    except Exception as exc:  # noqa: BLE001 -- the docstring's contract above
        # Reported, never swallowed: stderr is the one channel BOTH callers
        # already surface (`_propose_skeptic_antipatterns_best_effort` writes
        # its own line there), so a lost receipt is not silence bought by a fix.
        link = dict(link, receipt="failed", receipt_detail=repr(exc)[:300])
        sys.stderr.write(
            f"skeptic proposal filing receipt NOT written for {prd_id}: {exc!r}\n"
            f"  the proposal IS at {proposal_path} and the filer said "
            f"{link.get('state')}/{link.get('identifier')}\n"
        )
        return link
    # Stated on success too. A key present only on failure makes a missing key
    # mean both "receipt landed" and "an older caller never set it".
    return dict(link, receipt="written")


def _run_fleet_filer(
    shared, cfg: Config, prd_id: str, proposal_path: Path, findings: list[dict]
) -> dict:
    """Run alert-to-linear.py and read its answer through the shared parser."""
    env = dict(os.environ)
    # Route the ticket to THIS repo's Linear project, same as file_record does.
    env.setdefault("KIPI_ALERT_REPO_PATH", str(cfg.repo_root))
    try:
        res = subprocess.run(
            [sys.executable, str(shared.FILER),
             message_for_proposal(prd_id, proposal_path, findings)],
            capture_output=True, text=True, env=env,
            timeout=FILER_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        return {"state": "failed", "exit": None, "identifier": None,
                "at": _now_iso(), "detail": repr(exc)[:300]}
    return shared.parse_filer_output(res.returncode, res.stdout, res.stderr)


def _append_filing_receipt(
    cfg: Config, prd_id: str, proposal_path: Path, findings: list[dict], link: dict
) -> Path:
    """Append one row per filing attempt beside the proposals.

    Why a receipt and not just the issue: before ASK-3406 nothing in this repo
    could answer "which proposals were ever routed anywhere". Three sat unmerged
    for five months and the only way to notice was to read the directory.
    """
    out_dir = cfg.skeptic_proposals_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "filings.jsonl"
    row = {
        "prd_id": prd_id,
        "proposal": str(proposal_path),
        "findings": len(findings),
        "at": _now_iso(),
        "linear": link,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return path


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
    output_path = write_proposal(cfg, prd_id, text)
    # THE SINGLE FILING CHOKEPOINT. Both callers (prd_runner.cmd_archive and
    # main() below) reach Linear through here, so there is no path that writes a
    # proposal without routing it (ASK-3406).
    file_review_issue(cfg, prd_id, output_path, selected)
    return text, output_path


def write_proposal(cfg, prd_id: str, content: str) -> Path:
    """Write proposal markdown to the configured proposals dir.

    Resolved from config (default `.prd-os/skeptic-proposals`) rather than the
    old hardcoded `q-system/output/skeptic-proposals`, which created a kipi
    tree in every repo that archived a PRD.
    """
    out_dir = cfg.skeptic_proposals_dir
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

    if args.dry_run:
        spec_text = spec_path.read_text()
        skeptic_answers = parse_skeptic_answers(spec_text)
        records = load_findings(find_findings_path(cfg, args.prd_id))
        selected = select_findings_for_review(records)
        sys.stdout.write(render_proposal(args.prd_id, skeptic_answers, selected))
        return 0

    # Through propose(), not a second copy of its body: the filing chokepoint
    # lives there, and a CLI path that wrote a proposal without routing it is the
    # exact gap ASK-3406 closed.
    _text, out_path = propose(cfg, args.prd_id)
    print(json.dumps({"proposal_written": str(out_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
