"""spill-01 reproducer: out-of-scope findings land in a durable ledger and turn
the STANDING gate (`gates run`) red until each is resolved against a CLOSED issue.

Reproducer-first: before the spillover code exists every test here fails
(`spillover` is an unknown subcommand; `gates run` stays green with an open item).
The ADHD-proof property under test: an item that is merely "mentioned" cannot
clear the gate; only a real, closed, tracked issue (or an explicit recorded void)
can.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PRD_RUNNER = PLUGIN_ROOT / "scripts" / "prd_runner.py"


def run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PRD_RUNNER), "--repo-root", str(repo), *args],
        capture_output=True, text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / ".prd-os").mkdir(parents=True)
    (r / ".git").mkdir()
    (r / ".prd-os" / "config.json").write_text(json.dumps({
        "config_schema_version": 1,
        "prds_dir": ".prd-os/prds",
        "issues_dir": ".prd-os/issues",
        "findings_dir": ".prd-os/findings",
        "state_dir": ".claude/state",
    }))
    return r


def _ledger(repo: Path) -> Path:
    return repo / ".prd-os" / "spillover.jsonl"


def _write_issue(repo: Path, issue_id: str, status: str) -> None:
    d = repo / ".prd-os" / "issues"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{issue_id}.md").write_text(
        f"---\nid: {issue_id}\nstatus: {status}\n---\n\n# {issue_id}\n"
    )


def test_add_appends_open_item(repo):
    r = run(repo, "spillover", "add", "--source", "prd-x", "--desc", "obsidian export skips archived", "--id", "sp1")
    assert r.returncode == 0, r.stderr
    lines = _ledger(repo).read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["id"] == "sp1" and rec["status"] == "open" and rec["source"] == "prd-x"


def test_add_is_idempotent_by_id(repo):
    run(repo, "spillover", "add", "--source", "s", "--desc", "d", "--id", "sp1")
    run(repo, "spillover", "add", "--source", "s", "--desc", "d", "--id", "sp1")
    # last-write-wins read collapses to one effective item, still open
    r = run(repo, "spillover", "list", "--json")
    items = json.loads(r.stdout)
    assert len([i for i in items if i["id"] == "sp1"]) == 1


def test_check_red_while_open_green_when_none(repo):
    assert run(repo, "spillover", "check").returncode == 0  # empty ledger = green
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1")
    assert run(repo, "spillover", "check").returncode == 1  # open item = red


def test_gates_run_red_while_spillover_open(repo):
    # No registered gates at all, but an open spillover item must still make the
    # STANDING re-proof fail. This is the can't-be-forgotten property.
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1")
    g = run(repo, "gates", "run")
    assert g.returncode != 0, "gates run stayed green with an open spillover item"
    assert "sp1" in (g.stdout + g.stderr)


def test_resolve_refuses_unless_issue_closed(repo):
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1")
    _write_issue(repo, "iss-1", status="in-progress")
    bad = run(repo, "spillover", "resolve", "sp1", "--resolution-ref", "iss-1")
    assert bad.returncode != 0, "resolve accepted a non-closed issue"
    assert run(repo, "spillover", "check").returncode == 1  # still open

    _write_issue(repo, "iss-1", status="closed")
    ok = run(repo, "spillover", "resolve", "sp1", "--resolution-ref", "iss-1")
    assert ok.returncode == 0, ok.stderr
    assert run(repo, "spillover", "check").returncode == 0  # now green
    assert run(repo, "gates", "run").returncode == 0


def test_resolve_refuses_unknown_issue(repo):
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1")
    bad = run(repo, "spillover", "resolve", "sp1", "--resolution-ref", "nope")
    assert bad.returncode != 0


def test_void_resolves_with_recorded_reason(repo):
    run(repo, "spillover", "add", "--source", "s", "--desc", "not real", "--id", "sp1")
    ok = run(repo, "spillover", "resolve", "sp1", "--void", "duplicate of sp0")
    assert ok.returncode == 0, ok.stderr
    assert run(repo, "spillover", "check").returncode == 0
    last = [json.loads(l) for l in _ledger(repo).read_text().splitlines() if json.loads(l)["id"] == "sp1"][-1]
    assert last["status"] == "resolved" and last.get("void_reason") == "duplicate of sp0"


def test_resolve_requires_a_target(repo):
    run(repo, "spillover", "add", "--source", "s", "--desc", "x", "--id", "sp1")
    bad = run(repo, "spillover", "resolve", "sp1")  # neither --resolution-ref nor --void
    assert bad.returncode != 0
