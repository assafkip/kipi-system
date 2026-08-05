"""A receipt is written ONLY by the code that computed it.

The class, named by the founder 2026-08-05 after `mark verified` was shown to
succeed with zero checks run: **code that RECORDS a claim it never COMPUTED.**
Three instances lived in this repo while the system's own core rule says
enforcement requires executable code, never prose.

The rule these tests pin:

    There is no standalone "mark it done" verb. Whoever does the work writes
    the receipt, and the receipt carries the evidence that the work happened.

  verified          <- `verify` RUNS required_checks and records rc per command
  findings_triaged  <- `triage` COMPUTES pending==0 from the findings ledger
  reviewed          <- `record-review` writes it when a review round is recorded

The counter-examples that prove this was always achievable, all pre-existing:
`prd_runner.py gates run` subprocesses each bypass_check and reads the return
code; the judgment compiler's evidence gate resolves refs against real records;
this file's own scope check subprocesses git.

Fixtures come from producers: the issue spec under test is rendered by
`prd_split.py` from a real PRD, never hand-written.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

DSSE = Path(__file__).resolve().parent
PRDOS = DSSE.parents[1] / "prd-os/scripts"  # plugins/prd-os/scripts


def _run(repo: Path, script: Path, *args: str, env_extra=None):
    env = dict(os.environ)
    for leak in ("CLAUDE_PROJECT_DIR", "KIPI_HOME", "QROOT"):
        env.pop(leak, None)
    env.setdefault("PYTHONPATH", str(PRDOS))
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, str(script), *args],
                          cwd=repo, capture_output=True, text=True, env=env)


def _issue(repo: Path, *args, **kw):
    return _run(repo, DSSE / "issue_runner.py", *args, **kw)


@pytest.fixture()
def loaded_issue(tmp_path: Path) -> Path:
    """A virgin repo with one approved PRD split into one in-progress issue.

    The required_check is chosen to PASS so the honest path is exercised; the
    failing-check case gets its own repo inside its test.
    """
    return _make_repo(tmp_path, check="python3 -c \"print('ok')\"")


def _make_repo(tmp_path: Path, check: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["init", "-q"], ["config", "user.email", "t@t.co"],
                ["config", "user.name", "t"]):
        subprocess.run(["git", *cmd], cwd=repo, capture_output=True)
    (repo / "README.md").write_text("# t\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, capture_output=True)

    assert _run(repo, PRDOS / "prd_os_init.py").returncode == 0
    created = _run(repo, PRDOS / "prd_runner.py", "new", "probe", "--title", "T")
    assert created.returncode == 0, f"prd new failed: {created.stderr}"
    prd_id = json.loads(created.stdout)["created"]
    spec = repo / ".prd-os/prds" / f"{prd_id}.md"

    manifest = json.dumps([{
        "id": "probe-1", "title": "Probe", "allowed_files": ["README.md"],
        "required_checks": [check], "acceptance": "a",
        "finding_id": "finding-1",
        "bypass_check": "python3 -c \"print('no bypass')\"",
    }], indent=2)
    body = spec.read_text()
    marker = "\n## Issues"
    at = body.index(marker) + len(marker)
    spec.write_text(body[:at] + "\n\n```json\n" + manifest + "\n```\n" + body[at:])

    assert _run(repo, PRDOS / "prd_runner.py", "advance", "draft").returncode == 0
    add = subprocess.run(
        [sys.executable, str(PRDOS / "findings_writer.py"), "add", prd_id,
         "--source", "claude-review"],
        cwd=repo, capture_output=True, text=True,
        input='[{"severity":"major","body":"probe"}]')
    assert add.returncode == 0, add.stderr
    assert _run(repo, PRDOS / "findings_writer.py", "set-disposition", prd_id,
                "finding-1", "accepted", "--reason-code", "valid-fix-now",
                "--actor", "t").returncode == 0
    assert _run(repo, PRDOS / "prd_runner.py", "advance", "in-review").returncode == 0
    assert _run(repo, PRDOS / "prd_runner.py", "advance", "approved").returncode == 0
    assert _run(repo, PRDOS / "prd_split.py").returncode == 0
    assert _run(repo, PRDOS / "prd_runner.py", "clear").returncode == 0
    assert _issue(repo, "load", "probe-1").returncode == 0
    assert _issue(repo, "approve").returncode == 0
    return repo


def _receipts(repo: Path) -> dict:
    return json.loads(_issue(repo, "status").stdout).get("receipts", {})


# ---------------------------------------------------------------------------
# The rule: no standalone mark verb
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("receipt", ["verified", "reviewed", "findings_triaged"])
def test_mark_refuses_every_receipt_field(loaded_issue: Path, receipt: str):
    """Proven 2026-08-05 against the shipped runner: all three stamped with
    zero work done, exit 0 each. A receipt that can be asserted is not a
    receipt."""
    proc = _issue(loaded_issue, "mark", receipt)
    assert proc.returncode != 0, (
        f"`mark {receipt}` still writes a receipt on the caller's word"
    )
    assert not _receipts(loaded_issue).get(receipt), "receipt was written anyway"


@pytest.mark.parametrize("receipt,verb", [
    ("verified", "verify"),
    ("findings_triaged", "triage"),
    ("reviewed", "record-review"),
])
def test_mark_names_the_verb_that_computes_it(loaded_issue: Path, receipt, verb):
    """A refusal that does not teach the replacement gets routed around."""
    proc = _issue(loaded_issue, "mark", receipt)
    assert verb in (proc.stderr + proc.stdout), (
        f"refusal for {receipt} does not name `{verb}`: {proc.stderr!r}"
    )


# ---------------------------------------------------------------------------
# verified <- the checks actually run
# ---------------------------------------------------------------------------

def test_verify_runs_the_checks_and_records_the_evidence(loaded_issue: Path):
    proc = _issue(loaded_issue, "verify")
    assert proc.returncode == 0, proc.stderr
    state = json.loads(_issue(loaded_issue, "status").stdout)
    assert state["receipts"]["verified"], "verify did not write the receipt"
    ev = state.get("verified_evidence")
    assert ev, "no evidence recorded; the receipt is still an assertion"
    assert len(ev) == 1
    assert ev[0]["returncode"] == 0
    assert ev[0]["command"]
    assert ev[0].get("output_sha256"), "no output hash; the run is unreproducible"


def test_verify_refuses_and_writes_nothing_when_a_check_fails(tmp_path: Path):
    repo = _make_repo(tmp_path, check="python3 -c \"import sys; sys.exit(3)\"")
    proc = _issue(repo, "verify")
    assert proc.returncode != 0, "verify passed while its required_check exited 3"
    assert not _receipts(repo).get("verified"), (
        "verify wrote the receipt for a failing check"
    )


def test_verify_records_the_failing_returncode_not_just_a_refusal(tmp_path: Path):
    """The evidence must survive the failure, or a red run teaches nothing."""
    repo = _make_repo(tmp_path, check="python3 -c \"import sys; sys.exit(3)\"")
    _issue(repo, "verify")
    ev = json.loads(_issue(repo, "status").stdout).get("verified_evidence") or []
    assert ev and ev[0]["returncode"] == 3, f"failing rc not recorded: {ev}"


# ---------------------------------------------------------------------------
# findings_triaged <- computed from the ledger
# ---------------------------------------------------------------------------

def _add_pending_finding(repo: Path) -> Path:
    """Put one pending in-scope finding in the ISSUE's findings ledger.

    The path is DERIVED from the runner, not guessed: when config sets
    `findings_dir`, `Paths` appends an `issue/` subdir, so the ledger is
    `.prd-os/findings/issue/`. An earlier draft hardcoded a guess one directory
    up (and had a `or next(glob("*.jsonl"))` fallback that silently picked the
    PRD's findings file instead), so the test passed while "a pending finding"
    sat somewhere nobody read. No fallback: a wrong path now fails loudly.
    """
    sys.path.insert(0, str(DSSE))
    try:
        import issue_runner
        target = issue_runner.Paths(repo).findings_dir / "probe-1-findings.jsonl"
    finally:
        sys.path.pop(0)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "id": "finding-99", "severity": "major", "body": "still pending",
        "disposition": "pending", "source": "claude-review",
    }) + "\n")
    return target


def test_gate_refuses_while_an_in_scope_finding_is_pending(loaded_issue: Path):
    """`cmd_gate`'s pending branch had NO coverage until this test.

    Found by accident: a mutation aimed at `cmd_triage` hit `cmd_gate`'s
    identical `if pending or bad:` first (replace with count=1) and survived
    all 58 kipi-dsse tests. The stop gate could stop refusing on pending
    findings and nothing would notice.

    All three receipts are earned FIRST so the refusal can only come from the
    pending branch -- otherwise the missing-receipts branch would refuse and
    this test would pass without ever reaching the line it exists to cover.
    """
    assert _issue(loaded_issue, "verify").returncode == 0
    assert _issue(loaded_issue, "triage").returncode == 0
    assert _issue(loaded_issue, "record-review", "standard").returncode == 0
    assert _issue(loaded_issue, "gate").returncode == 0, "precondition: gate green"

    _add_pending_finding(loaded_issue)

    proc = _issue(loaded_issue, "gate")
    assert proc.returncode != 0, (
        "stop gate allowed the session to end with an in-scope finding pending"
    )
    assert "pending" in (proc.stderr + proc.stdout).lower(), (
        f"gate refused but did not name the pending findings: {proc.stderr!r}"
    )


def test_triage_refuses_while_an_in_scope_finding_is_pending(loaded_issue: Path):
    """`_count_in_scope_pending` already existed and was used as a close-time
    gate while the receipt stayed hand-stamped. Same computation, now the
    writer."""
    _add_pending_finding(loaded_issue)

    proc = _issue(loaded_issue, "triage")
    assert proc.returncode != 0, "triage wrote the receipt with a pending finding"
    assert not _receipts(loaded_issue).get("findings_triaged")


def test_triage_writes_the_receipt_when_nothing_is_pending(loaded_issue: Path):
    proc = _issue(loaded_issue, "triage")
    assert proc.returncode == 0, proc.stderr
    assert _receipts(loaded_issue)["findings_triaged"]


# ---------------------------------------------------------------------------
# reviewed <- written by the verb that records the review
# ---------------------------------------------------------------------------

def test_record_review_writes_the_reviewed_receipt(loaded_issue: Path):
    assert not _receipts(loaded_issue).get("reviewed")
    proc = _issue(loaded_issue, "record-review", "standard")
    assert proc.returncode == 0, proc.stderr
    assert _receipts(loaded_issue)["reviewed"], (
        "recording a review round did not write the receipt it attests to"
    )


# ---------------------------------------------------------------------------
# Env bypasses must be counted, not silent
# ---------------------------------------------------------------------------

def test_gate_off_is_recorded_not_silent(loaded_issue: Path):
    """`ISSUE_GATE_OFF=1` is agent-settable, which breaks the fleet's own
    "an agent cannot set it for itself" principle. Making it un-settable is not
    possible from inside the process, so the fallback is the linear-bypass
    pattern: every use leaves a countable row."""
    proc = _issue(loaded_issue, "gate", env_extra={"ISSUE_GATE_OFF": "1"})
    assert proc.returncode == 0
    ledger = loaded_issue / ".prd-os/gate-bypasses.jsonl"
    assert ledger.is_file(), "gate bypass left no trace"
    rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    assert rows and rows[-1]["env"] == "ISSUE_GATE_OFF"
    assert rows[-1].get("issue_id") == "probe-1"


def test_gate_without_the_override_writes_no_bypass_row(loaded_issue: Path):
    """Negative-fire: the ledger must count real bypasses only."""
    _issue(loaded_issue, "gate")
    assert not (loaded_issue / ".prd-os/gate-bypasses.jsonl").exists()
