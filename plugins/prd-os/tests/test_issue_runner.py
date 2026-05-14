"""End-to-end tests for the portable issue_runner.

All tests use an ephemeral repo under tmp_path, so they do not touch the host
repo's live `.claude/state/` or live issue specs. The pre-plugin runner at
q-ktlyst/.q-system/scripts/issue-runner.py remains untouched; this file
verifies that the port preserves the established contract and that paths
route through the config module.

Covers:
  - missing config in strict mode errors out
  - load -> status round-trip reflects the loaded spec
  - planning (open) does not arm the gate; approve does
  - approve flips open -> in-progress and resets stale receipts
  - approve is idempotent on in-progress
  - approve refuses when status is closed or unknown
  - scope empty allowed_files denies arbitrary paths, permits the spec
  - scope non-empty allowed_files allows matches, blocks non-matches
  - disallowed takes precedence over allowed
  - control_plane_files from config carve out scope for non-spec paths
  - gate passes with full receipts, fails with missing receipts
  - ISSUE_GATE_OFF bypasses the gate
  - close requires receipts; clear wipes state
  - ktlyst-compat: a config that names q-ktlyst paths exercises the runner
    end-to-end against those paths in an ephemeral repo
"""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_CONFIG = {"config_schema_version": 1}
KTLYST_CONFIG = {
    "config_schema_version": 1,
    "issues_dir": "q-ktlyst/.q-system/issues",
    "state_dir": ".claude/state",
}


def _load_state(repo: Path) -> dict:
    return json.loads((repo / ".claude" / "state" / "active-issue.json").read_text())


# ---------------------------------------------------------------------------
# Config wiring
# ---------------------------------------------------------------------------


def test_runner_errors_without_config(run_runner, fake_repo):
    result = run_runner(fake_repo, "status")
    assert result.returncode == 2
    assert "config" in result.stderr.lower()


def test_load_writes_state_under_configured_state_dir(
    run_runner, fake_repo, write_config, write_issue_spec
):
    write_config(fake_repo, DEFAULT_CONFIG)
    issues_dir = fake_repo / ".prd-os" / "issues"
    write_issue_spec(issues_dir, "issue-0-demo", allowed_files=["src/**"])
    result = run_runner(fake_repo, "load", "issue-0-demo")
    assert result.returncode == 0, result.stderr
    state = _load_state(fake_repo)
    assert state["issue_id"] == "issue-0-demo"
    assert state["spec_path"] == ".prd-os/issues/issue-0-demo.md"
    assert all(v is None for v in state["receipts"].values())


# ---------------------------------------------------------------------------
# Planning vs execution gate
# ---------------------------------------------------------------------------


def test_planning_does_not_arm_gate(run_runner, fake_repo, write_config, write_issue_spec):
    write_config(fake_repo, DEFAULT_CONFIG)
    write_issue_spec(fake_repo / ".prd-os" / "issues", "issue-plan", allowed_files=["src/**"])
    assert run_runner(fake_repo, "load", "issue-plan").returncode == 0
    gate = run_runner(fake_repo, "gate")
    assert gate.returncode == 0, gate.stderr


def test_approve_flips_status_and_arms_gate(run_runner, fake_repo, write_config, write_issue_spec):
    write_config(fake_repo, DEFAULT_CONFIG)
    spec = write_issue_spec(fake_repo / ".prd-os" / "issues", "issue-approve", allowed_files=["src/**"])
    run_runner(fake_repo, "load", "issue-approve")
    result = run_runner(fake_repo, "approve")
    assert result.returncode == 0, result.stderr
    # Spec file should now carry in-progress.
    assert "status: in-progress" in spec.read_text()
    # Gate refuses stop while no receipts exist.
    gate = run_runner(fake_repo, "gate")
    assert gate.returncode == 2
    assert "missing receipts" in gate.stderr


def test_approve_is_idempotent(run_runner, fake_repo, write_config, write_issue_spec):
    write_config(fake_repo, DEFAULT_CONFIG)
    write_issue_spec(fake_repo / ".prd-os" / "issues", "issue-idem", allowed_files=["src/**"])
    run_runner(fake_repo, "load", "issue-idem")
    assert run_runner(fake_repo, "approve").returncode == 0
    second = run_runner(fake_repo, "approve")
    assert second.returncode == 0
    payload = json.loads(second.stdout.strip().splitlines()[-1])
    assert payload["status"] == "in-progress"
    assert payload.get("note") == "already"


