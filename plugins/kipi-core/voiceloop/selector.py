#!/usr/bin/env python3
"""Deterministic exemplar selection: which 3-5 pieces of real writing ride in THIS prompt.

Selection exists because dumping the whole corpus recreates the monolith (Stage 0:
55k of voice produced posts 21/22 outside the founder's own sentence-length band).
Three properties, each load-bearing and each tested:

- DETERMINISTIC: same (corpus, counter, slot) -> same selection. A test can assert
  the exact ids; a provenance row can explain "why these" in one line.
- ROTATING: keyed to a caller-supplied counter (the postbook's per-channel count),
  plus the slot index within a multi-slot day. Consecutive posts get different
  exemplar sets by construction -- the structural defense against the engine's
  measured uniformity failure (7/22 posts opening "Three ...").
- FORM-MATCHED: a post slot gets post-shaped exemplars first. Stage 0 measured why:
  article excerpts teach article rhythm (mixed-corpus bands hid a 21/22 failure
  that post-only bands exposed).
"""
from __future__ import annotations

DEFAULT_K = 4

# The long/short break, measured on the live corpus 2026-08-13 rather than chosen:
# x exemplars run 5..55 words with a single outlier at 479, so any cut inside that
# gap gives the same partition. Re-measure before moving it; a threshold nobody
# re-ran is how the claims in this repo's other PRDs survived being wrong.
LONG_WORDS = 150

# Kind eligibility per slot kind, strongest first. A post slot prefers real posts;
# article excerpts pad only when the post pool is thin. Comments prefer comment/dm
# rows, then short posts -- a 320-char comment should not be taught by 800-word prose.
ELIGIBLE_KINDS = {
    "post": (("post",), ("article-excerpt",)),
    "comment": (("comment", "dm"), ("post",)),
}


def _channel_ok(row, channel):
    return row.get("channel", "any") in (channel, "any")


def eligible(rows, channel, slot_kind="post", target_words=None):
    """(primary, fallback) pools, each sorted by id for stable rotation.

    LENGTH PROMOTES article-excerpt INTO THE PRIMARY TIER (2026-08-13). An article
    excerpt is long-form writing; demoting it to fallback is right for a 280-char
    slot and wrong for a long one. Measured before changing it: with linkedin's 12
    post rows against k=4, `resolved_pool` never reached fallback, so all 18
    article-excerpt rows were unreachable at EVERY counter -- including sample-05
    at 169 words, the one long-form linkedin sample a long-form request most needs.
    The founder's spec is that the skill sees all the examples; it saw 41 of 59.

    A row with `eligible_for_voice_reference` explicitly False is OUT of both
    tiers, anchors included (2026-08-23). Before this line the field was dead:
    the corpus carried it, curation flipped it, and selection never read it, so
    a hype-register post ("It's ALIVE!!!") sat as an anchor in every linkedin
    prompt while believing it was retired. Absent or null keeps the row live --
    retirement is an explicit act, recorded on the row with a reason.

    The 2026-08-09 scar is preserved exactly, because it is a scar about SHORT
    slots: article rhythm taught post slots and the engine published essays on a
    280-char channel. A short request still gets the strict tiering that fixed it.
    Only a long request promotes, and for a long request article rhythm is the
    right answer rather than the bug.
    """
    rows = [r for r in rows if r.get("eligible_for_voice_reference") is not False]
    tiers = ELIGIBLE_KINDS.get(slot_kind, ELIGIBLE_KINDS["post"])
    primary_kinds, fallback_kinds = tiers[0], tiers[1]
    if (target_words is not None and target_words >= LONG_WORDS
            and slot_kind == "post"):
        primary_kinds = tuple(primary_kinds) + tuple(fallback_kinds)
    primary = sorted((r for r in rows if r.get("kind") in primary_kinds
                      and _channel_ok(r, channel)), key=lambda r: str(r.get("id")))
    fallback = sorted((r for r in rows if r.get("kind") in fallback_kinds
                       and _channel_ok(r, channel) and r not in primary),
                      key=lambda r: str(r.get("id")))
    return primary, fallback


def resolved_pool(rows, channel, slot_kind="post", k=DEFAULT_K, target_words=None):
    """THE pooling rule. One writer, because two readers drifted (2026-08-09).

    EXHAUST the primary tier before touching fallback. The line this replaced
    concatenated both tiers unconditionally, which made this module's own
    FORM-MATCHED promise false in code: over counters 0-29 a post slot got <=1
    post-kind exemplar in 18/30 rotations and ZERO in 10/30, so article rhythm
    taught post slots and the engine published essays on a 280-char channel
    (finding-5, prd-content-engine-sameness-2026-08-09).

    (The PRD and the first version of this comment both said ZERO in 12/30.
    Re-measured against the real corpus with the original anchor flags it is
    10/30. The <=1 figure of 18/30 reproduces exactly. Corrected here rather than
    carried, because a number nobody re-ran is how this PRD's other six
    falsified claims survived.)

    Padding is still allowed, because exhaustion must not become starvation: a
    primary tier too thin to fill k pads from fallback, and a slot kind whose
    primary tier is empty in this corpus (comment/dm rows, which most instances
    have none of) falls back wholesale rather than returning nothing.

    It is a PUBLIC function because `validate` needs the same answer. Both
    validators used to re-derive it by counting primary-kind rows, which is only
    the same thing above k -- so they printed statements that were false about
    their own corpus at n<k (adversarial + standard review agreed, by different
    methods). A checker that replicates the rule it checks tests its own copy.
    """
    primary, fallback = eligible(rows, channel, slot_kind, target_words)
    if len(primary) >= k:
        return primary
    return primary + [r for r in fallback if r not in primary]


