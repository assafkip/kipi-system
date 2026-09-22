#!/usr/bin/env python3
"""The substance gate. Today it enforces exactly ONE thing: a per-channel word floor.

Read that first line carefully, because this module's name and its history both promise
more than the code does, and the gap is deliberate.

`check()` returns a BLOCKING row only for a body under the word floor (5 words on X, 20 on
LinkedIn). The number requirement is GONE, retired 2026-08-11. The mechanism warn is
GONE, retired 2026-08-26 after it fired on 26 of 28 of his X posts.

why the module exists at all (2026-08-05, ASK-408): the founder called this build "the
decision maker", and `canonical/the-business.md` plus `output/business-plan-publishing.md`
both named one rule as the moat the publishing business rests on:

    No post ships without a measured number and a named mechanism.

That rule has since been reversed twice by the founder, in 2026-08-09 (block -> warn) and
2026-08-11 (retired). Neither canonical file has been updated, so both still assert the
original. When they disagree with this module, this module is what runs.

The rule lived only in prose. **The engine could ship a post that passed every voice
lint, sounded exactly like the founder, and said nothing checkable.** The decision maker
decided voice and never decided substance.

## What each half is worth, stated honestly

**The NUMBER half is fully deterministic and strong.** A numeral must be BOUND: bound to
a denominator (`648 of 776`), to a rate (`55%`), to a timeframe (`95 times in 30 days`),
or to money (`$40,560`). A bare count is not enough and a vague quantifier is a failure,
which is the whole point of the plan's line: "so `648 of 776` and never `most`".

**The NUMBER half is NECESSARY AND NOT SUFFICIENT** (added 2026-08-06, sp-3fb1630e).
This module asks whether a number is BOUND. It has never asked where the number came
from, and that gap is not theoretical: the fabricated-biography post scored well HERE
because "12 years" and "51,000+ lines" are numbers bound to a unit. The gate rewarded the
fabrication for being numerate. `figure_gate.check` is the other half and it asks the
question this one structurally cannot -- does this figure appear in the artifact the post
claims to come from. Both run in `decide._violations`; neither is enough alone.

**The MECHANISM half is a HEURISTIC and is labelled as one.** No regex can truly tell
whether a sentence names a causal mechanism. This checks for a mechanism marker, which
catches the common failure (a number with no explanation attached) and will miss a
mechanism phrased in a way the marker list does not cover. The real backstop for
semantic quality is the ported `voice_judge`, which catches AI *shape* the regex lints
cannot. Claiming this half is deterministic would be the same overclaim the practice
gets paid to find in other people's systems.

## Terminal behaviour

A failing candidate routes to the existing `discarded_replaced` state and the slot
refills in the same cycle. **This module adds a REASON to reject and no new terminal
state**, so `test_no_refusal_path.py` still holds: nothing is refused, nothing is held,
nothing waits.
"""
from __future__ import annotations

import re

