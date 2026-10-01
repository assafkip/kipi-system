#!/usr/bin/env python3
"""The gate-and-judge loop: run the stack, judge the style, revise, re-gate.

why this is ENGINE code (2026-09-05, VoiceLoop package extraction, slice 12). The
LOOP is the method. Gate the body, ask the style judge, hand the named violations to
a reviser, re-gate what comes back, and stop when it is clean or the budget is spent.
Every operator wants that shape. What differs between operators is WHICH gates, WHICH
judge and WHICH reviser, and none of those live here.

why the five dependencies are injected rather than imported. `decide` carries the ASK
roster, including a commercial price rule and a two-brand separation rule. Importing
it here would drag one practice's rules into the fleet package, which is the thing
this extraction exists to stop. So `decide`, `revise`, `voicefp_gate`,
`prompt_carried_for` and `_append_voice_provenance` arrive as keyword-only arguments.
`recent_openers` (2026-09-09) is the do-not-repeat list handed to BOTH
`decide_candidate` sites; `provenance_path` isolates the provenance sidecar the way
the ledger path already isolates the corpus. Both default to None and both are
documented here rather than only in the body, matching the slice-6b paragraph above.

`claude_bin`, `model` and `author` joined them on 2026-09-06 (slice 6b), when `revise`
moved into the package. The reviser shells a binary, names a tier and tells the model
whose voice to keep, and all three are the operator's: a default here would be one
machine's path, one operator's model choice and one operator's NAME shipped fleet-wide.
The exporter refuses an engine file carrying that name, which is how the third one was
found. They are threaded rather than bound on a shim because `pipeline.revise` has
to stay a plain `sys.modules` alias -- `reviser()`'s closure and the suite's
`monkeypatch.setattr(revise, "revise", ...)` must resolve to the SAME module object.

why they keep their original NAMES. The body below is byte-identical to the function
it was lifted from: 140 lines that decide when a post is finished, on the publishing
path, with a documented reason behind most of them. Renaming the references to
something tidier would have meant editing every one of those lines, and a diff where
every line moved is a diff nobody can review. The parameters are named `decide` and
`revise` because the code says `decide.decide_candidate` and `revise.reviser`, and
that is worth more than a naming convention.

The deployment's `cycle._gate_and_judge` binds the five and calls through, so
`run_slot` and its three invariants were not touched. That binder is the OTHER
half of the injection boundary and it lives in a repo this package cannot see, so
the guard below is exported as `gated_kwargs` (ASK-1937): a binder threading a
kwarg of its own imports that name rather than writing a second copy of the
check, which is where the two halves would drift.
"""
from __future__ import annotations

# The only import in this module, and it is a PACKAGE one: the five
# operator-specific dependencies stay injected (see the docstring). A sha
# function carries no operator's rules, and the alternative was making the
# caller pass the same one-line call as a sixth keyword argument.
from . import content_key



def _accepts(fn, name):
    """Does this INJECTED callable take `name`?

    The injection boundary is the reason this exists. Every symbol this module
    receives as an argument (`decide`, `revise`, `voicefp_gate`) is the
    instance's, and instances upgrade independently of this package. A keyword
    that is optional HERE is mandatory at the call site, so sending one the
    other side has never heard of is a TypeError on a live lane.

    Returns True for a callable that takes **kwargs, because such a callee
    accepts anything and inspecting further would refuse a lane that works.
    """
    import inspect
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return True            # un-inspectable: assume the newer contract
    for param in sig.parameters.values():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            return True
    return name in sig.parameters


class FatalKwargDropped(RuntimeError):
    """An injected callee predates a kwarg whose LOSS is not survivable.

    Raised by `_gated`, never by a callee. It names the callee and the kwarg,
    because the operator's next move is upgrading that one injected copy.
    """


