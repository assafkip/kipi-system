#!/usr/bin/env python3
"""`critic.run` is DRIVEN here, so emptying `critic.py` is RED rather than green.

WHY THIS EXISTS (ASK-1941, promoted from PR #311 review). `test_engine_surface.py`
names `critic` in a module manifest and imports it. An empty file imports fine, so
the manifest gate proves the file EXISTS and nothing about what it does. Measured
on this branch before this file existed: `critic.py` truncated to zero bytes left
the voiceloop suite at 292 passed. The repo that SYNCS this engine to the fleet
could not tell a working critic from an empty one.

WHAT IS DRIVEN. The public entry `critic.run`, end to end, against a stubbed model
call. Every case below asserts a behaviour that a mutation inside `critic.py` can
break, not a name that a deletion can remove:

  a clean pass ships THE JUDGED TEXT              `run` returns what it was handed
  a quality FAIL with no reviser discards         and names the constraint
  an unparseable answer is asymmetric             CLOSED on quality, OPEN on style
  an empty checklist is LOUD AND OPEN             a warn row plus the notify sink
  the stub is load-bearing                        no live `claude -p` is reachable

The asymmetry case is the one worth the file. It is this module's central named
behaviour, it is a judgment nothing deterministic re-derives, and inverting it
turns a supply cliff into a silent pass on the three questions the founder's read
keeps failing on.

NO LIVE MODEL CALL, and that is asserted rather than assumed. Every case injects
`runner=`, and `test_the_injected_runner_is_load_bearing` proves the omission
raises instead of shelling out: the negative self-test that stops the four green
cases above from being green for the wrong reason.

SCOPE, stated narrowly. One module of the manifest in `test_engine_surface.py`.
Every other module named there is still presence-only and that is ASK-1941's
declared `Not doing`: one module proves the shape, the sweep is its own issue.
"""
import json
import os
import sys

import pytest

# Same three-deep insert every sibling in this directory uses (test_usage_ledger.py
# and the rest): the plugin dir is not on sys.path when pytest is rooted at the
# repo, which is how the staged-snapshot gate and CI run it. Omitting it made this
# file a COLLECTION error there while passing locally from inside the plugin dir.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voiceloop import critic  # noqa: E402


# The rows are this file's, not the operator's. `critic.rows_for` reads whatever
# JSON it is pointed at, so a fixture checklist exercises the real reader without
# any dependency on one person's constraint list.
#
# FUNCTIONS AND NOT MODULE CONSTANTS, which is a deliberate choice about the shape
# of the failure. Reading `critic.QUALITY` at import time made an emptied
# `critic.py` an AttributeError during COLLECTION, and a collection error aborts
# the whole run: measured here as `1 error in 0.08s`, with the other 292 tests
# never executed. That reports the deletion and hides everything else, including
# whether the rest of the engine still works. Resolved at CALL time instead, so an
# emptied module fails these six cases by driving them and the suite still reports
# on every other module.
#
# The tier still comes from `critic`, never restated as a literal here: a copy of
# a value the module owns agrees on the day it is written and goes quietly stale
# the day the module changes it.
def _quality_row():
    return {"id": "tells-a-story", "tier": critic.QUALITY,
            "text": "The post recounts something that happened."}


def _style_row():
    return {"id": "no-rule-of-three", "tier": critic.STYLE,
            "text": "The post does not list exactly three items."}


DRAFT = "The agent handed me a month-old note in a live meeting."


def _checklist(tmp_path, rows, name="checklist.json"):
    path = tmp_path / name
    path.write_text(json.dumps(rows), encoding="utf-8")
    return str(path)


def _answer(verdict):
    """The strict two-line contract `build_prompt` asks for."""
    return f"EVIDENCE: the thing in the post that decides it.\nVERDICT: {verdict}\n"


def _rows_from(log_path):
    return critic.read_log(str(log_path))


def _critique(rows):
    return [r for r in rows if r["stage"] == critic.STAGE_CRITIQUE]


def test_a_clean_pass_accepts_and_ships_THE_JUDGED_TEXT(tmp_path):
    """RED if `run` returns a body other than the one the verdicts were about.

    The rationale flows into the log rows only. A `run` that returned the model's
    answer, or a reviser's output that never re-entered the gates, would ship a
    body nothing judged.
    """
    log = tmp_path / "critic-log.jsonl"
    outcome = critic.run(
        DRAFT, "linkedin",
        path=_checklist(tmp_path, [_quality_row(), _style_row()]),
        log_path=str(log),
        runner=lambda _prompt: _answer("PASS"),
        at="2026-09-26T00:00:00Z")

    assert outcome.status == critic.ACCEPTED
    assert outcome.text == DRAFT, (
        "the accepted body is not the judged body, so the critic's verdicts "
        "describe text that never shipped")

    verdicts = {(r["constraint_id"], r["verdict"]) for r in _critique(_rows_from(log))}
    assert verdicts == {("tells-a-story", critic.PASS),
                        ("no-rule-of-three", critic.PASS)}, verdicts


