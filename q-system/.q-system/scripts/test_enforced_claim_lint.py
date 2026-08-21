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
import json
import os
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


DETECTOR_SRC = "#!/usr/bin/env python3\nimport sys\nprint('finding')\nsys.exit(0)\n"
BLOCKER_SRC = "#!/usr/bin/env python3\nimport sys\nsys.exit(2)\n"


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


# --- clause_key: unique, non-empty, anchored on a real heading -------------------

def test_clause_key_strips_only_a_trailing_parenthetical():
    """THE ALIASING BUG. A global parenthetical strip made '# Delete (local)' and
    '# Delete (prod)' both normalize to 'delete', so one entry covered both."""
    assert L.clause_key("Cleanup Rule (ENFORCED)") == "cleanup rule"
    assert L.clause_key("Delete (local) (ENFORCED)") == "delete local"
    assert L.clause_key("Delete (prod) (ENFORCED)") == "delete prod"
    assert L.clause_key("Delete (local)") != L.clause_key("Delete (prod)")


def test_clause_key_normalization_is_stable():
    """The exact rules, pinned. 'Normalising case and punctuation' was not
    implementable as written; these are the four steps."""
    assert L.clause_key("  Cleanup / Migration Rule (ENFORCED)  ") == "cleanup migration rule"
    assert L.clause_key("Pre-Action Echo (ENFORCED)") == "pre action echo"
    assert L.clause_key("A: B; C!") == "a b c"


def test_clause_key_duplicate_entries_are_refused():
    """C2. Two entries normalizing to one key means the second silently shadows
    the first and one heading's disposition becomes unreadable."""
    block = ('[{"clause": "Cleanup Rule", "status": "ADVISORY", "note": "n"},'
             ' {"clause": "cleanup   rule", "status": "ENFORCED", "note": "n"}]')
    v = L.lint_text(_rule(block=block), "fixture.md")
    assert 2 in _codes(v)
    assert "silently shadows" in " ".join(str(x) for x in v)


def test_clause_key_empty_key_is_refused():
    """C2. A clause of '...' normalizes to '' and would match any heading that
    also normalizes to '' -- coverage by accident, worse than no coverage."""
    block = '[{"clause": "...", "status": "ADVISORY", "note": "n"}]'
    v = L.lint_text(_rule(block=block), "fixture.md")
    assert 2 in _codes(v)
    assert "empty key" in " ".join(str(x) for x in v)


def test_clause_key_orphan_entry_is_refused():
    """C3. A disposition matching no heading reads as coverage to an auditor and
    is the residue left behind when a heading is reworded."""
    block = '[{"clause": "A Heading That Does Not Exist", "status": "ADVISORY", "note": "n"}]'
    v = L.lint_text(_rule(block=block), "fixture.md")
    assert 3 in _codes(v)
    assert "matches no ENFORCED-marked heading" in " ".join(str(x) for x in v)


def test_clause_key_colliding_headings_are_refused():
    """C2, mirror image. Two distinct MARKED HEADINGS normalizing to one key mean
    one entry covers both, and coverage returns clean. Deduplicating headings into
    a set hid exactly the accidental coverage this check exists to prevent."""
    block = '[{"clause": "Delete local", "status": "ADVISORY", "note": "n"}]'
    text = _rule(heading="Delete-local (ENFORCED)", block=block)
    text += "\n## Delete local (ENFORCED)\n\nMore text.\n"
    v = L.lint_text(text, "fixture.md")
    assert 2 in _codes(v)
    assert "both normalize to clause key" in " ".join(str(x) for x in v)


def test_clause_key_near_marker_is_not_the_marker():
    """The marker is the token, not the word. Testing for the substring
    'ENFORCED' stripped the parenthetical off '(UNENFORCED)' too, so it collided
    with '(ENFORCED)' -- while marked_headings, testing `MARKER in line`,
    correctly does not treat '(UNENFORCED)' as a marker at all. One definition."""
    assert L.clause_key("Cleanup Rule (UNENFORCED)") == "cleanup rule unenforced"
    assert L.clause_key("Cleanup Rule (ENFORCED)") == "cleanup rule"
    assert L.clause_key("Cleanup Rule (UNENFORCED)") != L.clause_key("Cleanup Rule (ENFORCED)")
    # And the heading reader agrees: (UNENFORCED) is not a claim.
    assert not L.marked_headings("# Cleanup Rule (UNENFORCED)")
    assert L.marked_headings("# Cleanup Rule (ENFORCED)")


