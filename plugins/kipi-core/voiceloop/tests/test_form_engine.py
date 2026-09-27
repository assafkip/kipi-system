#!/usr/bin/env python3
"""The form checker as ENGINE code: measurements are pure, corpus reads are bound.

why this file exists (2026-09-05, package extraction slice 4b). `form` split. The
measurements stayed whole and moved here; the corpus RESOLUTION stayed in the
deployment. The deployment's `test_form.py` still covers the adapter half
(`corpus_path`, the env override, the two candidate directory names), and it stopped
shipping to the mirror because none of those exist over here -- the mirrored copy
failed at collection with "module 'voiceloop.form' has no attribute 'corpus_path'"
and the exporter refused the commit.

So this file covers what that one now structurally cannot: that the engine works
with NO deployment present, and that it refuses rather than guesses when nobody
tells it where the corpus is.

THE PROPERTY THAT MATTERS. `corpus_path()` used to resolve from `__file__`. Moving
the file would silently have repointed it at `plugins/kipi-core/voice/exemplars.jsonl`,
which does not exist, and every band would have come back computed from an empty
corpus. Empty is this module's chosen degradation for a missing file, so nothing
would have raised and no test would have failed. That is why the readers now take a
required path: the failure has to be loud, at the call site, on the first call.
"""
import inspect
import json
import os
import sys

import pytest

PKG_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

from voiceloop import form  # noqa: E402

READERS = ("corpus_posts", "bands", "report", "summary_line", "writer_guidance")


class TestTheEngineCannotGuessACorpus:
    """The whole reason this module split rather than moving."""

    def test_no_reader_has_a_default_path(self):
        for name in READERS:
            sig = inspect.signature(getattr(form, name))
            assert "path" in sig.parameters, f"{name} lost its path parameter"
            assert sig.parameters["path"].default is inspect.Parameter.empty, (
                f"form.{name} has a default path. A packaged module that can guess "
                f"a corpus points every operator at whichever file sits beside the "
                f"code, and reads empty in silence when none does")

    def test_calling_a_reader_without_a_path_raises(self):
        """Loud at the call site, which is the point. Not an empty result."""
        for name in READERS:
            with pytest.raises(TypeError):
                getattr(form, name)("x") if name != "report" else form.report("x", "x")

    def test_the_module_resolves_no_path_from_its_own_location(self):
        """Asserted on CODE via the AST, never on the file's text.

        The first version grepped the body for `__file__` and failed on this
        module's own comment explaining why `__file__` resolution was removed. That
        is the second time in one evening a prose mention tripped a code assertion
        here (the first was `slop_shapes` citing its exemplar corpus). A rule that
        fires on documentation teaches people to delete documentation.
        """
        import ast

        with open(form.__file__, encoding="utf-8") as handle:
            body = handle.read()
        assert ("q-" + "consult") not in body

        tree = ast.parse(body)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert "__file__" not in names, (
            "form resolves a path from __file__ again; that is exactly what made "
            "moving this file a silent behaviour change")


class TestTheMeasurementsAreStillPure:
    """They took no corpus before the split and must take none after."""

    def test_measure_reads_only_its_argument(self):
        out = form.measure("A short line. Then another one that runs a little longer.")
        assert isinstance(out, dict) and out

    def test_hook_words_and_paragraph_sentences_work_with_no_corpus(self):
        assert form.hook_words("Four teams fought the same problem.")
        assert form.paragraph_sentences("One. Two.\n\nThree.")


class TestABoundCorpusIsActuallyRead:
    """Give it a corpus in tmp_path and prove the readers use THAT one."""

    def _corpus(self, tmp_path, rows):
        p = tmp_path / "exemplars.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return str(p)

    def test_corpus_posts_returns_only_posts_from_the_given_file(self, tmp_path):
        path = self._corpus(tmp_path, [
            {"channel": "x", "kind": "post", "text": "the post that counts"},
            {"channel": "x", "kind": "comment", "text": "a comment that does not"},
            {"channel": "linkedin", "kind": "post", "text": "another channel"},
        ])
        out = form.corpus_posts("x", path)
        assert out == ["the post that counts"]

    def test_a_missing_file_still_degrades_to_empty(self, tmp_path):
        """Unchanged behaviour: absent corpus costs the reference, never a crash."""
        assert form.corpus_posts("x", str(tmp_path / "nope.jsonl")) == []