def test_a_quality_FAIL_with_no_reviser_discards_and_NAMES_the_constraint(tmp_path):
    """RED if a failed quality row ships, or discards without saying which row.

    `reviser` and `regate` are both absent, which is the caller shape that must
    terminate in a discard rather than an unbounded loop. The reason string is the
    product: a discard nobody can attribute to a constraint is a dead slot with no
    diagnosis.
    """
    log = tmp_path / "critic-log.jsonl"
    outcome = critic.run(
        DRAFT, "linkedin",
        path=_checklist(tmp_path, [_quality_row()]),
        log_path=str(log),
        runner=lambda _prompt: _answer("FAIL"),
        at="2026-09-26T00:00:00Z")

    assert outcome.status == critic.DISCARDED
    assert outcome.text == "", "a discarded candidate must not carry a body"
    assert any("critic-tells-a-story" in reason for reason in outcome.reasons), \
        outcome.reasons
    assert [r["verdict"] for r in _critique(_rows_from(log))] == [critic.FAIL]


def test_an_unparseable_answer_fails_CLOSED_on_quality(tmp_path):
    """THE ASYMMETRY, half one. RED if an unreadable answer passes a quality row.

    Those three questions are the ones the founder's read keeps failing on, so an
    answer nobody can parse must not become a pass there.
    """
    log = tmp_path / "critic-log.jsonl"
    outcome = critic.run(
        DRAFT, "linkedin",
        path=_checklist(tmp_path, [_quality_row()]),
        log_path=str(log),
        runner=lambda _prompt: "I am not sure what to say about this one.",
        at="2026-09-26T00:00:00Z")

    assert outcome.status == critic.DISCARDED, (
        "an unparseable answer on a quality row was honoured as a pass. That is "
        "the fail-open direction this module is built to refuse.")
    assert [r["verdict"] for r in _critique(_rows_from(log))] == [critic.FAIL]


def test_the_SAME_unparseable_answer_passes_OPEN_on_style(tmp_path):
    """THE ASYMMETRY, half two, and the pair is what makes either half mean anything.

    Byte-identical runner to the case above, one field different in the row. RED if
    a style row starts blocking: a style constraint that cannot be parsed must not
    starve a slot, because an empty supply is a founder-facing dead slot.
    """
    log = tmp_path / "critic-log.jsonl"
    outcome = critic.run(
        DRAFT, "linkedin",
        path=_checklist(tmp_path, [_style_row()]),
        log_path=str(log),
        runner=lambda _prompt: "I am not sure what to say about this one.",
        at="2026-09-26T00:00:00Z")

    assert outcome.status == critic.ACCEPTED, (
        "an unparseable answer on a STYLE row blocked the candidate. A style row "
        "is not worth starving a slot for; the asymmetry has inverted.")
    assert [r["verdict"] for r in _critique(_rows_from(log))] == [critic.WARN]

    # The contract violation is a COUNTABLE row, not a suspicion. RED if the
    # format row stops landing, which is how the violation rate goes dark.
    fmt = [r for r in _rows_from(log) if r["stage"] == critic.STAGE_FORMAT]
    assert [r["verdict"] for r in fmt] == [critic.FORMAT_UNPARSEABLE], fmt


def test_an_empty_checklist_is_LOUD_and_OPEN(tmp_path):
    """RED if nothing-was-judged becomes indistinguishable from everything-passed.

    A checklist that reads as `[]` ships the draft, because refusing would kill
    supply on a wiring fault. What stops that being the quiet normal is the warn
    row and the notify sink, so both are asserted here.
    """
    log = tmp_path / "critic-log.jsonl"
    told = []
    outcome = critic.run(
        DRAFT, "linkedin",
        path=_checklist(tmp_path, [], name="empty.json"),
        log_path=str(log),
        runner=lambda _prompt: _answer("PASS"),
        notify=told.append,
        at="2026-09-26T00:00:00Z")

    assert outcome.status == critic.ACCEPTED
    checklist_rows = [r for r in _rows_from(log)
                      if r["stage"] == critic.STAGE_CHECKLIST]
    assert [r["verdict"] for r in checklist_rows] == [critic.WARN], checklist_rows
    assert told and "critic" in told[0], (
        "an empty checklist passed without telling the notify sink, so a critic "
        "that judged nothing looks exactly like one that approved everything")


def test_the_injected_runner_is_load_bearing(tmp_path):
    """THE NEGATIVE SELF-TEST. An instrument that cannot fail proves nothing.

    Every case above hands `critic.run` a stub and reads the verdict back. If the
    stub were ignored and the real chokepoint reached, those cases would still be
    green while spending live `claude -p` calls. So this omits `runner=` and
    asserts the spend guard in `prompt_render.run_model` raises, which is both the
    proof that the stub is the model path and the proof that no case in this file
    can reach a live model.
    """
    with pytest.raises(RuntimeError) as caught:
        critic.run(
            DRAFT, "linkedin",
            path=_checklist(tmp_path, [_quality_row()]),
            log_path=str(tmp_path / "critic-log.jsonl"),
            at="2026-09-26T00:00:00Z")
    assert "critic.judge()" in str(caught.value), str(caught.value)
