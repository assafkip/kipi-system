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
    """One DISTINCT reason per fingerprint.

    This helper used to return the same string for every key and was labelled
    "the honest way". It was the bulk accept: a single expression blessing the
    whole population while satisfying every per-entry check. Naming the actual
    record in each reason is what a per-entry read leaves behind.
    """
    return {
        key: f"{reason} — {key[0]} [{key[1]}] {key[3][:8]}"
        for key in gate.blocking_fingerprints(findings)
    }


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

    current = gate.blocking_fingerprints(findings)
    assert gate.load_baseline_document(document, current=current) == current


def test_loading_an_entry_without_a_justification_is_refused():
    """The check has to survive a hand-edit of the committed file."""
    gate = load_gate()
    findings = [finding()]
    document = gate.build_baseline_document(findings, justify_all(gate, findings))
    document["entries"][0].pop("justification")

    with pytest.raises(gate.BaselineRefused):
        gate.load_baseline_document(document, current=gate.blocking_fingerprints(findings))


def test_loading_a_non_blocking_class_is_refused():
    """Nothing outside the six classes belongs in a file that grants permits."""
    gate = load_gate()
    findings = [finding()]
    document = gate.build_baseline_document(findings, justify_all(gate, findings))
    document["entries"][0]["fact_class"] = "unclassified_populated_record"

    with pytest.raises(gate.BaselineRefused):
        gate.load_baseline_document(document, current=gate.blocking_fingerprints(findings))


def test_classifier_mismatch_is_refused():
    """A baseline built by another classifier is not a statement about this one."""
    gate = load_gate()
    findings = [finding()]
    document = gate.build_baseline_document(
        findings, justify_all(gate, findings), classifier_sha256="a" * 64
    )

    current = gate.blocking_fingerprints(findings)
    assert gate.load_baseline_document(document, "a" * 64, current)
    with pytest.raises(gate.BaselineRefused):
        gate.load_baseline_document(document, "b" * 64, current)


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
        gate.load_baseline_document(document, current=gate.blocking_fingerprints(findings))
    assert "repeats" in str(refusal.value)


def test_malformed_document_metadata_is_refused():
    gate = load_gate()
    findings = [finding()]
    good = gate.build_baseline_document(findings, justify_all(gate, findings))

    current = gate.blocking_fingerprints(findings)
    for broken in (
        {},
        {**good, "schema_version": 999},
        {**good, "blocking_classes": ["pricing"]},
        {**good, "entries": "none"},
    ):
        with pytest.raises(gate.BaselineRefused):
            gate.load_baseline_document(broken, current=current)


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


def test_loading_a_granting_baseline_without_current_is_refused():
    """`current` is what bounds a permit, so it cannot be optional.

    With no current counts there is nothing for `count` to be measured
    against, and an unbounded count is one reason covering any number of
    copies.
    """
    gate = load_gate()
    findings = [finding()]
    document = gate.build_baseline_document(findings, justify_all(gate, findings))
    document["entries"][0]["count"] = 999

    with pytest.raises(gate.BaselineRefused) as refusal:
        gate.load_baseline_document(document)
    assert "unbounded" in str(refusal.value)


def test_hostile_justification_key_is_refused():
    """A key that merely compares equal to a fingerprint is not one.

    __eq__/__hash__ can make any object satisfy `key in counts`, so the reason
    is recorded against a fact it was never written for.
    """
    gate = load_gate()
    findings = [finding()]
    real_key = next(iter(gate.blocking_fingerprints(findings)))

    class EvilKey:
        def __hash__(self):
            return hash(real_key)

        def __eq__(self, other):
            return other == real_key

    with pytest.raises(gate.BaselineRefused) as refusal:
        gate.build_baseline_document(findings, {EvilKey(): "reason for nothing"})
    assert "not a fingerprint" in str(refusal.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("path", 42),
        ("indent", "sideways"),
        ("line_sha256", "not-a-digest"),
        ("justification", ["reviewed"]),
    ],
)
def test_malformed_entry_fields_are_refused(field, value):
    """A key built from a non-string never equals a computed fingerprint.

    It would read as reviewed while granting nothing, which is worse than an
    absent entry: it looks like coverage.
    """
    gate = load_gate()
    findings = [finding()]
    document = gate.build_baseline_document(findings, justify_all(gate, findings))
    document["entries"][0][field] = value

    with pytest.raises(gate.BaselineRefused):
        gate.load_baseline_document(
            document, current=gate.blocking_fingerprints(findings)
        )


