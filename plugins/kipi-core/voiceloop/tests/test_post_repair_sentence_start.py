"""The sentence-start repair capitalizes the word that STARTS the sentence, not the first
place that word appears in the draft.

Reported 2026-09-29 from live Reddit drafts: "from The abuse side", "the rest Of your list",
"It's almost never" mid-sentence. `repair` found a lowercase sentence start, then ran
`pattern.subn(..., count=1)` over the whole raw text, which rewrites the word's FIRST
occurrence anywhere. With up to 10 passes, common words ("the", "of", "it") got capitalized
in the middle of earlier sentences while the real sentence start stayed lowercase.
"""
import os
import sys

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PKG))

from voiceloop import post_repair  # noqa: E402

LINTER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(PKG))),
                           "q-system", ".q-system", "scripts", "voice-lint.py")
LINTER = post_repair._load_linter(LINTER_PATH)


def _repair(text):
    repaired, _changes = post_repair.repair(text, set(), LINTER, {})
    return repaired


def test_the_sentence_start_is_capitalized_not_an_earlier_occurrence():
    out = _repair("I work with the abuse team. the rest of the list is noise.")
    assert "with the abuse team" in out, out
    assert "The rest of the list" in out, out


def test_no_word_is_capitalized_mid_sentence_across_many_starts():
    text = ("I read it from the abuse side and it held. "
            "the rest of your list is fine. "
            "of course it breaks. "
            "it's almost never the model.")
    out = _repair(text)
    assert "from the abuse side and it held." in out, out
    assert "The rest of your list" in out, out
    assert "Of course it breaks." in out, out
    assert "It's almost never the model." in out, out
    for wrong in (" The abuse", " Of your", " It held"):
        assert wrong not in out, (wrong, out)


def test_a_word_inside_inline_code_is_never_the_one_rewritten():
    out = _repair("Run `the tool` first. the output is clean.")
    assert "`the tool`" in out, out
    assert "The output is clean." in out, out
