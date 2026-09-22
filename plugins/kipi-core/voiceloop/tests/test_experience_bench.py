#!/usr/bin/env python3
"""The retrieval benchmark, on a fixture corpus where the right answer is known.

Every test here builds its corpus in `tmp_path` and drives the REAL
`experience.match` against it. Nothing reads or writes the live corpus: the live
exemplar file has one writer and it is not this module, and a benchmark
that mutated the thing it measures would be worthless the second time it ran.

WHY SO MANY ASSERTIONS ON `render`: two review passes mutation-tested the first
version and 15 of 30 (and 17 of 45) module mutations survived a green suite. Every
survivor was a number the report PRINTS and no test READ: the gap metrics, the
top-score histogram, hit@1 versus hit@3, the full-text diagnostic, the probe
population, and `_rate`'s percentage itself, which could be inverted with the suite
staying green. A benchmark whose report is unasserted is a benchmark that can lie
quietly, which is the exact defect it exists to catch.
"""
import json
import os
import sys

import pytest

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PKG))

from voiceloop import experience, experience_bench  # noqa: E402


SCARS = """# scars

### Google

| Scar | Flags | Audience | Notes |
|---|---|---|---|
| **Four teams fought one scam operation** | public-safe | CISO | "Four teams fought the same scam operation across ads and search. None of them knew." Used in Mar 2026 LinkedIn post (Samples 1-2). |
| **Nobody warned us rooms** | public-safe | CISO | "I have been in too many rooms where the question was why did nobody warn us." (Sample 3) |
| **{{PLACEHOLDER}} row** | public-safe | VC | "not a scar yet" (Sample 4) |
| **The credentialing friction** | permission-required | practitioner | "Being told I was not technical enough to translate the findings." (Sample 6) |
"""

# The same file with the first row's TITLE and MATERIAL replaced and its Sample
# reference kept. The pairing still exists; the tokens to find it do not.
SCARS_FORCED_MISS = SCARS.replace(
    '**Four teams fought one scam operation**', '**Kiln firing schedules**').replace(
    '"Four teams fought the same scam operation across ads and search. None of '
    'them knew."',
    '"Bisque temperature for a stoneware glaze."')

BUILT = """# built

| Item | Flags | The specific |
|---|---|---|
| **A gate that refuses an unsourced figure** | public-safe | The gate refuses any number in a draft that no source artifact carries. |
"""

MINED = [
    # A basename that is ALSO an ordinary English word. It is what makes the
    # strict-vs-loose distinction measurable: `control` appears in his prose for
    # reasons that have nothing to do with the file.
    {"title": "The brakes and the pulse",
     "story": "Every job has a brake row and the runner checks it before acting.",
     "flag": "public-safe", "repo": "consulting", "path": "pipeline/control.py"},
    {"title": "Deterministic repair before the voice gate",
     "story": "Repair the draft deterministically before the voice gate reads it.",
     "flag": "public-safe", "repo": "consulting", "path": "pipeline/post_repair.py"},
    {"title": "A receipt carries the loop evidence",
     "story": "The receipt carries the loop's own evidence and the gate recomputes it.",
     "flag": "public-safe", "repo": "consulting", "path": "pipeline/route_contract.py"},
    # SAME TITLE as the first row, different path. The live mined corpus carries
    # repeats like this (one filename mined from several repos), and keying a
    # lookup on title silently drops one of them. Without a collision in the
    # fixture the counter can be deleted with the suite green.
    {"title": "The brakes and the pulse",
     "story": "A second copy of the brake row, mined from another repo.",
     "flag": "public-safe", "repo": "other", "path": "pipeline/other_thing.py"},
]