def test_approve_refuses_when_status_closed(run_runner, fake_repo, write_config, write_issue_spec):
    write_config(fake_repo, DEFAULT_CONFIG)
    write_issue_spec(
        fake_repo / ".prd-os" / "issues",
        "issue-closed",
        status="closed",
        allowed_files=["src/**"],
    )
    run_runner(fake_repo, "load", "issue-closed")
    result = run_runner(fake_repo, "approve")
    assert result.returncode == 2
    assert "expected 'open'" in result.stderr


def test_approve_resets_stale_receipts(run_runner, fake_repo, write_config, write_issue_spec):
    write_config(fake_repo, DEFAULT_CONFIG)
    spec = write_issue_spec(fake_repo / ".prd-os" / "issues", "issue-reset", allowed_files=["src/**"])
    run_runner(fake_repo, "load", "issue-reset")
    run_runner(fake_repo, "approve")
    for receipt in ("verified", "reviewed", "findings_triaged"):
        assert run_runner(fake_repo, "mark", receipt).returncode == 0
    # Simulate a manual revert in-progress -> open.
    spec.write_text(spec.read_text().replace("status: in-progress", "status: open"))
    run_runner(fake_repo, "approve")
    state = _load_state(fake_repo)
    assert state["receipts"] == {
        "verified": None,
        "reviewed": None,
        "findings_triaged": None,
    }


# ---------------------------------------------------------------------------
# Scope enforcement
# ---------------------------------------------------------------------------


def test_scope_no_active_issue_allows_anything(run_runner, fake_repo, write_config):
    write_config(fake_repo, DEFAULT_CONFIG)
    result = run_runner(fake_repo, "scope", "anything/at/all.py")
    assert result.returncode == 0


def test_scope_empty_allowed_files_denies(run_runner, fake_repo, write_config, write_issue_spec):
    write_config(fake_repo, DEFAULT_CONFIG)
    write_issue_spec(fake_repo / ".prd-os" / "issues", "issue-empty", allowed_files=[])
    run_runner(fake_repo, "load", "issue-empty")
    result = run_runner(fake_repo, "scope", "src/foo.py")
    assert result.returncode == 2
    assert "allowed_files is empty" in result.stderr


def test_scope_empty_allowed_files_still_permits_spec(
    run_runner, fake_repo, write_config, write_issue_spec
):
    write_config(fake_repo, DEFAULT_CONFIG)
    spec = write_issue_spec(
        fake_repo / ".prd-os" / "issues", "issue-spec-only", allowed_files=[]
    )
    run_runner(fake_repo, "load", "issue-spec-only")
    spec_rel = str(spec.relative_to(fake_repo))
    result = run_runner(fake_repo, "scope", spec_rel)
    assert result.returncode == 0, result.stderr


def test_scope_allowed_files_match_allows(run_runner, fake_repo, write_config, write_issue_spec):
    write_config(fake_repo, DEFAULT_CONFIG)
    write_issue_spec(fake_repo / ".prd-os" / "issues", "issue-allow", allowed_files=["src/**"])
    run_runner(fake_repo, "load", "issue-allow")
    result = run_runner(fake_repo, "scope", "src/foo/bar.py")
    assert result.returncode == 0, result.stderr


def test_scope_unmatched_path_blocked(run_runner, fake_repo, write_config, write_issue_spec):
    write_config(fake_repo, DEFAULT_CONFIG)
    write_issue_spec(fake_repo / ".prd-os" / "issues", "issue-block", allowed_files=["src/**"])
    run_runner(fake_repo, "load", "issue-block")
    result = run_runner(fake_repo, "scope", "other/file.py")
    assert result.returncode == 2
    assert "not in allowed_files" in result.stderr


def test_scope_disallowed_precedence(run_runner, fake_repo, write_config, write_issue_spec):
    write_config(fake_repo, DEFAULT_CONFIG)
    write_issue_spec(
        fake_repo / ".prd-os" / "issues",
        "issue-deny-priority",
        allowed_files=["src/**"],
        disallowed_files=["src/secret.py"],
    )
    run_runner(fake_repo, "load", "issue-deny-priority")
    result = run_runner(fake_repo, "scope", "src/secret.py")
    assert result.returncode == 2
    assert "matched disallowed" in result.stderr


