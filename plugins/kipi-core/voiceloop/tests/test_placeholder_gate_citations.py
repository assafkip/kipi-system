#!/usr/bin/env python3
"""A report's citation forms are text, an empty template token is a blank.

why this file exists (ASK-4658, found by the review of ASK-4651's PR, PR #763). That PR
exempted the IOC defang only. The other bracket conventions of a written report still hit
the hard row `unfilled-placeholder`, so reports sent through the press-doc door would have
been refused for a numbered footnote, a reference-link definition, `[sic]` inside a quote,
or `[REDACTED]`. Reviewer repro on `placeholder_gate.tokens`: all four blocked.

The sort, recorded on ASK-4658 (genre convention = exempt, real blank = keep):
  `[1]`, `[1, 2]`, `[3-5]` : exempt. A number is never a template slot.
  `[1]: https://...`, `[kroll]: https://...` at a line start : exempt, a link definition.
  `[label][1]` : exempt only when `[1]: https://...` is defined in the same text.
  `[sic]`, `[REDACTED]` : exempt, a fixed editorial word, exact match only.
  `[CLIENT NAME]`, `[TBD]`, `[paste the intake list here]`, `{{X}}` : keep, they block.

The controls matter more than the exempt table: each exemption is narrow (digits only,
exact words, a URL after the colon), and a near-miss of each still blocks.
"""
import os
import sys

import pytest

PKG_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

from voiceloop import placeholder_gate  # noqa: E402

EXEMPT = [
    ("numbered footnote", "The kit beaconed hourly [1] and rotated keys weekly."),
    ("footnote list", "Two vendors reported it [1, 2] before the takedown."),
    ("footnote range", "The campaign is documented elsewhere [3-5]."),
    ("reference link definition", "Sources\n\n[1]: https://example.com/report\n"),
    ("named reference definition", "[kroll]: https://example.com/kroll-2023\n"),
    ("reference link use", "See the [vendor writeup][1] for the full timeline.\n\n[1]: https://example.com/w\n"),
    ("link definition with a prose label", "[vendor writeup]: https://example.com/w\n"),
    ("sic in a quote", 'He wrote "we recieved [sic] the files" in the ticket.'),
    ("sic upper", 'The note said "teh [SIC] logs".'),
    ("redacted", "The account belonged to [REDACTED], a reseller in the region."),
    ("redacted lower", "Paid to [redacted] on the second day."),
]

BLOCKS = [
    ("client name", "Prepared for [CLIENT NAME] on request."),
    ("tbd", "The total is [TBD] pending the audit."),
    ("paste instruction", "[paste the intake list here]"),
    ("curly", "Dear {{X}}, here is the report."),
    ("word digit mix", "The count is [N] across the sample."),
    ("redacted with extra words", "Paid to [REDACTED name here] on day two."),
    ("sic with extra words", "teh [sic please fix] logs"),
    ("definition without a url", "[source]: fill this in later\n"),
    ("label alone", "Contact [name] for the keys."),
    # Review round 1 repros: a slot before an exempt-looking bracket, no definition behind it.
    ("slot + footnote", "The loss totalled [TBD][3] by the end of the quarter."),
    ("slot + redacted", "Sent to [CLIENT NAME][REDACTED] on day two."),
    ("slot + footnote range", "Prepared for [CLIENT NAME][1-2]."),
    ("paste instruction + footnote", "[paste the intake list here][1]"),
    ("reference link use with no definition", "See the [vendor writeup][1] for the full timeline."),
    ("slot + ref defined elsewhere under another name", "Total [TBD][9].\n\n[1]: https://example.com/w\n"),
    ("link definition label is a slot", "Sources\n\n[SOURCE 1]: https://example.com/a\n"),
    # Round 1 on the fix PR: a defined NAMED ref used to exempt both brackets.
    ("slot + defined named ref", "Prepared for [CLIENT NAME][kroll].\n\n[kroll]: https://example.com/k\n"),
    ("named reference use", "See [the report][kroll].\n\n[kroll]: https://example.com/k\n"),
    ("slot-shaped label before a defined number", "Total [TBD][3].\n\n[3]: https://example.com/w\n"),
    ("all-caps link definition label", "[SOURCE]: https://example.com/a\n"),
    ("slot inside a link definition url", "[1]: https://example.com/a[CLIENT]\n"),
]


@pytest.mark.parametrize("label,text", EXEMPT, ids=[e[0] for e in EXEMPT])
def test_a_report_citation_convention_is_not_a_blank(label, text):
    assert placeholder_gate.tokens(text) == [], (label, placeholder_gate.tokens(text))
    assert placeholder_gate.check(text) == []


@pytest.mark.parametrize("label,text", BLOCKS, ids=[b[0] for b in BLOCKS])
def test_control_a_real_blank_still_blocks(label, text):
    assert placeholder_gate.tokens(text), (label, "should have blocked")
    assert placeholder_gate.check(text)[0]["rule"] == "unfilled-placeholder"
