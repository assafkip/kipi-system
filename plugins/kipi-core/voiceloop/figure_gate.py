#!/usr/bin/env python3
"""Every NUMBER in a post must exist in the post's own source artifact. The figure gate.

why this exists (2026-08-06, sp-3fb1630e): `provenance.py` proves a source EXISTS. It
does not prove the text FOLLOWS FROM it, and it says so in its own docstring. Sal's
adversarial read of the first post produced under the provenance regime demonstrated the
gap on real output rather than in the abstract: the post resolved cleanly against commit
213d7f1b and still described the March draft in terms softer than the record.

`substance_gate` made that worse in a way worth naming. It REQUIRES a bound number and
treats finding one as the post doing its job. It never asks where the number came from.
That is how "51,000+ lines across those systems" scored as a STRENGTH on the fabricated
biography: the fabrication was numerate, and numerate was the whole test.

So the number half of the substance rule is now NECESSARY AND NOT SUFFICIENT. A post
must carry a bound number (substance_gate) AND every figure it carries must be traceable
to the artifact its provenance names (this module).

## What is deterministic here, and it is only this

A numeral either occurs in the artifact text or it does not. That is a string lookup,
the same class of thing `provenance.resolve` does, and it is the entire mechanism.

Two DERIVATIONS are allowed. Both are arithmetic and neither is a judgement:

- fraction -> percent: the artifact says `648 of 776`, the post says `84%`.
- percent -> fraction: the artifact says `80%`, the post says `4 of 5`.

The second direction is not decorative. `revise.RULE_GUIDANCE["stats-citation"]`
instructs the reviser to restate a bare percentage as its underlying count, in those
exact words, with those exact examples. Without this derivation the repair ladder would
manufacture text that this gate then rejects -- two gates fighting, one slot lost per
collision, and the failure would read as a sourcing problem rather than as the gate
interaction it is. Found by writing the interaction test before the code.

## What this does NOT do, stated plainly because the last docstring that overclaimed is
## the reason this module exists

**It cannot see a fact that is ABSENT.** The incident that motivated this module was
softening by OMISSION: a post that said the March draft "sat approved for 5 months" and
left out that the engine PUBLISHED it, verbatim, with a fabricated biography, under the
founder's name. Every figure in that post was supported by its artifact. This gate would
have passed it, and it still would today.

That half is not closed and is not closeable by inspecting the post's text: there is no
string to match on for a sentence nobody wrote. Anything claiming otherwise would be the
same overclaim in a new file.

**It matches VALUES, not MEANINGS.** Measured 2026-08-06 in this module's own
adversarial pass: an artifact reading "we ranked the top 3 subreddits" vouches for a post
saying "we cut it to 3 attempts". The digit is there; the fact is not. Narrowing this
would mean binding each figure to the noun phrase it modifies, which is parsing, which is
judgement, which is the thing this module refuses to do. So the honest statement is that
this raises the cost of inventing a number rather than making it impossible: an invented
figure now has to COLLIDE with a real one in the same artifact.

**It does not check non-numeric characterisations.** "We shipped" against a commit
authored by one person is a false attribution and this module is silent on it. Naming a
heuristic for that was considered and dropped: a first-person-plural check false-positives
on the founder's ordinary voice, which uses "we" for the practice.

**It is silent when there is no artifact.** `check(text, None)` returns no violations.
A candidate with no resolvable source is the PROVENANCE gate's job and it never reaches
here. Returning a violation here too would double-report one defect.

## The kill switch is shared, on purpose

This reads `provenance.load_mode()` rather than owning a second switch. `off` disables
both, `warn` makes both advisory, and the existing banner ("nothing is checking that a
post came from anything real") stays true either way. Two switches would mean a founder
who turned "the provenance gate" off still had half of it running, which is the kind of
half-state that makes a person stop trusting the off button.
"""
from __future__ import annotations

import re

# Number words the generator actually produces. Deliberately small: this exists because
# commit prose says "five months" while a post says "5 months", which is the REFERENCE
# case for this whole module. A wide list would start matching "one" the article-ish
# pronoun and "a second" the time unit, inventing support that is not there.
WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "dozen": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "thousand": 1000, "million": 1000000,
}

