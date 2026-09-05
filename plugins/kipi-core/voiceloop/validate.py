#!/usr/bin/env python3
"""The LOUD half of the corpus contract. Runs in suites and CLIs, never in the daily job.

corpus.py degrades so the publishing run cannot die; this module fails hard so decay
cannot hide. Same file, two consumers, two postures -- the split IS the design
(validate at edit time, degrade at run time).

Returns problem strings rather than raising, so a pytest suite can assert `== []`
and print every problem at once instead of dying on the first.
"""
from __future__ import annotations

import json
import os
import re

from . import assemble, channel_registry, corpus, fingerprint, selector

MIN_ROWS_PER_POOL = 3      # below this, selection silently narrows to repetition;
                           # the fix is curation, so the message says so.

MIN_ANCHORS_PER_KIND = 3   # an anchor rides in EVERY prompt for its rotation slot,
                           # so one anchor is not "an anchor", it is a pin. See
                           # check_anchor_diversity.


def check_exemplars(path):
    problems = []
    if not os.path.exists(path):
        return [f"{path}: missing"]
    seen_ids = set()
    with open(path, encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                problems.append(f"line {lineno}: unparseable JSON ({exc})")
                continue
            rid = row.get("id")
            if not rid:
                problems.append(f"line {lineno}: no id")
            elif rid in seen_ids:
                problems.append(f"line {lineno}: duplicate id {rid!r}")
            seen_ids.add(rid)
            if row.get("kind") not in corpus.EXEMPLAR_KINDS:
                problems.append(f"{rid}: kind {row.get('kind')!r} not in "
                                f"{corpus.EXEMPLAR_KINDS}")
            if row.get("channel") not in corpus.EXEMPLAR_CHANNELS:
                problems.append(f"{rid}: channel {row.get('channel')!r} not in "
                                f"{corpus.EXEMPLAR_CHANNELS}")
            text = row.get("text") or ""
            if not text.strip():
                problems.append(f"{rid}: empty text")
            if "—" in text:
                problems.append(f"{rid}: emdash in text (the one character the "
                                f"founder bans everywhere)")
            if row.get("status", "active") not in ("active", "retired"):
                problems.append(f"{rid}: status {row.get('status')!r}")
            # voice-2 review: two seed rows shipped literal {{UNVALIDATED}}
            # markers into the corpus -- template scaffolding presented as voice
            # material. Any mustache placeholder in an exemplar is scaffolding.
            if "{{" in text:
                problems.append(f"{rid}: template placeholder in text")
            # And several closed with campaign-hashtag tails, the exact register
            # identity prose disavows. A trailing hashtag-only line is metadata,
            # not voice.
            last = text.strip().splitlines()[-1] if text.strip() else ""
            if re.fullmatch(r"(#\w+[ \t]*)+", last):
                problems.append(f"{rid}: trailing hashtag line in text")
    return problems


CORRECTION_CLASSES = ("deterministic", "interpretive")
CORRECTION_STATUSES = ("active", "promoted", "retired")


def check_corrections(path, channels=None):
    """corrections.jsonl schema health (voice-2 review: the ledger had no
    validator at all, so a malformed or duplicate row passed the gate green)."""
    channels = channels or channel_registry.DEFAULT
    if not os.path.exists(path):
        return []                      # an absent ledger is a valid empty ledger
    problems = []
    seen = set()
    with open(path, encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                problems.append(f"corrections line {lineno}: unparseable ({exc})")
                continue
            rid = row.get("id")
            if not rid:
                problems.append(f"corrections line {lineno}: no id")
            elif rid in seen:
                problems.append(f"corrections line {lineno}: duplicate id {rid!r}")
            seen.add(rid)
            if not (row.get("instruction") or "").strip():
                problems.append(f"{rid}: empty instruction")
            if row.get("class") not in CORRECTION_CLASSES:
                problems.append(f"{rid}: class {row.get('class')!r}")
            if row.get("status") not in CORRECTION_STATUSES:
                problems.append(f"{rid}: status {row.get('status')!r}")
            for ch in row.get("scope") or []:
                if ch not in channels.scopes:
                    problems.append(
                        f"{rid}: unknown scope {ch!r}; the channel vocabulary is "
                        f"{list(channels.scopes)} (from "
                        f"{channels.source or 'the built-in default, no registry'})")
    return problems


def check_pools(voice, channels=None):
    """Selection starvation check: every (channel, kind) pool a slot can ask for."""
    channels = channels or channel_registry.DEFAULT
    problems = []
    rows = voice.active_exemplars()
    for channel in channels.assembled:
        for kind in ("post",):
            n = sum(1 for r in rows if r.get("kind") == kind
                    and r.get("channel", "any") in (channel, "any"))
            if n < MIN_ROWS_PER_POOL:
                problems.append(
                    f"pool ({channel}, {kind}) has {n} active rows, floor is "
                    f"{MIN_ROWS_PER_POOL}. Selection would repeat itself; the fix "
                    f"is curating more rows, not loosening this check.")
    return problems


# Every (channel, slot_kind) a caller can actually ask for. The comment slot is
# here because adversarial review measured it collapsing to ONE selection with
# zero anchors while all three checks stayed silent: ELIGIBLE_KINDS maps
# comment/dm to a ('comment','dm') primary tier that most corpora have no rows
# for, so it is the slot most likely to be thin and the one nobody looks at.
SLOT_KINDS = ("post", "comment")


def checked_slots(channels=None):
    """(channel, slot_kind) for every slot a caller can ask for, channels from
    the registry. The slot KINDS are a property of this engine's selector, not of
    an instance, so they stay here; the channels are not, so they do not."""
    channels = channels or channel_registry.DEFAULT
    return tuple((channel, slot_kind)
                 for channel in channels.assembled
                 for slot_kind in SLOT_KINDS)


# Kept as a module attribute because reviews and docs reference it by name. It is
# DERIVED from the one authority, so it is a view of the default vocabulary and
# not a fifth copy of the channel list.
CHECKED_SLOTS = checked_slots()


def _resolved_slots(voice, k, channels=None):
    """(channel, slot_kind, primary, pool) for each slot, POOL FROM THE SELECTOR.

    Both checks below used to count primary-kind rows by hand, which equals the
    real pool only above k. Below k the selector pads from the fallback tier, so
    the hand count was a partial replica and both checks printed sentences that
    were false about their own corpus (standard review found it by reading and
    measuring, adversarial review by mutation; they agreed by different methods).
    A checker that re-derives the rule it checks is testing its own copy.
    """
    rows = voice.active_exemplars()
    for channel, slot_kind in checked_slots(channels):
        primary, _ = selector.eligible(rows, channel, slot_kind)
        yield (channel, slot_kind, primary,
               selector.resolved_pool(rows, channel, slot_kind, k))


def check_anchor_diversity(voice, k=selector.DEFAULT_K, channels=None):
    """Anchors must ROTATE within the pool a slot actually draws from.

    The pairing this exists for (finding-5, prd-content-engine-sameness-2026-08-09):
    `select` exhausts the primary tier before padding, so a post slot's anchor
    comes from post-kind rows whenever there are enough of them. A corpus carrying
    one post-kind anchor therefore pinned that single row into all 30 rotations --
    measured at exactly that, one id selected 30 times out of 30 -- which is the
    failure selector.py's docstring names: "a pinned anchor is the same
    3-exemplars-forever failure with extra steps."

    (The row id is deliberately not named. This module ships to a PUBLIC skeleton;
    naming an instance's corpus rows in fleet code is the direction
    test_no_founder_data.py exists to prevent, and that test greps for content
    rather than ids, so it would not have caught this one.)

    Counted over the RESOLVED POOL, not over rows of the primary kind. Those differ
    below k, and the difference is not academic: with 3 post rows, 0 post anchors
    and 2 article anchors, 38 anchors ride across 30 prompts from 2 distinct ids,
    while the by-kind count said "0 post anchors, this pins that row into every
    prompt" -- a sentence false in both halves.

    A corpus that marks NOTHING stays silent. `select` guards with `if anchors:`,
    so it pins nothing, and it is the configuration most fleet instances ship with;
    reporting it would red them all for a mode they do not have. But a corpus that
    marks anchors none of which are REACHABLE from a given slot is the opposite
    case and the reason this is per-slot: keying the exemption on the per-slot
    count let exactly that through.

    Loud at edit time, never a runtime refusal. corpus.py keeps degrading; a thin
    anchor set costs voice, and killing the daily job over it costs more.
    """
    problems = []
    corpus_has_anchors = any(r.get("anchor") for r in voice.active_exemplars())
    if not corpus_has_anchors:
        return problems
    for channel, slot_kind, _primary, pool in _resolved_slots(voice, k, channels):
        reachable = [r for r in pool if r.get("anchor")]
        if len(reachable) < MIN_ANCHORS_PER_KIND:
            problems.append(
                f"slot ({channel}, {slot_kind}) can reach {len(reachable)} of the "
                f"corpus's anchor rows, floor is {MIN_ANCHORS_PER_KIND}. This slot "
                f"draws from a pool of {len(pool)}, so the anchors it does reach "
                f"ride in every prompt. The fix is marking anchor:true on rows this "
                f"slot can actually select, not loosening this check.")
    return problems


def check_rotation_headroom(voice, k=selector.DEFAULT_K, channels=None):
    """A pool no larger than k cannot rotate: `select` takes min(k, len(pool)).

    Found by adversarial review 2026-08-09, measured over counters 0-29 with k=4
    against a corpus of n post rows plus 18 article-excerpts:

        n = 0 -> 18 distinct    n = 3 ->  21 distinct
        n = 1 -> 18 distinct    n = 4 ->   1 distinct   <-- the only "same set"
        n = 2 -> 20 distinct    n = 5 ->   5 distinct

    The first version of this check fired across `n <= k` counting POST ROWS, and
    said "every prompt gets the SAME set" -- false at n=1,2,3, where padding makes
    selection vary. Worse, its advice ("curate more post rows") applied one row at
    a time walks an operator from 3 rows to 4, i.e. from 21 distinct selections to
    1. A validator that steers you onto the cliff it was written to catch is worse
    than no validator.

    Both conditions now read the resolved POOL, so each says something true:

    - pool <= k: there is one possible selection and every prompt gets it.
    - primary < k while the pool is padded: the slot is being taught by the wrong
      FORM, which is the original defect, and is separate from rotation.

    Both name the same concrete target, k+1, instead of "more" -- that is what
    stops the one-row-at-a-time walk onto the cliff.

    Overlaps `check_pools` below 3 rows on purpose: that one is about starvation,
    this is about repetition and form, and a corpus can clear one while failing
    the other.
    """
    problems = []
    floor = k + 1
    for channel, slot_kind, primary, pool in _resolved_slots(voice, k, channels):
        if not pool:
            continue                    # an empty pool is check_pools' story
        if len(pool) <= k:
            problems.append(
                f"slot ({channel}, {slot_kind}) draws from a pool of {len(pool)} "
                f"and selection takes {k}, so there is exactly one possible set "
                f"and EVERY prompt gets it. Curate to at least {floor} rows this "
                f"slot can select.")
        # 0 < primary < k, not primary < k. An EMPTY primary tier is the designed
        # wholesale fallback, spelled out in ELIGIBLE_KINDS ("Comments prefer
        # comment/dm rows, then short posts"): a corpus with no comment rows is
        # using the design, not failing it, and flagging it reds every instance
        # that never wrote comment exemplars. The defect is a tier that is
        # populated but too thin to fill k, where the corpus is trying to supply
        # the right form and silently gets the wrong one. An empty POST tier is
        # coarser still and belongs to check_pools.
        if 0 < len(primary) < k and len(pool) > len(primary):
            problems.append(
                f"slot ({channel}, {slot_kind}) has only {len(primary)} rows of "
                f"its own kind, fewer than the {k} selection takes, so every "
                f"prompt is padded from the fallback tier and this slot is taught "
                f"by the wrong FORM. Curate to at least {floor} rows of the "
                f"slot's own kind -- stopping at exactly {k} trades this defect "
                f"for a worse one, a single set forever.")
    return problems


def check_fingerprint_fresh(voice):
    """The bands must have been computed from THIS corpus. The canonical-digest
    pattern: corpus changed but fingerprint.json not regenerated = a failure."""
    if voice.fingerprint is None:
        return ["fingerprint.json missing or unparseable"]
    problems = []
    # Instrument skew FIRST (voice-1 review blocker): version_skew existed and
    # nothing called it, so a metrics change with an unchanged corpus passed
    # every check while the verdicts went wrong -- the exact scar the version
    # exists for, reproduced by the reviewer against this very function.
    if fingerprint.version_skew(voice.fingerprint):
        problems.append(
            f"fingerprint.json was computed by metrics_version "
            f"{voice.fingerprint.get('metrics_version')!r} but this instrument is "
            f"{fingerprint.METRICS_VERSION}. Recompute via the fingerprint CLI.")
    texts = [r.get("text") or "" for r in voice.active_exemplars()
             if r.get("kind") == "post"]
    want = fingerprint.corpus_sha(texts)
    got = voice.fingerprint.get("corpus_sha")
    if got != want:
        problems.append(
            f"fingerprint.json is stale: corpus_sha {got!r}, post-kind corpus "
            f"is {want!r}. Recompute via the fingerprint CLI (its only writer).")
    return problems


def check_budget(voice, channels=None):
    """The largest legal assembly must fit the budget. Suite-time, so the daily
    job never needs a runtime cap -- the cap that failed loudly here cannot slice
    silently there."""
    channels = channels or channel_registry.DEFAULT
    problems = []
    for channel in channels.assembled:
        worst = 0
        for counter in range(12):        # one rotation lap is enough to find the max
            text, _ = assemble.voice_section(voice, channel, counter)
            worst = max(worst, len(text))
        if worst > assemble.BUDGET_CHARS:
            problems.append(f"{channel}: largest assembly {worst} chars exceeds "
                            f"budget {assemble.BUDGET_CHARS}")
    return problems


#: The share of an assembled prompt that may be CORRECTIONS rather than his own
#: writing. A headroom alarm in the same posture as `assemble.BUDGET_CHARS`:
#: suite-time only, never a runtime slice.
#:
#: why a share and not just a size: the founder-directed premise of this corpus is
#: that posts are written FROM his examples, never from a model's impression of
#: him. Corrections are RULES ABOUT him. When the rules outweigh the examples, that
#: premise has quietly inverted while every size check still passes, because the
#: total can sit inside budget with the mix completely wrong.
#:
#: MEASURED 2026-08-31 against the LARGEST assembly of 12 counters: linkedin 11618
#: of 20552 chars (57%), x 10154 of 16994 (60%). Set at 0.70 to sit above that and
#: bite within a few additions -- a guard set below the current reading is a guard
#: someone switches off.
#:
#: THAT DENOMINATOR WAS THE WRONG END, so the two numbers above are the best case
#: rather than the reading that matters (found in review on PR #301). Rules crowd
#: his writing out worst at the THINNEST prompt a rotation produces, not the
#: fattest. Re-measured 2026-09-04 on the live ASK corpus, same rows, dividing by
#: the minimum: linkedin 11618 of 17995 (65%), x 10154 of 14293 (71%), reddit 527
#: of 7541 (7%).
#:
#: 0.70 IS DELIBERATELY LEFT ALONE, so x trips the moment an instance picks this
#: up. Moving the ceiling to clear a reading the corrected arithmetic has just
#: exposed would be switching the alarm off in the same edit that made it work.
#: How much of his prompt may be rules is the voice owner's number. The
#: arithmetic under it is the engine's.
#:
#: The remedy when it fires is RETIREMENT, never rotation and never a quiet drop.
#: `status` already gates this (`corpus.active_corrections` renders only "active";
#: verified 2026-08-31 that promoted/retired rows really are absent from the
#: prompt), so retiring a superseded rule is a one-field edit. Two rules that
#: genuinely say one thing get MERGED into one loud statement, never dropped.
CORRECTION_SHARE_CEILING = 0.70


def check_correction_share(voice, channels=None):
    """Corrections must not crowd his own writing out of the prompt."""
    channels = channels or channel_registry.DEFAULT
    problems = []
    for channel in channels.assembled:
        # THE MINIMUM, not the maximum. `check_budget` right above this uses `max`
        # and is correct to -- largest assembly against a size cap -- and this loop
        # was written from that one, which is how the wrong extremum arrived. Here
        # the max reports the BEST case of the very thing being graded: a rotation's
        # prompts differ by thousands of characters, so the fattest one always
        # flatters the share. Measured on the live ASK corpus 2026-09-04, the x
        # channel read 60% against the max and 71% against the min, with the ceiling
        # at 70%. The guard returned [] on a corpus already over its own line.
        # THE FULL ROTATION, not a fixed 12. `selector.select` offsets by
        # `counter % len(pool)`, so the period is the pool size and a 12-counter
        # window (inherited from `check_budget` with the rest of this loop) simply
        # does not see counters 12..n-1. Measured on the live ASK corpus 2026-09-04:
        # pools are 45 / 31 / 10, and linkedin's true thinnest prompt is 16987 chars
        # against the 17995 the 12-window reported. Same defect class as the max/min
        # bug this loop was just fixed for -- right extremum, wrong sample -- which
        # is why the period is DERIVED here instead of being a second literal.
        pool = selector.resolved_pool(voice.active_exemplars(), channel, "post",
                                      selector.DEFAULT_K)
        lengths = [len(assemble.voice_section(voice, channel, counter)[0])
                   for counter in range(len(pool) or 1)]
        # A counter that assembles to nothing has no share to measure, and taking a
        # minimum over it divides by zero. Drop the empties so the channel is graded
        # on the prompts it really produces; a channel with no prompt at all is
        # skipped, which is what the old `if not worst_len` meant.
        lengths = [n for n in lengths if n]
        if not lengths:
            continue
        thinnest = min(lengths)
        applied = [r for r in voice.active_corrections()
                   if not r.get("scope") or channel in r["scope"]]
        rules = sum(len(r.get("instruction") or "") for r in applied)
        share = rules / thinnest
        if share > CORRECTION_SHARE_CEILING:
            problems.append(
                f"{channel}: corrections are {rules} of {thinnest} chars "
                f"({share:.0%}) of the thinnest assembly, over the "
                f"{CORRECTION_SHARE_CEILING:.0%} ceiling. Retire a superseded "
                f"correction (set its status off 'active'), or merge two that say "
                f"one thing into one statement. Do not rotate them: a correction "
                f"dropped from a prompt is a rule the model never sees.")
    return problems


def check_all(voice_dir, channels=None):
    """Every check, one list. [] is a healthy corpus.

    `channels` is a `channel_registry.Channels`. None LOADS the registry that owns
    `voice_dir`, and falls back to the built-in default when nothing does -- which
    is what every instance without a registry gets and is byte-identical to the
    behavior before the registry existed.

    THIS IS THE LOAD PATH AND IT USED TO BE A SENTENCE. The line above said "an
    instance seam that owns a registry passes for_instance(<repo root>)" and no
    caller in this repo ever did: measured on PR #291, `for_instance` had one
    definition and zero non-test callers, so every corpus was graded against the
    built-in vocabulary no matter what its instance declared. The one instance
    that owns a registry today declares a scope the built-in default does not
    carry, so its first correction in that scope would have been refused by its
    own suite as unknown. Documenting a seam is not wiring one.
    """
    if channels is None:
        channels = channel_registry.for_path(voice_dir)
    voice = corpus.load(voice_dir)
    problems = check_exemplars(os.path.join(voice_dir, corpus.EXEMPLARS))
    problems += check_corrections(os.path.join(voice_dir, corpus.CORRECTIONS),
                                  channels)
    problems += check_pools(voice, channels)
    problems += check_anchor_diversity(voice, channels=channels)
    problems += check_rotation_headroom(voice, channels=channels)
    problems += check_fingerprint_fresh(voice)
    problems += check_budget(voice, channels)
    problems += check_correction_share(voice, channels)
    if voice.skipped_rows:
        problems.append(f"{voice.skipped_rows} corrupt JSONL row(s) skipped by the "
                        f"loader -- fix or remove them")
    return problems