def test_clause_key_control_distinct_keys_pass():
    """CONTROL. Two genuinely distinct clauses on two real headings are clean.

    Without this, C2 could be satisfied by a lint that rejects every multi-entry
    block, which would make the whole two-entry design unusable.
    """
    block = ('[{"clause": "First Rule", "status": "ADVISORY", "note": "n"},'
             ' {"clause": "Second Rule", "status": "ADVISORY", "note": "n"}]')
    text = _rule(heading="First Rule (ENFORCED)", block=block)
    text += "\n## Second Rule (ENFORCED)\n\nMore text.\n"
    assert L.lint_text(text, "fixture.md") == []


# --- exec_path and named_config: the executable exists and is wired THERE --------

def _tree(tmp_path, block, heading="Cleanup Rule (ENFORCED)",
          script_rel="q-system/scripts/real-lint.py", config_rel=".claude/settings.json",
          wire=True):
    """A repo-shaped fixture: a rules tree, a real script, and a config that may
    or may not reference it. Derived from what the lint actually resolves against
    (CLAUDE_PROJECT_DIR + repo-relative paths), not invented."""
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    script = tmp_path / script_rel
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(DETECTOR_SRC)
    cfg = tmp_path / config_rel
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cmd = ("python3 \"$CLAUDE_PROJECT_DIR/%s\"" % script_rel) if wire else "python3 other.py"
    cfg.write_text(json.dumps({"hooks": {"PostToolUse": [
        {"matcher": "Edit", "hooks": [{"type": "command", "command": cmd}]}]}}))
    rule = rules / "fixture.md"
    rule.write_text(_rule(heading=heading, block=block))
    return rule


def _lint_in(tmp_path, rule):
    old = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    try:
        return L.lint_file(rule)
    finally:
        if old is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = old


def test_exec_path_control_real_wired_script_passes(tmp_path):
    """CONTROL. A real script at a real path, referenced in the config named, is
    clean. Without this every assertion below could be met by refusing everything."""
    block = json.dumps([{"clause": "Cleanup Rule", "status": "DETECTED",
                         "exec": "q-system/scripts/real-lint.py",
                         "config": ".claude/settings.json"}])
    assert _lint_in(tmp_path, _tree(tmp_path, block)) == []


def test_exec_path_fictional_executable_is_refused(tmp_path):
    """THE MUTATION THE BRIEF NAMES. A rule claiming ENFORCED with a fictional
    executable must go red. The existing prompt-only-enforcement-guard is the
    cautionary case: it passes a fictional hook name at exit 0 because it matches
    vocabulary, not existence."""
    block = json.dumps([{"clause": "Cleanup Rule", "status": "ENFORCED",
                         "exec": "q-system/scripts/totally-imaginary-lint.py",
                         "config": ".claude/settings.json"}])
    v = _lint_in(tmp_path, _tree(tmp_path, block))
    assert 5 in _codes(v)
    assert "does not exist at that path" in " ".join(str(x) for x in v)


def test_exec_path_bare_basename_is_refused(tmp_path):
    """C5. A basename can name two different files and silently pair the wrong one
    with the wired command -- the residue skill-hook-audit.py still carries. This
    schema refuses it rather than resolving it by search."""
    block = json.dumps([{"clause": "Cleanup Rule", "status": "DETECTED",
                         "exec": "real-lint.py", "config": ".claude/settings.json"}])
    v = _lint_in(tmp_path, _tree(tmp_path, block))
    assert 5 in _codes(v)
    assert "bare basename" in " ".join(str(x) for x in v)


def test_exec_path_missing_fields_are_refused(tmp_path):
    """C5. ENFORCED and DETECTED both assert a wired executable, so an entry with
    neither exec nor config is asserting something it has not named."""
    block = json.dumps([{"clause": "Cleanup Rule", "status": "ENFORCED", "note": "n"}])
    v = _lint_in(tmp_path, _tree(tmp_path, block))
    assert 5 in _codes(v)


def test_named_config_orphan_script_is_refused(tmp_path):
    """C6. The script exists but the named config does not reference it: wired
    nowhere, so it never fires. This is the 8-of-30 population the forensics
    found."""
    block = json.dumps([{"clause": "Cleanup Rule", "status": "ENFORCED",
                         "exec": "q-system/scripts/real-lint.py",
                         "config": ".claude/settings.json"}])
    v = _lint_in(tmp_path, _tree(tmp_path, block, wire=False))
    assert 6 in _codes(v)
    assert "ORPHAN" in " ".join(str(x) for x in v)


