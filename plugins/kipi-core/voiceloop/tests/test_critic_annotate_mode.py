#!/usr/bin/env python3
"""ASK-4487: a row marked annotate never drives a revision (consulting V7 sp-e877b091).

The judge and the reviser are stubs; no model is called. The control is the same FAIL
on a row without the flag, which must still revise exactly as before.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voiceloop import critic  # noqa: E402

DRAFT = "A post body used only as a fixture."


def _drive(tmp_path, extra):
    row = {"id": "tells-a-story", "tier": critic.QUALITY, "text": "It recounts an event."}
    row.update(extra)
    cl = tmp_path / "c.json"
    cl.write_text(json.dumps([row]), encoding="utf-8")
    revised = []

    def reviser(text, _violations):
        revised.append(text)
        return text + " revised"

    outcome = critic.run(
        DRAFT, "linkedin", path=str(cl), log_path=str(tmp_path / "log.jsonl"),
        runner=lambda _p: "EVIDENCE: x.\nVERDICT: FAIL\n",
        reviser=reviser, regate=lambda t: (t, []), at="2026-11-10T00:00:00Z")
    return outcome, revised


def test_an_annotate_row_FAIL_does_not_call_the_reviser_and_is_a_note(tmp_path):
    outcome, revised = _drive(tmp_path, {"mode": "annotate"})
    assert revised == [], "an annotate-mode FAIL drove a revision"
    assert outcome.status == critic.ACCEPTED
    assert outcome.text == DRAFT
    notes = [r for r in outcome.rows if r["stage"] == critic.STAGE_CRITIQUE]
    assert [(r["verdict"], r["detail"].startswith("annotate:")) for r in notes] == \
        [(critic.WARN, True)]


def test_CONTROL_a_block_row_FAIL_still_drives_a_revision(tmp_path):
    outcome, revised = _drive(tmp_path, {})
    assert revised and revised[0] == DRAFT, "the default (block) path no longer revises"


def test_review_itself_demotes_so_the_loop_and_the_gate_agree(tmp_path):
    cl = tmp_path / "c.json"
    cl.write_text(json.dumps([{"id": "a", "tier": critic.QUALITY, "text": "t",
                               "mode": "annotate"}]), encoding="utf-8")
    res = critic.review(DRAFT, "linkedin", path=str(cl),
                        runner=lambda _p: "EVIDENCE: x.\nVERDICT: FAIL\n")
    assert [v for _r, v, _d, _f in res] == [critic.WARN]