def _words(row):
    """Declared length, or measured if this corpus predates the `words` field."""
    return row.get("words") or len((row.get("text") or "").split())


def length_band(rows, target_words):
    """Rows written at the same scale as the piece being written.

    THE FOURTH AXIS (2026-08-13). channel, kind and anchor were all matched; length
    was not, and length is the axis a reader feels first. A long-form post drew its
    whole prompt from 20-word tweets and came back in the wrong register.

    NEAREST-LENGTH, NOT A THRESHOLD (2026-08-14). The first version split the corpus
    at LONG_WORDS=150. That was defensible when the x corpus ran 5..55 with a single
    479-word outlier: any cut inside that gap gave the same partition. Then the
    founder banked a 139-word post, and 150 put it in the same band as a 5-word
    tweet -- so asking for exactly that register still returned tweets. The corpus
    has THREE registers now (tweets, ~139, long-form) and a binary cannot hold three.

    Ranking by distance needs no constant, so there is nothing to re-measure and
    nothing to tune toward whatever was banked last. It also degrades correctly: a
    corpus with one length returns that length, and a target between two clusters
    returns the closer one rather than a band edge's arbitrary answer.

    `target_words=None` returns every row, unchanged, which is what every pre-2026
    caller and pinned test relies on.
    """
    if target_words is None:
        return list(rows)
    # Stable: ties break on id, so the same corpus and target always give the same
    # order. Determinism is a property this module promises and a sort by float
    # alone would quietly break it.
    return sorted(rows, key=lambda r: (abs(_words(r) - target_words), str(r.get("id"))))


def select(rows, channel, counter, slot_index=0, k=DEFAULT_K, slot_kind="post",
           target_words=None):
    """The selection. Pure function of its arguments; no clock, no randomness.

    `counter` is how many posts this channel has already published (the postbook is
    the durable source); it advances the rotation so the next post sees a different
    window. One `anchor: true` row is always included when any exists ("most like the author"
    pieces stay in every prompt), rotated rather than pinned -- a pinned anchor is
    the same 3-exemplars-forever failure with extra steps.

    `target_words=None` is the pre-2026-08-13 behaviour byte for byte, so every
    existing caller and pinned test keeps its answer. Pass it to match the fourth
    axis; see `length_band`.
    """
    pool = resolved_pool(rows, channel, slot_kind, k, target_words)
    # Narrow AFTER pooling so the form-matched tier rule above still decides which
    # kinds are eligible; length filters that result, never replaces it. A band that
    # matches nothing widens back to the pool rather than starving the prompt -- the
    # same exhaustion-must-not-become-starvation rule `resolved_pool` states.
    # length_band now ORDERS by nearness instead of filtering, so the nearest k are
    # the band. Keeping the whole pool behind them means a thin corpus still fills k
    # rather than starving -- exhaustion must not become starvation.
    if target_words is not None:
        ranked = length_band(pool, target_words)
        near = ranked[:max(k, 1)]
        # ANCHORS SURVIVE THE TRUNCATION (Codex review of #147, minor). Truncating to
        # the nearest k could drop every anchor, and the rotation below promises one
        # anchor is always included when any exists. A guarantee the step above can
        # silently delete is not a guarantee.
        if not any(r.get("anchor") for r in near):
            near = near + [r for r in ranked if r.get("anchor")][:1]
        pool = near or pool
    if not pool:
        return []
    offset = (int(counter) + int(slot_index)) % len(pool)

    anchors = [r for r in pool if r.get("anchor")]
    picked = []
    if anchors:
        picked.append(anchors[offset % len(anchors)])

    # k consecutive from the rotated pool, skipping what is already in.
    idx = offset
    while len(picked) < min(k, len(pool)):
        row = pool[idx % len(pool)]
        idx += 1
        if row not in picked:
            picked.append(row)
    return picked


def selection_reason(picked, channel, counter, slot_index=0):
    """One line for the provenance row: why THESE exemplars, answerable from disk."""
    ids = ",".join(str(r.get("id")) for r in picked)
    return (f"channel={channel} counter={counter} slot={slot_index} "
            f"rotation -> [{ids}]")