def test_config_control_plane_files_whitelist_paths(
    run_runner, fake_repo, write_config, write_issue_spec
):
    """control_plane_files from config must carve out scope even when
    allowed_files is empty and the target is not the active spec."""
    write_config(fake_repo, {
        "config_schema_version": 1,
        "control_plane_files": ["ops/cluster-map.md"],
    })
    write_issue_spec(fake_repo / ".prd-os" / "issues", "issue-cp", allowed_files=[])
    run_runner(fake_repo, "load", "issue-cp")
    result = run_runner(fake_repo, "scope", "ops/cluster-map.md")
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Stop gate semantics
# ---------------------------------------------------------------------------


def test_gate_passes_with_full_receipts(run_runner, fake_repo, write_config, write_issue_spec):
    write_config(fake_repo, DEFAULT_CONFIG)
    write_issue_spec(fake_repo / ".prd-os" / "issues", "issue-gate-ok", allowed_files=["src/**"])
    run_runner(fake_repo, "load", "issue-gate-ok")
    run_runner(fake_repo, "approve")
    for r in ("verified", "reviewed", "findings_triaged"):
        run_runner(fake_repo, "mark", r)
    assert run_runner(fake_repo, "gate").returncode == 0


def test_gate_off_env_bypasses(run_runner, fake_repo, write_config, write_issue_spec):
    write_config(fake_repo, DEFAULT_CONFIG)
    write_issue_spec(fake_repo / ".prd-os" / "issues", "issue-gateoff", allowed_files=["src/**"])
    run_runner(fake_repo, "load", "issue-gateoff")
    run_runner(fake_repo, "approve")
    result = run_runner(fake_repo, "gate", env_extra={"ISSUE_GATE_OFF": "1"})
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Close + clear
# ---------------------------------------------------------------------------


def test_close_requires_all_receipts(run_runner, fake_repo, write_config, write_issue_spec):
    write_config(fake_repo, DEFAULT_CONFIG)
    write_issue_spec(fake_repo / ".prd-os" / "issues", "issue-close-missing", allowed_files=["src/**"])
    run_runner(fake_repo, "load", "issue-close-missing")
    run_runner(fake_repo, "approve")
    result = run_runner(fake_repo, "close")
    assert result.returncode == 2
    assert "missing receipts" in result.stderr


def test_close_flips_status_and_clears_state(
    run_runner, fake_repo, write_config, write_issue_spec
):
    write_config(fake_repo, DEFAULT_CONFIG)
    spec = write_issue_spec(fake_repo / ".prd-os" / "issues", "issue-close-ok", allowed_files=["src/**"])
    run_runner(fake_repo, "load", "issue-close-ok")
    run_runner(fake_repo, "approve")
    for r in ("verified", "reviewed", "findings_triaged"):
        run_runner(fake_repo, "mark", r)
    result = run_runner(fake_repo, "close")
    assert result.returncode == 0, result.stderr
    assert "status: closed" in spec.read_text()
    state = _load_state(fake_repo)
    assert state["issue_id"] is None


def test_clear_wipes_state(run_runner, fake_repo, write_config, write_issue_spec):
    write_config(fake_repo, DEFAULT_CONFIG)
    write_issue_spec(fake_repo / ".prd-os" / "issues", "issue-clr", allowed_files=["src/**"])
    run_runner(fake_repo, "load", "issue-clr")
    result = run_runner(fake_repo, "clear")
    assert result.returncode == 0
    state = _load_state(fake_repo)
    assert state["issue_id"] is None


# ---------------------------------------------------------------------------
# ktlyst compatibility
# ---------------------------------------------------------------------------


def test_ktlyst_paths_drive_runner(run_runner, fake_repo, write_config, write_issue_spec):
    """A config pointing at `q-ktlyst/.q-system/issues` must route the runner
    against those paths without any code change. This is the migration path
    for the ktlyst repo: keep existing specs in place, install the plugin,
    set the config, and the portable runner operates on the live layout."""
    write_config(fake_repo, KTLYST_CONFIG)
    ktlyst_issues = fake_repo / "q-ktlyst" / ".q-system" / "issues"
    # Note: using `src/*` (not `src/**`) — the inherited _match() helper treats
    # `src/**` as "nested children only" and does not match direct files like
    # `src/foo.py`. See step-3 report for the contract-port note.
    spec = write_issue_spec(ktlyst_issues, "issue-ktlyst-compat", allowed_files=["src/*"])
    load = run_runner(fake_repo, "load", "issue-ktlyst-compat")
    assert load.returncode == 0, load.stderr
    payload = json.loads(load.stdout)
    assert payload["spec_path"] == "q-ktlyst/.q-system/issues/issue-ktlyst-compat.md"
    # End-to-end: approve, scope-check against allowed path, mark receipts, close.
    assert run_runner(fake_repo, "approve").returncode == 0
    assert run_runner(fake_repo, "scope", "src/foo.py").returncode == 0
    for r in ("verified", "reviewed", "findings_triaged"):
        run_runner(fake_repo, "mark", r)
    assert run_runner(fake_repo, "close").returncode == 0
    assert "status: closed" in spec.read_text()


