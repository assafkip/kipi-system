"""ASK-527 reproducer: a stale or abandoned active scope must not grant amnesty.

THE DEFECT (live on kipi-system when this was written, not hypothetical).
ASK-526 made `gates run` fail-closed when there is no active scope. But the
scope is INFERRED from `.claude/state/active-prd.json`, and nothing proved the
thing it names is a real, live unit of work. Measured 2026-08-09:

    active-prd.json -> prd-judgment-compiler-not-deployed-2026-08-05
    status in the state file: "idea"   (never advanced past the first state)
    loaded_at:                2026-08-05T17:48:04Z  (3 days earlier)
    the spec file:            present on disk, NOT git-tracked
    result:                   gates run exited 0 over 635 open items

So a forgotten draft lying in one working tree silently narrowed the gate to
itself and granted a standing amnesty over the entire ledger. That is the same
hole the age-cutoff design was rejected for in ASK-526, arriving through a
different door: enforcement lapsed and nobody decided anything.

THE PROPERTY UNDER TEST. A scope may narrow the gate only if it is PROVABLY a
live, durable unit of work. Every unprovable case -- spec missing, spec not
tracked in git, spec in a terminal state, git unable to answer -- collapses to
"no scope", which falls through to the fail-closed path where every open item
blocks. Unprovable is never a reason to relax; it is the reason to refuse.

WHY GIT-TRACKED IS THE DURABILITY TEST. Precedent in this same codebase:
`_enforce_wiring_contract` (issue_runner) blocks close until every allowed_file
is git-tracked, born from the scar that a created-but-unstaged file passed every
gate and vanished on a fresh checkout. A PRD that governs a fleet safety gate but
exists only in one working tree is not a durable unit of work either.

WHAT WAS REJECTED, and why the clock is not welcome here:
  - An mtime age cap re-introduces exactly the ASK-526 defect one layer up: the
    scope would change state because time passed, with nobody deciding. Worse,
    mtime is not a durable property -- git checkout, rsync and `kipi update` all
    rewrite it, so the gate would flap for reasons unrelated to the work.
  - "Last ledger write attributable to the scope" is perverse: a scope would keep
    itself alive by PRODUCING MORE SPILLOVER. That rewards the behaviour the
    ledger exists to bound.
  - "Require an explicit active-state file instead of inferring" changes nothing.
    The file already exists and is explicit. The file IS the problem, not its
    absence.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PRD_RUNNER = PLUGIN_ROOT / "scripts" / "prd_runner.py"


def run(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PRD_RUNNER), "--repo-root", str(repo), *args],
        capture_output=True, text=True, env=env,
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A REAL git repo. The guard asks git whether a spec is tracked, so a
    fixture that only mkdir'd `.git` would make every tracked-ness answer
    unprovable and the tests would pass for the wrong reason."""
    r = tmp_path / "repo"
    (r / ".prd-os").mkdir(parents=True)
    (r / ".prd-os" / "config.json").write_text(json.dumps({
        "config_schema_version": 1,
        "prds_dir": ".prd-os/prds",
        "issues_dir": ".prd-os/issues",
        "findings_dir": ".prd-os/findings",
        "state_dir": ".claude/state",
    }))
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "README.md").write_text("fixture\n")
    _git(r, "add", "README.md")
    _git(r, "commit", "-q", "-m", "init")
    return r


def _active_prd(repo: Path, prd_id: str) -> None:
    d = repo / ".claude" / "state"
    d.mkdir(parents=True, exist_ok=True)
    (d / "active-prd.json").write_text(json.dumps({
        "prd_id": prd_id, "loaded_at": "2026-08-05T17:48:04Z",
        "spec_path": f".prd-os/prds/{prd_id}.md", "status": "idea",
    }))


def _write_spec(repo: Path, prd_id: str, status: str, *, tracked: bool) -> None:
    d = repo / ".prd-os" / "prds"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{prd_id}.md"
    p.write_text(f"---\nid: {prd_id}\nstatus: {status}\n---\n\n# {prd_id}\n")
    if tracked:
        _git(repo, "add", "-f", str(p.relative_to(repo)))
        _git(repo, "commit", "-q", "-m", f"add {prd_id}")


def _seed_backlog(repo: Path, n: int) -> None:
    """Reproduce the real scale. One CLI call establishes the producer's record
    shape; the rest are appended in that shape and then read back through the
    runner's own reader, so the fixture is validated by production code."""
    assert run(repo, "spillover", "add", "--source", "old-work",
               "--desc", "seed item 0", "--id", "sp-seed0",
               "--severity", "major").returncode == 0
    ledger = repo / ".prd-os" / "spillover.jsonl"
    shape = json.loads(ledger.read_text().splitlines()[0])
    with ledger.open("a") as fh:
        for i in range(1, n):
            rec = dict(shape, id=f"sp-seed{i}", description=f"seed item {i}")
            fh.write(json.dumps(rec) + "\n")
    check = run(repo, "spillover", "check")
    assert check.returncode == 1, "the runner did not read the seeded backlog"
    assert f"{n} open spillover item(s)" in check.stderr, check.stderr[-300:]


# --- the defect: this is kipi-system's exact live state ----------------------

