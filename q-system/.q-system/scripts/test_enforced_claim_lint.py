#!/usr/bin/env python3
"""Tests for enforced-claim-lint.py (ASK-965).

Pairs with `q-system/.q-system/scripts/enforced-claim-lint.py`.

Every test here is written so it CAN FAIL for the reason it claims. Where a
condition could be satisfied by a lint that simply refuses everything, there is a
paired control asserting the clean case passes -- a check that cannot tell right
from broken is decoration.

Fixtures are built from the producer's own shape (the block grammar the lint
parses, and the marker convention `_rule_marks` in apply_claude_changes.py
censuses), not invented, because an invented fixture tests my assumption rather
than the system.
"""
import importlib.util
import sys
from pathlib import Path

_LINT = Path(__file__).resolve().parent / "enforced-claim-lint.py"


def _load():
    spec = importlib.util.spec_from_file_location("enforced_claim_lint", _LINT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["enforced_claim_lint"] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load()


def _rule(heading="Cleanup Rule (ENFORCED)", block=None, body="Some directive text.\n"):
    """A minimal rule file. `block` is the raw text placed after the marker."""
    out = "---\ndescription: fixture\n---\n\n# %s\n\n%s\n" % (heading, body)
    if block is not None:
        out += "\n<!-- enforcement -->\n```json\n%s\n```\n" % block
    return out


def _codes(violations):
    return sorted(v.condition for v in violations)


# --- grammar: the block parses, or it is refused -------------------------------

def test_grammar_valid_block_parses_clean():
    """CONTROL. A well-formed block covering the marked heading is clean.

    Without this, every grammar assertion below could be satisfied by a lint that
    rejects all input.
    """
    block = '[{"clause": "Cleanup Rule", "status": "ADVISORY", "note": "no executable"}]'
    assert L.lint_text(_rule(block=block), "fixture.md") == []


def test_grammar_malformed_json_is_refused():
    """C4. A block that is not valid JSON is a schema violation, not a skip."""
    v = L.lint_text(_rule(block='[{"clause": "Cleanup Rule",}]'), "fixture.md")
    assert 4 in _codes(v)
    assert "not valid JSON" in str(v[0])


def test_grammar_non_array_is_refused():
    """C4. A bare object has no record delimiter; the array is the point."""
    v = L.lint_text(_rule(block='{"clause": "Cleanup Rule", "status": "ADVISORY"}'),
                    "fixture.md")
    assert 4 in _codes(v)
    assert "JSON array" in str(v[0])


def test_grammar_two_entries_both_parse():
    """THE finding-2 CASE. A flat key:value mapping had no record delimiter, so
    two entries repeated keys with undefined behaviour. Two JSON objects are
    unambiguous, and both must be read."""
    block = ('[{"clause": "First Rule", "status": "ADVISORY", "note": "n"},'
             ' {"clause": "Second Rule", "status": "ADVISORY", "note": "n"}]')
    text = _rule(heading="First Rule (ENFORCED)", block=block)
    text += "\n## Second Rule (ENFORCED)\n\nMore text.\n"
    entries, violations = L.parse_block(text, "fixture.md")
    assert violations == []
    assert [e["clause"] for e in entries] == ["First Rule", "Second Rule"]


def test_grammar_unknown_key_is_refused():
    """C4. A tolerated unknown key is where a future `skip: true` arrives wearing
    a permitted name. Same reasoning as ALLOWED_PROPOSAL_KEYS."""
    block = '[{"clause": "Cleanup Rule", "status": "ADVISORY", "note": "n", "skip": true}]'
    v = L.lint_text(_rule(block=block), "fixture.md")
    assert 4 in _codes(v)
    assert "unknown key" in str(v[0])


def test_grammar_bad_status_is_refused():
    """C4. An unknown status must not be silently ignored: that is how a typo
    becomes a free pass."""
    block = '[{"clause": "Cleanup Rule", "status": "ENFORCEDD", "note": "n"}]'
    v = L.lint_text(_rule(block=block), "fixture.md")
    assert 4 in _codes(v)


def test_grammar_missing_required_key_is_refused():
    """C4. An entry with no status covers nothing and must not read as coverage."""
    v = L.lint_text(_rule(block='[{"clause": "Cleanup Rule"}]'), "fixture.md")
    assert 4 in _codes(v)
    assert "missing required key" in str(v[0])


def test_grammar_two_blocks_are_refused():
    """C4. Two blocks means two sources of truth and a reader that has to guess."""
    text = _rule(block='[{"clause": "Cleanup Rule", "status": "ADVISORY", "note": "n"}]')
    text += '\n<!-- enforcement -->\n```json\n[]\n```\n'
    v = L.lint_text(text, "fixture.md")
    assert 4 in _codes(v)
    assert "enforcement blocks in one file" in str(v[0])


def test_grammar_plain_json_fence_is_not_a_block():
    """The marker, not the fence, is what makes a block. A rule quoting an example
    JSON snippet must not have it parsed as its own disposition."""
    text = "# Cleanup Rule (ENFORCED)\n\n```json\n[{\"not\": \"a disposition\"}]\n```\n"
    entries, violations = L.parse_block(text, "fixture.md")
    assert entries == [] and violations == []


# --- coverage: a marker with no entry is a bare claim ---------------------------

def test_marker_without_any_block_is_a_violation():
    """C1. THE MUTATION THE BRIEF DEMANDS, in unit form: a rule claiming ENFORCED
    with nothing substantiating it must be refused."""
    v = L.lint_text(_rule(block=None), "fixture.md")
    assert _codes(v) == [1]


def test_marker_with_uncovered_heading_is_a_violation():
    """C1. A block that disposes SOME markers does not green the others. This is
    the file-level-coverage hole, closed at marker granularity."""
    block = '[{"clause": "First Rule", "status": "ADVISORY", "note": "n"}]'
    text = _rule(heading="First Rule (ENFORCED)", block=block)
    text += "\n## Second Rule (ENFORCED)\n\nMore text.\n"
    v = L.lint_text(text, "fixture.md")
    assert _codes(v) == [1]
    assert "Second Rule" in str(v[0])


def test_unmarked_rule_is_untouched():
    """CONTROL + the fleet-safety property. A rule making no enforcement claim is
    not this lint's business, which is what keeps a fleet-wide hook from blocking
    every instance's ordinary rules."""
    text = "---\ndescription: fixture\n---\n\n# Just A Rule\n\nText.\n"
    assert L.lint_text(text, "fixture.md") == []


def test_marker_in_prose_does_not_demand_coverage():
    """Headings only, matching what _rule_marks counts separately. A rule that
    MENTIONS the marker while discussing it (as several rules here do) is not
    making a heading-level claim."""
    text = "# Just A Rule\n\nSome rules say (ENFORCED) in their heading.\n"
    assert L.lint_text(text, "fixture.md") == []


# --- self-scoping ---------------------------------------------------------------

def test_scope_only_rule_markdown():
    assert L.is_rule_file("/repo/.claude/rules/foo.md")
    assert L.is_rule_file("/repo/.claude/rules/nested/foo.md")
    assert not L.is_rule_file("/repo/.claude/settings.json")
    assert not L.is_rule_file("/repo/q-system/scripts/foo.py")
    assert not L.is_rule_file("/repo/docs/rules/foo.md")
