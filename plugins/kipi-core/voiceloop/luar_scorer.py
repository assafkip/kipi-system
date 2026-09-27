#!/usr/bin/env python3
"""The authorship scoring contract, in ONE module so two implementations cannot
disagree (prd-voice-authorship-scoring-2026-08-17, Codex finding-1).

The metric answers the one question the ten surface gates structurally cannot
approach: does this draft SIT NEAR his exemplar corpus in an authorship
embedding. That is corpus similarity -- evidence about authorship, never a
verdict on it. The 2026-08-18 decontamination is the standing proof of the gap:
every field of every record was computed correctly for a month while the
reference described templated marketing copy instead of him (sp-534dce09).
Human-facing surfaces say "corpus similarity"; the `authorship_*` record keys
stay, as a recorded shape. It is ADVISORY FOREVER under that PRD
-- it never enters a blocking tier, and nothing here can fail a draft.

## Why every clause below is pinned by a test rather than by this docstring

Each was measured on 2026-08-17 against the real corpus before any code existed
(`social-voice/q-system/output/luar-separation/`). The measurement is what makes
them non-negotiable, and a prose contract nobody executes is how two callers end
up computing two different numbers under one name.

- **Tokenization: single-document, 512-token truncation.** The chunk shape is NOT
  the contract and the difference is not cosmetic: short-band AUC is 0.883 single
  and 0.702 chunked against generic output, 0.836 versus 0.584 against other
  humans. So the emitted record NAMES the shape it used; a future change cannot
  silently move every number that was ever logged.
- **Combining exemplars: mean of per-document embeddings, then cosine.** Not
  cosine-of-concatenation (one long exemplar would dominate the region) and not
  mean-of-pairwise-cosines (a different statistic, and the one the 2026-08-17
  experiment happened to use for its AUC feature).
- **Reference: the per-length-band leave-one-out MEDIAN**, never p10. p10 was
  written into the PRD, then measured and falsified: at p10 the share of generic
  control drafts clearing his own floor is 39.4% short, 92.9% mid, 100% long,
  because his weakest real posts sit below the entire control distribution and
  set the floor. Against the median, 0% of long controls and 3% of short controls
  clear the line.
- **Band by the draft's OWN word count**, at the cuts the experiment used: short
  under 60, mid 60 to 150, long over 150. Banding is per length band only --
  pooled AUC (0.664) is worse than either band alone because cosine scale rises
  with length, and the channel x band cell counts (two cells hold a single row)
  forbid the finer split.
- **Mid gets a number and an explicitly null reference.** Excluded from BANDING
  (0.699/0.694, inconclusive under both tokenizations) is not excluded from
  scoring. Emitting a score against a reference nobody trusts would be worse than
  emitting no reference at all.

## torch is not a dependency of this module's import

`TransformersBackend` is the ONLY code here that touches torch/transformers, and
it imports them inside `_load()`. Importing this module, and every pure function
in it, works in an environment with neither. That is load-bearing twice over: the
319MB model must never load inside the scheduled posting lane, and the contract
tests must be able to run in the repo's own interpreter, which has no torch.

The tokenizer/model call shape is lifted verbatim from the experiment's
`Embedder.embed` (`run_experiment.py`, episode shape "single") rather than
rewritten, because the measured numbers belong to that exact shape -- including
embedding one text at a time so the episode axis stays (1, E, L).
"""
from __future__ import annotations

import difflib
import re
import statistics

# 319MB on disk, measured by `du` on the HF cache 2026-08-17. Two comments in this
# file said 1-2GB, which is the torch WHEEL download that `luar_env_backend.py`
# describes correctly; the two got conflated and the wrong figure was then repeated
# into a design decision. A number in a why-comment is load-bearing exactly because
# the next reader uses it instead of re-measuring.
MODEL_ID = "rrivera1849/LUAR-MUD"

# The record carries this string so a stored number can always be read back
# against the shape that produced it. Changing the shape means changing this
# value, which makes the change visible in every consumer instead of silent.
TOKENIZATION = "single-document-512"
MAX_TOKENS = 512

# The experiment's cuts, reused rather than re-derived. `band_of` is by the
# draft's own word count, never by the channel or by the reference set.
SHORT_MAX_WORDS = 60      # short = under 60 words
LONG_MIN_WORDS = 150      # long  = over 150 words

# Mid is deliberately absent. Its separation measured INCONCLUSIVE under both
# tokenizations, so it gets a cosine and an explicitly null reference.
BANDED = ("short", "long")

# Below this many exemplars in a band, a leave-one-out median is a median of one
# or two numbers -- an artifact of the cell count, not a central tendency. The
# same counting that killed per-cell banding kills a reference here.
MIN_REFERENCE_ROWS = 3