# The multiplier words. "twenty thousand" is 20,000, not the two figures 20 and 1000.
_WORD_SCALES = {100.0, 1000.0, 1000000.0}

_SCALE = {"k": 1000, "m": 1000000, "b": 1000000000}

# A numeral with optional thousands separators, optional decimal, optional K/M/B scale.
_NUMERAL = re.compile(r"(?<![\w.])(\d[\d,_]*(?:\.\d+)?)\s*([kmb])?\b", re.I)

# Anything inside one of these is notation, not a claim about the world. A URL's `2026`
# is not the post asserting a year, and flagging it would train a reader to ignore the
# gate. `first_comment_for` puts a link on every post, so this is not a rare shape.
_NOISE = re.compile(r"https?://\S+|`[^`]*`|\S+@\S+\.\S+", re.I)

# `648 of 776`, `648/776`, `648 out of 776`. The denominator form the practice's own
# writing rule asks for ("so 648 of 776 and never most").
_FRACTION = re.compile(r"(\d[\d,_]*)\s*(?:of|out of|/)\s*(\d[\d,_]*)", re.I)
_PERCENT = re.compile(r"(\d[\d,_]*(?:\.\d+)?)\s*%")

RULE = "figure-unsourced"

# THE MODE VALUES, restated here rather than imported (2026-09-05, extraction slice 9).
#
# The deployment's `provenance` module owns the switch and reads it from disk; this
# gate only needs to know what its three answers LOOK like. Importing provenance from
# fleet code would drag a deployment module into the package, which is the thing this
# extraction exists to stop.
#
# Two definitions of one fact is a drift risk and it is not left to care: the
# deployment's suite asserts these are identical to provenance's, so a rename over
# there fails a test rather than silently turning this gate off.
ENFORCE, WARN, OFF = "enforce", "warn", "off"

# How many supported figures to name back to the reviser. The violation detail is the
# reviser's ONLY view of the artifact -- it never sees the commit -- so it has to carry
# the usable numbers or the guidance "use a number from the source" is unfollowable.
MAX_OFFERED = 12


def _to_value(digits, scale=None):
    """'51,000' -> 51000.0; ('1.9','K') -> 1900.0. None when it is not a number."""
    try:
        value = float(str(digits).replace(",", "").replace("_", ""))
    except (TypeError, ValueError):
        return None
    if scale:
        value *= _SCALE.get(scale.lower(), 1)
    return value


def _strip_noise(text):
    return _NOISE.sub(" ", text or "")


def numerals(text):
    """Every numeral in `text` as (surface, value). URLs, code spans and emails removed."""
    out = []
    for match in _NUMERAL.finditer(_strip_noise(text)):
        value = _to_value(match.group(1), match.group(2))
        if value is not None:
            out.append((match.group(0).strip(), value))
    return out


def word_numerals(text):
    """Figures written as WORDS in a post, as (surface, value). ASK-431's word-form half.

    why this exists (2026-08-06, ASK-431): the engine published "twenty copies", "a dozen
    copies" and "four times" to X, live, and this gate never saw any of them -- `_NUMERAL`
    is digits-only, so a word-form figure was never extracted and never checked against
    the artifact. An invented word-number cost the reviser nothing.

    "one" STANDING ALONE is deliberately not extracted: in his prose it is a pronoun far
    more often than a figure ("no one noticed", "one of the checks", "the one thing"),
    and a gate that flags his ordinary English gets switched off, after which it protects
    nothing. Inside a run ("twenty one") it can only be a number, so there it counts.

    Adjacent number words combine the way English does: "twenty thousand" is 20,000, not
    the two separate figures 20 and 1000 -- otherwise a legitimate restatement of an
    artifact's "20,000" would be flagged twice for values the artifact never states.
    """
    out = []
    run = []          # [(word, value)] for the current unbroken sequence of number words

    def flush():
        if not run:
            return
        total = cur = 0.0
        for _word, value in run:
            if value in _WORD_SCALES:
                cur = (cur or 1.0) * value
            else:
                total += cur
                cur = value
        out.append((" ".join(word for word, _ in run), total + cur))
        run.clear()

    for word in re.findall(r"[a-z]+", _strip_noise(text or "").lower()):
        value = WORD_NUMBERS.get(word)
        if value is None or (word == "one" and not run):
            flush()
            continue
        run.append((word, float(value)))
    flush()
    return out


