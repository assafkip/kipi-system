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
