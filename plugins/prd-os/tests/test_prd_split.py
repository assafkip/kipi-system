"""Tests for prd_split.py.

Covers PRD-to-issue decomposition. The split script is deterministic: it
materializes one issue spec per entry in the PRD's fenced JSON manifest.
"""

from __future__ import annotations

import json
from pathlib import Path


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


def _write_prd(
    repo: Path,
    prd_id: str,
    *,
    status: str = "approved",
    manifest: object | None = None,
    fence: str = "```json",
    skip_issues_section: bool = False,
    skip_fence: bool = False,
) -> Path:
    prds_dir = repo / ".prd-os/prds"
    prds_dir.mkdir(parents=True, exist_ok=True)
    path = prds_dir / f"{prd_id}.md"
    body = (
        "---\n"
        f"id: {prd_id}\n"
        f"title: {prd_id} fixture\n"
        f"status: {status}\n"
        "created_at: 2026-04-16T00:00:00Z\n"
        "updated_at: 2026-04-16T00:00:00Z\n"
        "owner: tester\n"
        "---\n\n"
        "# body\n\n"
    )
    if not skip_issues_section:
        body += "## Issues\n\n"
        if not skip_fence:
            if manifest is None:
                manifest = []
            body += f"{fence}\n{json.dumps(manifest, indent=2)}\n```\n"
    path.write_text(body)
    return path


