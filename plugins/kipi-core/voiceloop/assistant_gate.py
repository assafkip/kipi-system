#!/usr/bin/env python3
"""Reject text that is the ASSISTANT talking, not a post. The deliberation gate.

why this exists (2026-08-06): a live run published this to LinkedIn, under the founder's
name, and all eight existing gates passed it:

    "I'm not going to write this one as-is. The source material is an internal incident
     report about a bug in your own automation ... That's a real content choice, not a
     formatting task, and it's yours to make, not mine to make silently."
     ...
    "My call: **A**. The mechanism is genuinely useful ..."
    "Which one? Say A, B, or park, and I write it. If A, one thing I need from you: ..."

The model REFUSED the job and asked the founder a question. The refusal was published as
the post. It also said "a bug in ASK's own tooling" in public.

## Why nothing caught it

Every gate in the stack asks about the WRITING. `post_repair` asks if the prose is clean,
`substance_gate` if there is a number and a mechanism, `ending_gate` how it closes,
`bio_gate` and `figure_gate` whether the claims are true, `name_gate` whose name is in it.
`source_shape` is the closest -- it catches RAW MINED MATERIAL that was never rewritten --
but this text was not mined. It was generated. It is fluent, first-person, correctly
punctuated, ends on a question, and contains no client name and no false claim.

Nothing asked the only question that would have caught it: **is this addressed to the
reader, or to the operator?**

## The honest split, stated the way name_gate and ending_gate state theirs

- **EXACT (`_refusal_signals`).** The model declining or deferring the task. "I'm not
  going to write", "yours to make, not mine", "I need from you", "say A, B, or park".
  Zero judgement: these are never a post, in any context, on any channel.
- **EXACT (`_meta_signals`).** Text that talks ABOUT the writing task rather than to a
  reader: "the source material", "the hard rules", "as-is", "the prompt". A post is about
  the work; these are about producing the post.
- **EXACT (`_markdown_signals`).** Bold markers and heading syntax. Neither LinkedIn nor X
  renders markdown, so `**A**` reaching a timeline is either assistant formatting or a
  leaked template. Cheap, and it fired on the real incident.
- **HEURISTIC (`_option_menu_signals`), and it is labelled one.** An A/B/C menu with a
  recommendation. This is the shape of the incident, but a legitimate post could number
  three options for a reader, so it needs two of three markers before it counts.

## What this does NOT do

**It cannot tell a refusal from a well-written post about refusing.** A post that opens
"I told a client I'm not going to build that" is about the founder's work, not the
model's, and this gate will flag it. That is a deliberate false-positive bias: the cost of
a blocked good post is one refilled slot, and the cost of a miss is the founder's timeline.

**It reads phrasing, not intent.** A model that declines in words this list does not carry
passes. The list grows from real incidents rather than from imagination, the same way
`ending_gate`'s closer list did.
"""
from __future__ import annotations

import re

RULE = "assistant-deliberation"

# The model declining, deferring, or asking the founder to choose. Never a post.
_REFUSAL = (
    "i'm not going to write", "i am not going to write", "i won't write",
    "i will not write", "i'm not writing this", "not mine to make",
    "yours to make", "yours to decide", "your call, not mine",
    "i need from you", "i'd need from you", "one thing i need",
    "say a, b, or park", "let me know which", "which one do you want",
    "tell me which", "and i write it", "and i'll write it",
    "my call:", "my recommendation:", "my pick:",
    # NOT "should i", "shall i" or "want me to" (removed 2026-08-06, same hour they were
    # added). They caught a REAL founder draft, `2026-03-17-claude-code-only.md`, because
    # "Should I trust it?" is an ordinary rhetorical question and question-as-dagger is a
    # named pattern in his voice. A gate that eats his own drafts gets switched off, and a
    # gate that is off protects nothing. The incident text is still blocked several times
    # over by the phrases above, so nothing was traded away to remove them.
)

# Talking ABOUT the writing task instead of to a reader. UNAMBIGUOUS ONLY: every entry
# here names the production of THIS post and can never be the subject of one.
_META = (
    "the source material", "source material is", "the hard rules",
    "a formatting task", "turning it into a linkedin post",
    "turning it into a post", "write this one", "content choice",
)

# The same nouns, but they are also ordinary SUBJECT MATTER for someone who builds LLM
# systems. On their own they are not evidence of anything (ASK-577).
#
# why this split exists: four entries sat in `_META` as hard blocks, and a post about
# prompt leakage -- clean on every other gate -- was rejected for the literal words "the
# prompt". Founder-directed 2026-08-09: "I'm building AI systems, llm systems. the posts
# say systems but no one knows I'm talking about ai." The gate rejected the genre he
# chose.
#
# This file already made this exact fix once. "should i" / "shall i" / "want me to" were
# added and removed within the hour on 2026-08-06 because they ate a real founder draft,
# and the reason is recorded above: a gate that eats his own drafts gets switched off,
# and a gate that is off protects nothing. These four are the same mistake, unnoticed
# only because nobody had written an AI-domain post yet.
_META_AMBIGUOUS = ("as-is", "the prompt", "this draft", "the draft")

# What actually separates deliberation from subject matter: deliberation is ADDRESSED TO
# THE OPERATOR. "The prompt carried five examples" is a fact about a system. "I can
# rewrite the prompt if you want" is a message to the operator. The nouns are identical; the
# second person and the offer are the signal.
#
# Deliberately NOT bare "should i" / "shall i" -- see the note above. These require an
# offer or a hand-back, not a question.
_OPERATOR_ADDRESS = (
    "if you want", "if you'd like", "if you like", "let me know",
    "i can rewrite", "i can write", "i can make", "want me to",
    "your call", "tell me which", "which you prefer", "and i'll write",
    "and i write it",
)