# --- the holdout identity rule (sp-9194e0bc) ---------------------------------
#
# A draft reaching the gate has NO id, so identity is judged on the text. The
# realistic case is not byte-identical either: the founder re-scores a post he
# lightly edited after banking it, and a hash misses that entirely.
#
# The statistic is CONTAINMENT of contiguous matching word runs in the shorter
# text, not difflib's ratio. Ratio is 2M/(la+lb) and it punishes a length gap, so
# an excerpt or an expanded draft slips past it; containment is M/min(la,lb) and
# it does not. Both thresholds below were measured against the real 61-row corpus
# on 2026-08-17 rather than chosen:
#
#   worst DISTINCT pair, no floor .... 0.5455 (11-token row vs a long one)
#   worst DISTINCT pair, 12+ tokens .. 0.4375
#   verbatim self .................... 1.0000
#   light edit (dropped sentence,
#     three words swapped) ........... 0.9937
#   first-half excerpt ............... 1.0000
#   full paraphrase .................. 0.2333
#
# 0.80 sits in the empty band between 0.4375 and 0.9937 with headroom on both
# sides. It is not a tuned number; there is nothing between those two clusters.
IDENTITY_CONTAINMENT = 0.80

# Under this many tokens, containment stops being evidence: a five-word post is
# trivially contained in anything. The worst distinct pair in the corpus (0.5455)
# is exactly this shape, and it disappears at 12. Below the floor the rule falls
# back to exact normalized equality, which still catches a verbatim re-score.
IDENTITY_MIN_TOKENS = 12

_IDENTITY_TOKEN = re.compile(r"[a-z0-9']+")


def normalize_for_identity(text):
    """Word tokens, casefolded, punctuation and layout dropped.

    Reflowing paragraphs, changing headline case, or adding a trailing ellipsis
    does not make it a different post, and every one of those happens between
    banking a row and re-scoring it.
    """
    return tuple(_IDENTITY_TOKEN.findall((text or "").casefold()))