def test_named_config_must_be_the_one_that_wires_it(tmp_path):
    """C6, THE finding-8 CASE. Asking only whether the exec appears in ANY config
    let a false `config` value pass whenever some OTHER config referenced it. The
    entry names one file, and that file is what gets read."""
    rule = _tree(tmp_path, json.dumps([{"clause": "Cleanup Rule", "status": "DETECTED",
                                        "exec": "q-system/scripts/real-lint.py",
                                        "config": "settings-template.json"}]))
    # settings.json (not named by the entry) DOES wire it; the named template does not.
    (tmp_path / "settings-template.json").write_text(json.dumps({"hooks": {}}))
    v = _lint_in(tmp_path, rule)
    assert 6 in _codes(v)
    assert "settings-template.json" in " ".join(str(x) for x in v)


def test_named_config_missing_file_is_refused(tmp_path):
    """C6. A config that does not exist cannot be wiring anything."""
    block = json.dumps([{"clause": "Cleanup Rule", "status": "DETECTED",
                         "exec": "q-system/scripts/real-lint.py",
                         "config": ".claude/nope.json"}])
    v = _lint_in(tmp_path, _tree(tmp_path, block))
    assert 6 in _codes(v)


def test_exec_path_advisory_needs_no_executable(tmp_path):
    """CONTROL. ADVISORY names no executable by definition, so exec checks must
    not fire on it -- otherwise the honest label would be the hardest to use."""
    block = json.dumps([{"clause": "Cleanup Rule", "status": "ADVISORY",
                         "note": "no executable exists for this"}])
    assert _lint_in(tmp_path, _tree(tmp_path, block)) == []


# --- exec_path: a textual occurrence is NOT wiring (the blocker) -----------------

def _tree_with_command(tmp_path, command, exec_rel="q-system/scripts/real-lint.py"):
    """Same fixture, but the config's hook command is supplied verbatim."""
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    script = tmp_path / exec_rel
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(DETECTOR_SRC)
    cfg = tmp_path / ".claude" / "settings.json"
    cfg.write_text(json.dumps({"hooks": {"PostToolUse": [
        {"matcher": "Edit", "hooks": [{"type": "command", "command": command}]}]}}))
    block = json.dumps([{"clause": "Cleanup Rule", "status": "DETECTED",
                         "exec": exec_rel, "config": ".claude/settings.json"}])
    rule = rules / "fixture.md"
    rule.write_text(_rule(block=block))
    return rule


def test_exec_path_control_real_invocation_passes(tmp_path):
    """CONTROL for the four false-referent cases below."""
    rule = _tree_with_command(
        tmp_path, 'python3 "$CLAUDE_PROJECT_DIR/q-system/scripts/real-lint.py"')
    assert _lint_in(tmp_path, rule) == []


def test_exec_path_backup_suffix_is_not_wiring(tmp_path):
    """THE BLOCKER, case 1. `real-lint.py.bak` CONTAINS the claimed path but is a
    different file, and the claimed one never runs."""
    rule = _tree_with_command(
        tmp_path, 'python3 "$CLAUDE_PROJECT_DIR/q-system/scripts/real-lint.py.bak"')
    v = _lint_in(tmp_path, rule)
    assert 6 in _codes(v)


def test_exec_path_longer_path_is_not_wiring(tmp_path):
    """THE BLOCKER, case 2. `archive/q-system/scripts/real-lint.py` contains the
    claimed path as a suffix and is a different file."""
    rule = _tree_with_command(
        tmp_path, 'python3 "$CLAUDE_PROJECT_DIR/archive/q-system/scripts/real-lint.py"')
    v = _lint_in(tmp_path, rule)
    assert 6 in _codes(v)


def test_exec_path_mention_outside_hooks_is_not_wiring(tmp_path):
    """THE BLOCKER, case 3. A path in an unrelated JSON value is prose, not wiring.
    The config is read STRUCTURALLY, so only hook commands count."""
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    exec_rel = "q-system/scripts/real-lint.py"
    (tmp_path / exec_rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / exec_rel).write_text(DETECTOR_SRC)
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({
        "_note": "we should wire q-system/scripts/real-lint.py one day",
        "hooks": {}}))
    block = json.dumps([{"clause": "Cleanup Rule", "status": "ENFORCED",
                         "exec": exec_rel, "config": ".claude/settings.json"}])
    rule = rules / "fixture.md"
    rule.write_text(_rule(block=block))
    v = _lint_in(tmp_path, rule)
    assert 6 in _codes(v)
    assert "is not wiring" in " ".join(str(x) for x in v)


