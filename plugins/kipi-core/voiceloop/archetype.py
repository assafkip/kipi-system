#!/usr/bin/env python3
"""Post STRUCTURE, and only structure. The layer between his voice and the platform.

why this exists (founder-directed 2026-08-24, verbatim: "I want the voice to change so it
writes the posts within the parameters of these archetypes. It needs to keep everything
else and not change except the structure of the post."):

`x-viral-template.md` v2 measured within-author lift across 5,722 posts from 51 accounts
and found the shape of a post moves engagement independently of what it says. A thread
starter with a colon-ending setup line runs 1.67x its author's own median. A single short
line with no artifact runs 0.78x, the worst combination in the corpus, and that is the
shape the first version of the template recommended first.

## The line this module is not allowed to cross

`build_idea_prompt` was reset to "idea + voice file, that's it" on 2026-08-13 after a
constraint stack went 0-for-7 on the founder's read in one evening. That stack failed
because it dictated CONTENT: story frames, source rules, what a post should be about,
which register to use. It laundered his words.

This module dictates SHAPE: how many lines, what the opening line does, where a list
goes, whether the post opens a reply chain. It says nothing about word choice, subject,
register, or what the post argues. That distinction is the entire justification for
re-adding a block to that prompt, and `test_archetype.py` holds it: the rendered section
is asserted to carry no worked example and no content directive.

If a future edit puts a sentence about WHAT to say into `config/post-archetypes.json`,
the 2026-08-13 failure is back and this docstring is the record of what it cost.

## Single source of truth

The archetypes live in `config/post-archetypes.json`, read every render, the same shape
`channel_guidance` uses and for the same reason: the copy belongs to whoever owns the
copy, and editing a data file must not require a code change. A missing or malformed
file degrades to NO structural block rather than raising. A generator that refuses to run
because a config moved is worse than one that writes the way it did last week.
"""
from __future__ import annotations

import json
import os
import re

# NO CONFIG PATH LIVES HERE, deliberately (2026-09-05, extraction slice 7).
#
# This module used to resolve `config/post-archetypes.json` from __file__. Inside one
# deployment that is correct and invisible; inside a package that ships fleet-wide it
# points every operator at whichever table sits beside the code. And the degradation
# is silent by design: `load` returns {} on any read failure and never raises, so a
# move would have left `select` choosing from an EMPTY archetype table without one
# test going red. Same trap as `form` in slice 4b, one file over.
#
# So `load` takes its path. The deployment binds it.

# The character half of the retired hot-take finding. The corpus measured 0.78x on
# posts that were one line AND under this length AND carried no artifact; each
# condition on its own measures something different, so the card checks all three.
HOT_TAKE_MAX_CHARS = 140

# The card is advisory text for the founder, never a gate. Nothing in this module can
# refuse a draft; the gate stack remains the only thing that can.
_UNKNOWN = {"id": None, "name": None}


def load(path):
    """The archetype table, or {} if it cannot be read. Never raises."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _archetypes(data):
    return (data or {}).get("archetypes") or {}


def select(idea_text, channel, path, forced=None):
    """Pick the archetype for this idea. Deterministic, and it shows its work.

    Returns (archetype_id, archetype_dict, why). `why` is a sentence naming the signal
    that decided it, because a silent structural choice is one the founder cannot argue
    with and this whole layer is a hypothesis he is meant to be able to overrule.

    Signal matching is on WHOLE WORDS for alphabetic signals. The first version matched
    substrings and 'first' fired inside 'first-party', which routed an idea about data
    into the how-to skeleton for a reason nobody could see. Non-alphabetic signals ('%',
    '$') keep substring matching because a word boundary around punctuation matches
    nothing.
    """
    data = load(path)
    table = _archetypes(data)
    if not table:
        return None, {}, "no archetype config, structure left to the writer"

    if forced:
        if forced not in table:
            raise UnknownArchetype(
                f"{forced!r} is not an archetype; known: {sorted(table)}")
        return forced, table[forced], f"forced to {forced} by the caller"

    text = (idea_text or "").lower()
    # Ordered, most specific first. `default` is consulted last and is the one with the
    # strongest evidence, so an idea that matches nothing still gets the best shape.
    for arch_id in ("receipt", "howto"):
        entry = table.get(arch_id)
        if not entry:
            continue
        for signal in entry.get("signals") or []:
            token = signal.lower()
            if token.isalpha():
                # NOT \b: a hyphen IS a word boundary, so \bfirst\b matched inside
                # 'first-party' and routed a data idea into the how-to skeleton for a
                # reason nobody could see in the trail (caught by
                # test_signals_match_whole_words_not_substrings, 2026-08-24).
                hit = re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", text)
            else:
                hit = token in text
            if hit:
                return arch_id, entry, (
                    f"the idea mentions {signal!r}, which is the {arch_id} signal")

    default_id = (data.get("default") or "thread")
    entry = table.get(default_id)
    if not entry:
        return None, {}, "the configured default archetype is missing from the table"
    return default_id, entry, (
        "nothing more specific matched, so this is the default, "
        "which also carries the strongest evidence in the corpus")


class UnknownArchetype(ValueError):
    """A forced archetype the config has no entry for. Loud, because the quiet version
    silently writes the default under the caller's chosen name."""


