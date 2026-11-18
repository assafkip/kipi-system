"""Authorship is read over the WHOLE text, in windows the model can hold (ASK-5358 part 1).

Scar, measured 2026-11-16: the first 400 words of an 841-word document scored
exactly the full document's score, and the first 480 words of a 2,479-word one
scored exactly its full score. `MAX_TOKENS = 512` truncation meant everything
after the first window was never read, so a draft could carry any amount of text
that was not his and the number could not move.

The fake backend below models that truncation honestly (2 tokens per word, 512
token cap), so on the pre-window code the essay and the essay-plus-filler embed
to the same vector. Only its tokenizer is fake: the window plan and the share
read come from the module's own pure helpers, the same ones the real backend uses.
No model, no torch, no live corpus.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voiceloop import luar_scorer as s  # noqa: E402

TOKENS_PER_WORD = 2


def _vec(words):
    # [his words, filler words, constant]: a region of his words points at
    # [1, 0, 0], a filler-only window points nearly at [0, 1, 0].
    e = sum(1 for w in words if w.startswith("e"))
    f = sum(1 for w in words if w.startswith("f"))
    return [float(e), float(f), 1.0]


def _offsets(text):
    """Two tokens per word, as character spans, the shape a fast tokenizer returns."""
    out, pos = [], 0
    for word in text.split(" "):
        mid = pos + max(1, len(word) // 2)
        out += [(pos, mid), (mid, pos + len(word))]
        pos += len(word) + 1
    return out


class TruncatingFake:
    """Reads only the first MAX_TOKENS tokens of each document, like LUAR does."""
    model_id = "fake-truncating"

    def encode(self, documents):
        keep = s.MAX_TOKENS // TOKENS_PER_WORD
        return [_vec(d.split()[:keep]) for d in documents]

    def encode_windowed(self, text, documents):
        return s.windowed_reply(text, _offsets(text), self.encode, documents,
                                count_tokens=lambda t: len(t.split()) * TOKENS_PER_WORD)


def _essay(n, tag="d"):
    return " ".join(f"e{tag}{i}" for i in range(n))


FILLER = " ".join(f"f{i}" for i in range(600))
EXEMPLARS = [{"text": _essay(220, tag=f"x{k}n")} for k in range(4)]


class WindowedAuthorship(unittest.TestCase):

    def test_filler_after_the_essay_pulls_the_score_down(self):
        essay = _essay(300)
        alone = s.score(essay, EXEMPLARS, backend=TruncatingFake())
        padded = s.score(essay + " " + FILLER, EXEMPLARS, backend=TruncatingFake())
        # The essay alone sits on his region; the filler windows do not.
        self.assertGreater(alone["authorship"], 0.99)
        self.assertLess(padded["authorship"], alone["authorship"] - 0.5,
                        "filler past the first 512 tokens was not read")
        self.assertEqual(padded["authorship_share_read"], 1.0)
        self.assertGreater(padded["authorship_windows"], 1)
        self.assertEqual(padded["authorship_tokenization"], s.TOKENIZATION_WINDOWED)
        self.assertEqual(padded["authorship_reference_tokenization"], s.TOKENIZATION)

    def test_one_filler_window_moves_the_lowest_not_the_median(self):
        # The decision on ASK-5358: a median lets a minority of the text be
        # someone else's. Here filler is 2 of 9 windows: the median stays on him.
        rec = s.score(_essay(1700) + " " + " ".join(f"f{i}" for i in range(500)),
                      EXEMPLARS, backend=TruncatingFake())
        self.assertGreater(rec["authorship_median"], 0.99)
        self.assertLess(rec["authorship"], rec["authorship_median"] - 0.5)

    def test_a_short_window_list_from_the_child_is_refused(self):
        class Skewed(TruncatingFake):
            def encode_windowed(self, text, documents):
                reply = super().encode_windowed(text, documents)
                reply["window_vectors"] = reply["window_vectors"][:1]
                return reply

        class NoShare(TruncatingFake):
            def encode_windowed(self, text, documents):
                reply = super().encode_windowed(text, documents)
                del reply["share_read"]
                return reply

        for fake in (Skewed(), NoShare()):
            with self.assertRaises(s.ScorerUnavailable):
                s.score(_essay(300) + " " + FILLER, EXEMPLARS, backend=fake)

    def test_every_window_fits_the_model(self):
        for n in (1, 503, 504, 505, 1008, 1800, 4959):
            plan = s.plan_windows(n, s.WINDOW_TOKENS)
            self.assertTrue(all(e - st <= s.WINDOW_TOKENS for st, e in plan), n)
            self.assertEqual(s.share_read(plan, n), 1.0, n)
        # The check can fail: a plan that stops at the first window reads under half.
        self.assertLess(s.share_read([(0, s.WINDOW_TOKENS)], 1800), 0.5)

    def test_short_text_scores_as_before(self):
        # One window: the number is the single-document number, so every stored
        # receipt under one window stays comparable with a new one.
        essay = _essay(200)
        new = s.score(essay, EXEMPLARS, backend=TruncatingFake())
        region = s.embed([r["text"] for r in EXEMPLARS], TruncatingFake())
        old = s.region_cosine(s.embed([essay], TruncatingFake())[0], region)
        self.assertAlmostEqual(new["authorship"], old, places=12)
        self.assertEqual(new["authorship_windows"], 1)

    def test_a_window_that_overflows_is_not_reported_as_read(self):
        # Re-tokenized alone, every window here holds twice its planned tokens,
        # so the model reads about half of each. The share must say so.
        text = _essay(1800 // TOKENS_PER_WORD)
        reply = s.windowed_reply(
            text, _offsets(text), TruncatingFake().encode, [],
            count_tokens=lambda t: len(t.split()) * TOKENS_PER_WORD * 2)
        self.assertLess(reply["share_read"], 0.6)

    def test_backend_without_windows_says_it_did_not_measure(self):
        class Plain:
            model_id = "plain"

            def encode(self, documents):
                return TruncatingFake().encode(documents)

        rec = s.score(_essay(300) + " " + FILLER, EXEMPLARS, backend=Plain())
        self.assertIsNone(rec["authorship_share_read"])
        self.assertEqual(rec["authorship_tokenization"], s.TOKENIZATION)


if __name__ == "__main__":
    unittest.main()
