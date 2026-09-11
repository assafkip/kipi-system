#!/usr/bin/env python3
"""Every module this package ships is named here and is imported by the gate.

WHY THIS EXISTS (PR #311 review, MAJOR, 2026-09-06). The engine was carried into
the skeleton 14 .py -> 43 and the registered suite reported "194 passed". The
reviewer then DELETED 15 of the carried modules and the suite stayed green,
because `voiceloop/tests/` only ever imports about half the package: the deep
coverage for critic, revise, x_format, archetype and ten others lives in the
operator instance's own pipeline test tree, which the skeleton cannot run and
should not carry. So the number proved something true about 19 modules and
nothing at all about the port.

(That sentence originally named the instance's test directory by path. The
founder-data guard in this same directory rejected it on the first run, which is
the guard behaving correctly: an instance path is one of the fact classes it
exists to keep out of a public tree. Name the data class, never the location.)

Two numbers produced by the same blind suite agreed with each other, which is
exactly why nobody noticed. A count is not coverage.

WHAT THIS IS AND IS NOT. It is a SURFACE gate: it proves each module exists and
imports cleanly, so a deletion, a syntax error, a circular import or a missing
dependency is RED here rather than at some instance's next sync. It is NOT a
behaviour suite and does not pretend to be. Behaviour lives instance-side.

THE ONE THING IT MUST NOT BECOME. An earlier draft walked the directory and
imported whatever it found. That version passes happily after a deletion,
because a deleted file is simply not enumerated, so the very mutation this gate
exists to catch would have been invisible. The list below is therefore a
LITERAL manifest, and the check runs in BOTH directions:

  manifest -> disk   a module named here that is gone fails to import  (deletion)
  disk -> manifest   a module on disk that is not named here fails     (drift)

Adding a module to the package means adding one line here. That cost is the
point: it is the same declared-vs-actual shape the capability gate uses.
"""
import importlib
import os

import pytest

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The 33 shipped modules, excluding __init__. Keep sorted; one line per module.
EXPECTED_MODULES = (
    "archetype",
    "assemble",
    "assistant_gate",
    "channel_registry",
    "content_key",
    "corpus",
    "critic",
    "echo",
    "ending_gate",
    "experience",
    "experience_bench",
    "figure_gate",
    "fingerprint",
    "form",
    "gate_and_judge",
    "gate_walk",
    "luar_env_backend",
    "luar_scorer",
    "opener_gate",
    "placeholder_gate",
    "post_repair",
    "prompt_render",
    "reply_format",
    "revise",
    "sameness",
    "selector",
    "slop_shapes",
    "source_shape",
    "substance_gate",
    "validate",
    "voice_ref",
    "voicefp_rules",
    "x_format",
)


def _modules_on_disk():
    return {
        f[:-3]
        for f in os.listdir(PKG_DIR)
        if f.endswith(".py") and f != "__init__.py"
    }


@pytest.mark.parametrize("name", EXPECTED_MODULES)
def test_every_shipped_module_imports(name):
    """Direction 1: the manifest drives it, so a DELETED module is red here.

    This is the direction the reviewer's mutation exercised. Because the name
    comes from the tuple above and not from a directory walk, removing the file
    turns this into an ImportError instead of a quietly shorter test run.
    """
    importlib.import_module(f"voiceloop.{name}")


def test_no_module_on_disk_is_unregistered():
    """Direction 2: a module added without a manifest line is red.

    Without this, the manifest rots the moment someone adds a file, and a gate
    that silently stops covering new code reads exactly like one that works.
    """
    unregistered = sorted(_modules_on_disk() - set(EXPECTED_MODULES))
    assert not unregistered, (
        "these modules ship but are not named in EXPECTED_MODULES, so nothing "
        "imports them: %s" % ", ".join(unregistered)
    )


def test_the_manifest_is_not_empty_and_matches_disk():
    """Vacuous-pass guard, derived rather than pinned to a literal.

    A floor like `>= 7` against a 33-module package would pass while covering
    almost nothing (PR #311 review, NIT). Comparing the two sets is the honest
    version: it cannot be satisfied by a truncated walk.
    """
    assert set(EXPECTED_MODULES) == _modules_on_disk()
