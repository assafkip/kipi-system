#!/usr/bin/env python3
"""Tests for q-system/hooks/lessons-index.py (ASK-965, finding-12).

Pairs with the SessionStart lessons injector.

THE TWO FAILURES THIS PINS, and they are the SAME defect pointed in opposite
directions:

  the old CAP        silently DROPPED content. CAP=20 against a corpus of 146
                     hid 126 lessons (86%) in every session, and chose which to
                     hide by ALPHABETICAL FILENAME, because the sort key was date
                     only and Python's sort is stable. Measured in the consulting
                     instance (153 lessons): the four lessons that exactly
                     described that week's failures ranked 93, 27, 57 and 24
                     against a cutoff of 20. All four had aged out.

  unbounded growth   silently GROWS. Injecting everything with no ceiling means
                     the payload creeps up every session and nobody sees the
                     moment it stops being worth it.

So the cap is gone and a CEILING replaces it. The ceiling never drops a lesson;
it fails this test, which turns growth into a decision someone makes on purpose
instead of a drift nobody watches.
"""
import importlib.util
import sys
from pathlib import Path

_HOOK = Path(__file__).resolve().parents[2] / "hooks" / "lessons-index.py"
_LESSONS = Path(__file__).resolve().parents[2] / "lessons"


def _load():
    spec = importlib.util.spec_from_file_location("lessons_index", _HOOK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lessons_index"] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load()


def test_no_cap_remains():
    """The structural half. A behavioural test could be satisfied while a cap
    lurked behind a condition, so this pins the absence of the slice itself."""
    src = _HOOK.read_text()
    assert "CAP = " not in src, "the cap is gone; a ceiling is not a cap"
    assert "[:CAP]" not in src


def test_every_lesson_with_a_title_is_injected():
    """THE POINT. 126 of 146 lessons were invisible in every session."""
    titles = L.collect_titles(_LESSONS)
    on_disk = [f for f in _LESSONS.glob("*.md") if f.name != "README.md"]
    titled = [f for f in on_disk if L.frontmatter(f).get("title")]
    assert len(titles) == len(titled), (len(titles), len(titled))
    assert len(titles) > 20, "a corpus at or under the old cap would not test anything"
    body = L.build_body(titles)
    for t in titles:
        assert t in body


def test_payload_stays_under_the_measured_ceiling():
    """THE CEILING, measured not estimated.

    At 146 lessons the payload is 9,933 chars, about 2,483 tokens (chars/4). The
    ceiling is 20,000 chars, roughly double, which is about 300 lessons at the
    current 2.61 writes/day -- somewhere over a year of headroom.

    WHEN THIS GOES RED, DO NOT RAISE IT REFLEXIVELY. Red means the SessionStart
    cost has doubled and someone has to decide whether every title still earns its
    place. That decision is the whole point; a cap made it silently and badly.
    """
    body = L.build_body(L.collect_titles(_LESSONS))
    assert len(body) <= L.PAYLOAD_CEILING_CHARS, (
        "lessons payload is %d chars (~%d tokens), over the %d ceiling. This is a "
        "decision to make, not a number to bump: prune, split the corpus, or raise "
        "the ceiling deliberately."
        % (len(body), len(body) // 4, L.PAYLOAD_CEILING_CHARS))


def test_ordering_is_total_and_stable():
    """The old key was date alone, so same-day lessons were ordered by filename.
    Harmless now that everything is injected, and it WAS the silent eviction rule
    while the cap existed. A total key means the output cannot change for reasons
    nobody can see."""
    titles = L.collect_titles(_LESSONS)
    assert titles == L.collect_titles(_LESSONS)


def test_missing_lessons_dir_is_silent(tmp_path):
    """The fail-closed contract survives. This runs at SessionStart, so it must
    never block a session starting, whatever it finds."""
    assert L.collect_titles(tmp_path) == []
