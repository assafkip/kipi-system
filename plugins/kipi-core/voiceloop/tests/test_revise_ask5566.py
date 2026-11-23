#!/usr/bin/env python3
"""ASK-5566: two over-refusals of the meaning check, from the round 1 review of consulting #632.

why: (a) `marketer-ending` guidance says "drawn from facts already in the draft", so a repair
that restates a figure the draft already has is the instructed fix. Counting it as ADDED
refused it twice and shipped the defective post. (b) `banned-phrase`'s mandated fix is deleting
the phrase, and a deleted "not"/"if"/modal inside it read as a dropped meaning token.
A figure that is NEW, and a small word that is ADDED, must still be refused (negative controls).
"""
import os
import sys

PKG_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

import pytest  # noqa: E402

from voiceloop import meaning_check, revise  # noqa: E402

DRAFT = ("We cut the intake backlog by 3 hours a week because the scripts now file the mail.\n\n"
         "What would you do with that time?")
RESTATED = ("We cut the intake backlog by 3 hours a week because the scripts now file the mail.\n\n"
            "Those 3 hours now go to the client work.")
ENDING = [{"rule": "marketer-ending", "detail": "ends on a question"}]
PHRASE = [{"rule": "banned-phrase", "detail": "banned phrase: 'one thing you should know'"}]


def test_a_figure_already_in_the_draft_is_not_an_added_figure():
    assert meaning_check.changes(DRAFT, RESTATED, allow_removals=True, presence=True) == {}
    assert revise.revise(DRAFT, ENDING, runner=lambda p: RESTATED) == RESTATED


def test_a_genuinely_new_figure_is_still_refused():
    new = RESTATED.replace("Those 3 hours", "Those 40 hours")
    assert meaning_check.changes(DRAFT, new, allow_removals=True, presence=True) == {"numbers": ["+40 hour"]}
    with pytest.raises(revise.MeaningRefused):
        revise.revise(DRAFT, ENDING, runner=lambda p: new)


def test_a_changed_figure_is_still_refused():
    assert meaning_check.changes("It took 3 hours.", "It took 30 hours.")


def test_deleting_a_banned_phrase_is_not_refused():
    text = "Here is one thing you should know. The scripts file the mail."
    out = "The scripts file the mail."
    assert revise.revise(text, PHRASE, runner=lambda p: out) == out


def test_banned_phrase_repair_still_refuses_an_added_negation():
    text = "Here is one thing you should know. The scripts file the mail."
    bad = "The scripts do not file the mail."
    with pytest.raises(revise.MeaningRefused):
        revise.revise(text, PHRASE, runner=lambda p: bad)


def test_banned_phrase_repair_refuses_a_not_dropped_elsewhere():
    text = "Here is one thing you should know. The scripts do not file the mail."
    bad = "The scripts file the mail."
    with pytest.raises(revise.MeaningRefused):
        revise.revise(text, PHRASE, runner=lambda p: bad)


def test_banned_phrase_repair_refuses_a_deleted_figure():
    text = "Here is one thing you should know. It took 3 hours."
    bad = "It took a while."
    with pytest.raises(revise.MeaningRefused):
        revise.revise(text, PHRASE, runner=lambda p: bad)


def test_a_strict_rule_still_counts_a_restated_figure_as_added():
    word = [{"rule": "banned-word", "detail": "banned word 'leverage'"}]
    text = "We leverage 3 hours a week."
    bad = "We use 3 hours a week. Those 3 hours matter."
    with pytest.raises(revise.MeaningRefused):
        revise.revise(text, word, runner=lambda p: bad)

def test_banned_phrase_paraphrase_keeping_the_modal_passes():
    text = "Here is one thing you should know. The scripts file the mail."
    out = "Here is what you should know. The scripts file the mail."
    assert revise.revise(text, PHRASE, runner=lambda p: out) == out


def test_banned_phrase_still_present_excuses_nothing():
    text = "Here is one thing you should know. The scripts file the mail. You should check."
    bad = "Here is one thing you should know. The scripts file the mail."
    with pytest.raises(revise.MeaningRefused):
        revise.revise(text, PHRASE, runner=lambda p: bad)


def test_an_apostrophe_phrase_detail_parses():
    v = [{"rule": "banned-phrase", "detail": "banned phrase: \"here's what you shouldn't miss\""}]
    assert revise._banned_phrases(v) == ["here's what you shouldn't miss"]
