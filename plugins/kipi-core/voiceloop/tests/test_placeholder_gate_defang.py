#!/usr/bin/env python3
"""An IOC defang is text, an empty template token is a blank.

why this file exists (ASK-4651, 2026-11-12). Pointing the voice gate at intel reports
(RULE-2026-11-12-A) ran the hard rows on his own long-form writing for the first time.
`unfilled-placeholder` refused one of his published articles on `[.]`, the standard
threat-intel defang (`example[.]com`). That row blocks in every gate that imports this
module, so every report that defangs a domain or an IP would have been refused.

The table below crosses the defang forms (dot, colon, at, scheme separator, the word
forms) with the places an indicator sits (domain, IP, URL, email). The controls prove
the gate still fires on a real blank, including a defang-shaped word that is NOT inside
an indicator, so the "inside an indicator" condition is load-bearing and not decoration.
"""
import os
import sys

import pytest

PKG_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

from voiceloop import placeholder_gate  # noqa: E402

DEFANGED = [
    ("domain, [.]", "The kit called home to example[.]com every hour."),
    ("ip, last octet", "Traffic went to 192.0.2[.]4 on port 443."),
    ("ip, every octet", "The second server was 198[.]51[.]100[.]7."),
    ("url, hxxp and [.]", "The lure linked hxxp://login.example[.]com/reset."),
    ("url, [:]", "The panel sat at hxxps[:]//panel.example[.]net/admin."),
    ("url, [://]", "Same panel, written hxxps[://]panel.example[.]net."),
    ("email, [@]", "Replies went to ops[@]example[.]org for a week."),
    ("word form, [dot]", "Their notes wrote it as example[dot]com."),
    ("word form, [at]", "And the mailbox as ops[at]example[dot]org."),
    ("upper case word form", "One analyst typed EXAMPLE[DOT]COM in caps."),
]


@pytest.mark.parametrize("label,text", DEFANGED, ids=[d[0] for d in DEFANGED])
def test_a_defanged_indicator_is_not_a_template_token(label, text):
    assert placeholder_gate.tokens(text) == [], label
    assert placeholder_gate.check(text) == [], label


def test_hxxp_alone_was_never_a_token():
    # Control: no bracket, so the gate never read it. Pinned so a later widening of the
    # pattern to other shapes cannot start refusing the scheme defang.
    assert placeholder_gate.check("Seen first at hxxp://example.com/a.") == []


BLANKS = [
    ("client name", "[CLIENT NAME] asked for the findings by Friday.", ["[CLIENT NAME]"]),
    ("date", "Ship it by [DATE] once the review clears.", ["[DATE]"]),
    ("tbd", "The root cause is [TBD].", ["[TBD]"]),
    ("curly", "Thanks {{X}}, the report is attached.", ["{{X}}"]),
    ("the 2026-08-11 defect", "I have ADHD and I built [specific thing] beats any pitch.",
     ["[specific thing]"]),
    # A defang-shaped word with whitespace on a side is not inside an indicator.
    ("free-standing [at]", "Meet the client [at] the venue.", ["[at]"]),
    ("free-standing [dot]", "Then write [dot] between the labels.", ["[dot]"]),
]


@pytest.mark.parametrize("label,text,expected", BLANKS, ids=[b[0] for b in BLANKS])
def test_a_real_blank_still_fires(label, text, expected):
    assert placeholder_gate.tokens(text) == expected, label
    rows = placeholder_gate.check(text)
    assert [r["rule"] for r in rows] == ["unfilled-placeholder"], label


def test_a_blank_next_to_a_defang_is_still_caught_alone():
    text = "The kit called example[.]com for [CLIENT NAME] twice."
    assert placeholder_gate.tokens(text) == ["[CLIENT NAME]"]
    detail = placeholder_gate.check(text)[0]["detail"]
    assert "[CLIENT NAME]" in detail
    assert "[.]" not in detail
