#!/usr/bin/env python3
"""The length axis: selector.length_band + select(target_words=...).

why these exist (2026-08-13): the axis shipped with zero tests. An adversarial
review said so plainly -- 74 tests passed and not one of them named `target_words`,
`length_band` or `LONG_WORDS`, so "74 tests pass" proved no REGRESSION and nothing
about the new code. The only evidence it worked was a one-off sweep in a terminal,
which disappears the moment someone edits the module.

Fixtures are built here rather than read from a founder corpus: voicekit ships to
every instance and `test_no_founder_data.py` holds that direction.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voicekit import selector  # noqa: E402


def rows():
    """Mirrors the real corpus SHAPE: many short posts, one long one, plus a
    separate article-excerpt tier holding both a long and a short row."""
    out = [{"id": f"p-{i:02d}", "kind": "post", "channel": "x",
            "text": "word " * 20, "words": 20} for i in range(10)]
    out.append({"id": "p-long", "kind": "post", "channel": "x",
                "text": "word " * 400, "words": 400})
    out.append({"id": "a-long", "kind": "article-excerpt", "channel": "x",
                "text": "word " * 300, "words": 300})
    out.append({"id": "a-short", "kind": "article-excerpt", "channel": "x",
                "text": "word " * 50, "words": 50})
    return out


def ids(picked):
    return [r["id"] for r in picked]


def test_none_target_is_unchanged_behaviour():
    """The back-compat promise every existing caller and pinned test rests on."""
    r = rows()
    for counter in range(12):
        assert selector.select(r, "x", counter, k=4) == \
            selector.select(r, "x", counter, k=4, target_words=None)


def test_long_target_returns_only_long_rows():
    picked = selector.select(rows(), "x", 0, k=4, target_words=480)
    assert picked, "a long target must not return an empty selection"
    for row in picked:
        assert row["words"] >= selector.LONG_WORDS, ids(picked)


def test_short_target_never_returns_the_long_row():
    """The defect that started this: a 20-word slot taught by a 479-word article."""
    for counter in range(40):
        picked = selector.select(rows(), "x", counter, k=4, target_words=25)
        assert "p-long" not in ids(picked)
        assert "a-long" not in ids(picked)


def test_long_target_promotes_article_excerpts_into_reach():
    """Measured on the real corpus: 18 article excerpts were unreachable at EVERY
    counter because the post tier alone exceeded k, so length filtering ran on a
    pool they had never entered."""
    picked = selector.select(rows(), "x", 0, k=4, target_words=480)
    assert "a-long" in ids(picked), ids(picked)


def test_short_target_keeps_the_2026_08_09_scar_closed():
    """Article rhythm taught post slots and the engine published essays on a
    280-char channel. Promotion is for LONG requests only."""
    for counter in range(40):
        picked = selector.select(rows(), "x", counter, k=4, target_words=25)
        for row in picked:
            assert row["kind"] != "article-excerpt", ids(picked)


def test_length_band_returns_empty_rather_than_silently_widening():
    """The caller decides whether to widen. A band that quietly falls back is how a
    wrong-register prompt looks identical to a right one."""
    short_only = [{"id": "s", "kind": "post", "channel": "x",
                   "text": "word " * 10, "words": 10}]
    assert selector.length_band(short_only, 480) == []
    assert selector.length_band(short_only, None) == short_only


def test_words_falls_back_to_measuring_when_the_field_is_absent():
    """Instances whose corpus predates the `words` field must still band correctly."""
    legacy = [{"id": "legacy", "kind": "post", "channel": "x",
               "text": "word " * 300}]
    assert selector.length_band(legacy, 480) == legacy
    assert selector.length_band(legacy, 25) == []


def test_selection_stays_deterministic_with_a_target():
    r = rows()
    for counter in (0, 3, 17):
        assert selector.select(r, "x", counter, k=4, target_words=480) == \
            selector.select(r, "x", counter, k=4, target_words=480)


def test_a_starved_band_widens_rather_than_returning_nothing():
    """Exhaustion must not become starvation: a corpus with no long row still gets
    a prompt, because an empty voice section produces writing in nobody's voice."""
    short_only = [{"id": f"s-{i}", "kind": "post", "channel": "x",
                   "text": "word " * 10, "words": 10} for i in range(6)]
    picked = selector.select(short_only, "x", 0, k=4, target_words=480)
    assert len(picked) == 4, ids(picked)