def skeleton_section(entry, channel="x"):
    """The STRUCTURE instruction handed to the writer. Structure only.

    Returns "" for an empty entry so a degraded config produces the pre-2026-08-24
    prompt exactly, rather than a prompt with an empty heading in it.
    """
    if not entry:
        return ""
    lines = entry.get("skeleton") or []
    if not lines:
        return ""
    out = ["STRUCTURE (shape only; the words, the subject and the voice stay his):"]
    out.extend(f"- {line}" for line in lines)
    lo, hi = (entry.get("lines") or [None, None])[:2] or (None, None)
    if lo and hi:
        out.append(f"- The finished post is between {lo} and {hi} lines.")
    return "\n".join(out)


def _line_count(text):
    return len([line for line in (text or "").split("\n") if line.strip()])


def posting_card(entry, arch_id, why, draft, channel, path):
    """How to actually post it. Advisory, deterministic, printed under the draft.

    This is the half of the founder's ask that the writer cannot answer: whether to open
    a reply chain, whether an image is required and what it has to show. It reads the
    FINISHED draft so what it reports is the post that exists, not the post that was
    requested.
    """
    data = load(path)
    entry = entry or {}
    lines = _line_count(draft)
    card = {
        "archetype": arch_id,
        "archetype_name": entry.get("name"),
        "why_this_archetype": why,
        "evidence": (entry.get("evidence") or {}).get("primary"),
        "supporting_evidence": (entry.get("evidence") or {}).get("supporting") or [],
        "channel": channel,
        "lines_in_draft": lines,
    }

    wants_thread = entry.get("thread")
    if wants_thread is True:
        card["thread"] = ("YES. Post this, then reply to it with the detail. The reply "
                          "chain is where the numbers and the mechanism go.")
    elif wants_thread == "optional":
        card["thread"] = ("Optional. A reply chain lifts it, and threading costs nothing "
                          "if the opening post already stands alone.")
    else:
        card["thread"] = "Not required."

    image = entry.get("image")
    guidance = data.get("image_guidance") or {}
    if image == "required":
        card["image"] = "REQUIRED. This archetype is the artifact; without it the post is a bare claim."
    elif image == "optional":
        card["image"] = ("Optional. Add one only if it carries evidence the text is "
                         "claiming. A photo on its own measures 1.04x, which is nothing.")
    else:
        card["image"] = "Not required."
    if image in ("required", "optional"):
        card["image_must_show"] = guidance.get("kinds") or []
        card["image_never"] = guidance.get("avoid") or []
        card["image_principle"] = guidance.get("principle")

    expected = entry.get("lines") or []
    if len(expected) == 2 and expected[0] and expected[1]:
        lo, hi = expected
        if lines < lo or lines > hi:
            card["line_count_warning"] = (
                f"the draft is {lines} lines; this archetype measures best at "
                f"{lo} to {hi}. Not a refusal, just the number.")

    retired = (data.get("retired") or {}).get("hot_take") or {}
    # BOTH halves of the finding, not one. The 0.78x measurement is one line AND under
    # 140 characters AND no artifact. The first version dropped the length condition and
    # fired on a 300-character single-paragraph thread starter, which is a different
    # shape entirely and the opposite of the one being warned about (caught on the first
    # real end-to-end run, 2026-08-24).
    body = (draft or "").strip()
    if lines == 1 and len(body) <= HOT_TAKE_MAX_CHARS and image != "required":
        card["warning"] = (
            "a single short line with no artifact is the worst-measuring shape in the "
            "corpus: " + (retired.get("why") or ""))
    return card


def render_card(card):
    """The card as plain text for a terminal. One block, no tables, scannable."""
    if not card:
        return ""
    out = ["=== HOW TO POST THIS ==="]
    name = card.get("archetype_name") or card.get("archetype") or "unknown"
    out.append(f"Archetype: {name}")
    out.append(f"Why: {card.get('why_this_archetype')}")
    if card.get("evidence"):
        out.append(f"Evidence: {card['evidence']}")
    out.append(f"Thread: {card.get('thread')}")
    out.append(f"Image: {card.get('image')}")
    if card.get("image_must_show"):
        out.append("Image must show one of:")
        out.extend(f"  - {kind}" for kind in card["image_must_show"])
        out.append("Never:")
        out.extend(f"  - {kind}" for kind in card.get("image_never") or [])
    if card.get("line_count_warning"):
        out.append(f"Note: {card['line_count_warning']}")
    if card.get("warning"):
        out.append(f"WARNING: {card['warning']}")
    return "\n".join(out)