# --------------------------------------------------------------------------
# Lifecycle: re-baselining prunes, and reports adds apart from removals
# --------------------------------------------------------------------------
#
# A permit that outlives its fact is the quiet failure. The line is deleted, the
# entry stays, and months later the same line comes back already blessed. And a
# classifier change moves hundreds of entries at once, which is exactly the
# cover a single "247 changed" number gives a real leak riding along. So:
# re-baselining prunes, and it reports what was ADDED separately from what was
# REMOVED.

PRICE = "- Package price: $45,000"


def rebaseline(gate, document, findings, justifications=None):
    return gate.rebaseline_document(document, findings, justifications or {})


def baselined(gate, findings):
    return gate.build_baseline_document(findings, justify_all(gate, findings))


def test_stale_entries_are_pruned():
    """A permit for a line that no longer exists re-authorizes its return."""
    gate = load_gate()
    was = [finding(), finding(fact_class="pricing", text=PRICE)]
    document = baselined(gate, was)

    result = rebaseline(gate, document, [finding()])

    kept = [entry["fact_class"] for entry in result["document"]["entries"]]
    assert kept == ["client_identity"]
    assert [entry["fact_class"] for entry in result["removed"]] == ["pricing"]


def test_adds_and_removals_are_reported_separately():
    """One combined number is what lets a real leak ride along with churn."""
    gate = load_gate()
    document = baselined(gate, [finding()])
    arrived = finding(fact_class="pricing", text=PRICE)

    result = rebaseline(
        gate,
        document,
        [arrived],
        {key: "reviewed 2026-07-25: rate card" for key in gate.blocking_fingerprints([arrived])},
    )

    assert [entry["fact_class"] for entry in result["added"]] == ["pricing"]
    assert [entry["fact_class"] for entry in result["removed"]] == ["client_identity"]


def test_surviving_entry_keeps_its_justification():
    """Unchanged content must not need re-justifying, or nobody re-baselines."""
    gate = load_gate()
    findings = [finding()]
    document = baselined(gate, findings)

    result = rebaseline(gate, document, findings)

    assert result["added"] == []
    assert result["removed"] == []
    assert result["document"]["entries"][0]["justification"].startswith("reviewed")


def test_a_newly_blessed_fingerprint_still_needs_its_own_justification():
    """Re-baselining is not a side door around per-entry provenance."""
    gate = load_gate()
    document = baselined(gate, [finding()])
    arrived = finding(fact_class="pricing", text=PRICE)

    with pytest.raises(gate.BaselineRefused):
        rebaseline(gate, document, [finding(), arrived])


def test_any_count_movement_needs_a_fresh_justification():
    """A shrink is a re-grant, because the old count may never have been real.

    The document conflates "how many a human reviewed" with "how many are
    permitted", so on the way down there is nothing left to prove the carried
    reason ever covered the surviving copy. Requiring a fresh reason on ANY
    movement is the only rule the current schema can actually enforce.
    """
    gate = load_gate()
    twice = [finding(), finding()]
    document = baselined(gate, twice)

    with pytest.raises(gate.BaselineRefused):
        rebaseline(gate, document, [finding()])

    result = rebaseline(
        gate,
        document,
        [finding()],
        {key: "reviewed 2026-07-25: one copy left" for key in gate.blocking_fingerprints([finding()])},
    )
    assert result["document"]["entries"][0]["count"] == 1
    assert result["removed"][0]["baseline_count"] == 2
    assert result["removed"][0]["current_count"] == 1