def test_exec_path_escaping_the_repo_is_refused(tmp_path):
    """Containment. `../` and absolute values let an entry substantiate a claim
    with files OUTSIDE the repository. pathlib silently discards root on an
    absolute right-hand side, which is what makes the naive join dangerous."""
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"hooks": {}}))
    for bad in ("../outside/real-lint.py", "/etc/passwd"):
        block = json.dumps([{"clause": "Cleanup Rule", "status": "DETECTED",
                             "exec": bad, "config": ".claude/settings.json"}])
        rule = rules / "fixture.md"
        rule.write_text(_rule(block=block))
        v = _lint_in(tmp_path, rule)
        assert 5 in _codes(v), bad
        assert "escapes the repo" in " ".join(str(x) for x in v), bad


def test_root_comes_from_the_rule_not_the_environment(tmp_path):
    """Cross-project validation. Preferring CLAUDE_PROJECT_DIR blindly meant a rule
    in ANOTHER project validated against THIS project's scripts and returned clean.
    A claim must be substantiated inside the tree that makes it."""
    other = tmp_path / "other"
    (other / ".claude" / "rules").mkdir(parents=True)
    (other / ".claude" / "settings.json").write_text(json.dumps({"hooks": {}}))
    rule = other / ".claude" / "rules" / "foo.md"
    rule.write_text(_rule(block=json.dumps(
        [{"clause": "Cleanup Rule", "status": "DETECTED",
          "exec": "q-system/scripts/real-lint.py", "config": ".claude/settings.json"}])))
    # THIS project has the script and would satisfy the claim if root came from env.
    here = tmp_path / "here"
    (here / "q-system" / "scripts").mkdir(parents=True)
    (here / "q-system" / "scripts" / "real-lint.py").write_text("x")
    assert L.resolve_root(rule) == other.resolve()
    v = _lint_in(here, rule)
    assert 5 in _codes(v), "the other project's missing script must not be excused"


def test_advisory_naming_an_executable_is_refused(tmp_path):
    """One meaning per status. ADVISORY means no executable, so naming one
    contradicts the label. Skipping ADVISORY entries entirely let that pass."""
    block = json.dumps([{"clause": "Cleanup Rule", "status": "ADVISORY",
                         "note": "n", "exec": "q-system/scripts/real-lint.py"}])
    v = _lint_in(tmp_path, _tree(tmp_path, block))
    assert 5 in _codes(v)
    assert "ADVISORY" in " ".join(str(x) for x in v)


def test_non_string_fields_are_a_violation_not_a_traceback():
    """A validator that crashes on bad input is not a validator. An int in `exec`
    reached path arithmetic and raised TypeError, which would break both hook and
    --all mode."""
    for bad in ('{"clause": "Cleanup Rule", "status": "DETECTED", "exec": 7, "config": "c"}',
                '{"clause": "Cleanup Rule", "status": "DETECTED", "exec": ["a"], "config": "c"}',
                '{"clause": "Cleanup Rule", "status": "ADVISORY", "note": "n", "directives": "four"}'):
        v = L.lint_text(_rule(block="[%s]" % bad), "fixture.md")
        assert 4 in _codes(v), bad


# --- named_config: command POSITION, real placeholders, real config files --------

def test_named_config_mention_is_not_invocation():
    """BLOCKER. Every token was treated as an invoked target, so all three of these
    passed while the named script never ran."""
    E = "q-system/scripts/lint.py"
    for cmd in ('test -f "$CLAUDE_PROJECT_DIR/q-system/scripts/lint.py" && python3 other.py',
                'echo "$CLAUDE_PROJECT_DIR/q-system/scripts/lint.py"',
                'cat < "$CLAUDE_PROJECT_DIR/q-system/scripts/lint.py"'):
        assert E not in L.command_targets(cmd), cmd


def test_named_config_real_invocation_shapes_match():
    """CONTROL, from the shapes actually present in this repo's configs, not
    invented ones. If these stopped matching, every honest claim would break."""
    E = "q-system/scripts/lint.py"
    for cmd in ('python3 "$CLAUDE_PROJECT_DIR/q-system/scripts/lint.py"',
                'python3 "${CLAUDE_PROJECT_DIR}/q-system/scripts/lint.py"',
                'test -f "$CLAUDE_PROJECT_DIR/q-system/scripts/lint.py" && '
                'python3 "$CLAUDE_PROJECT_DIR/q-system/scripts/lint.py"',
                'python3 "$CLAUDE_PROJECT_DIR/q-system/scripts/lint.py" 2>/dev/null || true',
                'KIPI_X=1 python3 "$CLAUDE_PROJECT_DIR/q-system/scripts/lint.py"'):
        assert E in L.command_targets(cmd), cmd


