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


# --- the injection boundary: a kwarg the other side may not have ------------------

def test_an_older_injected_decide_does_not_take_the_lane_down():
    """`decide` is the INSTANCE's, and instances upgrade independently.

    PR #386 round 3, major. `gate_and_judge` passed `recent_openers=` to
    `decide.decide_candidate` unconditionally. That parameter arrived 2026-09-09
    and the comment beside the call already recorded that fleet copies did not
    carry it. An instance on the older contract therefore raised TypeError on
    EVERY draft: the whole lane down, not a degraded feature.

    The fixture below is the older contract, verbatim: the same signature minus
    the one parameter. Before the fix this call raised; now it degrades.
    """
    from voiceloop import gate_and_judge

    def old_decide_candidate(text, regenerate=None, channel=None,
                             source_text=None, prompt_carried=None,
                             handles=True):
        return "reached"

    assert not gate_and_judge._accepts(old_decide_candidate, "recent_openers")

    def new_decide_candidate(text, regenerate=None, channel=None,
                             source_text=None, prompt_carried=None,
                             recent_openers=None, handles=True):
        return "reached"

    assert gate_and_judge._accepts(new_decide_candidate, "recent_openers")


def test_a_kwargs_callee_is_not_refused():
    """A callee taking **kwargs accepts anything; refusing it would break a
    working lane to satisfy an inspection."""
    from voiceloop import gate_and_judge

    def flexible(text, **kwargs):
        return "reached"

    assert gate_and_judge._accepts(flexible, "recent_openers")


def test_an_uninspectable_callee_assumes_the_newer_contract(monkeypatch):
    """Some callables refuse `inspect.signature` (C functions without a text
    signature, some wrappers). Assuming the OLDER contract there would silently
    drop a real do-not-repeat list on every draft, which is the quiet half of
    this defect rather than the loud one. Fail toward passing the argument.

    The BRANCH is exercised directly rather than by hunting a callable that
    happens to be uninspectable: the first version of this test used `len`,
    which modern Python inspects fine, so it asserted the opposite of what it
    claimed and failed on correct code.
    """
    import inspect
    from voiceloop import gate_and_judge

    def boom(*_a, **_k):
        raise ValueError("no signature available")

    monkeypatch.setattr(inspect, "signature", boom)

    def anything(text):
        return "reached"

    assert gate_and_judge._accepts(anything, "recent_openers"), (
        "an un-inspectable callee must be assumed to take the newer contract; "
        "assuming the older one drops the argument silently.")


def test_gate_and_judge_survives_an_OLD_injected_decide():
    """DRIVES the call site. RED if `recent_openers=` is passed unconditionally.

    The three tests above exercise `_accepts` and all of them stayed green with
    the guard removed from the call site, which made them decorative: they prove
    the helper answers correctly, never that the caller asks it. This one injects
    a `decide` on the OLDER contract -- the real fleet shape -- and asserts the
    lane reaches a verdict instead of raising TypeError.
    """
    import types
    from voiceloop import gate_and_judge as gj

    class _V:
        status = "SHIPPABLE"
        text = "the drafted post"
        reasons = []

    calls = {}

    def old_decide_candidate(text, regenerate=None, channel=None,
                             source_text=None, prompt_carried=None,
                             handles=True):
        # THE OLDER CONTRACT, verbatim: no `recent_openers`.
        calls["got"] = True
        return _V()

    decide = types.SimpleNamespace(decide_candidate=old_decide_candidate,
                                   SHIPPABLE="SHIPPABLE")
    revise = types.SimpleNamespace(reviser=lambda **_k: None,
                                   revise=lambda *a, **k: None)
    voicefp = types.SimpleNamespace(
        style_review=lambda *a, **k: {"verdict": "pass"},
        style_feedback=lambda *a, **k: "")
    trail = {"stages": []}

    try:
        gj.gate_and_judge(
            "the drafted post", channel="linkedin", idea_text="an idea",
            voice_prov={}, arch_id=None, arch_entry=None, runner=None,
            trail=trail, at=None,
            decide=decide, revise=revise, voicefp_gate=voicefp,
            prompt_carried_for=lambda _p: [],
            _append_voice_provenance=lambda *a, **k: None,
            recent_openers=["an opener"])
    except TypeError as exc:
        if "recent_openers" in str(exc):
            raise AssertionError(
                f"gate_and_judge passed recent_openers= to an injected decide "
                f"that does not take it: {exc}. `decide` lives in the INSTANCE "
                f"and upgrades independently, so this takes the whole lane down "
                f"on any instance still on the older contract.") from None
        raise
    except Exception:
        pass          # any OTHER failure is this fixture's thinness, not the defect

    assert calls.get("got"), "the fixture never reached decide_candidate"


def test_every_decide_call_site_is_guarded():
    """Read the call sites out of the module, never restate them here (ASK-1915,
    PR #386 round 4).

    Round 3 guarded ONE of the two `decide.decide_candidate` calls and left the
    style-revision one passing `recent_openers=` unconditionally, so the same
    TypeError still took the lane down on an instance with an older injected
    decide -- one branch over. The regression test written for it could not reach
    that branch, so 240 stayed green.

    A test that names the two sites would have the same blind spot the fix did.
    This one enumerates them from the AST, so adding a third unguarded site fails
    here without anyone remembering to update a list.
    """
    import ast
    import pathlib

    src = (pathlib.Path(__file__).resolve().parent.parent / "gate_and_judge.py").read_text()
    sites = [
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "decide_candidate"
    ]
    assert len(sites) >= 2, f"expected the known call sites, found {len(sites)}"
    for call in sites:
        named = {kw.arg for kw in call.keywords}
        # `None` is the arg name argparse-style **kwargs unpacking carries.
        unpacks_optional = any(
            kw.arg is None and isinstance(kw.value, ast.Name) and kw.value.id == "optional"
            for kw in call.keywords
        )
        assert "recent_openers" not in named, (
            f"line {call.lineno}: passes recent_openers= directly. It must travel "
            "in **optional, which _accepts() fills only when the injected callee "
            "takes it."
        )
        assert unpacks_optional, (
            f"line {call.lineno}: does not unpack **optional, so a future optional "
            "kwarg would reach an older injected decide unguarded."
        )


