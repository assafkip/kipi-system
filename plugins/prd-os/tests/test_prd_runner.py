"""Tests for prd_runner.py.

Covers the PRD state machine and the findings-gate check that blocks
advancement to `approved` when any finding is still `pending`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _bootstrap(repo: Path, write_config) -> None:
    write_config(
        repo,
        {
            "config_schema_version": 1,
            "prds_dir": ".prd-os/prds",
            "issues_dir": ".prd-os/issues",
            "findings_dir": ".prd-os/findings",
            "state_dir": ".claude/state",
        },
    )


def _read_state(repo: Path) -> dict:
    return json.loads((repo / ".claude/state/active-prd.json").read_text())


def _read_spec_status(repo: Path, prd_id: str) -> str:
    text = (repo / f".prd-os/prds/{prd_id}.md").read_text()
    for line in text.splitlines():
        if line.startswith("status:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("no status line in PRD spec")


# ---------------------------------------------------------------------------
# new
# ---------------------------------------------------------------------------


def test_new_creates_spec_and_state(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    r = run_prd_runner(fake_repo, "new", "widget-overhaul", "--owner", "assaf")
    assert r.returncode == 0, r.stderr
    state = _read_state(fake_repo)
    assert state["status"] == "idea"
    assert state["prd_id"].startswith("prd-widget-overhaul-")
    prd_path = fake_repo / state["spec_path"]
    assert prd_path.is_file()
    spec = prd_path.read_text()
    assert "status: idea" in spec
    assert "owner: assaf" in spec


def test_new_rejects_invalid_slug(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    r = run_prd_runner(fake_repo, "new", "Bad_Slug")
    assert r.returncode == 2
    assert "slug" in r.stderr.lower()


def test_new_refuses_when_active_prd_exists(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "first-thing").returncode == 0
    r = run_prd_runner(fake_repo, "new", "second-thing")
    assert r.returncode == 2
    assert "busy" in r.stderr.lower()


def test_new_allows_after_archive(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "first-thing").returncode == 0
    assert run_prd_runner(fake_repo, "archive").returncode == 0
    r = run_prd_runner(fake_repo, "new", "second-thing")
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------
# load / status
# ---------------------------------------------------------------------------


def test_load_hydrates_state_from_spec(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "cold-start").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]
    assert run_prd_runner(fake_repo, "clear").returncode == 0
    r = run_prd_runner(fake_repo, "load", prd_id)
    assert r.returncode == 0, r.stderr
    state = _read_state(fake_repo)
    assert state["prd_id"] == prd_id
    assert state["status"] == "idea"


def test_load_rejects_missing_spec(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    r = run_prd_runner(fake_repo, "load", "prd-does-not-exist-2026-01-01")
    assert r.returncode == 2


def test_status_reports_state(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    r = run_prd_runner(fake_repo, "status")
    assert r.returncode == 0
    assert "null" in r.stdout or "prd_id" in r.stdout


# ---------------------------------------------------------------------------
# advance transitions
# ---------------------------------------------------------------------------


def test_advance_valid_transitions(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "flow-1").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]

    r = run_prd_runner(fake_repo, "advance", "draft")
    assert r.returncode == 0, r.stderr
    assert _read_spec_status(fake_repo, prd_id) == "draft"
    assert _read_state(fake_repo)["status"] == "draft"

    r = run_prd_runner(fake_repo, "advance", "in-review")
    assert r.returncode == 0

    r = run_prd_runner(fake_repo, "advance", "draft")  # bounce back allowed
    assert r.returncode == 0


def test_advance_rejects_illegal_transition(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "jump-status").returncode == 0
    r = run_prd_runner(fake_repo, "advance", "approved")  # idea -> approved is illegal
    assert r.returncode == 2
    assert "illegal transition" in r.stderr


def test_advance_rejects_unknown_status(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "bad-status").returncode == 0
    r = run_prd_runner(fake_repo, "advance", "shipped")
    assert r.returncode == 2


def test_advance_without_active_prd(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    r = run_prd_runner(fake_repo, "advance", "draft")
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# approval gate (findings)
# ---------------------------------------------------------------------------


def _walk_to_in_review(repo, run_prd_runner):
    assert run_prd_runner(repo, "advance", "draft").returncode == 0
    assert run_prd_runner(repo, "advance", "in-review").returncode == 0


def _write_findings(repo: Path, prd_id: str, records: list[dict]) -> Path:
    path = repo / ".prd-os/findings" / f"{prd_id}-findings.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + ("\n" if records else ""))
    return path


def _stamp_reviewed(repo: Path, prd_id: str) -> None:
    """Add `codex_reviewed_at` to a PRD's frontmatter directly (test helper)."""
    spec = repo / f".prd-os/prds/{prd_id}.md"
    text = spec.read_text()
    end = text.find("\n---", 3)
    head = text[: end + 1]
    rest = text[end + 1 :]
    spec.write_text(head + "codex_reviewed_at: 2026-04-16T00:00:00Z\n" + rest)


