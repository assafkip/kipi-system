import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT / "validate-separation.py"
FIXTURES = Path(__file__).parent / "fixtures" / "fact-grammar.json"
REQUIRED_CATEGORIES = {
    "case_fact",
    "currency",
    "dated_interaction",
    "placeholder",
    "populated_field",
    "source",
    "synthetic_marker",
    "unclassified",
}
REQUIRED_CASE_IDS = {
    "affirmative-case-fact",
    "currency-without-source-or-date",
    "dated-interaction-without-source-or-currency",
    "fixture-provenance-without-marker",
    "invalid-dated-interaction",
    "mixed-placeholder-and-real-content",
    "placeholder-only-template",
    "source-without-date",
    "synthetic-marker-with-fixture-provenance",
    "synthetic-marker-without-provenance",
    "unclassified-populated-record",
}


def load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_separation",
        VALIDATOR,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_document():
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


DOCUMENT = load_document()
CASES = DOCUMENT["cases"]


def test_fixture_contract_is_non_vacuous():
    assert DOCUMENT["schema_version"] == 1
    assert set(DOCUMENT["required_categories"]) == REQUIRED_CATEGORIES
    assert CASES

    case_ids = [case["id"] for case in CASES]
    assert len(case_ids) == len(set(case_ids))
    assert REQUIRED_CASE_IDS <= set(case_ids)

    covered = set()
    for case in CASES:
        assert set(case) >= {
            "covers",
            "expected_classes",
            "expected_lines",
            "id",
            "text",
        }
        assert case["covers"]
        assert set(case["covers"]) <= REQUIRED_CATEGORIES
        assert len(case["expected_classes"]) == len(case["expected_lines"])
        covered.update(case["covers"])
    assert covered == REQUIRED_CATEGORIES

    by_id = {case["id"]: case for case in CASES}
    assert by_id["placeholder-only-template"]["expected_classes"] == []
    assert by_id["mixed-placeholder-and-real-content"][
        "expected_classes"
    ] == ["client_identity"]
    assert by_id["synthetic-marker-with-fixture-provenance"][
        "expected_classes"
    ] == []
    assert by_id["fixture-provenance-without-marker"][
        "expected_classes"
    ] == ["client_identity"]
    assert by_id["affirmative-case-fact"]["expected_classes"] == [
        "unclassified_populated_record"
    ]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_boundary(case):
    validator = load_validator()
    findings = validator.semantic_leakage_findings(
        case["text"],
        source_path=case.get("source_path"),
    )

    assert [finding["fact_class"] for finding in findings] == (
        case["expected_classes"]
    )
    assert [finding["line"] for finding in findings] == case["expected_lines"]
