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
`run_slot` and its three invariants were not touched.
"""
from __future__ import annotations


def gate_and_judge(post, *, channel, idea_text, voice_prov, arch_id, arch_entry,
                   runner, trail, at,
                   decide, revise, voicefp_gate,
                   prompt_carried_for, _append_voice_provenance,
                   claude_bin=None, model=None, author=None):
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
    verdict = decide.decide_candidate(
        post, regenerate=revise.reviser(runner=runner, claude_bin=claude_bin,
                                        model=model, author=author), channel=channel,
        source_text=idea_text, prompt_carried=prompt_carried_for(voice_prov),
        handles=False)
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
                                claude_bin=claude_bin, model=model, author=author)
        if not revised:
            break
        recheck = decide.decide_candidate(
            revised, regenerate=None, channel=channel,
            source_text=idea_text, prompt_carried=prompt_carried_for(voice_prov),
            handles=False)
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
    style_stage["fingerprint"] = voicefp_gate.drift_report(verdict.text,
                                                           authorship=True)
    trail["style"] = style_stage

    # The drift sidecar finally accumulates real rows on this lane (RC2): the
    # validation window sp-9aff1e67 has been waiting on since 2026-08-07 gets its
    # data from here. A record about the prompt, never a gate on it.
    _append_voice_provenance(channel, at, dict(
        voice_prov or {},
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
                        "repaired": bool(revisions)}))
    return verdict.text