def test_named_config_plugin_root_is_resolved():
    """MAJOR. Every plugin hook in this repo invokes through ${CLAUDE_PLUGIN_ROOT}
    (verified by reading them), so without this substitution no plugin-wired
    script could ever be substantiated."""
    cmd = 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/dogfood_gate.py"'
    targets = L.command_targets(cmd, plugin_root="plugins/kipi-design")
    assert "plugins/kipi-design/hooks/dogfood_gate.py" in targets
    assert L.plugin_root_for("plugins/kipi-design/hooks/hooks.json") == "plugins/kipi-design"
    assert L.plugin_root_for(".claude/settings.json") is None


def test_named_config_only_real_wiring_files_count(tmp_path):
    """BLOCKER. Any in-repo JSON with a hooks-shaped object satisfied the check.
    A fabricated docs/fake-hooks.json never runs."""
    assert L.is_wiring_config(".claude/settings.json")
    assert L.is_wiring_config("settings-template.json")
    assert L.is_wiring_config("plugins/kipi-core/hooks/hooks.json")
    assert not L.is_wiring_config("docs/fake-hooks.json")
    assert not L.is_wiring_config("plugins/kipi-core/hooks/other.json")
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    (tmp_path / "q-system").mkdir()
    (tmp_path / "q-system" / "lint.py").write_text("x")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "fake-hooks.json").write_text(json.dumps({"hooks": {"PostToolUse": [
        {"matcher": "Edit", "hooks": [{"type": "command",
                                       "command": 'python3 "$CLAUDE_PROJECT_DIR/q-system/lint.py"'}]}]}}))
    rule = rules / "fixture.md"
    rule.write_text(_rule(block=json.dumps([{"clause": "Cleanup Rule", "status": "ENFORCED",
                                             "exec": "q-system/lint.py",
                                             "config": "docs/fake-hooks.json"}])))
    v = _lint_in(tmp_path, rule)
    assert 6 in _codes(v)
    assert "not a file that wires hooks" in " ".join(str(x) for x in v)


def test_named_config_exec_form_args_are_read():
    """MAJOR. A legitimate handler using command + args was rejected because only
    `command` was read; and a non-command handler carrying a stray `command` field
    was accepted. Both are wrong in opposite directions."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "settings.json"
        p.write_text(json.dumps({"hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [
            {"type": "command", "command": "python3",
             "args": ["${CLAUDE_PROJECT_DIR}/q-system/scripts/lint.py"]},
            {"type": "notyet", "command": 'python3 "$CLAUDE_PROJECT_DIR/ghost.py"'},
        ]}]}}))
        cmds = L.wired_commands(p)
        joined = " ".join(cmds)
        assert "lint.py" in joined, "exec-form args must be read"
        assert "ghost.py" not in joined, "a non-command handler is not wiring"


def test_named_config_against_this_repos_real_wiring():
    """GROUNDING. Run the matcher over this repo's ACTUAL configs and assert it
    recognizes real, currently-wired scripts. A fixture I invent tests my
    assumption; the producer's own files test the system."""
    root = Path(__file__).resolve().parents[3]
    cfg = root / ".claude" / "settings.json"
    targets = set()
    for cmd in L.wired_commands(cfg):
        targets |= L.command_targets(cmd, None)
    assert "q-system/hooks/lessons-index.py" in targets
    assert "q-system/.q-system/token-guard.py" in targets
    plug = root / "plugins" / "kipi-design" / "hooks" / "hooks.json"
    if plug.is_file():
        ptargets = set()
        for cmd in L.wired_commands(plug):
            ptargets |= L.command_targets(cmd, "plugins/kipi-design")
        assert any(t.startswith("plugins/kipi-design/") for t in ptargets), ptargets


# --- posture: does the claimed label match what the wiring can do? ---------------

