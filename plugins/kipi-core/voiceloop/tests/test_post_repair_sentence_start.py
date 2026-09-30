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


# PR #475 review, round 1: the three tests above are all one line and never put the
# word loose inside a code span, so the line pin and the code-span mask survived
# mutation. These three are the inputs that kill those mutants.

def test_the_line_is_pinned_when_the_start_is_on_a_later_line():
    out = _repair("I saw the abuse side.\nthe rest is fine.")
    assert out == "I saw the abuse side.\nThe rest is fine.", out


def test_a_loose_word_inside_a_code_span_is_not_rewritten():
    out = _repair("Run `use the thing` first. the output is clean.")
    assert out == "Run `use the thing` first. The output is clean.", out


def test_a_start_behind_underscore_italics_is_fixed_and_later_starts_still_are():
    out = _repair("_the rest of it._\nthe rest is fine.\nof course it breaks.")
    assert out == "_The rest of it._\nThe rest is fine.\nOf course it breaks.", out


# The copy that WRITES FILES (`voice-lint.py --fix` -> fix_file) had the same defect:
# it capitalized the first match on the line. It must pin the start the same way.

def test_voice_lint_repair_capitalization_pins_the_start_not_the_first_match():
    out, fixed, _left = LINTER.repair_capitalization(
        "I read it from the abuse side and it held. the rest of your list is fine.")
    assert "from the abuse side" in out, out
    assert "The rest of your list" in out, out
    assert LINTER.check_capitalization(out) == [], LINTER.check_capitalization(out)
    assert fixed == ["the"], fixed


# PR #475 review round 2.

def test_voice_lint_two_same_word_starts_on_one_line_each_get_their_own():
    out, fixed, _left = LINTER.repair_capitalization(
        "I saw the team. the rest is fine. the end came fast.")
    assert out == "I saw the team. The rest is fine. The end came fast.", out
    assert LINTER.check_capitalization(out) == [], LINTER.check_capitalization(out)


def test_voice_lint_never_rewrites_a_loose_word_inside_a_code_span():
    out, _fixed, _left = LINTER.repair_capitalization(
        "Run `use the thing` first. the output is clean.")
    assert out == "Run `use the thing` first. The output is clean.", out


def test_the_command_line_entry_point_runs_instead_of_raising(tmp_path):
    import subprocess
    draft = tmp_path / "draft.md"
    draft.write_text("I read it from the abuse side. the rest is fine.\n", encoding="utf-8")
    run = subprocess.run([sys.executable, os.path.join(PKG, "post_repair.py"),
                          str(draft), LINTER_PATH], capture_output=True, text=True)
    assert "Traceback" not in run.stderr, run.stderr
    assert run.returncode in (0, 1), (run.returncode, run.stderr)
    assert "capitalized sentence start 'the'" in run.stdout, run.stdout
    assert "no verbatim-lowercase allowlist" in run.stderr, run.stderr


# PR #475 review round 3.

def test_voice_lint_a_code_start_is_not_counted_against_the_code_sentinel():
    out, _fixed, _left = LINTER.repair_capitalization(
        "Run `x` first. code review is next. code comes after.")
    assert out == "Run `x` first. Code review is next. Code comes after.", out
    assert LINTER.check_capitalization(out) == [], LINTER.check_capitalization(out)


def test_the_command_line_honors_the_verbatim_allowlist(tmp_path):
    import subprocess
    draft = tmp_path / "draft.md"
    draft.write_text("I ran it once. ratchet is the tool.\n", encoding="utf-8")
    allow = tmp_path / "verbatim-lowercase.txt"
    allow.write_text("ratchet\n", encoding="utf-8")
    run = subprocess.run([sys.executable, os.path.join(PKG, "post_repair.py"),
                          str(draft), LINTER_PATH, str(allow)], capture_output=True, text=True)
    assert "Traceback" not in run.stderr, run.stderr
    assert "protected verbatim token 'ratchet'" in run.stdout, run.stdout
    assert "no verbatim-lowercase allowlist" not in run.stderr, run.stderr