def test_no_optional_kwarg_reaches_an_INJECTED_callable_unguarded():
    """The class, not the instance (ASK-1915, PR #386 round 5).

    Three rounds patched three instances of one defect: an optional kwarg passed
    to a callable the ENGINE DOES NOT OWN, which TypeErrors on any instance whose
    injected copy predates the kwarg. r3 `recent_openers` at one decide site, r4
    the same kwarg at the second site, r5 `path` on `_append_voice_provenance`.
    Each fix was correct and too narrow, including the AST test written at r4,
    which named `decide_candidate` and therefore could not see r5.

    So the injected names are DERIVED from `run`'s own signature rather than
    listed here. Add a fourth injected dependency and pass it an optional kwarg
    directly, and this fails without anyone remembering to update a list.
    """
    import ast
    import pathlib

    mod = pathlib.Path(__file__).resolve().parent.parent / "gate_and_judge.py"
    tree = ast.parse(mod.read_text())
    # Find the entry point by what it TAKES, not by its name. Guessing the name
    # was this test's own first bug, which is the mistake it exists to prevent.
    run = next(n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)
               and "_append_voice_provenance" in
               {a.arg for a in n.args.args + n.args.kwonlyargs})

    # Everything the entry point is HANDED is owned by the instance, not us.
    injected = {a.arg for a in run.args.args + run.args.kwonlyargs}
    injected -= {"channel", "post", "idea_text", "trail", "at", "revised"}
    assert {"decide", "_append_voice_provenance"} <= injected, injected

    offenders = []
    for n in ast.walk(run):
        if not isinstance(n, ast.Call):
            continue
        name = (n.func.value.id if isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name) else
                n.func.id if isinstance(n.func, ast.Name) else None)
        if name not in injected:
            continue
        direct = [k.arg for k in n.keywords if k.arg]
        # A kwarg the ENGINE added is optional at the boundary; the callee may
        # predate it. Anything routed through ** has already met `_accepts`.
        risky = [k for k in direct if k in {"recent_openers", "path"}]
        if risky:
            offenders.append(f"line {n.lineno}: {name}(... {', '.join(risky)}=)")

    assert not offenders, (
        "an optional kwarg reaches an injected callable directly instead of "
        "through the **optional dict that _accepts() fills:\n  "
        + "\n  ".join(offenders))


def test_an_OLD_injected_provenance_writer_does_not_take_the_lane_down():
    """The second injected callee gets the same old-contract fixture (ASK-1915,
    PR #386 round 6).

    `decide` had one and `_append_voice_provenance` did not, and that asymmetry
    was the whole gap: a new optional kwarg planted at the decide site is caught
    by execution, the same kwarg at the provenance site was not. Measured on this
    branch before the fixture existed: 1 failed / 241 versus 242 green.

    NO KWARG NAME APPEARS IN THIS TEST. The r5 attempt restated
    {recent_openers, path} and therefore could not see a fourth; this one injects
    a callee on a STRICT older signature and lets Python raise. Whatever the
    engine adds next, an unguarded pass raises TypeError here and fails by
    execution rather than by recognition.
    """
    import types
    from voiceloop import gate_and_judge as gj

    class _V:
        status = "SHIPPABLE"
        text = "the drafted post"
        reasons = []

    seen = {}

    def old_append_voice_provenance(channel, at, row):
        # THE OLDER CONTRACT: positional only, and no `path`. A strict signature
        # is the point -- **kwargs here would accept anything and prove nothing.
        seen["got"] = True

    decide = types.SimpleNamespace(
        decide_candidate=lambda *a, **k: _V(), SHIPPABLE="SHIPPABLE")
    revise = types.SimpleNamespace(reviser=lambda **_k: None,
                                   revise=lambda *a, **k: None)
    voicefp = types.SimpleNamespace(
        style_review=lambda *a, **k: {"verdict": "pass"},
        style_feedback=lambda *a, **k: "",
        drift_report=lambda *a, **k: {})
    trail = {"stages": []}

    try:
        gj.gate_and_judge(
            "the drafted post", channel="linkedin", idea_text="an idea",
            voice_prov={}, arch_id=None, arch_entry=None, runner=None,
            trail=trail, at=None,
            decide=decide, revise=revise, voicefp_gate=voicefp,
            prompt_carried_for=lambda _p: [],
            _append_voice_provenance=old_append_voice_provenance,
            provenance_path="/tmp/ignored")
    except TypeError as exc:
        if "unexpected keyword argument" in str(exc):
            raise AssertionError(
                f"gate_and_judge passed a keyword to an injected provenance "
                f"writer that does not take it: {exc}. That callee lives in the "
                f"INSTANCE and upgrades independently, so an unguarded kwarg "
                f"takes the lane down on every instance still on the older "
                f"contract. Route it through _accepts() like the decide site."
            ) from None
        raise
    except Exception:
        pass          # any OTHER failure is this fixture's thinness, not the defect

    assert seen.get("got"), "the fixture never reached the provenance writer"
