#!/usr/bin/env python3
"""Code and quoted examples are not blanks. A bare template token still is.

why this file exists (ASK-4900, 2026-11-14). Run on written reports, `unfilled-placeholder`
refused three things that were never template slots:

  * a JSON array inside a fenced code block (`["-y", "@scope/some-server"]`, an MCP config);
  * a bracket inside a quoted scam message (`"Congrats [player], ..."`), quoted as evidence;
  * a bracket inside a quoted seller listing, held by a sweep row check.

The 81-text control in the gate's docstring was all social posts, which carry no code and
rarely quote anyone, so it could not see these. That row blocks in every gate that imports
the module, so each one stopped a finished report.

The controls below prove the exemption is bounded: a quote has to close, it cannot run past
a blank line, an inch mark is not a quote, and an unclosed fence exempts nothing. Without
those, one stray quote mark would switch the gate off for the rest of a paragraph.
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
    ("json array in a fenced block",
     "Add the server to the config:\n\n" + FENCE + "json\n"
     '{"command": "npx", "args": ["-y", "@scope/some-server"]}\n' + FENCE + "\n\nThen restart."),
    ("json array in a tilde fence",
     "The config:\n~~~\n\"args\": [\"-y\", \"@scope/some-server\"]\n~~~\n"),
    ("bracket in a quoted scam example",
     'The message read "Congrats [player], your prize is waiting. Reply to claim." '
     "Nobody had entered anything."),
    ("bracket in a curly-quoted scam example",
     "The message read \u201cCongrats [player], your prize is waiting.\u201d Then a link."),
    ("bracketed seller quote inside quotes",
     'One listing said "fresh [verified] accounts, bulk price, DM me" and stayed up a week.'),
    ("quote that wraps a line inside one paragraph",
     'The seller wrote "selling [aged] accounts,\nbulk only" in every post.'),
    ("inline code",
     "Pass `ARGS=[\"-y\"]` on the command line and it starts."),
    ("double-backtick inline code",
     "The field reads ``tags: [draft]`` in the export."),
    ("curly token in a fenced template example",
     "The mail merge used:\n" + FENCE + "\nHi {{first_name}},\n" + FENCE + "\n"),
    # The fence closes only on the same mark, at least as long, with nothing after it. Each
    # case below would leave the token OUTSIDE the fence if that rule were dropped.
    ("a tilde line does not close a backtick fence",
     "Config:\n" + FENCE + "\n~~~\nslot [region]\n" + FENCE + "\nDone."),
    ("a shorter fence does not close a longer one",
     "Config:\n````\n" + FENCE + "\nslot [region]\n````\nDone."),
    ("a fence line with text after it does not close",
     "Config:\n" + FENCE + "\n" + FENCE + "python\nslot [region]\n" + FENCE + "\nDone."),
]


@pytest.mark.parametrize("label,text", NOT_BLANKS, ids=[c[0] for c in NOT_BLANKS])
def test_code_or_a_quoted_example_is_not_a_blank(label, text):
    assert placeholder_gate.tokens(text) == [], label
    assert placeholder_gate.check(text) == [], label


STILL_BLANKS = [
    ("bare curly token", "Hi {{FIRST_NAME}}, thanks for the call.", "{{FIRST_NAME}}"),
    ("bare square token", "We built this for [CLIENT NAME] last month.", "[CLIENT NAME]"),
    ("token after a closed quote",
     'He said "hello" and then thanked [CLIENT NAME].', "[CLIENT NAME]"),
    ("token after closed inline code",
     "Run `make` once for [CLIENT NAME].", "[CLIENT NAME]"),
    ("token after a closed fence",
     FENCE + "\nrun\n" + FENCE + "\nThanks, [CLIENT NAME].", "[CLIENT NAME]"),
    ("unclosed quote", 'He said "we serve [CLIENT NAME] well.', "[CLIENT NAME]"),
    ("quote cannot cross a blank line",
     'He said "start\n\n[CLIENT NAME] is next" today.', "[CLIENT NAME]"),
    ("an inch mark is not a quote",
     'Two 5"wide panels for [CLIENT NAME], each 6" tall.', "[CLIENT NAME]"),
    # Review round 1 on PR 810: an inch mark could not OPEN a quote but could CLOSE one, so one
    # stray opening quote blanked the paragraph up to the next size in inches.
    ("an inch mark does not close a quote",
     'The listing said "fresh accounts, bulk only.\nOur draft still says [CLIENT NAME] '
     'next to a 55" set.', "[CLIENT NAME]"),
    ("quote cannot cross a CRLF blank line",
     'He said "start\r\n\r\n[CLIENT NAME] is next" today.', "[CLIENT NAME]"),
    # Round 2: the curly path had no open or close rule; autocorrect writes `55"` as a curly close.
    ("an inch mark does not close a curly quote",
     "The listing said \u201cfresh accounts, bulk only.\nOur draft still says [CLIENT NAME] "
     "next to a 55\u201d set.", "[CLIENT NAME]"),
    ("a quote glued to a word does not open one",
     'The vendor"s rep for [CLIENT NAME] signed off."', "[CLIENT NAME]"),
    ("unclosed fence after prose exempts nothing",
     "Notes below.\n\n" + FENCE + "\nWe built this for [CLIENT NAME].\n", "[CLIENT NAME]"),
    ("a token that only ENDS inside a quote is outside it",
     'Thanks, [CLIENT "NAME]" for the call.', '[CLIENT "NAME]'),
    ("unclosed fence exempts nothing",
     FENCE + "\nWe built this for [CLIENT NAME].\n", "[CLIENT NAME]"),
    ("unclosed backtick exempts nothing",
     "The `flag for [CLIENT NAME] stays.", "[CLIENT NAME]"),
    ("bare json array outside code", 'Use ["-y", "x"] as the args.', '["-y", "x"]'),
]


@pytest.mark.parametrize("label,text,token", STILL_BLANKS, ids=[c[0] for c in STILL_BLANKS])
def test_control_a_bare_token_still_blocks(label, text, token):
    assert token in placeholder_gate.tokens(text), label
    rows = placeholder_gate.check(text)
    assert rows and rows[0]["rule"] == "unfilled-placeholder", label
    assert "warn_only" not in rows[0], label
