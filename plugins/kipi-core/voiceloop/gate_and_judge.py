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
`run_slot` and its three invariants were not touched.
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
    optional = {}
    if _accepts(decide.decide_candidate, "recent_openers"):
        optional["recent_openers"] = recent_openers
    verdict = decide.decide_candidate(
        post, regenerate=revise.reviser(runner=runner, claude_bin=claude_bin,
                                        model=model, author=author), channel=channel,
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
                                claude_bin=claude_bin, model=model, author=author)
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
        recheck = decide.decide_candidate(
            revised, regenerate=None, channel=channel,
            source_text=idea_text, prompt_carried=prompt_carried_for(voice_prov),
            recent_openers=recent_openers,
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
        path=provenance_path)
    return verdict.text