def _entry(**overrides) -> dict:
    base = {
        "id": "issue-a",
        "title": "Issue A",
        "allowed_files": ["src/a.py"],
        "required_checks": ["pytest -q"],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_split_creates_issue_files_for_approved_prd(
    fake_repo, write_config, run_prd_split
):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo,
        "prd-foo-2026-04-16",
        manifest=[
            _entry(id="issue-a", title="A", allowed_files=["src/a.py"]),
            _entry(
                id="issue-b",
                title="B",
                allowed_files=["src/b.py"],
                priority="p0",
                disallowed_files=["src/secret.py"],
                required_checks=["pytest"],
                required_reviews=["codex"],
                acceptance="must pass pytest",
            ),
        ],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-foo-2026-04-16")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert len(payload["created"]) == 2

    a = (fake_repo / ".prd-os/issues/issue-a.md").read_text()
    assert "id: issue-a" in a
    assert "priority: p1" in a
    assert "  - src/a.py" in a
    assert "parent_prd: prd-foo-2026-04-16" in a

    b = (fake_repo / ".prd-os/issues/issue-b.md").read_text()
    assert "priority: p0" in b
    assert "  - src/secret.py" in b
    assert "  - pytest" in b
    assert "  - codex" in b
    assert "must pass pytest" in b


def test_split_defaults_to_active_prd(fake_repo, write_config, run_prd_runner, run_prd_split):
    _bootstrap(fake_repo, write_config)
    assert run_prd_runner(fake_repo, "new", "active-prd").returncode == 0
    state = json.loads((fake_repo / ".claude/state/active-prd.json").read_text())
    prd_id = state["prd_id"]
    # Overwrite with approved status + manifest
    _write_prd(
        fake_repo,
        prd_id,
        manifest=[_entry(id="issue-x", title="X", allowed_files=["src/x.py"])],
    )
    r = run_prd_split(fake_repo)
    assert r.returncode == 0, r.stderr
    assert (fake_repo / ".prd-os/issues/issue-x.md").is_file()


def test_split_idempotent_when_files_identical(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo,
        "prd-idemp-2026-04-16",
        manifest=[_entry(id="issue-only", title="Only", allowed_files=["src/x.py"])],
    )
    r1 = run_prd_split(fake_repo, "--prd-id", "prd-idemp-2026-04-16")
    assert r1.returncode == 0, r1.stderr
    issue_path = fake_repo / ".prd-os/issues/issue-only.md"
    first = issue_path.read_text()
    r2 = run_prd_split(fake_repo, "--prd-id", "prd-idemp-2026-04-16")
    assert r2.returncode == 0, r2.stderr
    assert issue_path.read_text() == first


def test_split_dry_run_does_not_write(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo,
        "prd-dry-2026-04-16",
        manifest=[_entry(id="issue-dry", title="Dry", allowed_files=["src/d.py"])],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-dry-2026-04-16", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert not (fake_repo / ".prd-os/issues/issue-dry.md").exists()
    payload = json.loads(r.stdout)
    assert any("issue-dry.md" in p for p in payload["would_create"])


# ---------------------------------------------------------------------------
# status gate
# ---------------------------------------------------------------------------


def test_split_refuses_unapproved_prd(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo,
        "prd-draft-2026-04-16",
        status="draft",
        manifest=[_entry()],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-draft-2026-04-16")
    assert r.returncode == 2
    assert "approved" in r.stderr


def test_split_rejects_missing_prd(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    r = run_prd_split(fake_repo, "--prd-id", "prd-missing-2026-04-16")
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# manifest validation
# ---------------------------------------------------------------------------


def test_split_empty_manifest_errors(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "prd-empty-2026-04-16", manifest=[])
    r = run_prd_split(fake_repo, "--prd-id", "prd-empty-2026-04-16")
    assert r.returncode == 2
    assert "empty" in r.stderr.lower()


def test_split_rejects_malformed_json(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    prds_dir = fake_repo / ".prd-os/prds"
    prds_dir.mkdir(parents=True, exist_ok=True)
    path = prds_dir / "prd-bad-2026-04-16.md"
    path.write_text(
        "---\n"
        "id: prd-bad-2026-04-16\n"
        "status: approved\n"
        "---\n\n"
        "## Issues\n\n"
        "```json\n"
        "[ { broken,,, ]\n"
        "```\n"
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-bad-2026-04-16")
    assert r.returncode == 2
    assert "json" in r.stderr.lower()


def test_split_rejects_missing_issues_section(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "prd-noissues-2026-04-16", skip_issues_section=True)
    r = run_prd_split(fake_repo, "--prd-id", "prd-noissues-2026-04-16")
    assert r.returncode == 2
    assert "issues" in r.stderr.lower()


def test_split_rejects_missing_required_keys(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo,
        "prd-missingkeys-2026-04-16",
        manifest=[{"id": "issue-nope"}],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-missingkeys-2026-04-16")
    assert r.returncode == 2
    assert "required" in r.stderr.lower() or "missing" in r.stderr.lower()


def test_split_rejects_invalid_id(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo,
        "prd-badid-2026-04-16",
        manifest=[_entry(id="Bad_ID!")],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-badid-2026-04-16")
    assert r.returncode == 2


def test_split_rejects_duplicate_ids(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo,
        "prd-dupe-2026-04-16",
        manifest=[
            _entry(id="issue-dup", title="one", allowed_files=["src/a.py"]),
            _entry(id="issue-dup", title="two", allowed_files=["src/b.py"]),
        ],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-dupe-2026-04-16")
    assert r.returncode == 2
    assert "duplicate" in r.stderr.lower()


def test_split_rejects_empty_allowed_files(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo,
        "prd-empty-allowed-2026-04-16",
        manifest=[
            {
                "id": "issue-x",
                "title": "x",
                "allowed_files": [],
                "required_checks": ["pytest"],
            }
        ],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-empty-allowed-2026-04-16")
    assert r.returncode == 2


def test_split_rejects_missing_required_checks(fake_repo, write_config, run_prd_split):
    """Gap the Codex stop-review caught: without required_checks, the runner's
    verification receipt is meaningless. The split must reject the manifest
    entirely, not emit a spec that silently bypasses the gate.
    """
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo,
        "prd-noreqchk-2026-04-16",
        manifest=[
            {
                "id": "issue-nocheck",
                "title": "no check",
                "allowed_files": ["src/a.py"],
            }
        ],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-noreqchk-2026-04-16")
    assert r.returncode == 2
    assert "required_checks" in r.stderr
    assert not (fake_repo / ".prd-os/issues/issue-nocheck.md").exists()


def test_split_rejects_empty_required_checks(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo,
        "prd-emptyreqchk-2026-04-16",
        manifest=[
            {
                "id": "issue-empty-check",
                "title": "empty check",
                "allowed_files": ["src/a.py"],
                "required_checks": [],
            }
        ],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-emptyreqchk-2026-04-16")
    assert r.returncode == 2
    assert "required_checks" in r.stderr
    assert "bypass" in r.stderr
    assert not (fake_repo / ".prd-os/issues/issue-empty-check.md").exists()


def test_split_rejects_blank_string_in_required_checks(
    fake_repo, write_config, run_prd_split
):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo,
        "prd-blankchk-2026-04-16",
        manifest=[
            {
                "id": "issue-blank",
                "title": "blank",
                "allowed_files": ["src/a.py"],
                "required_checks": [""],
            }
        ],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-blankchk-2026-04-16")
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# collision / no-clobber
# ---------------------------------------------------------------------------


def test_split_refuses_to_clobber_divergent_existing(
    fake_repo, write_config, run_prd_split
):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo,
        "prd-clash-2026-04-16",
        manifest=[_entry(id="issue-clash", title="new", allowed_files=["src/n.py"])],
    )
    # Pre-existing issue with same id but different content.
    issues_dir = fake_repo / ".prd-os/issues"
    issues_dir.mkdir(parents=True, exist_ok=True)
    (issues_dir / "issue-clash.md").write_text(
        "---\nid: issue-clash\ntitle: existing\nstatus: open\n---\n"
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-clash-2026-04-16")
    assert r.returncode == 2
    assert "clobber" in r.stderr.lower()


# ---------------------------------------------------------------------------
# fence variants
# ---------------------------------------------------------------------------


def test_split_accepts_plain_fence(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo,
        "prd-plain-fence-2026-04-16",
        manifest=[_entry(id="issue-pf", title="PF", allowed_files=["src/pf.py"])],
        fence="```",
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-plain-fence-2026-04-16")
    assert r.returncode == 0, r.stderr
    assert (fake_repo / ".prd-os/issues/issue-pf.md").is_file()
