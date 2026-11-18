#!/usr/bin/env python3
"""A model revision may not change a number, a negation, a modal or a condition (ASK-5428).

History: commit 68035d22 pinned each BAD case as passing through today's `revise.revise`
(green on the old code). The same five cases now assert the refusal, so the fix is a visible
flip and not a new test written after the fact.
"""
import os
import sys

PKG_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

import pytest  # noqa: E402

from voiceloop import meaning_check, revise  # noqa: E402

VIOLATIONS = [{"rule": "banned-word", "detail": "banned word 'leverage'"}]

BAD = {
    "modal may->must": ("The cache may expire after a deploy.",
                        "The cache must expire after a deploy."),
    "negation dropped": ("The job does not retry on failure.",
                         "The job retries on failure."),
    "number 3->30": ("It took 3 hours to finish.", "It took 30 hours to finish."),
    "condition 'only if' dropped": ("It retries only if the queue is empty.",
                                    "It retries when the queue is empty."),
    "unit hours->days": ("It took 3 hours to finish.", "It took 3 days to finish."),
}

SAME = {
    "modal kept": ("The cache may expire after a deploy.",
                   "After a deploy, the cache may expire."),
    "negation contracted": ("The job does not retry on failure.",
                            "The job doesn't retry on failure."),
    "number as word": ("It took 3 hours to finish.", "The run took three hours."),
    "condition reordered": ("It retries only if the queue is empty.",
                            "Only if the queue is empty does it retry."),
    "unit abbreviated": ("It took 5 minutes to finish.", "It took 5 min to finish."),
}


def _revise(original, revised, violations=VIOLATIONS):
    return revise.revise(original, violations, runner=lambda prompt: revised)


@pytest.mark.parametrize("name", sorted(BAD))
def test_a_changed_meaning_is_refused_and_names_the_tokens(name):
    original, revised = BAD[name]
    with pytest.raises(revise.MeaningRefused) as caught:
        _revise(original, revised)
    assert caught.value.changes and "revision changed meaning" in str(caught.value)


def test_the_trail_names_the_exact_tokens():
    with pytest.raises(revise.MeaningRefused) as caught:
        _revise(*BAD["modal may->must"])
    assert caught.value.changes == {"modals": ["-may", "+must"]}
    with pytest.raises(revise.MeaningRefused) as caught:
        _revise(*BAD["number 3->30"])
    assert caught.value.changes == {"numbers": ["-3 hour", "+30 hour"]}
    with pytest.raises(revise.MeaningRefused) as caught:
        _revise(*BAD["condition 'only if' dropped"])
    assert set(caught.value.changes) == {"conditions"}
    assert "-if" in caught.value.changes["conditions"]


@pytest.mark.parametrize("name", sorted(SAME))
def test_same_meaning_rewords_pass(name):
    original, revised = SAME[name]
    assert _revise(original, revised) == revised


def test_a_drift_gets_one_retry_that_names_the_tokens():
    original, bad = BAD["modal may->must"]
    prompts, answers = [], [bad, original]

    def runner(prompt):
        prompts.append(prompt)
        return answers.pop(0)

    assert revise.revise(original, VIOLATIONS, runner=runner) == original
    assert len(prompts) == 2 and "CHANGED THE MEANING" in prompts[1]
    assert "-may" in prompts[1] and "+must" in prompts[1]
    assert "CHANGED THE MEANING" not in prompts[0]


def test_two_drifts_in_a_row_refuse_after_exactly_two_calls():
    original, bad = BAD["negation dropped"]
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return bad

    with pytest.raises(revise.MeaningRefused):
        revise.revise(original, VIOLATIONS, runner=runner)
    assert len(calls) == 2


def test_a_figure_rule_may_change_numbers_but_not_the_modals():
    figure = [{"rule": "figure-unsourced", "detail": "42"}]
    assert _revise("We shipped 42 fixes.", "We shipped 40 fixes.", figure)
    with pytest.raises(revise.MeaningRefused):
        _revise("It may drop 42 rows.", "It must drop 40 rows.", figure)


def test_a_cut_may_remove_but_never_add_or_flip():
    cut = [{"rule": "x-too-long", "detail": "too long"}]
    long = "The cache may expire. It retries only if the queue is empty."
    assert _revise(long, "The cache may expire.", cut) == "The cache may expire."
    with pytest.raises(revise.MeaningRefused):
        _revise(long, "The cache must expire.", cut)
    with pytest.raises(revise.MeaningRefused):
        _revise("The cache may expire.", "The cache may never expire.", cut)


def test_function_is_pure_and_empty_when_nothing_changed():
    text = "It may take 3 hours unless the cache is warm, by default."
    assert meaning_check.changes(text, text) == {}
    assert meaning_check.changes(text, "It may take 3 hours, unless the cache is warm, "
                                       "by default.") == {}
    assert "by default" in meaning_check.changes(text, "It may take 3 hours unless the "
                                                 "cache is warm.")["conditions"][0]


def test_a_bare_only_is_not_a_condition_and_contractions_are_modal_plus_negation():
    assert meaning_check.changes("It is the only option.", "It is the sole option.") == {}
    found = meaning_check.changes("It won't run.", "It will run.")
    assert found == {"negations": ["-not"]}
    assert meaning_check.changes("It can't run.", "It cannot run.") == {}
