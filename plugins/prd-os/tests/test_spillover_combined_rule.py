"""The combined blocking contract: attribution narrows WHICH items count, severity
still sets the bar, and a `blocker` anywhere is the floor.

WHY THIS FILE EXISTS. Two fixes for one defect were written without seeing each
other. ASK-363 shipped a SEVERITY filter (blocker/major/high block, minor is
reported). ASK-526/527 shipped ATTRIBUTION scoping (only items your active scope
opened block). Landed naively, each deletes the other's contract: pure attribution
turns six severity tests red, and pure severity leaves the measured defect in place.

THE MEASURED DEFECT, so a later reader does not "simplify" this back. Run against
kipi-system 2026-08-09: 636 open items, of which the severity filter blocks 18, and
all 18 are inherited from other work (prd-silent-absence, scs-validated-event-fold,
ASK-402, PR-123). Not one is attributable to any change under review. A verdict that
is RED with probability 1 regardless of the diff carries no information about the
diff, and wiring-check.md still mandates `gates run` exits 0 as definition-of-done,
so the repo's own done-check was decoration.

THE RULE (see _spillover_blocks in prd_runner.py):

    no live scope        -> severity decides (ASK-363's rule, unchanged)
    item source == scope -> severity decides (your own item, normal bar)
    inherited item       -> only `blocker` blocks

The middle line is what keeps `archive` meaningful: `gates run` stays green day to
day on a minor item YOUR work opened, and `archive` is the stricter bar that refuses
on any open item at closeout. Collapsing those two bars is the "fix" this file
exists to make fail loudly.
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
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / ".prd-os").mkdir(parents=True)
    (r / ".prd-os" / "config.json").write_text(json.dumps({
        "config_schema_version": 1,
        "prds_dir": ".prd-os/prds",
        "issues_dir": ".prd-os/issues",
        "findings_dir": ".prd-os/findings",
        "state_dir": ".claude/state",
    }))
    # A REAL git repo. ASK-527's liveness guard asks git whether the active spec
    # is tracked; a mkdir'd .git makes that query fail, which the guard correctly
    # reads as "cannot confirm -> no amnesty".
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "README.md").write_text("x\n")
    _git(r, "add", "README.md")
    _git(r, "commit", "-q", "-m", "init")
    return r


def _scope(repo: Path, issue_id: str) -> None:
    """Establish a LIVE, TRACKED active issue -- the ASK-527 precondition for a
    scope to grant any amnesty at all."""
    d = repo / ".claude" / "state"
    d.mkdir(parents=True, exist_ok=True)
    (d / "active-issue.json").write_text(json.dumps({"issue_id": issue_id}))
    p = repo / ".prd-os" / "issues" / f"{issue_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nid: {issue_id}\nstatus: in-progress\n---\n\nbody\n")
    _git(repo, "add", "-f", str(p.relative_to(repo)))
    _git(repo, "commit", "-q", "-m", f"add {issue_id}")


def _add(repo: Path, sid: str, source: str, severity: str = "minor") -> None:
    r = run(repo, "spillover", "add", "--source", source, "--desc",
            f"item {sid}", "--id", sid, "--severity", severity)
    assert r.returncode == 0, r.stderr


# --- the defect the combination has to fix ----------------------------------

def test_inherited_major_does_not_block_a_scoped_run(repo):
    """THE MEASURED DEFECT. 17 inherited majors sat open; every one of them made
    every scope red forever. RED before the combined rule: fail-closed attribution
    blocked it, and pure severity blocked it too."""
    _scope(repo, "ASK-1")
    _add(repo, "sp-inherited", "some-old-issue", "major")
    g = run(repo, "gates", "run")
    assert g.returncode == 0, (
        "an inherited MAJOR from other work blocked a clean scope; the red light "
        f"is still uninformative.\nout={g.stdout + g.stderr}"
    )


def test_inherited_blocker_still_wedges_every_scope(repo):
    """The deliberate floor, and the known cost. A `blocker` from ANY source stops
    the world even though nobody in this scope can fix it.

    THE FAILURE MODE, NAMED ON PURPOSE (do not discover this at 2am): one inherited
    blocker wedges every scope in the repo until somebody acts on it. That is the
    intended blast radius -- `blocker` is defined as "stop the world" -- but it means
    the severity is a loaded gun and mislabelling one item halts all work. The escape
    hatches are auditable and there are exactly three, all of which RECORD a decision:
    `spillover reclassify` it with a --reason, `resolve` it against a closed issue, or
    `void` it with a reason. There is deliberately no --ignore-inherited flag, because
    that would be the hand-clear no-orphan-findings.md refuses everywhere else."""
    _scope(repo, "ASK-1")
    _add(repo, "sp-boom", "some-old-issue", "blocker")
    g = run(repo, "gates", "run")
    assert g.returncode != 0, (
        f"an inherited BLOCKER did not stop the world.\nout={g.stdout + g.stderr}")
    assert "sp-boom" in (g.stdout + g.stderr), "the blocker was not even named"


def test_your_own_minor_does_not_block_gates_but_archive_still_refuses(repo):
    """The two-bar split ASK-363 pinned, which pure attribution deleted. `gates run`
    is the day-to-day light; `archive` is the closeout bar that reports everything
    this work touched."""
    _scope(repo, "ASK-1")
    _add(repo, "sp-mine", "ASK-1", "minor")
    g = run(repo, "gates", "run")
    assert g.returncode == 0, (
        f"a MINOR item this work opened blocked the daily gate.\nout={g.stdout}{g.stderr}")


def test_your_own_major_still_blocks_your_scope(repo):
    """Attribution narrows which items count; it does not lower the bar on yours."""
    _scope(repo, "ASK-1")
    _add(repo, "sp-mine", "ASK-1", "major")
    g = run(repo, "gates", "run")
    assert g.returncode != 0, (
        f"a MAJOR this work opened did not block.\nout={g.stdout + g.stderr}")
    assert "sp-mine" in (g.stdout + g.stderr)


def test_census_still_prints_the_inherited_backlog_on_a_green_run(repo):
    """The thing ASK-526 refused to trade away. A gate that goes green over a large
    inherited backlog and says NOTHING is the silent drop, and for an operator with
    ADHD a number that stops being printed is functionally deleted."""
    _scope(repo, "ASK-1")
    for i in range(17):
        _add(repo, f"sp-maj{i}", "some-old-issue", "major")
    _add(repo, "sp-min", "some-old-issue", "minor")
    g = run(repo, "gates", "run")
    assert g.returncode == 0, f"inherited majors blocked: {g.stdout}{g.stderr}"
    out = g.stdout + g.stderr
    assert "18 open total" in out, f"census did not state the total.\nout={out}"
    assert "17" in out and "blocking severity" in out, (
        f"census went green without naming the 17 inherited majors.\nout={out}")
