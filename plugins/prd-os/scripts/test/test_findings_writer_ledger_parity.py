"""sp-7a8434ec: findings_writer must not undo what issue_findings just fixed.

TWO WRITERS, ONE LEDGER. `issue_findings.py` (kipi-dsse) and `findings_writer.py`
(prd-os) both fan a `deferred` finding out to `defer-*` rows in the SAME
`.prd-os/spillover.jsonl`, and ASK-429 fixed three defects on the kipi-dsse side
only. A defect fixed on one of two paths into a shared artifact is worse than one
fixed on neither: the safe path teaches an operator to trust the ledger, and the
unsafe path is the one that then lies to them.

The three carried over verbatim, plus a fourth this file measures rather than
assumes:

  nit severity   `nit` is a legal PRD finding severity and is NOT in the ledger's
                 vocabulary. `_is_blocking_severity` fails closed on unknown, so
                 deferring the most trivial finding a reviewer can file turns the
                 standing gate RED fleet-wide.
  pending        the reverse-transition branch is a bare `elif existing ...`, so
                 `set-disposition <prd> <finding> pending` -- the one disposition
                 needing no --rationale -- resolves the item. A third exit from a
                 ledger `no-orphan-findings.md` says has exactly two.
  no ledger lock the fan-out's read-then-append is unlocked across processes, so
                 concurrent deferrals of one finding each read "no such item".
A FOURTH was CLAIMED here and is RETRACTED. I asserted findings_writer had the
same unlocked read-modify-rewrite that lost a triage decision on the kipi-dsse
twin (5 of 15 trials), on the strength of `grep flock findings_writer.py`
returning nothing. It takes `judgment_compiler.ledger_lock(cfg)` UNCONDITIONALLY
across the read, the mutation and the write -- Codex major, PR #103 round 5,
whose own reproducer is quoted in the comment there. Measured before retracting:
12 workers x 40 trials, 0 lost updates, 0 truncated reads.

Grepping ONE file for `flock` was a claim about the whole lock mechanism, and it
was wrong. prd-os is AHEAD of kipi-dsse here; the `_findings_lock` added to
issue_findings.py in ASK-429 was re-deriving a fix this file already had.

Nothing here touches a real ledger: every test builds its own repo under
tmp_path, with `.git` a plain directory so the git-common-dir lookup fails and
falls back to that root.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
WRITER = SCRIPTS / "findings_writer.py"

PRD = "prd-parity-demo"
# Long enough that a write-time cap would be visible, and distinct per hole.
BODY = ("a real PRD finding that is not being fixed in this slice: the ledger "
        "row is the artifact a human triages from, so anything lost here is "
        "lost to whoever triages it next")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    for sub in (".prd-os/findings", ".prd-os/prds", ".claude/state"):
        (r / sub).mkdir(parents=True, exist_ok=True)
    (r / ".git").mkdir()
    (r / ".prd-os" / "config.json").write_text(json.dumps({
        "config_schema_version": 1,
        "prds_dir": ".prd-os/prds",
        "issues_dir": ".prd-os/issues",
        "findings_dir": ".prd-os/findings",
        "state_dir": ".claude/state",
    }))
    (r / ".prd-os" / "findings" / f"{PRD}-findings.jsonl").write_text(
        _rec("finding-1", "major") + _rec("finding-2", "nit"))
    return r


def _rec(fid: str, severity: str) -> str:
    # Field set copied from a PRODUCER-written record, not invented.
    return json.dumps({
        "id": fid, "prd_id": PRD, "source": "claude-review",
        "severity": severity, "disposition": "pending", "body": BODY,
        "affected_path": "plugins/prd-os/scripts/findings_writer.py",
        "out_of_scope": False, "created_at": "2026-08-06T00:00:00Z",
    }) + "\n"


def _env(repo: Path) -> dict:
    e = dict(os.environ)
    e["CLAUDE_PROJECT_DIR"] = str(repo)
    # The judgment-compiler gate is a separate concern with its own tests; this
    # file is about the ledger fan-out. Left ON would make every case here
    # depend on reason-code validation that has nothing to do with the defect.
    e["KIPI_JUDGMENT_CAPTURE"] = "0"
    return e


def disposition(repo: Path, value: str, rationale: str | None = "out of scope here",
                finding_id: str = "finding-1", **kw):
    cmd = [sys.executable, str(WRITER), "set-disposition", PRD, finding_id, value]
    if rationale:
        cmd += ["--rationale", rationale]
    return subprocess.run(cmd, capture_output=True, text=True,
                          cwd=str(repo), env=_env(repo), **kw)


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


def findings_records(repo: Path) -> list[dict]:
    p = repo / ".prd-os" / "findings" / f"{PRD}-findings.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


SID = f"defer-{PRD}-finding-1"


def test_control_deferring_creates_an_open_item(repo: Path):
    """Control. If this is red the fixture is wrong, not the code."""
    result = disposition(repo, "deferred")
    assert result.returncode == 0, f"set-disposition failed: {result.stderr!r}"
    assert SID in spillover(repo), f"ledger={list(spillover(repo))}"
    assert spillover(repo)[SID]["status"] == "open"


def test_a_deferred_nit_does_not_turn_the_standing_gate_red(repo: Path, monkeypatch):
    """HOLE 1. Asserted against prd_runner's OWN decider, not a restatement."""
    result = disposition(repo, "deferred", finding_id="finding-2")
    assert result.returncode == 0, f"defer failed: {result.stderr!r}"
    item = spillover(repo)[f"defer-{PRD}-finding-2"]

    monkeypatch.syspath_prepend(str(SCRIPTS))
    from prd_runner import _is_blocking_severity

    assert not _is_blocking_severity(item["severity"]), (
        f"a deferred `nit` landed in the ledger as severity {item['severity']!r}, "
        "which the standing gate treats as BLOCKING. The gate goes red over the "
        "least important finding a reviewer can file.")


