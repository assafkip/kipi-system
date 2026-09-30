#!/usr/bin/env python3
"""Refuse a post whose first line a stranger cannot resolve. The followable-cold gate.

why this exists (2026-08-12, the external lane's first live day): four of seven posts
opened inside a story the reader was never in. The founder read the first one and said it
makes no sense.

    That box under the TV playing free movies is clicking ads at 3am...
    Popa ran on TV boxes for four years while the traffic it relayed got sold...
    Court order on the breach data spells out who may touch the stolen records...

Which box. Who is Popa. Which breach. Each opens on a referent the reader has no way to
resolve, because the model had the source article and the reader does not.

## Why the prompt fix was not enough, stated plainly

`generate.build_prompt` now asks for a self-contained opening, and asking is all it does.
The executable is `check()` below, wired into `decide._violations` and pinned by
`tests/test_opener_gate.py`. Two independent reasons the gate had to exist as well:

1. **Substack has its OWN prompt.** `substack.build_seed_from_material` builds a separate
   instruction and never reads `build_prompt`, so the fix reached X and LinkedIn and
   stopped. A rule that has to be copied into every prompt is a rule that will be missing
   from the next one. This runs in `decide._violations`, which every channel passes through.
2. The founder's standing rule: a prompt-only fix has no blocker behind it.

## The honest split, in the posture `name_gate` and `substance_gate` use

**EXACT and mechanical (`_demonstrative`).** A first line beginning `That|This|These|Those`
plus a noun. Zero judgement. Nothing has introduced the referent because nothing precedes
the first line.

**EXACT (`_bare_proper_noun`).** A first line beginning with a single capitalised word
followed immediately by a past-tense verb of action. `Popa ran on TV boxes` is the shape.
A name a reader cannot resolve, used as though they already know it.

**EXACT (`_unnamed_event`).** A first line opening on an article plus a bare event noun:
`Court order on the breach data`, `The report found`. The event is referred to and never
identified.

## Negative control, run BEFORE this shipped

Against 124 real bodies (published plus banked):

    bare demonstrative opener      1 hit   and it IS the defect
    bare proper noun + verb        1 hit   and it IS the defect
    bare event-noun opener         1 hit   and it IS the defect

Three hits in 124, all of them the thing this was built to stop, zero false positives. That
matters more than the rule reading well: a gate that fires on the founder's real vocabulary
gets switched off within a week, and then it protects nothing.

## What this deliberately does NOT catch

A first line that is followable but boring, or one that names its subject and still says
nothing. Those are judgement, they belong to whoever writes the post, and claiming this
covers them would be the overclaim `substance_gate`'s docstring warns about.
"""
from __future__ import annotations

import re

#: `That box under the TV`. Nothing precedes line one, so nothing can have introduced it.
# "That box under the TV" is the defect. "This was a great experience" is
# English (organic-ayelet-chat). Copulas after the demonstrative are not a
# missing referent.
_DEMONSTRATIVE = re.compile(
    r"^\s*(that|this|these|those)\s+"
    r"(?!was|is|are|were|has|have|had|did|does|can|will|would|been\b)[a-z]",
    re.I)

#: `Popa ran on TV boxes`. A name used as though the reader already has it.
# Action verbs only. Copulas (is/are/was/were/has/have/had) made common nouns
# look like names: "Leadership is demanding" fired on x-22 (measured 2026-08-26).
# `Popa ran` still matches. The allowlist growing is the failure mode; dropping
# the copula is the cheaper cut.
_BARE_PROPER = re.compile(
    r"^\s*([A-Z][a-zA-Z]{2,})\s+"
    r"(ran|runs|went|got|said|launched|shipped|"
    r"pleaded|filed|announced|admitted|paid|lost|won)\b")

#: `Court order on the breach data`, `The report found`. The event is never identified.
_EVENT = (r"court order|ruling|report|study|breach|incident|filing|complaint|lawsuit|"
          r"settlement|outage|leak|memo|announcement|paper|verdict|indictment")
#: The article is OPTIONAL. `Court order on the breach data` opens with the bare noun
#: and no determiner at all, which a required-article pattern misses entirely. Caught
#: by a test that asserted the case before it was measured, which is the same
#: discipline failure this file documents elsewhere. Re-measured after the fix: 1 hit
#: in 124 real bodies, and the hit is the defect.
_UNNAMED_EVENT = re.compile(rf"^\s*(the\s+|a\s+|an\s+)?({_EVENT})\b", re.I)

#: Names a reader resolves without help, so a first line may open on one. Deliberately
#: SHORT and only what the corpus actually needed: this list growing is the failure mode,
#: because every entry is a promise that a stranger knows the word.
_PUBLICLY_RESOLVABLE = {
    "google", "meta", "linkedin", "openai", "anthropic", "microsoft", "amazon",
    "apple", "reddit", "twitter", "substack", "github", "london", "california",
    "snowflake", "claude", "chatgpt",
}


def first_line(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def signals(text):
    """Every reason a stranger could not follow the opening. Named, so a refusal explains."""
    line = first_line(text)
    if not line:
        return []
    found = []
    if _DEMONSTRATIVE.match(line):
        found.append("opens on a demonstrative ('that', 'this') pointing at something "
                     "the reader has never been shown")
    match = _BARE_PROPER.match(line)
    if match and match.group(1).lower() not in _PUBLICLY_RESOLVABLE:
        found.append(f"opens on the bare name {match.group(1)!r}, used as though the "
                     f"reader already knows it")
    if _UNNAMED_EVENT.match(line):
        found.append("opens on an event the line never identifies")
    return found


def check(text):
    """Violations in the gates' shape, so callers merge reports without special-casing."""
    found = signals(text)
    if not found:
        return []
    return [{
        "rule": "opener-not-followable",
        "line": 1,
        # No `warn_only`. That absence is what `decide.decide_candidate` reads to make this
        # blocking, and it is the enforcement; this sentence is not.
        "detail": ("a stranger who never read the source cannot follow the first line: "
                   + "; ".join(found)
                   + ". Name the subject rather than referring to it. Landing mid-story is "
                     "still right; the reader just has to know what the story is about."),
    }]
