#!/usr/bin/env python3
"""Did a model revision keep the small words that carry the meaning? (ASK-5428)

why this exists (founder, 2026-11-18, "Do 1+2", from the unslop review): a rewriter that is
told to fix ONE named violation can still turn "may" into "must", drop a "not", move a "3"
to "30" or lose an "only if", and every gate downstream reads the result as clean prose.
The unslop skill does this check as model judgment ("Step 5: final fidelity gate"); here it
is code, so a reviser that drifts is refused instead of trusted.

PURE: two strings in, a dict out. No I/O, no model, no clock. `revise.revise` is the only
caller, because every model revision in the fleet passes through it (the decide ladder,
critic, the style revise, the editor revise; consulting's `pipeline/revise.py` is an alias to
the same module object). A second caller would be a second chokepoint.

Number extraction is `figure_gate`'s (its regex and its value conversion), not a second
one. This is NOT the ASK-4988 question. That one asks whether a figure is vouched by the
SOURCE; this one asks whether a revision kept the draft's OWN figures. When ASK-4988
tightens what counts as a figure, this inherits it for free.

Four categories, each a multiset compare (count of each token before vs after). The one
exception is numbers under `presence=True` (a span-rewrite revision, see `changes`), which
compare as a set of (value, unit) pairs:
- numbers: (value, unit). "3 hours" and "three hours" are the same figure; "3" and "30",
  "hours" and "days" are not. A bare number carries unit "" so "3" -> "30" still flags.
- negations: not / never / no / n't. "does not" and "doesn't" are the same token.
- modals: may might must should will can could would shall ought. "won't" is will + not, "cannot" is can + not.
- conditions: if, unless, except, "by default", and "only" when it gates a clause ("only if").
  A bare "only" ("the only option") is a quantifier, not a condition, and counting it would
  refuse every reword of "the only" to "the sole".

Returns {category: [signed token, ...]} for the categories that changed; empty dict means the
meaning-bearing words are intact. "-x" was in the original and is gone, "+x" is new.
"""
from __future__ import annotations

import re
from collections import Counter

from . import figure_gate

MODALS = frozenset({"may", "might", "must", "should", "will", "can", "could",
                     "would", "shall", "ought"})
# "'d" is not counted: it is "had" as often as "would", and guessing either way would
# refuse correct rewrites.
NEGATIONS = frozenset({"not", "never", "no"})
CONDITIONS = frozenset({"if", "unless", "except"})
#: "only" gates a clause only when one of these follows it.
_ONLY_GATES = frozenset({"if", "when", "after", "before", "once", "unless", "while", "as"})

#: n't stems whose base is not the modal itself.
_NT_STEMS = {"ca": "can", "wo": "will"}

_UNITS = {
    "%": "percent", "percent": "percent", "pct": "percent",
    "s": "second", "sec": "second", "secs": "second", "second": "second",
    "seconds": "second",
    "ms": "ms", "millisecond": "ms", "milliseconds": "ms",
    "min": "minute", "mins": "minute", "minute": "minute", "minutes": "minute",
    "hr": "hour", "hrs": "hour", "hour": "hour", "hours": "hour",
    "day": "day", "days": "day", "week": "week", "weeks": "week",
    "month": "month", "months": "month", "year": "year", "years": "year",
    "kb": "kb", "mb": "mb", "gb": "gb", "tb": "tb",
    "usd": "usd", "dollar": "usd", "dollars": "usd",
    "x": "x",
}

_SCALES = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
_SCALE_AFTER = re.compile(r"\s*(" + "|".join(_SCALES) + r")\b")

_WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
_CODE = re.compile(r"```.*?```|`[^`]*`", re.S)


def _prep(text):
    return _CODE.sub(" ", (text or "").replace("’", "'").lower())


def _words(text):
    return _WORD.findall(_prep(text))


def _unit_after(stripped, end):
    """The unit word right after a figure, canonical, or '' when there is none."""
    rest = stripped[end:end + 24]
    if rest.lstrip().startswith("%"):
        return "percent"
    match = re.match(r"\s*([a-z]+)", rest)
    return _UNITS.get(match.group(1), "") if match else ""


def _figures(text):
    """Counter of (value, unit): digit figures and word figures, extraction from figure_gate.

    A leading "$" is the unit "usd", so "$5" and "5 dollars" are one figure.
    """
    stripped = figure_gate._strip_noise(_prep(text))
    found = Counter()
    scale_at = set()
    for match in figure_gate._NUMERAL.finditer(stripped):
        value = figure_gate._to_value(match.group(1), match.group(2))
        if value is None:
            continue
        end = match.end()
        # "5 million" is ONE figure, 5e6, exactly as "5M" is. Without this the digit pass
        # reads 5 and the word pass reads "million" = 1e6, so "$5 million" -> "$5M" was
        # refused and the trail named figures present in neither draft (PR #843 review).
        scale = _SCALE_AFTER.match(stripped, end)
        if scale:
            value *= _SCALES[scale.group(1)]
            scale_at.add(scale.start(1))
            end = scale.end()
        unit = _unit_after(stripped, end)
        if not unit and stripped[max(match.start() - 1, 0):match.start()] == "$":
            unit = "usd"
        found[(value, unit)] += 1
    taken = set(scale_at)
    for surface, value in figure_gate.word_numerals(_prep(text)):
        # First not-yet-used occurrence of this surface, so "three hours ... three days"
        # reads two different units rather than the first one twice. A hyphen reads as a
        # space: word_numerals joins "twenty-one" as "twenty one".
        pattern = r"\b" + re.escape(surface).replace(r"\ ", r"[\s-]+") + r"\b"
        for hit in re.finditer(pattern, stripped):
            if hit.start() not in taken:
                taken.add(hit.start())
                found[(value, _unit_after(stripped, hit.end()))] += 1
                break
    return found


