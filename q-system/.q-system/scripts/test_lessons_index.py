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


# Bytecode caching OFF for these loaders (ASK-965, 2026-08-21). Loading a module
# by path writes a .pyc keyed on that path, and a mutate-then-restore cycle can
# produce a file whose size and mtime the cache validator accepts -- so the module
# under test keeps running the OLD bytecode. That made a mutation test report
# GREEN after a restore while the source on disk was correct, i.e. a test result
# that described a file nobody was executing. Exactly the load-path class this PRD
# is about, arriving in the test harness.
sys.dont_write_bytecode = True


def _load():
    importlib.invalidate_caches()
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


def test_ordering_is_total_and_breaks_ties_by_title(tmp_path):
    """The old key was date alone, so SAME-DAY lessons were ordered by whatever
    order the filenames happened to arrive in -- and while the cap existed, that
    was the silent eviction rule.

    This asserted `collect_titles() == collect_titles()` until 2026-08-21, which
    is tautological: comparing a function to itself on an unchanged corpus passes
    under the old date-only key too, so it proved nothing (codex review of
    b5d96697, minor). It now builds same-day lessons whose FILENAME order is the
    REVERSE of their title order, which is the only shape that can tell the two
    keys apart.
    """
    lessons = tmp_path / "lessons"
    lessons.mkdir()
    # THE FIXTURE HAS TO DISCRIMINATE, and the first version did not: it used
    # filenames a,b,c with titles Zebra,Yak,Xray, so filename order and
    # title-descending order were IDENTICAL and both keys produced the same
    # answer. Mutating the key back to date-only left the test green -- a test
    # that cannot fail for the reason it claims, which is the thing this whole
    # session keeps finding.
    #
    # Ascending filenames with ASCENDING titles is the discriminating shape.
    # `sorted(reverse=True)` is stable and does NOT reverse ties, so a date-only
    # key returns filename order (Xray, Yak, Zebra) while (date, title) descending
    # returns Zebra, Yak, Xray. The two answers differ, so the assert can fail.
    for name, title in (("a.md", "Xray"), ("b.md", "Yak"), ("c.md", "Zebra")):
        (lessons / name).write_text(
            "---\ntitle: %s\ndate: 2026-06-01\n---\n\nbody\n" % title)
    got = L.collect_titles(lessons)
    assert got == ["Zebra", "Yak", "Xray"], got


def test_the_hook_and_the_test_read_the_same_collector():
    """ANTI-DRIFT. main() used to carry its own copy of the collection loop, so
    this test could have measured collect_titles while the hook shipped main's
    version -- and the ceiling number would stop describing the real payload
    without anything going red. Pins that main has exactly one caller for it and
    no inline duplicate."""
    src = _HOOK.read_text()
    body = src[src.index("def main("):]
    assert "collect_titles(" in body, "main must use the shared collector"
    assert 'fm.get("date"' not in body, "main must not re-implement collection"


def test_payload_matches_what_the_hook_emits():
    """END TO END. Runs the hook as a subprocess and asserts the emitted payload
    is byte-identical to what the ceiling test measures. A ceiling on a body the
    hook does not actually send would be measuring the wrong thing."""
    import json
    import os
    import subprocess
    root = Path(__file__).resolve().parents[3]
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    r = subprocess.run([sys.executable, str(_HOOK)], capture_output=True,
                       text=True, env=env)
    assert r.returncode == 0
    emitted = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert emitted == L.build_body(L.collect_titles(_LESSONS))


def test_missing_lessons_dir_is_silent(tmp_path):
    """The fail-closed contract survives. This runs at SessionStart, so it must
    never block a session starting, whatever it finds."""
    assert L.collect_titles(tmp_path) == []


if __name__ == "__main__":
    # The capability gate runs declared tests as `python3 <path>`, so the file has
    # to be executable on its own terms. Without this it was declared, discovered,
    # and never actually run -- present-but-ungated, which is the same shape as a
    # rule claiming ENFORCED with nothing behind it.
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
