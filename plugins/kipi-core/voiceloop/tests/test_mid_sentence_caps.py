#!/usr/bin/env python3
"""A CAPITAL IN THE MIDDLE OF A SENTENCE (sp-b970c388, measured 2026-09-10).

Four consecutive reddit reply runs shipped eleven model-introduced mid-sentence
capitals past a clean gate -- "the part That would worry me", "treats The chart",
"which is why They came back mixed" -- because `check_capitalization` and
`post_repair`'s step-2 loop both walk `_sentence_start_offsets` and can therefore only
ever see the FIRST word of a sentence. The trail carried `repairs: null` and
`revisions: 0`, so nothing in the stack observed any of it and the operator caught all
four runs by eye.

WHAT THIS FILE IS, AND THE HALF IT DELIBERATELY DOES NOT HOLD. The rule is a closed
word list, and the word-list scar says a list-based gate that was never measured
against the operator's own writing will block his real vocabulary. That measurement is
a CORPUS SCAN, and the corpus is the operator's and lives in his instance. This repo is
public, so the scan cannot run here and its absence is not an oversight: the
counterexample gate is instance-side, against the instance's own voice corpus, and this
file holds the MECHANISM -- the recorded defects, the three narrowing constraints, each
constraint's named true positive, and the wiring.

Read a green run here narrowly. It proves the rule still catches what it was built for
and still refuses the shapes it was narrowed against. It cannot prove the word set is
clean against anybody's corpus, and widening the set is a change that has to face the
instance-side scan.

Read-only and pure: the repair functions never touch disk, and nothing here writes.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
PKG_PARENT = os.path.dirname(PKG)
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

from voiceloop import post_repair  # noqa: E402

# The linter is a SCRIPT in the skeleton subtree, loaded by path rather than imported,
# which is the same shape the instance adapter uses. Four levels up from this file is
# the repo root in both trees, because an instance carries `plugins/` and `q-system/`
# side by side exactly as the skeleton does.
REPO_ROOT = os.path.dirname(os.path.dirname(PKG_PARENT))
VOICE_LINT = os.path.join(REPO_ROOT, "q-system", ".q-system", "scripts", "voice-lint.py")


@pytest.fixture(scope="module")
def linter():
    # A hard failure, never a skip. The whole package depends on this script being
    # reachable, and a skipped suite reads exactly like a passing one.
    assert os.path.exists(VOICE_LINT), f"voice linter not found at {VOICE_LINT}"
    return post_repair._load_linter(VOICE_LINT)


def _words(hits):
    return [word for _, word in hits]


def _repair(text, linter):
    """`repair()` with no instance config: an empty allowlist and no banned-word map.

    The engine takes every config as a REQUIRED argument so a second instance cannot
    inherit the first one's data. That makes the empty case the honest default here.
    """
    return post_repair.repair(text, allowlist=frozenset(), linter=linter, mapping={})


# --------------------------------------------------------------------------------------
# THE TWELVE LIVE DEFECTS, as they were reported across runs 3 to 6.
#
# Each fragment is set inside the sentence it needs to be mid-sentence in, because the
# fragment alone would put the capital at a sentence START, which the old layer already
# handled and which would make this fixture pass against unfixed code.
#
# TWO OF THE TWELVE ARE EXPECTED MISSES and are asserted as misses rather than dropped.
# "Latency" is a common noun; no closed function-word set reaches a common noun without
# also reaching "Google Sheet", "PowerPoint", "FX" and "SKU". Recording them as
# expected-MISS is the honest shape: the day someone widens the rule to catch them, this
# test fails and the widening has to face the instance-side corpus scan.
# --------------------------------------------------------------------------------------
MEASURED = [
    ("run3-a", "This is the part That would worry me.", ["That"]),
    ("run3-b", "It's That the agent cannot tell the two apart.", ["That"]),
    ("run3-c", "A system That edits its own source is a different animal.", ["That"]),
    ("run3-d", "The thing that breaks isn't the Latency.", []),
    ("run4-a", "The thing that breaks isn't Latency.", []),
    ("run5-a", "It rebuilds the chart Every cycle.", ["Every"]),
    ("run6-a", "The reason The labels move is the rebuild.", ["The"]),
    ("run6-b", "It treats The chart as disposable.", ["The"]),
    ("run6-c", "The labels move and The object rebuilds itself.", ["The"]),
    ("run6-d", "The AI generators do The same thing.", ["The"]),
    ("run6-e", "That is which is why They came back mixed.", ["They"]),
    ("run6-f", "Every cycle They regenerate the whole slide.", ["They"]),
]


@pytest.mark.parametrize("label,text,expected", MEASURED,
                         ids=[row[0] for row in MEASURED])
def test_the_twelve_measured_defects(label, text, expected, linter):
    assert _words(post_repair.mid_sentence_cap_hits(text, linter)) == expected


def test_ten_of_the_twelve_are_caught_and_the_two_misses_are_the_common_nouns(linter):
    """The rate, stated as a number so a silent regression in coverage is visible."""
    caught = [label for label, text, _ in MEASURED
              if post_repair.mid_sentence_cap_hits(text, linter)]
    assert len(caught) == 10, caught
    missed = [label for label, text, _ in MEASURED
              if not post_repair.mid_sentence_cap_hits(text, linter)]
    assert missed == ["run3-d", "run4-a"], missed


@pytest.mark.parametrize("label,text,expected", MEASURED,
                         ids=[row[0] for row in MEASURED])
def test_the_repair_lowercases_exactly_what_the_detector_found(label, text, expected,
                                                               linter):
    repaired, changes = post_repair.repair_mid_sentence_caps(text, linter)
    if not expected:
        assert repaired == text and changes == []
        return
    assert len(changes) == 1 and changes[0].startswith("lowercased mid-sentence capital")
    for word in expected:
        assert f" {word} " not in repaired and f" {word}." not in repaired
    # Idempotent: a second pass over repaired text finds nothing left.
    assert post_repair.mid_sentence_cap_hits(repaired, linter) == []


# --------------------------------------------------------------------------------------
# CONSTRAINT 1: the word must be in the closed set.
# --------------------------------------------------------------------------------------

def test_a_word_outside_the_set_is_never_touched(linter):
    """The true positive of constraint 1. Every one of these sits in exactly the
    position the regex matches -- a lowercase letter, a space, a capitalized word -- and
    survives only because the word is not in the set. Without constraint 1 this rule is
    "lowercase any capitalized word mid-clause", which eats every product name he
    writes."""
    for text in ("he tracks every SKU in one Google sheet by hand",
                 "the deck is a Powerpoint he rebuilds every month",
                 "they moved off Etsy onto one ledger",
                 "the fix went into Python and then shipped"):
        assert post_repair.mid_sentence_cap_hits(text, linter) == [], text


def test_the_constraint_1_guard_is_load_bearing(linter):
    """Negative self-test for the case above: the SAME shape with an in-set word IS
    caught. If this ever reads as a no-hit, constraint 1 has stopped narrowing and
    started being the whole rule."""
    assert _words(post_repair.mid_sentence_cap_hits(
        "he tracks every SKU in one That by hand", linter)) == ["That"]


LEGITIMATE = [
    "he tracks every SKU in one Google Sheet by hand",
    "they moved off Etsy and Square onto one ledger",
    "the deck is a PowerPoint he rebuilds every month",
    "the FX rate comes from the bank feed",
    "he sent it over as a PDF and asked for OK",
    "the fix went into JavaScript and then into Python",
]


@pytest.mark.parametrize("text", LEGITIMATE)
def test_his_real_capitals_are_never_touched(text, linter):
    assert post_repair.mid_sentence_cap_hits(text, linter) == []
    assert post_repair.repair_mid_sentence_caps(text, linter) == (text, [])


def test_bare_I_and_acronyms_cannot_match(linter):
    """`[A-Z][a-z']+` is what keeps them out, so a one-letter "I" and an all-caps token
    are unreachable by this rule rather than allowlisted out of it."""
    assert post_repair.mid_sentence_cap_hits(
        "the part I would worry about is the AI and the SKU", linter) == []


# --------------------------------------------------------------------------------------
# CONSTRAINT 2: the preceding character must be a lowercase letter or a comma, on the
# SAME line. (A digit qualified until PR #395 round 2; it admitted "## 2.1 The key".)
# --------------------------------------------------------------------------------------

def test_a_sentence_start_capital_is_never_touched(linter):
    """The true positive of constraint 2, and the layer's own boundary. Sentence starts
    belong to the existing pass, and a capital after a terminator, a colon, a quote, a
    dash, a newline or a list marker is skipped because the preceding character is not a
    lowercase letter or a comma. (A digit was an admitted predecessor until PR #395
    round 2 removed it; see the regex.)"""
    for text in ("It broke. The chart rebuilt itself.",
                 "the problem: The labels move",
                 'he said, "That is the whole bug"',
                 "the labels move\nThey come back mixed",
                 "- The chart rebuilds",
                 "the rule (That one) still holds"):
        assert post_repair.mid_sentence_cap_hits(text, linter) == [], text


def test_the_constraint_2_predecessors_that_DO_qualify(linter):
    """The named true positives of constraint 2: each of the two predecessors it still
    admits produces a hit. There were three until PR #395 round 2 dropped the digit,
    which had been admitting numbered section prefixes.

    The rationale here was WRONG when first written (PR #395 review, nit). It claimed
    deleting the lookbehind would leave the skip-list test above green. It does not:
    widening the predecessor turns that test red on "It broke. The chart rebuilt
    itself." What this case actually holds is the other direction -- that constraint 2
    is an ADMIT list and not a blanket refusal. Narrow the lookbehind to nothing and
    the rule stops firing entirely while every skip case stays green."""
    for text, expected in (("the labels move The chart rebuilds", ["The"]),
                           ("it rebuilt, The chart came back mixed", ["The"])):
        assert _words(post_repair.mid_sentence_cap_hits(text, linter)) == expected, text


# --------------------------------------------------------------------------------------
# CONSTRAINT 3: a following capitalized word means a title-case run, left alone.
# --------------------------------------------------------------------------------------
TITLE_CASE_RUNS = [
    "a note in The New York Times said the same thing",
    "I pushed it to The Garden repo last night",
    "he runs it through The Home Depot vendor portal",
]


@pytest.mark.parametrize("text", TITLE_CASE_RUNS)
def test_a_title_case_run_is_left_alone(text, linter):
    """The named true positive of the followed-by-a-capital guard. Without it every one
    of these loses its "The", because "the" is in the set and the preceding character is
    a lowercase letter. A guard whose true positive nobody can name reads like a guard
    that works."""
    assert post_repair.mid_sentence_cap_hits(text, linter) == []


def test_the_guard_is_load_bearing_and_not_decoration(linter):
    """Negative self-test on the guard itself: the same sentence WITHOUT the following
    capital is caught. If this ever passes as a no-hit, the guard has stopped being a
    narrowing and started being the whole rule."""
    assert _words(post_repair.mid_sentence_cap_hits(
        "a note in The paper said the same thing", linter)) == ["The"]


# --------------------------------------------------------------------------------------
# Code spans, wiring, and the standing rule that this layer repairs and never blocks.
# --------------------------------------------------------------------------------------

def test_code_spans_and_fences_are_never_rewritten(linter):
    """Same protection the other repair passes get, from the linter's own regexes: a
    rewrite inside a fence would break a working command."""
    inline = "run the thing `and The chart` before you ship"
    assert post_repair.mid_sentence_cap_hits(inline, linter) == []
    fenced = "the fix is here\n\n```\nx = The.chart\n```\n\nand it works\n"
    assert post_repair.mid_sentence_cap_hits(fenced, linter) == []


def test_the_full_repair_pass_reaches_the_new_layer(linter):
    """The wiring proof. Everything above tests the function; this tests the CALL.

    The call is a standalone statement between step 2 and step 3, NOT an entry in
    `repair()`\'s group-0 tuple, which is where it wrongly lived until PR #395 finding 1.
    (This docstring said "the tuple" after that move, round 3 nit.) Delete the call and
    this test goes red, measured."""
    repaired, changes = _repair("The reason The labels move is the rebuild.", linter)
    assert "the labels move" in repaired
    assert any(line.startswith("lowercased mid-sentence capital") for line in changes), \
        changes


def test_the_layer_runs_after_the_passes_that_CREATE_its_shape(linter):
    """The contraction pass turns "is not That" into "isn\'t That", which is the shape
    this layer looks for, so this case only passes if this layer sees that output.

    ITS ORIGINAL DOCSTRING WAS FALSE (PR #395 round 3, minor). It claimed a reorder
    putting this layer first "leaves the capital standing", so this test would go red.
    Measured: moving the call ahead of `repair_contractions` turns
    `test_the_pass_runs_after_the_sentence_start_pass` and
    `test_the_sentence_start_pass_cannot_plant_a_capital_this_layer_owns` red, and
    leaves THIS one green. Those two are what hold the ordering; this one holds only
    that the contracted shape is reachable, which is worth having and is not the same
    claim. A test whose stated reason nobody checked is how a suite grows decoration."""
    repaired, changes = _repair("The chart is not That reliable in practice.", linter)
    assert "isn't that reliable" in repaired, repaired
    assert any(line.startswith("lowercased mid-sentence capital") for line in changes), \
        changes


def test_it_repairs_and_never_blocks(linter):
    """The operator's standing rule on this layer: a fail that can be fixed gets fixed
    rather than killing the draft, because killing a whole post over capitalization
    narrows the usable set for no gain. So a mid-sentence capital must not appear in the
    violation surface, before or after the repair."""
    text = "It treats The chart as disposable."
    # The detector SEES it ...
    assert _words(post_repair.mid_sentence_cap_hits(text, linter)) == ["The"]
    # ... and neither violation surface reports it, before the repair.
    assert post_repair.capitalization_violations(text, linter) == []
    assert post_repair.violations(text, linter, phrases_path="") == []
    # The repair fixes it in place, so the text that reaches the gate is clean AND
    # changed. Stub the feature to identity and the last assertion goes red.
    repaired, changes = _repair(text, linter)
    assert repaired != text and "treats the chart" in repaired, repaired
    assert any(line.startswith("lowercased mid-sentence capital") for line in changes), \
        changes


def test_the_word_set_carries_no_product_or_proper_noun(linter):
    """A single capitalized word can never be a product name, so the set is checked
    against the shape rather than against a list somebody has to remember to extend:
    every member is lowercase, alphabetic, and at least two characters."""
    for word in post_repair.MID_SENTENCE_LOWERCASE_WORDS:
        assert word == word.lower() and word.isalpha() and len(word) >= 2, word
    assert {"and", "as", "have", "it", "your", "its"}.isdisjoint(
        post_repair.MID_SENTENCE_LOWERCASE_WORDS), \
        "all six are the unterminated-sentence-start class and were removed on purpose"


SALUTATIONS = [
    "Hey man, Your invoice is attached and the deck is done",
    "Hey man, Its the same problem as last week",
]


@pytest.mark.parametrize("text", SALUTATIONS)
def test_a_salutation_is_not_a_mid_clause(text, linter):
    """The reproducer that took `your` and `its` out of the set (PR #395 review).

    A salutation has no terminator, so the word after the comma IS a sentence start and
    the linter's offsets cannot see it. `dm` and `email` are default channel scopes, so
    this shape is in range. The corpus scan could not refute these words because the
    corpus holds posts, not one-line DMs. That is the limit of any corpus gate: it can
    only refute a word with text somebody already wrote."""
    assert post_repair.mid_sentence_cap_hits(text, linter) == []
    assert post_repair.repair_mid_sentence_caps(text, linter) == (text, [])


def test_the_pass_runs_after_the_sentence_start_pass(linter):
    """FINDING 1 (PR #395 review, major), as a regression test.

    This pass used to run in group 0, before step 2. Step 2 rewrites with
    `subn(..., count=1)` against the raw text, so it hits the FIRST standalone lowercase
    occurrence of its target word rather than the sentence-start one. A draft opening a
    later sentence with that same word got the capital put straight back, while
    `changes` still reported the repair. A false receipt is worse than the silence this
    layer exists to end.

    Every other `repair()`-level fixture in this file opens with a capital, so step 2
    finds no lowercase sentence start and the shape never arises. This one opens
    lowercase on purpose."""
    text = "it treats The chart as disposable. the fix is simple."
    repaired, changes = _repair(text, linter)
    assert repaired == "It treats the chart as disposable. The fix is simple.", repaired
    assert any(line.startswith("lowercased mid-sentence capital") for line in changes), \
        changes
    # The receipt has to be TRUE: nothing the change log claims may survive in the text.
    assert post_repair.mid_sentence_cap_hits(repaired, linter) == []


def test_the_sentence_start_pass_cannot_plant_a_capital_this_layer_owns(linter):
    """The same ordering, seen from the other side (PR #395 review, finding 2).

    Step 2 is itself a PRODUCER of mid-sentence capitals on ordinary lowercase-start
    prose, with no model involved. Running this layer after it means step 2's own
    injections get cleaned up for every word in the set. That is a consequence of the
    finding-1 fix, not an independent guarantee: step 2 can still plant a capital this
    layer's closed set does not cover, which is tracked separately."""
    for text in ("the agent keeps the chart open all day. the fix is a plugin.",
                 "nobody reads the summaries. the leftovers are what break you."):
        repaired, _ = _repair(text, linter)
        assert post_repair.mid_sentence_cap_hits(repaired, linter) == [], repaired


def test_a_none_body_is_answered_and_never_raises(linter):
    """The `text or ""` guard stated an intent the function did not have (PR #395
    review, minor): `_protected_spans` ran first and raised TypeError on None, so the
    guard was unreachable. Now the empty cases return before anything touches the
    linter."""
    for empty in (None, ""):
        assert post_repair.mid_sentence_cap_hits(empty, linter) == []
        assert post_repair.repair_mid_sentence_caps(empty, linter) == (empty, [])


DOTTED_AND_NUMBERED = [
    # A dotted brand name. Found in this repo's own prose, not constructed.
    "he reads it on Every.to most mornings",
    "the writeup went up on Which.co.uk last week",
    # A numbered section prefix. The digit predecessor used to admit these.
    "## 2.1 The dedup key",
    "see 3.4 That table for the numbers",
]


@pytest.mark.parametrize("text", DOTTED_AND_NUMBERED)
def test_a_dotted_name_or_a_numbered_heading_is_left_alone(text, linter):
    """PR #395 round 2, minor. `Every.to` -> `every.to` is exactly the failure this
    module's header calls worse than the bug: it cleared all three constraints because
    the dot is not a word character, so the trailing-boundary lookahead let it through.
    `## 2.1 The dedup key` cleared them because a digit was an admitted predecessor.

    Both were fixed by NARROWING, which is the only safe direction here: a rule whose
    worst case is eating a name he meant never gets widened to catch more."""
    assert post_repair.mid_sentence_cap_hits(text, linter) == [], text
    assert post_repair.repair_mid_sentence_caps(text, linter) == (text, [])


def test_a_trailing_period_still_matches(linter):
    """Negative self-test on the dotted-name narrowing: `(?!\\.\\w)` excludes a dot
    followed by a word character, NOT a sentence-ending period. If this goes green as a
    no-hit, the narrowing has eaten a real case."""
    assert _words(post_repair.mid_sentence_cap_hits(
        "the labels move and then rebuild, and so does The.", linter)) == ["The"]