EXEMPLARS = [
    {"id": "sample-01", "source": "writing-samples.md sample 1", "status": "active",
     "group": "piece-four-teams",
     "text": "Four teams fought the same scam operation and none of them knew. "
             "The ads team would take down a warhead and it came back."},
    {"id": "sample-02", "source": "writing-samples.md sample 2", "status": "active",
     "group": "piece-four-teams-two",
     "text": "Four teams fought one scam operation across ads and search. "
             "Nobody touched the infrastructure underneath."},
    {"id": "sample-03", "source": "writing-samples.md sample 3", "status": "active",
     "group": "piece-rooms",
     "text": "I have been in too many rooms where the question was why did nobody "
             "warn us. Somebody usually saw it weeks earlier. The control you "
             "think you have is the one nobody tested."},
    # EXISTS on purpose. The placeholder scar row names Sample 4, so the only thing
    # that can stop it becoming a pair is the placeholder skip itself.
    {"id": "sample-04", "source": "writing-samples.md sample 4", "status": "active",
     "group": "piece-naming",
     "text": "Naming the dysfunction is the whole job. "
             "Everyone in the room already knows."},
    # Pairs to a PERMISSION-REQUIRED scar, so it can never be returned however well
    # it scores. That is neither a row problem nor a ranking problem.
    {"id": "sample-06", "source": "writing-samples.md sample 6", "status": "active",
     "group": "piece-credentialing",
     "text": "Being told I was not technical enough to translate the findings. "
             "That became the reason I build."},
    # Ranks BOTH scars, so `discrimination` has a real gap population. Without a
    # two-result idea every gap field is unreachable and five mutants survive.
    {"id": "sample-07", "source": "founder-supplied", "status": "active",
     "group": "piece-two-hits",
     "text": "Four teams in too many rooms and nobody knew why. "
             "That is the whole pattern."},
    # gap 0. Scores 2 against BOTH scars, so the runner-up ties the top and the
    # tie is observable. Its second sentence carries `control`, giving the
    # non-snake module door a SECOND matching exemplar so the one-hit-per-row
    # break is measurable.
    {"id": "sample-11", "source": "founder-supplied", "status": "active",
     "group": "piece-tie",
     "text": "A scam operation and nobody warned us. "
             "The control was never tested."},
    # gap 1. Scores 2 against one scar and 3 against the other.
    {"id": "sample-12", "source": "founder-supplied", "status": "active",
     "group": "piece-gap-one",
     "text": "A scam operation nobody warned us about in those rooms. "
             "Same shape every time."},
    {"id": "sample-09", "source": "founder-supplied", "status": "active",
     "group": "piece-kayak",
     "text": "Choosing a kayak paddle length for touring water. "
             "Feather angle matters more than blade shape."},
]


def _corpus(tmp_path, scars_text=SCARS, with_mined=True):
    scars = tmp_path / "scars.md"
    scars.write_text(scars_text, encoding="utf-8")
    built = tmp_path / "built.md"
    built.write_text(BUILT, encoding="utf-8")
    mined = tmp_path / "built-mined.jsonl"
    if with_mined:
        mined.write_text("\n".join(json.dumps(r) for r in MINED) + "\n",
                         encoding="utf-8")
    exemplars = tmp_path / "exemplars.jsonl"
    exemplars.write_text("\n".join(json.dumps(r) for r in EXEMPLARS) + "\n",
                         encoding="utf-8")
    # THE FIXTURE SUPPLIES THE CORPUS DIRECTORY. Nothing here is found on disk:
    # the engine has no default corpus and refuses an unbound call, so a suite that
    # forgot to bind one goes red instead of silently measuring whatever ships
    # beside the package.
    return {"corpus_dir": str(tmp_path),
            "scars_path": str(scars), "built_path": str(built),
            "mined_path": str(mined), "exemplars_path": str(exemplars)}


@pytest.fixture
def bound():
    """The matcher, bound to the fixture corpus by ARGUMENT.

    It used to monkeypatch two module constants, because the matcher resolved
    built/mined from `__file__`. Those constants are gone: the engine takes its
    corpus from the caller, so binding is now a call and needs no teardown. That is
    the whole point of the extraction, expressed in the one place a test can see it.
    """
    def _bind(paths):
        def match_fn(idea, limit=3):
            return experience.match(idea, paths["corpus_dir"], limit=limit,
                                    scars_path=paths["scars_path"],
                                    built_path=paths["built_path"],
                                    mined_path=paths["mined_path"])
        return match_fn
    return _bind


