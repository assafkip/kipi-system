"""Tests for propose_skeptic_antipatterns.py.

Covers:
  - Happy path: PRD with Skeptic Q-A pairs + Codex findings -> proposal
    routes each finding to the right question and writes to disk.
  - Empty findings -> proposal emits the "nothing to learn" message.
  - Missing Skeptic section -> all answers marked missing/skipped.
  - Filters: rejected disposition, minor severity, non-codex source
    are excluded.
  - Uncategorized findings: body matches no known class -> routed to
    "uncategorized" bucket.
  - Bold-question format (`**Q1: ...**` + prose) parses correctly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from propose_skeptic_antipatterns import (  # noqa: E402
    parse_skeptic_answers,
    propose,
    render_proposal,
    select_findings_for_review,
)


PRD_FRONTMATTER = """---
id: prd-{slug}
title: {slug}
status: archived
codex_reviewed_at: 2026-05-14T00:00:00Z
---

# {slug}

## Problem

placeholder

"""

CANONICAL_SKEPTIC_BLOCK = """## Persona Review

### Skeptic

A1: The strongest argument is that the cheaper template alternative would solve the same problem.
A2: Run on 5 PRDs, kill if the rate does not drop 50%.
A3: A checklist appended to the PRD template, zero new commands.

## Issues

"""

BOLD_SKEPTIC_BLOCK = """## Persona Review

### Skeptic

**Q1: What is the strongest argument against doing this?**
The founder can solve this with a four-bullet checklist appended to the PRD template,
zero new commands, zero new infrastructure.

**Q2: What is the smallest experiment that would disprove the thesis?**
Skeptic persona only, three pinned questions, no precheck heuristic.

**Q3: What is the cheapest non-build alternative?**
Adding the four bullet lenses to the prd-start skill's authoring guidance.

## Issues

"""

NO_PERSONA_REVIEW = """## Issues

