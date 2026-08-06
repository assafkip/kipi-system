"""sp-9f11cf69 reproducer: a deferred finding's body must survive into the ledger.

`findings_writer._sync_spillover_for_finding` auto-creates the spillover item
that makes a `deferred` disposition non-terminal. It used to write
`str(finding.get('body',''))[:120]`, so every `defer-*` row in the ledger ended
mid-sentence.

WHY THIS IS NOT COSMETIC. Nobody can triage what they cannot read. An item whose
description stops mid-clause is not low-priority, it is unreadable, and `minor`
is the default bucket unreadable things land in. Measured 2026-08-06: all five
open `defer-*` descriptions ended mid-clause, and four of them were verified
against half-sentences before anyone opened the findings file that still held
the real text.

The canonical body lives in `.prd-os/findings/<prd>-findings.jsonl`, so the loss
is recoverable -- but only by APPENDING a corrected event. History never changes.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"


def _load(name: str):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    for sub in (".prd-os/prds", ".prd-os/issues", ".prd-os/findings", ".claude/state"):
        (r / sub).mkdir(parents=True, exist_ok=True)
    (r / ".git").mkdir()
    (r / ".prd-os" / "config.json").write_text(json.dumps({
        "config_schema_version": 1,
        "prds_dir": ".prd-os/prds",
        "issues_dir": ".prd-os/issues",
        "findings_dir": ".prd-os/findings",
        "state_dir": ".claude/state",
    }))
    return r


def _cfg(repo: Path):
    sys.path.insert(0, str(SCRIPTS))
    from config import load as load_config
    return load_config(repo, strict=True)


# A body long enough that a 120-char cap is unmistakable, and whose MEANING
# lives past the cut -- the "so" clause is the part a triager needs.
LONG_BODY = (
    "The grounding gate treats an absent manifest, a missing module, and "
    "unreadable JSON as equivalent to a clean pass, each returning exit 0, "
    "so the gate fails open on exactly the corrupted or unavailable evidence "
    "it needs in order to establish coverage at all."
)


def test_deferred_finding_body_survives_into_the_spillover_item(repo: Path):
    """The whole body reaches the ledger, not a 120-char prefix."""
    fw = _load("findings_writer")
    cfg = _cfg(repo)
    finding = {"id": "finding-3", "body": LONG_BODY, "severity": "blocker",
               "disposition": "deferred"}
    fw._sync_spillover_for_finding(cfg, "prd-test-2026-08-06", finding)

    from prd_runner import _read_spillover
    rows = [r for r in _read_spillover(cfg).values() if "finding-3" in r["id"]]
    assert rows, "no spillover item was created for the deferred finding"
    desc = rows[0].get("description", "")
    assert LONG_BODY in desc, (
        "the finding body did not survive into the ledger.\n"
        f"stored {len(desc)} chars; body is {len(LONG_BODY)}.\n"
        f"stored={desc!r}")


def test_the_meaning_bearing_tail_is_not_cut(repo: Path):
    """Targets the CUT, not just the length.

    A cap raised from 120 to some larger number would pass a length assertion
    while still truncating a longer finding. This asserts the specific clause
    that carries the finding's point.
    """
    fw = _load("findings_writer")
    cfg = _cfg(repo)
    fw._sync_spillover_for_finding(
        cfg, "prd-test-2026-08-06",
        {"id": "finding-9", "body": LONG_BODY, "severity": "major",
         "disposition": "deferred"})
    from prd_runner import _read_spillover
    row = [r for r in _read_spillover(cfg).values() if "finding-9" in r["id"]][0]
    assert "fails open" in row["description"], (
        "the clause carrying the finding's meaning was cut off; a triager "
        f"reading this row cannot tell what the defect is.\nstored={row['description']!r}")
    assert not row["description"].rstrip().endswith("..."), \
        "body was elided rather than carried"


def test_a_short_body_is_unchanged(repo: Path):
    """Negative self-test. An implementation that pads or mangles every body
    would satisfy both assertions above."""
    fw = _load("findings_writer")
    cfg = _cfg(repo)
    short = "Short and complete."
    fw._sync_spillover_for_finding(
        cfg, "prd-test-2026-08-06",
        {"id": "finding-1", "body": short, "severity": "minor",
         "disposition": "deferred"})
    from prd_runner import _read_spillover
    row = [r for r in _read_spillover(cfg).values() if "finding-1" in r["id"]][0]
    assert row["description"].endswith(short)
    assert "finding-1" in row["description"]


def test_the_row_still_passes_the_ledger_validator(repo: Path):
    """Wiring proof: a longer description must not break the fail-closed reader
    this issue shipped. An unreadable ledger would be a worse bug than a short one."""
    fw = _load("findings_writer")
    cfg = _cfg(repo)
    fw._sync_spillover_for_finding(
        cfg, "prd-test-2026-08-06",
        {"id": "finding-77", "body": LONG_BODY * 20, "severity": "major",
         "disposition": "deferred"})
    from prd_runner import _read_spillover
    rows = _read_spillover(cfg)  # raises SpilloverLedgerError if invalid
    assert any("finding-77" in k for k in rows)