def _posture_tree(tmp_path, entry, src=BLOCKER_SRC, neutered=False, with_test=True):
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    exec_rel = "q-system/scripts/real-lint.py"
    (tmp_path / exec_rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / exec_rel).write_text(src)
    if with_test:
        t = tmp_path / "q-system/scripts/test_real_lint.py"
        # Mentions the enforcer by name. The previous fixture was `assert True`,
        # which is exactly the weakness the review called out: is_file() alone made
        # any empty or unrelated file a valid "receipt".
        t.write_text("import real_lint  # real-lint.py\n\n"
                     "def test_blocks():\n    assert real_lint.main() == 2\n")
    cmd = 'python3 "$CLAUDE_PROJECT_DIR/%s"' % exec_rel
    if neutered:
        cmd += " 2>/dev/null || true"
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PostToolUse": [
        {"matcher": "Edit", "hooks": [{"type": "command", "command": cmd}]}]}}))
    rule = rules / "fixture.md"
    rule.write_text(_rule(block=json.dumps([entry])))
    return rule


_ENFORCED = {"clause": "Cleanup Rule", "status": "ENFORCED",
             "exec": "q-system/scripts/real-lint.py",
             "config": ".claude/settings.json",
             "test": "q-system/scripts/test_real_lint.py"}


def test_posture_control_honest_enforced_passes(tmp_path):
    """CONTROL. A blocking script, wired unneutered, with a real test file, is a
    legitimate ENFORCED claim and must pass."""
    assert _lint_in(tmp_path, _posture_tree(tmp_path, dict(_ENFORCED))) == []


def test_posture_enforced_needs_a_named_test(tmp_path):
    """C9. THE LOAD-BEARING ONE. finding-5 was right that 'the source contains a
    non-zero exit' does not prove that path is reachable. The decidable proxy is
    the receipt: the only two rules in this repo that were already honest each
    name a test pinning the claim."""
    entry = dict(_ENFORCED)
    entry.pop("test")
    v = _lint_in(tmp_path, _posture_tree(tmp_path, entry))
    assert 9 in _codes(v)
    assert "names no `test`" in " ".join(str(x) for x in v)


def test_posture_enforced_test_must_exist(tmp_path):
    """C9. Naming a test that is not there is the same class of claim as naming a
    script that is not there."""
    entry = dict(_ENFORCED, test="q-system/scripts/test_ghost.py")
    v = _lint_in(tmp_path, _posture_tree(tmp_path, entry))
    assert 9 in _codes(v)


def test_posture_enforced_but_neutered_is_refused(tmp_path):
    """C7. `|| true` swallows the failure, so the hook can never block. 9 of this
    fleet's 46 hook commands are written this way; a rule calling one of them
    ENFORCED is simply wrong."""
    v = _lint_in(tmp_path, _posture_tree(tmp_path, dict(_ENFORCED), neutered=True))
    assert 7 in _codes(v)
    assert "honest label is DETECTED" in " ".join(str(x) for x in v)


def test_posture_enforced_without_a_nonzero_exit_is_refused(tmp_path):
    """C8. A script that exits 0 on every path cannot block, whatever the rule
    says. wiring-check.py is the real example: it documents exit 0 everywhere."""
    v = _lint_in(tmp_path, _posture_tree(tmp_path, dict(_ENFORCED), src=DETECTOR_SRC))
    assert 8 in _codes(v)


def test_posture_detected_that_actually_blocks_is_reported(tmp_path):
    """C10. Understating is the safer direction but it is still a false label: a
    reader trusting DETECTED would not expect their write refused."""
    entry = {"clause": "Cleanup Rule", "status": "DETECTED",
             "exec": "q-system/scripts/real-lint.py", "config": ".claude/settings.json"}
    v = _lint_in(tmp_path, _posture_tree(tmp_path, entry))
    assert 10 in _codes(v)
    assert "it can BLOCK" in " ".join(str(x) for x in v)


def test_posture_control_honest_detected_passes(tmp_path):
    """CONTROL for C10. A real detector, wired, is a legitimate DETECTED claim."""
    entry = {"clause": "Cleanup Rule", "status": "DETECTED",
             "exec": "q-system/scripts/real-lint.py", "config": ".claude/settings.json"}
    assert _lint_in(tmp_path, _posture_tree(tmp_path, entry, src=DETECTOR_SRC)) == []


def test_posture_neutering_forms_beyond_double_pipe_true(tmp_path):
    """BLOCKER. `|| true` and `|| exit 0` were the only forms recognized, so four
    other always-succeed shapes passed as unneutered and let an ENFORCED claim
    stand for a hook that cannot block."""
    for tail in ("; true", " || :", " || /bin/true", " || echo ignored"):
        d = tmp_path / tail.replace(" ", "_").replace("/", "_").replace(":", "c")
        d.mkdir()
        rules = d / ".claude" / "rules"
        rules.mkdir(parents=True)
        exec_rel = "q-system/scripts/real-lint.py"
        (d / exec_rel).parent.mkdir(parents=True, exist_ok=True)
        (d / exec_rel).write_text(BLOCKER_SRC)
        (d / "q-system/scripts/test_real_lint.py").write_text("# real-lint.py\n")
        (d / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PostToolUse": [
            {"matcher": "Edit", "hooks": [{"type": "command",
             "command": 'python3 "$CLAUDE_PROJECT_DIR/%s"%s' % (exec_rel, tail)}]}]}}))
        rule = rules / "fixture.md"
        rule.write_text(_rule(block=json.dumps([dict(_ENFORCED)])))
        v = _lint_in(d, rule)
        assert 7 in _codes(v), tail