# WHAT LOSING EACH KWARG COSTS (ASK-1938). Degrading quietly is right for
# `recent_openers`: the lane loses a do-not-repeat check and keeps writing. It
# is wrong for `path`, because the instance's provenance writer FALLS BACK to
# the production corpus -- so a caller that explicitly asked for isolation
# appends fixture rows to the file the operator's style-drift analysis is
# measured from. That is the r5 defect (8 rows per run of one test file, with
# fabricated `draft_sha` values) arriving through the degradation path instead
# of the call path.
#
# THE ASYMMETRY IS THE POINT. Before r5 an older writer raised TypeError: loud,
# and the lane stopped. After it, the same instance writes production in
# silence. Trading a crash for silent corruption of the measurement corpus is a
# bad trade in this one case, and a good one for `recent_openers`, so the
# disposition is per pair rather than a property of `_gated`.
#
# UNDECLARED IS NOT FATAL AT RUNTIME, deliberately. Raising on a pair nobody
# added a row for would take a live lane down for a forgotten table entry. The
# pairs are read out of this module's AST by
# `test_every_gated_kwarg_has_a_declared_disposition`, so an undeclared kwarg is
# red at build time -- the layer that can afford to fail closed -- and merely
# recorded here.
_DROP_DISPOSITION = {
    ("decide.decide_candidate", "recent_openers"): "tolerable",
    ("revise.reviser", "claude_bin"): "tolerable",
    ("revise.reviser", "model"): "tolerable",
    ("revise.reviser", "author"): "tolerable",
    ("revise.revise", "claude_bin"): "tolerable",
    ("revise.revise", "model"): "tolerable",
    ("revise.revise", "author"): "tolerable",
    ("voicefp_gate.drift_report", "authorship"): "tolerable",
    ("_append_voice_provenance", "path"): "fatal",
}


def gated_kwargs(fn, label, trail, **maybe):
    """Keep only the kwargs this INJECTED callable actually takes, and SAY SO.

    PUBLIC, and that is the point of the name (ASK-1937). Both sides of the
    injection boundary need this check: the engine half is below, and the
    instance's binder threads its own kwargs through the same door by importing
    `from voiceloop.gate_and_judge import gated_kwargs`. Under the old private
    name a binder's only options were reaching past an underscore or writing its
    own copy, and a second copy is where a cross-repo contract drifts.

    THE CHOKEPOINT (RCA 2026-09-20, after PR #386 rounds 3 through 6 patched the
    same class four times). Rounds 3, 4 and 5 each guarded one kwarg at one site
    with its own `if _accepts(...)` block, and round 6 found the round-5 TEST
    restating `{"recent_openers", "path"}` -- a set that cannot name a kwarg
    nobody has written yet. Measured the same day: a NEW kwarg planted at five of
    the six injected call sites was caught by nothing, including the site round 4
    was written for.

    One door instead of five blocks. Everything optional that crosses the
    injection boundary goes through here, so the suite has one thing to watch and
    a new kwarg cannot arrive by a route the guard does not cover.

    A DROP WAS INVISIBLE UNTIL ASK-1938. The door kept the lane alive and told
    nobody which half of it stopped working, so every drop now leaves a row in
    `trail["dropped_kwargs"]` naming the callee and the kwarg, and a drop the
    table calls fatal refuses instead.

    `label` is the callee's name AS WRITTEN AT THE CALL SITE, not read off the
    object: an instance may inject a lambda, a partial or a bound method, and
    `__name__` on any of those would put a useless string in the trail and miss
    the disposition row.
    """
    keep, dropped = {}, []
    for k, v in maybe.items():
        if _accepts(fn, k):
            keep[k] = v
            continue
        disposition = _DROP_DISPOSITION.get((label, k), "undeclared")
        # A FATAL KWARG WHOSE VALUE IS None STILL DEGRADES. None means the
        # caller never asked for the non-default behaviour, so the callee's
        # fallback is what it wanted anyway. Refusing there would take the lane
        # down on every non-isolating caller with an older callee and buy no
        # safety at all -- a worse trade than the one this table exists to fix.
        fatal = disposition == "fatal" and v is not None
        dropped.append({"callee": label, "kwarg": k,
                        "disposition": disposition,
                        "value_was_none": v is None,
                        "refused": fatal})
        if fatal:
            _record_drops(trail, dropped)
            raise FatalKwargDropped(
                f"{label}() does not take `{k}`, and losing it is not "
                f"survivable: the callee falls back to a default the caller "
                f"explicitly asked it not to use. Upgrade that injected copy, "
                f"or pass {k}=None to accept the default on purpose.")
    _record_drops(trail, dropped)
    return keep


# THE BACK-COMPAT ALIAS, and it is what the six call sites below still say. The
# rename is a one-line export, not a six-line sweep through a body whose
# reviewability is the reason nothing in this module was ever renamed (see the
# `why they keep their original NAMES` paragraph in the module docstring).
# `test_the_boundary_guard_is_a_PUBLIC_symbol_a_binder_can_import` pins the two
# names to ONE function object, so a caller on either is running the same check.
_gated = gated_kwargs


def _record_drops(trail, dropped):
    """One writer for the degradation record, so a refusal and a tolerated drop
    cannot land in the trail two different shapes.

    Tolerant of a `trail` that is not a dict: this is observability, and an
    engine that crashes writing its own diagnostic is worse than one that is
    quiet. The refusal above is raised whether or not this succeeds.
    """
    if not dropped or not isinstance(trail, dict):
        return
    trail.setdefault("dropped_kwargs", []).extend(dropped)


