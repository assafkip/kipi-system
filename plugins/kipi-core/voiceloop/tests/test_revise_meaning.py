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


def test_a_cut_may_remove_but_never_add_a_token():
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


# ---- round 2 (PR #843 review): span-rewrite rules, magnitudes, modals, guards ----------

SPAN_CASES = {
    "marketer-ending": ("It can fail on a cold start. Can your team afford that?",
                        "It can fail on a cold start. Nobody ships that and never checks."),
    "voice-opener-echo": ("If the queue is empty it will retry. The job ends.",
                          "The queue empties, then it retries. The job ends."),
    "voicefp-sentence_mean": ("It will retry, and if it fails it will not stop.",
                              "It retries. It fails. It keeps going."),
    "source-shape": ("The job should not retry (ASK-12 fixed it).",
                     "The job retries on failure, and a fix landed."),
}


@pytest.mark.parametrize("rule", sorted(SPAN_CASES))
def test_a_span_rewrite_rule_is_not_refused_for_the_words_it_ordered_rewritten(rule):
    original, revised = SPAN_CASES[rule]
    calls = []
    out = revise.revise(original, [{"rule": rule, "detail": "x"}],
                        runner=lambda prompt: calls.append(prompt) or revised)
    assert out == revised and len(calls) == 1


def test_a_span_rewrite_rule_still_refuses_an_added_figure():
    with pytest.raises(revise.MeaningRefused):
        _revise("It ends. Can you afford it?", "It ends. It costs 40 hours.",
                [{"rule": "marketer-ending", "detail": "x"}])


def test_every_strict_rule_name_is_a_rule_the_reviser_has_guidance_for():
    # A literal set, so a rename of a RULE_GUIDANCE key makes this fail (round 3 review:
    # the old set was DERIVED from the keys and could not fail on a rename).
    assert revise.STRICT_RULES
    for name in revise.STRICT_RULES:
        assert name in revise.RULE_GUIDANCE, name


@pytest.mark.parametrize("rule,original,revised", [
    # round 3 (consulting PR #616 review): rules the old name lists missed.
    ("figure-in-post", "We shipped 1,990 fixes in 3 hours.",
     "We shipped a large number of fixes."),
    ("voice-style-hedge_count", "It might fail. It will retry.", "It fails. It will retry."),
    ("voice-style-sentence_mean", "It will retry, and if it fails it will not stop.",
     "It retries. It fails. It keeps going."),
    ("some-rule-nobody-has-written-yet", "It may drop 3 rows.", "It drops rows."),
])
def test_a_rule_outside_the_strict_set_is_never_refused_for_a_removal(rule, original, revised):
    calls = []
    out = revise.revise(original, [{"rule": rule, "detail": "x"}],
                        runner=lambda prompt: calls.append(prompt) or revised)
    assert out == revised and len(calls) == 1


def test_a_strict_rule_still_refuses_a_dropped_modal():
    with pytest.raises(revise.MeaningRefused):
        _revise("It might fail.", "It fails.", [{"rule": "banned-word", "detail": "x"}])


def test_mixed_strict_and_lenient_rules_are_lenient():
    out = _revise("It might fail.", "It fails.",
                  [{"rule": "banned-word", "detail": "x"},
                   {"rule": "voice-style-hedge_count", "detail": "x"}])
    assert out == "It fails."


def test_the_lane_catches_the_class_it_imports_not_one_read_off_the_injected_object():
    # PR #616 review, major: production injects a SimpleNamespace (post_envelope.revise_port),
    # which has no MeaningRefused attribute, so a getattr fallback caught nothing.
    import ast
    from voiceloop import gate_and_judge
    assert gate_and_judge.MeaningRefused is meaning_check.MeaningRefused
    assert revise.MeaningRefused is meaning_check.MeaningRefused
    tree = ast.parse(open(gate_and_judge.__file__).read())
    reads = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute)
             and n.attr == "MeaningRefused" and isinstance(n.value, ast.Name)
             and n.value.id == "revise"]
    assert not reads, "gate_and_judge reads MeaningRefused off the injected revise"


def test_the_retry_names_every_enforced_modal_and_sits_apart_from_the_post():
    prompts = []

    def runner(prompt):
        prompts.append(prompt)
        return "The cache must expire after a deploy."
    with pytest.raises(revise.MeaningRefused):
        revise.revise("The cache may expire after a deploy.", VIOLATIONS, runner=runner)
    before, after = prompts[1].split("YOUR LAST ANSWER")
    for word in meaning_check.MODALS:
        assert word in after, word
    assert "END OF POST" in before[-80:]


def test_a_shortened_magnitude_is_the_same_figure():
    assert meaning_check.changes("It cost $5 million.", "It cost $5M.") == {}
    assert meaning_check.changes("5 million users", "5M users") == {}
    assert meaning_check.changes("5 million users", "50 million users") != {}


def test_hyphenated_word_numbers_are_figures():
    assert meaning_check.changes("It took twenty-one days.", "It took 21 days.") == {}
    assert meaning_check.changes("It took twenty-one days.", "It took twenty-one weeks.")


def test_would_and_shall_are_modals():
    assert meaning_check.changes("It would break.", "It will break.") == {
        "modals": ["+will", "-would"]}
    assert meaning_check.changes("It would not run.", "It runs.")["modals"] == ["-would"]


def test_by_default_cannot_be_built_across_a_sentence_boundary():
    assert meaning_check.changes("It was decided by. Default is off.",
                                 "It was decided. Default is off.") == {}


def test_known_limit_the_compare_ignores_position():
    # Pinned, not endorsed: a moved token reads as intact. The docstring says so; this
    # test fails the day someone adds an ordered compare, so the docstring gets updated.
    assert meaning_check.changes("from 900 ms to 120 ms", "from 120 ms to 900 ms") == {}


def test_a_number_rule_may_delete_a_figure_with_the_sentence_that_carried_it():
    # PR #854 review, major: figure-unsourced orders the deletion; the sentence it sat in
    # also held a modal, and the removal was refused.
    original = "It might drop 42 rows. The job ends."
    out = _revise(original, "The job ends.", [{"rule": "figure-unsourced", "detail": "42"}])
    assert out == "The job ends."
    with pytest.raises(revise.MeaningRefused):
        _revise(original, "It must drop 42 rows. The job ends.",
                [{"rule": "figure-unsourced", "detail": "42"}])


def test_the_fail_closed_sentinel_does_not_switch_the_check_off():
    with pytest.raises(revise.MeaningRefused):
        _revise("It might fail.", "It fails.", [{"rule": "voice-lint-error", "detail": "x"}])
