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
import shutil
import subprocess
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


# ---------------------------------------------------------------------------
# ASK-3406: an accepted proposal reaches a queue, not a founder's reading pile
# ---------------------------------------------------------------------------


FLEET_SCRIPTS = Path("q-system") / ".q-system" / "scripts"
# Derived from this file, never typed: tests/ -> prd-os/ -> plugins/ -> repo root,
# the same `parents[3]` the rest of this suite's siblings use. A literal absolute
# path pinned the suite to one machine's worktree, so CI and every other checkout
# either read a tree they do not own or found nothing at all (PR #566, major).
REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_SCRIPTS = REPO_ROOT / FLEET_SCRIPTS

# VERBATIM from alert-to-linear.py:1440 (`alert-to-linear: {line}` on stdout) and
# the `filed <IDENT>` form spillover-linear-check.py:76 matches. Taken from the
# producer rather than imagined, per feedback_fixtures_from_producers.
STUB_FILER = '''#!/usr/bin/env python3
import sys, pathlib
pathlib.Path(__file__).with_name("filer-argv.txt").write_text("\\n".join(sys.argv[1:]))
# One line per invocation. A duplicate ticket is a COUNT question, and the only
# honest place to count is the sink itself: the receipt is written by the caller
# whose dedupe is under test, so asserting on rows alone would let a broken
# check certify itself (PR #566 round 2, major).
with pathlib.Path(__file__).with_name("filer-calls.txt").open("a") as fh:
    fh.write("called\\n")
print("alert-to-linear: filed ASK-9999 (owner:sana, needs-triage)")
sys.exit(0)
'''


def _filer_calls(repo: Path) -> int:
    """How many times the sink was actually executed."""
    path = repo / FLEET_SCRIPTS / "filer-calls.txt"
    if not path.is_file():
        return 0
    return len([ln for ln in path.read_text().splitlines() if ln.strip()])


def _receipt_rows(cfg) -> list[dict]:
    path = cfg.skeptic_proposals_dir / "filings.jsonl"
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _plant_fleet_filer(repo: Path) -> Path:
    """Give the fake repo the real shared reader plus a STUB sink.

    The reader (spillover-linear-check.py) is COPIED, not re-implemented: it owns
    how alert-to-linear's answer is parsed fleet-wide and resolves its sink as a
    sibling file, so a stub sibling is the whole seam needed. Only the sink is
    fake, and its stdout is copied from the real one.
    """
    scripts = repo / FLEET_SCRIPTS
    scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy(REAL_SCRIPTS / "spillover-linear-check.py",
                scripts / "spillover-linear-check.py")
    sink = scripts / "alert-to-linear.py"
    sink.write_text(STUB_FILER)
    return sink


