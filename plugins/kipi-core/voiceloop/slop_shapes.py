#!/usr/bin/env python3
"""Templated shapes that cost reach, blocked by pattern.

Source: the founder's own research, 2026-08-20, recorded in
`canonical/social-writing-method.md` section 14g. These generative templates carry
measured within-author reach penalties on LinkedIn, because so many people write
that exact shape that both the ranking model and human readers skip them.

COUNT THEM IN `SHAPES`, never here. This docstring said "four" for the length of one
session while six were live, which is the CLAUDE.md scar verbatim: a prose count
said "nine" for weeks and a post nearly published the wrong number by quoting it.

## Why these are BLOCKING and the usual word-list caution does not apply

The standing scar is that list-based gates catch the founder: six once blocked his
real vocabulary in a single session. So the test was run BEFORE writing this file,
against all 103 rows of `voice/exemplars.jsonl`:

    every shape in SHAPES   0 of 103

Zero. Not rare, absent. He has never once written any of these shapes, so the
false-positive rate against his own corpus is measured at zero and a block cannot
silence him. `test_slop_shapes.py` re-runs that sweep on the live corpus, so the day
he does write one, the gate fails its own test rather than quietly blocking him.

## What each replacement is

The research gave a positive replacement for every shape, and the through-line is
that each one deletes a rhetorical move and puts a mechanism or a number in its
place. That is the same finding the corpus score reached independently: folding
standalone aphorisms into causal sentences was the single largest voice improvement
measured on 2026-08-20 (+0.035).
"""
from __future__ import annotations

import re