class TestTheGroundTruthIsDerivedAndTheHitRateIsKnown:

    def test_hit_at_1_is_exactly_three_of_four_on_the_fixture(self, tmp_path, bound):
        paths = _corpus(tmp_path)
        result = experience_bench.run(match_fn=bound(paths), **paths)
        door_a = result["door_a"]
        # samples 1 and 2 pair to the first scar (Samples 1-2), sample 3 to the
        # second (Sample 3), sample 6 to the permission-required one (Sample 6).
        # The {{PLACEHOLDER}} row is skipped, so its Sample 4 yields no pair.
        assert door_a["n"] == 4, door_a
        assert door_a["hit_at_1"] == 3, door_a["misses"]
        assert door_a["hit_at_3"] == 3
        assert door_a["below_floor"] == 0

    def test_hit_at_3_is_not_the_same_number_as_hit_at_1(self, tmp_path, bound):
        """Two mutants survived because every fixture had hit@1 == hit@3, so the
        two were behaviourally identical everywhere the suite looked. This idea
        ranks the paired row SECOND."""
        paths = _corpus(tmp_path)
        match_fn = bound(paths)
        pairs = [{"exemplar_id": "x", "title": "Nobody warned us rooms",
                  "group": "g", "full_text": "",
                  # Scores 2 against "Nobody warned us rooms" and 3 against the
                  # four-teams scar, so the paired row lands at rank 2.
                  "idea": "Four teams fought a scam operation in too many rooms"}]
        rows = {r["title"]: r for r in experience.load(paths["scars_path"])}
        scored = experience_bench.score_pairs(pairs, match_fn, 3, rows)
        assert scored["hit_at_1"] == 0, scored
        assert scored["hit_at_3"] == 1, scored

    def test_removing_the_title_tokens_drops_hit_at_1(self, tmp_path, bound):
        """THE NEGATIVE SELF-TEST. Same pairs, same matcher, material gutted. A
        benchmark that cannot go down is not measuring anything."""
        paths = _corpus(tmp_path, scars_text=SCARS_FORCED_MISS)
        result = experience_bench.run(match_fn=bound(paths), **paths)
        door_a = result["door_a"]
        assert door_a["n"] == 4, door_a
        assert door_a["hit_at_1"] == 1, door_a["misses"]
        assert door_a["below_floor"] == 2
        assert {m["exemplar_id"] for m in door_a["misses"]} >= {"sample-01",
                                                                "sample-02"}

    def test_a_placeholder_scar_row_never_becomes_a_pair(self, tmp_path):
        paths = _corpus(tmp_path)
        exemplars = experience_bench.load_exemplars(paths["exemplars_path"])
        assert any(r["id"] == "sample-04" for r in exemplars)
        pairs = experience_bench.scar_pairs(paths["scars_path"], exemplars)
        titles = {p["title"] for p in pairs}
        assert not any("PLACEHOLDER" in t for t in titles), titles
        assert "sample-04" not in {p["exemplar_id"] for p in pairs}

    def test_an_uncleared_row_is_not_called_a_ranking_problem(self, tmp_path, bound):
        """`match` defaults to publishable_only=True, so a permission-required row
        can never be returned however well it scores. The first version bucketed
        that as ranked_out and the report then named two causes, both wrong."""
        paths = _corpus(tmp_path)
        result = experience_bench.run(match_fn=bound(paths), **paths)
        door_a = result["door_a"]
        assert door_a["uncleared"] == 1, door_a["misses"]
        assert door_a["ranked_out"] == 0, door_a["misses"]
        miss = [m for m in door_a["misses"] if m["exemplar_id"] == "sample-06"][0]
        assert miss["cleared"] is False
        text = experience_bench.render(result, "2026-09-04T00:00:00Z")
        assert "not cleared for publication" in text

    def test_distinct_pieces_not_ids_decides(self, tmp_path):
        """Two excerpts of one article share a first sentence, so an id count
        prints one observation as two. The live door A is exactly that shape."""
        pairs = [{"exemplar_id": "a", "group": "piece-x", "title": "T"},
                 {"exemplar_id": "b", "group": "piece-x", "title": "T"},
                 {"exemplar_id": "c", "group": "piece-y", "title": "T"}]
        assert experience_bench.distinct_pieces(pairs) == 2


