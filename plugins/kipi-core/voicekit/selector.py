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

# Kind eligibility per slot kind, strongest first. A post slot prefers real posts;
# article excerpts pad only when the post pool is thin. Comments prefer comment/dm
# rows, then short posts -- a 320-char comment should not be taught by 800-word prose.
ELIGIBLE_KINDS = {
    "post": (("post",), ("article-excerpt",)),
    "comment": (("comment", "dm"), ("post",)),
}


def _channel_ok(row, channel):
    return row.get("channel", "any") in (channel, "any")


def eligible(rows, channel, slot_kind="post"):
    """(primary, fallback) pools, each sorted by id for stable rotation."""
    tiers = ELIGIBLE_KINDS.get(slot_kind, ELIGIBLE_KINDS["post"])
    primary = sorted((r for r in rows if r.get("kind") in tiers[0]
                      and _channel_ok(r, channel)), key=lambda r: str(r.get("id")))
    fallback = sorted((r for r in rows if r.get("kind") in tiers[1]
                       and _channel_ok(r, channel)), key=lambda r: str(r.get("id")))
    return primary, fallback


def select(rows, channel, counter, slot_index=0, k=DEFAULT_K, slot_kind="post"):
    """The selection. Pure function of its arguments; no clock, no randomness.

    `counter` is how many posts this channel has already published (the postbook is
    the durable source); it advances the rotation so the next post sees a different
    window. One `anchor: true` row is always included when any exists ("most Assaf"
    pieces stay in every prompt), rotated rather than pinned -- a pinned anchor is
    the same 3-exemplars-forever failure with extra steps.
    """
    primary, fallback = eligible(rows, channel, slot_kind)
    pool = primary + [r for r in fallback if r not in primary]
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
