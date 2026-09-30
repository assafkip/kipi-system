#!/usr/bin/env python3
"""Reject a post that ends like a marketer. The closing gate.

why this exists (2026-08-05, ASK-426): the founder read the two posts that went live that
afternoon and asked "I don't remember that a CTA was allowed at the end of any of my posts
-- wasn't there a rule for that". There was. In two places. Neither was executable.

## The rule, both places it already lived

`my-project/icp-working.md:1641`, the operator-vs-marketer table written 2026-08-04:

    | The marketers post              | The operator posts instead        |
    | ends in a CTA to a course/call  | ends in nothing, or ONE SPECIFIC THING |

founder-voice SKILL.md rules 6 and 7: "Questions expose uncomfortable truths, not drive
engagement. Questions should make the reader uncomfortable, not curious." And: end with a
direct question or a sharp statement -- never "Thoughts?" or "Agree?".

## What shipped anyway, and why nothing caught it

    LinkedIn 6a73c855f76c3f806af32ffa
      "What's the most tedious, repeatable task in your work that you wish a
       machine could just handle?"

    X 6a73cbbaf76c3f806af33647
      "...that's exactly what this solves."

Both cleared four gates with zero violations, because no gate read the ENDING. voice-lint
reads banned words, emdashes, capitalization and stat citations. `substance_gate` reads for
a number and a mechanism. `source_shape` reads for un-rewritten mined material.
`name_gate` reads for a person. The last line of a post was unexamined territory.

## The honest split, stated the way `name_gate` and `substance_gate` state theirs

- **EXACT (`_solicitation_signals`).** A closed list of closers that solicit a reply, a
  follow, or a booking. Zero judgement: "thoughts?", "let me know", "DM me", "book a
  call", "link in bio", "follow for more". These are marketer boilerplate in any context.
- **EXACT (`_pitch_close_signals`).** The pitch wearing a sentence: "that's exactly what
  this solves", "that's what I do", "if you're a <role> who ... that's". The X post's
  closer is this shape, and it reads as prose, which is what let it through.
- **HEURISTIC (`_reader_survey_signals`), and labelled as one.** A final question asking
  the reader to NOMINATE something from their own situation: a superlative or a
  "one thing" plus a second-person possessive. "What's the MOST tedious task in YOUR
  work?" is a survey. The first version of this layer fired on any interrogative closer
  containing "you", and it rejected "How many of the checks in your pipeline have ever
  been seen to reject something?" -- a dagger, and one the skill explicitly permits. The
  superlative is what makes it a poll rather than an accusation.

## A closing question IS banned outright (2026-08-06, [USER-DIRECTED])

Founder: "Ban closing questions outright on X and LinkedIn and even on substack.
essentially on any social posts I don't finish with a question."

This REVERSES the paragraph that stood here, which read "a closing question is NOT banned
outright" and cited founder-voice rule 7. The reversal is evidence-driven. Measured across
both corpora on his instruction:

    writing-samples.md  1 of 27 samples ends on a question -- and that one is a line
                        INSIDE a piece, quoting what a CISO asks, not his closer
    seed drafts         4 of 11, all from March 2026, all second person, all about the
                        reader's own business

So in his published writing he essentially never ends on a question. The four that do are
the March LinkedIn drafts written to farm engagement, and they are the closest thing in
his corpus to the survey shape he objected to on 2026-08-05.

The earlier layers were built on the opposite premise, and the March drafts were used as
the control set that proved them safe. That was the error: rule 7 is an assertion, the
corpus is evidence, and they disagreed.

`_reader_survey_signals` is kept and still runs. It is now a strictly narrower case of the
outright ban, retained because its violation message names WHY a survey is worse than an
ordinary question, and the reviser reads that message.

## Repairable, never fatal

An ending is the single most rewritable part of a post: the body's reporting is untouched
and only the last line changes. So every violation here goes to the bounded reviser with
the offending closer quoted.

That is held by two executables, not by this paragraph:
`tests/test_ending_gate.py::test_the_ending_rule_is_never_fatal` asserts
`"marketer-ending" not in decide.FATAL_RULES`, and
`::test_a_marketer_ending_is_revised_and_the_slot_still_fills` drives a real candidate
through `decide.decide_candidate` with a reviser and asserts it ships.
"""
from __future__ import annotations

