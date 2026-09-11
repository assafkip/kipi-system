"""What md-prune is allowed to archive.

Founder decision 2026-08-14, verbatim: "yes decisions.md should not be
auto-pruned, delete the budget entry."

A decision LOG accumulates on purpose. Archiving its oldest rules archives the
reasoning the newest ones are built on. The budget was the defect, not the
file's length.

This test exists because deleting a dict key leaves no trace. The next person to
"restore the canonical budgets" would re-add it in one line with nothing
objecting, and the pruner is wired `2>/dev/null || true`, so the first anyone
would know is a rule gone missing from decisions.md.
"""
import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "md-prune.py"


def load_md_prune():
    """Import a module whose filename has a dash in it."""
    spec = importlib.util.spec_from_file_location("md_prune", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["md_prune"] = module
    spec.loader.exec_module(module)
    return module


def test_decisions_md_is_never_auto_pruned():
    """The founder decision, as an assertion."""
    budgets = load_md_prune().BUDGETS
    assert "canonical/decisions.md" not in budgets, (
        "decisions.md is back under a prune budget. That is a founder reversal "
        "(2026-08-14), not a cleanup -- a decision log accumulates on purpose."
    )


def test_the_other_budgets_are_still_there():
    """Negative control. A test that only asserts an ABSENCE goes green if the
    whole table is emptied, or if BUDGETS is renamed and this import silently
    reads a different dict. This one can fail for the reason we care about.
    """
    budgets = load_md_prune().BUDGETS
    assert len(budgets) >= 10, f"BUDGETS collapsed to {len(budgets)} entries"
    for expected in ("canonical/discovery.md", "my-project/relationships.md"):
        assert expected in budgets, f"{expected} vanished from BUDGETS"


def test_the_pruner_would_actually_read_this_table():
    """Guards the rename case the control above only half-covers: if the prune
    loop stops reading BUDGETS, both tests above keep passing while the real
    behaviour moves somewhere this file cannot see.
    """
    source = SCRIPT.read_text()
    assert "BUDGETS.items()" in source, (
        "the prune loop no longer iterates BUDGETS, so this test file is "
        "asserting against a table nothing reads"
    )
