import hashlib
import importlib.util
import json
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
# shell, Python or most config syntax produces no finding." Prose degrades
# silently, so the bound is a fixture instead: one fact written many ways, each
# pinned to what the classifier ACTUALLY returns.
#
# The first version of this probe was WRONG, and wrong in the flattering
# direction: it was sampled to reproduce the prose claim. Every "prose" form it
# chose happened to lack a leading label and every "config" form happened to
# use `=` rather than `:`. The real rule is validate-separation.py's
# SEMANTIC_FIELD pattern -- ANY line shaped `Word(s): value`, whatever syntax
# surrounds it -- so YAML frontmatter, nested YAML, indented markdown,
# multi-line HTML comments and labeled prose are all SEEN. That matters
# concretely: q-system/ canonical files are YAML-frontmattered markdown, the
# shape the old probe called invisible.
#
# This is a SAMPLE bound, not a total one. A green suite means the classifier
# did not move ON THESE FORMS. It never means the classifier did not move.


def _reach_probe():
    """Loaded per-test, not at import.

    A module-level read turns a malformed fixture into a collection ERROR that
    takes out the thirteen tests above, which have nothing to do with the probe.
    """
    return json.loads(
        (Path(__file__).parent / "fixtures" / "fact-grammar.json").read_text(
            encoding="utf-8"
        )
    )["reach_probe"]


def _probe_forms():
    return _reach_probe()["forms"]


@pytest.mark.parametrize("form", _probe_forms(), ids=lambda form: form["id"])
def test_classifier_reach_is_pinned_per_form(form):
    """Pinned to class AND line, matching what the `cases` half of this fixture
    already pins. Dropping the line meant a change to WHERE a finding fires was
    invisible here while being caught next door.

    A failure is not a regression. It means the classifier moved and the stated
    bound is now wrong: re-measure, update the fixture AND its texts_sha256,
    and update any prose quoting the number.
    """
    findings = sorted(
        findings_for(form["text"]), key=lambda f: (f["line"], f["fact_class"])
    )
    expected = sorted(
        form["seen_findings"], key=lambda f: (f["line"], f["fact_class"])
    )
    assert findings == expected, (
        f"the {form['category']} form {form['id']!r} no longer classifies as "
        f"recorded; re-measure the bound before editing this fixture"
    )


def test_blind_spot_coverage_is_measured_not_assumed():
    """The bound as a number, over a sample chosen against the claim.

    Measured 2026-07-25: 13 of 33 forms are visible. The visible set spans
    record, prose, code AND config, which is why there is no assertion here
    that only `record` forms are seen -- that assertion was true of the old
    flattering sample and false of the classifier.
    """
    probe = _reach_probe()
    forms = probe["forms"]
    seen = [form for form in forms if form["seen_findings"]]

    assert len(forms) == 33
    assert len(seen) == 13, (
        f"reach changed: {len(seen)}/{len(forms)} seen; re-state the bound in "
        "the PRD and in propagation-leak-gate.py, do not just edit this number"
    )
    # Taxonomy may not grow silently, but category is a LABEL a human typed and
    # nothing derives it from the text, so it is never used to assert anything
    # about what the classifier can see.
    assert {form["category"] for form in forms} == {
        "record", "prose", "heading", "json", "code", "config",
    }


def test_probe_texts_cannot_be_edited_to_dodge_a_red_pin():
    """The cheapest way out of a failing pin was editing the probe string.

    Removing two quote characters from a JSON form was enough to return the
    suite to green after a real classifier widening, with the bound unchanged
    and nothing recorded. Pinning the texts makes that a deliberate two-place
    edit a reviewer can see.
    """
    probe = _reach_probe()
    forms = probe["forms"]
    texts = [form["text"] for form in forms]

    assert len(set(texts)) == len(texts), "two probe forms share the same text"
    assert len({form["id"] for form in forms}) == len(forms), "duplicate form id"
    assert (
        hashlib.sha256("\0".join(texts).encode("utf-8")).hexdigest()
        == probe["texts_sha256"]
    ), "a probe text changed; re-measure and update texts_sha256 deliberately"


def test_every_probe_form_carries_the_real_fact():
    """Guards against gutting the probe while every count still passes.

    The needle used to live in the same editable dict as the haystack, so
    setting `fact` to "O" and replacing all thirteen blind forms with the
    literal string "O" passed every test: right counts, right categories,
    `fact in text` true throughout. The needle is pinned to a literal now.
    """
    probe = _reach_probe()
    assert probe["fact"] == "Oriole Systems"
    for form in probe["forms"]:
        assert probe["fact"] in form["text"], (
            f"{form['id']} does not contain the fact it claims to carry"
        )
        assert len(form["text"]) > len(probe["fact"]), (
            f"{form['id']} is the bare fact with no surrounding shape, so it "
            "measures nothing"
        )