import re

# Closers that exist to extract a reply, a follow or a booking. Boilerplate anywhere.
SOLICITATION_CLOSERS = (
    "thoughts?",
    "agree?",
    "am i wrong?",
    "what do you think",
    "what about you",
    "anyone else",
    "curious what others think",
    "curious to hear",
    "let me know",
    "drop a comment",
    "comment below",
    "dm me",
    "send me a dm",
    "reach out",
    "get in touch",
    "book a call",
    "book a time",
    "schedule a call",
    "hit me up",
    "link in bio",
    "link in the comments",
    "follow for more",
    "share this",
    "repost this",
    "tag someone",
    "sign up",
    "subscribe",
    "join the waitlist",
)

# The pitch wearing a sentence. This is the shape that reads as prose and slips through.
PITCH_CLOSE_PATTERNS = (
    re.compile(r"(?i)that'?s (?:exactly )?what (?:this|it|i) (?:solves|does|do|fixes|build)"),
    re.compile(r"(?i)that'?s (?:exactly )?the (?:problem|thing) (?:this|i) (?:solve|fix|build)"),
    re.compile(r"(?i)^\s*if you'?re (?:a|an) [^.\n]{3,60}[,:]? .*\bthat'?s\b"),
    re.compile(r"(?i)\bthis is what i (?:do|build|sell)\b"),
    re.compile(r"(?i)\b(?:i can|i'?ll) help you\b"),
    re.compile(r"(?i)\bhappy to (?:help|chat|talk)\b"),
)

# The reader's OWN situation. Possessive only: a bare "you" appears in daggers too.
_SECOND_PERSON_POSSESSIVE_RE = re.compile(r"(?i)\b(?:your|yours)\b")

# The poll tell: the question asks the reader to NOMINATE their worst/biggest/one thing.
# This is what separates a survey from a dagger, and it is the narrowest signal that
# still catches the closer the founder objected to.
_NOMINATION_RE = re.compile(
    r"(?i)\b(?:the most|the biggest|the worst|the hardest|the best|the top|your favou?rite|"
    r"one thing|the one|which one)\b")

_INTERROGATIVE_OPENER = re.compile(
    r"(?i)^\s*(?:what|which|how|when|where|who|why|do|does|did|have|has|are|is|can|could|"
    r"would|will|ever)\b")


# Zero-width and other format characters. They render as nothing on every timeline, so
# appending one after a "?" changes no pixel a reader sees and defeats any byte-exact
# endswith check. Found 2026-08-06 in this module's adversarial pass: the cheapest
# disguise available to a model whose obvious phrasing is blocked.
_INVISIBLES = re.compile(r"[​‌‍⁠﻿­]")

# The punctuation run a sentence can END on. If a "?" appears anywhere in it, the
# sentence is a question: "record?", "record?!", "record??", "record?…" all read as one.
_TRAILING_PUNCT = re.compile(r"[?!.…]+$")


def normalize_glyphs(text):
    """Unicode look-alikes collapsed to the byte the checks compare against.

    Curly apostrophes, fullwidth question marks and invisible format characters all
    render like their ASCII originals, which makes them free evasions for every
    byte-exact list in this file (and in assistant_gate, which imports this). The gates
    compare normalized text; the published text is untouched.
    """
    text = _INVISIBLES.sub("", text or "")
    return (text.replace("’", "'").replace("‘", "'")
                .replace("“", '"').replace("”", '"')
                .replace("？", "?").replace("！", "!"))