def test_untracked_stale_spec_cannot_grant_amnesty(repo):
    """RED before the fix: exits 0 over 600+ open items because a forgotten,
    never-committed draft narrowed the gate to itself."""
    _seed_backlog(repo, 600)
    _active_prd(repo, "prd-abandoned")
    _write_spec(repo, "prd-abandoned", "idea", tracked=False)
    g = run(repo, "gates", "run")
    out = g.stdout + g.stderr
    assert g.returncode != 0, (
        "an UNTRACKED spec granted a standing amnesty over 600 open items; "
        f"the fail-closed path was never reached.\nout={out}"
    )
    assert "600" in out, f"the backlog it refused to excuse was not named.\nout={out}"
    assert "not git-tracked" in out, (
        f"refusal did not name a fixable reason, so the red gate is as "
        f"uninformative as the one ASK-526 replaced.\nout={out}"
    )


def test_missing_spec_cannot_grant_amnesty(repo):
    _seed_backlog(repo, 600)
    _active_prd(repo, "prd-vanished")  # no spec written at all
    g = run(repo, "gates", "run")
    assert g.returncode != 0, (
        "an active-state file naming a spec that does not exist still scoped "
        f"the gate.\nout={g.stdout + g.stderr}"
    )
    assert "does not exist" in (g.stdout + g.stderr)


def test_terminal_spec_cannot_grant_amnesty(repo):
    _seed_backlog(repo, 600)
    _active_prd(repo, "prd-done")
    _write_spec(repo, "prd-done", "archived", tracked=True)
    g = run(repo, "gates", "run")
    assert g.returncode != 0, (
        "an ARCHIVED PRD still scoped the gate; finished work must not carry a "
        f"live amnesty.\nout={g.stdout + g.stderr}"
    )


def test_spec_without_status_frontmatter_cannot_grant_amnesty(repo):
    """Unprovable is a refusal, not a pass. A spec whose status cannot be read
    says nothing about whether the work is live."""
    _seed_backlog(repo, 600)
    _active_prd(repo, "prd-nostatus")
    d = repo / ".prd-os" / "prds"
    d.mkdir(parents=True, exist_ok=True)
    (d / "prd-nostatus.md").write_text("---\nid: prd-nostatus\n---\n\n# no status\n")
    _git(repo, "add", "-f", ".prd-os/prds/prd-nostatus.md")
    _git(repo, "commit", "-q", "-m", "add prd-nostatus")
    g = run(repo, "gates", "run")
    assert g.returncode != 0, (
        f"a spec with no status frontmatter scoped the gate.\nout={g.stdout + g.stderr}"
    )


def test_git_unable_to_answer_is_a_refusal_not_a_pass(repo):
    """The fail-OPEN direction. If the tracked-ness lookup cannot run at all
    (git missing from PATH), the scope is unprovable and must be refused. A
    lookup that guessed True on failure would hand out amnesty precisely when
    the system knows least."""
    _seed_backlog(repo, 600)
    _active_prd(repo, "prd-live")
    _write_spec(repo, "prd-live", "draft", tracked=True)
    assert run(repo, "gates", "run").returncode == 0, "precondition: scope is live"
    blind = dict(os.environ, PATH="/nonexistent-so-git-cannot-be-found")
    g = run(repo, "gates", "run", env=blind)
    assert g.returncode != 0, (
        "with git unavailable the guard assumed the spec was tracked and "
        f"scoped the gate anyway.\nout={g.stdout + g.stderr}"
    )


# --- the invariants the guard must NOT break ---------------------------------

def test_tracked_live_spec_still_scopes(repo):
    """The guard must refuse abandoned scopes, not all scopes. If this ever goes
    red the fix has become 'delete the feature', which is not the ask."""
    _seed_backlog(repo, 600)
    _active_prd(repo, "prd-live")
    _write_spec(repo, "prd-live", "draft", tracked=True)
    g = run(repo, "gates", "run")
    out = g.stdout + g.stderr
    assert g.returncode == 0, f"a live, tracked, in-flight PRD failed to scope.\nout={out}"
    assert "600 inherited" in out, f"the census stopped naming the backlog.\nout={out}"


def test_explicit_scope_flag_is_honoured_without_a_spec(repo):
    """`--scope` is a caller ASSERTING accountability, which is a decision by
    somebody. The defect was amnesty INFERRED from a file nobody looked at, so
    the explicit flag stays honoured and is not required to name a spec."""
    _seed_backlog(repo, 600)
    run(repo, "spillover", "add", "--source", "ASK-9", "--desc", "mine", "--id", "sp-mine",
        "--severity", "major")
    g = run(repo, "gates", "run", "--scope", "ASK-9")
    out = g.stdout + g.stderr
    assert g.returncode == 1 and "sp-mine" in out, out
    assert "600 inherited" in out, f"census lost under an explicit scope.\nout={out}"


def test_dead_issue_does_not_fall_back_to_a_live_prd(repo):
    """The issue is the narrower unit and wins, but only while IT is live."""
    _seed_backlog(repo, 600)
    _active_prd(repo, "prd-live")
    _write_spec(repo, "prd-live", "draft", tracked=True)
    d = repo / ".claude" / "state"
    (d / "active-issue.json").write_text(json.dumps({"issue_id": "iss-dead"}))
    idir = repo / ".prd-os" / "issues"
    idir.mkdir(parents=True, exist_ok=True)
    (idir / "iss-dead.md").write_text("---\nid: iss-dead\nstatus: closed\n---\n")
    _git(repo, "add", "-f", ".prd-os/issues/iss-dead.md")
    _git(repo, "commit", "-q", "-m", "add iss-dead")
    g = run(repo, "gates", "run")
    assert g.returncode != 0, (
        "a CLOSED active issue scoped the gate instead of falling through to "
        f"fail-closed.\nout={g.stdout + g.stderr}"
    )
