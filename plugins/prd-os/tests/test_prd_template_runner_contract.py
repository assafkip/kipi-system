"""Contract test: the PRD template teaches the manifest shape the runner enforces.

Scar (sp-435edda6, 2026-06-30): templates/prd.md documented a `## Issues` manifest
of id/title/allowed_files/required_checks (the pre-spine shape), but the approval
gate in prd_runner.py requires `finding_id` + a `bypass_check` per entry. A PRD
authored to the template was rejected at approve. The template and the runner are
two representations of one contract; this test fails if they drift apart.

Runs in CI via `pytest plugins/prd-os/tests/`.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PRD_OS = os.path.dirname(HERE)
RUNNER = os.path.join(PRD_OS, "scripts", "prd_runner.py")
TEMPLATE = os.path.join(PRD_OS, "templates", "prd.md")

# Keys the approval gate reads from each manifest entry (source of truth = runner).
# bypass_check / bypass_exempt are an OR; the rest are individually required.
REQUIRED_BY_GATE = {"finding_id", "allowed_files", "required_checks"}
BYPASS_KEYS = {"bypass_check", "bypass_exempt"}
# prd_split also needs `id`; the template must teach it too.
REQUIRED_BY_SPLIT = {"id"}


def _issues_section(text):
    i = text.find("## Issues")
    assert i != -1, "templates/prd.md has no ## Issues section"
    return text[i:]


def test_runner_actually_reads_the_required_keys():
    """Guard the source-of-truth: the gate must still reference these keys."""
    runner = open(RUNNER).read()
    read_keys = set(re.findall(r'entry\.get\("(\w+)"\)', runner))
    missing = (REQUIRED_BY_GATE | BYPASS_KEYS) - read_keys
    assert not missing, f"prd_runner approval gate no longer reads: {sorted(missing)}"


def test_template_documents_every_runner_required_key():
    section = _issues_section(open(TEMPLATE).read())
    for key in REQUIRED_BY_GATE | REQUIRED_BY_SPLIT:
        assert key in section, (
            f"templates/prd.md ## Issues does not document required key '{key}' "
            "(template/runner drift -- sp-435edda6)"
        )


def test_template_documents_the_bypass_contract():
    section = _issues_section(open(TEMPLATE).read())
    assert any(k in section for k in BYPASS_KEYS), (
        "templates/prd.md ## Issues must document bypass_check or bypass_exempt"
    )
