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


# --- the targets declaration: what the ENGINE can state on its own -----------------
#
# PR #386 round 2 flagged a citation in validate._targets_for pointing at
# `test_voice_reach.py`, which lives in the consuming repo and does not travel
# with this package. Second occurrence of that class, so the fix is structural
# rather than another reworded comment: the COMPLETENESS half genuinely cannot
# live here (it resolves instance modules this engine has never heard of), and
# the CONSEQUENCE half can. These two pin the consequence.

def _corpus(tmp_path, lengths, channel="linkedin", kind="post"):
    import json
    d = tmp_path / "voice"
    d.mkdir()
    with open(d / "exemplars.jsonl", "w", encoding="utf-8") as h:
        for i, n in enumerate(lengths):
            h.write(json.dumps({"id": f"r-{i:03d}", "channel": channel,
                                "kind": kind, "words": n,
                                "text": " ".join(["w"] * n)}) + "\n")
    return str(d)


def test_check_budget_grades_the_LONGEST_end_not_the_shortest(tmp_path):
    """DRIVES check_budget. Goes RED if its fallback reverts to the floor.

    The first version of this test called `_targets_for(..., extreme=max)`
    directly and passed with `check_budget`'s call site reverted, which made it
    decorative: it asserted the helper can be asked for the ceiling, never that
    the ceiling is what the gate asks for. Reverting the call site is the whole
    mutation and the test could not see it.

    The corpus below is built so the two ends straddle the budget: the short
    register assembles well under it and the long register over it. A gate
    enumerating the floor returns clean on a corpus that really does overflow.

    Measured on the live ASK corpus when this was found: floor fallback reported
    20944 as linkedin's worst, reachable worst was 23915, ceiling 24000.
    """
    from voiceloop import assemble, corpus, validate, channel_registry

    # INTERLEAVED, and that is what makes the two ends distinguishable at all.
    # The fallback is (None, extreme(...)), so None is enumerated either way --
    # and at None `select` takes k consecutive by offset, which on a corpus with
    # the long rows GROUPED lands on four of them and finds the overflow without
    # help. Two earlier fixtures failed for exactly that reason: they proved the
    # gate catches an overflow, never that it catches THIS one.
    #
    # Alternating short/long means no four consecutive rows are all long, so the
    # None arm tops out around two long rows, while a ceiling target ranks by
    # nearness and selects the four longest together. Only the ceiling arm
    # crosses the budget.
    #
    # Sized from the helper, not guessed: `_corpus` writes each word as "w", so a
    # row of n words is 2n-1 chars and k=4 selection needs > BUDGET_CHARS/4 per
    # row. A previous version assumed "~7 chars per word" and built rows a tenth
    # of the size needed.
    long_words = (assemble.BUDGET_CHARS // 4) // 2 + 400
    lengths = []
    for _ in range(8):
        lengths += [20, long_words]
    d = _corpus(tmp_path, lengths)
    voice = corpus.load(d)
    chans = channel_registry.DEFAULT
    problems = validate.check_budget(voice, chans)
    assert any("budget" in p for p in problems), (
        f"check_budget returned {problems} on a corpus whose longest register "
        f"assembles past {assemble.BUDGET_CHARS}. It is enumerating the floor, "
        f"so the ceiling it claims to grade is never reached.")


def test_an_undeclared_channel_falls_back_rather_than_going_ungraded(tmp_path):
    """A declaration that omits a channel must not silently disable the gate.

    The instance-side completeness test is what stops a lane being omitted in the
    first place; this pins what happens if one slips through anyway. `_targets_for`
    returns the corpus-derived fallback for an undeclared channel, never an empty
    list, because an empty list means the enumeration loop body never runs.
    """
    from voiceloop import corpus, validate, selector
    d = _corpus(tmp_path, [40] * 10)
    voice = corpus.load(d)
    base = selector.resolved_pool(voice.active_exemplars(), "linkedin",
                                  "post", selector.DEFAULT_K)
    got = validate._targets_for("linkedin", base, {"x": [40]}, extreme=max)
    assert got, ("an undeclared channel returned an empty target list, so its "
                 "grading loop never runs and the gate is off for it.")
