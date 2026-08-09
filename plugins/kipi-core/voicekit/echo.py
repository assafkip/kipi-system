#!/usr/bin/env python3
"""Echo detection: the candidate must not parrot what its own prompt showed it.

why this exists (2026-08-06, Stage 0 finding 2): 9 of 22 posts published in one day
contained the literal sentence pair "Nothing was sent. Nothing was lost." -- the
EXAMPLE ending inside `revise.RULE_GUIDANCE`. The reviser copied its own guidance
example into published text, and nothing compared output against what the prompt
carried. Loading exemplars into prompts (the whole voice architecture) makes this
class WORSE unless it is gated, so the gate ships with the loader.

Two checks, both pure text ops:

- `prompt_echo`: any N-gram (default 8 words) shared between the candidate and any
  text that rode in its prompt (exemplars, guidance examples). 8 is deliberate: long
  enough that a shared idiom ("the same thing happened to us") cannot fire, short
  enough that a lifted sentence cannot hide.
- `opener_echo`: the candidate's first sentence shape vs recent published openers.
  First-6-word overlap of 4+ tokens = the same opener. 7/22 posts opening "Three
  receipts/drafts/duplicate..." is the measured failure.
"""
from __future__ import annotations

import re

NGRAM = 8
OPENER_WORDS = 6
OPENER_SHARED = 4

_WORD = re.compile(r"[A-Za-z0-9']+")


def _words(text):
    return [w.lower() for w in _WORD.findall(text or "")]


def ngrams(text, n=NGRAM):
    words = _words(text)
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def prompt_echo(candidate, prompt_texts, n=NGRAM):
    """Echoed n-grams between the candidate and the texts its prompt carried.

    Returns a sorted list of the echoed word-tuples joined as strings; [] is a pass.
    `prompt_texts` is the exemplar/guidance bodies only, never the instruction
    boilerplate -- instructions repeat by design, and flagging them would make the
    gate cry wolf until someone switches it off.
    """
    got = ngrams(candidate, n)
    if not got:
        return []
    hits = set()
    for source in prompt_texts or []:
        hits |= got & ngrams(source, n)
    return sorted(" ".join(gram) for gram in hits)


def opener(text, k=OPENER_WORDS):
    return _words(text)[:k]


def opener_echo(candidate, recent_openers, k=OPENER_WORDS, shared=OPENER_SHARED):
    """The recent opener this candidate repeats, or None.

    `recent_openers` is a list of the last few published posts' opening words
    (the caller reads them from the published-body archive). Position-wise
    comparison: the same 4 of the first 6 words IN ORDER is the same opener shape.
    """
    mine = opener(candidate, k)
    if not mine:
        return None
    for prev in recent_openers or []:
        prev_words = [w.lower() for w in prev][:k] if isinstance(prev, (list, tuple)) \
            else opener(str(prev), k)
        same = sum(1 for a, b in zip(mine, prev_words) if a == b)
        if same >= shared:
            return " ".join(prev_words)
    return None
