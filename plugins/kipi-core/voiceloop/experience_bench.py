#!/usr/bin/env python3
"""Does `experience.match` find the RIGHT row? A read-only benchmark.

why this exists: the matcher is token overlap with two floors, `MIN_MATCH_SCORE = 2`
for hand rows and `MIN_MINED_MATCH_SCORE = 3` for mined ones. Those numbers were
chosen against 11 scars and 19 hand-written built rows. The corpus is now ~500 rows.
Nobody had measured whether the matcher still finds the right one, and two standing
decisions in `experience.py`'s docstring, no model in retrieval and "if the matching
is too crude the fix is better rows, not a smarter matcher", were being held on
argument rather than on a number.

This module produces the numbers. It changes nothing: no writes to the corpus, no
model call, no embedding, no import of anything that publishes.

## EVERY NUMBER ON THE PAGE IS COMPUTED HERE. None is prose.

The first version of this module carried three figures in its docstring and its
report ("3911 pairs across 135 exemplars", "roughly 29 per exemplar", "221 pairs")
that came from throwaway scripts written while designing it. Two reviewers
independently re-derived them: 24 readings of the first and none landed within 180
of 3911, and no reading produced 135 exemplars at all; the second contradicted this
module's own `module_name_pairs`, which returns 74. A benchmark whose report cites
figures its own code cannot reproduce is the defect it exists to catch, wearing a
lab coat. So the alternate pairings are COMPUTED now (`door_b_variants`), and
nothing on the page comes from memory.

## Ground truth is DERIVED, never labelled, and one of the two doors does not work

Waiting on the founder to label pairs would make the measurement his homework, so
both doors read a pairing somebody already recorded for another reason.

**Door A, scars: a human wrote the pairing down.** a scar row's Notes name the
writing sample a scar was used in ("Used in Mar 2026 LinkedIn post + Medium article
(Samples 17-18)"), and exemplar `source` strings carry `writing-samples.md sample N`.
That is a (post -> row) pair with no judgment and no token overlap in it.

Its PAIRING is non-circular. Its MISS ATTRIBUTION is not, and the report says so:
`paired_overlap` recomputes `experience._tokens`, the matcher's own scorer, so
"row problem" versus "ranking problem" restates the matcher's internal state rather
than checking it from outside.

**Door B, mined rows: measured, and it yields nothing usable.** Three pairings are
computed and printed side by side so the refusal is reproducible rather than
asserted: the module name where the basename could only be a module, the module
name where the basename may be an ordinary English word, and the two-distinct-title-
tokens rule. The last is CIRCULAR and that is the fatal half: a ground truth built
from token overlap cannot grade a token-overlap matcher.

## So the deciding numbers are the ones that need no pairs at all

And each one is printed WITH the artifact that could be producing it, because two
reviewers showed that all three move on something other than retrieval quality:

- **returned nothing**, split by WHY. A row scoring 2 that is mined is blocked by
  `MIN_MINED_MATCH_SCORE` alone; a row scoring 1 is under every floor; a score of 0
  means the corpus has nothing. Reporting only the total hides the one number that
  informs a floor change, and the total moves by tens of points on that constant.
- **false surfacing**, over TWO probe sets plus each set's mean token overlap with
  the corpus. The rate is a property of the probe list: the shipped list was chosen
  to "share no vocabulary with the corpus", which selects on the axis being
  measured, and a second off-domain list written without that rule scores several
  times higher. A rate that moves on probe choice is not a rate, and the page has to
  say so next to the number.
- **discrimination**, printed with the top-score histogram. Most ties are FORCED: an
  idea whose top score equals the mined floor cannot have a runner-up below it, so
  gap 0 is arithmetic, not an absence of signal.

## Degenerate cases, decided rather than left to crash

- the mined corpus file is gitignored by construction and absent in a fresh
  clone. Every mined-derived number then changes, by up to 19 points, and the first
  version printed those changed numbers with no marker beyond one corpus line while
  still printing door B's conclusion. `degraded()` now collects the reason, `render`
  prints a banner, and every affected section is labelled NOT MEASURED rather than
  given a conclusion.
- No scar Notes naming a sample: door A reports n=0 and no hit rate. A rate over an
  empty population is not a rate.
- Below three DISTINCT PIECES it is an OBSERVATION, not a claim, and is labelled as
  one. Distinct pieces, not ids: exemplars carry a `group`, and door A's two pairs
  are two excerpts of one piece with the same first sentence, so an id count would
  print one observation as two.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from . import experience

# The off-domain probes for the false-surfacing control. Two sets on purpose.
#
# SHARED_NOTHING was written to "share no vocabulary with the corpus", which selects
# on the axis being measured and lands it about one token under the floor by
# construction. ORDINARY was written the way he actually writes, keeping the
# ordinary abstract words (why, rule, change, one, real) that any English sentence
# carries. Both are 100% off-domain. Reporting only the first understates the rate
# several fold, which is what an adversarial pass measured.
SHARED_NOTHING_PROBES = (
    "sourdough starter hydration ratios in a cold kitchen",
    "why the offside rule ruins the flow of a football match",
    "repotting a monstera that has outgrown its ceramic pot",
    "tuning a bicycle derailleur after the cable stretches",
    "the best month to see puffins on the Farne Islands",
    "why medieval cathedrals used flying buttresses",
    "brewing temperature for a light roast Ethiopian coffee",
    "how tides work around a spring equinox",
    "choosing snow tyres for a rear wheel drive estate car",
    "the difference between a viola and a violin bow hold",
    "growing tomatoes in a greenhouse without blossom end rot",
    "why vinyl records need a stylus tracking force adjustment",
    "the rules of a cribbage crib and pegging",
    "how to proof a cold fermented pizza dough overnight",
    "sharpening a chisel on a waterstone to a mirror bevel",
    "the migration route of the arctic tern",
    "why cast iron pans need seasoning rather than soap",
    "setting the intonation on an electric guitar bridge",
    "how a sextant fixes a position at sea",
    "the difference between a stout and a porter",
)

ORDINARY_PROBES = (
    "I finally worked out why my sourdough never rises the way the book says",
    "Every knitter I know has one project they will never actually finish",
    "The real rule with beekeeping is that you check less than you want to",
    "Nobody tells you that the hardest part of fly fishing is the walking",
    "I changed one thing about how I prune the orchid and it flowered again",
    "Most people get the tomato watering completely backwards and nothing happens",
    "The way you hold the bow changes everything and no one explains it",
    "I spent a year thinking my coffee was the problem when it was the water",
    "There is a moment in every long walk where the map stops being useful",
    "What actually made the difference was doing less to the cast iron pan",
    "I kept buying better running shoes instead of running more often",
    "The one thing that made my bread work was measuring the flour by weight",
    "Everyone says you need expensive tools and then the cheap chisel wins",
    "I was told to repot every spring and it turns out that was wrong",
    "The number of people who overwater a monstera is genuinely remarkable",
    "It took me three seasons to see why the bees were leaving that hive",
    "My whole approach to the garden changed after one very dry summer",
    "There is no way to learn this except by ruining a few of them first",
    "The difference between a good loaf and a bad one is almost never the oven",
    "I check the tyre pressure now because one winter taught me to",
)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# `Samples 17-18`, `Sample 7`, `Samples 1, 2`. The scars file writes all three.
_SAMPLE_REF = re.compile(r"Samples?\s+(\d+)(?:\s*[-–]\s*(\d+))?(?:\s*,\s*(\d+))?")


def first_sentence(text):
    """What he would have TYPED, not the finished post.

    Handing the matcher the whole exemplar is the answer leaking into the question:
    a 300-word post shares dozens of tokens with any row it is about, and the score
    stops being about retrieval. The first sentence is the closest thing on disk to
    the one-line idea the lane actually receives.
    """
    body = " ".join((text or "").split())
    if not body:
        return ""
    return _SENTENCE_END.split(body)[0].strip()


def load_exemplars(path):
    """Exemplar rows. READ ONLY: the exemplar file has one writer,
    `pipeline.voice exemplars add`, and this module is not it.

    A line that parses but is not an OBJECT is skipped, not appended. The first
    version guarded `ValueError` per line and then appended whatever came back, so
    a line like `[1,2,3]` reached `row.get("id")` and killed the whole run with an
    AttributeError. A malformed corpus must degrade the benchmark, never crash it.
    """
    rows = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except ValueError:
                    continue
                if isinstance(parsed, dict) and parsed.get("id"):
                    rows.append(parsed)
    except OSError:
        return []
    return rows


def sample_numbers(body):
    """Every writing-sample number a scar row's Notes name."""
    found = set()
    for hit in _SAMPLE_REF.finditer(body or ""):
        start = int(hit.group(1))
        found.add(start)
        if hit.group(2):
            for number in range(start, int(hit.group(2)) + 1):
                found.add(number)
        if hit.group(3):
            found.add(int(hit.group(3)))
    return sorted(found)