def test_posture_stderr_redirect_alone_is_not_neutering():
    """CONTROL for the list above. `2>/dev/null` preserves the exit status, so it
    must NOT count as neutering -- an earlier comment implied it did."""
    assert not L._NEUTERED.search('python3 "$CLAUDE_PROJECT_DIR/x.py" 2>/dev/null')
    assert L._NEUTERED.search('python3 "$CLAUDE_PROJECT_DIR/x.py" 2>/dev/null || true')


def test_posture_exit_in_a_comment_or_string_does_not_count():
    """BLOCKER. Scanning raw text meant a script containing only `# sys.exit(2)`
    or `print("sys.exit(2)")` was classified as blocking while it always exits
    zero -- a false ENFORCED claim handed out by the checker meant to stop them."""
    assert not L.can_exit_nonzero("# sys.exit(2)\nprint('hi')\n", ".py")
    assert not L.can_exit_nonzero('print("sys.exit(2)")\n', ".py")
    assert not L.can_exit_nonzero("# exit 2\necho hi\n", ".sh")
    # And the real forms still count.
    assert L.can_exit_nonzero("import sys\nsys.exit(2)\n", ".py")
    assert L.can_exit_nonzero("raise SystemExit(2)\n", ".py")
    assert L.can_exit_nonzero("echo hi\nexit 2\n", ".sh")


def test_posture_one_unneutered_wiring_cannot_launder_a_neutered_one(tmp_path):
    """MAJOR. `all()` meant a script wired twice - blocking on a rare event and
    swallowed on the common one - read as a clean ENFORCED claim."""
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    exec_rel = "q-system/scripts/real-lint.py"
    (tmp_path / exec_rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / exec_rel).write_text(BLOCKER_SRC)
    (tmp_path / "q-system/scripts/test_real_lint.py").write_text("# real-lint.py\n")
    base = 'python3 "$CLAUDE_PROJECT_DIR/%s"' % exec_rel
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": base + " || true"}]}],
        "PostToolUse": [{"matcher": "Edit", "hooks": [
            {"type": "command", "command": base}]}]}}))
    rule = rules / "fixture.md"
    rule.write_text(_rule(block=json.dumps([dict(_ENFORCED)])))
    v = _lint_in(tmp_path, rule)
    assert 7 in _codes(v), "a neutered wiring must not be laundered by an unneutered one"


def test_posture_test_receipt_must_mention_the_enforcer(tmp_path):
    """MAJOR. is_file() alone was trivially satisfiable by an empty or unrelated
    file. Mentioning the executable is a weak but real tie, and it is the
    strongest link available without running anything."""
    entry = dict(_ENFORCED, test="q-system/scripts/unrelated_test.py")
    rule = _posture_tree(tmp_path, entry)
    (tmp_path / "q-system/scripts/unrelated_test.py").write_text("def test_x():\n    pass\n")
    v = _lint_in(tmp_path, rule)
    assert 9 in _codes(v)
    assert "never mentions" in " ".join(str(x) for x in v)


def test_posture_unprovable_exit_counts_as_possible():
    """The deliberate asymmetry. `sys.exit(main())` is how this lint and most
    non-trivial hooks here exit; a literal-only regex would call them advisory and
    push authors to label real gates DETECTED."""
    assert L.can_exit_nonzero("import sys\nsys.exit(main())\n", ".py")
    assert L.can_exit_nonzero("import sys\nsys.exit(2)\n", ".py")
    assert not L.can_exit_nonzero("import sys\nsys.exit(0)\n", ".py")
    assert not L.can_exit_nonzero("print('hi')\n", ".py")
    assert L.can_exit_nonzero("exit 1\n", ".sh")
    assert not L.can_exit_nonzero("exit 0\n", ".sh")


