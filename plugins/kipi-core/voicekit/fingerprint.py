#!/usr/bin/env python3
"""Style fingerprint: measurable voice, computed from a corpus, scored on a candidate.

why this exists (2026-08-06): a 55k-char prose style guide shipped in every generation
prompt and the founder still read the output as "missing my voice as a grumpy engineer".
Prose describing a distribution is a region; only numbers computed FROM the writing can
say whether a candidate sits inside it. This module is the instrument: `compute()` builds
percentile bands from real exemplars, `score()` reports where a candidate falls.

Everything is pure text ops -- no model, no network, no clock. The metric set is the
deterministic slice of the voice only. Whether a scar is true, whether a coined name is
good, whether the humor lands: none of that is here, and any claim that a script scores
"voice authenticity" would be prompt-only enforcement wearing a script's name.

Band semantics: p10/p90 over the corpus, per metric. A candidate outside a band is
FLAGGED, not judged -- the caller decides which metrics block (tight bands plus a known
generator failure direction) and which stay advisory (real signal, too noisy to block on).
That tiering lives in the instance's fingerprint.json, not in code, because the corpus
owner is the one who can see false positives: a voice gate that rejects the founder's own
writing gets switched off, which protects nothing.
"""
from __future__ import annotations

import hashlib
import json
import re

# A sentence boundary for STATISTICS, not for grammar. Naive on purpose: the same
# splitter runs on corpus and candidate, so a systematic bias cancels in the comparison.
_SENT_SPLIT = re.compile(r"[.!?]+[\s\"')\]]|[.!?]+$|\n+")
_WORD = re.compile(r"[A-Za-z0-9']+")

# Contraction FORMS, not an enumerated word list: the rate is the signal.
_CONTRACTION = re.compile(r"\b\w+'(?:t|s|re|m|ve|ll|d)\b", re.I)

# The formal pairs a model reaches for when it is being careful. Each has a contracted
# form the founder actually uses; a high count is the "characterless" register in one
# number. Word-boundary matched so "is not" inside "this nothing" cannot fire.
_FORMAL_PAIRS = re.compile(
    r"\b(?:do not|does not|did not|is not|are not|was not|were not|cannot|"
    r"can not|will not|would not|should not|could not|have not|has not|it is|"
    r"that is|there is|you are|we are|they are|i am)\b", re.I)

_FIRST_PERSON = re.compile(r"\b(?:I|I'm|I've|I'll|I'd|we|we're|we've|my|our|me)\b")

# Hedges: the softeners that dilute a verdict. Small list, presence-per-post is the
# metric; an exhaustive list would be a banned-word gate, which is a different tool.
_HEDGE = re.compile(
    r"\b(?:probably|perhaps|maybe|might|somewhat|arguably|likely|generally|"
    r"typically|often|tend to|seems? to|sort of|kind of)\b", re.I)


def sentences(text):
    """Sentence word-counts, in order. Empty segments dropped."""
    counts = []
    for seg in _SENT_SPLIT.split(text or ""):
        if seg is None:
            continue
        words = _WORD.findall(seg)
        if words:
            counts.append(len(words))
    return counts


def paragraphs(text):
    """Sentence counts per paragraph (blank-line separated)."""
    out = []
    for para in re.split(r"\n\s*\n", (text or "").strip()):
        if para.strip():
            out.append(max(1, len(sentences(para))))
    return out


def _word_count(text):
    return len(_WORD.findall(text or ""))


def _monotony_run(counts):
    """Longest run of consecutive sentences within +-2 words of each other.

    The uniformity tell: a model writes evenly, the founder does not. Measured on his
    corpus the longest observed run is short; generated posts run long.
    """
    best = run = 1
    for prev, cur in zip(counts, counts[1:]):
        run = run + 1 if abs(cur - prev) <= 2 else 1
        best = max(best, run)
    return best if counts else 0


def metrics(text):
    """Every per-text metric, one dict. Pure; safe on empty input."""
    text = (text or "").strip()
    counts = sentences(text)
    n_sent = len(counts) or 1
    words = _word_count(text) or 1
    paras = paragraphs(text)
    mean = sum(counts) / n_sent
    var = sum((c - mean) ** 2 for c in counts) / n_sent
    body_questions = text.count("?")
    # The FINAL sentence's question mark belongs to ending_gate, not to this metric.
    if text.rstrip().endswith("?"):
        body_questions -= 1
    return {
        "sentence_mean": round(mean, 2),
        "sentence_stdev": round(var ** 0.5, 2),
        "short_share": round(sum(1 for c in counts if c <= 6) / n_sent, 3),
        "long_share": round(sum(1 for c in counts if c >= 25) / n_sent, 3),
        "monotony_run": _monotony_run(counts),
        "para_single_share": round(
            sum(1 for p in paras if p == 1) / (len(paras) or 1), 3),
        "para_max_sentences": max(paras) if paras else 0,
        "contraction_rate": round(len(_CONTRACTION.findall(text)) * 100 / words, 2),
        "formal_pair_count": len(_FORMAL_PAIRS.findall(text)),
        "first_person_rate": round(len(_FIRST_PERSON.findall(text)) * 100 / words, 2),
        "hedge_count": len(_HEDGE.findall(text)),
        "midpost_questions": max(0, body_questions),
        "colon_rate": round(text.count(":") * 100 / words, 2),
    }


METRIC_NAMES = sorted(metrics("x."))