def scar_pairs(scars_path, exemplars):
    """Door A. (exemplar, scar title) pairs a human recorded in the Notes column."""
    by_id = {row.get("id"): row for row in exemplars}
    try:
        with open(scars_path, encoding="utf-8") as handle:
            lines = handle.read().split("\n")
    except OSError:
        return []
    pairs = []
    for line in lines:
        hit = experience._ROW.match(line.strip())
        if not hit:
            continue
        title = hit.group("title").strip()
        # A row still carrying a template placeholder is not a scar yet, and
        # `experience.load` drops it. Without this the two disagree: the pair set
        # would name a title the matcher can never return, and every such pair
        # would count as a permanent miss. Found by mutation, not by reading: the
        # first version of the test passed only because its fixture placeholder
        # named a sample id that did not exist.
        if experience._PLACEHOLDER.search(title) or \
                experience._PLACEHOLDER.search(hit.group("body")):
            continue
        for number in sample_numbers(hit.group("body")):
            exemplar = by_id.get("sample-%02d" % number)
            if exemplar is not None:
                pairs.append({"exemplar_id": exemplar["id"],
                              "idea": first_sentence(exemplar.get("text")),
                              "full_text": exemplar.get("text") or "",
                              # THE PIECE, not the id. Two excerpts of one article
                              # are one observation; door A's own two pairs are
                              # exactly that, with a byte-identical first sentence.
                              "group": exemplar.get("group") or exemplar["id"],
                              "title": title, "kind": "scar"})
    return pairs


