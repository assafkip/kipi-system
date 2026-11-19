"""The reference is built in the SAME shape as the draft statistic (ASK-5457, A5b).

Scar, found in the PR #837 review: the draft was read whole, in windows, and
scored by its lowest window, while the reference it is compared with stayed the
median of first-512-token leave-one-out cosines. A long text that sat on his
region for its first window and wandered after it set a reference near 1.0
while the same shaped draft scored near 0.0, so the floor compared unlike
things. The reference must be the median over exemplars of each exemplar's OWN
windowed statistic, with the exemplar's region being the others.

Fake backend only (see test_luar_windowed.py): no model, no torch, no corpus.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voiceloop import luar_scorer as s  # noqa: E402
from voiceloop.tests.test_luar_windowed import (  # noqa: E402
    TOKENS_PER_WORD, TruncatingFake, _essay, _offsets, _vec)


def _drifting(tag, head=300, tail=600):
    """His words for a window, then someone else's: 4 windows, only the first his."""
    return (_essay(head, tag=tag) + " "
            + " ".join(f"f{tag}x{i}" for i in range(tail)))


DRIFTERS = [{"text": _drifting(f"x{k}n")} for k in range(4)]
SHORTS = [{"text": _essay(220, tag=f"x{k}n")} for k in range(4)]


class WindowedReference(unittest.TestCase):

    def test_reference_and_draft_are_the_same_statistic(self):
        rec = s.score(_drifting("dr"), DRIFTERS, backend=TruncatingFake())
        self.assertEqual(rec["authorship_band"], "long")
        # A draft shaped like every exemplar must land at the reference, not far
        # under it. The head-only reference sat near 1.0 against a draft near 0.
        self.assertAlmostEqual(rec["authorship"], rec["authorship_reference"],
                               delta=0.1)
        self.assertAlmostEqual(rec["authorship_median"],
                               rec["authorship_reference_median"], delta=0.1)
        self.assertEqual(rec["authorship_reference_tokenization"],
                         s.TOKENIZATION_WINDOWED)

    def test_short_exemplars_keep_the_old_reference(self):
        # One window each: the statistic is the single-document number, so every
        # stored reference under one window stays comparable.
        rec = s.score(_essay(200, tag="dr"), SHORTS, backend=TruncatingFake())
        region = s.embed([r["text"] for r in SHORTS], TruncatingFake())
        old = s.leave_one_out_median(region)
        self.assertAlmostEqual(rec["authorship_reference"], old, places=12)
        self.assertAlmostEqual(rec["authorship_reference_median"], old, places=12)

    def test_a_backend_without_exemplar_windows_says_the_old_shape(self):
        class NoDocWindows(TruncatingFake):
            def encode_windowed(self, text, documents):
                reply = super().encode_windowed(text, documents)
                del reply["document_windows"]
                return reply

        rec = s.score(_drifting("dr"), DRIFTERS, backend=NoDocWindows())
        self.assertEqual(rec["authorship_reference_tokenization"], s.TOKENIZATION)
        self.assertEqual(rec["authorship_tokenization"], s.TOKENIZATION_WINDOWED)

    def test_malformed_exemplar_windows_are_refused(self):
        class Short(TruncatingFake):
            def encode_windowed(self, text, documents):
                reply = super().encode_windowed(text, documents)
                reply["document_windows"] = reply["document_windows"][:1]
                return reply

        class Empty(TruncatingFake):
            def encode_windowed(self, text, documents):
                reply = super().encode_windowed(text, documents)
                reply["document_windows"][0] = []
                return reply

        for fake in (Short(), Empty()):
            with self.assertRaises(s.ScorerUnavailable):
                s.score(_drifting("dr"), DRIFTERS, backend=fake)

    def test_exemplar_windows_cost_nothing_extra_for_single_window_texts(self):
        calls = []

        class Counting(TruncatingFake):
            def encode(self, documents):
                calls.append(len(documents))
                return super().encode(documents)

        s.score(_essay(200, tag="dr"), SHORTS, backend=Counting())
        # draft window + 4 exemplars, one call, no extra pieces.
        self.assertEqual(calls, [1 + len(SHORTS)])


if __name__ == "__main__":
    unittest.main()
