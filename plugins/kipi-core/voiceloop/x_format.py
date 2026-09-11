#!/usr/bin/env python3
"""X's own format rules, as a gate. Item 4b: LENGTH.

why this exists (prd-content-engine-sameness-2026-08-09, item 4): `build_prompt` took
no channel until item 4a, so every X slot was written against LinkedIn's rules -- "120
to 250 words", which is roughly 700 characters, on a channel that takes 280.

## The size of the problem, with its denominator stated

**29 of 29 MEASURABLE X bodies are over 280.** Not most. All of them. The shortest is
981 and the longest is 1428, so the 981-char body the parent PRD offers as an example
is the MINIMUM, not an outlier.

The denominator matters and the first version of this docstring got it wrong, in the
exact way the sibling issue in this PRD was built to prevent. It said "30 of 30
published X bodies", measured with `postbook.archived_rows()`. That is the UNREFUSING
path. `postbook.corpus_bodies("x")` exists to answer this question and REFUSES to,
naming three published X posts with no archived body -- so a rate over the archive is
a rate over a silently reduced denominator, which is the move
`archive-validity-joins-ledger` withdrew a claim for one issue earlier. Caught by the
adversarial review; recorded here rather than quietly corrected.

The honest population: **32** distinct published X post ids, of which **29** have an
archived body and 3 do not, plus 1 archived X row with no published-X ledger row at
all. So "no X post the engine has published would pass this gate" is a claim about 32
backed by 29, and it is written that way on purpose.

## Why a gate and not just a line in the prompt

`generate.py:130`'s own comment already records the answer: a model told "output only
the post" still opens with "Here's the post:" often enough that it has to be stripped
rather than requested. An instruction is a request. This is the enforcement.

## Scope

LENGTH only. Paragraph shape is editorial, not an X platform limit, so short posts and
long-form X articles are both valid. Hashtag / emoji / in-body-link rules have their
own fixtures because they fail in unrelated ways.
"""
from __future__ import annotations

import re
import unicodedata

# FOUNDER-DIRECTED 2026-08-09, verbatim: "I have x premium. I can do more than 280
# chars." This account is on X Premium, so the hard limit is 25,000 weighted units and
# NOT 280.
#
# The correction matters more than the number. This gate shipped with a 280 BLOCK, and
# 280 is not a limit for this account -- it is an editorial preference. Measured: it
# would have rejected all 29 measurable published X bodies, min 981, max 1428. A gate
# that rejects 100% of the founder's own published writing is not enforcing a platform
# rule, it is silently imposing an editorial one nobody agreed to. The tier was flagged
# as an unverified premise (sp-9d2ce0b4) precisely because nobody had recorded it; the
# founder answered, and the shipped answer was wrong.
X_MAX_CHARS = 25000

# The RESEARCHED target, and it is not the platform limit.
#
# `platforms.md` (the same audience research best-times.json is built on) says of X:
# "Tweets under 100 characters get more engagement." That is a reach finding, not a
# rule about what fits, and it is the only X-specific length evidence this fleet holds.
#
# Measured against it, every X post ever published here is a LinkedIn post: word counts
# run 187 to 253 against a prompt that said "120 to 250 words", because X had no format
# of its own until 2026-08-09 and inherited LinkedIn's. 27 of 29 sit inside LinkedIn's
# range. The shortest is 981 characters, roughly ten times the researched target.
#
# TARGET, not a cap, and deliberately NOT a per-post violation row.
#
# It reaches the model through the PROMPT and is measured in `sameness.report`. It was
# briefly a warn_only gate row and that was wrong: warnings are recorded to the postbook,
# nearly every post exceeds 100 characters, so it fired on almost everything and wrote a
# ledger row each time. A signal that fires constantly is the cry-wolf failure this
# codebase keeps writing scars about, and a gate here would be the checklist mistake
# again in a new costume.
#
# The founder has Premium so nothing truncates until 25,000. The research earns a nudge
# in the instruction and a number in the report, never a veto.
X_TARGET_CHARS = 100

# The timeline FOLD, not a limit. X collapses a long post behind "Show more" at roughly
# this length, so the ending every other gate just checked is not the ending a scrolling
# reader sees. That is worth reporting and is never worth killing a slot for, so it is a
# `warn_only` row -- the same posture voicefp_gate uses for a degraded engine. Reported,
# never blocking.
X_FOLD_CHARS = 280

# X does NOT count characters, and `len()` was wrong in BOTH directions (adversarial
# review, 4b). It counts WEIGHTED units after NFC normalisation: the ranges below weigh
# 1, everything else weighs 2, and every URL counts a flat 23 whatever its real length.
#
# Measured against the real rule:
#   a 200-char Japanese body  -> len 200, weighs 400 -> PASSED a gate X would truncate
#   a 158-char emoji run      -> len 158, weighs 288 -> PASSED a gate X would truncate
#   a body with a 54-char URL -> len 305, weighs 274 -> DISCARDED a post that fits
#
# The false negative is the gate failing at its one job: a post it passes still loses
# the ending, which the violation text explicitly promises to protect.
_LIGHT_RANGES = ((0x0000, 0x10FF), (0x2000, 0x200D), (0x2010, 0x201F), (0x2032, 0x2037))
_LIGHT_WEIGHT = 100
_DEFAULT_WEIGHT = 200
_SCALE = 100
_URL_WEIGHT = 23

