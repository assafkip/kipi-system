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
# duplicate `## Issues` heading gate
# ---------------------------------------------------------------------------


def test_advance_blocks_when_body_has_duplicate_issues_heading(
    fake_repo, write_config, run_prd_runner
):
    """Drafting artifact: author adds a second `## Issues` block while filling
    Problem/Goals/etc., on top of the template's pre-existing one. The dup
    causes downstream `re.search` parsing to pick the wrong block silently.
    Reject deterministically at advance time.
    """
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "dup-issues-block").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]
    spec_path = fake_repo / f".prd-os/prds/{prd_id}.md"
    spec_path.write_text(
        spec_path.read_text() + "\n## Issues\n\n```json\n[]\n```\n"
    )

    r = run_prd_runner(fake_repo, "advance", "draft")
    assert r.returncode == 2
    assert "## Issues" in r.stderr
    assert "duplicate" in r.stderr.lower() or "2 " in r.stderr


def test_advance_passes_with_single_issues_heading(
    fake_repo, write_config, run_prd_runner
):
    """Sanity: the template's single `## Issues` heading does not trip the gate."""
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "single-issues-block").returncode == 0
    r = run_prd_runner(fake_repo, "advance", "draft")
    assert r.returncode == 0, r.stderr


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


def _write_manifest(repo: Path, prd_id: str, entries: list[dict]) -> None:
    """Replace the template's empty `[]` manifest with a real one."""
    spec = repo / f".prd-os/prds/{prd_id}.md"
    text = spec.read_text()
    payload = json.dumps(entries, indent=2)
    if "```json\n[]\n```" in text:
        spec.write_text(text.replace("```json\n[]\n```", f"```json\n{payload}\n```"))
        return
    # Template shape changed; append a fresh manifest section at the end.
    spec.write_text(text + f"\n## Issues\n\n```json\n{payload}\n```\n")


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
    _write_manifest(
        fake_repo,
        prd_id,
        [
            {
                "id": "issue-1",
                "title": "fix 1",
                "finding_id": "finding-1",
                "allowed_files": ["src/a.py"],
                "required_checks": ["pytest"],
                "bypass_exempt": "test fixture",
            }
        ],
    )
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


# ---------------------------------------------------------------------------
# archive: manifest-status gate (G6)
#
# Closes the failure mode observed 2026-05-04 in the warming-ladder PRD: a
# parent PRD archived with 5 issues at status: open. _archive_coverage_gate
# only checks accepted findings, so a PRD with rejected/deferred-only findings
# could archive with every manifest issue still open. The new gate walks the
# `## Issues` manifest and requires every entry's spec to be `status: closed`.
# ---------------------------------------------------------------------------


def _append_issues_manifest(repo: Path, prd_id: str, entries: list[dict]) -> None:
    """Replace the PRD template's empty `## Issues` JSON block with entries.

    The PRD template ships with a `## Issues` section containing an empty
    fenced `[]` array. Tests need to populate it; appending a second `## Issues`
    section would not be picked up because the gate finds the first match.
    """
    import re as _re

    spec_path = repo / f".prd-os/prds/{prd_id}.md"
    text = spec_path.read_text()
    block = json.dumps(entries, indent=2)
    new_text = _re.sub(
        r"(?ms)(##\s+Issues\b.*?```(?:json)?\s*\n)(.*?)(\n```)",
        lambda m: m.group(1) + block + m.group(3),
        text,
        count=1,
    )
    if new_text == text:
        new_text = text + f"\n## Issues\n\n```json\n{block}\n```\n"
    spec_path.write_text(new_text)


def test_archive_blocks_when_manifest_issue_is_open(
    fake_repo, write_config, run_prd_runner, write_issue_spec
):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "still-open").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]
    write_issue_spec(
        fake_repo / ".prd-os/issues",
        "still-open-issue-1",
        status="open",
        allowed_files=["foo.py"],
    )
    _append_issues_manifest(
        fake_repo,
        prd_id,
        [
            {
                "id": "still-open-issue-1",
                "title": "Open issue blocks archive",
                "finding_id": "finding-1",
                "allowed_files": ["foo.py"],
                "required_checks": ["pytest -q"],
                "bypass_exempt": "test fixture",
            }
        ],
    )
    r = run_prd_runner(fake_repo, "archive")
    assert r.returncode == 2, r.stdout
    assert "still-open-issue-1" in r.stderr
    assert "status=open" in r.stderr