def distinct_pieces(pairs):
    """How many separate PIECES a pair set really represents."""
    return len({(p.get("group"), p.get("title")) for p in pairs})


def _basename(row):
    return os.path.splitext(os.path.basename(row.get("where") or ""))[0]


def module_name_pairs(rows, exemplars, snake_only=True, one_per_row=True):
    """Door B by module name. Every (row, exemplar) hit unless `one_per_row`.

    `snake_only` is the discriminator and the reason the door fails. A basename with
    an underscore could only be a module. A basename without one is frequently an
    English word (`control`, `ledger`, `digest`) that appears in his prose for
    reasons that have nothing to do with the file.

    `one_per_row` exists because the two halves of the comparison were counted with
    DIFFERENT rules in the first version: this door stopped at the first matching
    exemplar while the figure it was set against counted every combination, which
    understated the loose door about fourfold. Both counts are reported now.
    """
    pairs = []
    for row in rows:
        base = _basename(row)
        if not base or (snake_only and "_" not in base):
            continue
        variants = {base.lower(), base.replace("_", " ").lower(),
                    base.replace("_", "-").lower(), base.replace("_", "").lower()}
        for exemplar in exemplars:
            body = (exemplar.get("text") or "").lower()
            if any(variant in body for variant in variants):
                pairs.append({"exemplar_id": exemplar.get("id"),
                              "idea": first_sentence(exemplar.get("text")),
                              "full_text": exemplar.get("text") or "",
                              "group": exemplar.get("group") or exemplar.get("id"),
                              "title": row.get("title", ""), "kind": "mined"})
                if one_per_row:
                    break
    return pairs


def title_token_pairs(rows, exemplars, minimum=2):
    """Door B by shared title tokens. THE CIRCULAR ONE, computed so its yield is a
    number on the page rather than a claim in a docstring.

    It pairs a row with an exemplar when they share `minimum` distinct title tokens,
    which is the matcher's own scoring function with the ranking thrown away. It
    cannot grade the matcher and no hit rate is reported from it. It is here to make
    the size of the problem reproducible: a ground truth this loose pairs every
    exemplar with dozens of rows.
    """
    pairs = []
    exemplar_tokens = [(e, experience._tokens(e.get("text"))) for e in exemplars]
    for row in rows:
        wanted = experience._tokens(row.get("title"))
        if not wanted:
            continue
        for exemplar, tokens in exemplar_tokens:
            if len(wanted & tokens) >= minimum:
                pairs.append((row.get("title", ""), exemplar.get("id")))
    return pairs


def _rank(idea, match_fn, limit):
    return match_fn(idea, limit=limit) or []


