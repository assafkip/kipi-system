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
#: RETIRED 2026-09-19, and DELETED rather than left at a value nobody reads.
#: `ROTATION_WINDOW_MULT = 3` capped the rotation window at k*3 rows on top of the
#: distance bound below, which already expresses "near the target". Two bounds for
#: one job, and the count one did not grow with the corpus: reach stayed at 12
#: whether the pool held 13 rows or 1300. Measured on the live ASK corpus, 13 of
#: 106 reachable with 61 inside the band. `selector.select` carries the full record.
#:
#: Its docstring also claimed "lowering it to 1 restores the defect this fixes",
#: which stopped being true the moment the constant stopped being read. A dead
#: constant is clutter; a dead constant that still asserts a behaviour is a trap
#: for the next reader, which is why this is a deletion and not a rename.
#: `tests/test_length_axis.py::test_every_row_inside_the_band_is_reachable` is the
#: guard that goes RED if the cap is reintroduced.
#: How far from the target a row may sit and still enter the rotation window, as a
#: fraction of the target with a floor for very short targets. BOTH ARE JUDGMENT
#: CALLS, not measurements, and are labelled so rather than given a false n. The
#: floor exists because a 20-word target with a pure fraction admits almost nothing.
#: What is checkable: at these values every live slot rotates through more than one
#: exemplar set across 31 counters, and the thin-corpus scar test
#: (`test_short_target_never_returns_the_long_row`) stays green -- a count-only
#: window failed it immediately, which is why distance is here at all.
ROTATION_SPAN_FRACTION = 0.6
ROTATION_MIN_SPAN_WORDS = 25

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
        # THE WINDOW IS WIDER THAN k, AND THAT IS THE WHOLE FIX (2026-09-10).
        #
        # This line read `ranked[:max(k, 1)]`, which cut the pool to EXACTLY k while
        # the rotation below picks k of it. Choosing k of k is the same SET at every
        # counter; `offset` only permuted the order. Measured on the live corpus over
        # 31 consecutive counters: linkedin/post at target 200 gave 1 distinct set
        # (4 via the anchor rescue below, which is incidental, not rotation), x/post
        # at 40 gave 1, reddit/comment at 95 gave 1. With `target_words=None` the
        # same call gave 31 of 31, which is the negative control proving the
        # rotation machinery itself was fine and only the pool was starved.
        #
        # That made the module's stated defense inert. The docstring at the top of
        # this file calls rotation "the structural defense against the engine's
        # measured uniformity failure" (finding-5,
        # prd-content-engine-sameness-2026-08-09), and every production caller
        # passes a target: `social.py` defaults to 200 on linkedin and 40 on x even
        # with no `--words`, and `voice_ref.py` makes `--words` required. So there
        # was no untargeted path and the defense never ran.
        #
        # Widening to the whole pool is the WRONG fix and would reopen the 2026-08-09
        # scar from the other side: rotating over all 45 linkedin rows means a high
        # counter selects the rows FURTHEST from the target, which is how article
        # rhythm taught post slots and the engine published essays on a 280-char
        # channel. The window keeps the nearest rows and rotates inside them.
        # THE WINDOW IS BOUNDED BY DISTANCE AS WELL AS COUNT, and the count-only
        # version was caught by `test_short_target_never_returns_the_long_row`
        # within minutes of being written. On the thin fixture corpus (ten 20-word
        # posts and one 400-word post) a window of k*3 simply swallowed the long
        # row, which is the 2026-08-09 scar reopening from the other side. Size
        # alone cannot express "near"; distance can.
        span = max(target_words * ROTATION_SPAN_FRACTION, ROTATION_MIN_SPAN_WORDS)
        near = [r for r in ranked if abs(_words(r) - target_words) <= span]
        # THE DISTANCE BOUND IS THE WINDOW, and the count cap that used to sit here
        # was a second threshold doing the same job worse (sp-1d33d5f9, 2026-09-19).
        #
        # This line read `near[:max(k * ROTATION_WINDOW_MULT, k + 1)]`. That cut the
        # band to 12 rows no matter how large it was, so reach did not grow with the
        # corpus. Measured on the live ASK corpus the day 51 approved LinkedIn posts
        # were banked: linkedin/post at the production target of 200 had 61 rows
        # INSIDE the band and the rotation reached 13 of 106. Banking 51 posts moved
        # reach from 13 to 13 -- the corpus doubled and what the model sees did not.
        # 93 of 106 rows were unreachable; one row appeared in 24 of 24 counters.
        #
        # WHY REMOVING IT DOES NOT REOPEN THE 2026-08-09 SCAR. That scar is about a
        # short slot being taught article rhythm, and `span` is what prevents it:
        # every row in `near` is already within ROTATION_SPAN_FRACTION of the target.
        # The count cap was added in the same 2026-09-10 edit that added `span`,
        # against a count-ONLY version that had no distance bound at all -- the
        # comment below records that history. Once distance arrived the count became
        # redundant, and nobody removed it. `test_short_target_never_returns_the_long
        # _row` is the guard that proves distance is doing the work; it stays green
        # with this line gone, and `test_voice_reach.py` in the consuming repo pins
        # both halves against each other.
        #
        # Raising ROTATION_WINDOW_MULT instead was rejected: that is moving a
        # threshold to fit the data, which is the failure mode this file's own
        # comments exist to document.
        window = near
        # EXHAUSTION MUST NOT BECOME STARVATION, the rule `resolved_pool` states and
        # this branch inherits. A tight band on a thin corpus can hold fewer than k
        # rows; falling back to the nearest k is the pre-2026-09-10 behaviour, so a
        # starved slot is no worse off than before rather than empty.
        if len(window) < k:
            window = ranked[:max(k, 1)]
        # ANCHORS SURVIVE THE TRUNCATION (Codex review of #147, minor). Truncating to
        # the nearest k could drop every anchor, and the rotation below promises one
        # anchor is always included when any exists. A guarantee the step above can
        # silently delete is not a guarantee.
        if not any(r.get("anchor") for r in window):
            window = window + [r for r in ranked if r.get("anchor")][:1]
        pool = window or pool
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