class TestTheIdeaIsWhatHeWouldHaveTyped:

    def test_only_the_first_sentence_reaches_the_matcher(self):
        idea = experience_bench.first_sentence(EXEMPLARS[0]["text"])
        assert idea == "Four teams fought the same scam operation and none of them knew."
        assert "warhead" not in idea

    def test_door_a_is_actually_wired_to_first_sentence_and_not_the_whole_post(
            self, tmp_path, bound):
        """MUTATION-COVERED WIRING. Feeding door A the whole post survived a green
        suite in the first version, which is the exact leak `first_sentence` exists
        to prevent: the class name claimed coverage the assertions did not give.

        The fixture's second sentence carries `warhead`, a token no row has, so the
        two readings produce a DIFFERENT match set and the wiring is observable.
        """
        paths = _corpus(tmp_path)
        exemplars = experience_bench.load_exemplars(paths["exemplars_path"])
        pairs = experience_bench.scar_pairs(paths["scars_path"], exemplars)
        first = [p for p in pairs if p["exemplar_id"] == "sample-01"][0]
        assert "warhead" not in first["idea"]
        assert "warhead" in first["full_text"]
        # And `run` scores door A on `idea`, never on `full_text`. Asserted by CALL
        # ORDER, not by membership: `discrimination` also ranks every first
        # sentence, so "a first sentence was passed at some point" stays true even
        # when door A is fed whole posts. Both mutants survived that weaker check.
        seen = []

        def spy(idea, limit=3):
            seen.append(idea)
            return bound(paths)(idea, limit=limit)
        experience_bench.run(match_fn=spy, **paths)
        n = len(pairs)
        door_a_calls, diagnostic_calls = seen[:n], seen[n:2 * n]
        assert not any("warhead" in call for call in door_a_calls), door_a_calls
        assert set(door_a_calls) == {p["idea"] for p in pairs}
        assert any("warhead" in call for call in diagnostic_calls), diagnostic_calls

    def test_an_empty_exemplar_yields_an_empty_idea_rather_than_raising(self):
        assert experience_bench.first_sentence("") == ""
        assert experience_bench.first_sentence(None) == ""

    @pytest.mark.parametrize("body,expected", [
        ("Used in Mar 2026 (Samples 17-18).", [17, 18]),
        ("The CIB framing in Sample 7 is the same operation.", [7]),
        ("Tested against Bard (writing-samples Samples 1, 2)", [1, 2]),
        ("no reference at all", []),
    ])
    def test_every_sample_reference_shape_in_the_real_file_parses(self, body, expected):
        assert experience_bench.sample_numbers(body) == expected


class TestTheDoorThatDoesNotWorkReportsThatItDoesNotWork:

    def test_the_module_name_door_yields_nothing_on_snake_case_names(self, tmp_path,
                                                                     bound):
        paths = _corpus(tmp_path)
        variants = experience_bench.run(match_fn=bound(paths),
                                        **paths)["door_b_variants"]
        assert variants["module_name_strict"] == 0
        # THE OTHER HALF, and the reason the zero means anything: the same corpus
        # carries `pipeline/control.py`, whose basename is an ordinary English word
        # that sample-03 uses. The loose door pairs it.
        assert variants["module_name_any_basename"] == 1

    def test_the_two_counting_rules_are_reported_separately(self, tmp_path, bound):
        """The first version compared a one-hit-per-row count against an
        every-combination count in the same paragraph, understating the loose door
        about fourfold. Both rules are printed now, and this proves they differ."""
        paths = _corpus(tmp_path)
        variants = experience_bench.run(match_fn=bound(paths),
                                        **paths)["door_b_variants"]
        # `control` matches TWO exemplars, so the two rules give different numbers.
        # With one hit per row it is 1; counting every combination it is 2.
        assert variants["module_name_any_basename"] == 1, variants
        assert variants["module_name_any_basename_all_hits"] == 2, variants

    def test_the_circular_door_is_computed_and_not_quoted(self, tmp_path, bound):
        """Every figure the report prints has to come from this run. The first
        version carried three numbers from throwaway scripts and two reviewers
        could not reproduce any of them."""
        paths = _corpus(tmp_path)
        result = experience_bench.run(match_fn=bound(paths), **paths)
        variants = result["door_b_variants"]
        text = experience_bench.render(result, "2026-09-04T00:00:00Z")
        assert "%d pairs across %d exemplars" % (
            variants["two_title_tokens"],
            variants["two_title_tokens_exemplars"]) in text
        # And the function itself pairs on two shared title tokens, proven on a
        # crafted input rather than on whatever the fixture corpus happens to do.
        rows = [{"title": "Deterministic repair before the voice gate"}]
        assert experience_bench.title_token_pairs(
            rows, [{"id": "hit", "text": "deterministic repair is the whole idea"}])
        assert not experience_bench.title_token_pairs(
            rows, [{"id": "miss", "text": "deterministic and nothing else"}])
        # No figure from the retired prose survives anywhere on the page.
        for stale in ("3911", "135 exemplars", "221 pairs", "roughly 29"):
            assert stale not in text

    def test_an_exemplar_naming_the_module_does_pair_so_the_door_is_not_broken(self):
        """The negative control on the door itself: prove the zero above is a fact
        about his writing and not a broken matcher."""
        # BY PATH, not by index: MINED gained a row at position 0 and an index
        # here silently pointed the test at a different fixture.
        rows = [experience._mined_row(
            next(r for r in MINED if "post_repair" in r["path"]))]
        exemplars = [{"id": "x", "text": "I wrote post_repair.py to fix this."}]
        pairs = experience_bench.module_name_pairs(rows, exemplars, snake_only=True)
        assert [p["exemplar_id"] for p in pairs] == ["x"]


