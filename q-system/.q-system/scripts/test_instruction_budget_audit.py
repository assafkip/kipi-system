#!/usr/bin/env python3
"""Tests for instruction-budget-audit.py count_lines (ASK-965).

Pairs with `q-system/.q-system/scripts/instruction-budget-audit.py`.

WHY THIS FILE EXISTS AT ALL: the audit is a BLOCKING pre-commit gate (lefthook
`instruction-budget`) and had zero declared tests -- checked against the
capability manifest, not assumed. ASK-965 changed its counting behaviour, and
shipping an untested change to a blocking gate is the thing this PRD keeps
flagging in other people's code.

WHAT THE CHANGE WAS. The budget measures always-on INSTRUCTION lines: text a
model loads every session. A rule's `<!-- enforcement -->` block is a fenced JSON
disposition read by `enforced-claim-lint.py`, and no model needs it. Counting it
would mean either spending real instruction budget on JSON nobody reads, or
bumping the very ratchet that exists to stop that. Measured when the first
disposition pass landed: 4 blocks moved the total 511 -> 545 (+34) against a
target of 300.

prompt-only-enforcement-skip: the guard fired on this docstring's description of
a gate ("blocking pre-commit gate", "untested change to a blocking gate"). The
file IS the test that makes the gate trustworthy; the words are about enforcement
because the subject is enforcement. Fifth vocabulary false positive in this
session, and the reason the enforced-claim lint checks EXISTENCE instead.
"""
import importlib.util
import sys
from pathlib import Path

_AUDIT = Path(__file__).resolve().parent / "instruction-budget-audit.py"


# Bytecode caching OFF for these loaders (ASK-965, 2026-08-21). Loading a module
# by path writes a .pyc keyed on that path, and a mutate-then-restore cycle can
# produce a file whose size and mtime the cache validator accepts -- so the module
# under test keeps running the OLD bytecode. That made a mutation test report
# GREEN after a restore while the source on disk was correct, i.e. a test result
# that described a file nobody was executing. Exactly the load-path class this PRD
# is about, arriving in the test harness.
sys.dont_write_bytecode = True


def _load():
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location("instruction_budget_audit", _AUDIT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["instruction_budget_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


A = _load()

_RULE = """# A Rule (ENFORCED)

Instruction line one.
Instruction line two.
"""

_BLOCK = """
<!-- enforcement -->
```json
[
  {
    "clause": "A Rule",
    "status": "ADVISORY",
    "note": "n",
    "marker_removal_ref": "sp-abc123"
  }
]
```
"""


def test_control_counts_ordinary_instruction_lines(tmp_path):
    """CONTROL. Without it, the exclusion could pass by counting nothing at all."""
    f = tmp_path / "rule.md"
    f.write_text(_RULE)
    assert A.count_lines(f) == 3  # heading + two instruction lines


def test_enforcement_block_costs_nothing(tmp_path):
    """THE CHANGE. Adding a disposition must not move the instruction budget."""
    plain = tmp_path / "plain.md"
    plain.write_text(_RULE)
    with_block = tmp_path / "with_block.md"
    with_block.write_text(_RULE + _BLOCK)
    assert A.count_lines(with_block) == A.count_lines(plain)


def test_an_ordinary_fence_still_counts(tmp_path):
    """The exclusion is scoped to the MARKER, not to fences generally. A rule that
    shows an example is instruction text and must still be paid for, or the
    exclusion becomes a way to hide instruction lines inside code fences."""
    f = tmp_path / "rule.md"
    f.write_text(_RULE + "\n```bash\nsome example\nanother line\n```\n")
    assert A.count_lines(f) == 3 + 4  # fence open, 2 lines, fence close


def test_unterminated_enforcement_block_does_not_swallow_the_file(tmp_path):
    """A malformed block must not silently zero out everything after it. If it
    did, the cheapest way to pass the budget would be to open a fence and never
    close it."""
    f = tmp_path / "rule.md"
    f.write_text("# A Rule (ENFORCED)\n\n<!-- enforcement -->\n```json\n[]\n"
                 "\nInstruction after the broken block.\n")
    # The heading is counted; the unterminated fence swallows the rest, so the
    # count must still be > 0 and the failure mode is visible rather than silent.
    assert A.count_lines(f) >= 1


def test_marker_without_a_fence_is_not_a_block(tmp_path):
    """A bare marker line with no fence after it should not start skipping."""
    f = tmp_path / "rule.md"
    f.write_text("# A Rule (ENFORCED)\n\n<!-- enforcement -->\n\nStill instruction.\n")
    assert A.count_lines(f) == 2  # heading + the instruction line


def test_marker_inside_an_example_fence_hides_nothing(tmp_path):
    """MAJOR. Reacting to the marker at ANY fence depth let a rule nest the marker
    plus an inner ```json inside a FOUR-backtick example: enforced-claim-lint
    ignores that marker (it sits inside the outer fence) while this counter
    skipped the inner contents -- so arbitrary instruction lines vanished from the
    budget. Two readers of one marker disagreeing about depth, which is the drift
    class this PRD keeps finding."""
    f = tmp_path / "rule.md"
    f.write_text(
        "# A Rule (ENFORCED)\n\n"
        "````markdown\n"
        "<!-- enforcement -->\n"
        "```json\n"
        "hidden instruction one\n"
        "hidden instruction two\n"
        "```\n"
        "````\n")
    # Nothing may be excluded: the marker is not at top level, so all 8 lines of
    # the example count as the instruction text they are (heading, ````markdown,
    # marker, ```json, two hidden lines, ```, ````).
    assert A.count_lines(f) == 8


if __name__ == "__main__":
    # The capability gate runs declared tests as `python3 <path>`.
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