# Neither LinkedIn nor X renders markdown. Bold or heading syntax on a timeline is
# assistant formatting or a leaked template.
_MARKDOWN = re.compile(r"\*\*\S|^#{1,6}\s", re.M)

# HEURISTIC. An options menu with a recommendation.
_OPTION_LABEL = re.compile(r"^\s*\*{0,2}([ABC])[.)]\s", re.M)
_PARK = re.compile(r"\bpark it\b|\bor park\b", re.I)


def _refusal_signals(lowered):
    return [f"refusal or hand-back: {p!r}" for p in _REFUSAL if p in lowered]


def _addresses_the_operator(lowered):
    return any(p in lowered for p in _OPERATOR_ADDRESS)


def _meta_signals(lowered):
    hits = [f"talks about the writing task, not to a reader: {p!r}"
            for p in _META if p in lowered]
    # The ambiguous nouns count ONLY alongside an address to the operator. Two signals,
    # the same posture `_option_menu_signals` already takes for its heuristic.
    if _addresses_the_operator(lowered):
        hits += [f"deliberation addressed to the operator, not a reader: {p!r}"
                 for p in _META_AMBIGUOUS if p in lowered]
    return hits



def _markdown_signals(text):
    hit = _MARKDOWN.search(text or "")
    return [f"markdown syntax on a timeline that does not render it: {hit.group().strip()!r}"] \
        if hit else []


def _option_menu_signals(text, lowered):
    """HEURISTIC. Two of three markers before it counts, so a numbered list is safe."""
    labels = {m.group(1) for m in _OPTION_LABEL.finditer(text or "")}
    markers = 0
    if len(labels) >= 2:
        markers += 1
    if _PARK.search(text or ""):
        markers += 1
    if "my call" in lowered or "my recommendation" in lowered:
        markers += 1
    if markers >= 2:
        return [f"reads as an options menu for the founder, not a post "
                f"(labels={sorted(labels)}, markers={markers}) [heuristic]"]
    return []


def refusal_violations(text):
    """ONLY the refusal signals, and normalized the same way `violations` is.

    why this is public (2026-08-09, archive-validity-joins-ledger): a caller needed
    "did the model decline the task" WITHOUT the meta/markdown/option-menu signals,
    and reached into `_refusal_signals` directly. That skipped the normalization
    below, so the same refusal text was caught with a straight apostrophe and
    missed with a curly one -- the default quote style of every model in this
    stack, and the exact scar `violations`' docstring already records. A private
    name is an invitation to re-derive the prelude; this is the prelude, once.

    The breadth matters and is why `violations` was not simply reused: over the 33
    valid published bodies, the full set fires on 4 and this fires on 1. The three
    extras trip on `_meta_signals`, which matches the substring "the draft" and is
    correct for a generation-time gate and far too broad for deciding whether an
    already-published body belongs in a measurement corpus.

    That 1-of-33 is a fact about THIS CORPUS, not a statement of detection power, and
    the distinction was worth writing down (adversarial review round 2). This is a
    deny-list of one incident's vocabulary. It misses ordinary paraphrases -- "I can't
    write this post from an internal incident report", "This one is a no from me" --
    and it always will, because `assistant_gate` reads PHRASING, not intent, and grows
    from real incidents. Read a clean result as "no known refusal phrasing", never as
    "not a refusal".
    """
    from . import ending_gate

    return _refusal_signals(_collapse_spaces(
        ending_gate.normalize_glyphs(text or "")).lower())


# Every Unicode space is a space, and a run of them is one space. STRUCTURAL, not a
# longer list of characters.
#
# why (adversarial review round 2, 2026-08-09): `normalize_glyphs` collapses
# look-alike QUOTES and strips INVISIBLES, which closed the curly-apostrophe hole one
# commit earlier. It does not touch look-alike SPACES, so this walked straight
# through the filter and returned []:
#
#     "I'm not\xa0going to write this one as-is."
#
# A no-break space renders identically to a space in every client, the published text
# is the model's own output, and a soft wrap puts a newline mid-phrase for free. Same
# failure class as the curly apostrophe, one glyph family over. Adding U+00A0 to a
# list would fix this incident and leave U+202F, U+2009 and the plain double space,
# which is how the first version of this bug shipped: `\s` plus a collapse states the
# property instead of enumerating the characters an incident happened to name.
_WHITESPACE_RUN = re.compile(r"\s+")


def _collapse_spaces(text):
    return _WHITESPACE_RUN.sub(" ", text).strip()


def violations(text):
    """Every reason this text is the assistant talking. Empty list means it reads as a post.

    Glyph-normalized first (2026-08-06): every phrase in `_REFUSAL` carrying an
    apostrophe compares byte-exact, so "I’m not going to write" with a curly apostrophe
    -- the default quote style of every model in this stack -- walked straight past the
    list. Normalization lives in ending_gate; one implementation, both gates.
    """
    from . import ending_gate

    text = ending_gate.normalize_glyphs(text)
    lowered = (text or "").lower()
    return (_refusal_signals(lowered)
            + _meta_signals(lowered)
            + _markdown_signals(text)
            + _option_menu_signals(text, lowered))


def check(text):
    """Violations in the gates' shape. Empty list means it passes."""
    return [{"rule": RULE, "detail": detail} for detail in violations(text)]