def test_archive_passes_when_all_manifest_issues_closed(
    fake_repo, write_config, run_prd_runner, write_issue_spec
):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "all-closed").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]
    write_issue_spec(
        fake_repo / ".prd-os/issues",
        "all-closed-issue-1",
        status="closed",
        allowed_files=["bar.py"],
    )
    write_issue_spec(
        fake_repo / ".prd-os/issues",
        "all-closed-issue-2",
        status="closed",
        allowed_files=["baz.py"],
    )
    _append_issues_manifest(
        fake_repo,
        prd_id,
        [
            {
                "id": "all-closed-issue-1",
                "title": "First",
                "finding_id": "finding-1",
                "allowed_files": ["bar.py"],
                "required_checks": ["pytest -q"],
                "bypass_exempt": "test fixture",
            },
            {
                "id": "all-closed-issue-2",
                "title": "Second",
                "finding_id": "finding-2",
                "allowed_files": ["baz.py"],
                "required_checks": ["pytest -q"],
                "bypass_exempt": "test fixture",
            },
        ],
    )
    # closed status must be receipt-backed now (hand-edited closes bypass
    # the spine contract) — write the legitimate close receipts.
    import json as _json
    receipts = fake_repo / ".prd-os" / "receipts.jsonl"
    receipts.parent.mkdir(parents=True, exist_ok=True)
    with receipts.open("a") as fh:
        for iid in ("all-closed-issue-1", "all-closed-issue-2"):
            fh.write(_json.dumps({
                "issue_id": iid, "prd_id": prd_id,
                "finding_id": "finding-1",
                "closed_at": "2026-01-01T00:00:00Z"}) + "\n")
    r = run_prd_runner(fake_repo, "archive")
    assert r.returncode == 0, r.stderr
    assert _read_spec_status(fake_repo, prd_id) == "archived"


def test_archive_blocks_when_manifest_issue_spec_missing(
    fake_repo, write_config, run_prd_runner
):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "phantom").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]
    _append_issues_manifest(
        fake_repo,
        prd_id,
        [
            {
                "id": "phantom-issue-not-on-disk",
                "title": "Phantom",
                "finding_id": "finding-1",
                "allowed_files": ["x.py"],
                "required_checks": ["pytest -q"],
                "bypass_exempt": "test fixture",
            }
        ],
    )
    r = run_prd_runner(fake_repo, "archive")
    assert r.returncode == 2
    assert "phantom-issue-not-on-disk" in r.stderr
    assert "do not exist on disk" in r.stderr


def test_archive_passes_when_prd_has_no_issues_section(
    fake_repo, write_config, run_prd_runner
):
    """Legacy / content-only PRDs without a ## Issues manifest are passed through."""
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "content-only").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]
    # No manifest appended.
    r = run_prd_runner(fake_repo, "archive")
    assert r.returncode == 0, r.stderr
    assert _read_spec_status(fake_repo, prd_id) == "archived"


def test_advance_archived_also_runs_manifest_gate(
    fake_repo, write_config, run_prd_runner, write_issue_spec
):
    """`advance archived` (not just `archive`) must run the manifest-status gate."""
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "via-advance").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]
    write_issue_spec(
        fake_repo / ".prd-os/issues",
        "via-advance-issue-1",
        status="open",
        allowed_files=["a.py"],
    )
    _append_issues_manifest(
        fake_repo,
        prd_id,
        [
            {
                "id": "via-advance-issue-1",
                "title": "Open issue",
                "finding_id": "finding-1",
                "allowed_files": ["a.py"],
                "required_checks": ["pytest -q"],
                "bypass_exempt": "test fixture",
            }
        ],
    )
    r = run_prd_runner(fake_repo, "advance", "archived")
    assert r.returncode == 2
    assert "via-advance-issue-1" in r.stderr


