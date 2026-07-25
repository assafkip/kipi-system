"""Fingerprints for the propagation leak gate.

A baseline is an allowlist, and an allowlist keyed on a bare set of
`path + class + line-hash` is a permanent replay permit: once a line is
blessed, the same asserted line can be pasted a second time, or deleted and
brought back later, without ever registering as new. Counting occurrences is
what turns the allowlist back into a statement about a specific amount of
known content.
"""

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
GATE = REPO_ROOT / "q-system" / ".q-system" / "scripts" / "propagation-leak-gate.py"

RECORD = "- Client: Northwind Trading\n"
OTHER = "- Deal size: $45,000\n"


def load_gate():
    spec = importlib.util.spec_from_file_location("propagation_leak_gate", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def findings(*records):
    """Shape the classifier emits: one dict per detected record."""
    return [
        {"path": "q-system/marketing/templates/outreach.md",
         "fact_class": "client_identity",
         "line": index + 1,
         "text": record}
        for index, record in enumerate(records)
    ]


def test_fingerprint_ignores_line_movement():
    """Reformatting must not churn the baseline."""
    gate = load_gate()
    first = gate.fingerprint_findings(findings(RECORD))
    moved = gate.fingerprint_findings(
        [{**finding, "line": finding["line"] + 40} for finding in findings(RECORD)]
    )
    assert first == moved


def test_fingerprint_registers_a_changed_value():
    """Changing the asserted value is a different fact."""
    gate = load_gate()
    before = gate.fingerprint_findings(findings(RECORD))
    after = gate.fingerprint_findings(findings("- Client: Someone Else\n"))
    assert gate.new_findings(before, after)


def test_count_blocks_a_duplicate_replay():
    """A blessed line pasted a second time is new content, not blessed content."""
    gate = load_gate()
    baseline = gate.fingerprint_findings(findings(RECORD))
    duplicated = gate.fingerprint_findings(findings(RECORD, RECORD))
    added = gate.new_findings(baseline, duplicated)
    assert added, "a duplicated baselined record replayed for free"
    assert any(entry["count_delta"] == 1 for entry in added)


def test_count_blocks_a_remove_and_reintroduce_replay():
    """Removing a blessed line must retire its permit, not park it."""
    gate = load_gate()
    baseline = gate.fingerprint_findings(findings(RECORD))
    removed = gate.fingerprint_findings(findings())
    assert gate.new_findings(baseline, removed) == []

    # The baseline is only refreshed by an explicit re-baseline, so a later
    # reintroduction is still measured against the pruned set.
    pruned = gate.prune_baseline(baseline, removed)
    assert pruned == {}
    assert gate.new_findings(pruned, gate.fingerprint_findings(findings(RECORD)))


def test_a_second_record_reusing_the_line_is_new():
    """The same text under a second fact class is a separate permit."""
    gate = load_gate()
    baseline = gate.fingerprint_findings(findings(RECORD))
    extra = [
        {"path": "q-system/marketing/templates/outreach.md",
         "fact_class": "pricing",
         "line": 1,
         "text": RECORD}
    ]
    both = gate.fingerprint_findings(findings(RECORD) + extra)
    assert gate.new_findings(baseline, both)


def test_reindenting_a_record_is_not_new():
    """Moving a list item under a new parent is a reformat, not a new fact."""
    gate = load_gate()
    baseline = gate.fingerprint_findings(findings(RECORD))
    reindented = gate.fingerprint_findings(findings("    " + RECORD))
    assert gate.new_findings(baseline, reindented) == []


def test_unchanged_content_is_not_new():
    """The control: an identical scan must produce no additions."""
    gate = load_gate()
    baseline = gate.fingerprint_findings(findings(RECORD, OTHER))
    assert gate.new_findings(baseline, gate.fingerprint_findings(findings(RECORD, OTHER))) == []


def test_a_finding_without_text_is_refused():
    """No text means no fingerprint. Guessing one would bless the wrong line."""
    gate = load_gate()
    with pytest.raises(ValueError):
        gate.fingerprint_findings(
            [{"path": "a.md", "fact_class": "client_identity", "line": 1}]
        )
