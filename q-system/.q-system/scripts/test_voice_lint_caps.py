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



class LegitimatelyLowercase(unittest.TestCase):
    """Tokens that are CORRECTLY lowercase must not be flagged (2026-08-03).

    Every case here is real. The daily social drafts failed this gate three times
    and shipped nothing, on 'reverse-skill', 'claude-video' and 'https'. The Stop
    hook then blocked an assistant message opening with an email address. A gate
    that fires on correct content gets bypassed or ignored.
    """

    def _caps(self, text):
        return [v for v in voice_lint.check_capitalization(text)
                if "starts lowercase" in v["detail"]]

    def test_tool_name_slug_is_not_a_sentence(self):
        self.assertEqual(self._caps("reverse-skill turns a repo into a skill."), [])

    def test_second_tool_name(self):
        self.assertEqual(self._caps("claude-video renders a clip."), [])

    def test_url(self):
        self.assertEqual(self._caps("https://example.com/x is the link."), [])

    def test_email(self):
        self.assertEqual(self._caps("assafkip@gmail.com received it."), [])

    def test_filename(self):
        self.assertEqual(self._caps("run_daily.sh builds the episode."), [])

    def test_a_real_lowercase_sentence_is_STILL_caught(self):
        # The exemptions must not blunt the rule they are narrowing.
        self.assertEqual(len(self._caps("this is a real sentence.")), 1)


class AutoFix(unittest.TestCase):
    """Casing is the one voice rule with a single right answer, so it is repaired
    rather than reported. Blocking on it is what burned the retry budget."""

    def test_fixes_a_real_lowercase_start(self):
        out, n = voice_lint.fix_capitalization("this needs a capital.")
        self.assertEqual(out, "This needs a capital.")
        self.assertEqual(n, 1)

    def test_fixes_bare_i(self):
        out, n = voice_lint.fix_capitalization("I know. i wrote it.")
        self.assertIn("I wrote it.", out)

    def test_leaves_exempt_tokens_untouched(self):
        text = "reverse-skill ships. https://x.com/y links. a@b.com wrote."
        out, n = voice_lint.fix_capitalization(text)
        self.assertEqual(out, text)
        self.assertEqual(n, 0)

    def test_is_idempotent(self):
        once, _ = voice_lint.fix_capitalization("this needs a capital.")
        twice, n = voice_lint.fix_capitalization(once)
        self.assertEqual(once, twice)
        self.assertEqual(n, 0)

if __name__ == "__main__":
    unittest.main(verbosity=2)
