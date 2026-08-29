#!/usr/bin/env python3
"""The METHOD/DATA boundary, held by a test and not a comment.

Founder-decided split (voice-architecture PRD, 2026-08-06): the plugin ships the
machinery fleet-wide; Assaf's corpus stays in his instance (`q-consult/voice/`).
kipi-system is a PUBLIC repo, so a corpus line leaking into this tree is not just
architecture drift, it is founder data published to the world.

The check greps the voicekit tree for distinctive fingerprints of the private
corpus: phrases from his real writing, his instance paths, and personal
identifiers. Distinctive-but-harmless probes, chosen so the test itself does not
become the leak it polices (the public-skeleton rule: name the data class, never
quote the data at length).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Fingerprints of the PRIVATE side. Short, distinctive, non-sensitive probes.
FORBIDDEN = (
    "q-consult",                 # his instance's content dir
    "askconsulting",             # his business
    "pig butchering",            # his corpus subject matter
    "whac-a-mole",               # his coined metric name
    "60 muscles",                # his known post
    "Kipnis",                    # the founder
)


def _tree_files():
    out = []
    for root, dirs, files in os.walk(PKG):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        out.extend(os.path.join(root, f) for f in files
                   if f.endswith((".py", ".json", ".jsonl", ".md")))
    return out


def test_the_tree_has_files_to_check():
    """Vacuous-pass guard: if the walk breaks, this fails before the grep lies."""
    assert len(_tree_files()) >= 7


def test_no_founder_data_in_the_plugin_tree():
    here = os.path.abspath(__file__)
    for path in _tree_files():
        if os.path.abspath(path) == here:
            continue                     # the probe list itself lives here
        with open(path, encoding="utf-8", errors="replace") as handle:
            content = handle.read().lower()
        for needle in FORBIDDEN:
            assert needle.lower() not in content, (
                f"{os.path.relpath(path, PKG)} contains {needle!r}: founder data "
                f"or an instance path is inside the fleet plugin. The corpus "
                f"lives in the instance's voice/ dir, never here.")


def test_negative_selftest_the_probe_detects_a_planted_leak(tmp_path):
    """Prove the predicate catches the thing it exists to catch."""
    planted = tmp_path / "leak.md"
    planted.write_text("notes on the pig butchering analysis")
    with open(planted, encoding="utf-8") as handle:
        content = handle.read().lower()
    assert any(n.lower() in content for n in FORBIDDEN)
