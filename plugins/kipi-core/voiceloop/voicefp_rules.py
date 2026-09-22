#!/usr/bin/env python3
"""ECHO AND FINGERPRINT TIERING: given what the engines found, what does it mean?

why this module exists as ENGINE code (2026-09-05, VoiceLoop package extraction,
slice 9b). The plan says "echo_check and fingerprint_check live in the engine; the
degradation contract stays in the deployment". This is that split, drawn one notch
narrower than the wording, and the reason is in the code it came out of.

WHAT MOVED: the tiering. Given a set of exact matches, echo hits and an opener
collision, which rows come back and which of them are warn_only. Given a set of
out-of-band metrics, the same question. That is a judgement about writing, it needs
no corpus and no operator, and it is the fleet's.

WHAT DELIBERATELY DID NOT: every line of resource resolution and error handling.
`voicefp_gate.echo_check` resolves the echo engine BEFORE its try block, and its own
comment records why in the strongest terms available: a renamed-away constant inside
the try does not raise, the broad except launders it into
`voice-echo-unavailable`, and the post then publishes with prompt_echo, opener_echo
AND exact_echo all silently off while the detail line blames the wrong component.
That placement was the resolution of a standard review finding. Moving the handlers
into a package, where a future edit would be one repo further from that comment, is
how a documented bug class comes back.

So the deployment keeps: which engine, which bands file, what a missing one means,
and what a raised exception means. It calls in here only once it has real results.

NOTHING HERE FAILS OPEN OR CLOSED, because nothing here can fail: it is given values
and returns rows. The fail-open decisions both live with the caller, which is where
their reasons live too.
"""
from __future__ import annotations

#: Below this many words, a verbatim retired phrase is treated as coincidence.
#:
#: LENGTH decides the tier, because length decides whether reproduction can be an
#: accident. A seven-word phrase reproduced verbatim is not. "Safety debt" is two
#: words of ordinary industry idiom that the founder writes because it is what the
#: thing is CALLED, proven with a real comment nobody copied from anything, and an
#: unconditional block rejected it outright.
RETIRED_ENFORCE_WORDS = 5


def echo_rows(exact, hits, prev):
    """Rows for what the echo engine found. `[]` is a pass.

    `exact`   verbatim reproductions of retired phrases
    `hits`    passages matching the slot's own prompt material
    `prev`    an opener matching a recent post, or falsy

    Order is deliberate and matches the shipped gate: retired phrase, then prompt
    echo, then opener echo.
    """
    out = []
    if exact:
        shortest = min(len(p.split()) for p in exact)
        coincidental = shortest < RETIRED_ENFORCE_WORDS
        out.append({
            "rule": "voice-retired-phrase",
            **({"warn_only": True} if coincidental else {}),
            "detail": (f"reproduces a RETIRED phrase verbatim: "
                       f"\"{exact[0][:60]}\". Reproducing one is the leak, not a "
                       f"coincidence. Say it in your own words."),
        })
    if hits:
        out.append({
            "rule": "voice-echo",
            "detail": (f"{len(hits)} passage(s) matching the slot's prompt "
                       f"material (exemplars/guidance), e.g. \"{hits[0][:80]}\". "
                       f"Shipping prompt material verbatim is the 9-of-22 "
                       f"defect; say it in different words."),
        })
    if prev:
        out.append({
            "rule": "voice-opener-echo",
            "detail": (f"opens with the same shape as a recent post "
                       f"(\"{prev[:60]}\"). 7 of 22 posts opened identically on "
                       f"2026-08-06; vary the first sentence."),
        })
    return out
