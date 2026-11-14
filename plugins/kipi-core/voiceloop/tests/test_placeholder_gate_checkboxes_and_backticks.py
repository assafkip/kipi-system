#!/usr/bin/env python3
"""Task checkboxes are not blanks, and a stray backtick does not exempt a real one.

why this file exists.

ASK-4945 (2026-11-14). A written plan full of task lists (`- [ ] the client runs the
morning routine 4x a week`) refused on `unfilled-placeholder` with one token, `[ ]`. A
markdown task box is a checklist mark, not a template slot.

ASK-4922 (2026-11-14, leftover from PR 810 review). A stray backtick paired with the opener
of the NEXT inline-code span and exempted the prose between, a real `[CLIENT NAME]`
included, across table rows too. Two bounds also had no control: deleting the straight
quote closer lookahead, or searching inline code before fences are blanked, changed real
verdicts and left the code-and-quotes suite green. The last two cases below are those
controls; each was run against the mutated module and failed it.
All text here is synthetic; this repo is public.
"""
import os
import sys

import pytest

PKG_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

from voiceloop import placeholder_gate  # noqa: E402

FENCE = "`" * 3

NOT_BLANKS = [
    ("open task box", "Plan:\n\n- [ ] The client runs the morning routine 4x a week\n"),
    ("done task box", "- [x] Intake list loaded\n- [X] Owner named\n"),
    ("star and plus bullets", "* [ ] first\n+ [x] second\n"),
    ("numbered task boxes", "1. [ ] first\n2) [x] second\n"),
    ("indented task box", "- parent\n  - [ ] child step\n\t- [x] tab child\n"),
    ("task box at end of a line", "- [ ]\n"),
    ("CRLF task list", "- [ ] one\r\n- [x] two\r\n"),
]


@pytest.mark.parametrize("label,text", NOT_BLANKS, ids=[c[0] for c in NOT_BLANKS])
def test_a_task_box_is_not_a_blank(label, text):
    assert placeholder_gate.tokens(text) == [], label
    assert placeholder_gate.check(text) == [], label


STILL_BLANKS = [
    # ASK-4945 controls: only the box at the start of a list item is exempt.
    ("template token as a list item", "- [paste the intake list here]\n",
     "[paste the intake list here]"),
    ("token after a task box", "- [ ] Call [CLIENT NAME] on Monday\n", "[CLIENT NAME]"),
    ("a box in prose is still a blank", "Tick [ ] when the call is done.", "[ ]"),
    ("a box with no space after the bullet", "-[ ] step one\n", "[ ]"),
    ("a box glued to the text after it", "- [ ]step one\n", "[ ]"),
    ("a box after the list text", "- step one [ ]\n", "[ ]"),
    ("a curly token in a task item", "- [ ] Hi {{FIRST_NAME}}\n", "{{FIRST_NAME}}"),
    # ASK-4922: a stray backtick before a later inline-code span.
    ("stray backtick then code on the same line",
     "The `flag for [CLIENT NAME] stays. Run `make` now.", "[CLIENT NAME]"),
    ("stray backtick then code on the next line",
     "The `flag for [CLIENT NAME] stays.\nRun `make` now.", "[CLIENT NAME]"),
    ("stray backtick then code in parentheses",
     "The `flag for [CLIENT NAME] stays (`make` it).", "[CLIENT NAME]"),
    ("stray backtick in a table row, code in the next row",
     "| a | `x | [CLIENT NAME] |\n| b | c | `code` |\n", "[CLIENT NAME]"),
    ("stray backtick in a table row, code after punctuation in the next row",
     "| a | `x | [CLIENT NAME] |\n| b | c:`code` |\n", "[CLIENT NAME]"),
    ("stray backtick in a table row, code glued to the next cell",
     "| a | `x | [CLIENT NAME] |\n|`code`| c |\n", "[CLIENT NAME]"),
    ("stray backtick and a glued code cell in one row",
     "| `x | [CLIENT NAME] |`code`|\n", "[CLIENT NAME]"),
    # PR 818 review round 1: a stray backtick glued to the word BEFORE it, or standing alone,
    # used to slip through a "padded" shortcut that skipped the closer check.
    ("stray backtick glued to the word before it",
     "Set the flag` and tell [CLIENT NAME] to run `make` now.", "[CLIENT NAME]"),
    ("stray backtick as its own word",
     "Quote it with ` and then email [CLIENT NAME]. Run `make`.", "[CLIENT NAME]"),
    ("stray backtick at a line end",
     "Left a backtick here `\nso [CLIENT NAME] must be filled, run `make`.", "[CLIENT NAME]"),
    ("stray backtick alone in a table cell",
     "| a | x ` | [CLIENT NAME] | `code` |\n", "[CLIENT NAME]"),
    # Round 1 too: a code span whose content ends in `(` or `|` was refused as a closer, then
    # promoted to an opener, and blanked prose up to the next code span.
    ("code span ending in a pipe, then prose, then code",
     "Every table row starts with `|` and [CLIENT NAME] is still a blank. Run `make`.",
     "[CLIENT NAME]"),
    ("code span ending in a paren, then prose, then code",
     "Type `(` to start, then ask [CLIENT NAME] about it, then `go`.", "[CLIENT NAME]"),
    ("code span ending in a space, then prose, then code",
     "Run `make ` then call [CLIENT NAME] and run `go` next.", "[CLIENT NAME]"),
    # ASK-4922 controls for two bounds that had none.
    # Deleting the straight-quote closer lookahead lets `vendor"s` close the open quote.
    ("a quote mark glued to the next word does not close a quote",
     'He said "we serve [CLIENT NAME] well, and the vendor"s rep agreed.', "[CLIENT NAME]"),
    # Searching inline code before fences are blanked pairs the backtick inside the fence
    # with the one after the token.
    ("a backtick inside a fence does not pair with one outside it",
     "~~~\nuse ` here\n~~~\n[CLIENT NAME] said.`x` is the flag.", "[CLIENT NAME]"),
]


@pytest.mark.parametrize("label,text,token", STILL_BLANKS, ids=[c[0] for c in STILL_BLANKS])
def test_control_a_real_token_still_blocks(label, text, token):
    assert token in placeholder_gate.tokens(text), label
    rows = placeholder_gate.check(text)
    assert rows and rows[0]["rule"] == "unfilled-placeholder", label
    assert "warn_only" not in rows[0], label


CODE_STILL_EXEMPT = [
    ("real code after a stray backtick is still code",
     "The `flag stays. Run `make [target]` now.", []),
    ("padded inline code", "Type `` [draft] `` in the field.", []),
    ("code in a table cell", "| a | `tags: [draft]` |\n| b | `[x]` |\n", []),
    ("code cell padded at the end", "| step | `tags: [draft] ` |\n", []),
    ("code span ending in a pipe", "Run `grep [x] |` then stop.", []),
    ("code with a letter glued after its closer", "Count the `[draft]`s in the export.", []),
]


@pytest.mark.parametrize("label,text,expected", CODE_STILL_EXEMPT,
                         ids=[c[0] for c in CODE_STILL_EXEMPT])
def test_real_inline_code_is_still_exempt(label, text, expected):
    assert placeholder_gate.tokens(text) == expected, label
