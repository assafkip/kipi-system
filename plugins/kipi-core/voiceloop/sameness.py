#!/usr/bin/env python3
"""SAMENESS RATES: does a window of posts read like one template?

why this module exists as ENGINE code (2026-09-05, VoiceLoop package extraction,
slice 9). Every function here takes a LIST OF STRINGS and returns a number. None of
them knows where the strings came from, which operator wrote them, or what happens to
the verdict. That is the whole test for whether a rule belongs to the fleet, and this
half of `sameness` passes it cleanly.

The half that did NOT move is the half that answers "which bodies": the postbook
reconciliation, the queue read, the prompt-echo check against the deployment's voice
data, and the CLI. Those stay in the deployment, and they are the reason `sameness`
split rather than moved.

WHAT THESE MEASURE, and it is not quality. A high shared-8-gram share does not mean a
post is bad; it means two posts in the window are built from the same sentence. The
thresholds live with the READER, not here, because "how much sameness is too much" is
a judgement about one operator's output and "how much sameness is there" is
arithmetic.

Nothing here is a gate. `decide` does not import this module and must not: a report
that can refuse a draft is a gate wearing a report's name, and the deployment's suite
pins that separation.
"""
from __future__ import annotations

import re

# NO THRESHOLD LIVES HERE, and that is the split, not an oversight. The deployment
# keeps MAX_SHARED_NGRAM_SHARE, MAX_OPENER_COLLISION_SHARE, MAX_SHAPE_SHARE,
# MAX_CONTRAST_SHARE and MAX_PROMPT_ECHO, because "how much sameness is too much" is a
# judgement about one operator's output while "how much sameness is there" is
# arithmetic. Shipping a threshold fleet-wide would hand every operator this founder's
# tolerance for his own tics.

NGRAM = 8


def _words(text):
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def ngrams(text, n=NGRAM):
    words = _words(text)
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def _sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()]


def _final_sentence(text):
    parts = _sentences(text)
    return parts[-1] if parts else ""


def _closing_pair(text):
    """The last TWO sentences, because the tic being measured spans the boundary.

    The contrast move is written across two sentences -- the negation ends one and the
    assertion opens the next:

        "A control you never wired isn't a control."  "It is a note to yourself."

    The first classifier read only the FINAL sentence, so it required `not` and `it is`
    in the same string and structurally could not fire. Measured: `contrast` scored
    0 of 29 on a corpus where 8 of 29 (28%) end on exactly that construction, and all 8
    were bucketed `other` -- the one bucket this report promises never to score. The
    comment above the regex even wrote the pattern with a period in the middle, and the
    code then split on that period and threw the first half away.
    """
    parts = _sentences(text)
    return " ".join(parts[-2:]) if parts else ""


def ending_shape(text):
    """Which shape the CLOSING takes. Read over the last two sentences, not one."""
    last = _final_sentence(text).strip()
    closing = _closing_pair(text).strip()
    if not last:
        return "other"
    if last.endswith("?"):
        return "question"
    # "X isn't Y. It is Z" -- the contrast pattern, matched across the sentence
    # boundary it is actually written across (see `_closing_pair`).
    # DENY THEN ASSERT, in whatever words. Requiring "It is" after the negation caught
    # 5 of the ~8 real instances; the rest say "You have", "A test does", "Working code
    # is". The move is the negation followed by the restatement, not one phrasing of it:
    #
    #     "Prose doesn't hold a pricing rule."      "A test does."
    #     "you don't have a control."               "You have a bottleneck ..."
    #     "It isn't a system that ran."             "Working code is the only ..."
    #
    # Deliberately inclusive. This is a REPORT: its job is to surface a candidate tic
    # for a human to look at, not to convict a post, and a detector that misses the
    # founder's signature move at 28% is the failure mode that matters here.
    # DENY, then ASSERT. The negation, a clause boundary, then a real clause after it.
    #
    # Two calibration steps, both measured against the live corpus rather than argued:
    #
    #   requiring "It is" after the negation   -> 5/29, missed "A test does."
    #   any negation in the closing pair       -> 12/29 (41%), over-fired on ordinary
    #                                             negations that are not the move
    #   negation + boundary + a following clause -> 8/29 (28%)
    #
    # 28% is the figure an independent hand count of the same 29 bodies produced, which
    # is the closest thing to a calibration this has.
    #
    # NO leading \b on the negation: in "isn't" and "doesn't" the n is preceded by a
    # letter, so a word boundary there matches nothing and an earlier version silently
    # collapsed to standalone "not" -- it went DOWN from 5 to 2 after a change that
    # could only widen it. Caught by watching the live number move the wrong way.
    if _CONTRAST.search(closing):
        return "contrast"
    words = _words(last)
    if words and words[0] in {"pick", "go", "look", "check", "ask", "try", "stop",
                              "start", "read", "watch", "run", "build", "use"}:
        return "imperative"
    # A parallel pair: two clauses of similar length around a comma or semicolon.
    halves = re.split(r"[;,]", last)
    if len(halves) == 2 and all(len(_words(h)) >= 3 for h in halves):
        left, right = (len(_words(h)) for h in halves)
        if abs(left - right) <= 2:
            return "parallel-pair"
    return "other"


