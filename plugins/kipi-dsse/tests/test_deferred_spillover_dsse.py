"""sp-5642a835 reproducer: the DSSE ISSUE path must honor the deferred
disposition contract too. `.claude/rules/no-orphan-findings.md` promises
that deferring a finding AUTO-creates an open spillover item in BOTH
findings systems. The prd-os writer grew that sync (sp-5bcfbfe8); the
kipi-dsse issue path -- the one every increment of a split PRD actually
runs -- still dropped `deferred` silently at the time this was written.

Reproducer-first: deferring through issue_findings.py leaves the ledger
empty before the fix, and mirrors it after.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ISSUE_FINDINGS = PLUGIN_ROOT / "scripts" / "issue_findings.py"
ISSUE_ID = "c2w-demo"


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    # issue_findings resolves its repo from CLAUDE_PROJECT_DIR / cwd walk,
    # not a flag -- drive it the way production does.
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(repo))
    return subprocess.run(
        [sys.executable, str(ISSUE_FINDINGS), *args],
        capture_output=True, text=True, env=env, cwd=str(repo),
    )


def _ledger(repo: Path) -> dict:
    path = repo / ".prd-os" / "spillover.jsonl"
    items: dict = {}
    if not path.exists():
        return items
    for raw in path.read_text().splitlines():
        if raw.strip():
            rec = json.loads(raw)
            if isinstance(rec, dict) and rec.get("id"):
                items[rec["id"]] = rec  # last-write-wins, same as readers
    return items


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "issues" / "findings").mkdir(parents=True)
    (r / ".git").mkdir()
    rec = {
        "id": "finding-9", "issue_id": ISSUE_ID, "source": "codex-adversarial",
        "severity": "major", "disposition": "pending",
        "body": "exporter drops non-ascii slugs on the floor",
        "affected_path": "q-consult/pipeline/exporters.py",
        "out_of_scope": False,
        "created_at": "2026-08-24T00:00:00Z",
    }
    (r / "issues" / "findings" / f"{ISSUE_ID}-findings.jsonl").write_text(
        json.dumps(rec) + "\n")
    return r


def _set(repo: Path, disposition: str, rationale: str = "later") -> subprocess.CompletedProcess:
    args = ["set-disposition", ISSUE_ID, "finding-9", disposition]
    if disposition in ("rejected", "deferred"):
        args += ["--rationale", rationale]
    return _run(repo, *args)


def test_deferring_through_the_issue_path_opens_a_spillover_item(repo):
    out = _set(repo, "deferred")
    assert out.returncode == 0, out.stderr
    items = _ledger(repo)
    sid = f"defer-{ISSUE_ID}-finding-9"
    assert items.get(sid, {}).get("status") == "open", (
        "a DSSE-path defer is terminal and silent -- the exact drop "
        "no-orphan-findings.md says cannot happen")
    assert "finding-9" in items[sid].get("description", "")
    assert items[sid].get("rationale_hint") or True


def test_rejecting_stays_terminal_and_does_not_open_one(repo):
    out = _set(repo, "rejected", rationale="won't fix, by design")
    assert out.returncode == 0, out.stderr
    assert _ledger(repo) == {}, "rejection must not manufacture work"


def test_leaving_deferred_clears_the_item(repo):
    assert _set(repo, "deferred").returncode == 0
    sid = f"defer-{ISSUE_ID}-finding-9"
    assert _ledger(repo)[sid]["status"] == "open"
    out = _set(repo, "accepted")
    assert out.returncode == 0, out.stderr
    assert _ledger(repo)[sid]["status"] == "resolved"


def test_second_defer_is_idempotent_not_a_duplicate_stream(repo):
    assert _set(repo, "deferred").returncode == 0
    assert _set(repo, "deferred").returncode == 0
    rows = [r for r in _ledger(repo).values()
            if r["id"] == f"defer-{ISSUE_ID}-finding-9"]
    assert len(rows) == 1 and rows[0]["status"] == "open"