# ---------------------------------------------------------------------------
# Receipt writing on close (PRD: prd-os-receipts-and-phase0-measure)
# ---------------------------------------------------------------------------


def _mark_all_receipts(run_runner, fake_repo):
    for receipt in ("verified", "reviewed", "findings_triaged"):
        result = run_runner(fake_repo, "mark", receipt)
        assert result.returncode == 0, result.stderr


def test_close_writes_receipt_to_receipts_jsonl(
    run_runner, fake_repo, write_config, write_issue_spec
):
    """Happy path: close emits a receipt record with required fields."""
    write_config(fake_repo, DEFAULT_CONFIG)
    write_issue_spec(
        fake_repo / ".prd-os" / "issues",
        "issue-emit-receipt",
        allowed_files=["src/**"],
    )
    run_runner(fake_repo, "load", "issue-emit-receipt")
    run_runner(fake_repo, "approve")
    _mark_all_receipts(run_runner, fake_repo)
    result = run_runner(fake_repo, "close")
    assert result.returncode == 0, result.stderr

    receipts_path = fake_repo / ".prd-os" / "receipts.jsonl"
    assert receipts_path.is_file(), "receipts.jsonl was not created"
    lines = [
        json.loads(line)
        for line in receipts_path.read_text().splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    record = lines[0]
    # Required fields per prd_runner._load_receipts_for_prd
    assert record["prd_id"] == "prd-fixture"
    assert record["finding_id"] == "finding-fixture"
    # Audit fields kept for traceability
    assert record["issue_id"] == "issue-emit-receipt"
    assert "closed_at" in record
    assert set(record["receipts"].keys()) == {"verified", "reviewed", "findings_triaged"}


def test_close_creates_receipts_path_parents(
    run_runner, fake_repo, write_config, write_issue_spec
):
    """If the receipts file's parent directory does not exist, close creates it."""
    config = {
        "config_schema_version": 1,
        "receipts_path": "nested/dir/that/does/not/exist/receipts.jsonl",
    }
    write_config(fake_repo, config)
    write_issue_spec(
        fake_repo / ".prd-os" / "issues",
        "issue-parents",
        allowed_files=["src/**"],
    )
    run_runner(fake_repo, "load", "issue-parents")
    run_runner(fake_repo, "approve")
    _mark_all_receipts(run_runner, fake_repo)
    result = run_runner(fake_repo, "close")
    assert result.returncode == 0, result.stderr
    receipts_path = fake_repo / "nested" / "dir" / "that" / "does" / "not" / "exist" / "receipts.jsonl"
    assert receipts_path.is_file()


def test_close_warns_when_marker_missing(
    run_runner, fake_repo, write_config
):
    """A spec without the prd_split marker still closes; warning on stderr."""
    write_config(fake_repo, DEFAULT_CONFIG)
    issues_dir = fake_repo / ".prd-os" / "issues"
    issues_dir.mkdir(parents=True)
    spec_no_marker = issues_dir / "issue-no-marker.md"
    spec_no_marker.write_text(
        "---\n"
        "id: issue-no-marker\n"
        "title: no marker fixture\n"
        "status: open\n"
        "priority: p0\n"
        "allowed_files: []\n"
        "disallowed_files: []\n"
        "required_checks: []\n"
        "required_reviews: []\n"
        "---\n\n"
        "No prd_split marker in this body.\n"
    )
    run_runner(fake_repo, "load", "issue-no-marker")
    run_runner(fake_repo, "approve")
    _mark_all_receipts(run_runner, fake_repo)
    result = run_runner(fake_repo, "close")
    assert result.returncode == 0, result.stderr
    assert "no prd_split marker" in result.stderr.lower()
    # Spec still closed.
    assert "status: closed" in spec_no_marker.read_text()
    # No receipt written.
    receipts_path = fake_repo / ".prd-os" / "receipts.jsonl"
    if receipts_path.is_file():
        assert receipts_path.read_text().strip() == ""


def test_close_is_idempotent_on_duplicate_pair(
    run_runner, fake_repo, write_config, write_issue_spec
):
    """Closing two issues that share (prd_id, finding_id) writes only one receipt.

    This guards against duplicate close attempts (retries, manual reruns) bloating
    the receipts file. The reader already dedupes via set semantics, so the
    behavior is idempotent end-to-end.
    """
    write_config(fake_repo, DEFAULT_CONFIG)
    # Both issues use the same default fixture marker (prd-fixture / finding-fixture).
    write_issue_spec(
        fake_repo / ".prd-os" / "issues",
        "issue-dup-one",
        allowed_files=["src/**"],
    )
    write_issue_spec(
        fake_repo / ".prd-os" / "issues",
        "issue-dup-two",
        allowed_files=["src/**"],
    )

    for issue_id in ("issue-dup-one", "issue-dup-two"):
        run_runner(fake_repo, "load", issue_id)
        run_runner(fake_repo, "approve")
        _mark_all_receipts(run_runner, fake_repo)
        run_runner(fake_repo, "close")

    receipts_path = fake_repo / ".prd-os" / "receipts.jsonl"
    lines = [
        line for line in receipts_path.read_text().splitlines() if line.strip()
    ]
    assert len(lines) == 1, f"expected one record, got {len(lines)}"


def test_close_unblocks_prd_archive_end_to_end(
    run_runner, run_prd_runner, run_prd_split, run_findings_writer,
    fake_repo, write_config,
):
    """End-to-end: close writes a receipt that prd_runner.archive accepts.

    This is the regression test for the bug that motivated this PRD. Previously
    /prd-archive blocked because no receipts.jsonl writer existed.
    """
    write_config(fake_repo, DEFAULT_CONFIG)
    # Author a PRD with one accepted finding and a manifest pointing to it.
    prd_path = fake_repo / ".prd-os" / "prds" / "prd-e2e-2026-05-14.md"
    prd_path.parent.mkdir(parents=True)
    prd_path.write_text(
        "---\n"
        "id: prd-e2e-2026-05-14\n"
        "title: end-to-end fixture\n"
        "status: approved\n"
        "codex_reviewed_at: 2026-05-14T00:00:00Z\n"
        "---\n\n"
        "## Issues\n\n"
        "```json\n"
        "[\n"
        '  {"id": "e2e-issue-one", "title": "the single issue",\n'
        '   "finding_id": "finding-1", "allowed_files": ["src/foo.py"],\n'
        '   "required_checks": ["true"]}\n'
        "]\n"
        "```\n"
    )
    # Author the accepted finding so the archive gate has something to match.
    findings_dir = fake_repo / ".prd-os" / "findings"
    findings_dir.mkdir(parents=True)
    (findings_dir / "prd-e2e-2026-05-14-findings.jsonl").write_text(
        json.dumps({
            "id": "finding-1",
            "severity": "major",
            "body": "fixture",
            "disposition": "accepted",
            "created_at": "2026-05-14T00:00:00Z",
            "resolved_at": "2026-05-14T00:00:00Z",
            "source": "codex-review",
        }) + "\n"
    )
    # Split the PRD into the single issue spec (this injects the marker).
    split_result = run_prd_split(fake_repo, "--prd-id", "prd-e2e-2026-05-14")
    assert split_result.returncode == 0, split_result.stderr

    # Run the full issue lifecycle on the single issue.
    assert run_runner(fake_repo, "load", "e2e-issue-one").returncode == 0
    assert run_runner(fake_repo, "approve").returncode == 0
    for r in ("verified", "reviewed", "findings_triaged"):
        assert run_runner(fake_repo, "mark", r).returncode == 0
    close_result = run_runner(fake_repo, "close")
    assert close_result.returncode == 0, close_result.stderr

    # The receipts file now exists and carries the expected pair.
    receipts_path = fake_repo / ".prd-os" / "receipts.jsonl"
    receipt = json.loads(receipts_path.read_text().strip())
    assert receipt["prd_id"] == "prd-e2e-2026-05-14"
    assert receipt["finding_id"] == "finding-1"

    # Archive should now succeed.
    assert run_prd_runner(fake_repo, "load", "prd-e2e-2026-05-14").returncode == 0
    archive_after = run_prd_runner(fake_repo, "archive")
    assert archive_after.returncode == 0, archive_after.stderr
    assert "archived" in archive_after.stdout
