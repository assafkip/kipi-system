"""ASK-1961: the minor tier is not a queue, and the rule file says what the code does.

Measured 2026-09-22 on kipi-system: 618 open minor/low rows (last row per id wins),
zero inflow since 2026-09-12 (`spillover add` refuses minor, low and nit), and
no outflow built for them. `gates run` already never let them block, yet its
`[REPORT]` line listed them as items to triage, so a 618-row "queue" with no
drain printed on every run. And no-orphan-findings.md still said "`gates run`
fails while any item is open", which the code stopped doing at ASK-526.

The decision (RULE-2026-09-12-A applied to the rows written before it): the
legacy minor tier is a closed tier, not a queue. `gates run` does not count it
in the verdict or in the triage report; it states the tier's size on one line
so the number never goes quiet.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
PRD_RUNNER = PLUGIN_ROOT / "scripts" / "prd_runner.py"
RULE_FILE = REPO_ROOT / ".claude" / "rules" / "no-orphan-findings.md"


def _load_runner():
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("prd_runner_minor_tier", PRD_RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


def _seed(repo: Path, sid: str, severity: str) -> None:
    ledger = repo / ".prd-os" / "spillover.jsonl"
    rec = {"id": sid, "source": "s", "description": f"{severity} row", "severity": severity,
           "status": "open", "created_at": "2026-09-01T00:00:00Z", "owner": "sana"}
    with ledger.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")


def _gates_run(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PRD_RUNNER), "--repo-root", str(repo), "gates", "run"],
        capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    # Same shape as test_spillover.py's fixture: a config and a .git marker.
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


def _report_line(out: str) -> str:
    lines = [line for line in out.splitlines() if line.startswith("[REPORT] spillover")]
    return lines[0] if lines else ""


def test_the_triage_report_does_not_list_the_closed_minor_tier(repo):
    _seed(repo, "sp-minor", "minor")
    _seed(repo, "sp-low", "low")
    _seed(repo, "sp-medium", "medium")
    g = _gates_run(repo)
    out = g.stdout
    assert g.returncode == 0, f"a non-blocking tier turned the gate red:\n{out}{g.stderr}"
    report = _report_line(out)
    assert "sp-medium" in report, f"a medium is triage work and left the report:\n{out}"
    assert "sp-minor" not in report and "sp-low" not in report, (
        f"the closed minor tier is still listed as triage work:\n{out}")


def test_the_closed_tier_is_counted_on_one_line_never_silent(repo):
    _seed(repo, "sp-minor", "minor")
    _seed(repo, "sp-low", "low")
    out = _gates_run(repo).stdout
    tier = [line for line in out.splitlines() if "not a queue" in line]
    assert tier and " 2 " in tier[0], f"the closed tier left the screen:\n{out}"
    assert "2 open total" in out, (
        f"the census stopped stating the ledger total:\n{out}")


def test_a_closed_tier_row_with_no_severity_is_still_counted(repo):
    """An absent severity is the documented `minor` default (_is_blocking_severity)."""
    ledger = repo / ".prd-os" / "spillover.jsonl"
    ledger.write_text(json.dumps({"id": "sp-bare", "source": "s", "description": "d",
                                  "status": "open"}) + "\n")
    out = _gates_run(repo).stdout
    assert "sp-bare" not in _report_line(out)
    assert any("not a queue" in line and " 1 " in line for line in out.splitlines()), out


@pytest.mark.xfail(strict=True, reason=(
    "ASK-1961: the harness refused the edit to .claude/rules/no-orphan-findings.md "
    "as a sensitive file; the proposed text is in the PR body. strict: once the "
    "rule is edited this XPASSes and fails, so the marker cannot outlive the gap."))
def test_the_rule_file_and_the_code_agree():
    """Derived from the constants the gate reads, never restated here."""
    text = RULE_FILE.read_text()
    assert "fails while any item is open" not in text, (
        "the rule still claims every open item turns `gates run` red")
    for sev in RUNNER.SPILLOVER_BLOCKING_SEVERITIES:
        assert f"`{sev}`" in text, f"rule does not name blocking severity {sev}"
    for sev in RUNNER.SPILLOVER_CLOSED_TIER:
        assert f"`{sev}`" in text, f"rule does not name closed-tier severity {sev}"
    assert "not a queue" in text


def test_the_closed_tier_is_exactly_the_refused_tier_the_ledger_can_hold():
    """Closed tier = what the add door refuses, restricted to severities a row can carry."""
    assert RUNNER.SPILLOVER_CLOSED_TIER, "empty tier makes every check above vacuous"
    expected = tuple(s for s in RUNNER.SPILLOVER_REFUSED_SEVERITIES
                     if s in RUNNER.SPILLOVER_KNOWN_SEVERITIES)
    assert RUNNER.SPILLOVER_CLOSED_TIER == expected