def _word_values(text):
    """Values written as words. `five months` in a commit supports `5 months` in a post."""
    found = set()
    for word in re.findall(r"[a-z]+", (text or "").lower()):
        if word in WORD_NUMBERS:
            found.add(float(WORD_NUMBERS[word]))
    return found


def supported_values(source_text):
    """Every value the artifact vouches for, as floats. The lookup table, built once.

    Both word readings of the source count: the flat one (`_word_values`, where "one"
    supports 1) and the combined one (`word_numerals`, where "twenty thousand" supports
    20,000). The source side stays GENEROUS on purpose -- a value the artifact arguably
    states must vouch for the post, or the gate manufactures violations out of phrasing.
    """
    values = {value for _surface, value in numerals(source_text)}
    values |= _word_values(source_text)
    values |= {value for _surface, value in word_numerals(source_text)}
    return values


def _percents_from_fractions(source_text):
    """`648 of 776` in the artifact also vouches for `84%` in the post.

    Both the rounded integer and the one-decimal form, because a generator that computes
    a percentage picks its own precision and neither choice is an invention.
    """
    out = set()
    for numerator, denominator in _FRACTION.findall(_strip_noise(source_text)):
        top, bottom = _to_value(numerator), _to_value(denominator)
        if not bottom:
            continue
        pct = 100.0 * top / bottom
        out.add(round(pct))
        out.add(round(pct, 1))
    return out


def _fractions_from_percents(source_text):
    """`80%` in the artifact vouches for the counts in `4 of 5`.

    This exists because `revise.RULE_GUIDANCE['stats-citation']` tells the reviser to do
    exactly this conversion, naming '80%' -> '4 of 5'. A gate that rejected the repair
    ladder's own prescribed output would be two rules disagreeing, not a post being
    caught.

    ONLY the fraction in LOWEST TERMS, and only when its denominator is at most 20.

    why so tight (2026-08-06, caught by this module's own adversarial test): the first
    version walked every denominator from 2 to 20 and admitted any numerator that came
    out whole. One `80%` in an artifact then vouched for 4, 8, 12, 16, 20 and every
    denominator alongside them -- roughly thirty small integers from a single figure. The
    fabricated-biography test went GREEN against a real commit because "12 years" was
    manufactured by this function out of an unrelated `80%`. A derivation that invents
    support is worse than no derivation: it launders exactly the numbers this gate exists
    to catch. Lowest terms is the restatement a person would actually write, which is
    what the reviser is instructed to produce, and 80% yields {4, 5} and nothing else.
    """
    from fractions import Fraction

    out = set()
    for surface in _PERCENT.findall(_strip_noise(source_text)):
        pct = _to_value(surface)
        if pct is None:
            continue
        ratio = Fraction(pct).limit_denominator(10000) / 100
        if 2 <= ratio.denominator <= 20:
            out.add(float(ratio.numerator))
            out.add(float(ratio.denominator))
    return out


# THE ILLUSTRATIVE EXEMPTION (2026-08-12, Amber's ruling under RULE-2026-08-12-F).
#
# The conflict she was handed: the founder said "I dont care if numbers are made up, but I
# want interesting posts", and this gate binds every numeral to the post's own artifact.
# Her ruling is deliberately narrower than his literal words, and her reason is the only
# thing that matters here: a number presented AS A MEASURED FACT is a claim a reader can
# rely on, repeat, or catch him lying about. Loosening wholesale would let a fabricated
# statistic back in with nothing but the writer's judgment between it and his name, which
# is the exact condition that produced the "51,000+ lines" incident this module exists for.
#
# So exactly one path is exempt, and it needs THREE independent conditions to hold:
#
#   ROUND        the shape of an estimate, not of a measurement
#   MARKED       the sentence says outright that the number is a stand-in
#   UNATTACHED   no real named person, company or incident in that sentence
#
# Each condition is separately load-bearing and each is separately pinned in
# `test_figure_gate_illustrative.py`: a round number stated as a finding stays refused, a
# falsely precise number inside an illustrative frame stays refused, and a round marked
# number attached to a name stays refused. Drop any one condition and one of those three
# goes green.
#
# FAIL CLOSED, in her words: "I would rather lose a good illustrative number than let one
# more fabricated 'measured' figure ship under his name." Every ambiguity below therefore
# resolves toward demanding the source match.

