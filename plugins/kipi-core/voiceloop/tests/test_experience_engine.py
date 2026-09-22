#!/usr/bin/env python3
"""The corpus seam: the matcher has NO default corpus and refuses an unbound call.

why this file exists (2026-09-05, the package extraction). The matcher used to
resolve all three corpus files from `__file__`. Inside one instance that is correct
and invisible. Inside a package that ships fleet-wide it silently points every
founder at whichever corpus happens to sit beside the code, which is the same
failure `voice_ref` refuses by carrying no default corpus path at all.

The refusal is the load-bearing half of the move, so it gets the test. Every case
here builds its corpus in `tmp_path`; nothing reads a real one.
"""
import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voiceloop import experience  # noqa: E402

SCARS = """# rows

### Google

| Row | Flags | Audience | Notes |
|---|---|---|---|
| **Four teams fought one operation** | public-safe | CISO | "Four teams fought the same operation across two surfaces. None of them knew." |
"""

BUILT = """## Mechanisms

| Item | Flag | The specific |
|---|---|---|
| **A ledger that refuses an unverifiable row** | public-safe | The quarantine ledger keeps the row and refuses to score it, so an absence is visible instead of silent. |
"""


def _corpus(tmp_path, with_mined=True):
    (tmp_path / "scars.md").write_text(SCARS, encoding="utf-8")
    (tmp_path / "built.md").write_text(BUILT, encoding="utf-8")
    if with_mined:
        (tmp_path / "built-mined.jsonl").write_text("", encoding="utf-8")
    return str(tmp_path)


class TestTheEngineHasNoDefaultCorpus:

    def test_match_without_a_corpus_dir_is_a_type_error(self):
        """POSITIONAL AND REQUIRED. The old signature was `match(idea, path=None)`,
        so the call the instance makes today, `match(idea)`, used to succeed against
        a corpus resolved from the module's own location. It must now not compile a
        call at all."""
        with pytest.raises(TypeError):
            experience.match("four teams fought one operation")

    def test_match_with_an_empty_corpus_dir_refuses_loudly(self):
        """THE MUTATION THIS FILE WAS WRITTEN FOR. Passing None is what an adapter
        that lost its binding would do, and a `None` that fell through to a
        `__file__` join would be the exact silent failure the move exists to end."""
        with pytest.raises(experience.CorpusNotBound):
            experience.match("four teams fought one operation", None)
        with pytest.raises(experience.CorpusNotBound):
            experience.match("four teams fought one operation", "")

    def test_card_matches_refuses_on_the_same_terms(self):
        """The card door is the ONLY caller that asks for rows a writer may not see.
        A refusal that guarded one door and not the other would leak exactly the
        uncleared rows, which is the worst available half-fix."""
        with pytest.raises(experience.CorpusNotBound):
            experience.card_matches("four teams fought one operation", None)

    def test_corpus_paths_refuses_and_names_the_three_files(self):
        with pytest.raises(experience.CorpusNotBound) as exc:
            experience.corpus_paths(None)
        for name in (experience.SCARS_FILE, experience.BUILT_FILE,
                     experience.MINED_FILE):
            assert name in str(exc.value)

    def test_per_file_overrides_still_require_the_directory(self, tmp_path):
        """NEGATIVE CONTROL on the override path. A caller able to name all three
        files can name the directory, and letting the overrides stand in for it
        reopens the hole one argument to the left."""
        corpus = _corpus(tmp_path)
        with pytest.raises(experience.CorpusNotBound):
            experience.match("four teams fought one operation", None,
                             scars_path=os.path.join(corpus, "scars.md"),
                             built_path=os.path.join(corpus, "built.md"),
                             mined_path=os.path.join(corpus, "built-mined.jsonl"))

    @staticmethod
    def _file_refs(source):
        """`__file__` used as CODE, never as prose.

        A substring grep was the first version and it failed on this module's own
        docstring, which has to name `__file__` to explain why it does not use one.
        AST separates the two: a use is an `ast.Name`, a mention is a string
        constant.
        """
        return [node for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.Name) and node.id == "__file__"]

    def test_the_module_holds_no_file_relative_corpus_constant(self):
        """Read the tree, not the memory. A later edit that re-adds a
        `dirname(__file__)` corpus join would restore the defect with every test
        above still green, because those test the ARGUMENT and not the absence of a
        fallback."""
        with open(experience.__file__, encoding="utf-8") as handle:
            source = handle.read()
        found = self._file_refs(source)
        assert found == [], (
            "experience.py uses __file__ at line(s) %s. The corpus is the caller's; "
            "a path derived from where the code lives is the defect the package "
            "extraction removed." % [n.lineno for n in found])

    def test_the_file_detector_fires_on_the_shape_it_claims_to_catch(self):
        """NEGATIVE SELF-TEST. A detector that never fires reads exactly like one
        that works."""
        planted = ("import os\n"
                   "P = os.path.join(os.path.dirname(__file__), 'voice', 'x.md')\n")
        assert self._file_refs(planted)
        assert self._file_refs("P = 'a comment about __file__ in a string'") == []


class TestTheBoundCallStillRetrieves:
    """The refusal is worthless if it also refuses the good case."""

    def test_a_bound_call_finds_the_scar_row(self, tmp_path):
        hits = experience.match("four teams fought the same operation",
                                _corpus(tmp_path))
        assert [row["title"] for row in hits] == ["Four teams fought one operation"]
        assert hits[0]["company"] == "Google"

    def test_a_bound_call_finds_the_built_row_and_never_names_a_company(self, tmp_path):
        hits = experience.match("a ledger that refuses an unverifiable row",
                                _corpus(tmp_path))
        assert hits and hits[0]["kind"] == "built"
        assert hits[0]["company"] == ""

    def test_a_missing_corpus_FILE_degrades_to_empty_rather_than_raising(self, tmp_path):
        """The DIRECTORY is required; a file inside it is not. `load_mined` returning
        [] for an absent mined file is the documented degradation and is what a fresh
        clone gets. Those are two different questions and only one of them refuses."""
        corpus = _corpus(tmp_path, with_mined=False)
        assert experience.load_mined(os.path.join(corpus, "built-mined.jsonl")) == []
        assert experience.match("four teams fought the same operation", corpus)