def same_text(a, b):
    """Is `b` the same piece of writing as `a`, for the purpose of holding it out.

    Deliberately a separate named predicate rather than an inline comparison: it
    is the one clause here with a blind spot worth stating, and a rule nobody can
    call is a rule nobody can test.

    What it does NOT catch, stated rather than discovered later:
      - a genuine rewrite of the same post from scratch (paraphrase measured at
        0.2333). Same ideas, new surface, and it stays in the region.
      - a lightly edited version of a row under 12 tokens, which needs exact
        equality. 4 of the corpus's 61 rows are that short.
      - a draft assembled from short quotes of several banked rows, where no
        single row clears containment.
    """
    ta, tb = normalize_for_identity(a), normalize_for_identity(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    if min(len(ta), len(tb)) < IDENTITY_MIN_TOKENS:
        return False
    # autojunk=False is load-bearing, not a default worth copying blindly:
    # SequenceMatcher treats any element appearing in more than 1% of a sequence
    # longer than 200 elements as junk. Word tokens over a long-form post trip
    # that on "the" and "a", which silently deletes the matching runs that ARE
    # the evidence, and the holdout would then quietly match nothing.
    matcher = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / min(len(ta), len(tb)) >= IDENTITY_CONTAINMENT


class ScorerUnavailable(RuntimeError):
    """Anything that stops a score being produced.

    One exception type on purpose: the caller's contract turns ANY failure into
    `authorship: null` plus `authorship_error`, so a crash and an empty region
    must be indistinguishable to a reader. A missing torch, a missing weight
    file, and a band with no exemplars are all "no number this run".
    """


# ------------------------------------------------------------------ backend ----


class TransformersBackend:
    """The only object in this repo that loads LUAR-MUD. Weights load on the
    first `encode`, never at import and never at construction."""

    def __init__(self, model_id=MODEL_ID):
        self.model_id = model_id
        self._tok = None
        self._model = None
        self._torch = None

    def _load(self):
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except Exception as exc:                      # noqa: BLE001
            raise ScorerUnavailable(
                f"torch/transformers unavailable: {exc}") from exc
        try:
            self._tok = AutoTokenizer.from_pretrained(self.model_id)
            self._model = AutoModel.from_pretrained(self.model_id,
                                                    trust_remote_code=True)
            self._model.eval()
            torch.manual_seed(0)
            self._torch = torch
        except Exception as exc:                      # noqa: BLE001
            raise ScorerUnavailable(f"model load failed: {exc}") from exc

    def encode(self, documents):
        """One vector per document. `documents` is already one-document-per-text.

        Batching would change the episode axis: LUAR takes (batch, episode,
        length), and the measured numbers come from one text per call with a
        single-document episode. Looping is slower and is what was measured.
        """
        self._load()
        torch = self._torch
        out = []
        for text in documents:
            enc = self._tok([text], max_length=MAX_TOKENS,
                            padding="max_length", truncation=True,
                            return_tensors="pt")
            ids = enc["input_ids"].unsqueeze(0)        # (1, E, L)
            mask = enc["attention_mask"].unsqueeze(0)
            with torch.no_grad():
                vec = self._model(input_ids=ids, attention_mask=mask)
            vec = torch.nn.functional.normalize(vec, p=2, dim=-1)[0]
            out.append([float(x) for x in vec.reshape(-1)])
        return out


# ------------------------------------------------------------ the one embed ----


def embed(texts, backend):
    """THE embed site. Every vector in this system is produced here.

    Single-document: each text becomes exactly ONE document, so the list handed
    to the backend has the same length as `texts`. A caller that wants chunking
    has to change this function, which changes the tokenization name with it.
    """
    documents = [str(t) for t in texts]
    vectors = backend.encode(documents)
    if len(vectors) != len(documents):
        raise ScorerUnavailable(
            f"backend returned {len(vectors)} vectors for {len(documents)} "
            f"documents")
    return [_unit(v) for v in vectors]


# -------------------------------------------------------------- vector math ----


def _unit(vec):
    norm = sum(x * x for x in vec) ** 0.5
    if norm == 0:
        raise ScorerUnavailable("zero-norm embedding")
    return [x / norm for x in vec]


def cosine(a, b):
    if len(a) != len(b):
        raise ScorerUnavailable(f"dimension mismatch {len(a)} vs {len(b)}")
    return sum(x * y for x, y in zip(a, b))


def region_vector(vectors):
    """THE combine site: mean of per-document embeddings, then unit-normalized.

    Normalizing AFTER the mean is what makes the next step a cosine rather than a
    dot product of unequal magnitudes. Averaging pairwise cosines instead would
    be a different statistic and the PRD rejects it by name.
    """
    if not vectors:
        raise ScorerUnavailable("empty region: no exemplars to combine")
    width = len(vectors[0])
    if any(len(v) != width for v in vectors):
        raise ScorerUnavailable("ragged region: exemplar vectors differ in width")
    mean = [sum(v[i] for v in vectors) / len(vectors) for i in range(width)]
    return _unit(mean)


def region_cosine(vec, region_vectors):
    """Similarity of one document to a region. The only way to get a score."""
    return cosine(vec, region_vector(region_vectors))


# --------------------------------------------------------------- the bands ----


def usable_as_reference(row):
    """May this row shape the region a draft is measured against?

    The refusal the seed- id prefix never was (sp-534dce09): 11 of 13 long-band
    rows were templated marketing posts, the band median read 0.8594 -- the
    self-similarity of templated copy -- and 11 of 12 posts the founder confirmed
    writing scored below it. The prefix was a convention; nothing refused the
    rows. This predicate lives INSIDE the scorer so no caller, whatever file it
    loaded, can hand a refused row into a region or a reference.

    Keyed on the explicit refusing values only: `generated: true` (a templated or
    machine mode, NOT an authorship verdict -- the founder committed the seeds
    under his name) and `eligible_for_voice_reference: false` (the ground-truth
    file's stated verdict). Absent fields keep every pre-2026-08-18 row a full
    citizen; a default that refused would have emptied the corpus at cutover.
    """
    if row.get("generated") is True:
        return False
    if row.get("eligible_for_voice_reference") is False:
        return False
    return True


def normalize_whitespace(text):
    """One layout convention before any embed (sp-2a9bf797).

    The SAME draft measured 0.4625 raw and 0.4827 stripped on 2026-08-18:
    trailing newlines and doubled spaces moved a number that claims to describe
    authorship. Layout is not authorship. Collapse-and-strip is idempotent,
    changes no word and no word count, and runs ONCE at score()'s entry -- the
    single site -- so no caller is ever the one who forgot to strip.
    """
    return " ".join((text or "").split())


def word_count(text):
    return len((text or "").split())


def band_of(words):
    """The draft's band, from its own word count. Never from the reference set."""
    if words < SHORT_MAX_WORDS:
        return "short"
    if words > LONG_MIN_WORDS:
        return "long"
    return "mid"


def leave_one_out_median(vectors):
    """Median of each vector's cosine to the region of the OTHERS.

    Leave-one-out so a text is never compared against itself, which would put a
    1.0 in the reference and drag the median up by 1/n. None when the band is too
    thin for the median to mean anything.
    """
    if len(vectors) < MIN_REFERENCE_ROWS:
        return None
    scores = []
    for i, vec in enumerate(vectors):
        others = vectors[:i] + vectors[i + 1:]
        scores.append(region_cosine(vec, others))
    return statistics.median(scores)


# -------------------------------------------------------------- the record ----


def score(text, exemplars, backend=None):
    """The advisory authorship record for one draft. Raises ScorerUnavailable.

    `exemplars` is every ACTIVE row of the one corpus, carrying `text`. The
    region is cut from it by LENGTH BAND and by nothing else. Channel is not a
    region axis: with channel='x' the long band collapses to a single row,
    because the corpus holds one long-form X exemplar, and a region of one is not
    a region -- it scored 0.9999 against that row on 2026-08-17. The caller hands
    over the whole corpus and this function does the only cut there is.

    Raising rather than returning a null record is deliberate: the caller
    (`voicefp_gate`) owns the additive-null contract and catches at exactly one
    site. Two places building the same null record is how the key goes missing on
    one of them.
    """
    if backend is None:
        backend = TransformersBackend()
    # THE normalization site: the draft and every exemplar body land on one
    # whitespace convention before banding, identity, dedup, or embedding.
    text = normalize_whitespace(text)
    exemplars = [dict(r, text=normalize_whitespace(r.get("text")))
                 for r in exemplars]
    words = word_count(text)
    band = band_of(words)
    banded = [r for r in exemplars
              if usable_as_reference(r)
              and (r.get("text") or "").strip()
              and band_of(word_count(r.get("text"))) == band]
    # THE holdout site. The scored text never sits in the region it is measured
    # against -- leave-one-out was specified for the reference median only, so a
    # banked draft used to read 0.9999 against itself (sp-9194e0bc, measured on
    # the article published 2026-08-13, which is exemplar x-29 verbatim).
    # `same_text` is module-level rather than inlined so the negative self-test
    # can force it to match nothing and prove the numbers move.
    region_rows = [r for r in banded if not same_text(text, r["text"])]
    held_out = len(banded) - len(region_rows)
    if not region_rows:
        # An honest failure, which the caller turns into `authorship: null`. The
        # alternative -- scoring against the un-held-out region because it is all
        # there is -- is the exact 1.0 this holdout exists to stop.
        raise ScorerUnavailable(
            f"no active exemplars in band {band!r} to score against"
            + (f" after holding out {held_out} matching the draft"
               if held_out else ""))
    # ONE vector per DISTINCT text, and the list is the whole BAND rather than
    # the region, because the reference below needs the held-out rows too.
    # Deduplicating is not an optimization: when the draft IS a banked row the
    # two strings are equal, and embedding it twice would double the cost of the
    # only 319MB model load in this system for no second number.
    banded_texts = [r["text"] for r in banded]
    distinct = list(dict.fromkeys([text] + banded_texts))
    by_text = dict(zip(distinct, embed(distinct, backend)))
    draft_vec = by_text[text]
    region_vecs = [by_text[r["text"]] for r in region_rows]
    # The reference is a property of the BAND, so it is computed BEFORE the draft
    # holdout, never after it. Computed after, a draft the founder happened to
    # bank changed a number describing his corpus: a 3-row band fell to 2 and
    # `leave_one_out_median` returned None, so the record shipped
    # `authorship_reference: null` while an identical unbanked draft kept its
    # line. The quieter half is a 4-row band, where the median over the three
    # survivors was still a number and read 1.0. Leave-one-out already stops any
    # row being compared against itself inside this computation, which is why the
    # draft's own row is safe to leave in.
    reference = (leave_one_out_median([by_text[t] for t in banded_texts])
                 if band in BANDED else None)
    return {
        "authorship": region_cosine(draft_vec, region_vecs),
        "authorship_band": band,
        "authorship_reference": reference,
        # The shape rides WITH the number. A stored score whose tokenization is
        # implicit cannot be compared to a later one.
        "authorship_tokenization": TOKENIZATION,
        "authorship_model": getattr(backend, "model_id", MODEL_ID),
        "authorship_words": words,
        "authorship_region_n": len(region_vecs),
        # Rides WITH the number so a reader can tell "scored against 12 peers"
        # from "scored against 13 peers, one of which was this draft". A zero
        # here on a draft the founder knows he banked is the tell that the
        # identity rule missed an edit.
        "authorship_held_out": held_out,
        # The reference's OWN denominator, which is the band and not the region.
        # It used to be `len(region_vecs)` back when the median was computed from
        # the region; leaving it there after moving the median would have made
        # the field lie by exactly `held_out`. `region_n + held_out` is the
        # relation, and a reader who cannot tell the two counts apart cannot read
        # either number.
        "authorship_reference_n": (len(banded_texts)
                                   if reference is not None else 0),
    }