def _percentile(values, q):
    """Nearest-rank percentile. No numpy: this runs inside a launchd job."""
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[idx]


# Version of the METRIC DEFINITIONS, not the file format. Bumped whenever any
# metric's computation changes (a splitter tweak, a new regex). Review finding-8:
# bands computed by one instrument and evaluated by another is the _version_key
# scar again -- silent skew, every check green, verdicts wrong. `version_skew`
# is the paired check; the consuming staleness test calls it.
METRICS_VERSION = 2


def version_skew(fingerprint_doc):
    """Truthy when the bands were computed by a different metrics version."""
    return (fingerprint_doc or {}).get("metrics_version") != METRICS_VERSION


def corpus_sha(texts):
    """Identity of the corpus a fingerprint was computed from. Order-independent."""
    digest = hashlib.sha256()
    for t in sorted(" ".join((t or "").split()) for t in texts):
        digest.update(t.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:32]


def compute(texts, generated_at, scope=None, blocking=None, advisory=None):
    """Percentile bands over a corpus. The ONLY producer of fingerprint.json content.

    `generated_at` is injected, never read from a clock -- same doctrine as the postbook:
    a writer that cannot invent a timestamp cannot produce a future-dated row.
    """
    if not texts:
        raise ValueError("cannot fingerprint an empty corpus")
    rows = [metrics(t) for t in texts]
    bands = {}
    for name in METRIC_NAMES:
        values = [r[name] for r in rows]
        bands[name] = {"p10": _percentile(values, 0.10),
                       "p50": _percentile(values, 0.50),
                       "p90": _percentile(values, 0.90),
                       "min": min(values), "max": max(values)}
    return {
        "generated_at": generated_at,
        "corpus_sha": corpus_sha(texts),
        "corpus_size": len(texts),
        "metrics_version": METRICS_VERSION,
        "scope": scope or {},
        "metrics": bands,
        "blocking": [_norm_blocking(b) for b in (blocking or [])],
        "advisory": list(advisory or []),
    }


def _norm_blocking(entry):
    """{'metric', 'direction'} from either shape. Strings are legacy 'both'.

    Direction is load-bearing (review finding-2): sentence_mean is a CAP -- the
    founder's punchiest register sits BELOW the band and must never block.
    """
    if isinstance(entry, str):
        return {"metric": entry, "direction": "both"}
    return {"metric": entry.get("metric"),
            "direction": entry.get("direction", "both")}


def _bounds(band):
    """The BLOCKING bounds: p10/p90 widened to the corpus extremes.

    Review finding-1 (blocker): p10/p90 alone reject the corpus's own extreme
    members on any small corpus -- the control-set requirement ("the gate must
    never reject the voice it encodes") would be unsatisfiable by construction.
    min/max are corpus observations, so every corpus member is inside its own
    bounds, which is exactly the property the control-set test asserts.
    """
    # Degrade-not-die on a partial band dict (voice-1 review, minor): a
    # hand-migrated band can hold min without p10; min(None, x) raises. Every
    # present bound participates; an absent one simply does not constrain.
    lows = [v for v in (band.get("p10"), band.get("min")) if v is not None]
    highs = [v for v in (band.get("p90"), band.get("max")) if v is not None]
    if not lows or not highs:
        return None, None
    return min(lows), max(highs)


def score(text, fingerprint):
    """Where one candidate falls against the bands. Report, not verdict.

    Returns {metric: {"value", "band", "inside"}}. `inside` uses the corpus MIN/MAX
    widened to the band edges: outside [p10, p90] is out-of-band, but a candidate is only
    flagged in a DIRECTION the corpus itself never reaches -- p10/p90 on n~30 are noisy,
    and the caller's blocking tier is what turns a flag into a rejection.
    """
    got = metrics(text)
    out = {}
    for name, band in (fingerprint.get("metrics") or {}).items():
        value = got.get(name)
        if value is None or band.get("p10") is None:
            continue
        lo, hi = _bounds(band)
        if lo is None:
            continue
        out[name] = {"value": value, "band": [band["p10"], band["p90"]],
                     "bounds": [lo, hi], "inside": lo <= value <= hi}
    return out


def out_of_band(text, fingerprint, tier="blocking"):
    """The named metrics from one tier that the candidate fails. [] is a pass.

    Blocking entries carry a direction (above|below|both): a cap only fails
    ABOVE its widened bounds, a floor only BELOW. Legacy plain-string entries
    mean both.

    This function is GATE semantics. The advisory tier is report-only: read it
    through `score()`, never through here -- passing tier="advisory" would
    coerce report-only names into both-direction rejections (voice-1 review,
    minor). The tier parameter exists for a future PROMOTED tier, not for
    advisory reads.
    """
    got = metrics(text)
    bands = fingerprint.get("metrics") or {}
    failed = []
    for entry in fingerprint.get(tier) or []:
        norm = _norm_blocking(entry)
        name, direction = norm["metric"], norm["direction"]
        band = bands.get(name)
        value = got.get(name)
        if band is None or value is None or band.get("p10") is None:
            continue
        lo, hi = _bounds(band)
        if lo is None:
            continue
        too_high = direction in ("above", "both") and value > hi
        too_low = direction in ("below", "both") and value < lo
        if too_high or too_low:
            failed.append(name)
    return sorted(failed)


def load(path):
    """Read a fingerprint.json. Raises on malformed content -- the CALLER decides
    whether a missing/broken file degrades (daily job: yes) or fails (validator: no)."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)
