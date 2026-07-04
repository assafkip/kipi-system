"""Mechanical/judgment split contract (fable-mechanical-judgment-split).

The discipline checklist is judgment-only: every mechanically checkable item
(regex, count, file inspection) is PROMOTED into fable-discipline-lint and
REMOVED from the checklist. Two mechanical slices exist today, so this test
pins (a) both detectors are enumerated in the hook header with CATCHES and
MISSES (the hook-blind-spots scar: undocumented coverage reads as full
coverage), and (b) the checklist no longer states either mechanical rule as
a checkbox the model re-judges per task.
"""
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1] / "skills/fable-discipline"
LINT = SKILL_DIR / "scripts/fable-discipline-lint.py"
CHECKLIST = SKILL_DIR / "references/checklist.md"


def _lint_docstring() -> str:
    return LINT.read_text().split('"""')[1]


def test_hook_header_enumerates_both_detectors():
    doc = _lint_docstring()
    assert "Detector coverage" in doc
    # detector 2 gets its own block; split the docstring on its title so each
    # detector's enumeration is asserted independently (a global substring
    # check would pass on the test-isolation block alone)
    marker = "Deferral-capture detector coverage"
    assert marker in doc, (
        "deferral detector has no enumerated CATCHES/MISSES block in the header"
    )
    isolation_block, deferral_block = doc.split(marker, 1)
    for block_name, block in (("isolation", isolation_block),
                              ("deferral", deferral_block)):
        for word in ("CATCHES", "MISSES"):
            assert word in block, f"{block_name} block lacks {word}"
    assert "SKIPS" in deferral_block, "deferral block lacks SKIPS"


def test_hook_header_scope_matches_both_detector_scopes():
    """The Scope paragraph must describe BOTH detectors' firing conditions.
    Scar: the deferral detector shipped while Scope still said 'fires only
    on a Python test file', so the header contradicted the hook's actual
    exit-2 surface (codex adversarial finding, fable-mechanical-judgment-split).
    """
    doc = _lint_docstring()
    scope = doc.split("Scope", 1)[1]
    assert "ANY code file" in scope, (
        "Scope does not state the deferral detector fires on any code file"
    )
    assert "TEST file" in scope, (
        "Scope does not state the isolation detector's test-file scope"
    )
    assert "only on a Python TEST file" not in scope.split("\n")[0], (
        "Scope leads with the old single-detector claim"
    )


def _checkbox_lines() -> list[str]:
    return [
        line for line in CHECKLIST.read_text().splitlines()
        if line.lstrip().startswith("- [ ]")
    ]


def test_checklist_has_no_mechanical_test_isolation_item():
    hits = [l for l in _checkbox_lines() if ":memory:" in l]
    assert not hits, (
        f"test-isolation is hook-enforced (mechanical); checklist must not "
        f"restate it as a checkbox: {hits}"
    )


def test_checklist_has_no_mechanical_deferral_item():
    hits = [l for l in _checkbox_lines() if re.search(r"spillover add", l)]
    assert not hits, (
        f"deferral-language capture is hook-enforced (mechanical); checklist "
        f"must not restate the command as a checkbox: {hits}"
    )