def _lines_without_trailing_hashtags(text):
    """Every non-empty line of the post, minus the trailing hashtag block.

    Hashtags are not gated here -- no rule the founder wrote bans them -- but a trailing
    "#AIConsulting #ProfessionalServices" block would otherwise BECOME the final line and
    hide the actual closer from every check below. So it is stripped for the purpose of
    finding the ending, and left alone otherwise.

    Trailing hashtag TOKENS on the closer's own line are stripped too (2026-08-06):
    "Where does yours keep the record? #AI" made "#AI" the final sentence, and the
    question above it cleared every check -- the whole-line strip was the fix written
    against the one disguise just seen.

    EXTRACTED from `_final_block` 2026-08-12, unchanged in behaviour, because the
    question-only exemption below needs the WHOLE post under the same hashtag stripping
    the ending already got. Two copies of that stripping is how a disguise gets fixed on
    one surface and stays open on the other -- the shape `ends_on_question` was
    consolidated to kill in `comment.violations`.
    """
    lines = [line.strip() for line in (text or "").strip().splitlines() if line.strip()]
    while lines and all(token.startswith("#") for token in lines[-1].split()):
        lines.pop()
    if not lines:
        return []
    tokens = lines[-1].split()
    while tokens and tokens[-1].startswith("#"):
        tokens.pop()
    lines[-1] = " ".join(tokens)
    return lines


def _final_block(text):
    """The last non-empty line, minus trailing hashtags."""
    lines = _lines_without_trailing_hashtags(text)
    return lines[-1] if lines else ""