def test_approve_blocked_without_bypass_check_or_exempt(fake_repo, write_config, run_prd_runner):
    """Spine contract: an entry with neither bypass_check nor bypass_exempt
    cannot approve; adding either unblocks."""
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "contract-x").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]
    _walk_to_in_review(fake_repo, run_prd_runner)
    _stamp_reviewed(fake_repo, prd_id)
    entry = {"id": "i1", "title": "t", "finding_id": "finding-1",
             "allowed_files": ["a.py"], "required_checks": ["pytest"]}
    _write_manifest(fake_repo, prd_id, [entry])
    _write_findings(fake_repo, prd_id, [{
        "id": "finding-1", "prd_id": prd_id, "source": "codex-review",
        "severity": "minor", "disposition": "accepted", "body": "ok",
        "created_at": "2026-04-16T00:00:00Z"}])
    r = run_prd_runner(fake_repo, "advance", "approved")
    assert r.returncode == 2
    assert "bypass_check" in r.stderr and "bypass_exempt" in r.stderr

    # unblock by editing the SAME manifest in place (a second _write_manifest
    # would append a duplicate ## Issues heading and trip the dedup gate):
    # parse the fenced JSON, add bypass_check, re-dump — serializer-agnostic.
    import re as _re
    spec = fake_repo / ".prd-os" / "prds" / f"{prd_id}.md"
    text = spec.read_text()
    m = _re.search(r"```json\n(.*?)```", text, _re.S)
    manifest = json.loads(m.group(1))
    manifest[0]["bypass_check"] = "pytest tests/test_no_bypass.py"
    text = text[:m.start(1)] + json.dumps(manifest, indent=2) + "\n" + text[m.end(1):]
    spec.write_text(text)
    r = run_prd_runner(fake_repo, "advance", "approved")
    assert r.returncode == 0, r.stderr


def test_umbrella_kind_approves_empty_and_archives_on_real_coverage(
        fake_repo, write_config, run_prd_runner):
    """kind: umbrella — empty manifest approves when accepted findings carry
    covered_by; archive verifies coverage targets exist and are past idea."""
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "umb").returncode == 0
    prd_id = _read_state(fake_repo)["prd_id"]
    spec = fake_repo / ".prd-os" / "prds" / f"{prd_id}.md"
    spec.write_text(spec.read_text().replace(
        f"id: {prd_id}", f"id: {prd_id}\nkind: umbrella", 1))
    _walk_to_in_review(fake_repo, run_prd_runner)
    _stamp_reviewed(fake_repo, prd_id)
    _write_findings(fake_repo, prd_id, [{
        "id": "finding-1", "prd_id": prd_id, "source": "codex-review",
        "severity": "major", "disposition": "accepted", "body": "phase work",
        "created_at": "2026-04-16T00:00:00Z",
        "covered_by": "prd-missing-phase-2099-01-01"}])
    r = run_prd_runner(fake_repo, "advance", "approved")
    assert r.returncode == 0, r.stderr  # approval: coverage NAMED is enough
    # archive: the named coverage must EXIST and be past idea
    r = run_prd_runner(fake_repo, "archive")
    assert r.returncode == 2
    assert "covered_by" in r.stderr
    phase = fake_repo / ".prd-os" / "prds" / "prd-missing-phase-2099-01-01.md"
    phase.write_text("---\nid: prd-missing-phase-2099-01-01\nstatus: draft\n---\n# p\n")
    r = run_prd_runner(fake_repo, "archive")
    assert r.returncode == 0, r.stderr


def test_depends_on_blocks_activation_on_red_gate(
        fake_repo, write_config, run_prd_runner):
    """Phase gating: a PRD depending on another cannot LOAD while that
    dependency has a RED registered gate; green unblocks."""
    import json as _json
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "phase-one").returncode == 0
    dep_id = _read_state(fake_repo)["prd_id"]
    assert run_prd_runner(fake_repo, "clear").returncode == 0
    assert run_prd_runner(fake_repo, "new", "phase-two").returncode == 0
    two_id = _read_state(fake_repo)["prd_id"]
    assert run_prd_runner(fake_repo, "clear").returncode == 0
    spec2 = fake_repo / ".prd-os" / "prds" / f"{two_id}.md"
    spec2.write_text(spec2.read_text().replace(
        f"id: {two_id}", f"id: {two_id}\ndepends_on: {dep_id}", 1))
    gates = fake_repo / ".prd-os" / "gates.jsonl"
    gates.parent.mkdir(parents=True, exist_ok=True)
    gates.write_text(_json.dumps({
        "gate_id": "g-red", "prd_id": dep_id, "issue_id": "i",
        "command": "false", "lifecycle": "regression",
        "registered_at": "2026-01-01T00:00:00Z"}) + "\n")
    r = run_prd_runner(fake_repo, "load", two_id)
    assert r.returncode == 2
    assert "RED gate" in r.stderr
    gates.write_text(_json.dumps({
        "gate_id": "g-green", "prd_id": dep_id, "issue_id": "i",
        "command": "true", "lifecycle": "regression",
        "registered_at": "2026-01-01T00:00:00Z"}) + "\n")
    r = run_prd_runner(fake_repo, "load", two_id)
    assert r.returncode == 0, r.stderr
