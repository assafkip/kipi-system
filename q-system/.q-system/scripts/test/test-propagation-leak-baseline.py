"""A baseline is only evidence if someone had to say why, one line at a time.

The gate blocks on a delta, so whatever sits in the baseline at creation is
blessed forever. `semantic_leakage_findings` reports 64k findings on this repo
and 784 of them fall in the six high-confidence classes. Two failure modes
follow directly:

- Baseline everything and the file is unreadable, so it is an unaudited
  allowlist wearing the costume of a review.
- Accept the high-confidence classes in bulk and a fact that leaked BEFORE the
  gate shipped is pre-authorized to propagate forever, silently.

So blocking scope is the six classes, every entry in them carries its own
written justification, and there is no call shape that accepts them together.
`unclassified_populated_record` is reported as a warning and can never block,
because 63k entries is not something a human can stand behind.
"""

import importlib.util
import json
from collections.abc import Mapping
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
GATE = REPO_ROOT / "q-system" / ".q-system" / "scripts" / "propagation-leak-gate.py"
BASELINE_FILE = (
    REPO_ROOT / "q-system" / ".q-system" / "state" / "propagation-leak-baseline.json"
)


def load_gate():
    spec = importlib.util.spec_from_file_location("propagation_leak_gate", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def finding(fact_class="client_identity", text="- Client: Northwind Trading",
            path="q-system/marketing/templates/outreach.md"):
    return {"path": path, "fact_class": fact_class, "line": 3, "text": text}


def justify_all(gate, findings, reason="reviewed 2026-07-25: template placeholder"):
    """Per-entry justifications, the honest way, for tests not about provenance."""
    return {key: reason for key in gate.blocking_fingerprints(findings)}


def test_blocking_scope_is_the_six_high_confidence_classes():
    gate = load_gate()
    assert set(gate.BLOCKING_FACT_CLASSES) == {
        "case_proof_gap",
        "client_identity",
        "dated_interaction",
        "pricing",
        "source_identity",
        "sourced_interaction",
    }


def test_unclassified_records_never_block():
    """63k frontmatter hits cannot be a gate, only a warning."""
    gate = load_gate()
    findings = [finding(fact_class="unclassified_populated_record")]

    assert gate.blocking_fingerprints(findings) == {}
    assert gate.warning_findings(findings) == findings


def test_bulk_accept_is_refused():
    """One reason covering the whole set is the thing this issue exists to stop."""
    gate = load_gate()
    findings = [finding(), finding(text="- Price: $45,000", fact_class="pricing")]

    with pytest.raises(gate.BaselineRefused) as refusal:
        gate.build_baseline_document(findings, "all reviewed 2026-07-25, looks fine")
    assert "per-entry" in str(refusal.value)


def test_missing_justification_is_refused():
    gate = load_gate()
    findings = [finding(), finding(text="- Price: $45,000", fact_class="pricing")]
    partial = dict(list(justify_all(gate, findings).items())[:1])

    with pytest.raises(gate.BaselineRefused) as refusal:
        gate.build_baseline_document(findings, partial)
    assert "pricing" in str(refusal.value)


def test_blank_justification_is_refused():
    """An empty string is a bulk accept with extra steps."""
    gate = load_gate()
    findings = [finding()]
    blank = {key: "   " for key in gate.blocking_fingerprints(findings)}

    with pytest.raises(gate.BaselineRefused):
        gate.build_baseline_document(findings, blank)


def test_justification_for_a_fact_that_does_not_exist_is_refused():
    """A permit written ahead of the fact is a pre-authorized leak."""
    gate = load_gate()
    findings = [finding()]
    justifications = justify_all(gate, findings)
    justifications[("q-system/ghost.md", "client_identity", "top", "0" * 64)] = "n/a"

    with pytest.raises(gate.BaselineRefused) as refusal:
        gate.build_baseline_document(findings, justifications)
    assert "ghost.md" in str(refusal.value)


def test_document_carries_every_entry_with_its_reason():
    gate = load_gate()
    findings = [finding()]
    document = gate.build_baseline_document(findings, justify_all(gate, findings))

    assert len(document["entries"]) == 1
    entry = document["entries"][0]
    assert entry["fact_class"] == "client_identity"
    assert entry["count"] == 1
    assert entry["justification"].startswith("reviewed 2026-07-25")
    assert json.dumps(document)  # the file on disk has to be plain JSON


def test_loaded_document_reproduces_the_fingerprint_counts():
    """Round trip, or the baseline does not describe what the gate compares."""
    gate = load_gate()
    findings = [finding(), finding()]
    document = gate.build_baseline_document(findings, justify_all(gate, findings))

    assert gate.load_baseline_document(document) == gate.blocking_fingerprints(findings)


def test_loading_an_entry_without_a_justification_is_refused():
    """The check has to survive a hand-edit of the committed file."""
    gate = load_gate()
    findings = [finding()]
    document = gate.build_baseline_document(findings, justify_all(gate, findings))
    document["entries"][0].pop("justification")

    with pytest.raises(gate.BaselineRefused):
        gate.load_baseline_document(document)


def test_loading_a_non_blocking_class_is_refused():
    """Nothing outside the six classes belongs in a file that grants permits."""
    gate = load_gate()
    findings = [finding()]
    document = gate.build_baseline_document(findings, justify_all(gate, findings))
    document["entries"][0]["fact_class"] = "unclassified_populated_record"

    with pytest.raises(gate.BaselineRefused):
        gate.load_baseline_document(document)


def test_classifier_mismatch_is_refused():
    """A baseline built by another classifier is not a statement about this one."""
    gate = load_gate()
    findings = [finding()]
    document = gate.build_baseline_document(
        findings, justify_all(gate, findings), classifier_sha256="a" * 64
    )

    assert gate.load_baseline_document(document, classifier_sha256="a" * 64)
    with pytest.raises(gate.BaselineRefused):
        gate.load_baseline_document(document, classifier_sha256="b" * 64)


def test_bulk_accept_via_a_hostile_mapping_is_refused():
    """`isinstance(x, Mapping)` is not proof that x holds per-entry reasons.

    A Mapping whose `get` answers every key with one reason, and whose
    `__iter__` is empty, satisfies every per-entry check while being exactly
    the bulk accept those checks exist to stop.
    """
    gate = load_gate()

    class BulkAccept(Mapping):
        def __getitem__(self, key):
            return "all reviewed 2026-07-25"

        def get(self, key, default=None):
            return "all reviewed 2026-07-25"

        def __iter__(self):
            return iter(())

        def __len__(self):
            return 0

    with pytest.raises(gate.BaselineRefused):
        gate.build_baseline_document([finding()], BulkAccept())


def test_inflated_count_is_refused():
    """A count is how many copies ONE written reason covers."""
    gate = load_gate()
    findings = [finding()]
    document = gate.build_baseline_document(findings, justify_all(gate, findings))
    document["entries"][0]["count"] = 999

    with pytest.raises(gate.BaselineRefused) as refusal:
        gate.load_baseline_document(document, current=gate.blocking_fingerprints(findings))
    assert "cannot exceed" in str(refusal.value)


def test_duplicate_entries_for_one_fingerprint_are_refused():
    """Splitting an inflated permit across two innocuous rows is the same trick."""
    gate = load_gate()
    findings = [finding()]
    document = gate.build_baseline_document(findings, justify_all(gate, findings))
    document["entries"].append(dict(document["entries"][0]))

    with pytest.raises(gate.BaselineRefused) as refusal:
        gate.load_baseline_document(document)
    assert "repeats" in str(refusal.value)


def test_malformed_document_metadata_is_refused():
    gate = load_gate()
    findings = [finding()]
    good = gate.build_baseline_document(findings, justify_all(gate, findings))

    for broken in (
        {},
        {**good, "schema_version": 999},
        {**good, "blocking_classes": ["pricing"]},
        {**good, "entries": "none"},
    ):
        with pytest.raises(gate.BaselineRefused):
            gate.load_baseline_document(broken)


def test_non_canonical_fact_class_still_blocks():
    """Exact matching fails open: a warning never stops a run."""
    gate = load_gate()
    spaced = [finding(fact_class="pricing ", text="- Price: $45,000")]

    assert len(gate.blocking_fingerprints(spaced)) == 1
    assert gate.warning_findings(spaced) == []
    assert list(gate.blocking_fingerprints(spaced))[0][1] == "pricing"


def test_finding_without_a_fact_class_is_refused():
    """Malformed classifier output must fail closed, not become a warning."""
    gate = load_gate()

    with pytest.raises(gate.BaselineRefused):
        gate.warning_findings([{"path": "a.md", "text": "- Client: X", "line": 1}])


def test_committed_baseline_file_loads():
    """The file that ships must satisfy its own rules."""
    gate = load_gate()
    document = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))

    assert gate.load_baseline_document(document) == {}
    assert document["entries"] == [], (
        "an entry landed without going through build_baseline_document"
    )
