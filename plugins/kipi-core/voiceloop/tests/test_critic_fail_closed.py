#!/usr/bin/env python3
"""ASK-5411: a failed quality row never yields a partly-judged, complete-looking run.

Founder ruling, 2026-11-18, verbatim: "sana needs to fix this so when the post fails, it
lets me know and tries again, not fails open."

Measured repro (a LinkedIn post, 2026-11-18): one quality row failed, `review` skipped
the whole style wave, the critic part reported 8 of 15 rows, and the receipt still read
`complete`. Three pins:

- `review` judges every row even when a quality row FAILS (no wave skip on a FAIL).
- `run` revises up to its attempt cap, every pass judges every row, and a draft that
  still fails at the cap is refused with the failed rows named (the lane alerts on it).

The "a partial run never yields complete" rule itself is ASK-4969's shared
partial-run check, on its own branch. This file pins only that the critic stops
producing the partial run.

Judge, reviser and regate are stubs; no model is called; every path is a tmp_path.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voiceloop import critic  # noqa: E402

DRAFT = "A post body used only as a fixture."


def _rows():
    return [
        {"id": "maps-to-a-buyer-problem", "tier": critic.QUALITY,
         "text": "QUALITYMARK the post maps to a buyer problem."},
        {"id": "no-rule-of-three", "tier": critic.STYLE, "text": "STYLEMARK one."},
        {"id": "no-emdash", "tier": critic.STYLE, "text": "STYLEMARK two."},
    ]


def _checklist(tmp_path):
    p = tmp_path / "checklist.json"
    p.write_text(json.dumps(_rows()), encoding="utf-8")
    return str(p)


def _runner(prompt):
    if "QUALITYMARK" in prompt:
        return "EVIDENCE: no buyer named.\nVERDICT: FAIL\n"
    return "EVIDENCE: fine.\nVERDICT: PASS\n"


def test_a_quality_FAIL_still_judges_every_style_row(tmp_path):
    """RED on the 2026-08-13 wave cut: a FAIL returned the quality wave alone."""
    res = critic.review(DRAFT, "linkedin", path=_checklist(tmp_path), runner=_runner)
    assert [r["id"] for r, _v, _d, _f in res] == [r["id"] for r in _rows()], (
        "a quality FAIL skipped the style rows; the critic part becomes a partial run")
    assert [v for _r, v, _d, _f in res] == [critic.FAIL, critic.PASS, critic.PASS]


def test_a_draft_that_keeps_failing_retries_to_the_cap_then_is_refused_with_reasons(tmp_path):
    told = []
    revised = []

    def reviser(text, _violations):
        revised.append(text)
        return text + " revised"

    out = critic.run(DRAFT, "linkedin", path=_checklist(tmp_path),
                     log_path=str(tmp_path / "log.jsonl"), runner=_runner,
                     reviser=reviser, regate=lambda t: (t, []), attempts=3,
                     notify=told.append, at="2026-11-18T00:00:00Z")
    assert out.status == critic.DISCARDED and out.text == ""
    assert out.attempts == 3 and len(revised) == 2, "did not retry to the cap"
    assert any("maps-to-a-buyer-problem" in r for r in out.reasons)
    # Every pass judged all 3 rows: 3 passes x 3 rows of critique.
    crit = [r for r in out.rows if r["stage"] == critic.STAGE_CRITIQUE]
    assert len(crit) == 9, "a revision pass skipped rows (%d critique rows)" % len(crit)
    # One candidate's discard is routine (the slot refills), so the engine sends no
    # "refused" alert per candidate (PR #840 review). The lane alerts on the POST.
    assert told == [], "a per-candidate refusal reached the notify sink: %r" % told


def test_a_raising_sink_on_an_empty_checklist_does_not_kill_the_run(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")

    def sink(_msg):
        raise RuntimeError("slack timed out")

    out = critic.run(DRAFT, "linkedin", path=str(empty),
                     log_path=str(tmp_path / "log.jsonl"), runner=_runner,
                     notify=sink, at="2026-11-18T00:00:00Z")
    assert out.status == critic.ACCEPTED


def test_CONTROL_an_accepted_draft_is_not_reported_as_refused(tmp_path):
    told = []
    out = critic.run(DRAFT, "linkedin", path=_checklist(tmp_path),
                     log_path=str(tmp_path / "log.jsonl"),
                     runner=lambda _p: "EVIDENCE: fine.\nVERDICT: PASS\n",
                     notify=told.append, at="2026-11-18T00:00:00Z")
    assert out.status == critic.ACCEPTED and told == []
