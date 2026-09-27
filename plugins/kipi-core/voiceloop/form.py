#!/usr/bin/env python3
"""Is this draft SHAPED like him. The other half of the voice question.

`luar_scorer` answers "does this sound like him" by embedding a draft against his
corpus. Nothing answered "is it shaped like him", and the gap was invisible for the
same reason the gate gap was: every one of the 14 gates in `decide._violations` is a
NEGATIVE check, and the assembled voice section is 15,000 characters describing
REGISTER. Measured 2026-08-20, that section says "characters" 0 times, "hook" 0
times, "first line" 0 times. The machinery knew who was writing and had no opinion
about what shape the thing should be.

Found the hard way: one post ran twelve drafts and four founder rejections of the
hook. Every draft opened with a 20-30 word sentence. His own median is 9. Nothing
could see it, so nobody could say it.

## Everything here is DERIVED, never copied

The bands come from `voice/exemplars.jsonl` at call time. A hardcoded median is a
second source of truth that drifts the moment he writes another post, which is the
derivation split this repo keeps writing scars about. `founder-research` numbers
(section 14g of `canonical/social-writing-method.md`) CALIBRATE and never override:
where his corpus and the research disagree, his corpus wins, because
`social-writing-method.md` note 12 puts voice above every other instruction.

They mostly agree. Measured 2026-08-20 on posts only: LinkedIn median 808 chars
(research window 800-1000), hook median 9 words (research 8-12), 1 sentence per
paragraph (research 1-2).

## kind == "post" ONLY, and that is the whole reason these numbers are usable

The LinkedIn corpus holds 24 posts, 10 article-excerpts and 3 comments. Including
the excerpts moves the median from 808 to 756 and stretches the range to 2449, which
reads as "he writes long" and is an artifact of measuring articles as if they were
posts. The first read of this corpus made exactly that mistake and concluded his
corpus DISAGREED with the research. It does not. A form reference built from the
wrong population is worse than none: it would have taught the generator to write
articles.
"""
from __future__ import annotations

import json
import os
import re
import statistics as st

# The module takes a path; the INSTANCE supplies it. Same split `voice_ref.py` uses
# and for the same recorded reason: a founder-specific corpus directory hardcoded in a
# shared module is what `test_no_founder_data.py` caught the last time one moved. The
# env var wins so a caller outside this checkout can point at its own corpus without
# editing the package, and the local default keeps every existing call site working
# with no argument.
# NO CORPUS RESOLUTION LIVES HERE, deliberately (2026-09-05, extraction slice 4b).
#
# This module used to resolve the exemplar corpus from __file__: two candidate
# directory names, an env override, and a parent computed from the module's own
# location. Inside one deployment that is correct and invisible. Moving the file
# would silently have repointed it at `plugins/kipi-core/voice/exemplars.jsonl`,
# which does not exist, so the "pure move" the plan expected here was a behaviour
# change wearing a move's clothes.
#
# Every corpus reader below therefore takes its path as a REQUIRED argument. A
# caller that forgets gets a TypeError at the call site, never a silent read of an
# empty or foreign corpus. The deployment half keeps the env var, the candidate
# directory names and `corpus_path()`, and binds them.

#: X's timeline fold. A post longer than this is collapsed behind "Show more", so a
#: reader who sees the rest CHOSE to expand it, which is the dwell signal the platform
#: now pays for. Founder call 2026-08-20: on X, follow the algorithm rather than his
#: corpus. The research weights dwell over two minutes at +10x and an author-engaged
#: reply at +75x, while a like is +0.5x. The retired 100-character target was built to
#: farm likes, so it optimised the weakest signal on the platform and structurally
#: foreclosed the two strongest: 100 characters cannot hold a reader for two minutes
#: or carry enough claim to answer.
#:
#: This is a FLOOR derived from a platform mechanic, not a length invented to hit a
#: number. The research gives a direction and no figure, so nothing here pretends to
#: one. His X corpus median is 133, so this deliberately departs from his corpus on
#: this channel and only this channel, on his explicit instruction.
X_DWELL_FLOOR_CHARS = 280


def _usable(row):
    """The same refusal `luar_scorer.usable_as_reference` makes, plus retired rows.

    Kept in step with that predicate on purpose: two definitions of "may this row
    speak for him" is how a decontamination fixes one consumer and misses another.
    """
    if row.get("generated") is True:
        return False
    if row.get("eligible_for_voice_reference") is False:
        return False
    if row.get("status") == "retired":
        return False
    return bool((row.get("text") or "").strip())


def corpus_posts(channel, path):
    """His real posts on one channel. kind == "post", never excerpts or comments."""
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("channel") == channel and row.get("kind") == "post" and _usable(row):
                out.append(row["text"])
    return out


def hook_words(text):
    """Words in the first sentence or first line, whichever ends first.

    A line break ends the hook even mid-sentence, because that is what the reader
    sees before the fold decides whether they keep going.
    """
    first = re.split(r"(?<=[.!?])\s+|\n", (text or "").strip())[0]
    return len(first.split())


def paragraph_sentences(text):
    """Sentence count for each paragraph, in order."""
    out = []
    for para in [p for p in (text or "").split("\n\n") if p.strip()]:
        out.append(len([s for s in re.split(r"(?<=[.!?])\s+", para.strip()) if s.strip()]))
    return out


def measure(text):
    """What this draft IS. No judgement, no reference."""
    paras = paragraph_sentences(text)
    return {
        "chars": len(text or ""),
        "words": len((text or "").split()),
        "hook_words": hook_words(text),
        "paragraphs": len(paras),
        "max_sentences_per_paragraph": max(paras) if paras else 0,
    }