# Sentence-scoped, not post-scoped. A name three sentences away must not cost an honest
# illustration, and an illustration in one sentence must not vouch for a measurement in
# the next. Split AFTER `_strip_noise` so a url's dots cannot manufacture a boundary.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

# The markers, as a CLOSED set. A wide list would start reading ordinary hedges
# ("roughly", "about") as illustrative framing, and a hedge is not a disclaimer: "roughly
# 40,000 postings" still claims he counted postings. Each entry here states that the
# number is a stand-in rather than something he found.
#
# "say" is required to be followed by an article or a pronoun. Bare "say" is far more
# often the verb ("they say it works", "the docs say"), and a marker that fires on his
# ordinary English would exempt numbers nobody framed as illustrations.
_ILLUSTRATIVE = re.compile(
    r"\b(?:"
    r"let'?s\s+say"
    r"|say\s+(?:a|an|the|you|your|some|its|it's)\b"
    r"|suppose"
    r"|imagine"
    r"|hypothetical(?:ly)?"
    r"|pretend"
    r"|for\s+the\s+sake\s+of\s+argument"
    r"|made[-\s]up\s+number"
    r"|pick\s+a\s+number"
    r")", re.I)


def _sentences(text):
    """The post's sentences, noise already stripped. Empty ones dropped."""
    return [s for s in _SENTENCE_SPLIT.split(_strip_noise(text or "")) if s.strip()]


def is_round(value):
    """A number with ONE significant digit. 40000 yes, 1500 no, 51000 no, 12 no.

    One significant digit is the arithmetic version of "the shape of an estimate". It
    admits 5, 40, 200, 40000; it refuses 12, 1500, 40560 and 51000, which are the shapes a
    reader reads as counted. `12` failing this matters on its own: a tenure figure can
    never reach the exemption, whatever sentence it sits in.
    """
    if value is None or value <= 0 or value != int(value):
        return False
    digits = str(int(value))
    return len(digits.rstrip("0")) == 1


def names_a_real_entity(sentence):
    """True when the sentence carries a proper noun, so the exemption must not fire.

    Amber: "that last clause is load-bearing. An illustrative number about a generic,
    unnamed shop is fine; the same number attached to a real client name is not
    illustrative anymore, it is a false claim about a real business."

    A capitalized word anywhere but the first position, which is the same heuristic
    `name_gate._person_shape_signals` uses and it is labelled a heuristic there for the
    same reason. It over-fires: a mid-sentence "AI" or "Monday" costs an illustration.
    That direction is the one Amber asked for -- losing a good number is cheap, laundering
    a fabricated one is not -- so it is not tuned down.
    """
    words = re.findall(r"[A-Za-z][\w'’-]*", sentence or "")
    return any(word[0].isupper() for word in words[1:])


def _sentence_exempts_round_numbers(sentence):
    """Both non-value conditions, per sentence. Roundness is applied per figure."""
    return bool(_ILLUSTRATIVE.search(sentence)) and not names_a_real_entity(sentence)


