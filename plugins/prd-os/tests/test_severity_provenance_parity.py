"""ASK-465 reproducer: the two producers that write the most consequential rows
into the spillover ledger do not stamp `severity_source`, so a reviewer-assessed
finding lands in the `unknown` bucket.

ASK-430 shipped the field and `spillover add`/`reclassify` populate it. The
`defer-*` rows do not, and those are the ones that matter most: their severity is
TRANSLATED from a severity a human reviewer actually assigned.

WHY THIS IS URGENT RATHER THAN TIDY. Measured on the live ledger 2026-08-06,
immediately after ASK-430 landed: 600 open non-blocking items split 2 assessed /
0 untriaged / 598 unknown. The 598 are honest -- they predate the field. But
every reviewer-deferred finding from here also lands in `unknown`, so the bucket
stops meaning "predates the field" and starts meaning "predates the field, OR a
reviewer assessed it and we dropped that on the floor". A leak in a measurement
is hardest to see once the measurement has been running a while.

THE DERIVATION TEST is `test_writers_derive_the_constant_from_prd_runner`. Both
writers already import prd_runner's ledger helpers; the provenance constant has
to come the same way. A restated `"explicit"` literal in either file passes every
other test here and drifts the first time the vocabulary changes -- which is the
exact failure FINDING_TO_LEDGER_SEVERITY's placement comment warns about. It
monkeypatches the OWNER's constant and asserts the writer's output follows,
because "it imports it" is a claim about behaviour that a grep for the import
line cannot make.

Import direction is load-bearing and one-way: prd-os owns this ledger, so
consumers import from prd_runner. prd-os must never reach into kipi-dsse or
q-system for a severity vocabulary -- that trades one derivation split for a
worse one. (kipi-dsse's issue_findings.py:104 already keeps a LOCAL
`LEDGER_SEVERITY` duplicating prd-os's FINDING_TO_LEDGER_SEVERITY. That split is
real, pre-existing, and deliberately NOT fixed here.)

No test touches the live ledger: every one builds its own repo under tmp_path.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PRD_OS = Path(__file__).resolve().parents[1]
DSSE = PRD_OS.parents[0] / "kipi-dsse"
PRD_RUNNER = PRD_OS / "scripts" / "prd_runner.py"
FINDINGS_WRITER = PRD_OS / "scripts" / "findings_writer.py"
ISSUE_FINDINGS = DSSE / "scripts" / "issue_findings.py"
PRD_ID = "prd-parity-2026-08-06"
ISSUE_ID = "iss-parity-01"


def _run(script: Path, repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), "--repo-root", str(repo), *args],
        capture_output=True, text=True)


def _load(path: Path, name: str):
    for d in (PRD_OS / "scripts", DSSE / "scripts"):
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # REGISTER BEFORE EXEC, same reason conftest.py does it for config.py:
    # @dataclass resolves string annotations by looking up cls.__module__ in
    # sys.modules, so an unregistered module raises
    # "AttributeError: 'NoneType' object has no attribute '__dict__'" from
    # inside dataclasses.py -- a setup failure that looks nothing like the
    # provenance defect these tests are about.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


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


def seed_finding(repo: Path, finding_id: str = "finding-1",
                 severity: str = "major") -> None:
    d = repo / ".prd-os" / "findings"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{PRD_ID}-findings.jsonl").write_text(json.dumps({
        "id": finding_id, "prd_id": PRD_ID, "source": "codex-review",
        "severity": severity, "disposition": "pending",
        "body": "obsidian export reads canonical without an archive filter",
        "created_at": "2026-08-06T00:00:00Z",
    }) + "\n")


def defer(repo: Path, finding_id: str = "finding-1"):
    return _run(FINDINGS_WRITER, repo, "set-disposition", PRD_ID, finding_id,
                "deferred", "--rationale", "tracked separately")


def spill(repo: Path) -> list:
    r = _run(PRD_RUNNER, repo, "spillover", "list", "--json")
    return json.loads(r.stdout) if r.stdout.strip() else []


def only_defer_row(repo: Path) -> dict:
    rows = [i for i in spill(repo) if i["id"].startswith("defer-")]
    assert len(rows) == 1, f"expected one defer-* row, got {[r['id'] for r in rows]}"
    return rows[0]


# --------------------------------------------------------------------------
# GREEN CONTROL: must pass before AND after. If this goes red with the rest,
# the fixture is broken and every RED below is uninformative.
# --------------------------------------------------------------------------

def test_control_deferral_still_creates_an_open_row_with_translated_severity(repo):
    seed_finding(repo, severity="major")
    assert defer(repo).returncode == 0
    row = only_defer_row(repo)
    assert row["status"] == "open"
    assert row["severity"] == "major"


# --------------------------------------------------------------------------
# DELIVERABLE 1: findings_writer stamps explicit.
# --------------------------------------------------------------------------

def test_findings_writer_deferral_stamps_explicit(repo):
    seed_finding(repo)
    assert defer(repo).returncode == 0
    assert only_defer_row(repo)["severity_source"] == "explicit"


def test_findings_writer_deferral_does_not_read_as_unknown(repo):
    """Through the READER, not the raw key: `unknown` is what the gates-run
    report counts, and that count is the thing degrading."""
    runner = _load(PRD_RUNNER, "runner_parity_a")
    seed_finding(repo)
    defer(repo)
    assert runner.severity_source(only_defer_row(repo)) == "explicit"


def test_a_reviewer_assessed_deferral_is_reported_as_assessed(repo):
    """End to end at the surface an operator reads. The `defer-*` row is
    non-blocking after translation only for minor/nit, so use a `nit`: it is the
    case where a reviewer's judgement is most likely to be mistaken for nobody
    having looked."""
    seed_finding(repo, severity="nit")
    defer(repo)
    out = _run(PRD_RUNNER, repo, "gates", "run").stdout
    assert "1 assessed" in out
    assert "1 unknown" not in out


# --------------------------------------------------------------------------
# DELIVERABLE 2: issue_findings (kipi-dsse) stamps explicit, identically.
# Called at the function the DoR names. Both writers fan into ONE ledger, so a
# rule applied at one of them is a drift, not a fix.
# --------------------------------------------------------------------------

def test_issue_findings_deferral_stamps_explicit(repo):
    mod = _load(ISSUE_FINDINGS, "issue_findings_parity")
    mod._sync_spillover_for_finding(repo, ISSUE_ID, {
        "id": "finding-9", "severity": "major", "disposition": "deferred",
        "body": "a real defect deferred by a reviewer"})
    row = only_defer_row(repo)
    assert row["severity"] == "major"
    assert row["severity_source"] == "explicit"


def test_both_writers_agree_on_provenance(repo, tmp_path):
    """Parity is the property. Two writers, one ledger, one answer."""
    seed_finding(repo)
    defer(repo)
    prd_row = only_defer_row(repo)

    other = tmp_path / "repo2"
    (other / ".prd-os").mkdir(parents=True)
    (other / ".git").mkdir()
    (other / ".prd-os" / "config.json").write_text(
        (repo / ".prd-os" / "config.json").read_text())
    mod = _load(ISSUE_FINDINGS, "issue_findings_parity_b")
    mod._sync_spillover_for_finding(other, ISSUE_ID, {
        "id": "finding-9", "severity": "major", "disposition": "deferred",
        "body": "a real defect deferred by a reviewer"})
    dsse_row = only_defer_row(other)
    assert prd_row["severity_source"] == dsse_row["severity_source"] == "explicit"


# --------------------------------------------------------------------------
# DELIVERABLE 3: the writers DERIVE the constant, they do not restate it.
# --------------------------------------------------------------------------

def test_writers_derive_the_constant_from_prd_runner(repo, tmp_path, monkeypatch):
    """Move the OWNER's constant; both writers' output must move with it.

    A restated `"explicit"` literal in either file passes every other test in
    this module and drifts silently the first time the vocabulary changes. This
    is the difference between "it imports the name" (a grep) and "its output is
    derived from that name" (a behaviour). Both writers import prd_runner INSIDE
    the function, so patching the module attribute reaches them.
    """
    runner = _load(PRD_RUNNER, "prd_runner")  # bind under its import name
    monkeypatch.setitem(sys.modules, "prd_runner", runner)
    monkeypatch.setattr(runner, "SEVERITY_SOURCE_EXPLICIT", "sentinel-derived")

    writer = _load(FINDINGS_WRITER, "findings_writer_derivation")
    cfg_mod = _load(PRD_OS / "scripts" / "config.py", "config_derivation")
    seed_finding(repo)
    writer._sync_spillover_for_finding(
        cfg_mod.load(repo, strict=True), PRD_ID,
        {"id": "finding-1", "severity": "major", "disposition": "deferred",
         "body": "b"})
    assert only_defer_row(repo)["severity_source"] == "sentinel-derived", (
        "findings_writer restated the literal instead of importing it")

    other = tmp_path / "repo3"
    (other / ".prd-os").mkdir(parents=True)
    (other / ".git").mkdir()
    (other / ".prd-os" / "config.json").write_text(
        (repo / ".prd-os" / "config.json").read_text())
    dsse = _load(ISSUE_FINDINGS, "issue_findings_derivation")
    dsse._sync_spillover_for_finding(other, ISSUE_ID, {
        "id": "finding-9", "severity": "major", "disposition": "deferred",
        "body": "b"})
    assert only_defer_row(other)["severity_source"] == "sentinel-derived", (
        "issue_findings restated the literal instead of importing it")


# --------------------------------------------------------------------------
# DELIVERABLE 4: the triage lens shows provenance.
# `gates run`'s own next-step line sends the operator here.
# --------------------------------------------------------------------------

def test_triage_lens_groups_by_provenance(repo):
    _run(PRD_RUNNER, repo, "spillover", "add", "--source", "s",
         "--desc", "nobody looked in prd_runner.py", "--id", "sp-t0000001")
    _run(PRD_RUNNER, repo, "spillover", "add", "--source", "s",
         "--desc", "judged small in prd_runner.py", "--severity", "minor", "--id", "sp-t0000002")
    out = _run(PRD_RUNNER, repo, "spillover", "triage").stdout
    assert "by severity_source" in out, (
        "gates run splits assessed/untriaged/unknown and then points the "
        "operator at `spillover triage`; arriving here must not lose it")
    assert "explicit" in out and "default" in out


def test_triage_lens_shows_legacy_rows_as_unset_not_assessed(repo):
    """A pre-field row groups under an unset bucket. The lens must not imply
    somebody looked -- same honesty rule as the reader (ASK-430 deliverable 3)."""
    led = repo / ".prd-os" / "spillover.jsonl"
    led.write_text(json.dumps({
        "id": "sp-legacy99", "source": "old", "description": "legacy row",
        "severity": "minor", "status": "open"}) + "\n")
    out = _run(PRD_RUNNER, repo, "spillover", "triage").stdout
    assert "by severity_source" in out
    assert "explicit" not in out
