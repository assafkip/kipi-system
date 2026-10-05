#!/usr/bin/env python3
"""One lane may lift the closing-question rule; every other caller keeps it.

why (2026-10-05). A founder lifted "never end on a question" for one scheduled
lane after a controlled study measured an open question at +53% replies. The rule
lives in two places: `ending_gate` (the gate) and an active correction rendered by
`assemble.voice_section` (the prose). Lifting one and not the other is the defect
that kept the lane at 0% questions for three rounds, so both halves are tested
here, and each default is pinned so no other caller changes.
"""
import os
import sys

PKG_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

from voiceloop import assemble, ending_gate, validate  # noqa: E402

QUESTION = "The tool said every number matched.\n\nWould you trust that report?"
SURVEY = "Half the stack guesses.\n\nWhich of your tools is the worst at saying it doesn't know?"
CTA = "The tool said every number matched.\n\nComment AUDIT and I'll send you the checklist."


def test_default_still_refuses_a_closing_question():
    assert ending_gate.check(QUESTION)


def test_the_lane_switch_allows_a_closing_question():
    assert ending_gate.check(QUESTION, allow_reader_question=True) == []


def test_the_lane_switch_allows_a_reader_survey_question():
    assert ending_gate.check(SURVEY)
    assert ending_gate.check(SURVEY, allow_reader_question=True) == []


CTAS = (
    CTA,
    "The tool said every number matched.\n\nComment AUDIT to get the doc.",
    "The tool said every number matched.\n\nFollow me for more of these.",
    "The tool said every number matched.\n\nDM me and I'll send the checklist.",
    "The tool said every number matched.\n\nSubscribe for the full teardown.",
)


def test_a_cta_is_refused_with_or_without_the_switch():
    for cta in CTAS:
        assert ending_gate.check(cta), cta
        assert ending_gate.check(cta, allow_reader_question=True), cta


def test_prose_that_mentions_a_comment_is_not_a_cta():
    for last in ("The comment thread and the PR both said nothing.",
                 "Reply rate and open rate measure different things.",
                 "Type checking and the lint both pass now.",
                 "Comment thread and PR description disagreed."):
        text = "Nobody read the review.\n\n" + last
        assert ending_gate.check(text, allow_reader_question=True) == [], last


class _Voice:
    identity = pov = ""
    lexicon = {}
    skipped_rows = []

    def __init__(self, rows):
        self.rows = rows

    def active_exemplars(self):
        return []

    def active_corrections(self):
        return self.rows


ROW = {"id": "no-q", "instruction": "Do not open with a question.", "scope": ["x"],
       "scope_exclude": ["scheduled-x"], "status": "active", "source": "founder"}


def _render(lane):
    return assemble.voice_section(_Voice([ROW]), "x", 0, target_words=None, lane=lane)


def test_an_excluded_lane_gets_neither_the_prose_nor_the_receipt():
    text, prov = _render("scheduled-x")
    assert "Do not open with a question" not in text
    assert "no-q" not in prov["correction_ids"]


def test_every_other_caller_still_gets_the_correction():
    for lane in (None, "attended-x"):
        text, prov = _render(lane)
        assert "Do not open with a question" in text
        assert "no-q" in prov["correction_ids"]


def test_validator_refuses_a_malformed_scope_exclude(tmp_path):
    bad = tmp_path / "corrections.jsonl"
    bad.write_text('{"id": "a", "instruction": "x", "class": "interpretive", '
                   '"status": "active", "scope_exclude": "scheduled-x"}\n')
    assert any("scope_exclude" in p for p in validate.check_corrections(str(bad)))
    good = tmp_path / "ok.jsonl"
    good.write_text('{"id": "a", "instruction": "x", "class": "interpretive", '
                    '"status": "active", "scope_exclude": ["scheduled-x"]}\n')
    assert validate.check_corrections(str(good)) == []
    typo = tmp_path / "typo.jsonl"
    typo.write_text('{"id": "a", "instruction": "x", "class": "interpretive", '
                    '"status": "active", "scope_exclude": ["scheduled-X"]}\n')
    assert any("scope_exclude" in p for p in validate.check_corrections(str(typo)))
