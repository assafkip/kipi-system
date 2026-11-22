"""encode_windowed_many on the real backends (ASK-5540).

Scar: consulting #622 batched calibrate through `encode_windowed_many`, but only a
test fake defined it, so the real uv backend fell back to one subprocess per text.
Here the subprocess is faked at `subprocess.run` and COUNTED; the worker body and
the windowing helpers are the real code. No model, no torch, no uv, no live path.
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voiceloop import luar_env_backend as eb  # noqa: E402
from voiceloop import luar_scorer as s  # noqa: E402


def _offsets(text):
    out, pos = [], 0
    for w in text.split():
        i = text.index(w, pos)
        out.append((i, i + len(w)))
        pos = i + len(w)
    return out


class Counting:
    """encode() records every batch so document re-embeds are visible."""
    def __init__(self):
        self.batches = []

    def __call__(self, docs):
        self.batches.append(list(docs))
        return [[float(len(d)), 1.0] for d in docs]


def _many(texts, docs, enc):
    return s.windowed_many_reply(texts, _offsets, enc, docs,
                                 count_tokens=lambda t: len(t.split()),
                                 offsets_of=_offsets)


TEXTS = ["a b c", " ".join("w%d" % i for i in range(1200)), "x y"]
DOCS = ["doc one", "doc two two"]


class ManyReply(unittest.TestCase):
    def test_per_text_matches_the_single_reply(self):
        reply = _many(TEXTS, DOCS, Counting())
        for text, rec in zip(TEXTS, reply["per_text"]):
            one = s.windowed_reply(text, _offsets(text), Counting(), DOCS,
                                   lambda t: len(t.split()), offsets_of=_offsets)
            for k in ("window_vectors", "tokens", "share_read"):
                self.assertEqual(rec[k], one[k], k)
        self.assertEqual([r["tokens"] for r in reply["per_text"]], [3, 1200, 2])
        self.assertEqual(reply["vectors"], [[7.0, 1.0], [11.0, 1.0]])

    def test_documents_are_embedded_once_not_per_text(self):
        enc = Counting()
        _many(TEXTS, DOCS, enc)
        embedded = [d for b in enc.batches for d in b]
        self.assertEqual(embedded.count("doc one"), 1, enc.batches)

    def test_no_texts_is_refused(self):
        with self.assertRaises(ValueError):
            _many([], DOCS, Counting())


class UvPath(unittest.TestCase):
    def setUp(self):
        self.calls = 0
        self.reply_mutator = None

    def _run(self, cmd, input, **kw):
        self.calls += 1
        req = json.loads(input)
        out = cmd[cmd.index("--out") + 1]
        fake = type("B", (), {})()
        enc = Counting()
        if "windowed_texts" in req:
            payload = _many(req["windowed_texts"], req["documents"], enc)
        else:
            payload = s.windowed_reply(req["windowed_text"],
                                       _offsets(req["windowed_text"]), enc,
                                       req["documents"],
                                       lambda t: len(t.split()), offsets_of=_offsets)
        if self.reply_mutator:
            self.reply_mutator(payload)
        with open(out, "w") as fh:
            json.dump(payload, fh)
        return mock.Mock(returncode=0, stderr="")

    def _backend(self):
        return mock.patch.multiple(
            eb, _uv_available=lambda: True, ensure_declared_env=lambda: None)

    def test_n_texts_cost_one_subprocess(self):
        with self._backend(), mock.patch.object(eb.subprocess, "run", self._run):
            reply = eb.UvEnvBackend().encode_windowed_many(TEXTS, DOCS)
            self.assertEqual(self.calls, 1)
            self.assertEqual(len(reply["per_text"]), len(TEXTS))
            self.calls = 0
            for t in TEXTS:                      # the fallback this replaces
                eb.UvEnvBackend().encode_windowed(t, DOCS)
            self.assertEqual(self.calls, len(TEXTS))

    def test_wrong_length_per_text_is_refused(self):
        self.reply_mutator = lambda p: p["per_text"].pop()
        with self._backend(), mock.patch.object(eb.subprocess, "run", self._run):
            with self.assertRaises(s.ScorerUnavailable):
                eb.UvEnvBackend().encode_windowed_many(TEXTS, DOCS)

    def test_worker_dispatches_to_many(self):
        seen = {}

        class FakeTB:
            def encode_windowed_many(self, texts, documents):
                seen["many"] = (list(texts), list(documents))
                return {"per_text": [], "vectors": []}

            def encode_windowed(self, text, documents):
                seen["one"] = True
                return {}

        out = os.path.join(os.environ.get("TMPDIR", "/tmp"), "many-%d.json" % os.getpid())
        req = json.dumps({"documents": DOCS, "windowed_texts": TEXTS})
        try:
            with mock.patch.object(s, "TransformersBackend", FakeTB), \
                    mock.patch.object(sys, "stdin", io.StringIO(req)):
                code = eb._worker_main(["--out", out])
        finally:
            if os.path.exists(out):
                os.unlink(out)
        self.assertEqual(code, 0)
        self.assertEqual(seen, {"many": (TEXTS, DOCS)})


if __name__ == "__main__":
    unittest.main()
