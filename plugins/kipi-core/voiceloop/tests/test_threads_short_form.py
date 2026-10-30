"""threads is accepted beside x as the short-form channel.

An instance whose short-form lane moved from X to Threads relabels its corpus x -> threads
(2026-10-29). The engine named that lane as the literal "x" in five places; each test
below fails if one of them goes back to x-only, which is what a review of the first
version of this change proved by reverting all five and watching the suite stay green.
"""
from __future__ import annotations

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voiceloop import channel_registry, corpus, form, reply_format, voice_ref, x_format  # noqa: E402


def test_threads_is_a_short_form_channel_and_x_still_is():
    assert set(x_format.SHORT_FORM_CHANNELS) == {"x", "threads"}


def test_a_threads_row_is_legal():
    assert "threads" in corpus.EXEMPLAR_CHANNELS
    # The registry DEFAULT stays the pre-change literals on purpose (it changes every
    # instance); an instance with a threads lane declares it in voice-channels.json.
    assert "threads" not in channel_registry.DEFAULT_SCOPES


def test_threads_has_a_reply_lane():
    assert "threads" in reply_format.CHANNELS


def test_the_length_rule_runs_on_threads_exactly_as_on_x():
    verdict = lambda body, ch: [(r["rule"], bool(r.get("warn_only")))
                                for r in x_format.length_violations(body, ch)]
    for body in ("a" * 100, "a" * 600, "a" * 30000):
        assert verdict(body, "threads") == verdict(body, "x")
    assert x_format.length_violations("a" * 30000, "threads")
    assert x_format.length_violations("a" * 30000, "linkedin") == []


def test_the_dwell_floor_reaches_threads_and_names_no_platform(tmp_path):
    rows = [{"id": f"t{i}", "channel": "threads", "kind": "post", "status": "active",
             "text": "word " * (20 + i)} for i in range(10)]
    path = tmp_path / "exemplars.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    report = form.report("too short", "threads", path=str(path))
    assert report["char_rule"]["kind"] == "dwell-floor"
    assert any("short-form dwell floor" in f for f in report["flags"]), report["flags"]
    assert form.writer_guidance("threads", str(path)) is None


def test_a_threads_length_finding_names_no_platform_and_x_keeps_its_words():
    # Both branches (the fold warn and the ceiling block), and X as a whole word in any
    # position ("X.", "X's"), per the #565 review.
    for body in ("a" * 600, "a" * 30000):
        threads = x_format.length_violations(body, "threads")[0]["detail"]
        assert not re.search(r"\bX\b", threads) and "short-form" in threads, threads
    assert "X shows about" in x_format.length_violations("a" * 600, "x")[0]["detail"]
    assert "X truncates" in x_format.length_violations("a" * 30000, "x")[0]["detail"]


def test_voice_ref_takes_threads_and_still_refuses_an_unknown_channel(monkeypatch, tmp_path):
    monkeypatch.setenv("KIPI_VOICE_DIR", str(tmp_path))
    base = ["voice_ref", "--words", "40", "--slot-kind", "post", "--channel"]
    monkeypatch.setattr(sys, "argv", base + ["bogus"])
    with pytest.raises(SystemExit) as bad:
        voice_ref.main()
    assert bad.value.code == 2
    monkeypatch.setattr(sys, "argv", base + ["threads"])
    with pytest.raises(SystemExit) as good:
        voice_ref.main()
    # Past argparse: it now stops on the missing corpus, with a message, not code 2.
    assert good.value.code != 2 and "exemplars.jsonl" in str(good.value.code)