def test_rebaseline_cannot_launder_an_inflated_count():
    """The bug this rule exists for.

    A human reviewed ONE copy. The committed file is hand-edited to three.
    Reality is two. load_baseline_document refuses that file outright, so the
    operator re-baselines, and the rewrite prunes 3 -> 2, carries the old
    reason forward, and reports it only as a REMOVAL. The result loads clean
    and grants two copies of a private line that one human ever read once.
    """
    gate = load_gate()
    once = [finding()]
    document = baselined(gate, once)
    document["entries"][0]["count"] = 3
    reality = [finding(), finding()]

    with pytest.raises(gate.BaselineRefused):
        gate.load_baseline_document(
            document, current=gate.blocking_fingerprints(reality)
        )

    with pytest.raises(gate.BaselineRefused):
        rebaseline(gate, document, reality)


def test_one_reason_reused_across_entries_is_refused():
    """The bulk accept that survives every per-entry check.

    `{key: ONE_REASON for key in blocking_fingerprints(findings)}` is one
    expression that blesses the whole population. It satisfies "a mapping",
    "a key per fingerprint" and "non-empty" while no human read a single one.
    """
    gate = load_gate()
    findings = [finding(), finding(fact_class="pricing", text=PRICE)]
    one_reason = {
        key: "reviewed 2026-07-25, all fine"
        for key in gate.blocking_fingerprints(findings)
    }

    with pytest.raises(gate.BaselineRefused) as refusal:
        gate.build_baseline_document(findings, one_reason)
    assert "reused" in str(refusal.value)


def test_a_non_string_justification_is_refused_at_build():
    """The builder must not emit a document its own loader rejects."""
    gate = load_gate()
    findings = [finding()]
    listed = {key: ["reviewed"] for key in gate.blocking_fingerprints(findings)}

    with pytest.raises(gate.BaselineRefused):
        gate.build_baseline_document(findings, listed)


def test_rebaseline_does_not_restamp_an_unverified_classifier():
    """Stamp only what was proven.

    Omitting classifier_sha256 skips the provenance check entirely, so copying
    the old hash onto entries computed by an unknown classifier makes the file
    assert something the tool never checked.
    """
    gate = load_gate()
    findings = [finding()]
    document = gate.build_baseline_document(
        findings, justify_all(gate, findings), classifier_sha256="a" * 64
    )

    with pytest.raises(gate.BaselineRefused) as refusal:
        rebaseline(gate, document, findings)
    assert "classifier" in str(refusal.value)


def test_classifier_churn_cannot_hide_a_new_fact():
    """The stated reason the two sets are reported apart.

    A classifier change retires many entries at once. If that showed up as one
    net number, a genuinely new fact would be invisible inside it.
    """
    gate = load_gate()
    retiring = [
        finding(path=f"q-system/canonical/case-{index}.md") for index in range(5)
    ]
    document = baselined(gate, retiring)
    arrived = finding(fact_class="pricing", text=PRICE)

    result = rebaseline(
        gate,
        document,
        [arrived],
        {key: "reviewed 2026-07-25: rate card" for key in gate.blocking_fingerprints([arrived])},
    )

    assert len(result["removed"]) == 5
    assert len(result["added"]) == 1
    assert result["added"][0]["fact_class"] == "pricing"


def test_rebaselining_a_hand_edited_document_is_refused():
    """The lifecycle runs the load rules, so an unjustified row cannot survive."""
    gate = load_gate()
    findings = [finding()]
    document = baselined(gate, findings)
    document["entries"][0]["justification"] = "  "

    with pytest.raises(gate.BaselineRefused):
        rebaseline(gate, document, findings)


def test_committed_baseline_file_loads():
    """The file that ships must satisfy its own rules."""
    gate = load_gate()
    document = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))

    assert gate.load_baseline_document(document) == {}
    assert document["entries"] == [], (
        "an entry landed without going through build_baseline_document"
    )