#: Each entry: rule name, compiled pattern, and what to write instead. The `instead`
#: text reaches the reviser, so a refusal here is actionable rather than a wall.
SHAPES = (
    (
        "slop-contrast-bridge",
        re.compile(r"(?i)\b(that|this|it)\s*(?:is|'s)\s+not\b[^.!?\n]{0,80}[.!?]\s+"
                   r"(?:it|that|this)\s*(?:is|'s)\s+\w+", re.M),
        "a definitive statement. Say what it IS, without first saying what it is not.",
    ),
    (
        "slop-dramatic-pause",
        re.compile(r"(?i)[.!?]\s+(the result\?|the problem\?|the catch\?|why\?|the kicker\?)"),
        "causal linking. Join the cause to the effect in one sentence instead of "
        "staging a reveal.",
    ),
    (
        "slop-false-secret",
        re.compile(r"(?i)\b(here'?s what nobody|what nobody tells you|nobody talks about|"
                   r"the secret (?:nobody|no one)|what they don'?t tell you)\b"),
        "a data-anchored premise. Open on the thing you measured, not on the claim "
        "that it is hidden.",
    ),
    (
        # 2026-08-20 WIDENING. The four shapes above match the founder research's own
        # QUOTED EXAMPLES, so they catch the phrasing and miss the shape: a draft
        # written 2026-08-20 shipped both patterns below and returned [] from this
        # module. Same evidence bar as the originals, run before writing them: each
        # hits 0 of 103 usable rows in `voice/exemplars.jsonl`, pinned by
        # `test_slop_shapes.py`. The third candidate tried, an imperative-pair widening
        # of generic-advice past `stop ...ing / start ...ing`, caught nothing real and
        # was dropped rather than shipped as dead weight.
        "slop-contrast-parallel",
        re.compile(r"(?i)\b(a|the)\s+(\w+)\s+that\b[^.!?\n]{0,70}[.!?]\s+"
                   r"(a|the)\s+\2\s+(where|that)\b"),
        "a definitive statement. Say what the thing does, once, without building a "
        "matched pair around it.",
    ),
    (
        "slop-aphorism-close",
        re.compile(r"(?i)\byou\s+(?:can'?t|cannot)\b[^.!?\n]{0,40}\bwhat\s+you\s+"
                   r"(?:haven'?t|didn'?t|don'?t)\b"),
        "the mechanism. Name what was actually done and what it found, instead of "
        "closing on a maxim the reader has heard before.",
    ),
    (
        "slop-generic-advice",
        re.compile(r"(?i)\bstop \w+ing\b[^.!?\n]{0,60}[.!?]\s*start \w+ing\b"),
        "a direct operational directive. Name the action and the object, once.",
    ),
    (
        # 2026-09-30, founder-directed: he flagged "X isn't X. It's a Y with a Z
        # attached." as an AI tell. The noun must RETURN after the negation (`\1`),
        # which is what separates this from an ordinary "the review isn't done."
        # Measured before shipping: 0 hits across his exemplars, organic posts,
        # writing examples, mined work and approved comments. Both apostrophes,
        # because model output uses the curly one and a `'`-only pattern misses the
        # sentence it was written for.
        "slop-redefinition-close",
        re.compile(r"(?i)\b(\w{3,})\b[^.!?\n]{0,60}?\b(?:isn['’]?t|is not)\s+"
                   r"(?:\w+\s+){0,2}?\1\b[^.!?\n]{0,20}[.!?]\s+"
                   r"(?:it['’]?s|its|it is|that['’]?s|thats)\s+"
                   r"(?:just\s+)?(?:a|an)\s+\w+"),
        "the consequence as a mechanism, not a metaphor. Say what breaks and how, "
        "instead of redefining the thing as something it is not.",
    ),
    # ASK-5427, 2026-11-18, founder: "Do 1+2". Seven habits from the unslop skill's
    # "Claude's own measured habits" list (counted over 4.5M words of Claude Code
    # prose). Each hits 0 of 170 rows in `voice/exemplars.jsonl`, measured the same day,
    # and the sweep test on the instance side re-runs that on exemplars, organic posts
    # and writing examples. Deliberately NOT here: actually (28 hits in his corpus),
    # rather than (30), the real, genuinely, bottom line, not just. Blocking those
    # would block him, which is the standing scar of list gates. `worth it`, `worth
    # keeping` and a plain `drives the car` stay legal because those patterns need the
    # habit's own second word. The bare-word rules (load-bearing, cleanly,
    # fundamentally) have no literal carve-out: the ticket chose to block the word,
    # since he writes none of them (0 of 201 rows). Review round 1 (PR 842) measured
    # the cost: 'applied cleanly' and a literal load-bearing wall are blocked too, and
    # the cold-outreach template's 'worth flagging' line trips the preamble rule.
    # slop-worth-preamble also overlaps voice-lint BANNED_PHRASES on 'it is worth
    # noting'; the engine copy stays because only this path carries an instead line.
    (
        "slop-load-bearing",
        re.compile(r"(?i)\bload[- ]bearing\b"),
        "the plain phrase. Name the claim this rests on or the constraint that "
        "matters here.",
    ),
    (
        "slop-cleanly",
        re.compile(r"(?i)\bcleanly\b"),
        "the verb alone, or the observable result. Say what happened (exits with "
        "code 0, leaves no lock file) instead of grading it.",
    ),
    (
        "slop-fundamentally",
        re.compile(r"(?i)\bfundamentally\b"),
        "the specific difference. Name what differs, or drop the intensifier.",
    ),
    (
        "slop-worth-preamble",
        re.compile(r"(?i)\bworth\s+(?:flagging|noting|surfacing|stating|"
                   r"being\s+(?:precise|clear|explicit)|"
                   r"a\s+(?:look|glance|quick\s+check)|checking)\b"),
        "the point itself. State the finding, or give the action (check whether the "
        "index went stale), instead of announcing that it is worth making.",
    ),
    (
        "slop-single-superlative",
        re.compile(r"(?i)\bthe\s+single\s+(?:most|biggest|highest|largest|greatest)\b"),
        "the thing without crowning it first. State the number or the cause and "
        "let the reader rank it.",
    ),
    (
        "slop-belt-and-suspenders",
        re.compile(r"(?i)\bbelt[- ]and[- ]suspenders\b"),
        "the literal fact: a second guard that fires if the first one fails.",
    ),
    (
        "slop-totalizer-crown",
        re.compile(r"(?i)\b(?:shapes|drives|governs|gates|determines)\s+"
                   r"(?:everything(?:\s+else)?|the\s+rest|the\s+whole\s+thing)\b"),
        "the plain claim. Name what it determines and how, for example 'the open "
        "question is whether Redis failover holds'.",
    ),
)


def check(text):
    """Blocking rows for every penalized shape present. Empty when the draft is clean.

    Channel-blind on purpose. The research measured these on LinkedIn, and nothing
    about "this sentence reads as a template" is channel-specific: the same shape on
    X trips the same human skip. A channel-scoped version would let the identical
    sentence through on the channel nobody measured.
    """
    out = []
    for name, pattern, instead in SHAPES:
        found = pattern.search(text or "")
        if found:
            out.append({
                "rule": name,
                "line": (text or "")[:found.start()].count("\n") + 1,
                "detail": f"templated shape that costs reach: {found.group().strip()!r}. "
                          f"Write {instead}",
            })
    return out