# DENY, then ASSERT. A denial token, a clause boundary, then a real clause.
#
# Calibrated against the live corpus in four measured steps, never argued:
#
#   require "It is" after the negation        5/29  -- missed "A test does."
#   any negation in the closing pair         12/29  -- fired on ordinary negations
#   negation + period + 3 tokens              8/29  -- missed the COMMA form
#   this one                                 10/29 (34%)
#
# An independent hand count of the same 29 bodies put the move at 8. This sits slightly
# above that because it also catches the comma form ("Nothing was lost, and the log
# proves it"), which is the same move with different punctuation.
#
# The boundary set and the denial set are BOTH pinned by tests, in both directions --
# four canonical phrasings that must fire and three ordinary negations that must not.
# Three rejected calibrations previously passed the suite because nothing held them.
_CONTRAST = re.compile(
    # NOT `\bno\b`: "with no receipt" and "had no state column" are ordinary noun
    # negations, not the rhetorical move, and including it fired on both. The move is a
    # denial of a CLAIM, which in practice is not / n't / never / nothing.
    r"(?:n[o']t|\bnever\b|\bnothing\b)\b"            # the denial
    r"[^.;!?]*"                                       # the rest of that clause
    r"[.;!?,\u2013\u2014-]\s*"                        # . ; ! ? , en-dash em-dash hyphen
    r"\S+(?:\s+\S+){1,}",                            # an assertion, not a fragment
    re.I | re.S)


def _fraction(count, total):
    return {"count": count, "of": total,
            "share": round(count / total, 3) if total else None}


def shared_ngram_rate(bodies):
    """Posts sharing an 8-gram with ANOTHER post in the window."""
    grams = [ngrams(b) for b in bodies]
    sharing = 0
    for i, mine in enumerate(grams):
        others = set().union(*(g for j, g in enumerate(grams) if j != i)) if len(grams) > 1 else set()
        if mine & others:
            sharing += 1
    return _fraction(sharing, len(bodies))


def opener_collision_rate(bodies, words=6):
    """Posts whose first `words` words match another post's."""
    openers = [" ".join(_words(b)[:words]) for b in bodies]
    collided = sum(1 for i, o in enumerate(openers)
                   if o and any(o == other for j, other in enumerate(openers) if j != i))
    return _fraction(collided, len(bodies))


def ending_shape_concentration(bodies):
    """Concentration in a NAMED shape. `other` is excluded and that is the whole point.

    Caught by running this against the live corpus before shipping it: X came back
    FAIL with `other` at 65%, and `other` is the UNCLASSIFIED bucket. Scoring it means
    the report asks for fewer unrecognised endings and therefore MORE questions and
    contrast pairs -- it would push the engine toward the tics it exists to detect, and
    the first thing a reader would do to satisfy it is make the output more uniform.

    A named shape at 40% is a tic. `other` at 65% is either healthy variety or shapes
    nobody has named yet; both are fine and neither is sameness.
    """
    counts = {}
    for body in bodies:
        shape = ending_shape(body)
        counts[shape] = counts.get(shape, 0) + 1
    total = len(bodies)
    named = {k: v for k, v in counts.items() if k != "other"}
    worst = max(named, key=named.get) if named else None
    return {"counts": counts, "total": total, "worst": worst,
            "worst_share": round(named[worst] / total, 3) if worst and total else None,
            "contrast_share": round(counts.get("contrast", 0) / total, 3) if total else None,
            "unclassified_share": round(counts.get("other", 0) / total, 3) if total else None}
