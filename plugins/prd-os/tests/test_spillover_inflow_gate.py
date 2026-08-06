"""ASK-446 reproducer: refuse a `spillover add` whose description names nothing
a reader could act on, and report the ledger's RATE rather than its level.

The ledger grows without bound and triage does not change that. Inflow is
automated (every deferred finding fans out); outflow is manual. Measured
2026-08-06: 574 -> 590 open during a single session that was actively resolving.

GATE THE RATE, NOT THE LEVEL. A gate on total open count is permanently red,
which teaches everyone to step over it -- the same failure the severity split
was built to fix. So `spillover rate` reports added-minus-resolved over a
trailing window, and nothing here blocks on the standing count.

WHAT THE GATE MUST DO, and the reason the control below is not decoration: a
gate that cannot fail in BOTH directions is not a gate, it is a filter with an
opinion. A mutant that accepts everything has to go red on
`test_add_naming_nothing_actionable_is_refused`; a mutant that refuses
everything has to go red on `test_control_*`. Neither test is meaningful
without the other.

NO RETROACTIVE REFUSAL. The existing rows that would not pass this gate are its
evidence, not its first victims. Refusing them after the fact would be a third
exit from the ledger beside fixed and voided, which is what
`no-orphan-findings.md` forbids and what got the baseline plan withdrawn.
`test_gate_does_not_reach_backwards` holds that line.

CALIBRATION, measured read-only against the live ledger before this gate was
written (603 open non-blocking items):
  - names no FILE ARTIFACT (path or filename): 49 (8.1%)
  - names NOTHING per this gate's rule:          6 (1.0%)
ASK-446 quotes "77 of 571 (13.5%)". That number is the FILE-ARTIFACT measure,
not this gate's rule, and it does not survive the DoR's own outcome sentence
("no path, script, symbol, command or reproducer"). Recorded here so the next
reader does not assume this gate reclaims 13.5% of the ledger. It does not. Its
value is the rows never written from here on.

No test touches the live ledger.
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
        capture_output=True, text=True)


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


def ledger(repo: Path) -> Path:
    return repo / ".prd-os" / "spillover.jsonl"


def rows(repo: Path) -> list:
    if not ledger(repo).is_file():
        return []
    return [json.loads(l) for l in ledger(repo).read_text().splitlines() if l.strip()]


def add(repo: Path, desc: str, *extra: str, sid: str = "sp-gate0001"):
    return run(repo, "spillover", "add", "--source", "s", "--desc", desc,
               "--id", sid, *extra)


# A description naming NOTHING a reader could act on. Deliberately a real
# sentence: the failure mode is not gibberish, it is a fluent note that leaves
# the reader with nowhere to go.
VAGUE = ("the export pipeline feels slow and we should probably clean up the "
         "way it handles the older records at some point")


# --------------------------------------------------------------------------
# THE CONTROL. Half of the both-directions requirement. A gate that refuses
# everything passes the refusal test and fails here.
# --------------------------------------------------------------------------

def test_control_add_naming_a_path_is_accepted_unchanged(repo: Path):
    r = add(repo, "plugins/prd-os/scripts/prd_runner.py drops the lock on the "
                  "resolve path", sid="sp-ctl00001")
    assert r.returncode == 0, r.stderr
    (row,) = [x for x in rows(repo) if x["id"] == "sp-ctl00001"]
    assert row["status"] == "open"
    assert "unstructured_reason" not in row, (
        "an accepted add must not be marked as a bypass")


@pytest.mark.parametrize("desc,signal", [
    ("plugins/prd-os/scripts/prd_runner.py line 200 is wrong", "path"),
    ("prd_runner.py mis-parses the header", "filename"),
    ("_spillover_lock() is never released on the early return", "call"),
    ("the `gates run` command exits 0 with a torn ledger line", "backtick"),
    ("severity_source is not stamped by the deferral fan-out", "snake_case"),
    ("FABLE_TIMEOUT is measured at 27-44s against a 45s cap", "const"),
    ("the dispatcher query has no orderBy so priority is ignored", "camelCase"),
    ("run python3 -m pytest -q to see it fail", "command"),
    ("sp-61faebb3 records the same defect on the ratchet", "ledger ref"),
    ("ASK-430 shipped the field this depends on", "issue ref"),
])
def test_control_each_signal_alone_is_enough(repo: Path, desc: str, signal: str):
    """Every signal the gate accepts, proven to be sufficient ON ITS OWN.

    Without this, one over-broad regex could be carrying all ten cases and the
    other nine would be dead code that still reads as covered.
    """
    r = add(repo, desc, sid="sp-sig00001")
    assert r.returncode == 0, f"{signal} should be accepted: {r.stderr}"


# --------------------------------------------------------------------------
# THE REFUSAL. The other half. A gate that accepts everything fails here.
# --------------------------------------------------------------------------

def test_add_naming_nothing_actionable_is_refused(repo: Path):
    r = add(repo, VAGUE)
    assert r.returncode == 2, (
        f"expected refusal, got rc={r.returncode}\nstdout={r.stdout}")


def test_a_refused_add_writes_nothing(repo: Path):
    """Refuse BEFORE the file is touched. A gate that appends and then errors is
    the worst of both: the row is on disk AND the caller saw a failure. Same
    contract `validate_for_append` already holds."""
    before = ledger(repo).read_bytes() if ledger(repo).is_file() else b""
    add(repo, VAGUE)
    after = ledger(repo).read_bytes() if ledger(repo).is_file() else b""
    assert before == after
    assert rows(repo) == []


def test_the_refusal_says_what_is_missing_and_how_to_proceed(repo: Path):
    """A refusal a caller cannot act on gets worked around, not fixed."""
    err = add(repo, VAGUE).stderr
    for expected in ("path", "symbol", "command", "--unstructured"):
        assert expected in err, f"refusal message never mentions {expected!r}: {err}"


# --------------------------------------------------------------------------
# THE BYPASS: possible, but recorded and countable.
# --------------------------------------------------------------------------

def test_bypass_is_accepted_and_recorded(repo: Path):
    r = add(repo, VAGUE, "--unstructured",
            "genuinely structural; no single artifact owns it", sid="sp-byp00001")
    assert r.returncode == 0, r.stderr
    (row,) = [x for x in rows(repo) if x["id"] == "sp-byp00001"]
    assert row["unstructured_reason"] == (
        "genuinely structural; no single artifact owns it")


def test_bypass_requires_a_reason(repo: Path):
    """A bare --unstructured flag would be a silent opt-out. The reason is the
    thing that makes it auditable rather than a switch someone flips once."""
    r = add(repo, VAGUE, "--unstructured", "   ")
    assert r.returncode == 2


def test_bypasses_are_countable(repo: Path):
    add(repo, VAGUE, "--unstructured", "structural", sid="sp-byp00002")
    add(repo, "prd_runner.py leaks a handle", sid="sp-ok000001")
    out = run(repo, "spillover", "rate").stdout
    assert "1 bypassed" in out, (
        "a bypass nobody can count is an unaudited hatch with a paper trail "
        "nobody opens")


# --------------------------------------------------------------------------
# NO RETROACTIVE REFUSAL.
# --------------------------------------------------------------------------

def test_gate_does_not_reach_backwards(repo: Path):
    """A row written before the gate stays readable, listable and resolvable.
    The gate is on the WRITE path only. These rows are its evidence."""
    ledger(repo).write_text(json.dumps({
        "id": "sp-legacy01", "source": "old", "description": VAGUE,
        "severity": "minor", "status": "open",
        "created_at": "2026-07-01T00:00:00Z"}) + "\n")
    listed = run(repo, "spillover", "list", "--open", "--json")
    assert listed.returncode == 0
    assert [x["id"] for x in json.loads(listed.stdout)] == ["sp-legacy01"]
    assert run(repo, "spillover", "triage").returncode == 0
    assert run(repo, "spillover", "resolve", "sp-legacy01",
               "--void", "not a real item").returncode == 0


# --------------------------------------------------------------------------
# RATE, NOT LEVEL.
# --------------------------------------------------------------------------

def test_rate_reports_added_minus_resolved_over_the_window(repo: Path):
    add(repo, "prd_runner.py one", sid="sp-r0000001")
    add(repo, "prd_runner.py two", sid="sp-r0000002")
    add(repo, "prd_runner.py three", sid="sp-r0000003")
    assert run(repo, "spillover", "resolve", "sp-r0000003",
               "--void", "not real").returncode == 0
    out = run(repo, "spillover", "rate").stdout
    assert "3 added" in out
    assert "1 resolved" in out
    assert "net +2" in out


def test_rate_excludes_events_outside_the_window(repo: Path):
    """The window is what makes this a RATE. Without it this is the open count
    wearing a different label, and an ever-red number teaches people to ignore
    it -- the exact failure this issue exists to avoid."""
    ledger(repo).write_text("\n".join(json.dumps(r) for r in [
        {"id": "sp-old00001", "source": "s", "description": "prd_runner.py old",
         "severity": "minor", "status": "open",
         "created_at": "2026-01-01T00:00:00Z"},
    ]) + "\n")
    add(repo, "prd_runner.py recent", sid="sp-new00001")
    out = run(repo, "spillover", "rate", "--days", "7").stdout
    assert "1 added" in out, f"old row leaked into a 7-day window: {out}"


def test_rate_does_not_block(repo: Path):
    """Reports, never refuses. The moment this returns non-zero on a healthy
    repo it becomes a permanently-red gate people route around."""
    add(repo, "prd_runner.py something", sid="sp-nb000001")
    assert run(repo, "spillover", "rate").returncode == 0
