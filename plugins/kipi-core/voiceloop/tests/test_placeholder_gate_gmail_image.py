#!/usr/bin/env python3
"""Gmail's inline-image marker is not a blank (ASK-5198).

why this file exists. Measured 2026-11-15: on the thread-cache sent-mail source the
gate_draft census reads, this gate refused 24 of 59 of his real sent emails. Every image
refusal was Gmail's plain-text stand-in for an inline image, `[image: <name>]`: a pasted
screenshot's file name, or a signature icon's alt text (`[image: linkedin]`). He did not
write those brackets; Gmail did. The rows below are shaped from those real markers, with
no name from the mail itself, because this repo is public.
"""
import os
import sys

import pytest

PKG_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

from voiceloop import placeholder_gate  # noqa: E402

SENT_ROW = ("Here is where the step drops the request.\n\n"
            "[image: Screen Shot 2026-07-24 at 1.53.58 PM.png]\n\n"
            "Talk soon,\nA\n\n[image: linkedin]  [image: mobilePhone]\n"
            "> On Tue, someone wrote:\n> [image: Header profile photo]\n")

NOT_BLANKS = [
    ("pasted screenshot, signature icons and a quoted reply", SENT_ROW),
    ("a URL as the alt text", "See the site.\n[image: https://example.com]\n"),
    ("a capitalised alt text", "[image: Google]\n"),
]


@pytest.mark.parametrize("label,text", NOT_BLANKS, ids=[c[0] for c in NOT_BLANKS])
def test_a_gmail_image_marker_is_not_a_blank(label, text):
    assert placeholder_gate.tokens(text) == [], label


STILL_BLANKS = [
    ("a real blank in the same email", SENT_ROW + "\nHi [CLIENT NAME],\n", "[CLIENT NAME]"),
    ("a curly blank in the same email", SENT_ROW + "\nHi {{FIRST_NAME}}\n", "{{FIRST_NAME}}"),
    # A slot-shaped alt text is a template asking for an image, not one Gmail placed.
    ("a slot-shaped image label", "Logo here: [image: CLIENT LOGO]\n", "[image: CLIENT LOGO]"),
    ("image with no space after the colon is not Gmail's shape", "[image:logo]\n", "[image:logo]"),
    ("an empty image label", "[image: ]\n", "[image: ]"),
]


@pytest.mark.parametrize("label,text,token", STILL_BLANKS, ids=[c[0] for c in STILL_BLANKS])
def test_a_real_blank_still_blocks(label, text, token):
    assert token in placeholder_gate.tokens(text), label
