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
    """C4. Two blocks means two sources of truth and a reader that has to guess.

    Asserts the condition code plus 'exactly one', not the full sentence: the
    wording moved once already (blocks -> markers, when marker counting replaced
    fence counting) and a test that fails on a reworded message while the
    behaviour is correct is noise, not coverage.
    """
    text = _rule(block='[{"clause": "Cleanup Rule", "status": "ADVISORY", "note": "n"}]')
    text += '\n<!-- enforcement -->\n```json\n[]\n```\n'
    v = L.lint_text(text, "fixture.md")
    assert 4 in _codes(v)
    assert "exactly one is" in str(v[0])


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


# --- grammar: the four holes codex found in 461bd3ac ---------------------------

def test_grammar_indented_heading_still_needs_coverage():
    """C1 via the producer's regex. Markdown allows up to 3 leading spaces, and
    apply_claude_changes._HEADING (line 182) accepts them. An earlier version
    anchored at column 0, so `   # Foo (ENFORCED)` was a heading to the census and
    invisible to coverage -- a silent, exploitable evasion."""
    text = "---\nd: f\n---\n\n   # Sneaky Rule (ENFORCED)\n\nText.\n"
    v = L.lint_text(text, "fixture.md")
    assert _codes(v) == [1]


def test_heading_matches_producer_regex():
    """The anti-drift pin. Two readers of 'is this a heading' must stay one rule.

    Asserts on BEHAVIOUR against the producer's accepted forms rather than on the
    pattern string, so a cosmetic rewrite of either regex does not fail while a
    real divergence does.
    """
    for raw in ("# A (ENFORCED)", " # A (ENFORCED)", "   # A (ENFORCED)",
                "###### A (ENFORCED)", "#\tA (ENFORCED)"):
        assert L.marked_headings(raw), "producer accepts %r as a heading" % raw
    for raw in ("    # A (ENFORCED)", "#A (ENFORCED)", "####### A (ENFORCED)"):
        assert not L.marked_headings(raw), "producer rejects %r as a heading" % raw


def test_grammar_second_malformed_block_is_not_ignored():
    """C4. A valid covering block plus a MALFORMED second one used to pass on the
    valid half, defeating the malformed-block refusal and the one-block invariant
    at the same time. Markers are counted, not well-formed fences."""
    text = _rule(block='[{"clause": "Cleanup Rule", "status": "ADVISORY", "note": "n"}]')
    text += "\n<!-- enforcement -->\nnot a fence at all\n"
    v = L.lint_text(text, "fixture.md")
    assert 4 in _codes(v)
    assert "enforcement markers in one file" in str(v[0])


def test_grammar_marker_without_a_fence_is_refused():
    """C4. A marker whose fence is missing or malformed must be a violation, not a
    silence. Silence here reads identically to 'this file makes no claim'."""
    text = "---\nd: f\n---\n\n# Cleanup Rule (ENFORCED)\n\n<!-- enforcement -->\n\nnope\n"
    v = L.lint_text(text, "fixture.md")
    assert 4 in _codes(v)
    assert "no parseable" in str(v[0])


def test_grammar_duplicate_keys_are_refused():
    """C4. json.loads keeps the LAST duplicate silently, so an entry could present
    one disposition to the machine and another to a human reading the file."""
    block = ('[{"clause": "Cleanup Rule", "status": "ADVISORY", '
             '"status": "ENFORCED", "note": "n"}]')
    v = L.lint_text(_rule(block=block), "fixture.md")
    assert 4 in _codes(v)
    assert "duplicate key" in str(v[0])


def test_all_mode_treats_an_unreadable_file_as_a_violation(tmp_path):
    """C0. --all runs in lefthook and CI, where skipping a file it could not read
    and printing PASS is a green meaning 'inspected nothing'."""
    bad = tmp_path / "broken.md"
    bad.write_bytes(b"\xff\xfe\x00 not valid utf-8 \xff")
    assert L.lint_file(bad, strict=True), "strict mode must report the unreadable file"
    assert L.lint_file(bad, strict=False) == [], "hook mode must stay silent"


# --- self-scoping ---------------------------------------------------------------

def test_scope_only_rule_markdown():
    assert L.is_rule_file("/repo/.claude/rules/foo.md")
    assert L.is_rule_file("/repo/.claude/rules/nested/foo.md")
    assert not L.is_rule_file("/repo/.claude/settings.json")
    assert not L.is_rule_file("/repo/q-system/scripts/foo.py")
    assert not L.is_rule_file("/repo/docs/rules/foo.md")


def test_scope_accepts_relative_paths():
    """THE BYPASS. Requiring a leading slash made coverage depend on whether the
    editing tool emitted an absolute path, so a legal relative spelling of the
    same file skipped the gate entirely."""
    assert L.is_rule_file(".claude/rules/foo.md")
    assert L.is_rule_file("./.claude/rules/foo.md")
    assert L.is_rule_file(".claude/rules/nested/foo.md")
    # Still not ours: a same-named directory that is not the rules tree.
    assert not L.is_rule_file("myclaude/rules/foo.md")


def test_marker_inside_a_larger_example_fence_is_not_a_disposition():
    """THE QUOTED-EXAMPLE BYPASS. A rule may DOCUMENT the convention by showing a
    marker and a ```json block inside a ````-fenced example. That inert example
    must not satisfy a live ENFORCED heading outside the fence."""
    text = (
        "---\nd: f\n---\n\n# Real Rule (ENFORCED)\n\n"
        "Here is what a disposition looks like:\n\n"
        "````markdown\n"
        "<!-- enforcement -->\n"
        "```json\n"
        '[{"clause": "Real Rule", "status": "ADVISORY", "note": "n"}]\n'
        "```\n"
        "````\n")
    v = L.lint_text(text, "fixture.md")
    assert _codes(v) == [1], "the quoted example must not cover the live heading"


def test_real_block_after_an_example_fence_still_counts():
    """CONTROL for the test above. Fence tracking must not swallow the real block
    that follows the example -- a scanner that loses the genuine disposition is
    as broken as one that accepts a quoted one."""
    text = (
        "---\nd: f\n---\n\n# Real Rule (ENFORCED)\n\n"
        "````markdown\n<!-- enforcement -->\n```json\n[]\n```\n````\n\n"
        "<!-- enforcement -->\n```json\n"
        '[{"clause": "Real Rule", "status": "ADVISORY", "note": "n"}]\n'
        "```\n")
    assert L.lint_text(text, "fixture.md") == []


def test_unterminated_fence_is_refused():
    """C4. A marker whose fence never closes yields no parseable block, which must
    be a violation rather than a silence."""
    text = ("---\nd: f\n---\n\n# Real Rule (ENFORCED)\n\n"
            "<!-- enforcement -->\n```json\n[]\n")
    v = L.lint_text(text, "fixture.md")
    assert 4 in _codes(v)