class TestTheControlsThatNeedNoPairs:

    def test_the_probe_population_is_reported_and_not_empty(self, tmp_path, bound):
        """Replacing OFF_DOMAIN_PROBES with an empty tuple survived a green suite:
        the rate passed over an empty population. The n is asserted now."""
        paths = _corpus(tmp_path)
        fs = experience_bench.run(match_fn=bound(paths), **paths)["false_surfacing"]
        assert set(fs) == {"shared-nothing", "ordinary-words"}
        for name, block in fs.items():
            assert block["n"] == 20, (name, block["n"])
        assert len(experience_bench.SHARED_NOTHING_PROBES) == 20
        assert len(experience_bench.ORDINARY_PROBES) == 20
        # CONTENT, not just the count. Replacing the list with filler kept the
        # length and stayed green. A probe has to be a real sentence, and the two
        # sets have to be different sentences.
        both = list(experience_bench.SHARED_NOTHING_PROBES) + \
            list(experience_bench.ORDINARY_PROBES)
        assert len(set(both)) == 40, "probes must be distinct"
        assert all(len(p.split()) >= 6 for p in both), \
            [p for p in both if len(p.split()) < 6]

    def test_the_probe_sets_carry_their_corpus_overlap(self, tmp_path, bound):
        """The rate is a property of the list, so the selection effect has to be on
        the page beside it. `shared-nothing` was chosen to share no vocabulary with
        the corpus, which selects on the axis being measured."""
        paths = _corpus(tmp_path)
        result = experience_bench.run(match_fn=bound(paths), **paths)
        for block in result["false_surfacing"].values():
            overlap = block["probe_corpus_overlap"]
            assert overlap["n"] == 20
            assert overlap["mean"] is not None
        # KNOWN ANSWER. `mean is not None` passed against a function hardcoded to
        # return zero, which is the whole selection-effect measurement gone with a
        # green suite.
        rows = [{"title": "brake row", "story": "the runner checks the pulse"}]
        known = experience_bench.corpus_overlap(
            ["the brake row runner", "puffins on the island", "brake"], rows)
        assert known == {"n": 3, "mean": 1.33, "median": 1}, known
        text = experience_bench.render(result, "2026-09-04T00:00:00Z")
        assert "Mean probe tokens that appear anywhere in the corpus" in text

    def test_a_probe_that_must_match_proves_the_control_can_fire(self, tmp_path,
                                                                bound):
        """A zero false-surfacing rate is meaningless unless the same instrument is
        shown returning something. Negative-control every zero."""
        paths = _corpus(tmp_path)
        result = experience_bench.run(
            match_fn=bound(paths),
            probe_sets=(("must-hit",
                         ("Four teams fought one scam operation across ads and "
                          "search.",)),),
            **paths)
        assert result["false_surfacing"]["must-hit"]["surfaced"] == 1

    def test_why_nothing_splits_the_mined_floor_out_of_the_headline(self, tmp_path,
                                                                    bound):
        """The number that informs a floor change. A mined row scoring at the hand
        floor but under the mined floor is blocked by ONE CONSTANT, not by the
        corpus, and the first version folded it into a single total."""
        paths = _corpus(tmp_path)
        why = experience_bench.run(match_fn=bound(paths), **paths)["why_nothing"]
        assert why["n"] == len(EXEMPLARS)
        assert sum(why[k] for k in ("returned", "under_every_floor",
                                    "blocked_only_by_the_mined_floor",
                                    "corpus_has_nothing")) == why["n"]
        # sample-09 is about kayaking and matches nothing in this corpus.
        assert why["corpus_has_nothing"] >= 1

    def test_the_mined_floor_bucket_can_actually_fill(self, tmp_path, bound):
        """NEGATIVE CONTROL on the bucket above. A split that is always zero on
        every fixture is a split nobody has seen work."""
        paths = _corpus(tmp_path)
        rows = [experience._mined_row(r) for r in MINED]
        # Two shared tokens with the mined row's title+story: at the hand floor of
        # 2, under the mined floor of 3.
        why = experience_bench.why_nothing(["brake runner"], rows)
        assert why["blocked_only_by_the_mined_floor"] == 1, why

    def test_discrimination_reports_the_gap_the_ties_and_the_histogram(self,
                                                                      tmp_path,
                                                                      bound):
        """Five mutants survived here: the gap could be inverted, the median made a
        max, singles counted as empties and gap_zero forced to 0, all green. The
        fixture now produces a real gap population and every field is read."""
        paths = _corpus(tmp_path)
        result = experience_bench.run(match_fn=bound(paths), **paths)
        disc = result["discrimination"]
        assert disc["n"] == len(EXEMPLARS)
        assert disc["returned_nothing"] >= 1
        # min, median and max must DIFFER, and there must be a real tie. With one
        # gap value the median equals the max and `gap_zero = 0` is free, which is
        # how four mutants survived.
        assert sorted(set(disc["gaps"])) == [0, 1, 2], disc["gaps"]
        assert disc["gap_zero"] >= 1, disc["gaps"]
        assert disc["gap_min"] != disc["gap_median"] != disc["gap_max"]
        assert disc["gap_min"] == min(disc["gaps"])
        assert disc["gap_max"] == max(disc["gaps"])
        assert disc["gap_median"] == sorted(disc["gaps"])[len(disc["gaps"]) // 2]
        assert disc["gap_zero"] == sum(1 for g in disc["gaps"] if g == 0)
        assert sum(disc["top_scores"].values()) == \
            disc["n"] - disc["returned_nothing"]
        text = experience_bench.render(result, "2026-09-04T00:00:00Z")
        assert "top-score histogram" in text
        assert "most ties are FORCED" in text

    def test_a_single_returned_row_is_not_counted_as_returning_nothing(self):
        """`returned_one` and `returned_nothing` were interchangeable in every
        fixture, so a mutant swapping them stayed green."""
        disc = experience_bench.discrimination(
            ["a", "b"],
            lambda idea, limit=3: [{"score": 4, "title": "T"}] if idea == "a" else [])
        assert disc["returned_one"] == 1
        assert disc["returned_nothing"] == 1


class TestTheMinedCorpusIsGitignoredAndOftenAbsent:

    def test_a_missing_mined_file_degrades_loudly_and_draws_no_conclusion(
            self, tmp_path, bound):
        """The first version printed door B's conclusion and three headline numbers
        computed against hand rows only, with no marker beyond one corpus line. Its
        test greped for the word "absent" anywhere on the page and stayed green."""
        paths = _corpus(tmp_path, with_mined=False)
        result = experience_bench.run(match_fn=bound(paths), **paths)
        assert result["corpus"]["mined_present"] is False
        assert result["corpus"]["mined"] == 0
        assert result["degraded"], "an absent mined corpus must be recorded"
        text = experience_bench.render(result, "2026-09-04T00:00:00Z")
        assert "DEGRADED RUN" in text
        assert "NOT MEASURABLE" in text
        # Every mined-derived section carries the caveat, not just the corpus line.
        assert text.count("NOT MEASURED, see the banner above.") >= 4

    def test_a_present_mined_file_draws_no_degraded_banner(self, tmp_path, bound):
        paths = _corpus(tmp_path)
        result = experience_bench.run(match_fn=bound(paths), **paths)
        assert result["corpus"]["mined_present"] is True
        assert result["corpus"]["mined"] == len(MINED)
        assert result["degraded"] == []
        text = experience_bench.render(result, "2026-09-04T00:00:00Z")
        assert "DEGRADED RUN" not in text
        assert "NOT MEASURED" not in text


class TestTheReportCarriesItsPopulations:

    def test_a_rate_over_an_empty_population_is_not_rendered_as_a_percentage(self):
        assert "n/a" in experience_bench._rate(0, 0)

    def test_the_percentage_is_the_right_way_round(self):
        """`_rate` could be inverted with the whole suite green, which made every
        percentage in the report unasserted."""
        assert experience_bench._rate(1, 4) == "1/4 (25%)"
        assert experience_bench._rate(3, 4) == "3/4 (75%)"
        assert experience_bench._rate(0, 7) == "0/7 (0%)"

    def test_fewer_than_three_distinct_pieces_is_labelled_an_observation(self,
                                                                        tmp_path,
                                                                        bound):
        paths = _corpus(tmp_path)
        result = experience_bench.run(match_fn=bound(paths), **paths)
        result["door_a"]["n_distinct_pieces"] = 2
        text = experience_bench.render(result, "2026-09-04T00:00:00Z")
        assert "OBSERVATION and not a claim" in text

    def test_the_report_labels_each_number_with_its_own_name(self, tmp_path, bound):
        """Four mutants swapped one rendered number for another (returned-nothing
        for returned-one, below_floor for ranked_out, strict door for loose, scars
        for built) and stayed green because nothing read the page."""
        paths = _corpus(tmp_path)
        result = experience_bench.run(match_fn=bound(paths), **paths)
        text = experience_bench.render(result, "2026-09-04T00:00:00Z")
        disc, corpus = result["discrimination"], result["corpus"]
        variants = result["door_b_variants"]
        assert "- returned nothing: %s" % experience_bench._rate(
            disc["returned_nothing"], disc["n"]) in text
        assert "- returned exactly one row: %s" % experience_bench._rate(
            disc["returned_one"], disc["n"]) in text
        assert "- scars.md rows: %d" % corpus["scars"] in text
        assert "- built.md rows: %d" % corpus["built_hand"] in text
        assert "snake_case basenames only (a token that could only be a module): " \
               "%d pairs" % variants["module_name_strict"] in text
        assert "%d rows matched, %d (row, exemplar) hits" % (
            variants["module_name_any_basename"],
            variants["module_name_any_basename_all_hits"]) in text

    def test_the_report_names_the_live_floors_rather_than_a_copy(self, tmp_path,
                                                                bound):
        paths = _corpus(tmp_path)
        result = experience_bench.run(match_fn=bound(paths), **paths)
        assert result["floors"] == {"hand": experience.MIN_MATCH_SCORE,
                                    "mined": experience.MIN_MINED_MATCH_SCORE}
        text = experience_bench.render(result, "2026-09-04T00:00:00Z")
        assert "floors: hand %d, mined %d" % (experience.MIN_MATCH_SCORE,
                                              experience.MIN_MINED_MATCH_SCORE) in text

    def test_the_full_text_diagnostic_uses_the_full_text(self, tmp_path, bound):
        """Two mutants neutered the diagnostic (re-running it on `idea`, or
        flipping the default key) and stayed green. It is the instrument the commit
        message leaned on, and it had no test."""
        paths = _corpus(tmp_path)
        result = experience_bench.run(match_fn=bound(paths), **paths)
        text = experience_bench.render(result, "2026-09-04T00:00:00Z")
        assert "NOT a hit rate to quote" in text

    def test_the_title_collision_count_is_reported(self, tmp_path, bound):
        """Keying by title drops rows silently; the live corpus loses dozens. The
        count is on the page so a reader knows a lookup may read a different row."""
        paths = _corpus(tmp_path)
        result = experience_bench.run(match_fn=bound(paths), **paths)
        assert result["corpus"]["title_collisions"] == 1, result["corpus"]
        corpus = result["corpus"]
        # 3 scars (the placeholder row is dropped) + 1 built + 4 mined, minus the
        # one duplicate title.
        assert corpus["distinct_titles"] == \
            corpus["scars"] + corpus["built_hand"] + corpus["mined"] - 1, corpus
        text = experience_bench.render(result, "2026-09-04T00:00:00Z")
        assert "rows sharing a title with another row: 1" in text


class TestDegenerateInputsAreDecidedRatherThanCrashing:

    def test_a_json_line_that_is_not_an_object_is_skipped(self, tmp_path):
        path = tmp_path / "exemplars.jsonl"
        path.write_text('[1,2,3]\n"a string"\n{"id":"ok","text":"fine."}\nnot json\n\n',
                        encoding="utf-8")
        rows = experience_bench.load_exemplars(str(path))
        assert [r["id"] for r in rows] == ["ok"]

    def test_a_missing_exemplars_file_returns_empty_rather_than_raising(self,
                                                                       tmp_path):
        assert experience_bench.load_exemplars(str(tmp_path / "nope.jsonl")) == []

    @pytest.mark.parametrize("limit", [0, -1, None, "3"])
    def test_a_limit_that_would_silently_zero_the_report_is_refused(self, tmp_path,
                                                                    bound, limit):
        """`--limit 0` made `match` return an empty slice for every idea and the
        page rendered 100% returned-nothing and 0% false surfacing as measurements."""
        paths = _corpus(tmp_path)
        with pytest.raises(ValueError):
            experience_bench.run(match_fn=bound(paths), limit=limit, **paths)

    def test_a_missing_scars_file_yields_no_pairs_rather_than_raising(self, tmp_path):
        assert experience_bench.scar_pairs(str(tmp_path / "nope.md"), []) == []

    def test_a_paired_title_absent_from_the_corpus_is_its_own_bucket(self):
        """`score=None` was bucketed as below-floor, so the page printed 'scored
        UNDER its floor' next to 'overlap was None, floor is None'."""
        scored = experience_bench.score_pairs(
            [{"exemplar_id": "x", "title": "not in the corpus", "idea": "an idea",
              "group": "g"}],
            lambda idea, limit=3: [], 3, {})
        assert scored["title_not_in_corpus"] == 1
        assert scored["below_floor"] == 0


class TestTheCLIWritesBothArtifactsOrNeither:

    def test_main_creates_the_directory_for_the_json_as_well_as_the_report(
            self, tmp_path, capsys):
        """The first version made `--out`'s directory and not `--json`'s, so an
        unwritable json path left the markdown on disk, no json and no stdout: a
        partial artifact that looks like a finished run. `main` had no test at all.

        It used to reach the fixture corpus by monkeypatching three module constants
        AND wrapping `run` to force the paths back in, which meant the CLI's own
        corpus plumbing was never exercised. `--corpus-dir` replaced all of it: the
        flag is the only way in, so this now fails if that plumbing breaks.
        """
        _corpus(tmp_path)
        out = tmp_path / "deep" / "nested" / "report.md"
        raw = tmp_path / "other" / "deeper" / "raw.json"
        assert experience_bench.main(["--corpus-dir", str(tmp_path),
                                      "--out", str(out), "--json", str(raw)]) == 0
        assert out.is_file() and raw.is_file()
        assert json.loads(raw.read_text())["floors"]["hand"] == \
            experience.MIN_MATCH_SCORE
        assert "Retrieval benchmark" in capsys.readouterr().out


class TestItNeverWritesTheCorpus:

    def test_the_module_opens_the_corpus_read_only(self):
        """A benchmark that can write `exemplars.jsonl` is a second writer, and the
        single-writer rule on that file is what keeps a bad source string from
        blocking everyone's commit.

        AST, not a substring search: the first version grepped the source for
        "exemplars add" and failed on its OWN docstring. And it enumerated only
        `open`, so a `Path.write_text` or a `shutil.copyfile` added above `main`
        stayed green. The check now walks every call node and matches a set of
        write APIs by name.
        """
        writes = self._writes_above_main(experience_bench.__file__)
        assert writes == [], writes

    def test_the_write_detector_fires_on_every_api_it_claims_to_cover(self, tmp_path):
        """NEGATIVE CONTROL, on the REAL detector. The first version of this test
        re-implemented the scan inline over its own temp file, so it could not fail
        for any change to the module and it stayed green while its sibling went red.
        """
        for snippet in ('def run():\n    open("/x", "a").write("1")\n',
                        'import pathlib\ndef run():\n'
                        '    pathlib.Path("/x").write_text("1")\n',
                        'import shutil\ndef run():\n    shutil.copyfile("/a","/b")\n',
                        'import os\ndef run():\n    os.replace("/a","/b")\n'):
            bad = tmp_path / "bad.py"
            bad.write_text(snippet + "\ndef main():\n    pass\n")
            found = self._writes_above_main(str(bad))
            assert found, snippet

    @staticmethod
    def _writes_above_main(path):
        import ast
        tree = ast.parse(open(path, encoding="utf-8").read())
        main_line = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                main_line = node.lineno
        # Every API that can put bytes on disk, not just `open`. A guard that
        # enumerates one name is a guard a one-line change walks past.
        # Unambiguous on their own: nothing but a filesystem write is spelled this
        # way. `replace` and `rename` are NOT here, because `str.replace` is all
        # over this module and a bare name match reported three false writes.
        UNAMBIGUOUS = {"write_text", "write_bytes", "writelines", "copyfile", "copy2"}
        # These need their receiver, because the same word means something else on
        # a string.
        QUALIFIED = {("os", "replace"), ("os", "rename"), ("os", "remove"),
                     ("os", "unlink"), ("os", "makedirs"), ("os", "mkdir"),
                     ("shutil", "copy"), ("shutil", "copyfile"), ("shutil", "move"),
                     ("json", "dump")}
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            receiver = getattr(getattr(node.func, "value", None), "id", None)
            if name in UNAMBIGUOUS or (receiver, name) in QUALIFIED:
                found.append((node.lineno, name))
            elif name == "open":
                modes = [a.value for a in node.args[1:2]
                         if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                modes += [kw.value.value for kw in node.keywords
                          if kw.arg == "mode" and isinstance(kw.value, ast.Constant)]
                if any(f in m for m in modes for f in ("w", "a", "x", "+")):
                    found.append((node.lineno, "open:" + ",".join(modes)))
        # Writes BELOW `main` are the report the caller asked for. Writes above it
        # would be the benchmark mutating its own inputs.
        return [f for f in found if f[0] < main_line]
