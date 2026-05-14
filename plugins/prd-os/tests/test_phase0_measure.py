"""Tests for phase0_measure.py.

Validates persona detection (commented vs uncommented sections), per-group
aggregation, the verdict logic (kill / continue / insufficient-data), JSON
output schema, and baseline.md row appending.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from phase0_measure import (  # noqa: E402
    BASELINE_DOC_RELPATH,
    append_baseline_row,
    classify_prds,
    compute_verdict,
    has_personas_applied,
    run,
    _format_baseline_row,
    _group_summary,
    _today_iso_date,
)


PRD_FRONTMATTER = """---
id: prd-{slug}
title: {slug}
status: archived
codex_reviewed_at: 2026-05-14T00:00:00Z
---

"""


def _write_prd(prds_dir: Path, slug: str, body: str) -> Path:
    prds_dir.mkdir(parents=True, exist_ok=True)
    path = prds_dir / f"prd-{slug}.md"
    path.write_text(PRD_FRONTMATTER.format(slug=slug) + body)
    return path


def _write_findings(findings_dir: Path, slug: str, records: list[dict]) -> Path:
    findings_dir.mkdir(parents=True, exist_ok=True)
    path = findings_dir / f"prd-{slug}-findings.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + ("\n" if records else ""))
    return path


# ---------------------------------------------------------------------------
# Persona detection
# ---------------------------------------------------------------------------


def test_classify_personas_applied_when_section_has_answers():
    body = (
        "## Persona Review\n\n"
        "### Skeptic\n\n"
        "Q1: What is the strongest argument against?\n"
        "A1: This is a real, non-empty answer.\n"
    )
    assert has_personas_applied(body) is True


def test_classify_no_personas_when_only_commented_scaffold():
    body = (
        "<!--\n"
        "## Persona Review (optional, fill in before /prd-review)\n\n"
        "### Skeptic\n\n"
        "A1:\n"
        "A2:\n"
        "A3:\n"
        "-->\n"
    )
    assert has_personas_applied(body) is False


def test_classify_no_personas_when_section_exists_but_answers_blank():
    body = (
        "## Persona Review\n\n"
        "### Skeptic\n\n"
        "Q1: Strongest argument?\n"
        "A1:\n"
        "Q2: Smallest experiment?\n"
        "A2:\n"
        "Q3: Cheapest alternative?\n"
        "A3:\n"
    )
    assert has_personas_applied(body) is False


def test_classify_personas_applied_when_at_least_one_answer_filled():
    body = (
        "## Persona Review\n\n"
        "### Skeptic\n\n"
        "A1:\n"
        "A2: This one has an answer.\n"
        "A3:\n"
    )
    assert has_personas_applied(body) is True


# ---------------------------------------------------------------------------
# Verdict logic (per the parent PRD's kill criterion)
# ---------------------------------------------------------------------------


def _group(prd_count: int, total: int, concerning: int) -> dict:
    return {
        "prds": [f"prd-{i}" for i in range(prd_count)],
        "total_findings": total,
        "concerning_findings": concerning,
        # Synthetic split: half vague, half empty-non-goals (rounded).
        "vague_goal": concerning // 2,
        "empty_non_goals": concerning - (concerning // 2),
        "rate": concerning / total if total else 0.0,
    }


def test_verdict_kill_when_50_percent_reduction_achieved():
    """personas rate at exactly half the baseline rate -> kill."""
    no_personas = _group(3, 20, 10)  # rate = 0.5
    personas_applied = _group(3, 20, 5)  # rate = 0.25
    verdict, _ = compute_verdict(personas_applied, no_personas)
    assert verdict == "kill"


def test_verdict_kill_when_personas_rate_far_lower():
    no_personas = _group(5, 50, 20)  # rate = 0.4
    personas_applied = _group(5, 40, 4)  # rate = 0.1
    verdict, _ = compute_verdict(personas_applied, no_personas)
    assert verdict == "kill"


def test_verdict_continue_when_reduction_not_achieved():
    no_personas = _group(3, 20, 8)  # rate = 0.4
    personas_applied = _group(3, 20, 6)  # rate = 0.3, > 0.5 * 0.4 = 0.2
    verdict, _ = compute_verdict(personas_applied, no_personas)
    assert verdict == "continue"


def test_verdict_insufficient_data_when_personas_group_small():
    no_personas = _group(5, 50, 25)
    personas_applied = _group(2, 10, 1)
    verdict, _ = compute_verdict(personas_applied, no_personas)
    assert verdict == "insufficient-data"


def test_verdict_insufficient_data_when_no_personas_group_small():
    no_personas = _group(1, 10, 5)
    personas_applied = _group(5, 50, 5)
    verdict, _ = compute_verdict(personas_applied, no_personas)
    assert verdict == "insufficient-data"


# ---------------------------------------------------------------------------
# Group aggregation against a synthetic config
# ---------------------------------------------------------------------------


class _FakeConfig:
    def __init__(self, prds_dir: Path, findings_dir: Path):
        self.prds_dir = prds_dir
        self.findings_dir = findings_dir
        self.repo_root = prds_dir.parent.parent  # not used by classify_prds


def test_classify_prds_buckets_by_persona_detection(tmp_path):
    prds_dir = tmp_path / "prds"
    findings_dir = tmp_path / "findings"

    # PRD A: personas applied
    _write_prd(prds_dir, "a", "## Persona Review\n\n### Skeptic\n\nA1: yes.\n")
    _write_findings(findings_dir, "a", [
        {"id": "finding-1", "body": "Goals are vague."},
        {"id": "finding-2", "body": "Unrelated nit."},
    ])

    # PRD B: no personas
    _write_prd(prds_dir, "b", "Body without persona section.\n")
    _write_findings(findings_dir, "b", [
        {"id": "finding-1", "body": "Scope creep risk."},
        {"id": "finding-2", "body": "Non-goals section is empty."},
        {"id": "finding-3", "body": "Wording nit."},
    ])

    cfg = _FakeConfig(prds_dir, findings_dir)
    personas_applied, no_personas = classify_prds(cfg)
    assert len(personas_applied) == 1
    assert personas_applied[0]["prd_id"] == "prd-a"
    assert personas_applied[0]["vague"] == 1
    assert len(no_personas) == 1
    assert no_personas[0]["prd_id"] == "prd-b"
    assert no_personas[0]["empty_ng"] == 2


def test_classify_prds_skips_prds_without_findings_file(tmp_path):
    prds_dir = tmp_path / "prds"
    findings_dir = tmp_path / "findings"
    _write_prd(prds_dir, "no-findings", "Body.\n")
    # Do NOT create a findings file for prd-no-findings.

    cfg = _FakeConfig(prds_dir, findings_dir)
    personas_applied, no_personas = classify_prds(cfg)
    assert personas_applied == []
    assert no_personas == []


# ---------------------------------------------------------------------------
# JSON schema + run() integration
# ---------------------------------------------------------------------------


def test_run_returns_documented_json_schema(tmp_path):
    prds_dir = tmp_path / "prds"
    findings_dir = tmp_path / "findings"
    _write_prd(prds_dir, "alpha", "## Persona Review\n\n### Skeptic\n\nA1: ok.\n")
    _write_findings(findings_dir, "alpha", [{"id": "finding-1", "body": "nit"}])

    cfg = _FakeConfig(prds_dir, findings_dir)
    result = run(cfg)

    # Top-level keys
    assert set(result.keys()) == {"personas_applied", "no_personas", "verdict", "recommendation"}
    # Group schema
    for group_key in ("personas_applied", "no_personas"):
        group = result[group_key]
        assert set(group.keys()) == {
            "prds", "total_findings", "concerning_findings",
            "vague_goal", "empty_non_goals", "rate",
        }
        assert isinstance(group["prds"], list)
        assert isinstance(group["total_findings"], int)
        assert isinstance(group["concerning_findings"], int)
        assert isinstance(group["vague_goal"], int)
        assert isinstance(group["empty_non_goals"], int)
        assert isinstance(group["rate"], float)
    # Verdict + recommendation
    assert result["verdict"] in {"kill", "continue", "insufficient-data"}
    assert isinstance(result["recommendation"], str) and result["recommendation"]


def test_run_verdict_is_insufficient_data_on_single_prd(tmp_path):
    prds_dir = tmp_path / "prds"
    findings_dir = tmp_path / "findings"
    _write_prd(prds_dir, "only", "## Persona Review\n\n### Skeptic\n\nA1: yes.\n")
    _write_findings(findings_dir, "only", [{"id": "finding-1", "body": "nit"}])

    cfg = _FakeConfig(prds_dir, findings_dir)
    result = run(cfg)
    assert result["verdict"] == "insufficient-data"


# ---------------------------------------------------------------------------
# Baseline.md append
# ---------------------------------------------------------------------------


def test_format_baseline_row_includes_verdict_and_counts():
    personas_applied = _group(3, 20, 5)
    no_personas = _group(3, 20, 10)
    row = _format_baseline_row("2026-05-14", personas_applied, no_personas, "kill")
    assert "2026-05-14" in row
    assert "verdict=kill" in row
    assert "3/3 PRDs" in row
    assert row.endswith("\n")


def test_append_baseline_row_creates_file_when_missing(tmp_path):
    repo_root = tmp_path
    row = "| 2026-05-14 | measurement | 1/2 PRDs | 5 | 1+2 | verdict=kill |\n"
    append_baseline_row(repo_root, row)
    baseline = repo_root / BASELINE_DOC_RELPATH
    assert baseline.is_file()
    assert baseline.read_text() == row


def test_append_baseline_row_appends_exactly_one_row(tmp_path):
    repo_root = tmp_path
    baseline = repo_root / BASELINE_DOC_RELPATH
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text("existing content\n")

    row = "| 2026-05-14 | measurement | 1/1 PRDs | 3 | 0+0 | verdict=insufficient-data |\n"
    append_baseline_row(repo_root, row)
    contents = baseline.read_text()
    assert contents.startswith("existing content\n")
    assert contents.endswith(row)
    # Exactly one row added (count newlines)
    new_lines = contents[len("existing content\n"):].splitlines()
    assert len(new_lines) == 1


# ---------------------------------------------------------------------------
# Scoped Skeptic detection (per codex review finding)
# ---------------------------------------------------------------------------


def test_classify_no_personas_when_skeptic_subsection_missing():
    """Persona Review heading exists but ### Skeptic subsection does not."""
    body = (
        "## Persona Review\n\n"
        "Some other prose with A1: an unrelated mention.\n"
    )
    assert has_personas_applied(body) is False


def test_classify_personas_applied_with_bold_question_in_skeptic():
    """Earlier PRDs use **Q1: ...?** format inside the Skeptic subsection."""
    body = (
        "## Persona Review\n\n"
        "### Skeptic\n\n"
        "**Q1: What is the strongest argument against doing this?**\n"
        "The founder could solve this with a simple checklist instead.\n"
    )
    assert has_personas_applied(body) is True


def test_classify_no_personas_when_answer_is_outside_skeptic_subsection():
    """An A1: line in some other subsection must not trigger detection."""
    body = (
        "## Persona Review\n\n"
        "### Skeptic\n\n"
        "Q1: blah\n"
        "A1:\n"
        "A2:\n"
        "A3:\n\n"
        "### Some Other Persona\n\n"
        "A1: This is from a different persona, not Skeptic.\n"
    )
    assert has_personas_applied(body) is False
