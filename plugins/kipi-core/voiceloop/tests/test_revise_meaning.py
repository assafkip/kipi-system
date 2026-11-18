#!/usr/bin/env python3
"""A model revision may not change a number, a negation, a modal or a condition (ASK-5428).

Stage 1 (characterization): each BAD case passes on today's code because `revise.revise`
hands the changed text straight back. That is the defect, pinned as a green test before
the fix, so the fix is a visible flip and not a new test written after the fact.
"""
import os
import sys

PKG_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

from voiceloop import revise  # noqa: E402

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


def _revise(original, revised):
    return revise.revise(original, VIOLATIONS, runner=lambda prompt: revised)


def test_today_a_changed_meaning_passes_through():
    for name, (original, revised) in BAD.items():
        assert _revise(original, revised) == revised, name


def test_same_meaning_rewords_pass():
    for name, (original, revised) in SAME.items():
        assert _revise(original, revised) == revised, name