def gate_and_judge(post, *, channel, idea_text, voice_prov, arch_id, arch_entry,
                   runner, trail, at,
                   decide, revise, voicefp_gate,
                   prompt_carried_for, _append_voice_provenance,
                   claude_bin=None, model=None, author=None,
                   recent_openers=None, provenance_path=None):
    """The deterministic stack plus the style judge, on ONE body. Returns the final
    text or None, and writes the `gates` stage, the `style` block and the provenance
    row into `trail`.

    why this is a function (2026-09-02, founder-directed: "ensure that all tests that
    run on x and linkedin run here. The mechanism needs to be mirrored"): the reddit
    lane was built as its own contract and ran NONE of this -- not `bio_gate`, not
    `ending_gate`, not `figure_gate`, not `assistant_gate`, not the style loop, not the
    fingerprint -- because the PRD non-goal that correctly barred X's FORMAT gates from
    reddit was read as barring the whole stack (sp-d1ed4469). The body of this helper
    is `draft_from_idea`'s own, moved verbatim; the lane that wrote posts and the lane
    that writes reddit now call the same code, so a gate added here reaches both. A
    second copy is where the reddit copy would have drifted again.

    Channel-coupled gates stay channel-coupled INSIDE the stack: `x_format` is silent
    off x, `substance_gate` reads its floor per channel. Nothing here is skipped by
    channel; the stack skips itself where a rule does not apply.
    """
    # BOTH DECISION SITES GET THE REPEAT LIST, and the second one is the point
    # (2026-09-09). `decide` runs an opener-echo check whose whole
    # input is this list, so until it was threaded here the check ran against []
    # and could never fire on any lane. It was green the entire time, because the
    # only test of it built the list by hand and called the checker directly.
    #
    # KEYWORD WITH A None DEFAULT, deliberately: this module serves more than one
    # lane, so a required argument would break a caller with no list to give. None
    # means no repeat check, which is exactly today's behaviour for anyone who does
    # not pass one. Measured in this repo: two callers, and the reddit one passes
    # nothing, so the default is load-bearing rather than theoretical.
    #
    # AN EARLIER VERSION OF THIS COMMENT SAID "ships fleet-wide to every instance"
    # and used that as the reason. Measured 2026-09-09: the fleet copies did not
    # carry `recent_openers` at all and only this repo's copy had the fix, so
    # propagation ran the other way from what the comment claimed. The design choice
    # stands; the justification did not, and a reason nobody checked is how the next
    # reader inherits a false premise. NO COUNTS ARE QUOTED HERE ON PURPOSE: a census
    # of copies inverts on the first fleet sync and would then be a second false
    # premise wearing a measurement's clothes.
    # FEATURE-DETECTED, NOT ASSUMED (PR #386 round 3, major). `decide` is
    # INJECTED: it lives in the instance, not in this package, so this module
    # cannot know which version it is calling. Passing `recent_openers=`
    # unconditionally raises TypeError on every draft in any instance whose
    # `decide_candidate` predates that parameter -- the whole lane down, not a
    # degraded feature.
    #
    # The comment above already recorded (2026-09-09) that fleet copies did NOT
    # carry `recent_openers` and only this repo's did, so the hazard was known
    # and the call site still assumed. Measured 2026-09-20: all 15 decide.py
    # copies on the author's machine accept it and all 15 are one instance's, so
    # the blast radius is zero TODAY. That is a fact about today, not a property
    # of the design, and it inverts the first time another instance grows the
    # lane. A kwarg passed across an injection boundary needs a check, not a
    # census.
    #
    # Asking the signature is the check. It degrades to the older contract
    # instead of dying, and `_accepts` is used for every optional kwarg crossing
    # this boundary rather than this one, so the next one added cannot
    # reintroduce the same defect by being written the old way.
    optional = _gated(decide.decide_candidate, "decide.decide_candidate", trail,
                      recent_openers=recent_openers)
    verdict = decide.decide_candidate(
        post, regenerate=revise.reviser(runner=runner,
                                        **_gated(revise.reviser,
                                                 "revise.reviser", trail,
                                                 claude_bin=claude_bin,
                                                 model=model, author=author)),
        channel=channel,
        source_text=idea_text, prompt_carried=prompt_carried_for(voice_prov),
        handles=False, **optional)
    trail["stages"].append({"stage": "gates", "status": verdict.status,
                            "reasons": list(verdict.reasons or [])})
    if verdict.status != decide.SHIPPABLE:
        # The style loop below needs a SHIPPABLE body to measure, so the refusal
        # returns first and the trail says the review never ran. `unchecked` is
        # derived from this status, so a refused draft still carries an honest one.
        trail["style"] = {
            "status": "not_run",
            "reason": "refused by the deterministic gates before the style review",
        }
        return None

    # THE STYLE LOOP (2026-08-24, RCA-voice-enforcement RC2/RC3/RC4; landed here
    # 2026-08-31 from the stranded fix/restatement branch, which could not push).
    #
    # Until this ran, this lane had no positive voice judge at all: the 14 gates in
    # `decide._violations` are every one of them NEGATIVE checks, so a draft could sit
    # farther from his voice than anything he ever wrote and still hand itself to him
    # as clean. That is the whole finding of
    # rca-idea-lane-still-has-no-voice-judge-2026-08-26, and the binary fingerprint
    # bounds could not close it either: they ask "did he EVER write like this" and
    # generation is anchored on his own exemplars, so the answer is almost always yes.
    #
    # `style_review` measures multi-axis distance in units of HIS OWN spread against
    # thresholds derived from his corpus (`pipeline.voice style-calibrate`). A HOLD
    # becomes named revision feedback through the SAME reviser every other gate uses,
    # bounded at two attempts, and each attempt is RE-GATED so a style fix can never
    # sneak a body past the deterministic stack. WATCH never repairs: measured on his
    # own X posts, roughly a third sit there naturally, and repairing those would be
    # the gate rewriting his voice rather than checking it.
    #
    # THIS IS NOT THE CRITIC. Removing the critic from this lane was founder-directed
    # 2026-08-13 (quotes at the top of this function) and it stays removed.
    #
    # Archetype-claimed axes are ANNOTATED, never escalated: a shape the archetype
    # asked for is visible in the flags without counting as a violation.
    arch_claims = (arch_entry or {}).get("style_claims") or []
    review = voicefp_gate.style_review(verdict.text, arch_claims)
    style_stage = {"before_level": review.get("level"),
                   "before_distance": review.get("distance"),
                   "flags": review.get("flags") or []}
    revisions = 0
    while review.get("level") == "hold" and revisions < 2:
        feedback = voicefp_gate.style_feedback(review)
        if not feedback:
            break
        revised = revise.revise(verdict.text, feedback, runner=runner,
                                **_gated(revise.revise, "revise.revise", trail,
                                         claude_bin=claude_bin,
                                         model=model, author=author))
        if not revised:
            break
        # THE RE-CHECK DETECTS; ONLY THE FIRST PASS REJECTS. A style revision is the
        # moment the writer is most likely to reproduce an opening it has already
        # used, so wiring only the call above would leave the revision path blind.
        #
        # Say the consequence exactly, because an earlier version of this comment
        # said the re-check "needs it more" and that overstated what happens here
        # (adversarial review 2026-09-09). A refusal below lands on
        # `style_stage[...] = "refused-by-gates"` and `continue`, which discards the
        # REVISION and keeps the already-SHIPPABLE `verdict` from the first pass. So
        # this site can stop a bad rewrite from replacing a good body; it cannot
        # reject the draft. The site above is the only one that can.
        # THE SECOND CALL SITE, and it was missed once (claude review of PR #386
        # round 4). Round 3 guarded the site above and left this one passing
        # `recent_openers=` unconditionally, so an instance on the older injected
        # contract still died -- on the style-revision path instead of the first
        # one. Same TypeError, one branch over. `test_every_decide_call_site_is_
        # guarded` now reads the call sites out of this module's AST rather than
        # naming them, so a third site cannot be added unguarded.
        recheck = decide.decide_candidate(
            revised, regenerate=None, channel=channel,
            source_text=idea_text, prompt_carried=prompt_carried_for(voice_prov),
            handles=False, **optional)
        revisions += 1
        if recheck.status != decide.SHIPPABLE:
            style_stage[f"attempt{revisions}"] = "refused-by-gates"
            continue
        next_review = voicefp_gate.style_review(recheck.text, arch_claims)
        if next_review.get("distance", 1e9) < review.get("distance", 1e9):
            verdict, review = recheck, next_review
            style_stage[f"attempt{revisions}"] = {
                "level": next_review.get("level"),
                "distance": next_review.get("distance")}
            if review.get("level") != "hold":
                break
        else:
            # A revision that did not move closer is DISCARDED, not shipped. The
            # original stands and the trail says why, so "we tried and it did not
            # help" is readable rather than inferred from an unchanged body.
            style_stage[f"attempt{revisions}"] = "no-improvement"
            break
    style_stage["after_level"] = review.get("level")
    style_stage["after_distance"] = review.get("distance")
    style_stage["revisions"] = revisions
    # `status` is what the route receipt reads to decide `unchecked`. It stops being
    # the constant "not_run" here, which is the whole point of the landing: a judged
    # draft must be able to say so, and an unjudged one must still say THAT.
    #
    # DERIVED FROM THE VERDICT, never hardcoded "reviewed". `style_review` fails OPEN
    # on missing or stale thresholds (level "unavailable"), which is right -- a
    # thresholds file naming another corpus must not judge -- but a receipt that
    # reports `unchecked: []` off a review that could not run is the exact defect
    # this landing exists to close, rebuilt one layer up. Seen in a real run 2026-08-31:
    # the branch's thresholds named corpus c4737fe2 and this corpus is a0e60f87,
    # so every draft came back "unavailable" and every receipt said judged.
    style_stage["status"] = (
        "not_run" if review.get("level") in {"unavailable", "error", None}
        else "reviewed")
    if style_stage["status"] == "not_run":
        style_stage["reason"] = review.get("detail") or "style review unavailable"
    # AUTHORSHIP IS ON (founder-directed 2026-08-31, verbatim: "WE always call for
    # it"). It had been defaulted OFF by codex finding-4 on
    # prd-voice-authorship-scoring-2026-08-17, resolved eleven minutes after it was
    # raised, by an agent; `decisions.md` has no entry and he was never asked. Read
    # off the FINAL body, so a repaired draft reports the score of what he will see.
    style_stage["fingerprint"] = voicefp_gate.drift_report(
        verdict.text, **_gated(voicefp_gate.drift_report,
                               "voicefp_gate.drift_report", trail,
                               authorship=True))
    trail["style"] = style_stage

    # The drift sidecar finally accumulates real rows on this lane (RC2): the
    # validation window sp-9aff1e67 has been waiting on since 2026-08-07 gets its
    # data from here. A record about the prompt, never a gate on it.
    # THE THIRD INSTANCE OF ONE CLASS (claude review of PR #386 round 5). Round 3
    # guarded `recent_openers` at one decide call site, round 4 at the second, and
    # this was the same TypeError again with a different kwarg on a different
    # INJECTED callable: `_append_voice_provenance` arrives keyword-only at line 76,
    # so an instance whose copy predates `path` died here. Patching the instance a
    # third time is what the founder's five-rounds-is-a-loop scar is about, so the
    # test below now derives the injected names from THIS function's own signature
    # instead of naming `decide_candidate`.
    prov_optional = _gated(_append_voice_provenance, "_append_voice_provenance",
                           trail, path=provenance_path)
    _append_voice_provenance(channel, at, dict(
        voice_prov or {},
        # THE JOIN KEY (2026-09-08). Without it this lane's rows carry a style
        # distance and an authorship score attributable to no draft, which is what
        # made 1,085 accumulated rows unjoinable to any outcome. Computed on the
        # text that actually won, with the same `content_key.text_sha` the critic
        # writes, so the two artifacts meet on one key.
        draft_sha=(content_key.text_sha(verdict.text)
                   if isinstance(verdict.text, str) else None),
        # The fingerprint was computed eleven lines up and then thrown away here:
        # this lane's `advisory_drift` is hand-built from the STYLE review, which
        # has no authorship in it. Naming the fingerprint is what puts the score on
        # disk for the founder-idea lane (ASK-1244).
        fingerprint=style_stage.get("fingerprint"),
        advisory_drift={"level": review.get("level"),
                        "distance": review.get("distance"),
                        "hold_distance": review.get("hold_distance"),
                        "zscores": review.get("zscores") or {},
                        "archetype": arch_id,
                        "style_claims": arch_claims,
                        "repaired": bool(revisions)}),
        # ISOLABLE, and it was not (standard review 2026-09-09, finding 3). The
        # instance's writer already derives a sidecar beside a caller-supplied
        # ledger and falls back to the production path otherwise; this call passed
        # nothing, so EVERY test that reaches this line appended a fixture body's
        # provenance to the live 3MB `voice-provenance.jsonl`. Measured before the
        # fix: 8 rows per run of one test file. That file is the corpus the operator's
        # style-drift analysis is measured from, so fixture rows with fabricated
        # `draft_sha` values join straight into it, and gitignore keeps them out of
        # version control rather than out of the number.
        #
        # The same derivation the corpus capture already gets, for the reason recorded
        # there: a caller that isolates its ledger to a temp dir and still reads the
        # PRODUCTION corpus is a defect this package has paid for before.
        **prov_optional)
    return verdict.text
