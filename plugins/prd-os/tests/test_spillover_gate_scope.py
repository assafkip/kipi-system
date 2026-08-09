"""ASK-526 reproducer: `gates run` must say WHICH thing is red.

THE DEFECT. `cmd_gates` collapsed two unrelated verdicts into one exit code:
"a regression gate failed" (you broke something) and "the spillover ledger is
non-empty" (there is a backlog). Measured on kipi-system 2026-08-08: 640 open
items, arriving ~50/day from 141 distinct sources against ~4/day resolved. A
boolean over a queue whose arrival rate is 12x its service rate is RED with
probability 1, permanently -- so every issue closeout inherited a red light
that carried no information, and a genuine NEW regression is invisible inside
it. That is the roll-up-status failure: BLOCKED tells you nothing about which
thing is blocked.

THE FIX UNDER TEST. Blocking is scoped by ATTRIBUTION, never by the clock.
Items whose `source` is the active scope block; items inherited from other
work are reported in a census that prints on EVERY run. Nothing ages out,
nothing leaves the ledger, and an unscoped run stays fail-closed on the whole
set -- so the bare `gates run` named by wiring-check.md still tells the truth
about all 640.

WHY NOT AN AGE CUTOFF (the rejected design). An age cutoff would let
`gates run` print "no open spillover" while 640 items sat open. A gate that
prints a false statement is strictly worse than one that is red: red is
uninformative, a lying green is misleading. `test_census_*` below is what
pins that -- a passing scoped run must still say the number out loud.
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


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


def _commit_live_spec(repo: Path, sub: str, sid: str) -> None:
    """A scope only narrows the gate when it is PROVABLY live (ASK-527): spec
    present, git-tracked, non-terminal status. These tests are about which items
    block, so their setup must satisfy that precondition -- the assertions below
    are unchanged."""
    d = repo / ".prd-os" / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sid}.md").write_text(f"---\nid: {sid}\nstatus: draft\n---\n")
    _git(repo, "add", "-f", f".prd-os/{sub}/{sid}.md")
    _git(repo, "commit", "-q", "-m", f"add {sid}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / ".prd-os").mkdir(parents=True)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / ".prd-os" / "config.json").write_text(json.dumps({
        "config_schema_version": 1,
        "prds_dir": ".prd-os/prds",
        "issues_dir": ".prd-os/issues",
        "findings_dir": ".prd-os/findings",
        "state_dir": ".claude/state",
    }))
    (r / "README.md").write_text("fixture\n")
    _git(r, "add", "README.md")
    _git(r, "commit", "-q", "-m", "init")
    return r


def _set_active_issue(repo: Path, issue_id: str) -> None:
    d = repo / ".claude" / "state"
    d.mkdir(parents=True, exist_ok=True)
    (d / "active-issue.json").write_text(json.dumps({"issue_id": issue_id}))
    _commit_live_spec(repo, "issues", issue_id)


def _set_active_prd(repo: Path, prd_id: str) -> None:
    d = repo / ".claude" / "state"
    d.mkdir(parents=True, exist_ok=True)
    (d / "active-prd.json").write_text(json.dumps({"prd_id": prd_id}))
    _commit_live_spec(repo, "prds", prd_id)


def _add(repo: Path, sid: str, source: str, desc: str = "a real finding") -> None:
    assert run(repo, "spillover", "add", "--source", source,
               "--desc", desc, "--id", sid).returncode == 0


def _register_failing_gate(repo: Path, gate_id: str) -> None:
    """A regression gate that always fails, so the OTHER verdict can be seen."""
    (repo / ".prd-os" / "gates.jsonl").write_text(json.dumps({
        "gate_id": gate_id, "issue_id": "iss-old", "lifecycle": "regression",
        "command": "exit 7",
    }) + "\n")


# --- the defect itself -------------------------------------------------------

def test_inherited_backlog_does_not_block_a_scoped_run(repo):
    """RED before the fix: one item from OTHER work made a clean issue red."""
    _set_active_issue(repo, "ASK-1")
    _add(repo, "sp-inherited", "some-old-issue")
    g = run(repo, "gates", "run")
    assert g.returncode == 0, (
        "an inherited backlog item blocked a scoped run; the red light is "
        f"still uninformative.\nstdout={g.stdout}\nstderr={g.stderr}"
    )


def test_census_names_the_inherited_backlog_on_a_passing_run(repo):
    """A pass must still say the number out loud. This is the anti-silent-drop
    property: the operator has ADHD and a backlog that stops being printed is
    functionally deleted. Asserts the LITERAL count, not 'same as before'."""
    _set_active_issue(repo, "ASK-1")
    for n in range(3):
        _add(repo, f"sp-old{n}", "some-old-issue")
    g = run(repo, "gates", "run")
    assert g.returncode == 0
    out = g.stdout + g.stderr
    assert "3" in out and "inherited" in out, (
        f"a passing scoped run hid the 3-item backlog entirely.\nout={out}"
    )
    assert "no open spillover" not in out, (
        "the run printed a FALSE claim of an empty ledger while 3 items were "
        f"open. A lying green is worse than a red.\nout={out}"
    )


def test_explicit_scope_flag_selects_what_blocks(repo):
    _set_active_issue(repo, "ASK-1")
    _add(repo, "sp-mine", "ASK-2")
    g = run(repo, "gates", "run", "--scope", "ASK-2")
    assert g.returncode == 1, (
        "--scope did not select the blocking set (2 = argparse rejected the "
        f"flag).\nstdout={g.stdout}\nstderr={g.stderr}"
    )
    assert "sp-mine" in (g.stdout + g.stderr)


# --- the invariants the fix must NOT break -----------------------------------

def test_attributable_item_still_blocks_a_scoped_run(repo):
    """The whole point of the ledger. If this ever passes green, the fix has
    become the hand-clear it was written to avoid."""
    _set_active_issue(repo, "ASK-1")
    _add(repo, "sp-mine", "ASK-1")
    g = run(repo, "gates", "run")
    assert g.returncode != 0, "work's own spillover item did not block its gate"
    assert "sp-mine" in (g.stdout + g.stderr)


def test_unscoped_run_is_fail_closed_on_everything(repo):
    """No active issue = no excuse. The bare `gates run` that wiring-check.md
    tells you to run still sees all 640. Nothing is hidden by the scoping."""
    _add(repo, "sp-a", "some-old-issue")
    _add(repo, "sp-b", "another-old-issue")
    g = run(repo, "gates", "run")
    assert g.returncode != 0, "unscoped run went green over an open ledger"
    out = g.stdout + g.stderr
    assert "sp-a" in out and "sp-b" in out


def test_active_prd_scopes_when_no_active_issue(repo):
    _set_active_prd(repo, "prd-x")
    _add(repo, "sp-inherited", "some-old-issue")
    _add(repo, "sp-mine", "prd-x")
    g = run(repo, "gates", "run")
    assert g.returncode != 0
    out = g.stdout + g.stderr
    assert "sp-mine" in out, f"active PRD did not scope the gate.\nout={out}"


def test_regression_failure_is_reported_separately_from_the_backlog(repo):
    """The two verdicts must be distinguishable. A closeout reading this needs
    to tell 'you broke something' from 'there is a backlog'."""
    _set_active_issue(repo, "ASK-1")
    _register_failing_gate(repo, "g-broken")
    _add(repo, "sp-inherited", "some-old-issue")
    g = run(repo, "gates", "run")
    assert g.returncode != 0
    out = g.stdout + g.stderr
    assert "g-broken" in out, f"the real regression failure was not named.\nout={out}"
    assert "GATE RED: spillover" not in out, (
        "an inherited-only backlog was reported as a gate failure, which is "
        f"the ambiguity this issue exists to remove.\nout={out}"
    )
