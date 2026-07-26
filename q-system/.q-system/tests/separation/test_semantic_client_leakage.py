import importlib.util
from pathlib import Path

import pytest


VALIDATOR = Path(__file__).resolve().parents[4] / "validate-separation.py"


def load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_separation",
        VALIDATOR,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def findings_for(text, source_path=None):
    validator = load_validator()
    return validator.semantic_leakage_findings(
        text,
        source_path=source_path,
    )


def classes_for(text, source_path=None):
    return {
        finding["fact_class"]
        for finding in findings_for(text, source_path=source_path)
    }


def test_unknown_name_and_relationship_are_instance_facts():
    classes = classes_for(
        "\n".join(
            [
                "- **Client:** Oriole Systems",
                "- **Relationship:** Maren introduced Oriole Systems",
            ]
        )
    )

    assert classes == {"client_identity", "relationship"}


def test_currency_is_pricing_fact_without_known_names():
    assert classes_for("- **Package:** $12,345 for the investigation") == {
        "pricing"
    }


def test_sourced_dated_interaction_is_instance_fact():
    assert classes_for(
        "- **Source:** Maren / Oriole pricing discussion - 2026-07-24"
    ) == {"sourced_interaction"}


def test_case_proof_gap_is_instance_fact():
    assert classes_for(
        "- **Gaps:** Missing attribution proof for the Oriole case"
    ) == {"case_proof_gap"}


def test_unknown_name_and_unclassified_populated_record_fails_closed():
    assert classes_for(
        "- **Engagement detail:** Oriole requested custom deployment"
    ) == {"unclassified_populated_record"}


def test_placeholder_only_fields_are_generic():
    assert classes_for("- **Client:** {{CLIENT_NAME}}") == set()


def test_explicit_synthetic_fixture_is_generic():
    assert classes_for(
        "\n".join(
            [
                "fixture: synthetic",
                "- **Client:** Oriole Systems",
                "- **Price:** $12,345",
            ]
        ),
        source_path=(
            "q-system/.q-system/tests/separation/fixtures/synthetic.md"
        ),
    ) == set()


def test_synthetic_marker_without_fixture_provenance_does_not_bypass():
    classes = classes_for(
        "\n".join(
            [
                "fixture: synthetic",
                "- **Client:** Oriole Systems",
            ]
        ),
        source_path="q-system/canonical/discovery.md",
    )

    assert "client_identity" in classes


@pytest.mark.parametrize(
    "record",
    [
        "**Client**: Oriole Systems",
        "Client: Oriole Systems",
        "| Client | Oriole Systems |",
        "**Client:**\n  Oriole Systems",
    ],
)
def test_alternate_populated_field_forms_fail_closed(record):
    assert "client_identity" in classes_for(record)


def test_one_record_emits_every_matching_class_and_line():
    findings = findings_for(
        "- **Source:** Maren quoted $5,000 on July 24, 2026"
    )

    assert findings == [
        {"fact_class": "pricing", "line": 1},
        {"fact_class": "sourced_interaction", "line": 1},
    ]


def test_invalid_date_does_not_claim_dated_interaction():
    assert classes_for("- **Meeting:** 2026-99-99") == {
        "unclassified_populated_record"
    }


@pytest.mark.parametrize(
    "placeholder",
    [
        "{{client_name}}",
        "{{ client.name }}",
        "{{client-name}}",
    ],
)
def test_placeholder_variants_are_generic(placeholder):
    assert classes_for(f"- **Client:** {placeholder}") == set()


def test_prospect_and_standalone_source_fields_are_classified():
    findings = findings_for(
        "\n".join(
            [
                "- **Prospect:** Oriole Systems",
                "- **Potential source:** Maren",
            ]
        )
    )

    assert findings == [
        {"fact_class": "client_identity", "line": 1},
        {"fact_class": "source_identity", "line": 2},
    ]


# ---------------------------------------------------------------------------
# Reach: how much of a leak this classifier can actually see
# ---------------------------------------------------------------------------
#
# The PRD states the bound in prose: "a client name in prose, a heading, JSON,
# shell, Python or most config syntax produces no finding, so it passes this
# gate untouched." Prose degrades silently. It stays on the page while the
# classifier changes underneath it, and by then nobody knows whether the
# sentence is still true.
#
# So the bound is a fixture: one fact, the client "Oriole Systems", written
# sixteen ways, each pinned to what the classifier ACTUALLY returns today. If
# the grammar widens, these fail and force the number to be re-measured and
# re-stated. A blind spot that closes without anyone noticing is how a bound
# becomes a lie.

import json

REACH_PROBE = json.loads(
    (Path(__file__).parent / "fixtures" / "fact-grammar.json").read_text(
        encoding="utf-8"
    )
)["reach_probe"]


@pytest.mark.parametrize(
    "form", REACH_PROBE["forms"], ids=lambda form: form["id"]
)
def test_classifier_reach_is_pinned_per_form(form):
    """Each form is pinned to what the classifier returns, seen or blind.

    A failure here is not a regression. It means the classifier moved and the
    stated bound is now wrong: re-measure, update the fixture, and update any
    prose that quotes the number.
    """
    assert sorted(classes_for(form["text"])) == form["seen_classes"], (
        f"the {form['category']} form {form['id']!r} no longer classifies as "
        f"recorded; re-measure the bound before changing this fixture"
    )


def test_blind_spot_coverage_is_measured_not_assumed():
    """The bound as a number: 3 of 16 forms of one fact are visible.

    All three are the same shape -- an explicit `label: value` record. Every
    prose, heading, JSON, code and config form is invisible, which is most of
    the ways a real fact gets written down.
    """
    forms = REACH_PROBE["forms"]
    seen = [form for form in forms if form["seen_classes"]]
    blind = [form for form in forms if not form["seen_classes"]]

    assert len(forms) == 16
    assert len(seen) == 3, f"reach changed: {len(seen)}/16 seen, re-state the bound"
    assert {form["category"] for form in seen} == {"record"}, (
        "the classifier now sees something outside label:value records; the "
        "bound in the PRD and in propagation-leak-gate.py must be re-stated"
    )
    assert {form["category"] for form in blind} == {
        "prose", "heading", "json", "code", "config",
    }


def test_blind_spot_forms_carry_the_fact_a_human_would_read():
    """Guard against the fixture drifting into forms that carry no fact.

    A "blind spot" that does not actually contain the client name would make
    the bound look worse than it is, which is its own kind of dishonesty.
    """
    for form in REACH_PROBE["forms"]:
        assert REACH_PROBE["fact"] in form["text"], (
            f"{form['id']} does not contain the fact it claims to hide"
        )
