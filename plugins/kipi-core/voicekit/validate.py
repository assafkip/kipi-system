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

from . import assemble, corpus, fingerprint

MIN_ROWS_PER_POOL = 3      # below this, selection silently narrows to repetition;
                           # the fix is curation, so the message says so.


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


def check_fingerprint_fresh(voice):
    """The bands must have been computed from THIS corpus. The canonical-digest
    pattern: corpus changed but fingerprint.json not regenerated = a failure."""
    if voice.fingerprint is None:
        return ["fingerprint.json missing or unparseable"]
    texts = [r.get("text") or "" for r in voice.active_exemplars()
             if r.get("kind") == "post"]
    want = fingerprint.corpus_sha(texts)
    got = voice.fingerprint.get("corpus_sha")
    if got != want:
        return [f"fingerprint.json is stale: corpus_sha {got!r}, post-kind corpus "
                f"is {want!r}. Recompute via the fingerprint CLI (its only writer)."]
    return []


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
    problems += check_pools(voice)
    problems += check_fingerprint_fresh(voice)
    problems += check_budget(voice)
    if voice.skipped_rows:
        problems.append(f"{voice.skipped_rows} corrupt JSONL row(s) skipped by the "
                        f"loader -- fix or remove them")
    return problems
