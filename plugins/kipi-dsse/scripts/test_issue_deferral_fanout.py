"""sp-5bcfbfe8 reproducer: a deferred ISSUE finding must not be a silent drop.

THE GAP. There are two findings systems and only one honours the backstop:

  PRD findings   prd-os/scripts/findings_writer._sync_spillover_for_finding
                 appends an open `defer-<prd>-<finding>` item on `deferred`,
                 and resolves it when the finding moves off `deferred`.
  ISSUE findings kipi-dsse/scripts/issue_findings.set-disposition
                 wrote a rationale and stopped.

Measured 2026-08-06 while closing `scs-validated-event-fold`: deferred
finding-2, finding-8 and finding-9, then folded the ledger for ids containing
the issue id -> []. So at the issue level `deferred` WAS terminal, which is the
silent drop `no-orphan-findings.md` exists to forbid.

`finding-8` survived only because two of the three had been captured by hand
beforehand, for unrelated reasons. The backstop's whole job is to make that luck
unnecessary.

WHY THE RULE TEXT WAS ALSO WRONG. The rule said "A `deferred` triage
disposition AUTO-creates an open spillover item (findings_writer)". That
sentence is TRUE, and it names findings_writer. It is a correct statement about
one of two systems that reads as a guarantee about both, because the reader
supplies the generalization. Harder to catch than a false comment: a false
comment disagrees with its code, this one matched its code exactly and still
misled. Fixed by making the unqualified sentence true, not by qualifying it.

Nothing here touches the real ledger; every test builds its own repo under
tmp_path, with `.git` a plain directory so the git-common-dir lookup fails and
falls back to that root.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
FINDINGS = SCRIPTS / "issue_findings.py"
PRD_RUNNER = SCRIPTS.parents[1] / "prd-os" / "scripts" / "prd_runner.py"

ISSUE = "iss-demo"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    for sub in (".prd-os/findings/issue", ".prd-os/issues", ".claude/state"):
        (r / sub).mkdir(parents=True, exist_ok=True)
    (r / ".git").mkdir()
    (r / ".prd-os" / "config.json").write_text(json.dumps({
        "config_schema_version": 1,
        "prds_dir": ".prd-os/prds",
        "issues_dir": ".prd-os/issues",
        "findings_dir": ".prd-os/findings",
        "state_dir": ".claude/state",
    }))
    (r / ".prd-os" / "findings" / "issue" / f"{ISSUE}-findings.jsonl").write_text(
        json.dumps({
            "id": "finding-1", "issue_id": ISSUE, "severity": "major",
            "body": "a real defect that is not being fixed in this slice",
            "source": "claude-review", "disposition": "pending",
            # Field set taken from a PRODUCER-written record
            # (.prd-os/findings/issue/*-findings.jsonl, written by
            # `issue_findings.py add`), not invented. Guessing it field-by-field
            # cost two red runs whose failures were my fixture, not the defect.
            "affected_path": "plugins/kipi-dsse/scripts/issue_findings.py",
            "out_of_scope": False,
            "created_at": "2026-08-06T00:00:00Z",
        }) + "\n")
    return r


def disposition(repo: Path, value: str, rationale: str | None = "out of scope here"):
    cmd = [sys.executable, str(FINDINGS), "set-disposition", ISSUE, "finding-1", value]
    if rationale:
        cmd += ["--rationale", rationale]
    return subprocess.run(cmd, capture_output=True, text=True,
                          cwd=str(repo), env=_env(repo))


def _env(repo: Path) -> dict:
    import os
    e = dict(os.environ)
    e["CLAUDE_PROJECT_DIR"] = str(repo)
    return e


def spillover(repo: Path) -> dict:
    p = repo / ".prd-os" / "spillover.jsonl"
    if not p.is_file():
        return {}
    out = {}
    for line in p.read_text().splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec["id"]] = rec
    return out


SID = f"defer-{ISSUE}-finding-1"


def test_deferring_an_issue_finding_creates_an_open_spillover_item(repo: Path):
    """THE reproducer. Red against today's code with an EMPTY result.

    Asserted as "an open item with this id exists", not "the file is non-empty"
    -- a weaker assertion would pass on any unrelated append.
    """
    result = disposition(repo, "deferred")
    assert result.returncode == 0, f"set-disposition failed: {result.stderr!r}"
    items = spillover(repo)
    assert SID in items, (
        "deferring an issue finding created NO spillover item, so `deferred` is "
        f"a terminal state and the finding is silently dropped.\nledger={list(items)}")
    assert items[SID].get("status") == "open", (
        f"item exists but is not open: {items[SID]!r}")
    assert items[SID].get("severity") == "major", (
        "the finding's severity must carry over, or a major defect lands in the "
        f"gate's non-blocking bucket: {items[SID]!r}")


def test_the_item_carries_the_whole_finding_body(repo: Path):
    """Not a prefix. sp-9f11cf69 was exactly this defect on the PRD side: a
    120-char cap made every defer-* row end mid-sentence, and nobody can triage
    what they cannot read."""
    disposition(repo, "deferred")
    desc = spillover(repo)[SID].get("description", "")
    assert "a real defect that is not being fixed in this slice" in desc, (
        f"finding body did not survive into the ledger row: {desc!r}")


def test_deferring_twice_does_not_double_append(repo: Path):
    """Idempotency, matching the PRD-level fan-out.

    The ledger is append-only and folds last-write-wins, so a duplicate is not
    a correctness bug -- but it is noise in a ledger whose central problem is
    unbounded growth, and re-deferring is a normal operator action.
    """
    disposition(repo, "deferred")
    first = (repo / ".prd-os" / "spillover.jsonl").read_text()
    disposition(repo, "deferred", "still out of scope")
    assert (repo / ".prd-os" / "spillover.jsonl").read_text() == first, \
        "a second defer appended a duplicate event"


def test_moving_off_deferred_resolves_the_item(repo: Path):
    """Reverse transition, matching PRD-level behaviour: accepting a finding
    must not leave an orphan open item blocking the gate forever."""
    disposition(repo, "deferred")
    assert spillover(repo)[SID]["status"] == "open"
    result = disposition(repo, "accepted", rationale=None)
    assert result.returncode == 0, f"accept failed: {result.stderr!r}"
    assert spillover(repo)[SID]["status"] == "resolved", (
        "the finding is no longer deferred but its spillover item is still open; "
        "the standing gate would block on work that is done")


def test_a_non_deferred_disposition_creates_nothing(repo: Path):
    """Negative self-test. A fan-out that fires on every disposition would
    satisfy the first test and flood the ledger."""
    result = disposition(repo, "rejected", "duplicate of finding-0")
    assert result.returncode == 0, f"reject failed: {result.stderr!r}"
    assert SID not in spillover(repo), \
        "a rejected finding created a spillover item; reject is terminal by design"
