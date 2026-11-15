#!/usr/bin/env python3
"""Inline code pairs by parity, a blockquoted task box is a task box (ASK-4984, ASK-4995).

why this file exists.

PR 818 decided whether a backtick closes a span from one character on each side of it
(`reads_as_opener`). Three review rounds retuned that window and each round left a new
residual on both sides of it:
- ASK-4995: a stray backtick still paired with the next span's opener when that opener
  starts with punctuation (`--fast`, `.env`), so a real `[CLIENT NAME]` between them passed.
- ASK-4984 box 1: real code whose content ends in a space or one of `([|=:` with a letter
  glued after the closer (`grep [x] |`s) stopped being code and refused.
- ASK-4984 box 3: a fence marker the fence parser refused still paired as inline code.
The fix counts instead of guessing: inside one paragraph or table row, an odd number of
backtick runs of one width means one of them is stray, nothing says which, so none of
that width pairs and every token there stays visible.
ASK-4984 box 2: a task box in a blockquoted list (`> - [ ] step`) refused.
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

STILL_BLANKS = [
    # ASK-4995: the reviewer's two live reproducers, plus the ticket's general shape.
    ("stray tick, later code starting with dashes",
     "The `flag for [CLIENT NAME] stays. Run `--fast` now.", "[CLIENT NAME]"),
    ("stray tick, later code starting with a dot",
     "The `flag for [CLIENT NAME] stays. Edit `.env` now.", "[CLIENT NAME]"),
    ("stray tick, later code after a period",
     "The `flag for [CLIENT NAME] stays. See.`x` here.", "[CLIENT NAME]"),
    ("stray tick, later code after a dash",
     "The `flag for [CLIENT NAME] stays. Then -`x` here.", "[CLIENT NAME]"),
    # ASK-4984 box 3, shape 1: a fence the fence parser refused is not inline code either.
    ("refused fence marker does not pair as inline code",
     FENCE + "\n[CLIENT NAME] needs filling\n" + FENCE + ".\n", "[CLIENT NAME]"),
    ("unclosed fence then a later fence-width run",
     FENCE + "\n[CLIENT NAME] here\nand " + FENCE + " there\n", "[CLIENT NAME]"),
    # ASK-4984 box 2 controls: only a list item's box is exempt, quoted or not.
    ("blockquoted box in prose still blocks", "> [ ] tick when done\n", "[ ]"),
    ("blockquoted box after item text still blocks", "> - step one [ ]\n", "[ ]"),
    ("blockquoted token after a task box still blocks",
     "> - [ ] Call [CLIENT NAME] on Monday\n", "[CLIENT NAME]"),
    # Parity is per width: a single-tick inside a double-tick span is not counted, so it
    # cannot pair with a stray outside it.
    ("tick nested in a double span, then a stray",
     "Use ``a`b`` then tell [CLIENT NAME] the ` mark.", "[CLIENT NAME]"),
]


@pytest.mark.parametrize("label,text,token", STILL_BLANKS, ids=[c[0] for c in STILL_BLANKS])
def test_a_real_token_still_blocks(label, text, token):
    assert token in placeholder_gate.tokens(text), label


NOT_BLANKS = [
    # ASK-4984 box 1: exempt again, as on main before PR 818.
    ("code ending in a pipe, letter glued after", "Use `grep [x] |`s in the export.", []),
    ("code ending in a space, letter glued after", "Run `tags: [draft] `s next.", []),
    ("code ending in a paren, letter glued after", "Count `f([x] (`s here.", []),
    ("code ending in =, letter glued after", "Set `[k]=`x and go.", []),
    # ASK-4984 box 2.
    ("blockquoted task box", "> - [ ] The client runs the morning routine\n", []),
    ("nested blockquoted task boxes", ">> - [x] done\n> > 1. [ ] next\n", []),
    # Two spans of different widths in one paragraph each pair on their own.
    ("tick span and double span together", "Run `[a]` then ``[b]`` now.", []),
    ("tick nested in a double span", "Use ``a`[b]`` here.", []),
]


@pytest.mark.parametrize("label,text,expected", NOT_BLANKS, ids=[c[0] for c in NOT_BLANKS])
def test_not_a_blank(label, text, expected):
    assert placeholder_gate.tokens(text) == expected, label


def test_task_box_pattern_has_no_inert_anchor():
    # ASK-4995 nit: `^` in _TASK_BOX was inert (match() already starts at the line start),
    # so a mutant dropping it survived. The anchor is gone; this pins that it stays gone.
    assert not placeholder_gate._TASK_BOX.pattern.startswith("^")