def paired_overlap(pair, rows_by_key):
    """The paired row's ACTUAL overlap with the idea, its floor, and its clearance.

    why this is carried rather than inferred: "the matcher did not return it" has
    three different causes and reporting the wrong one sends the fix to the wrong
    place. Under the floor is a ROW problem. Over the floor and absent is a RANKING
    problem. NOT CLEARED is neither: `match` defaults to `publishable_only=True`, so
    an uncleared row can never be returned however well it scores, and the first
    version called that a ranking problem.

    NOT independent of the matcher, and the report says so: this recomputes
    `experience._tokens`, which is the matcher's own scorer.
    """
    row = rows_by_key.get(pair["title"])
    if row is None:
        return None, None, None
    wanted = experience._tokens(pair.get("idea"))
    overlap = wanted & experience._tokens("%s %s" % (row.get("title", ""),
                                                     row.get("story", "")))
    floor = (experience.MIN_MINED_MATCH_SCORE if row.get("origin") == "mined"
             else experience.MIN_MATCH_SCORE)
    return len(overlap), floor, bool(row.get("publishable"))


def score_pairs(pairs, match_fn, limit=3, rows_by_key=None, idea_key="idea"):
    """hit@1, hit@3, and the THREE different ways a paired row can be missing."""
    rows_by_key = rows_by_key or {}
    hit1 = hit3 = below = ranked_out = uncleared = unknown = 0
    misses = []
    for pair in pairs:
        idea = pair.get(idea_key) or ""
        ranked = _rank(idea, match_fn, limit)
        titles = [row.get("title", "") for row in ranked]
        if titles[:1] == [pair["title"]]:
            hit1 += 1
        if pair["title"] in titles:
            hit3 += 1
            continue
        score, floor, cleared = paired_overlap(dict(pair, idea=idea), rows_by_key)
        if score is None:
            unknown += 1
        elif cleared is False:
            uncleared += 1
        elif score >= floor:
            ranked_out += 1
        else:
            below += 1
        misses.append({"exemplar_id": pair["exemplar_id"], "wanted": pair["title"],
                       "paired_score": score, "floor": floor, "cleared": cleared,
                       "got": titles})
    return {"n": len(pairs), "n_distinct_pieces": distinct_pieces(pairs),
            "hit_at_1": hit1, "hit_at_3": hit3, "below_floor": below,
            "ranked_out": ranked_out, "uncleared": uncleared,
            "title_not_in_corpus": unknown, "misses": misses}