"""


def _write_prd(prds_dir: Path, slug: str, skeptic_block: str) -> Path:
    prds_dir.mkdir(parents=True, exist_ok=True)
    path = prds_dir / f"prd-{slug}.md"
    path.write_text(PRD_FRONTMATTER.format(slug=slug) + skeptic_block)
    return path


def _write_findings(findings_dir: Path, slug: str, records: list[dict]) -> Path:
    findings_dir.mkdir(parents=True, exist_ok=True)
    path = findings_dir / f"prd-{slug}-findings.jsonl"
    body = "\n".join(json.dumps(r) for r in records)
    path.write_text(body + ("\n" if records else ""))
    return path


def _finding(
    fid: str,
    body: str,
    *,
    severity: str = "major",
    disposition: str = "accepted",
    source: str = "codex-review",
) -> dict:
    return {
        "id": fid,
        "prd_id": "prd-fixture",
        "severity": severity,
        "disposition": disposition,
        "source": source,
        "body": body,
        "created_at": "2026-05-14T00:00:00Z",
        "resolved_at": "2026-05-14T00:00:00Z",
    }


def _load_cfg(fake_repo, write_config, import_config):
    write_config(
        fake_repo,
        {
            "config_schema_version": 1,
            "prds_dir": ".prd-os/prds",
            "issues_dir": ".prd-os/issues",
            "findings_dir": ".prd-os/findings",
            "state_dir": ".claude/state",
        },
    )
    return import_config.load(strict=True)


# ---------------------------------------------------------------------------
# parse_skeptic_answers
# ---------------------------------------------------------------------------


def test_parse_canonical_format_returns_three_answers():
    answers = parse_skeptic_answers(PRD_FRONTMATTER.format(slug="x") + CANONICAL_SKEPTIC_BLOCK)
    assert set(answers.keys()) == {"Q1", "Q2", "Q3"}
    assert "template alternative" in answers["Q1"]
    assert "five prds" in answers["Q2"].lower() or "5 prds" in answers["Q2"].lower()


def test_parse_bold_format_returns_three_answers():
    answers = parse_skeptic_answers(PRD_FRONTMATTER.format(slug="x") + BOLD_SKEPTIC_BLOCK)
    assert set(answers.keys()) == {"Q1", "Q2", "Q3"}
    assert "four-bullet checklist" in answers["Q1"]


def test_parse_missing_section_returns_empty():
    answers = parse_skeptic_answers(PRD_FRONTMATTER.format(slug="x") + NO_PERSONA_REVIEW)
    assert answers == {}


# ---------------------------------------------------------------------------
# select_findings_for_review (filter contract)
# ---------------------------------------------------------------------------


def test_select_excludes_rejected_minor_and_non_codex():
    records = [
        _finding("finding-1", "vague success metric", severity="blocker"),
        _finding("finding-2", "non-goals empty", disposition="rejected"),
        _finding("finding-3", "minor nit", severity="minor"),
        _finding("finding-4", "self-review issue", source="self-review"),
        _finding("finding-5", "scope discipline missing", severity="major"),
    ]
    kept = select_findings_for_review(records)
    kept_ids = [r["id"] for r in kept]
    assert kept_ids == ["finding-1", "finding-5"]


# ---------------------------------------------------------------------------
# render_proposal (markdown shape)
# ---------------------------------------------------------------------------


def test_render_routes_vague_goal_to_q1_and_empty_ng_to_q3():
    findings = [
        _finding("finding-1", "the success metric is too vague, not operationalized"),
        _finding("finding-2", "scope discipline missing, non-goals empty"),
    ]
    answers = {"Q1": "A1 answer", "Q2": "A2 answer", "Q3": "A3 answer"}
    md = render_proposal("prd-fixture", answers, findings, generated_at="2026-05-15T00:00:00Z")
    assert "routed to Q1" in md
    assert "routed to Q3" in md
    assert "implementation language" in md  # vague-goal anti-pattern template
    assert "non-build paths" in md  # empty-non-goals anti-pattern template
    assert "A1 answer" in md
    assert "A3 answer" in md


def test_render_empty_findings_emits_nothing_to_learn():
    md = render_proposal("prd-fixture", {"Q1": "x", "Q2": "y", "Q3": "z"}, [])
    assert "Nothing to learn from this round" in md


def test_render_missing_skeptic_section_marks_answers_missing():
    md = render_proposal("prd-fixture", {}, [])
    assert "missing or skipped" in md


def test_render_uncategorized_class_routes_to_uncategorized():
    findings = [
        _finding("finding-9", "some issue that does not match any known class"),
    ]
    md = render_proposal("prd-fixture", {}, findings, generated_at="2026-05-15T00:00:00Z")
    assert "routed to uncategorized" in md
    assert "candidate for a new Skeptic question" in md


# ---------------------------------------------------------------------------
# propose() end-to-end: writes file
# ---------------------------------------------------------------------------


def test_propose_writes_proposal_file(fake_repo, write_config, import_config):
    cfg = _load_cfg(fake_repo, write_config, import_config)
    _write_prd(fake_repo / ".prd-os" / "prds", "fixture", CANONICAL_SKEPTIC_BLOCK)
    _write_findings(
        fake_repo / ".prd-os" / "findings",
        "fixture",
        [_finding("finding-1", "the success metric is too vague, not operationalized")],
    )

    text, out_path = propose(cfg, "prd-fixture")

    assert out_path is not None
    assert out_path.is_file()
    assert out_path.name == "prd-fixture-proposal.md"
    assert out_path.parent.name == "skeptic-proposals"
    assert "routed to Q1" in text
    assert out_path.read_text() == text


def test_propose_raises_for_missing_spec(fake_repo, write_config, import_config):
    cfg = _load_cfg(fake_repo, write_config, import_config)
    # No PRD spec written.
    with pytest.raises(FileNotFoundError):
        propose(cfg, "prd-does-not-exist")
