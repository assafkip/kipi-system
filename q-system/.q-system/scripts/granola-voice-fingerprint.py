#!/usr/bin/env python3
"""granola-voice-fingerprint.py — Stage 3 deterministic linguistic fingerprint.

Pairs with plan: q-system/output/plans/voice-from-granola-2026-07-04.md

Answers the mechanical questions the LLM synthesis can't answer reliably: how
Assaf opens a sentence, how he closes one, which words he over-uses, which
discourse markers pepper his speech, and which corporate cliches he never says.
Pure counting over me-corpus.txt (his utterances only). No LLM, so the numbers
are reproducible and auditable. Interpretation into canonical prose happens
after, by hand, clearly separated from these counts.

Output: <corpus_dir>/voice-fingerprint.json  (+ printed summary)
Usage:  python3 granola-voice-fingerprint.py <corpus_dir>
"""
import re
import json
import sys
import os
from collections import Counter

# Function words + trivial tokens: excluded from "content words" so the signal is
# what he talks ABOUT, not grammar scaffolding.
STOPWORDS = set((
    "the a an and or but so to of in on at it is was were be been am are i you he "
    "she we they me my your his her our their this that these those for with as if "
    "then than just yeah no okay ok not do did does have has had will would can "
    "could im its thats dont youre there here what when how why who which about "
    "out up down get got go going get gonna wanna them your youre s t re ve ll d m "
    "into from by now all one like so very really thing things stuff kind"
).split())

# Spoken discourse markers: counted as phrases (his verbal fingerprint, even the
# ones we would NOT reproduce in writing).
DISCOURSE = ["like", "so", "you know", "i mean", "right", "dude", "man", "literally",
             "actually", "basically", "kind of", "i don't know", "whatever", "cool",
             "i think", "of course", "for sure"]

# Corporate/founder cliches: the absence check. What he does NOT say is signal.
CORPORATE_CLICHE = ["leverage", "synergy", "excited to", "thrilled", "humbled",
                    "circling back", "touch base", "low-hanging", "move the needle",
                    "best practice", "stakeholder", "paradigm", "seamless",
                    "cutting-edge", "cutting edge", "game-changing", "game changing",
                    "innovative", "disrupt", "empower", "holistic", "ecosystem",
                    "value-add", "deep dive", "north star", "double-click"]


def sentences(text):
    return [p.strip() for p in re.split(r"[.?!]+", text) if p.strip()]


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: granola-voice-fingerprint.py <corpus_dir>")
    cdir = sys.argv[1]
    raw = open(os.path.join(cdir, "me-corpus.txt"), encoding="utf-8").read()
    body = re.sub(r"=====.*?=====", " ", raw)  # drop per-meeting headers
    low = body.lower()
    words = re.findall(r"[a-z']+", low)
    total = max(1, len(words))

    freq = Counter(words)
    content = Counter({w: c for w, c in freq.items() if w not in STOPWORDS and len(w) > 2})

    disc = {d: low.count(" " + d + " ") for d in DISCOURSE}

    openers, closers = Counter(), Counter()
    for s in sentences(body):
        w = re.findall(r"[A-Za-z']+", s)
        if not w:
            continue
        openers[w[0].lower()] += 1
        closers[w[-1].lower()] += 1

    absent = [c for c in CORPORATE_CLICHE if low.count(c) == 0]
    present = {c: low.count(c) for c in CORPORATE_CLICHE if low.count(c) > 0}

    out = {
        "total_words": total,
        "top_content_words": content.most_common(30),
        "discourse_markers_per_1k_words": {
            d: round(c * 1000 / total, 2)
            for d, c in sorted(disc.items(), key=lambda x: -x[1]) if c > 0
        },
        "sentence_openers_top": openers.most_common(20),
        "sentence_closers_top": closers.most_common(20),
        "corporate_cliches_absent": absent,
        "corporate_cliches_present": present,
    }
    json.dump(out, open(os.path.join(cdir, "voice-fingerprint.json"), "w"), indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
