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
    problems += check_fingerprint_fresh(voice)
    problems += check_budget(voice)
    if voice.skipped_rows:
        problems.append(f"{voice.skipped_rows} corrupt JSONL row(s) skipped by the "
                        f"loader -- fix or remove them")
    return problems
