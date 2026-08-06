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

# 191 chars, ON PURPOSE. The historical defect this suite's whole-body test names
# is `str(finding.get('body',''))[:120]` (findings_writer, removed in d8698523).
# The first fixture body here was 51 chars, so restoring that exact cap left the
# test GREEN -- and the commit that shipped this suite claimed "5/5 mutants
# killed" on the strength of a `[:12]` mutant instead, which is a cap the short
# body could see. A regression test whose fixture is smaller than the bound it
# guards is decoration.
#
# Truncating this at 120 cuts mid-WORD ("a descripti|on"), so a survivor is
# visible in the failure message rather than needing arithmetic to spot.
BODY = ("a real defect that is not being fixed in this slice: the ledger row is the "
        "artifact a human triages from, so a description that stops mid-clause is "
        "unactionable and lands at the minor default")
EXPECTED_DESCRIPTION = f"deferred issue finding finding-1: {BODY}"


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
    def rec(fid: str, severity: str) -> str:
        return json.dumps({
            "id": fid, "issue_id": ISSUE, "severity": severity,
            "body": BODY,
            "source": "claude-review", "disposition": "pending",
            # Field set taken from a PRODUCER-written record
            # (.prd-os/findings/issue/*-findings.jsonl, written by
            # `issue_findings.py add`), not invented. Guessing it field-by-field
            # cost two red runs whose failures were my fixture, not the defect.
            "affected_path": "plugins/kipi-dsse/scripts/issue_findings.py",
            "out_of_scope": False,
            "created_at": "2026-08-06T00:00:00Z",
        }) + "\n"

    # finding-2 is a `nit` because `nit` is a legal ISSUE severity that the
    # LEDGER's vocabulary does not contain. Fixturing only `major` kept the
    # whole severity-translation seam out of the suite.
    (r / ".prd-os" / "findings" / "issue" / f"{ISSUE}-findings.jsonl").write_text(
        rec("finding-1", "major") + rec("finding-2", "nit"))
    return r


def disposition(repo: Path, value: str, rationale: str | None = "out of scope here",
                finding_id: str = "finding-1", **kw):
    cmd = [sys.executable, str(FINDINGS), "set-disposition", ISSUE, finding_id, value]
    if rationale:
        cmd += ["--rationale", rationale]
    return subprocess.run(cmd, capture_output=True, text=True,
                          cwd=str(repo), env=_env(repo), **kw)