def test_posture_classifies_this_repos_real_scripts():
    """GROUNDING, not a fixture. The producer's own files decide whether the
    classifier is right: wiring-check.py documents exit 0 on every path,
    token-guard.py blocks, and this lint exits via sys.exit(main())."""
    root = Path(__file__).resolve().parents[3]
    cases = {"q-system/.q-system/scripts/wiring-check.py": False,
             "q-system/.q-system/token-guard.py": True,
             "q-system/hooks/lessons-index.py": False,
             "q-system/.q-system/scripts/enforced-claim-lint.py": True}
    for rel, expected in cases.items():
        p = root / rel
        if p.is_file():
            assert L.can_exit_nonzero(p.read_text(), p.suffix) is expected, rel


# --- directive count: a new directive cannot inherit an old disposition ----------

def _directive_rule(count_decl, body):
    block = json.dumps([{"clause": "Cleanup Rule", "status": "ADVISORY",
                         "note": "n", "directives": count_decl}])
    return _rule(block=block, body=body)


def test_directive_count_control_matching_count_passes():
    """CONTROL. A declaration matching the section is clean. Without this the
    ratchet could be satisfied by a check that always disagrees."""
    body = "You MUST do the thing.\nYou must never skip it.\n"
    assert L.lint_text(_directive_rule(2, body), "fixture.md") == []


def test_directive_count_added_directive_trips_the_ratchet():
    """C12, THE POINT (finding-3). Coverage keyed to a heading is heading-level
    wearing a clause-level label: one disposition greens every directive beneath a
    broad heading. Adding a MUST must force a re-read rather than inherit."""
    body = "You MUST do the thing.\nYou must never skip it.\nAnd you MUST also log it.\n"
    v = L.lint_text(_directive_rule(2, body), "fixture.md")
    assert 12 in _codes(v)
    assert "carries 3" in " ".join(str(x) for x in v)


def test_directive_count_removed_directive_also_trips():
    """The ratchet is two-way. Deleting a directive silently would leave a
    disposition claiming to cover more than the section says."""
    v = L.lint_text(_directive_rule(2, "You MUST do the thing.\n"), "fixture.md")
    assert 12 in _codes(v)


def test_directive_count_is_optional():
    """Omission is the honest form of 'not ratcheted', and it is VISIBLE in the
    block -- unlike a default, which would look like a count."""
    block = json.dumps([{"clause": "Cleanup Rule", "status": "ADVISORY", "note": "n"}])
    body = "You MUST do the thing.\nAnd you MUST do another.\n"
    assert L.lint_text(_rule(block=block, body=body), "fixture.md") == []


def test_directive_count_ignores_fenced_examples():
    """A directive quoted inside a code fence is not an instruction the rule is
    issuing, so it must not move the count."""
    body = "You MUST do the thing.\n\n```\nthe docs say you MUST NOT do this\n```\n"
    assert L.lint_text(_directive_rule(1, body), "fixture.md") == []


def test_directive_count_one_per_line_not_per_occurrence():
    """A line saying MUST twice is one instruction to a reader. Counting
    occurrences would move the number on rewording rather than on meaning."""
    body = "You MUST do X and you MUST do Y.\n"
    assert L.lint_text(_directive_rule(1, body), "fixture.md") == []


def test_sections_are_level_aware():
    """MEASURED, not assumed. Splitting at EVERY heading gave 3 directives across
    all 32 marked sections in the real tree, against a forecast of 118. A ratchet
    with a near-zero population cannot detect growth in anything."""
    text = ("# Top (ENFORCED)\n\nYou MUST do A.\n\n"
            "## Sub\n\nYou MUST do B.\n\n"
            "# Other\n\nYou MUST do C.\n")
    got = {L._HEADING_RE.match(h).group(2): L.count_directives(b)
           for h, b in L.sections(text)}
    assert got["Top (ENFORCED)"] == 2, "an H1 owns its subsections"
    assert got["Sub"] == 1
    assert got["Other"] == 1, "and stops at the next same-level heading"


def test_directive_regex_population_is_not_near_zero():
    """GROUNDING. Pins the decision that case-insensitive matching was required:
    on this repo's real marked sections the population must stay substantial, or
    the ratchet is decoration."""
    root = Path(__file__).resolve().parents[3]
    total = 0
    markers = 0
    for f in sorted((root / ".claude" / "rules").rglob("*.md")):
        for heading, body in L.sections(f.read_text()):
            if L.MARKER in heading:
                markers += 1
                total += L.count_directives(body)
    assert markers >= 25, markers
    assert total >= 50, ("directive population collapsed to %d across %d markers; "
                         "uppercase-only matching gave 15 and was rejected for this"
                         % (total, markers))


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