def test_every_prd_severity_maps_into_the_ledger_vocabulary(repo: Path, monkeypatch):
    """Drift guard. Fails when a severity is added with no ledger translation,
    instead of waiting for someone to defer one."""
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import findings_writer
    from prd_runner import (FINDING_TO_LEDGER_SEVERITY,
                            SPILLOVER_KNOWN_SEVERITIES)

    # Asserted against the CANONICAL table in prd_runner, not a copy in
    # findings_writer. A second table here would be the derivation split
    # sp-a05c37a4 records, recreated by the change meant to fix it.
    unmapped = [s for s in findings_writer.SEVERITIES
                if FINDING_TO_LEDGER_SEVERITY.get(s) not in SPILLOVER_KNOWN_SEVERITIES]
    assert not unmapped, (
        f"PRD severities with no ledger translation: {unmapped}. An unknown "
        "severity reaches the gate as BLOCKING.")


def test_moving_back_to_pending_does_not_clear_the_item(repo: Path):
    """HOLE 2. Undeciding is not resolving."""
    disposition(repo, "deferred")
    assert spillover(repo)[SID]["status"] == "open"
    result = disposition(repo, "pending", rationale=None)
    assert result.returncode == 0, f"pending failed: {result.stderr!r}"
    item = spillover(repo)[SID]
    assert item["status"] == "open", (
        "moving a deferred finding back to `pending` resolved its spillover item "
        "with no rationale and no closed issue -- a third way out of a ledger "
        f"that has exactly two.\n  item={item!r}")


def test_the_fanout_takes_the_ledger_lock(repo: Path):
    """HOLE 3, deterministic in both directions."""
    import fcntl
    import time

    lock_path = repo / ".prd-os" / "spillover.jsonl.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        with pytest.raises(subprocess.TimeoutExpired):
            disposition(repo, "deferred", timeout=5)
    assert SID not in spillover(repo), (
        "the fan-out appended straight through a held LOCK_EX, so it never asks "
        "for the lock at all")
    # CONTROL. "Did not finish in 5s" is satisfied by ANY slowness -- a slow
    # `git rev-parse --git-common-dir` on PATH stalls past 5s by itself, and a
    # shim demonstrated exactly that against the kipi-dsse twin. Timing the
    # unlocked run separates "blocked on the lock" from "slow generally".
    t0 = time.monotonic()
    result = disposition(repo, "deferred", timeout=30)
    elapsed = time.monotonic() - t0
    assert result.returncode == 0, f"unlocked run failed: {result.stderr!r}"
    assert elapsed < 4, (
        f"the unlocked run took {elapsed:.1f}s, so the timeout above does not "
        "distinguish waiting on the lock from being slow for another reason")


def test_concurrent_dispositions_of_different_findings_all_land(repo: Path):
    """PARITY GUARD, not a reproducer -- this passes against today's code.

    Kept deliberately: it is green because `judgment_compiler.ledger_lock` is
    taken unconditionally, and it goes red the moment someone makes that lock
    conditional again (the pre-sp-0c725cde shape used a nullcontext when
    judgment capture was disabled, which is why this fixture sets
    KIPI_JUDGMENT_CAPTURE=0 -- it exercises exactly the branch that used to skip
    the lock).

    THIS GUARD IS UNPROVEN, and saying so is the point. I tried to mutation-check
    it by restoring a30311f6's pre-sp-0c725cde shape (`ledger_lock` when judgment
    capture is on, `contextlib.nullcontext()` when off) and the harness reported
    the mutant SEMANTICALLY EQUIVALENT: its probe held a lock at a GUESSED path,
    so the axis was dead and baseline and mutant looked identical. That is a
    defect in my probe, not evidence about the lock.

    So: this test passes today, and nothing yet demonstrates it would fail if the
    lock were re-conditionalized. Tracked rather than asserted -- an unverified
    "mutation-checked" line here would be the same false receipt this whole
    session has been retracting.
    """
    import concurrent.futures

    path = repo / ".prd-os" / "findings" / f"{PRD}-findings.jsonl"
    ids = [f"finding-{i}" for i in range(1, 7)]

    for trial in range(8):
        path.write_text("".join(_rec(i, "minor") for i in ids))
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(ids)) as pool:
            res = dict(zip(ids, pool.map(
                lambda f: disposition(repo, "rejected", "race probe", finding_id=f),
                ids)))
        on_disk = {r["id"]: r["disposition"] for r in findings_records(repo)}
        for fid, r in res.items():
            assert r.returncode == 0, f"trial {trial} {fid}: {r.stderr!r}"
            assert on_disk.get(fid) == "rejected", (
                f"trial {trial}: `set-disposition {fid} rejected` exited 0 and "
                f"printed success, but disk says {on_disk.get(fid)!r}. A "
                "concurrent writer rewrote the file from a stale read, so a "
                "triage decision was silently dropped.")
