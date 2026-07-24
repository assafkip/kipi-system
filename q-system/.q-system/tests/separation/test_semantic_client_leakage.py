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