def unsupported(text, source_text):
    """[(surface, value)] for every figure in `text` the artifact does not vouch for."""
    # A non-string source is NO source. `decide_slot` is deliberately ignorant of what an
    # origin IS and hands back whatever object it was given, so a caller that passes
    # `(label, body)` pairs reaches here with a tuple. Regexing that raises TypeError deep
    # inside a gate, which would surface as a broken linter rather than as a missing
    # artifact. Silence is the honest verdict: we could not read the source.
    if not isinstance(source_text, str) or not source_text:
        return []
    direct = supported_values(source_text)
    derived = _percents_from_fractions(source_text) | _fractions_from_percents(source_text)
    allowed = {float(v) for v in direct | derived}
    bad = []
    # WALKED PER SENTENCE so the illustrative exemption is scoped to the sentence that
    # frames the number. Post-scoped would mean one "say a shop..." anywhere vouches for
    # every round figure in the post, which is a laundering path, and it would also let a
    # name three sentences away kill an honest illustration. Concatenating the sentences
    # reproduces the old whole-text walk exactly, because `_strip_noise` runs before the
    # split and both extractors strip again idempotently.
    for sentence in _sentences(text):
        exempt = _sentence_exempts_round_numbers(sentence)
        # Digit figures AND word figures. The word half is ASK-431: "twenty copies"
        # shipped live because only digits were ever extracted from the post.
        for surface, value in numerals(sentence) + word_numerals(sentence):
            if value in allowed:
                continue
            # A percentage the post computed from a fraction the artifact carries. Checked
            # per-figure rather than folded into `allowed` so the rounding tolerance stays
            # attached to the percent form and does not loosen plain integer matching.
            if any(abs(value - candidate) <= 0.5 for candidate in
                   _percents_from_fractions(source_text)) and "%" in surface:
                continue
            if exempt and is_round(value):
                continue
            bad.append((surface, value))
    return bad


def offered_figures(source_text, limit=MAX_OFFERED):
    """The artifact's own figures, as text, for the reviser's instruction."""
    seen, out = set(), []
    for surface, value in numerals(source_text or ""):
        if value in seen:
            continue
        seen.add(value)
        out.append(surface)
        if len(out) >= limit:
            break
    return out


def check(text, source_text, mode=ENFORCE):
    """Violations in the gates' shape. Empty list means every figure traces to the source.

    `source_text=None` is SILENCE, not a pass and not a failure: a candidate with no
    resolvable artifact is refused upstream by the provenance gate, and reporting it here
    as well would turn one defect into two log lines.

    `mode` DEFAULTS TO ENFORCE, and the direction of that default is the point
    (2026-09-05, extraction slice 9). Before the split this argument defaulted to None
    and the gate read the deployment's switch itself; a fleet package cannot do that,
    because `provenance` reads one operator's file off disk. The three production
    callers -- `decide`, `gate_scope`, `verify_deployed` -- now resolve the mode and
    pass it, so the default is what a caller that says NOTHING gets.
    
    Fail-closed, therefore. A caller who forgets gets the gate ON. The alternative
    default is a package that silently stops checking figures for anyone who does not
    know to ask, which is the same shape as the config path that returned {} and the
    corpus path that returned [] elsewhere in this extraction.
    """
    if mode == OFF:
        return []
    bad = unsupported(text, source_text)
    if not bad:
        return []
    figures = ", ".join(sorted({surface for surface, _ in bad}))
    offered = offered_figures(source_text)
    detail = (f"figure(s) not found in the source this post came from: {figures}. "
              f"A number that is not in the artifact was invented or carried in from "
              f"somewhere else, which is how '51,000+ lines' shipped.")
    if offered:
        detail += f" Numbers the source actually contains: {', '.join(offered)}."
    else:
        detail += " The source contains no numbers at all."
    return [{"rule": RULE, "line": 1, "warn_only": mode == WARN,
             "detail": detail}]


def report(text, source_text):
    """Human-readable verdict, for the CLI."""
    violations = check(text, source_text)
    if not violations:
        count = len(numerals(text))
        return f"figures: ok ({count} figure(s), all present in the source)"
    return "figures: " + violations[0]["detail"]


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("usage: figure_gate.py <post-file> <source-artifact-file>", file=sys.stderr)
        raise SystemExit(2)
    with open(sys.argv[1], encoding="utf-8") as handle:
        post = handle.read()
    with open(sys.argv[2], encoding="utf-8") as handle:
        source = handle.read()
    print(report(post, source))
    raise SystemExit(1 if check(post, source) else 0)