# URLs, WITH OR WITHOUT a scheme. twitter-text's own `urls_without_protocol` group
# asserts `example.com`, `www.example.com`, `t.co` and `foo.co.jp` are URLs, and charges
# each a flat 23. The first version matched `https?://` only, so a schemeless link was
# counted letter by letter and the gate PASSED posts X truncates (adversarial round 2).
#
# The TLD list is deliberately short rather than the full IANA set: a long alternation
# here would start matching ordinary prose like "etc.io" written mid-sentence, and a
# false URL costs 23 units against a 280 budget. These are the ones this account
# actually links.
_URL = re.compile(
    r"""(?:
        https?://\S+                              # any scheme-ful URL
      | (?<![\w@.])                               # not mid-word, not an email
        (?:www\.)?[\w-]+(?:\.[\w-]+)*
        \.(?:com|org|net|io|dev|co|ai|app|me|sh|jp|uk)
        (?:\.[a-z]{2})?                           # co.jp, co.uk
        (?:/\S*)?
    )""", re.I | re.X)

# One emoji ENTITY weighs `_DEFAULT_WEIGHT`, no matter how many code points it is
# built from. `config/v3.json` sets emojiParsingEnabled, and twitter-text's parseTweet
# adds one defaultWeight per entity then skips the rest of its code points.
#
# Measured before this existed: a single family emoji is 7 code points and scored 11
# units where X says 2, so 140 of them scored 1540 against X's 280 -- a conformance
# case X marks VALID that this gate rejected outright. Six of the eleven conformance
# failures were this one class.
#
# Matched structurally rather than from an emoji table: base, then any run of variation
# selectors, skin-tone modifiers, keycap marks and ZWJ-joined continuations. A table
# would be a copy of Unicode that goes stale every release.
_EMOJI_BASE = (
    "\U0001F000-\U0001FAFF"      # the emoji planes
    "☀-➿"              # misc symbols and dingbats
    "←-⇿⬀-⯿"  # arrows and misc symbols/arrows
    "\U0001F1E6-\U0001F1FF"      # regional indicators (flags)
    "#*0-9"                      # keycap bases, only when followed by U+20E3
)
_EMOJI_SEQUENCE = re.compile(
    "[" + _EMOJI_BASE + "]"
    "(?:[︎️⃣]|[\U0001F3FB-\U0001F3FF]|[\U0001F1E6-\U0001F1FF])*"
    "(?:‍[" + _EMOJI_BASE + "]"
    "(?:[︎️⃣]|[\U0001F3FB-\U0001F3FF])*)*")


def _char_weight(char):
    point = ord(char)
    for low, high in _LIGHT_RANGES:
        if low <= point <= high:
            return _LIGHT_WEIGHT
    return _DEFAULT_WEIGHT


def weighted_length(text):
    """X's own unit count for `text`. The instrument, and never `len()`.

    NFC first, because a decomposed e-acute is two code points and one unit -- so the
    same visible post could pass or fail depending only on how it was typed.
    """
    body = unicodedata.normalize("NFC", text or "")
    total = 0
    cursor = 0
    for match in _URL.finditer(body):
        total += _weigh_run(body[cursor:match.start()])
        total += _URL_WEIGHT * _SCALE
        cursor = match.end()
    total += _weigh_run(body[cursor:])
    return total // _SCALE


def _weigh_run(run):
    """Weigh a stretch of non-URL text, charging ONE default weight per emoji entity."""
    total = 0
    cursor = 0
    for match in _EMOJI_SEQUENCE.finditer(run):
        total += sum(_char_weight(c) for c in run[cursor:match.start()])
        total += _DEFAULT_WEIGHT
        cursor = match.end()
    total += sum(_char_weight(c) for c in run[cursor:])
    return total


def length_violations(text, channel):
    """Violations in the gates' shape, so callers merge reports without special-casing.

    Channel-scoped and SILENT on every channel but x -- `figure_gate`'s posture, and
    for the same reason: a gate that fires where it does not apply gets switched off,
    and this one would fire on every LinkedIn post ever written.

    Counted in X's WEIGHTED units, not words and not `len()`. The defect being fixed is
    a word-count rule ("120 to 250 words") applied to a length-limited channel, and
    replacing it with the wrong length instrument would only move the error.

    TWO THRESHOLDS, and only one of them blocks. The block is TRUNCATION (25,000 on
    Premium): past it the platform cuts the post and the ending is lost. The warning is
    the FOLD (280): the post survives intact, but the timeline collapses it behind
    "Show more", so the ending is one click away rather than gone.

    Keeping them apart is the whole correction. Blocking at the fold rejected every one
    of the 29 measurable published bodies, which is not a platform rule being enforced;
    it is an editorial preference being imposed under a platform rule's name.
    """
    if channel != "x":
        return []
    body = text or ""
    weighted = weighted_length(body)
    if weighted > X_MAX_CHARS:
        return [{
            "rule": "x-too-long",
            "line": 1,
            "detail": (
                f"this is {weighted} units and X truncates past {X_MAX_CHARS}. The "
                f"ending the gates just checked is not the ending a reader sees. Cut "
                f"it. Do not summarise the long version -- a compressed long post "
                f"reads like a compressed long post, which is the sameness this is "
                f"meant to end."),
        }]
    if weighted > X_FOLD_CHARS:
        return [{
            "rule": "x-past-the-fold",
            "warn_only": True,
            "line": 1,
            "detail": (
                f"this is {weighted} units, so X shows about {X_FOLD_CHARS} and "
                f"collapses the rest behind 'Show more'. Nothing is lost and nothing "
                f"is blocked; the ending is one click from the timeline."),
        }]
    return []


def blocks(text):
    """Non-empty paragraph blocks."""
    return [b for b in re.split(r"\n\s*\n", text or "") if b.strip()]