def test_proposal_with_findings_files_one_issue_for_sana(
    fake_repo, write_config, import_config
):
    """The DoR check: archive a PRD with one missed blocker -> an issue appears.

    RED before ASK-3406: propose() wrote a markdown file and stopped, so the only
    artifact was a proposal nobody was asked to read (3 unmerged since Aug-Sep).
    """
    cfg = _load_cfg(fake_repo, write_config, import_config)
    _plant_fleet_filer(fake_repo)
    _write_prd(fake_repo / ".prd-os" / "prds", "fixture", CANONICAL_SKEPTIC_BLOCK)
    _write_findings(
        fake_repo / ".prd-os" / "findings",
        "fixture",
        [_finding("finding-1", "the success metric is too vague, not operationalized",
                  severity="blocker")],
    )

    _text, out_path = propose(cfg, "prd-fixture")

    receipts = cfg.skeptic_proposals_dir / "filings.jsonl"
    assert receipts.is_file(), "no filing receipt: the proposal reached no queue"
    rows = [json.loads(line) for line in receipts.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["prd_id"] == "prd-fixture"
    assert row["findings"] == 1
    assert row["linear"]["state"] == "filed"
    assert row["linear"]["identifier"] == "ASK-9999"

    argv = (fake_repo / FLEET_SCRIPTS / "filer-argv.txt").read_text()
    assert "prd-fixture" in argv
    assert out_path.name in argv


def test_proposal_with_no_findings_files_nothing(
    fake_repo, write_config, import_config
):
    """A round that learned nothing is not a queue item. Volume from one detector
    is a signal about the detector (automated-filer-marking.md)."""
    cfg = _load_cfg(fake_repo, write_config, import_config)
    _plant_fleet_filer(fake_repo)
    _write_prd(fake_repo / ".prd-os" / "prds", "fixture", CANONICAL_SKEPTIC_BLOCK)
    _write_findings(fake_repo / ".prd-os" / "findings", "fixture", [])

    propose(cfg, "prd-fixture")

    assert not (cfg.skeptic_proposals_dir / "filings.jsonl").exists()
    assert not (fake_repo / FLEET_SCRIPTS / "filer-argv.txt").exists()


def test_missing_fleet_filer_still_writes_the_proposal(
    fake_repo, write_config, import_config
):
    """prd-os ships to repos with no q-system tree. Archive is load-bearing; the
    filing is not. No filer -> proposal written, receipt says so, no raise."""
    cfg = _load_cfg(fake_repo, write_config, import_config)
    _write_prd(fake_repo / ".prd-os" / "prds", "fixture", CANONICAL_SKEPTIC_BLOCK)
    _write_findings(
        fake_repo / ".prd-os" / "findings",
        "fixture",
        [_finding("finding-2", "the success metric is too vague", severity="blocker")],
    )

    _text, out_path = propose(cfg, "prd-fixture")

    assert out_path.is_file()
    rows = [
        json.loads(line)
        for line in (cfg.skeptic_proposals_dir / "filings.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert rows[-1]["linear"]["state"] == "no-filer"


def test_real_fleet_sink_exists_and_refuses_under_pytest():
    """Negative self-test on the chain itself: the sink this wiring reaches is the
    REAL alert-to-linear.py, and it cannot open a live ticket from a suite.

    Without this, the three tests above prove only that a stub was called.
    """
    sink = REAL_SCRIPTS / "alert-to-linear.py"
    assert sink.is_file()
    res = subprocess.run(
        [sys.executable, str(sink), "ASK-3406 self-test, must not file"],
        capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 4, (res.returncode, res.stdout, res.stderr)
    assert "REFUSED under pytest" in res.stderr


def test_fleet_scripts_resolve_from_this_repo_not_a_machine_path():
    """RED before this commit: REAL_SCRIPTS was a literal worktree path.

    Two halves, because each catches a different thing. The equality is the
    BOUND check -- move this file and the constant moves with it -- and
    `.is_file()` is the derivation's floor, so a wrong parents[] depth fails
    loudly instead of making every check above a silent no-op
    (`derive-a-value-from-its-owner-never-restate-it-in-a-test`). The source
    scan is the tripwire against re-introducing one anywhere else in the file.
    """
    assert REAL_SCRIPTS == REPO_ROOT / FLEET_SCRIPTS
    assert (REAL_SCRIPTS / "alert-to-linear.py").is_file(), REAL_SCRIPTS
    assert (REAL_SCRIPTS / "spillover-linear-check.py").is_file(), REAL_SCRIPTS
    # Split so this assertion is not itself the hit, the way
    # test_promotion_receipt.py writes `"As" + "saf"` for the same reason.
    needle = "/Use" + "rs/"
    assert needle not in Path(__file__).read_text(), (
        "a literal home path pins this suite to one machine"
    )


# ---------------------------------------------------------------------------
# PR #566 round 2, major: a re-run must not open a second permanent ticket
# ---------------------------------------------------------------------------


def _one_blocker(repo: Path, bodies: list[str]) -> None:
    _write_findings(
        repo / ".prd-os" / "findings",
        "fixture",
        [_finding(f"finding-{i}", body, severity="blocker")
         for i, body in enumerate(bodies, start=1)],
    )


def test_identical_proposal_does_not_open_a_second_ticket(
    fake_repo, write_config, import_config
):
    """RED before this commit: two sink calls, two `filed` rows, two tickets.

    The shared sink DOES fingerprint-dedupe an identical message, measured on
    the real `alert-to-linear.fingerprint` -- but it deliberately opens a NEW
    ticket once the prior one is closed, because for an ALERT a recurrence after
    a close is the signal worth having. A proposal does not recur: Sana merges
    the anti-patterns and closes it, and a later archive of the same PRD then
    asks for work already merged. The semantics difference belongs to this
    caller, not to a sink every other producer shares.
    """
    cfg = _load_cfg(fake_repo, write_config, import_config)
    _plant_fleet_filer(fake_repo)
    _write_prd(fake_repo / ".prd-os" / "prds", "fixture", CANONICAL_SKEPTIC_BLOCK)
    _one_blocker(fake_repo, ["the success metric is too vague"])

    propose(cfg, "prd-fixture")
    propose(cfg, "prd-fixture")

    assert _filer_calls(fake_repo) == 1, "the sink ran twice: two permanent tickets"
    rows = _receipt_rows(cfg)
    assert [r["linear"]["state"] for r in rows] == ["filed", "already-filed"]
    # The skip names the ticket that already exists, so the row is still an
    # answer to "where did this proposal go" and not just an absence.
    assert rows[1]["linear"]["identifier"] == "ASK-9999"
    assert "ASK-9999" in rows[1]["linear"]["detail"]


def test_changed_findings_do_open_a_second_ticket(
    fake_repo, write_config, import_config
):
    """The dedupe must not make the detector dark on NEW content.

    RED against a prd_id-only key (measured: 1 sink call, states
    `filed, already-filed`). A proposal whose finding set grew is different
    information, and suppressing it would reproduce ASK-3406 inside its own fix.
    """
    cfg = _load_cfg(fake_repo, write_config, import_config)
    _plant_fleet_filer(fake_repo)
    _write_prd(fake_repo / ".prd-os" / "prds", "fixture", CANONICAL_SKEPTIC_BLOCK)
    _one_blocker(fake_repo, ["the success metric is too vague"])
    propose(cfg, "prd-fixture")

    _one_blocker(fake_repo, ["the success metric is too vague", "non-goals are empty"])
    propose(cfg, "prd-fixture")

    assert _filer_calls(fake_repo) == 2
    assert [r["linear"]["state"] for r in _receipt_rows(cfg)] == ["filed", "filed"]


def test_refile_reopens_the_queue_for_an_identical_proposal(
    fake_repo, write_config, import_config
):
    """The escape hatch is a flag, never a person remembering.

    Without one, an identical proposal whose ticket was closed WITHOUT the merge
    can never reach a queue again -- the ASK-113 round-2 shape, where a fix made
    a detector permanently dark after the operator did the right thing.
    """
    cfg = _load_cfg(fake_repo, write_config, import_config)
    _plant_fleet_filer(fake_repo)
    _write_prd(fake_repo / ".prd-os" / "prds", "fixture", CANONICAL_SKEPTIC_BLOCK)
    _one_blocker(fake_repo, ["the success metric is too vague"])

    propose(cfg, "prd-fixture")
    propose(cfg, "prd-fixture", refile=True)

    assert _filer_calls(fake_repo) == 2
    rows = _receipt_rows(cfg)
    assert [r["linear"]["state"] for r in rows] == ["filed", "filed"]
    assert rows[1]["refile"] is True, "a deliberate re-file is marked as one"


# ---------------------------------------------------------------------------
# PR #566 round 2, minor: absent filer and broken filer are different states
# ---------------------------------------------------------------------------


def test_broken_fleet_filer_is_not_reported_as_absent(
    fake_repo, write_config, import_config, capsys
):
    """RED before this commit: state `no-filer`, detail "no <path> in <root>".

    That detail is a false claim about a file that is sitting right there. In a
    kipi instance -- where the q-system tree ALWAYS exists -- it reads as "this
    repo has no fleet tree", which is the one state that is an ordinary no-op,
    so a broken shared reader hid inside the quiet path.
    """
    cfg = _load_cfg(fake_repo, write_config, import_config)
    scripts = fake_repo / FLEET_SCRIPTS
    scripts.mkdir(parents=True, exist_ok=True)
    # Produced by the loader's own failure, not monkeypatched: exec_module on
    # this raises SyntaxError the same way a half-synced file would.
    (scripts / "spillover-linear-check.py").write_text("def (:\n")
    _write_prd(fake_repo / ".prd-os" / "prds", "fixture", CANONICAL_SKEPTIC_BLOCK)
    _one_blocker(fake_repo, ["the success metric is too vague"])

    _text, out_path = propose(cfg, "prd-fixture")

    assert out_path.is_file()
    link = _receipt_rows(cfg)[-1]["linear"]
    assert link["state"] == "filer-broken", link
    assert "failed to import" in link["detail"], link
    assert "SyntaxError" in link["detail"], link
    # Louder than absence on purpose: a broken fleet reader is an engineering
    # signal, and it used to be indistinguishable from the ordinary no-op.
    assert "filer-broken" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# PR #566 minor: file_review_issue's "never raises" is the CLI's exit contract
# ---------------------------------------------------------------------------


def _break_the_receipt_path(cfg) -> Path:
    """Make the receipt append fail the way a real filesystem does.

    `filings.jsonl` as a directory raises IsADirectoryError from `open("a")`,
    which is an OSError reached through the same code path a read-only volume
    or a full disk would take. Produced from the writer's own call, not
    monkeypatched, per `feedback_fixtures_from_producers`.
    """
    cfg.skeptic_proposals_dir.mkdir(parents=True, exist_ok=True)
    blocker = cfg.skeptic_proposals_dir / "filings.jsonl"
    blocker.mkdir()
    return blocker


def test_receipt_io_failure_does_not_raise_through_propose(
    fake_repo, write_config, import_config, capsys
):
    """RED before this commit: IsADirectoryError escaped propose().

    The proposal was already on disk and the Linear issue may already exist, so
    a lost receipt turned a successful round into a traceback and `main()`
    exited nonzero against its documented `{"proposal_written": ...}` / exit-0
    contract.
    """
    cfg = _load_cfg(fake_repo, write_config, import_config)
    _plant_fleet_filer(fake_repo)
    _write_prd(fake_repo / ".prd-os" / "prds", "fixture", CANONICAL_SKEPTIC_BLOCK)
    _write_findings(
        fake_repo / ".prd-os" / "findings",
        "fixture",
        [_finding("finding-1", "the success metric is too vague", severity="blocker")],
    )
    _break_the_receipt_path(cfg)

    _text, out_path = propose(cfg, "prd-fixture")

    assert out_path.is_file()
    # Not silent: the one channel both callers already surface says what was
    # lost, so a receipt hole is never bought with silence
    # (coding-standards.md forbids the quiet swallow).
    assert "receipt NOT written" in capsys.readouterr().err


def test_receipt_io_failure_is_recorded_on_the_returned_link(
    fake_repo, write_config, import_config
):
    """The caller can tell receipt-landed from receipt-lost, not just no-raise."""
    from propose_skeptic_antipatterns import file_review_issue

    cfg = _load_cfg(fake_repo, write_config, import_config)
    _plant_fleet_filer(fake_repo)
    _break_the_receipt_path(cfg)
    findings = [_finding("finding-1", "the success metric is too vague",
                         severity="blocker")]

    link = file_review_issue(
        cfg, "prd-fixture", cfg.skeptic_proposals_dir / "prd-fixture-proposal.md",
        findings,
    )

    assert link is not None
    assert link["state"] == "filed", link
    assert link["receipt"] == "failed", link
    assert "IsADirectoryError" in link["receipt_detail"]


def test_receipt_success_is_stated_not_inferred_from_absence(
    fake_repo, write_config, import_config
):
    """A key present only on failure makes `None` mean two things at once."""
    from propose_skeptic_antipatterns import file_review_issue

    cfg = _load_cfg(fake_repo, write_config, import_config)
    _plant_fleet_filer(fake_repo)
    findings = [_finding("finding-1", "the success metric is too vague",
                         severity="blocker")]

    link = file_review_issue(
        cfg, "prd-fixture", cfg.skeptic_proposals_dir / "prd-fixture-proposal.md",
        findings,
    )

    assert link["receipt"] == "written"
    # The on-disk row keeps the filer's answer only: the receipt's own state is
    # not a fact the receipt can report about itself.
    rows = [json.loads(line)
            for line in (cfg.skeptic_proposals_dir / "filings.jsonl").read_text().splitlines()
            if line.strip()]
    assert "receipt" not in rows[-1]["linear"]
