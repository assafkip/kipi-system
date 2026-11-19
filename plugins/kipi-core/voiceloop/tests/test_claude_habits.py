#!/usr/bin/env python3
"""Seven Claude habits that never appear in the founder's writing (ASK-5427).

Why this file: the phrases come from a friend's prompt-only skill, counted across
4.5M words of Claude Code prose. They were measured at 0 hits across the founder's
170-row exemplar corpus on 2026-11-18, so a block cannot silence him. The words he
DOES write (`actually`, `rather than`, `the real`, `genuinely`, `bottom line`,
`not just`) are deliberately absent from the rules, and
`test_his_own_words_stay_unblocked` pins that: list gates that caught his real
vocabulary are the standing scar.

The corpus sweep over exemplars, organic posts and writing examples lives on the
instance side (`test_slop_shapes.py`), because this package ships to a public
mirror and the corpus does not. This file holds the synthetic half: each rule
fires on its habit, names an `instead`, and leaves the literal sense alone.
"""
import os
import sys

PKG_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

import pytest  # noqa: E402

from voiceloop import slop_shapes  # noqa: E402

#: rule name -> a draft carrying exactly that habit.
HABITS = {
    "slop-load-bearing": "The retry cap is a load-bearing piece of the queue.",
    "slop-cleanly": "The worker exits cleanly when the lock is gone.",
    "slop-fundamentally": "The two paths are fundamentally different in what they write.",
    "slop-worth-preamble": "It is worth flagging that the cache went stale.",
    "slop-single-superlative": "That is the single biggest cost in the run.",
    "slop-belt-and-suspenders": "We added a second check, belt-and-suspenders style.",
    "slop-totalizer-crown": "The open question shapes everything else in the plan.",
}

#: Literal senses the habits must leave alone (unslop's own "Survives" rule).
LITERAL_SENSES = (
    "The extra review was worth it.",
    "That file is worth keeping.",
    "The old mug is worth a dollar.",
    "He drives the car to the shop.",
    "The wall bears the roof and the load is spread.",
    "The reviewer shapes the draft by hand.",
)

#: His own measured words: any rule that fires on these silences him.
HIS_OWN_WORDS = (
    "I actually shipped it on Friday.",
    "We chose a queue rather than a cron job.",
    "The real problem is the handoff.",
    "It genuinely surprised me.",
    "Bottom line, the number held.",
    "This is not just a tool.",
    # Verbatim from his 2026-08-27 correction in voice/corrections.jsonl (ASK-5452).
    "Incorporate it into the mechanism in a way that does not fundamentally change the mechanism.",
)


def _rules(text):
    return {v["rule"] for v in slop_shapes.check(text)}


@pytest.mark.parametrize("rule,draft", sorted(HABITS.items()))
def test_each_habit_is_refused(rule, draft):
    assert rule in _rules(draft), f"{rule} did not fire on {draft!r}"


@pytest.mark.parametrize("rule", sorted(HABITS))
def test_each_rule_has_a_real_instead_line(rule):
    """Read the SHAPES tuple, not the detail string: check() always prefixes 'Write ',
    so asserting on the detail passes for an empty instead (review round 1, PR 842)."""
    instead = next(i for n, _p, i in slop_shapes.SHAPES if n == rule)
    assert len(instead.split()) >= 5, f"{rule} instead text is too thin to act on"


@pytest.mark.parametrize("text", LITERAL_SENSES)
def test_literal_senses_pass(text):
    new = set(HABITS) & _rules(text)
    assert not new, f"literal sense blocked by {new}: {text!r}"


@pytest.mark.parametrize("text", HIS_OWN_WORDS)
def test_his_own_words_stay_unblocked(text):
    assert slop_shapes.check(text) == [], text


@pytest.mark.parametrize("variant", [
    "The plan drives everything.", "That gates the rest.",
    "One flag governs the whole thing.", "Cost determines everything else.",
])
def test_totalizer_variants(variant):
    assert "slop-totalizer-crown" in _rules(variant)


def test_single_superlative_covers_largest():
    assert "slop-single-superlative" in _rules("It is the single largest cost.")


def test_the_new_rules_are_all_registered():
    names = {name for name, _pat, _instead in slop_shapes.SHAPES}
    assert set(HABITS) <= names