def findings_records(repo: Path) -> list[dict]:
    p = repo / ".prd-os" / "findings" / "issue" / f"{ISSUE}-findings.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


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
    what they cannot read.

    Asserts the LITERAL whole description, not `expected in desc`. A containment
    check on a substring the cap does not reach passes against the defect, which
    is how the first version of this test shipped green with `[:120]` restored.
    """
    disposition(repo, "deferred")
    desc = spillover(repo)[SID].get("description", "")
    assert desc == EXPECTED_DESCRIPTION, (
        "the ledger row is not the whole finding body. A write-time cap "
        f"(historically `[:120]`) truncates it.\n  got {len(desc)} chars: {desc!r}\n"
        f"  want {len(EXPECTED_DESCRIPTION)} chars: {EXPECTED_DESCRIPTION!r}")


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


def test_moving_back_to_pending_does_not_clear_the_item(repo: Path):
    """`pending` is the ABSENCE of a decision, so it must not empty the ledger.

    The reverse-transition branch resolved the item for every non-`deferred`
    value, and `pending` is the one that needs no --rationale. So
    `set-disposition <iss> <finding> pending` was a one-command, unexplained
    THIRD way out of the ledger -- the thing `no-orphan-findings.md` (the file
    this change edits) says does not exist.

    Sharpest for an OUT-OF-SCOPE finding: `count --in-scope-pending` skips it,
    so after this the finding blocked nothing and the ledger held nothing.
    """
    disposition(repo, "deferred")
    assert spillover(repo)[SID]["status"] == "open"
    result = disposition(repo, "pending", rationale=None)
    assert result.returncode == 0, f"pending failed: {result.stderr!r}"
    item = spillover(repo)[SID]
    assert item["status"] == "open", (
        "moving a deferred finding back to `pending` resolved its spillover item "
        "with no rationale and no closed issue. Undeciding is not resolving.\n"
        f"  item={item!r}")


def test_an_unwritable_ledger_fails_the_command_and_rolls_back(repo: Path):
    """A backstop that cannot write must not report success.

    The fan-out caught `Exception`, wrote a WARNING and fell through to
    `return 0`, so the exact failure it exists to prevent -- a deferred finding
    with nothing tracking it -- exited GREEN. Nothing downstream reads stderr
    for a passing command.

    Fails CLOSED both ways: non-zero exit AND the findings file restored, so the
    record does not read `deferred` while the ledger has no item for it.
    """
    (repo / ".prd-os" / "spillover.jsonl").write_text('{"id": "torn", "stat\n')
    result = disposition(repo, "deferred")
    assert result.returncode != 0, (
        "the spillover ledger could not be read, no item was created, and the "
        f"command still exited 0.\nstdout={result.stdout!r}\nstderr={result.stderr!r}")
    assert findings_records(repo)[0]["disposition"] == "pending", (
        "the command failed but the findings file still says `deferred`, so the "
        "record claims a backstop that does not exist: "
        f"{findings_records(repo)[0]!r}")


def test_a_nit_finding_does_not_turn_the_standing_gate_red(repo: Path):
    """`nit` is a legal ISSUE severity and is NOT in the LEDGER's vocabulary.

    `_is_blocking_severity` fails closed on an unknown severity (correct: ASK-402
    shipped that so `--severity critical` could not read as minor). Handing it
    `nit` therefore made deferring the most trivial finding in the system turn
    the standing gate RED fleet-wide until someone hand-resolved the row.

    Asserted against prd_runner's OWN decider, not a restatement of the rule.
    """
    result = disposition(repo, "deferred", finding_id="finding-2")
    assert result.returncode == 0, f"defer failed: {result.stderr!r}"
    item = spillover(repo)[f"defer-{ISSUE}-finding-2"]

    sys.path.insert(0, str(PRD_RUNNER.parent))
    from prd_runner import _is_blocking_severity

    assert not _is_blocking_severity(item["severity"]), (
        f"a deferred `nit` landed in the ledger as severity {item['severity']!r}, "
        "which the standing gate treats as BLOCKING. The gate goes red over the "
        "least important finding the reviewer can file.")


def test_every_issue_severity_maps_into_the_ledger_vocabulary(repo: Path):
    """Drift guard for the seam above.

    The two vocabularies are edited in different plugins by different changes;
    `nit` was legal on one side and unknown on the other for as long as both
    existed. This fails the moment a new issue severity is added without a
    ledger translation, instead of waiting for someone to defer one.
    """
    sys.path.insert(0, str(FINDINGS.parent))
    sys.path.insert(0, str(PRD_RUNNER.parent))
    import issue_findings
    from prd_runner import SPILLOVER_KNOWN_SEVERITIES

    unmapped = [s for s in issue_findings.SEVERITIES
                if issue_findings.LEDGER_SEVERITY.get(s) not in SPILLOVER_KNOWN_SEVERITIES]
    assert not unmapped, (
        f"issue severities with no ledger translation: {unmapped}. An unknown "
        "severity reaches the gate as BLOCKING, so this is a red gate waiting "
        "for someone to defer one of them.")


def test_the_fanout_serializes_on_the_ledger_lock(repo: Path):
    """The fan-out's read-modify-append must hold prd_runner's ledger lock.

    Deterministic in BOTH directions, which the trial-count test below is not:
    this holds LOCK_EX on the sibling .lock file and asserts the CLI cannot
    finish. Unlocked, it returns in well under a second.

    The idempotency test above only ever ran single-threaded, and re-deferral
    from a retrying agent is exactly the concurrent case it was standing in for.
    """
    import fcntl

    lock_path = repo / ".prd-os" / "spillover.jsonl.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        with pytest.raises(subprocess.TimeoutExpired):
            disposition(repo, "deferred", timeout=5)
    assert SID not in spillover(repo), (
        "the fan-out appended straight through a held LOCK_EX, so it never asks "
        "for the lock at all")


def test_concurrent_deferrals_of_one_finding_write_one_row(repo: Path):
    """The defect the lock exists for, measured rather than argued.

    Four processes defer the SAME finding at once. Each reads "no open item",
    each appends. Measured before the lock: duplicate open rows in 5 of 6
    trials. The fold is last-write-wins so duplicates are not a correctness
    bug -- they are unbounded growth in a ledger whose whole problem is that it
    grows, and each duplicate needs its own resolve to leave.
    """
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = [f.result() for f in
                   [pool.submit(disposition, repo, "deferred") for _ in range(4)]]
    assert all(r.returncode == 0 for r in results), \
        [r.stderr for r in results if r.returncode != 0]

    raw = (repo / ".prd-os" / "spillover.jsonl").read_text().splitlines()
    rows = [json.loads(l) for l in raw if l.strip()]
    creates = [r for r in rows if r["id"] == SID and r.get("status") == "open"]
    assert len(creates) == 1, (
        f"{len(creates)} open rows for one deferral. The idempotency check reads "
        "then appends, so without a lock every concurrent caller reads "
        f"'no such item'.\n{creates}")