def _final_sentence(block):
    parts = [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+", block) if chunk.strip()]
    return parts[-1] if parts else block


def _solicitation_signals(ending):
    low = ending.lower()
    hits = [phrase for phrase in SOLICITATION_CLOSERS if phrase in low]
    return [f"solicitation closer {hits[0]!r}"] if hits else []


def _pitch_close_signals(ending):
    for pattern in PITCH_CLOSE_PATTERNS:
        match = pattern.search(ending)
        if match:
            return [f"pitch close {match.group(0).strip()!r}"]
    return []


# An instruction to the reader, at the start of a sentence. "Pick one ...", "Go look at
# ...", "Take one of your ...". These are the assignment verbs, not every verb.
# BROADENED 2026-08-06, immediately after "Pull your last ten outbound messages" shipped
# clean. The first version listed the verbs that had been SEEN, so the next synonym walked
# straight through -- the same "only knows the costumes it has been shown" failure the
# closing-question ban was supposed to end. This is now the common English imperative set
# for assigning work, not a list of incidents. The possessive requirement in
# `_homework_signals` is what keeps it from firing on ordinary statements.
_HOMEWORK_IMPERATIVE = re.compile(
    r"(?i)(?:^|(?<=[.!?]\s))\s*(?:go\s+)?("
    r"pick|pull|take|grab|find|check|count|list|look|open|read|scan|audit|review|"
    r"measure|compare|track|test|try|ask|answer|write|note|map|walk|run|start|stop|"
    r"add|remove|replace|fix|call|email|message|send|share|tell|show|name|choose|"
    r"pick one|next time you|think about|have a look|go through"
    r")\b")

# The softened form. "Worth checking in your own setup:", "Worth asking what your ...".
_HOMEWORK_SOFTENED = re.compile(
    r"(?i)\bworth (?:checking|asking|a look|doing|knowing|finding out)\b")


def _homework_signals(ending):
    """HEURISTIC. A closing that assigns the reader a task.

    why (2026-08-06): the founder read ten published X posts and asked why they still end
    with a CTA. Every one passed the three checks above, because none of them is a
    solicitation or a pitch. They are HOMEWORK:

        "Pick one scheduled automation in your business. Where does it keep the proof?"
        "Worth checking in your own setup: where does something get done, and where ..."
        "Go look at anything in your business that runs on a schedule."

    Two of those phrasings appeared VERBATIM on two posts each in a single day, which is
    the template tell on top of the CTA.

    The line this draws: a QUESTION that makes the reader uncomfortable is a dagger and
    founder-voice rule 7 explicitly permits it. An INSTRUCTION telling them to go perform
    a task is an ask, and an ask is the thing he banned. So both conditions are required:
    an assignment verb AND the reader's own domain (possessive). "Check the record" is a
    statement about the world; "Check your record" is homework.
    """
    if not _SECOND_PERSON_POSSESSIVE_RE.search(ending):
        return []
    hit = _HOMEWORK_IMPERATIVE.search(ending) or _HOMEWORK_SOFTENED.search(ending)
    if hit:
        return [f"homework closer {hit.group(0).strip()!r}: it tells the reader to go do "
                f"something, which is an ask [heuristic]"]
    return []


def ends_on_question(text):
    """Does this text close on a question? THE single derivation of that fact.

    `comment.violations` delegates here rather than keeping its own `endswith("?")`
    (2026-08-06): two copies of one rule is how a fix lands on the post surface while the
    comment surface stays open to the same disguise -- the CTA that moved one box down,
    as a code structure.

    The check reads the trailing punctuation RUN, not the last byte: "record?!",
    "record??" and "record?…" are all questions, and normalize_glyphs upstream has
    already collapsed the fullwidth and zero-width variants that defeat byte equality.
    """
    sentence = _final_sentence(normalize_glyphs(_final_block(text)))
    trail = _TRAILING_PUNCT.search(sentence.rstrip())
    return bool(trail and "?" in trail.group())


def _closing_question_signals(ending):
    """EXACT. A social post does not end on a question. Founder-directed 2026-08-06.

    Measured before building it: 1 of 27 writing samples ends on a question, and that one
    is a quoted line inside a piece rather than a closer. The rule is the corpus, not a
    preference.

    Applies to every social channel -- X, LinkedIn and Substack -- because he named all
    three: "essentially on any social posts I don't finish with a question."
    """
    sentence = _final_sentence(ending)
    trail = _TRAILING_PUNCT.search(sentence.rstrip())
    if trail and "?" in trail.group():
        return [f"the post ends on a question: {sentence[:80]!r}. A social post ends on a "
                f"verdict, never a question (founder-directed 2026-08-06)"]
    return []


def _reader_survey_signals(ending):
    """HEURISTIC. A closing question asking the reader to NOMINATE something of theirs.

    All four conditions, and the fourth is the one that earns its keep: it is a question,
    it opens interrogatively, it refers to the reader's own things (possessive, not a bare
    "you"), and it asks for a superlative or a single pick.

    Dropping either of the last two turns this into a ban on closing questions, which
    founder-voice rule 7 explicitly permits. Measured while writing it: requiring only a
    bare "you" rejected "How many of the checks in your pipeline have ever been seen to
    reject something?", which is a dagger.
    """
    sentence = _final_sentence(ending)
    if not sentence.endswith("?"):
        return []
    if not _INTERROGATIVE_OPENER.match(sentence):
        return []
    if not _SECOND_PERSON_POSSESSIVE_RE.search(sentence):
        return []
    if not _NOMINATION_RE.search(sentence):
        return []
    return [f"reader-survey question {sentence!r} (heuristic)"]


# The exemption's own CTA set, Amber's condition 4. SOLICITATION_CLOSERS above is a list
# of whole CLOSERS ("let me know", "drop a comment"); this is the bare verb set, and it is
# checked ANYWHERE in the post rather than in the final block, because a one-sentence post
# has no elsewhere to hide one in.
_CTA_VERB_RE = re.compile(
    r"(?i)\b(?:comment|comments|reply|replies|share|shares|tag|tags|dm|dms|"
    r"tell me|let me know)\b")

# Amber's condition 3, exactly as ratified: "Under 160 characters total." Long enough to
# hold an actor and a moment, short enough to still read as one line rather than a
# developed argument that happens to close with a question mark.
QUESTION_ONLY_MAX_CHARS = 160


def question_only_scene_exemption(text):
    """May this post end on a question? THE deterministic half of RULE-2026-08-12-G.

    Founder, reading the round-two batch 2026-08-12: "Question only posts are okay - as
    long as they tell a story or narrative." That NARROWS the 2026-08-06 outright ban; it
    does not reverse it. What he banned was a closing question tacked onto a developed
    post to farm engagement, and that shape stays banned byte for byte.

    ## What this function can and cannot see, stated because it matters more than the code

    Amber's spec has five conditions. FOUR of them are string-length and regex checks and
    are implemented here exactly as written: sole sentence, under 160 chars, no CTA verb,
    and `_reader_survey_signals` still running (that one lives in `signals`, which never
    stops calling it).

    The fifth, CARRIES A SCENE, is not checkable this way and this function does not
    pretend it is. A regex cannot tell a concrete moment from an abstract prompt dressed
    to look like one. That requirement is carried by the PROMPT -- the STORY IS THE
    PACKAGE frame added the same day -- which is the same posture `opener_gate`'s
    docstring already concedes for a line that is "followable but boring".

    So a false pass is possible by design: a question that is short and CTA-free with no
    real scene in it will clear this. That is named here rather than hidden, because
    judgment the gate cannot see is not judgment the gate should pretend to see. It is
    caught at corpus review.

    FAIL CLOSED everywhere the regex CAN decide. Any second sentence at all, any second
    LINE, anything borderline on length: no exemption, and `_closing_question_signals`
    runs as it always did.
    """
    body = normalize_glyphs(text)
    lines = _lines_without_trailing_hashtags(body)
    # One line, or two: a claim then a short question. His X register does
    # that (x-06: "I haven't seen a race car...\nI wonder why?"). A third
    # line is a developed post and stays inside the closing-question ban.
    if len(lines) not in (1, 2):
        return False
    if len(body.strip()) >= QUESTION_ONLY_MAX_CHARS:
        # The WHOLE post's length, not the stripped line's: a hashtag block does not buy
        # a longer question.
        return False
    last = lines[-1]
    if len(lines) == 1:
        if len([c for c in re.split(r"(?<=[.!?])\s+", last) if c.strip()]) != 1:
            return False
    else:
        first = lines[0].rstrip()
        first_trail = _TRAILING_PUNCT.search(first)
        if first_trail and "?" in first_trail.group():
            return False
        # A finished sentence then a question on the next line is TACKED_ON
        # (test_ending_gate dagger). x-06's first line has no terminator.
        if first_trail and any(ch in first_trail.group() for ch in ".!"):
            return False
    trail = _TRAILING_PUNCT.search(last.rstrip())
    if not (trail and "?" in trail.group()):
        return False
    return not _CTA_VERB_RE.search(last)


def signals(text):
    """Every marketer tell in the ending, named so a rejection can explain itself.

    The ending is glyph-normalized before any list or pattern reads it: a curly
    apostrophe took "That's exactly what this solves" past the pitch patterns (which
    match the ASCII apostrophe), and a fullwidth "？" took the question ban. The text
    that publishes is never modified; only the copy the checks read is.
    """
    ending = normalize_glyphs(_final_block(text))
    if not ending:
        return []
    # RULE-2026-08-12-G. The exemption suppresses exactly ONE check and nothing else.
    # Written as a substitution rather than an early return on purpose: an early return
    # would hand a question-only post a pass on the survey heuristic too, and Amber's
    # condition 5 is explicit that the exemption is additive and never overrides it.
    closing_question = ([] if question_only_scene_exemption(text)
                        else _closing_question_signals(ending))
    return (_solicitation_signals(ending)
            + _pitch_close_signals(ending)
            + _homework_signals(ending)
            + closing_question
            + _reader_survey_signals(ending))


def check(text):
    """Violations in the gates' shape, so callers merge reports without special-casing."""
    found = signals(text)
    if not found:
        return []
    return [{
        "rule": "marketer-ending",
        "line": 1,
        "detail": ("the post ends like a marketer: " + ", ".join(found)
                   + ". An operator post ends in nothing, or in one specific thing "
                     "(icp-working.md operator table, 2026-08-04). A closing question is "
                     "allowed only as a dagger -- it makes the reader uncomfortable, it "
                     "does not ask them to reply (founder-voice rules 6-7). Rewrite the "
                     "LAST LINE only; the body stands."),
    }]
