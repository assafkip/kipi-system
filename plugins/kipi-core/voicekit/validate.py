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

from . import assemble, corpus, fingerprint, selector

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


def check_corrections(path):
    """corrections.jsonl schema health (voice-2 review: the ledger had no
    validator at all, so a malformed or duplicate row passed the gate green)."""
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
                if ch not in ("linkedin", "x", "substack", "medium", "dm",
                              "email", "comment"):
                    problems.append(f"{rid}: unknown scope {ch!r}")
    return problems


def check_pools(voice):
    """Selection starvation check: every (channel, kind) pool a slot can ask for."""
    problems = []
    rows = voice.active_exemplars()
    for channel in ("linkedin", "x"):
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
CHECKED_SLOTS = tuple((channel, slot_kind)
                      for channel in ("linkedin", "x")
                      for slot_kind in ("post", "comment"))


def _resolved_slots(voice, k):
    """(channel, slot_kind, primary, pool) for each slot, POOL FROM THE SELECTOR.

    Both checks below used to count primary-kind rows by hand, which equals the
    real pool only above k. Below k the selector pads from the fallback tier, so
    the hand count was a partial replica and both checks printed sentences that
    were false about their own corpus (standard review found it by reading and
    measuring, adversarial review by mutation; they agreed by different methods).
    A checker that re-derives the rule it checks is testing its own copy.
    """
    rows = voice.active_exemplars()
    for channel, slot_kind in CHECKED_SLOTS:
        primary, _ = selector.eligible(rows, channel, slot_kind)
        yield (channel, slot_kind, primary,
               selector.resolved_pool(rows, channel, slot_kind, k))


def check_anchor_diversity(voice, k=selector.DEFAULT_K):
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
    for channel, slot_kind, _primary, pool in _resolved_slots(voice, k):
        reachable = [r for r in pool if r.get("anchor")]
        if len(reachable) < MIN_ANCHORS_PER_KIND:
            problems.append(
                f"slot ({channel}, {slot_kind}) can reach {len(reachable)} of the "
                f"corpus's anchor rows, floor is {MIN_ANCHORS_PER_KIND}. This slot "
                f"draws from a pool of {len(pool)}, so the anchors it does reach "
                f"ride in every prompt. The fix is marking anchor:true on rows this "
                f"slot can actually select, not loosening this check.")
    return problems


def check_rotation_headroom(voice, k=selector.DEFAULT_K):
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
    for channel, slot_kind, primary, pool in _resolved_slots(voice, k):
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


def check_budget(voice, channels=("linkedin", "x")):
    """The largest legal assembly must fit the budget. Suite-time, so the daily
    job never needs a runtime cap -- the cap that failed loudly here cannot slice
    silently there."""
    problems = []
    for channel in channels:
        worst = 0
        for counter in range(12):        # one rotation lap is enough to find the max
            text, _ = assemble.voice_section(voice, channel, counter)
            worst = max(worst, len(text))
        if worst > assemble.BUDGET_CHARS:
            problems.append(f"{channel}: largest assembly {worst} chars exceeds "
                            f"budget {assemble.BUDGET_CHARS}")
    return problems


def check_all(voice_dir):
    """Every check, one list. [] is a healthy corpus."""
    voice = corpus.load(voice_dir)
    problems = check_exemplars(os.path.join(voice_dir, corpus.EXEMPLARS))
    problems += check_corrections(os.path.join(voice_dir, corpus.CORRECTIONS))
    problems += check_pools(voice)
    problems += check_anchor_diversity(voice)
    problems += check_rotation_headroom(voice)
    problems += check_fingerprint_fresh(voice)
    problems += check_budget(voice)
    if voice.skipped_rows:
        problems.append(f"{voice.skipped_rows} corrupt JSONL row(s) skipped by the "
                        f"loader -- fix or remove them")
    return problems
