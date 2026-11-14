#!/usr/bin/env python3
"""The hand-back row reads a hand-back, not the words "need from you" (ASK-4909).

why this file exists (2026-11-14). `assistant_gate` carried the bare substring
"i need from you" as a refusal phrase. That substring is in an ordinary sentence a
consultant writes to a client when he scopes a meeting ("That's the only time I need
from you."), and a real sent email refused at exit 2 on the report channel because of
it. A gate that refuses his own writing gets switched off, the same scar this module
already records for "should i".

What the row is FOR is the 2026-08-06 incident: the generated text handed the work
back to the operator ("one thing I need from you: ..."). The property is that the
phrase INTRODUCES an ask the writer waits on: a colon or a "before I can" after it, or
a placeholder object ("what", "thing") in front of it that only exists to point at the
ask. A concrete object in front of it ("the only time I need from you") names the
thing already, so nothing is handed back.

All text here is synthetic. This file ships to a public repo.
"""
import os
import sys
import unittest

PKG_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

from voiceloop import assistant_gate  # noqa: E402


def _hand_back_hits(text):
    return [v for v in assistant_gate.violations(text) if "need from you" in v]


class TestAScopingSentenceIsNotAHandBack(unittest.TestCase):
    """The red case. Each of these refused before the fix."""

    def test_the_only_time_i_need_from_you(self):
        text = ("We start with one call, both of you, about two hours. "
                "Thats the only time I need from you.")
        self.assertEqual(assistant_gate.violations(text), [])
        self.assertEqual(assistant_gate.refusal_violations(text), [])

    def test_with_a_curly_apostrophe(self):
        text = "That’s the only time I need from you this month."
        self.assertEqual(assistant_gate.violations(text), [])

    def test_the_time_id_need_from_you(self):
        text = "Two hours is all the time I'd need from you, and it is one call."
        self.assertEqual(assistant_gate.violations(text), [])


class TestARealHandBackStillRefuses(unittest.TestCase):
    """The control. If these pass, the row was loosened into a hole."""

    def test_here_is_what_i_need_from_you_before_i_can_continue(self):
        text = "Here is what I need from you before I can continue."
        self.assertTrue(_hand_back_hits(text), assistant_gate.violations(text))
        self.assertTrue(assistant_gate.refusal_violations(text))

    def test_a_colon_introduces_the_ask(self):
        text = "Before I draft it, I need from you: the routine's real name."
        self.assertTrue(_hand_back_hits(text), assistant_gate.violations(text))

    def test_the_incident_shape(self):
        text = ("Say A, B, or park, and I write it. If A, one thing I need from "
                "you: is the routine's real name fine to describe in public?")
        self.assertTrue(_hand_back_hits(text), assistant_gate.violations(text))

    def test_a_placeholder_object_points_at_the_ask(self):
        for text in ("What I need from you is a pick between the two.",
                     "The only thing I'd need from you is a yes.",
                     "Here’s what I need from you."):
            with self.subTest(text=text):
                self.assertTrue(_hand_back_hits(text),
                                assistant_gate.violations(text))

    def test_a_gated_continuation_without_a_placeholder(self):
        text = "There is one name I need from you to continue."
        self.assertTrue(_hand_back_hits(text), assistant_gate.violations(text))

    def test_a_line_break_inside_the_phrase(self):
        text = "Here is what I need\nfrom you before I write it."
        self.assertTrue(_hand_back_hits(text), assistant_gate.violations(text))


class TestANamedObjectAfterThePhraseIsAHandBack(unittest.TestCase):
    """ASK-4925 item 1. #812 dropped these; the base caught every one.

    When "I" opens the clause, the thing needed comes AFTER the phrase, so the
    writer is asking the reader for it. That is the plainest hand-back in English.
    """

    def test_the_object_follows_the_phrase(self):
        for text in (
                "I need from you the real name of the routine before I can finish.",
                "I need from you a decision on the opener.",
                "I'd need from you a yes or a no on the second option.",
                "I'll need from you the final numbers before I write it.",
                "I will need from you two answers, then it goes out.",
                "What do I need from you? The real name of the routine.",
                "The draft is ready, and I need from you the export.",
                "The draft is ready.\nI'll need from you one more file."):
            with self.subTest(text=text):
                self.assertTrue(_hand_back_hits(text),
                                assistant_gate.violations(text))
                self.assertTrue(assistant_gate.refusal_violations(text))


class TestAPlaceholderWithAColonStaysAHandBack(unittest.TestCase):
    """ASK-4925 item 2, the decision pinned: this STAYS a hand-back.

    "one thing I need from you: <ask>" is the 2026-08-06 incident's own shape, and
    "the only thing I need from you: two hours" is the same words. The gate reads
    phrasing, so it cannot tell a client being scoped from an operator being asked.
    A writer keeps the sentence by naming the object first ("two hours is the only
    time I need from you"), which the red case above already lets through.
    """

    def test_the_only_thing_with_a_colon(self):
        text = "That's the only thing I need from you: two hours on one call."
        self.assertTrue(_hand_back_hits(text), assistant_gate.violations(text))
        self.assertTrue(assistant_gate.refusal_violations(text))


class TestEveryRefusalRowSurvivesAWrapOrANbsp(unittest.TestCase):
    """ASK-4925 item 3. `violations` collapses whitespace as `refusal_violations` does."""

    def test_a_no_break_space_inside_a_refusal_phrase(self):
        text = "Which one do you\xa0want? Both read fine to me."
        self.assertIn("refusal or hand-back: 'which one do you want'",
                      assistant_gate.violations(text))

    def test_a_soft_wrap_inside_a_refusal_phrase(self):
        text = "My\ncall: A. It is the better one."
        self.assertIn("refusal or hand-back: 'my call:'",
                      assistant_gate.violations(text))

    def test_both_entry_points_agree(self):
        text = "Which one do you\xa0want? Tell me\nwhich and I write it."
        self.assertEqual(
            [v for v in assistant_gate.violations(text)
             if v.startswith("refusal or hand-back")],
            assistant_gate.refusal_violations(text))


class TestOneThingINeedReadsAHandBack(unittest.TestCase):
    """ASK-4925 item 4. The bare substring "one thing i need" ate ordinary prose."""

    def test_ordinary_prose_passes(self):
        for text in ("The one thing I need is the Q3 export, and then I can model it.",
                     "There's one thing I need before Friday: nothing from your team."):
            with self.subTest(text=text):
                self.assertEqual(assistant_gate.violations(text), [])

    def test_one_thing_i_need_introducing_an_ask_refuses(self):
        for text in ("One thing I need: is the routine's real name fine to use?",
                     "There is one thing I need before I can continue."):
            with self.subTest(text=text):
                self.assertTrue(assistant_gate.refusal_violations(text))

    def test_the_2026_08_06_incident_still_refuses_on_this_row(self):
        # The incident as the module docstring records it (already public).
        text = ("I'm not going to write this one as-is. That's a real content "
                "choice, not a formatting task, and it's yours to make, not mine "
                "to make silently.\n\nMy call: **A**. The mechanism is genuinely "
                "useful.\n\nWhich one? Say A, B, or park, and I write it. If A, one "
                "thing I need from you: is the routine's real name fine to "
                "describe in public?")
        self.assertTrue(_hand_back_hits(text), assistant_gate.violations(text))


if __name__ == "__main__":
    unittest.main()