def bands(channel, path):
    """His p25/median/p75 for one channel, or None when the corpus is too small.

    Refuses under 8 posts rather than emitting a quartile from a handful of rows. A
    band computed from 3 posts is a number with a confidence interval nobody prints,
    and it would be read as his practice.
    """
    posts = corpus_posts(channel, path=path)
    if len(posts) < 8:
        return None
    chars = [len(t) for t in posts]
    hooks = [hook_words(t) for t in posts]
    sents = [s for t in posts for s in paragraph_sentences(t)]
    def q(vals):
        vals = sorted(vals)
        quart = st.quantiles(vals, n=4) if len(vals) >= 4 else [vals[0], st.median(vals), vals[-1]]
        return {"p25": int(quart[0]), "median": int(st.median(vals)), "p75": int(quart[2])}
    return {"n": len(posts), "chars": q(chars), "hook_words": q(hooks),
            "sentences_per_paragraph": q(sents)}


def report(text, channel, path):
    """Draft vs his own practice. ADVISORY, like the corpus score, and for the same
    reason: this is evidence about shape, never a verdict on it.

    On X the char reference is the dwell floor rather than his corpus band, per the
    founder call recorded at `X_DWELL_FLOOR_CHARS`. Both are reported either way so a
    reader can always see what his corpus actually does.
    """
    got = measure(text)
    ref = bands(channel, path=path)
    out = {"channel": channel, "measured": got, "corpus": ref, "flags": []}
    if ref is None:
        out["flags"].append("no-reference: fewer than 8 posts on this channel")
        return out
    if channel == "x":
        out["char_rule"] = {"kind": "dwell-floor", "floor": X_DWELL_FLOOR_CHARS}
        if got["chars"] < X_DWELL_FLOOR_CHARS:
            out["flags"].append(
                f"below the X dwell floor: {got['chars']} chars, under {X_DWELL_FLOOR_CHARS}. "
                f"It will not earn an expand, so it cannot collect the dwell or reply "
                f"signals the channel pays for.")
    else:
        lo, hi = ref["chars"]["p25"], ref["chars"]["p75"]
        out["char_rule"] = {"kind": "corpus-band", "p25": lo, "p75": hi}
        if got["chars"] > hi:
            out["flags"].append(
                f"longer than he writes: {got['chars']} chars against his p75 of {hi} "
                f"(median {ref['chars']['median']})")
        elif got["chars"] < lo:
            out["flags"].append(
                f"shorter than he writes: {got['chars']} chars against his p25 of {lo}")
    hk = ref["hook_words"]["p75"]
    if got["hook_words"] > hk:
        out["flags"].append(
            f"hook runs long: {got['hook_words']} words against his p75 of {hk} "
            f"(median {ref['hook_words']['median']}). The first line is what the fold cuts.")
    sp = ref["sentences_per_paragraph"]["p75"]
    if got["max_sentences_per_paragraph"] > sp:
        out["flags"].append(
            f"a paragraph runs {got['max_sentences_per_paragraph']} sentences against "
            f"his p75 of {sp}")
    return out


def summary_line(text, channel, path):
    """One line for a human. Empty string when the draft sits inside his practice."""
    rep = report(text, channel, path=path)
    if not rep["flags"]:
        return f"form: inside his practice ({rep['measured']['chars']} chars, " \
               f"{rep['measured']['hook_words']}-word hook)"
    return "form: " + "; ".join(rep["flags"])


def writer_guidance(channel, path):
    """The shape numbers as ONE sentence for the writer's prompt, or None.

    `report`/`summary_line` face a finished draft. This faces the model BEFORE it
    writes, and the split matters: the 22,124-character LinkedIn prompt said
    "character" zero times on 2026-08-20, so every draft was shaped by nothing and
    then measured against a band it was never given. Measuring a draft against a
    target the writer never received is not a gate, it is a postmortem.

    Returns None when the corpus cannot speak (fewer than 8 posts, per `bands`). The
    caller keeps its existing copy in that case rather than rendering a numberless
    target, which is the exact thing Amber's Q1 ruling rejected on the X branch.

    WHY THIS IS NOT A SEVENTH WRITER CONSTRAINT. `generate.WRITER_CONSTRAINTS` keeps
    six because arXiv 2608.02639 measures compliance collapsing past roughly 20
    stacked constraints with SILENT drops. Shape belongs inside constraint 6,
    `channel-format`, which is already the block about format and already substitutes
    runtime values on X. Adding a rule of its own would trade a shape the model
    ignores for a shape the model ignores plus one more constraint competing with the
    other six.

    X keeps its dwell floor rather than its corpus band: founder call 2026-08-20
    recorded at `X_DWELL_FLOOR_CHARS`, follow the algorithm on that channel and not
    his history. So this returns the LINKEDIN sentence only, and `format_rules`
    keeps owning the X copy it already had.
    """
    if channel == "x":
        return None
    ref = bands(channel, path=path)
    if ref is None:
        return None
    return (
        f"aim for about {ref['chars']['median']} characters, which is his own median "
        f"on this channel, and treat {ref['chars']['p75']} as the outside edge. Open "
        f"on a first line of about {ref['hook_words']['median']} words, then a line "
        f"break: that first line is what the fold cuts. Keep a paragraph to "
        f"{ref['sentences_per_paragraph']['median']} sentence, "
        f"{ref['sentences_per_paragraph']['p75']} at the very outside."
    )