# A numeral is BOUND when it carries the size of the thing it is a fraction of, a rate, a
# timeframe or a currency. Ordered most-specific first so `why` names the real reason.
BOUND_NUMBER_PATTERNS = [
    ("fraction", re.compile(r"\b[\d,]+\s*(?:of|out of|/)\s*[\d,]+\b", re.I)),
    ("rate", re.compile(r"\b\d+(?:\.\d+)?\s*%")),
    ("money", re.compile(r"\$\s?[\d,]+(?:\.\d+)?")),
    ("over-time", re.compile(
        r"\b[\d,]+\s+\w+(?:\s+\w+){0,3}\s+(?:in|per|a|every|over)\s+"
        r"(?:\d+\s+)?(?:second|minute|hour|day|week|month|year|run|cycle|click|request)s?\b",
        re.I)),
    ("ratio", re.compile(r"\b[\d,]+\s*(?:->|→|to)\s*[\d,]+\b")),
    ("scale", re.compile(r"\b\d+(?:\.\d+)?\s*x\b", re.I)),
    # A numeral attached to a countable noun is a MEASUREMENT: "465K people read it",
    # "1.9K upvotes", "155 comments", "48 repos". Added 2026-08-05 after the gate
    # discarded 9 of the 12 real drafts, including the one flagged "publish FIRST" whose
    # numbers were 465K reads / 1.9K upvotes / 155 comments. The plan's rule is "a
    # number, never `most`"; the first implementation demanded a FRACTION, which is a
    # stricter rule than the plan states and starves the queue. What still fails is the
    # absence of a numeral, which is what "most" and "a lot" actually are.
    ("count", re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*[KMB]?\s+[a-z][\w-]*", re.I)),
]

# Words that promise a measurement and deliver none. Their presence is not itself a
# failure; shipping ONLY these is.
VAGUE_QUANTIFIERS = re.compile(
    r"\b(?:most|many|several|numerous|significant(?:ly)?|substantial(?:ly)?|"
    r"a lot of|lots of|countless|various|multiple|some|often|frequently|"
    r"dramatically|massively|hugely)\b", re.I)

# Markers that a causal mechanism is being named. HEURISTIC, see the module docstring.
MECHANISM_MARKERS = re.compile(
    r"\b(?:because|since it|the reason|which is why|so that|caused by|"
    r"turned out|the cause|it works by|works by|"
    r"by \w+ing\b|"                     # "by batching the lookup", "by walking the AST"
    r"what it does is|the mechanism|under the hood|the fix (?:is|was)|"
    r"root cause|traced (?:it )?to|comes from|due to|"
    # A procedure IS a mechanism even without a causal connective. Added 2026-08-05:
    # the XDA draft names three prompts and what each does, then "I built a toggle.
    # Research mode activates all three." That is plainly a mechanism and the marker
    # list missed it, which is the false-negative direction the docstring warned about
    # showing up in real material within an hour.
    r"so i built|i built a|which (?:activates|triggers|blocks|catches|stops)|"
    r"it (?:activates|refuses|blocks|catches|stops|checks|reads|writes)|"
    r"tradeoff|trade-off|instead of)\b", re.I)
# `by <gerund>` is deliberately general rather than an allowlist of verbs. An earlier
# version listed nine verbs and rejected "by batching the lookup", which is plainly a
# mechanism. Whack-a-mole on verbs would have kept producing false negatives that cost a
# slot each. The general form admits a few weak matches ("by growing the list"), and a
# false PASS here is caught downstream by the semantic voice judge.


def find_bound_number(text):
    """(kind, matched_text) for the first bound numeral, or None."""
    for kind, pattern in BOUND_NUMBER_PATTERNS:
        match = pattern.search(text)
        if match:
            return kind, match.group().strip()
    return None


def has_mechanism(text):
    match = MECHANISM_MARKERS.search(text)
    return match.group().strip() if match else None


# A FLOOR, not a checklist. The one thing the two warn_only rules were quietly doing
# besides causing the sameness: keeping fragments out.
#
# Measured after they were relaxed: "It broke." (9 characters) passed every blocking
# gate and would have published, and "junk" failed only on capitalization, which
# `post_repair` fixes automatically before any gate sees it.
#
# Deliberately far BELOW the researched X target of 100 characters (platforms.md: "tweets
# under 100 characters get more engagement"), so the floor and the target can never
# fight. It exists to reject a fragment, not to have an opinion about length. There is
# no phrase to recite and nothing to imitate, which is the whole difference between this
# and the marker list it replaces.
MIN_WORDS = 5

# PER CHANNEL, because 5 words is a floor calibrated for X and LinkedIn had none at all.
#
# Measured 2026-08-09 on every LinkedIn body that exists: 3 published at 227, 246 and 249
# words, and 10 banked at 195 to 227. Then two banked bodies at 5 and 9 words, which were
# the model's own refusal text leaking through as posts -- "No correctable post exists
# here." and "The AI is confidently wrong about what it built." Both cleared every gate,
# because the only length rule in the stack was a fragment floor set deliberately low so
# it could never fight X's researched 100-character target.
#
# 20, NOT 100, and the difference is the whole point. The real distribution is 195-249
# words, so a 100-word floor is defensible arithmetic -- and it would encode "LinkedIn
# posts must be long" from n=13, which is the over-reach that produced every other false
# positive in this session. The measured DEFECT is refusal text at 5 and 9 words, not
# short posts. 20 catches both fragments and asserts nothing about how long a good post
# is.
#
# It also happens to be the most a floor can be without rewriting 16 test fixtures that
# use a 24-word body to test publishing mechanics. That is a real constraint and not a
# principled one, so it is stated rather than dressed up: a higher floor is arguable and
# is captured as spillover rather than smuggled in here.
MIN_WORDS_BY_CHANNEL = {"linkedin": 20}


def min_words(channel=None):
    return MIN_WORDS_BY_CHANNEL.get(channel, MIN_WORDS)


def check(text, channel=None):
    """Return a list of violations. Empty list means the candidate may ship.

    Shape matches the voice linters' violation dicts so a caller can merge reports
    without special-casing this one.
    """
    violations = []

    floor = min_words(channel)
    if len((text or "").split()) < floor:
        violations.append({
            "rule": "substance-fragment",
            "line": 1,
            "detail": (f"{len((text or '').split())} words, under the {floor}-word floor "
                       f"for {channel or 'this channel'}, so it is a fragment and not a "
                       f"post. This is the ONLY hard length rule: there is no phrase to "
                       f"say and nothing to imitate."),
        })

    # RETIRED 2026-08-11, founder-directed: "I dont care if numbers are made up, but I want
    # interesting posts that are in my voice and engaging."
    #
    # This warn asked every post for a measured number bound to a denominator. That
    # requirement is reversed for social copy, so the row now instructs the opposite of
    # the standing rule, and a warn that contradicts the directive is worse than no warn:
    # it is read, believed, and acted on. Measured 2026-08-11: it fired on 4 of 5 posts in
    # the batch Amber wrote, she declined to satisfy it twice on the correct grounds that
    # inventing a denominator would break a harder rule, and the earlier batch shipped
    # because the reviewer waved the identical row through as "advisory".
    #
    # The evidence bar it came from is a RESEARCH rule (`canonical/icp-discovery-method.md`
    # "No claim below three observations"), about not trusting an unaudited rate. It was
    # never scoped to copy and it leaked here.
    #
    # NOT retired: the fragment floor above, and `figure_gate`,
    # which still refuses a figure that contradicts its source when a source is supplied.
    # The standard is no longer "every post carries a measured number"; it is "a post is
    # allowed to be approximate, and may never invent a funding round, a client or a
    # conversation" (`canonical/social-writing-method.md` section 7).
    # The 2026-08-09 half-measure this replaces: the same requirement, downgraded from
    # block to warn. Its own numbers argued for going further and the warn was kept anyway.
    # Measured then, across the whole ledger: "no measured number" caused 63 discards and
    # "figure(s) not found in the source" another 44, so the number rules caused 107 of 130
    # discards, 82% of everything the engine threw away, each one a model call. The 44
    # fabrications were the tell: the model was told it MUST carry a number, did not have
    # one, invented it, and `figure_gate` caught the invention. The rule was fighting itself,
    # and a warn kept the instruction alive while removing only its teeth.

    # substance-mechanism RETIRED 2026-08-26. It fired on 26 of 28 of his eligible
    # X posts (rca-voice-gate-refuses-his-corpus-2026-08-26). A warn that always
    # fires trains agents to stuff "because" and line counts. The fragment floor
    # above is the only row this function still emits.

    return violations


def report(text):
    """Human-readable verdict, for the CLI and for a Slack escalation line."""
    violations = check(text)
    if not violations:
        kind, matched = find_bound_number(text)
        return f"substance: ok ({kind}: {matched!r}; mechanism: {has_mechanism(text)!r})"
    return "substance: " + "; ".join(v["detail"] for v in violations)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("usage: substance_gate.py <file>", file=sys.stderr)
        raise SystemExit(2)
    with open(sys.argv[1], encoding="utf-8") as handle:
        body = handle.read()
    print(report(body))
    raise SystemExit(1 if check(body) else 0)