def corpus_overlap(probes, rows):
    """Mean and median count of probe tokens that appear anywhere in the corpus.

    This is the selection effect, measured. A probe list chosen to share no
    vocabulary with the corpus sits under the floor by construction, so its
    false-surfacing rate is a fact about the list, not about the matcher.
    """
    corpus = set()
    for row in rows:
        corpus |= experience._tokens("%s %s" % (row.get("title", ""),
                                                row.get("story", "")))
    counts = sorted(len(experience._tokens(p) & corpus) for p in probes)
    if not counts:
        return {"n": 0, "mean": None, "median": None}
    return {"n": len(counts),
            "mean": round(sum(counts) / len(counts), 2),
            "median": counts[len(counts) // 2]}


def false_surfacing(match_fn, probes, rows, limit=3):
    """How often an idea from outside his work returns a row anyway."""
    surfaced = []
    for probe in probes:
        ranked = _rank(probe, match_fn, limit)
        if ranked:
            surfaced.append({"probe": probe, "title": ranked[0].get("title", ""),
                             "score": ranked[0].get("score", 0),
                             "matched_on": list(ranked[0].get("matched_on") or [])})
    return {"n": len(probes), "surfaced": len(surfaced), "detail": surfaced,
            "probe_corpus_overlap": corpus_overlap(probes, rows)}


def why_nothing(ideas, rows):
    """THE NUMBER THAT INFORMS A FLOOR CHANGE, which the first version withheld.

    "returned nothing" has three causes and only one of them is about the corpus:

    - the best publishable row scores under EVERY floor. Nothing to retrieve.
    - the best publishable row is MINED and scores at or above the hand floor but
      under the mined floor. Blocked by one constant, not by the corpus.
    - the best publishable row scores zero. The corpus genuinely has nothing.

    An adversarial pass measured that moving `MIN_MINED_MATCH_SCORE` from 3 to 2
    moves the headline by tens of points, and the first version's closing advice was
    "read these before changing a floor" while withholding exactly this split.
    """
    pub = [row for row in rows if row.get("publishable")]
    scored = [(row, experience._tokens("%s %s" % (row.get("title", ""),
                                                  row.get("story", "")))) for row in pub]
    out = {"returned": 0, "under_every_floor": 0,
           "blocked_only_by_the_mined_floor": 0, "corpus_has_nothing": 0}
    for idea in ideas:
        wanted = experience._tokens(idea)
        best, best_mined = 0, False
        for row, tokens in scored:
            overlap = len(wanted & tokens)
            if overlap > best:
                best, best_mined = overlap, row.get("origin") == "mined"
            elif overlap == best and row.get("origin") == "mined":
                best_mined = True
        floor = (experience.MIN_MINED_MATCH_SCORE if best_mined
                 else experience.MIN_MATCH_SCORE)
        if best == 0:
            out["corpus_has_nothing"] += 1
        elif best >= floor:
            out["returned"] += 1
        elif best_mined and best >= experience.MIN_MATCH_SCORE:
            out["blocked_only_by_the_mined_floor"] += 1
        else:
            out["under_every_floor"] += 1
    out["n"] = len(ideas)
    return out


def discrimination(ideas, match_fn, limit=3):
    """Top score minus runner-up, WITH the top-score histogram beside it.

    The histogram is not decoration. Most ties are forced: an idea whose top score
    equals the mined floor cannot have a runner-up scoring below it, so gap 0 is
    arithmetic and not an absence of signal. Reporting the tie rate alone reads as
    "there is nothing to rank on", which is a stronger claim than the data supports.
    """
    gaps, tops = [], []
    empty = singles = 0
    for idea in ideas:
        ranked = _rank(idea, match_fn, limit)
        if not ranked:
            empty += 1
            continue
        tops.append(ranked[0].get("score", 0))
        if len(ranked) < 2:
            singles += 1
            continue
        gaps.append(ranked[0].get("score", 0) - ranked[1].get("score", 0))
    out = {"n": len(ideas), "returned_nothing": empty, "returned_one": singles,
           "gaps": gaps, "top_scores": {}}
    for score in tops:
        out["top_scores"][str(score)] = out["top_scores"].get(str(score), 0) + 1
    if gaps:
        ordered = sorted(gaps)
        out["gap_min"] = ordered[0]
        out["gap_median"] = ordered[len(ordered) // 2]
        out["gap_max"] = ordered[-1]
        out["gap_zero"] = sum(1 for gap in gaps if gap == 0)
    return out


# The exemplar file sits beside the three corpus files, in the same directory.
# Named here rather than resolved from `__file__` for the reason the matcher itself
# was moved: a path derived from where the CODE lives points every founder at
# whichever corpus happens to ship next to the package.
EXEMPLARS_FILE = "exemplars.jsonl"


def run(corpus_dir=None, scars_path=None, built_path=None, mined_path=None,
        exemplars_path=None, match_fn=None, limit=3, probe_sets=None):
    """Every number, in one dict. Reads only; writes nothing anywhere.

    `corpus_dir` binds all four inputs at once. Individual paths override it, which
    is what the fixture suite uses to build one file at a time in tmp_path. What is
    REFUSED is neither: an unbound benchmark used to resolve the live corpus off
    `experience.__file__`, and after the package extraction that file sits inside the
    plugin, so the same call would have measured an empty directory and reported the
    zeros as a result.
    """
    if not isinstance(limit, int) or limit < 1:
        # A limit of 0 makes `match` return an empty slice for every idea, and the
        # first version rendered that as "returned nothing: 161/161 (100%)" and
        # "false surfacing 0/20" as if both were measurements.
        raise ValueError("limit must be a positive int, got %r" % (limit,))
    if corpus_dir:
        _paths = experience.corpus_paths(corpus_dir)
        scars_path = scars_path or _paths["scars"]
        built_path = built_path or _paths["built"]
        mined_path = mined_path or _paths["mined"]
        exemplars_path = exemplars_path or os.path.join(corpus_dir, EXEMPLARS_FILE)
    unbound = [name for name, value in (("scars_path", scars_path),
                                        ("built_path", built_path),
                                        ("mined_path", mined_path),
                                        ("exemplars_path", exemplars_path))
               if not value]
    if unbound:
        raise experience.CorpusNotBound(
            "the benchmark has no corpus: pass corpus_dir, or every one of %s"
            % ", ".join(unbound))
    if match_fn is None:
        def match_fn(idea, limit=3):
            return experience.match(idea, corpus_dir or os.path.dirname(scars_path),
                                    limit=limit, scars_path=scars_path,
                                    built_path=built_path, mined_path=mined_path)
    probe_sets = probe_sets or (("shared-nothing", SHARED_NOTHING_PROBES),
                                ("ordinary-words", ORDINARY_PROBES))

    exemplars = load_exemplars(exemplars_path)
    mined_rows = experience.load_mined(mined_path)
    mined_present = os.path.exists(mined_path)
    hand_rows = list(experience.load(scars_path)) + list(
        experience.load_built(built_path))
    all_rows = hand_rows + mined_rows

    # KEYED ON TITLE because that is what `score_pairs` compares, and the collision
    # count is REPORTED rather than swallowed: last-writer-wins means a lookup can
    # read a different row's story and origin than the pair names.
    rows_by_key = {}
    collisions = 0
    for row in all_rows:
        if row.get("title") in rows_by_key:
            collisions += 1
        rows_by_key[row.get("title")] = row

    door_a = scar_pairs(scars_path, exemplars)
    ideas = [first_sentence(row.get("text")) for row in exemplars]
    ideas = [idea for idea in ideas if idea]

    degraded = []
    if not mined_present:
        degraded.append(
            "the mined corpus file is ABSENT. It is gitignored by construction, so "
            "a fresh clone has none of it. Door B, the returned-nothing split, the "
            "false-surfacing rate and the discrimination numbers below were all "
            "computed against the %d hand rows only. They are NOT MEASURED for this "
            "corpus and no conclusion may be drawn from them." % len(hand_rows))

    return {
        "corpus": {
            "scars": len([r for r in hand_rows if r.get("kind") == "scar"]),
            "built_hand": len([r for r in hand_rows if r.get("kind") == "built"]),
            "mined": len(mined_rows),
            "mined_present": mined_present,
            "exemplars": len(exemplars),
            "title_collisions": collisions,
            "distinct_titles": len(rows_by_key),
        },
        "degraded": degraded,
        "floors": {"hand": experience.MIN_MATCH_SCORE,
                   "mined": experience.MIN_MINED_MATCH_SCORE},
        "door_a": score_pairs(door_a, match_fn, limit, rows_by_key),
        # DIAGNOSTIC ONLY, and labelled as one everywhere it is printed. Feeding the
        # matcher the whole post leaks the answer into the question, so this is not a
        # hit rate anybody may quote. It exists to separate two causes the
        # first-sentence number alone cannot: if the row is findable from the full
        # post and not from the opening line, the defect is the IDEA, his posts open
        # with a hook whose vocabulary is unrelated to the material underneath.
        "door_a_full_text_diagnostic": score_pairs(
            door_a, match_fn, limit, rows_by_key, idea_key="full_text"),
        "door_b_variants": {
            "module_name_strict": len(module_name_pairs(mined_rows, exemplars,
                                                        snake_only=True)),
            "module_name_any_basename": len(module_name_pairs(mined_rows, exemplars,
                                                              snake_only=False)),
            "module_name_any_basename_all_hits": len(
                module_name_pairs(mined_rows, exemplars, snake_only=False,
                                  one_per_row=False)),
            "two_title_tokens": len(title_token_pairs(mined_rows, exemplars)),
            "two_title_tokens_exemplars": len(
                {eid for _, eid in title_token_pairs(mined_rows, exemplars)}),
        },
        "why_nothing": why_nothing(ideas, all_rows),
        "false_surfacing": {name: false_surfacing(match_fn, probes, all_rows, limit)
                            for name, probes in probe_sets},
        "discrimination": discrimination(ideas, match_fn, limit),
    }


def _rate(part, whole):
    if not whole:
        return "n/a (population is empty)"
    return "%d/%d (%.0f%%)" % (part, whole, 100.0 * part / whole)


def _not_measured(result):
    return " NOT MEASURED, see the banner above." if result.get("degraded") else ""


def render(result, at):
    """The report. Numbers and their populations, never a bare percentage."""
    corpus = result["corpus"]
    door_a = result["door_a"]
    variants = result["door_b_variants"]
    why = result["why_nothing"]
    disc = result["discrimination"]
    caveat = _not_measured(result)
    lines = ["# Retrieval benchmark: does experience.match find the right row?", "",
             "Generated %s by `python3 -m pipeline.experience_bench`. Read only." % at,
             ""]
    for reason in result.get("degraded") or []:
        lines += ["> **DEGRADED RUN.** " + reason, ""]
    lines += [
        "## Corpus under test", "",
        "- scars.md rows: %d" % corpus["scars"],
        "- built.md rows: %d" % corpus["built_hand"],
        "- mined rows: %s" % (str(corpus["mined"]) if corpus["mined_present"]
                              else "absent (gitignored; a fresh clone has none, and "
                                   "every mined number below is NOT MEASURABLE, not "
                                   "zero)"),
        "- exemplars: %d" % corpus["exemplars"],
        "- floors: hand %d, mined %d" % (result["floors"]["hand"],
                                         result["floors"]["mined"]),
        "- rows sharing a title with another row: %d (%d distinct titles). A lookup "
        "by title reads the last one written, so a pair naming a colliding title may "
        "be scored against a different row." % (corpus["title_collisions"],
                                                corpus["distinct_titles"]),
        "",
        "## Door A: pairs a human recorded (scars.md Notes name a writing sample)", "",
        "- pairs: n=%d, across %d DISTINCT PIECES" % (door_a["n"],
                                                      door_a["n_distinct_pieces"]),
    ]
    if door_a["n"]:
        lines += [
            "- hit@1: %s" % _rate(door_a["hit_at_1"], door_a["n"]),
            "- hit@3: %s" % _rate(door_a["hit_at_3"], door_a["n"]),
            "- misses by cause: %d under the paired row's floor (a row or floor "
            "problem), %d over it and still absent (ranking, or the "
            "one-source-per-output filter), %d not cleared for publication so the "
            "matcher could never return them, %d whose title is not in the corpus "
            "at all." % (door_a["below_floor"], door_a["ranked_out"],
                         door_a["uncleared"], door_a["title_not_in_corpus"]),
            "- this attribution is NOT independent of the matcher: it recomputes "
            "`experience._tokens`, the matcher's own scorer, so it restates the "
            "matcher's internal state rather than checking it from outside.",
        ]
    if door_a["n_distinct_pieces"] < 3:
        lines.append(
            "- **%d distinct pieces, so this is an OBSERVATION and not a claim** "
            "(agent-brief-constraints.md constraint 2). Distinct PIECES, not ids: "
            "two excerpts of one article share a first sentence, so an id count "
            "would print one observation as two."
            % door_a["n_distinct_pieces"])
    for miss in door_a["misses"]:
        lines.append(
            "  - miss: %s wanted `%s` (that row's overlap with the idea was %s, its "
            "floor is %s, cleared=%s), got %s"
            % (miss["exemplar_id"], miss["wanted"], miss["paired_score"],
               miss["floor"], miss["cleared"], miss["got"] or "nothing"))
    diag = result.get("door_a_full_text_diagnostic") or {}
    if diag.get("n"):
        lines += [
            "",
            "**Diagnostic, NOT a hit rate to quote.** The same pairs re-run with the "
            "WHOLE exemplar as the idea, which leaks the answer into the question: "
            "hit@1 %s, hit@3 %s. High here while the first-sentence number above is "
            "low would mean the defect is the IDEA rather than the corpus. On this "
            "corpus it rests on %d distinct piece(s), so it is a lead to test, not a "
            "finding." % (_rate(diag["hit_at_1"], diag["n"]),
                          _rate(diag["hit_at_3"], diag["n"]),
                          door_a["n_distinct_pieces"])]
    lines += [
        "",
        "## Door B: the mined-row pairings, all computed here, none quoted from prose",
        "",
        "- module name, snake_case basenames only (a token that could only be a "
        "module): %d pairs.%s" % (variants["module_name_strict"], caveat),
        "- module name, any basename including ordinary English words like `control` "
        "and `ledger`: %d rows matched, %d (row, exemplar) hits.%s"
        % (variants["module_name_any_basename"],
           variants["module_name_any_basename_all_hits"], caveat),
        "- two distinct title tokens: %d pairs across %d exemplars.%s"
        % (variants["two_title_tokens"], variants["two_title_tokens_exemplars"],
           caveat),
        "",
        "The two-title-token rule is CIRCULAR and that is the fatal half: a ground "
        "truth built from token overlap cannot grade a token-overlap matcher, so no "
        "mined hit rate is reported. The module-name doors are reported as counts "
        "only; whether they justify a conclusion depends on the mined corpus being "
        "present, and the banner above says whether it was.",
        "",
        "## Why an idea returns nothing, split by cause", "",
        "- probe ideas (first sentence of every exemplar): %d" % why["n"],
        "- returned something: %s" % _rate(why["returned"], why["n"]),
        "- best row is under EVERY floor: %s (nothing to retrieve)"
        % _rate(why["under_every_floor"], why["n"]),
        "- best row is MINED and scores at or above the hand floor but under the "
        "mined floor: %s. **This bucket is blocked by one constant, not by the "
        "corpus.**%s" % (_rate(why["blocked_only_by_the_mined_floor"], why["n"]),
                         caveat),
        "- corpus genuinely has nothing (best score 0): %s"
        % _rate(why["corpus_has_nothing"], why["n"]),
        "",
        "## False surfacing, over TWO probe sets, because the rate is a property of "
        "the list", "",
    ]
    for name, block in sorted(result["false_surfacing"].items()):
        overlap = block["probe_corpus_overlap"]
        lines.append(
            "- `%s`: %s returned at least one row. Mean probe tokens that appear "
            "anywhere in the corpus: %s (median %s), against floors of %d and %d.%s"
            % (name, _rate(block["surfaced"], block["n"]), overlap["mean"],
               overlap["median"], result["floors"]["hand"],
               result["floors"]["mined"], caveat))
        for row in block["detail"][:5]:
            lines.append("  - `%s` -> `%s` (score %s, on %s)"
                         % (row["probe"][:58], row["title"][:58], row["score"],
                            ", ".join(row["matched_on"])))
    lines += [
        "",
        "`shared-nothing` was written to share no vocabulary with the corpus, which "
        "selects on the axis being measured. `ordinary-words` is equally off-domain "
        "and keeps the ordinary abstract words any English sentence carries. Read "
        "the two together; neither alone is a rate.",
        "",
        "## Discrimination: is there a signal to rank on?", "",
        "- returned nothing: %s" % _rate(disc["returned_nothing"], disc["n"]),
        "- returned exactly one row: %s" % _rate(disc["returned_one"], disc["n"]),
    ]
    if disc.get("gaps"):
        lines += [
            "- top-minus-runner-up gap: min %s, median %s, max %s"
            % (disc["gap_min"], disc["gap_median"], disc["gap_max"]),
            "- gap of ZERO: %s" % _rate(disc["gap_zero"], len(disc["gaps"])),
            "- top-score histogram: %s" % ", ".join(
                "%s -> %d" % (k, v) for k, v in sorted(disc["top_scores"].items())),
            "- **most ties are FORCED, not an absence of signal.** An idea whose top "
            "score equals the mined floor (%d) cannot have a runner-up below it, so "
            "gap 0 is arithmetic. Read the histogram before reading the tie rate.%s"
            % (result["floors"]["mined"], caveat),
        ]
    lines += [
        "",
        "## What these numbers do and do not settle", "",
        "- They do NOT settle hit rate on mined rows. No non-circular pairing exists "
        "in the corpus today, and inventing one by hand would be the labelling this "
        "issue exists to avoid.",
        "- They do NOT settle whether a smarter matcher would help. Every number "
        "here is computed in the matcher's own units, at its own floors.",
        "- They DO settle where the returned-nothing population comes from, and that "
        "is the number to read before changing a floor: the mined-floor bucket is "
        "the one a single constant moves.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Measure whether experience.match finds the right row. "
                    "Read only: no corpus writes, no model call, no embedding.")
    parser.add_argument("--corpus-dir", dest="corpus_dir", required=True,
                        help="the directory holding scars.md, built.md, "
                             "built-mined.jsonl and exemplars.jsonl")
    parser.add_argument("--out", required=True,
                        help="where to write the markdown report")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--json", dest="json_out", default=None,
                        help="also write the raw numbers here")
    args = parser.parse_args(argv)

    import datetime
    at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = run(corpus_dir=args.corpus_dir, limit=args.limit)
    text = render(result, at)
    # BOTH destinations get their directory made BEFORE either file is written. The
    # first version made `--out`'s directory and not `--json`'s, so an unwritable
    # json path left the markdown on disk, no json, and no stdout: a partial
    # artifact that looks like a finished run.
    for dest in [d for d in (args.out, args.json_out) if d]:
        os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(text)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=1, sort_keys=True)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
