#!/usr/bin/env python3
"""test_voice_lint_caps: the capitalization rule in voice-lint.py.

WHY (2026-07-28): a client email was drafted entirely in lowercase because
`voice-dna.md` says "Lowercase-default. Rarely capitalizes." That line describes
the founder's Slack/DM register, not anything he sends to a client. The founder
caught it by reading the draft. Nothing checked it, because every voice rule in
the linter judged word choice and none judged casing.

Isolation: every case writes to a tempfile. No test touches a real content path.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "voice_lint", Path(__file__).resolve().parent / "voice-lint.py"
)
voice_lint = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(voice_lint)


def lint_text(text, *, proper_nouns=None, name="reply-draft.md"):
    """Lint `text` as an outreach file, optionally beside a proper-nouns list."""
    tmp = Path(tempfile.mkdtemp())
    outreach = tmp / "q-inst" / "output" / "outreach"
    outreach.mkdir(parents=True)
    if proper_nouns is not None:
        canonical = tmp / "q-inst" / "canonical"
        canonical.mkdir(parents=True)
        (canonical / "proper-nouns.txt").write_text(
            "\n".join(proper_nouns) + "\n", encoding="utf-8"
        )
    target = outreach / name
    target.write_text(text, encoding="utf-8")
    return [v for v in voice_lint.lint_file(str(target)) if v["rule"] == "capitalization"]


class SentenceInitialCaps(unittest.TestCase):
    def test_lowercase_paragraph_start_is_flagged(self):
        found = lint_text("i went through your list.\n")
        self.assertTrue(found, "a lowercase paragraph opener must be caught")

    def test_lowercase_after_period_is_flagged(self):
        found = lint_text("The form runs on Railway. angus set it up.\n")
        self.assertEqual(len(found), 1)
        self.assertIn("angus", found[0]["detail"])

    def test_correctly_capitalized_prose_is_clean(self):
        found = lint_text(
            "I went through your list. The account number field already exists.\n"
        )
        self.assertEqual(found, [])

    def test_lowercase_list_item_is_flagged(self):
        found = lint_text("What I need:\n\n1. who owns the Railway account\n")
        self.assertTrue(found)

    def test_capitalized_list_item_is_clean(self):
        found = lint_text("What I need:\n\n1. Who owns the Railway account\n")
        self.assertEqual(found, [])


class BareI(unittest.TestCase):
    def test_bare_lowercase_i_is_flagged(self):
        found = lint_text("The form is live but i cannot log in.\n")
        self.assertTrue(any("'i'" in v["detail"] for v in found))

    def test_capital_i_is_clean(self):
        found = lint_text("The form is live but I cannot log in.\n")
        self.assertEqual(found, [])


class ProperNouns(unittest.TestCase):
    NOUNS = ["Blue Peak", "Brightspeed", "Railway", "Angus", "GroupMe"]

    def test_lowercase_proper_noun_is_flagged(self):
        found = lint_text(
            "The order form runs on railway.\n", proper_nouns=self.NOUNS
        )
        self.assertTrue(any("Railway" in v["detail"] for v in found))

    def test_multiword_proper_noun_is_flagged(self):
        found = lint_text(
            "I need the blue peak message format.\n", proper_nouns=self.NOUNS
        )
        self.assertTrue(any("Blue Peak" in v["detail"] for v in found))

    def test_correct_casing_is_clean(self):
        found = lint_text(
            "I need the Blue Peak message format from GroupMe.\n",
            proper_nouns=self.NOUNS,
        )
        self.assertEqual(found, [])

    def test_check_stands_down_without_a_list(self):
        """No proper-nouns.txt means the instance has not opted in."""
        found = lint_text("The order form runs on railway.\n")
        self.assertEqual(
            found, [], "an instance with no noun list must not be blocked"
        )


class DoesNotFireOnNonProse(unittest.TestCase):
    def test_code_fence_is_exempt(self):
        found = lint_text("Run it.\n\n```\nimport os\nos.getcwd()\n```\n")
        self.assertEqual(found, [])

    def test_inline_code_is_exempt(self):
        found = lint_text("The field is `account_number` on every row.\n")
        self.assertEqual(found, [])

    def test_url_start_is_exempt(self):
        found = lint_text("The dashboard is here.\n\nhttps://example.com/path\n")
        self.assertEqual(found, [])

    def test_frontmatter_is_exempt(self):
        found = lint_text("---\nname: draft\nstatus: open\n---\n\nI sent it.\n")
        self.assertEqual(found, [])

    def test_skip_marker_disables_the_rule(self):
        found = lint_text("<!-- voice-lint-skip -->\n\ni went through your list.\n")
        self.assertEqual(found, [])


class FalsePositivesFoundInTheFleetSweep(unittest.TestCase):
    """Three defects found by running the new rule over 60 real fleet files.

    Without these the rule is unusable: this repo hard-wraps markdown prose, so
    defect C alone flagged nearly every wrapped paragraph.
    """

    def test_a_terminator_inside_quotes_is_not_a_sentence_break(self):
        found = lint_text('- **Never:** Generic CTAs like "Thoughts?" or "Agree?"\n')
        self.assertEqual(found, [], "a ? inside a quoted span does not end a sentence")

    def test_b_line_numbers_are_reported_against_the_source_file(self):
        text = "```\ncode\ncode\ncode\n```\n\nThe form is live.\n\nangus set it up.\n"
        found = lint_text(text)
        self.assertEqual(len(found), 1)
        self.assertEqual(
            found[0]["line"], 9, "line number must survive code-fence stripping"
        )

    def test_c_soft_wrapped_continuation_is_not_a_sentence_start(self):
        text = (
            "Recurring weekly mechanism to advertise the AI skill set for the AI-builder\n"
            "beachhead across every channel we own.\n"
        )
        self.assertEqual(lint_text(text), [])

    def test_c_a_real_new_sentence_after_a_wrap_is_still_caught(self):
        text = (
            "Recurring weekly mechanism to advertise the AI skill set. It runs\n"
            "weekly. angus owns it.\n"
        )
        found = lint_text(text)
        self.assertTrue(any("angus" in v["detail"] for v in found))

    def test_c_paragraph_opener_after_a_blank_line_is_still_caught(self):
        text = "The form is live.\n\nangus set it up.\n"
        self.assertTrue(lint_text(text))


class RuleIsBlocking(unittest.TestCase):
    def test_capitalization_is_not_warn_class(self):
        """A rule with zero interpretation belongs in the BLOCK set."""
        self.assertNotIn("capitalization", voice_lint.WARN_RULES)


class RepairFirstFixesProseAndLeavesIdentifiersAlone(unittest.TestCase):
    """The repair-first contract (founder 2026-08-03, restated 2026-08-10:
    "the rule was that you dont reject - you fix until it can come out").

    Two defects hide under one rule and need OPPOSITE treatments. Both halves are
    asserted here, because a repairer that only does one of them is the bug: fixing
    identifiers corrupts tool names, and refusing to fix prose burns the retry
    budget until the job ships nothing.
    """

    def test_a_genuine_lowercase_english_sentence_is_REPAIRED(self):
        text = "The form is live.\n\nthanks for sending it over this morning.\n"
        repaired, fixed, left = voice_lint.repair_capitalization(text)
        self.assertIn("Thanks for sending", repaired)
        self.assertEqual(fixed, ["thanks"])
        self.assertEqual(left, [])

    def test_an_identifier_is_LEFT_ALONE_never_capitalized(self):
        """The negative half. Capitalizing a tool name corrupts it, which is a worse
        outcome than the block it was trying to avoid."""
        text = ("Today's AI news.\n\n"
                "pi-from-scratch: a working coding agent in 600 lines.\n\n"
                "phone-harness: native iPhone control for a coding agent.\n")
        repaired, fixed, left = voice_lint.repair_capitalization(text)
        self.assertIn("pi-from-scratch:", repaired)
        self.assertIn("phone-harness:", repaired)
        self.assertNotIn("Pi-from-scratch", repaired)
        self.assertNotIn("Phone-harness", repaired)
        self.assertEqual(fixed, [])
        self.assertEqual(sorted(left), ["phone-harness", "pi-from-scratch"])

    def test_BOTH_in_one_file_are_split_correctly(self):
        """The case that proves the split is real rather than a global on/off."""
        text = ("Today's AI news.\n\n"
                "pi-from-scratch: a working coding agent.\n\n"
                "thanks for reading this roundup.\n")
        repaired, fixed, left = voice_lint.repair_capitalization(text)
        self.assertIn("pi-from-scratch:", repaired)
        self.assertIn("Thanks for reading", repaired)
        self.assertEqual(fixed, ["thanks"])
        self.assertEqual(left, ["pi-from-scratch"])

    def test_repair_actually_CLEARS_the_block_it_was_repairing(self):
        """End to end: the whole point is that the gate stops holding afterwards.

        Without this the repairer could 'fix' something the checker still flags and
        the loop would keep dying with a green-looking repair step.
        """
        text = "The form is live.\n\nthanks for sending it over.\n"
        self.assertTrue(lint_text(text), "control: it must block BEFORE repair")
        repaired, _, _ = voice_lint.repair_capitalization(text)
        self.assertFalse(lint_text(repaired), "it must be clean AFTER repair")

    def test_repair_does_not_touch_a_file_it_cannot_improve(self):
        text = "The form is live.\n\npi-from-scratch: a coding agent.\n"
        repaired, fixed, _ = voice_lint.repair_capitalization(text)
        self.assertEqual(repaired, text, "an identifier-only file is returned byte-identical")
        self.assertEqual(fixed, [])


class TheFixModeExitCodeIsUsable(unittest.TestCase):
    """Scar 2026-08-10: --fix did not exist, the call hit the usage branch and
    exited 1, and make_social.py discarded the result. A repair step that never ran
    once looked exactly like one that worked, for a week."""

    def _tmp(self, text):
        import tempfile
        path = Path(tempfile.mkdtemp()) / "draft.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_fix_mode_exits_0_when_it_repairs(self):
        path = self._tmp("The form is live.\n\nthanks for sending.\n")
        self.assertEqual(voice_lint.fix_mode(str(path)), 0)
        self.assertIn("Thanks for sending", path.read_text())

    def test_fix_mode_exits_0_when_there_is_NOTHING_to_repair(self):
        """"Nothing to fix" is success. A caller treating it as failure would hold
        every clean draft, which is the opposite of repair-first."""
        path = self._tmp("The form is live.\n\nIt went out this morning.\n")
        self.assertEqual(voice_lint.fix_mode(str(path)), 0)

    def test_fix_mode_exits_1_on_a_real_fault(self):
        self.assertEqual(voice_lint.fix_mode("/nonexistent/draft.md"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