def _small_words(text):
    """Counters for negations, modals and conditions."""
    words = _words(text)
    neg, mod, cond = Counter(), Counter(), Counter()
    for index, word in enumerate(words):
        if word.endswith("n't"):
            stem = word[:-3]
            neg["not"] += 1
            base = _NT_STEMS.get(stem, stem)
            if base in MODALS:
                mod[base] += 1
            continue
        if word.endswith("'ll"):
            mod["will"] += 1
            continue
        if word == "cannot":
            neg["not"] += 1
            mod["can"] += 1
        elif word in NEGATIONS:
            neg[word] += 1
        elif word in MODALS:
            mod[word] += 1
        elif word in CONDITIONS:
            cond[word] += 1
        elif word == "only" and index + 1 < len(words) and words[index + 1] in _ONLY_GATES:
            cond["only"] += 1
    # On the raw prepared text, not the joined word stream: joining drops the period, so
    # "decided by. Default is off." would manufacture a "by default" (PR #843 review).
    cond["by default"] += len(re.findall(r"\bby[ \t]+default\b", _prep(text)))
    return neg, mod, +cond


def _diff(before, after, render, allow_removals, presence=False):
    out = []
    for key in sorted(set(before) | set(after), key=str):
        delta = after[key] - before[key]
        if presence:
            # why presence for figures (ASK-5566, #632 review): marketer-ending and
            # substance-mechanism guidance say "facts already in the draft", so a repair
            # that restates "3 hours" is the instructed fix. A count compare read the
            # second mention as an ADDED figure, refused twice, and shipped the defect.
            delta = (after[key] > 0) - (before[key] > 0)
        if delta < 0 and allow_removals:
            continue
        if delta:
            out.append(("+" if delta > 0 else "-") + render(key))
    return out


def changes(original, revised, skip_numbers=False, allow_removals=False,
            skip_small_words=False, presence=False, removable=""):
    """Meaning-bearing tokens that differ between `original` and `revised`.

    `skip_numbers`: the revision was asked to fix a figure rule, which changes numbers by
    design (the figure gate re-judges them downstream).
    `allow_removals`: the revision was asked to cut (x-too-long), so a dropped token is
    expected. An ADDED token never is. A token dropped from a sentence the revision KEPT
    (a cut that deletes the "not" of a retained line) is a removal and is allowed here:
    removals are indistinguishable from the cut itself at multiset level.
    `presence`: figures compare as a set of (value, unit), so restating a figure the draft already
    has is not an added figure. Off by default: under the strict rules every figure must
    survive exactly and a second "3 hours" is a new claim. Only a span rewrite (marketer-ending,
    substance-mechanism: "facts already in the draft") turns it on (ASK-5566).
    `removable`: text the revision was told to delete (the banned phrase). The negations,
    modals and conditions inside it may go; the same words anywhere else may not.
    `skip_small_words`: the revision was asked to rewrite a span (every rule outside revise.STRICT_RULES),
    so negation/modal/condition drift inside it is not judged here.

    Limit, pinned by test_known_limit_the_compare_ignores_position: each compare is a
    multiset, so a token MOVED to another clause ("A is not B, C is D" -> "A is B, C is not
    D") or a figure pair reversed reads as intact.
    """
    out = {}
    if not skip_numbers:
        rows = _diff(_figures(original), _figures(revised),
                     lambda k: ("%g %s" % (k[0], k[1])).strip(), allow_removals,
                     presence=presence)
        if rows:
            out["numbers"] = rows
    if skip_small_words:
        return out
    n0, m0, c0 = _small_words(original)
    n1, m1, c1 = _small_words(revised)
    if removable:
        # why subtract from the BEFORE side: the phrase's own small words are expected to
        # vanish with it, and Counter `-` clamps at zero so a phrase can never excuse
        # more than it holds. A "not" elsewhere in the post still reads as dropped.
        rn, rm, rc = _small_words(removable)
        n0, m0, c0 = n0 - rn, m0 - rm, c0 - rc
    for name, before, after in (("negations", n0, n1), ("modals", m0, m1),
                                ("conditions", c0, c1)):
        rows = _diff(before, after, str, allow_removals)
        if rows:
            out[name] = rows
    return out


def describe(found):
    """One line for a trail: 'modals: -may +must; numbers: -3 hour +30 hour'."""
    return "; ".join("%s: %s" % (name, " ".join(rows)) for name, rows in found.items())


class MeaningRefused(Exception):
    """A revision changed a number, negation, modal or condition. Never a silent pass.

    Defined HERE, not in `revise`, and imported by type everywhere (PR #616 review, major):
    `gate_and_judge` receives `revise` as an injected argument, and production injects a
    SimpleNamespace (`post_envelope.revise_port`) with no such attribute, so catching it
    through the argument caught nothing and the refusal escaped the style lane. This is
    the same reason `GateRefused` is imported as a type. `revise.MeaningRefused` stays as
    an alias to this one class.

    An `Exception` on purpose: the decide ladder ("regenerator raised"), the critic
    ("reviser raised") and the editor revise already turn an exception into a discard
    whose reason carries `str(exc)`. `changes` is the dict from `changes()`.
    """

    def __init__(self, changes):
        self.changes = changes
        super().__init__("revision changed meaning (%s)" % describe(changes))
