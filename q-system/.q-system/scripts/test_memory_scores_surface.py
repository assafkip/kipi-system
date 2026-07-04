"""Tests for memory-scores-surface.py — the earned-trust recall surface.

finding-5: earned trust reaches TWO read surfaces — the SessionStart block and
the MEMORY.md index marker. The `marker` test is the bypass_check.
"""
from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import memory_outcomes as mo
import memory_reflect as mr

# The surface script has a hyphen in its filename, so load it by path.
_SPEC = importlib.util.spec_from_file_location(
    "memory_scores_surface",
    Path(__file__).with_name("memory-scores-surface.py"))
surface = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(surface)

NOW = datetime(2026, 7, 4, tzinfo=timezone.utc)


def _scored(tmp_path, root=None):
    """Build a sidecar with a preferred, a contested, and a stale memory."""
    log = tmp_path / "outcomes.jsonl"
    src = tmp_path / "cur.md"
    src.write_text("v1\n")
    # preferred: 2 distinct useful
    mo.record_outcome("m_pref", "useful", event_id="p1", date="2026-07-01", log_path=log)
    mo.record_outcome("m_pref", "useful", event_id="p2", date="2026-07-02", log_path=log)
    # contested: useful then corrected
    mo.record_outcome("m_cont", "useful", event_id="c1", date="2026-06-01", log_path=log)
    mo.record_outcome("m_cont", "corrected", event_id="c2", date="2026-07-03", log_path=log)
    # stale: cites a file we then change
    mo.record_outcome("m_stale", "useful", event_id="s1", date="2026-07-01",
                      source_file=str(src), log_path=log)
    mo.record_outcome("m_stale", "useful", event_id="s2", date="2026-07-02",
                      source_file=str(src), log_path=log)
    scores = tmp_path / ".memory-scores.json"
    mr.write_sidecar(mo.read_events(log), scores, now=NOW, root=root or tmp_path)
    src.write_text("v2\n")  # make m_stale stale
    return scores


def test_render_block_lists_preferred_contested_stale(tmp_path):
    scores = _scored(tmp_path)
    loaded = mr.load_sidecar(scores, root=tmp_path)
    block = surface.render_block(loaded)
    assert "m_pref" in block
    assert "m_cont" in block
    assert "m_stale" in block
    # coverage is labeled (finding-1 honesty)
    assert "q-system/memory" in block


def test_render_block_empty_when_no_scores():
    assert surface.render_block({}) == ""  # nothing to surface -> no noise


def test_marker_annotates_index(tmp_path):
    """bypass_check: MEMORY.md index lines get [contested]/[stale] prefixes."""
    scores = _scored(tmp_path)
    loaded = mr.load_sidecar(scores, root=tmp_path)
    index = (
        "# Memory Index\n\n"
        "- [Pref](m_pref.md) - a preferred memory\n"
        "- [Cont](m_cont.md) - a contested memory\n"
        "- [Stale](m_stale.md) - a stale memory\n"
    )
    out = surface.annotate_index(index, loaded)
    by_slug = {slug: line for line in out.splitlines()
               for slug in ("m_pref", "m_cont", "m_stale") if f"{slug}.md" in line}
    assert by_slug["m_cont"].startswith("- [contested]")
    assert by_slug["m_stale"].startswith("- [stale]")
    # preferred is not a risk marker -> line unchanged
    assert by_slug["m_pref"] == "- [Pref](m_pref.md) - a preferred memory"


def test_annotate_leaves_non_index_bullets_untouched(tmp_path):
    """A non-index bullet (incl. one that happens to start with a marker word)
    must not be rewritten (review finding)."""
    scores = mr.load_sidecar(_scored(tmp_path), root=tmp_path)
    index = (
        "- [contested] not an index line\n"
        "- see [docs](https://example.com) for more\n"
        "- [Unknown](m_absent.md) - not in sidecar\n"
    )
    assert surface.annotate_index(index, scores) == index  # unchanged


def test_main_silent_on_malformed_sidecar(tmp_path, monkeypatch, capsys):
    """A sidecar whose top-level JSON is a list must not crash SessionStart."""
    bad = tmp_path / ".memory-scores.json"
    bad.write_text("[]\n")
    monkeypatch.setattr(surface, "DEFAULT_SIDECAR", bad)
    assert surface.main([]) == 0
    assert capsys.readouterr().out == ""  # silent, no crash


def test_marker_is_idempotent(tmp_path):
    scores = _scored(tmp_path)
    loaded = mr.load_sidecar(scores, root=tmp_path)
    index = "- [Cont](m_cont.md) - x\n"
    once = surface.annotate_index(index, loaded)
    twice = surface.annotate_index(once, loaded)
    assert once == twice  # re-running never stacks markers