def test_approve_blocked_when_no_codex_review_stamp(
    fake_repo, write_config, run_prd_runner
):
    """The bypass Codex flagged: no Codex review run, but advance to approved
    succeeded because the findings file was absent. Now blocked.
    """
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "never-reviewed").returncode == 0
    _walk_to_in_review(fake_repo, run_prd_runner)
    r = run_prd_runner(fake_repo, "advance", "approved")
    assert r.returncode == 2
    assert "codex_reviewed_at" in r.stderr


def test_approve_allowed_when_stamp_present_and_no_findings(
    fake_repo, write_config, run_prd_runner
):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "clean-review").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]
    _walk_to_in_review(fake_repo, run_prd_runner)
    _stamp_reviewed(fake_repo, prd_id)
    r = run_prd_runner(fake_repo, "advance", "approved")
    assert r.returncode == 0, r.stderr


def test_approve_blocked_by_pending_finding(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "has-pending").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]
    _walk_to_in_review(fake_repo, run_prd_runner)
    _stamp_reviewed(fake_repo, prd_id)
    _write_findings(
        fake_repo,
        prd_id,
        [
            {
                "id": "finding-1",
                "prd_id": prd_id,
                "source": "codex-review",
                "severity": "major",
                "disposition": "pending",
                "body": "stop-and-think",
                "created_at": "2026-04-16T00:00:00Z",
            }
        ],
    )
    r = run_prd_runner(fake_repo, "advance", "approved")
    assert r.returncode == 2
    assert "pending" in r.stderr.lower()


def test_approve_allowed_when_all_dispositioned(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "disp-ok").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]
    _walk_to_in_review(fake_repo, run_prd_runner)
    _stamp_reviewed(fake_repo, prd_id)
    _write_findings(
        fake_repo,
        prd_id,
        [
            {
                "id": "finding-1",
                "prd_id": prd_id,
                "source": "codex-review",
                "severity": "minor",
                "disposition": "accepted",
                "body": "ok",
                "created_at": "2026-04-16T00:00:00Z",
            },
            {
                "id": "finding-2",
                "prd_id": prd_id,
                "source": "manual",
                "severity": "nit",
                "disposition": "deferred",
                "rationale": "later",
                "body": "tweak wording",
                "created_at": "2026-04-16T00:00:00Z",
            },
        ],
    )
    r = run_prd_runner(fake_repo, "advance", "approved")
    assert r.returncode == 0, r.stderr


def test_approve_blocked_on_invalid_jsonl(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "broken-jsonl").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]
    _walk_to_in_review(fake_repo, run_prd_runner)
    _stamp_reviewed(fake_repo, prd_id)
    path = fake_repo / ".prd-os/findings" / f"{prd_id}-findings.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json\n")
    r = run_prd_runner(fake_repo, "advance", "approved")
    assert r.returncode == 2
    assert "invalid" in r.stderr.lower() or "jsonl" in r.stderr.lower()


# ---------------------------------------------------------------------------
# archive / clear
# ---------------------------------------------------------------------------


def test_archive_wipes_active_state(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "arch-me").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]
    r = run_prd_runner(fake_repo, "archive")
    assert r.returncode == 0, r.stderr
    assert _read_spec_status(fake_repo, prd_id) == "archived"
    state = _read_state(fake_repo)
    assert state["prd_id"] is None
    assert state["status"] is None


def test_archive_idempotent_when_already_archived(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "already-done").returncode == 0
    # advance -> archived leaves state populated (advance does not wipe).
    assert run_prd_runner(fake_repo, "advance", "archived").returncode == 0
    # Re-archiving hits the `already archived` branch and reports, does not error.
    r = run_prd_runner(fake_repo, "archive")
    assert r.returncode == 0, r.stderr
    assert "already" in r.stdout


def test_clear_wipes_state_only(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "clr-me").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]
    r = run_prd_runner(fake_repo, "clear")
    assert r.returncode == 0
    state = _read_state(fake_repo)
    assert state["prd_id"] is None
    # Spec file untouched
    assert _read_spec_status(fake_repo, prd_id) == "idea"
