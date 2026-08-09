#!/usr/bin/env python3
"""voicekit offline suite. No model calls, no network, tmp_path only.

Every module gets a negative self-test: neuter the mechanism (or feed the known-bad
input) and prove the check fails. A test that cannot fail is not a test.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voicekit import assemble, corpus, echo, fingerprint, selector, validate  # noqa: E402

PUNCHY = ("I watched it break. Twice. The fix shipped in a day.\n\n"
          "Nobody asked why. That was the tell. We built the check instead.")
SMOOTH = ("In today's rapidly evolving landscape, organizations are increasingly "
          "discovering that comprehensive solutions require careful consideration "
          "of multiple interrelated factors. It is important to recognize that "
          "sustainable outcomes depend on thoughtful analysis of the underlying "
          "dynamics. Furthermore, teams that do not invest in robust processes "
          "will not achieve the results that they are hoping to accomplish.")


def _rows(n=6, kind="post", channel="any", anchor_every=None):
    rows = []
    for i in range(n):
        rows.append({"id": f"ex-{i:02d}", "kind": kind, "channel": channel,
                     "status": "active", "weight": 1.0,
                     "anchor": bool(anchor_every and i % anchor_every == 0),
                     "text": f"Body {i}. Short lines. It broke and I saw it break. "
                             f"Number {i} of {n} systems failed."})
    return rows


def _voice_dir(tmp_path, rows=None, corrections=None, identity="The practitioner.",
               pov="Learning disappears.", lexicon=None, fp=None):
    d = tmp_path / "voice"
    d.mkdir(exist_ok=True)
    (d / corpus.EXEMPLARS).write_text(
        "\n".join(json.dumps(r) for r in (rows if rows is not None else _rows())))
    if corrections is not None:
        (d / corpus.CORRECTIONS).write_text(
            "\n".join(json.dumps(r) for r in corrections))
    (d / corpus.IDENTITY).write_text(identity)
    (d / corpus.POV).write_text(pov)
    (d / corpus.LEXICON).write_text(json.dumps(lexicon or {
        "prefer": [{"use": "use", "not": "leverage"}],
        "voiceprint_terms": ["shelfware", "compound"]}))
    if fp is not None:
        (d / corpus.FINGERPRINT).write_text(json.dumps(fp))
    return str(d)


# --- fingerprint ------------------------------------------------------------------

class TestFingerprint:
    def test_metrics_are_pure_and_complete(self):
        m = fingerprint.metrics(PUNCHY)
        assert set(m) == set(fingerprint.METRIC_NAMES)
        assert m == fingerprint.metrics(PUNCHY)

    def test_punchy_and_smooth_separate_on_the_measured_axes(self):
        """The Stage 0 result in miniature: the blocking metrics must point the
        measured direction, or the gate built on them is theater."""
        p, s = fingerprint.metrics(PUNCHY), fingerprint.metrics(SMOOTH)
        assert p["sentence_mean"] < s["sentence_mean"]
        assert p["short_share"] > s["short_share"]
        assert p["first_person_rate"] > s["first_person_rate"]

    def test_first_person_rate_is_the_same_sentence_cased(self, ):
        """Capitalization must not move a MEASUREMENT (ASK-508, sp-83d62639).

        _FIRST_PERSON was the only pattern in fingerprint.py without re.I, so
        "We shipped" and "My take" scored as impersonal and the same prose
        measured differently depending on where a sentence happened to break.
        The band this feeds is blocking, so a case-sensitive count is a gate
        that moves under the text.
        """
        # No bare lowercase "i" here on purpose: the I-forms stay case-sensitive
        # so that i.e. cannot read as first person (the test below), which means
        # "i" and "I" are NOT expected to measure the same. The words that vary
        # innocently with sentence position are the ones this pins.
        lower = "we broke it. my fault, our call, blame me."
        upper = "We broke it. My fault, Our call, blame Me."
        assert (fingerprint.metrics(upper)["first_person_rate"]
                == fingerprint.metrics(lower)["first_person_rate"])

    def test_capitalization_never_moves_the_measurement(self, ):
        """The PROPERTY, across a case table, not the spellings a reviewer named
        (ASK-512).

        ASK-508 fixed "We shipped" and shipped [Ww]e, which still missed
        ALL-CAPS -- so a headline or emphatic line measured as impersonal in a
        BLOCKING band. Enumerating shapes is what left the hole; the invariant
        is that case carries no information about first person, so every casing
        of the same sentence must land on the same number.
        """
        variants = ["we broke it and my call cost us our week",
                    "We broke it and My call cost us Our week",
                    "WE BROKE IT AND MY CALL COST US OUR WEEK",
                    "wE bRoKe It AnD mY cAlL cOsT uS oUr WeEk"]
        rates = {v: fingerprint.metrics(v)["first_person_rate"] for v in variants}
        assert len(set(rates.values())) == 1, (
            "capitalization moved the measurement: %r" % rates)
        assert all(r > 0 for r in rates.values()), "precondition: some matched"

    def test_bare_i_in_an_abbreviation_is_not_first_person(self, ):
        """The guard on the fix above: re.I across the whole pattern would make
        \\bi\\b match the "i" in "i.e.", inventing first-person voice in prose
        that has none. The I-forms stay case-sensitive; only the genuinely
        case-varying words become case-insensitive.
        """
        assert fingerprint.metrics("The gate, i.e. the hook, ran.")[
            "first_person_rate"] == 0.0

    def test_bands_from_the_pre_fix_instrument_are_stale(self, ):
        """A LITERAL version, not a relative one (ASK-508, codex major on #127).

        first_person_rate changed meaning when the case classes landed, so bands
        computed before that measure occurrences the old instrument could not
        see. METRICS_VERSION 2 is the value that shipped WITH the old regex, so
        a doc carrying it must now read as skewed or validate.py keeps treating
        pre-fix bands as current -- in a BLOCKING band that runs unattended,
        which means valid founder text refused at 3am by a gate calibrated to a
        different instrument.

        Asserted against the literal 2 on purpose. The staleness test below uses
        METRICS_VERSION - 1, which follows the constant and therefore stays green
        whether or not anyone remembers to bump it -- it cannot catch a missing
        bump, which is the whole failure mode here.
        """
        # A TABLE of literals, one per version that shipped a DIFFERENT
        # first_person_rate. Grown, never rewritten: 2 shipped the no-re.I
        # regex, 3 shipped [Ww]e (which measured ALL-CAPS as impersonal --
        # "WE SHIPPED MY CODE. WE DID." reads 0.0 under 3 and 50.0 under 4).
        # Each new row is the receipt that a measurement change was noticed.
        for shipped in (2, 3):
            assert fingerprint.version_skew({"metrics_version": shipped}), (
                "bands computed by instrument v%d measure something this "
                "version does not; they must not read as current" % shipped)

    def test_compute_then_score_roundtrip(self):
        texts = [PUNCHY, PUNCHY + " More of it.", "Short. Very. It broke. I saw."]
        fp = fingerprint.compute(texts, generated_at="2026-08-06",
                                 blocking=["sentence_mean"])
        verdict = fingerprint.score(texts[0], fp)
        assert verdict["sentence_mean"]["inside"]

    def test_out_of_band_names_the_failing_metric(self):
        fp = fingerprint.compute([PUNCHY, "It broke. I watched. We fixed it fast."],
                                 generated_at="2026-08-06",
                                 blocking=["sentence_mean", "short_share"])
        assert "sentence_mean" in fingerprint.out_of_band(SMOOTH, fp)

    def test_negative_selftest_neutered_bands_pass_everything(self):
        """Neuter the mechanism: with the blocking list emptied, even SMOOTH passes.
        Proves the tier list is what rejects, not an accident elsewhere."""
        fp = fingerprint.compute([PUNCHY], generated_at="2026-08-06", blocking=[])
        assert fingerprint.out_of_band(SMOOTH, fp) == []

    def test_empty_corpus_raises_loudly(self):
        with pytest.raises(ValueError):
            fingerprint.compute([], generated_at="2026-08-06")

    def test_corpus_sha_is_order_independent(self):
        assert fingerprint.corpus_sha(["a", "b"]) == fingerprint.corpus_sha(["b", "a"])


# --- corpus (degrade, never die) --------------------------------------------------

class TestCorpus:
    def test_missing_dir_loads_empty_not_raising(self, tmp_path):
        v = corpus.load(str(tmp_path / "nowhere"))
        assert v.exemplars == [] and v.identity == "" and v.fingerprint is None

    def test_corrupt_row_is_skipped_and_counted(self, tmp_path):
        d = tmp_path / "voice"
        d.mkdir()
        good = json.dumps(_rows(1)[0])
        (d / corpus.EXEMPLARS).write_text(good + "\n{torn json\n")
        v = corpus.load(str(d))
        assert len(v.exemplars) == 1
        assert v.skipped_rows == 1, "the decay count is the deadman signal"

    def test_negative_selftest_the_count_sees_a_real_tear(self, tmp_path):
        """Prove the counter is wired to the parse, not a constant zero."""
        d = tmp_path / "voice"
        d.mkdir()
        (d / corpus.EXEMPLARS).write_text("{a\n{b\n{c\n")
        assert corpus.load(str(d)).skipped_rows == 3

    def test_nonnumeric_weight_degrades_instead_of_raising(self, tmp_path):
        """A row can be VALID JSON and still carry junk in a numeric field
        (ASK-508, sp-18daaa21).

        read_jsonl only guarantees the LINE parsed, so it counts no skip here and
        float() raised ValueError inside active_exemplars() -- past the
        degrade-without-dying boundary the loader exists to hold. The usable rows
        around it must still come back.
        """
        rows = _rows(2)
        rows[0]["weight"] = "heavy"
        v = corpus.load(_voice_dir(tmp_path, rows=rows))
        assert [r["id"] for r in v.active_exemplars()] == ["ex-01"], (
            "a junk weight must drop its own row and spare the rest")

    def test_nonnumeric_weight_is_counted_as_decay(self, tmp_path):
        """Dropping the row is half the job; the drop has to be VISIBLE
        (ASK-508, codex minor on #127).

        skipped_rows is the deadman signal validation and provenance read, and
        the first cut of the crash fix returned 0.0 for a junk weight and said
        nothing. A corpus quietly rotting to zero usable rows would have looked
        identical to a healthy one. A malformed field is a malformed ROW, the
        same class as a torn line, so it is counted where torn lines are.
        """
        rows = _rows(2)
        rows[0]["weight"] = "heavy"
        v = corpus.load(_voice_dir(tmp_path, rows=rows))
        assert v.skipped_rows == 1, (
            "a junk weight must show up as decay, not vanish (got %r)"
            % (v.skipped_rows,))

    def test_non_finite_weights_are_counted_as_decay(self, tmp_path):
        """NaN and the infinities go through the same door as a junk string
        (ASK-508, codex minor on PR #127 round 2).

        float("NaN") and float("inf") PARSE, so the previous fix's try/except
        never fired. NaN then fails `> 0` and vanished uncounted, exactly the
        silent decay the round-1 fix was supposed to end. inf is worse in kind:
        it passes `> 0` and survives as a usable exemplar carrying infinite
        weight, so a nonsense row reads as the most valid row in the corpus.

        Fixing only the reported NaN would leave that. A weight has to be a
        real number to mean anything, so the check is finiteness, not a list of
        the spellings someone happened to report.
        """
        for spelling in ("NaN", "inf", "-inf", "Infinity"):
            rows = _rows(2)
            rows[0]["weight"] = spelling
            v = corpus.load(_voice_dir(tmp_path, rows=rows))
            assert [r["id"] for r in v.active_exemplars()] == ["ex-01"], (
                "%r must not survive as a usable row" % spelling)
            assert v.skipped_rows == 1, (
                "%r must show up as decay, got %r" % (spelling, v.skipped_rows))

    def test_no_json_scalar_weight_can_crash_the_loader(self, tmp_path):
        """The PROPERTY: a weight is a finite number or the row is decay, for
        every scalar JSON can carry (ASK-512).

        ASK-508 caught non-numeric strings and the non-finite floats, then
        missed a plain integer too big for a float -- float(10**400) raises
        OverflowError, which (TypeError, ValueError) does not catch. Valid JSON,
        loader dead. Listing the shapes someone reported is what left it, so
        this walks the scalar space instead.
        """
        # TWO assertions per shape, because the first cut made only the first
        # one and was structurally blind to the codex nit on PR #128: a falsy
        # malformed weight ([], {}, "", null) hit `float(raw or 0)`, became 0.0,
        # failed `> 0`, and so satisfied "not usable" while being RETAINED and
        # never counted as decay. A table that asserts one half of a property is
        # the same defect as the METRICS_VERSION - 1 test replaced this round.
        malformed = ["heavy", "NaN", "inf", "-inf", "Infinity", 10 ** 400,
                     -(10 ** 400), None, True, False, [], {}, "", "1e999"]
        for bad in malformed:
            rows = _rows(2)
            rows[0]["weight"] = bad
            v = corpus.load(_voice_dir(tmp_path, rows=rows))
            assert [r["id"] for r in v.active_exemplars()] == ["ex-01"], (
                "weight=%r must not survive as usable" % (bad,))
            assert v.skipped_rows == 1, (
                "weight=%r is malformed, so it must show as decay (got %r)"
                % (bad, v.skipped_rows))

        # The other side of the boundary: a real zero is a DECISION, not damage.
        # Without this the fix could over-reach and start counting deliberate
        # zero-weight rows as corpus decay, which would fire the deadman signal
        # on a healthy corpus.
        for legit in (0, 0.0, "0"):
            rows = _rows(2)
            rows[0]["weight"] = legit
            v = corpus.load(_voice_dir(tmp_path, rows=rows))
            assert [r["id"] for r in v.active_exemplars()] == ["ex-01"]
            assert v.skipped_rows == 0, (
                "weight=%r is a deliberate zero, not decay (got %r)"
                % (legit, v.skipped_rows))

    def test_retired_and_zero_weight_rows_are_excluded(self, tmp_path):
        rows = _rows(3)
        rows[0]["status"] = "retired"
        rows[1]["weight"] = 0
        v = corpus.load(_voice_dir(tmp_path, rows=rows))
        assert [r["id"] for r in v.active_exemplars()] == ["ex-02"]


# --- selector ---------------------------------------------------------------------

class TestSelector:
    def test_deterministic(self):
        rows = _rows(8, anchor_every=4)
        a = selector.select(rows, "linkedin", counter=5)
        b = selector.select(rows, "linkedin", counter=5)
        assert [r["id"] for r in a] == [r["id"] for r in b]

    def test_rotation_no_repeated_set_across_consecutive_states(self):
        """The design's uniformity kill: 10 consecutive postbook states, no
        identical selection twice in a row."""
        rows = _rows(8)
        prev = None
        for counter in range(10):
            ids = [r["id"] for r in selector.select(rows, "linkedin", counter)]
            assert ids != prev, f"counter {counter} repeated {ids}"
            prev = ids

    def test_negative_selftest_without_the_counter_it_would_repeat(self):
        """Neuter rotation (fixed counter): the selection IS identical, proving the
        rotation test above is measuring the counter and nothing else."""
        rows = _rows(8)
        a = [r["id"] for r in selector.select(rows, "linkedin", 3)]
        b = [r["id"] for r in selector.select(rows, "linkedin", 3)]
        assert a == b

    def test_anchor_always_present_and_rotating(self):
        rows = _rows(9, anchor_every=3)          # anchors: ex-00, ex-03, ex-06
        seen = set()
        for counter in range(6):
            picked = selector.select(rows, "linkedin", counter)
            anchors = [r["id"] for r in picked if r["anchor"]]
            assert anchors, "an anchor must ride in every selection"
            seen.update(anchors)
        assert len(seen) > 1, "the anchor must rotate, not pin"

    def test_form_matching_prefers_post_rows_for_post_slots(self):
        rows = _rows(3, kind="article-excerpt") + _rows(3)[0:3]
        # ids collide across the two _rows calls; rebuild with distinct ids
        rows = ([{**r, "id": f"art-{i}"} for i, r in enumerate(_rows(3, kind="article-excerpt"))]
                + [{**r, "id": f"post-{i}"} for i, r in enumerate(_rows(3))])
        picked = selector.select(rows, "linkedin", counter=0, k=3)
        assert all(r["kind"] == "post" for r in picked), (
            "with enough post rows, article excerpts must not pad a post slot")

    def test_empty_pool_returns_empty(self):
        assert selector.select([], "linkedin", 0) == []


# --- echo -------------------------------------------------------------------------

class TestEcho:
    GUIDANCE = "Good shapes: Nothing was sent. Nothing was lost. The damage was trust."

    def test_the_shipped_defect_is_caught(self):
        """The Stage 0 live defect, verbatim: output carrying the guidance example."""
        candidate = ("Our queue died quietly. Nothing was sent. Nothing was lost. "
                     "The damage was trust. We rebuilt the receipts.")
        assert echo.prompt_echo(candidate, [self.GUIDANCE])

    def test_negative_selftest_clean_text_passes(self):
        assert echo.prompt_echo(PUNCHY, [self.GUIDANCE]) == []

    def test_short_shared_idiom_does_not_fire(self):
        assert echo.prompt_echo("The same thing happened to us last week in prod.",
                                ["the same thing happened to us"]) == []

    def test_opener_echo_catches_the_three_receipts_shape(self):
        recent = [["three", "receipts", "written", "out", "of", "five"]]
        assert echo.opener_echo("Three receipts written out of order today.", recent)

    def test_opener_echo_passes_a_fresh_opener(self):
        recent = [["three", "receipts", "written", "out", "of", "five"]]
        assert echo.opener_echo("I watched a deploy eat its own logs.", recent) is None


# --- assemble ---------------------------------------------------------------------

class TestAssemble:
    def test_order_identity_pov_lexicon_exemplars_corrections(self, tmp_path):
        cor = [{"id": "c1", "status": "active", "instruction": "Never open with a number."}]
        v = corpus.load(_voice_dir(tmp_path, corrections=cor))
        text, prov = assemble.voice_section(v, "linkedin", counter=0)
        order = [text.find("WHO IS WRITING"), text.find("WHAT HE WRITES"),
                 text.find("reaches for"), text.find("POSTS HE HAS WRITTEN"),
                 text.find("STANDING CORRECTIONS")]
        assert -1 not in order and order == sorted(order)
        assert prov["exemplar_ids"] and prov["correction_ids"] == ["c1"]

    def test_scoped_correction_excluded_off_channel(self, tmp_path):
        cor = [{"id": "c1", "status": "active", "scope": ["x"],
                "instruction": "X only rule."}]
        v = corpus.load(_voice_dir(tmp_path, corrections=cor))
        text, _ = assemble.voice_section(v, "linkedin", counter=0)
        assert "X only rule" not in text

    def test_off_channel_correction_is_not_recorded_as_applied(self, tmp_path):
        """Provenance is a RECEIPT, so it may only name corrections the prompt
        actually carried (ASK-508, sp-9642b63d).

        test_scoped_correction_excluded_off_channel above pins the prompt half
        and stops there, which is exactly why this survived review: the rule was
        correctly withheld from the model and still recorded as applied. Same
        class as the notify_cap scar, where an exit code became proof of a page
        that never sent.
        """
        cor = [{"id": "on", "status": "active", "scope": ["linkedin"],
                "instruction": "Linkedin only rule."},
               {"id": "off", "status": "active", "scope": ["x"],
                "instruction": "X only rule."}]
        v = corpus.load(_voice_dir(tmp_path, corrections=cor))
        text, prov = assemble.voice_section(v, "linkedin", counter=0)
        assert "X only rule" not in text, "precondition: the rule is withheld"
        assert prov["correction_ids"] == ["on"], (
            "provenance named %r; it must name only what the prompt carried"
            % (prov["correction_ids"],))

    def test_promoted_correction_stops_loading(self, tmp_path):
        cor = [{"id": "c1", "status": "promoted", "instruction": "Old rule."}]
        v = corpus.load(_voice_dir(tmp_path, corrections=cor))
        text, prov = assemble.voice_section(v, "linkedin", counter=0)
        assert "Old rule" not in text and prov["correction_ids"] == []

    def test_empty_voice_dir_yields_empty_section_not_a_raise(self, tmp_path):
        v = corpus.load(str(tmp_path / "nowhere"))
        text, prov = assemble.voice_section(v, "linkedin", counter=0)
        assert text == "" and prov["exemplar_ids"] == []

    def test_provenance_texts_match_prompt_exemplars(self, tmp_path):
        """The echo gate compares output to prov['exemplar_texts']; they must be
        the exact bodies the prompt carried."""
        v = corpus.load(_voice_dir(tmp_path))
        text, prov = assemble.voice_section(v, "linkedin", counter=2)
        for body in prov["exemplar_texts"]:
            assert body.strip() in text


# --- validate ---------------------------------------------------------------------

class TestValidate:
    def _fresh_fp(self, rows):
        texts = [r["text"] for r in rows if r["kind"] == "post"]
        return fingerprint.compute(texts, generated_at="2026-08-06")

    def test_healthy_corpus_passes(self, tmp_path):
        rows = _rows(6)
        d = _voice_dir(tmp_path, rows=rows, fp=self._fresh_fp(rows))
        assert validate.check_all(d) == []

    def test_negative_selftest_each_check_fires(self, tmp_path):
        rows = _rows(6)
        rows[1]["id"] = rows[0]["id"]                       # duplicate id
        rows[2]["text"] = "an emdash — right here"          # banned char
        d = _voice_dir(tmp_path, rows=rows, fp=self._fresh_fp(rows))
        problems = "\n".join(validate.check_all(d))
        assert "duplicate id" in problems and "emdash" in problems

    def test_stale_fingerprint_is_red(self, tmp_path):
        rows = _rows(6)
        stale = self._fresh_fp(_rows(3))
        d = _voice_dir(tmp_path, rows=rows, fp=stale)
        assert any("stale" in p for p in validate.check_all(d))

    def test_starved_pool_is_red(self, tmp_path):
        rows = _rows(2)
        d = _voice_dir(tmp_path, rows=rows, fp=self._fresh_fp(rows))
        assert any("floor" in p for p in validate.check_all(d))

    def test_budget_overflow_is_red(self, tmp_path):
        rows = _rows(6)
        for r in rows:
            r["text"] = "Long. " * 2000
        d = _voice_dir(tmp_path, rows=rows, fp=self._fresh_fp(rows))
        assert any("budget" in p for p in validate.check_all(d))


# --- voice-1-instrument: review findings 1, 2, 8 ----------------------------------

class TestBlockingTierContract:
    CORPUS = ["I saw it break. Twice. We fixed it.",
              "Long sentences flow onward without any pause or breath at all in "
              "this one here, and then some.",
              "Short. It broke. I watched it happen live.",
              "Mid length lines carry the middle of the band here.",
              "Another corpus row with its own rhythm and length in it."]

    def test_every_corpus_member_passes_its_own_blocking_tier(self):
        """Review finding-1 (blocker). On a small corpus the p10/p90 extremes are
        corpus members; blocking membership must widen to corpus min/max or the
        control-set requirement is unsatisfiable by construction."""
        fp = fingerprint.compute(self.CORPUS, generated_at="x",
                                 blocking=[{"metric": "sentence_mean",
                                            "direction": "above"},
                                           {"metric": "short_share",
                                            "direction": "below"}])
        for text in self.CORPUS:
            assert fingerprint.out_of_band(text, fp) == [], text

    def test_direction_above_only_blocks_above(self):
        """Review finding-2. sentence_mean is a CAP: below the band is the founder's
        punchiest register and must never block."""
        fp = fingerprint.compute(self.CORPUS, generated_at="x",
                                 blocking=[{"metric": "sentence_mean",
                                            "direction": "above"}])
        punchier = "It broke. I saw. We fixed. Done. Fast. True."
        assert fingerprint.out_of_band(punchier, fp) == []
        rambler = ("This sentence keeps going far beyond anything the corpus ever "
                   "did because it never stops to breathe or land a point at all "
                   "and simply continues onward accumulating clauses forever more "
                   "without any period in sight for dozens of words.")
        assert fingerprint.out_of_band(rambler, fp) == ["sentence_mean"]

    def test_negative_selftest_direction_both_still_blocks_below(self):
        """Prove direction is the discriminator: the same punchy text DOES block
        when the tier says both. Otherwise the above-only test passes vacuously."""
        fp = fingerprint.compute(
            ["Twelve words in every single sentence of this corpus row exactly here now.",
             "Another twelve word sentence fills this corpus row from end to end today.",
             "Yet more twelve word sentences occupy the entire corpus row right here."],
            generated_at="x",
            blocking=[{"metric": "sentence_mean", "direction": "both"}])
        assert fingerprint.out_of_band("Short. Very. Tiny. Words. Only. Here.",
                                       fp) == ["sentence_mean"]

    def test_legacy_string_blocking_entries_still_work(self):
        """A bands file written before direction support must not crash the gate."""
        fp = fingerprint.compute(self.CORPUS, generated_at="x",
                                 blocking=["sentence_mean"])
        assert fingerprint.out_of_band(self.CORPUS[0], fp) == []

    def test_metrics_version_recorded_and_checked(self):
        """Review finding-8. Bands computed by one instrument version must not be
        silently evaluated by another."""
        fp = fingerprint.compute(self.CORPUS, generated_at="x")
        assert fp["metrics_version"] == fingerprint.METRICS_VERSION
        stale = dict(fp, metrics_version=-1)
        assert fingerprint.version_skew(stale)
        assert not fingerprint.version_skew(fp)


# --- voice-1 review round: the four findings, pinned -------------------------------

class TestReviewRoundFixes:
    def test_metrics_version_skew_is_caught_by_the_freshness_check(self, tmp_path):
        """Review blocker: version_skew existed, nothing called it. Same corpus_sha,
        stale metrics_version, and check_all reported healthy."""
        rows = [{"id": f"r{i}", "kind": "post", "channel": "any", "status": "active",
                 "anchor": False, "weight": 1.0,
                 "text": f"Row {i}. It broke. I watched. We fixed it fast."}
                for i in range(4)]
        fp = fingerprint.compute([r["text"] for r in rows], generated_at="x")
        fp["metrics_version"] = fingerprint.METRICS_VERSION - 1   # skew, sha intact
        d = tmp_path / "voice"
        d.mkdir()
        (d / corpus.EXEMPLARS).write_text("\n".join(json.dumps(r) for r in rows))
        (d / corpus.FINGERPRINT).write_text(json.dumps(fp))
        v = corpus.load(str(d))
        assert any("metrics_version" in p for p in validate.check_fingerprint_fresh(v))

    def test_direction_below_actually_blocks_below(self):
        """Review major: the below path had only a passing case. A floor must fire
        under the bounds and stay silent above them."""
        punchy_corpus = ["It broke. I saw. We fixed. Done. Fast.",
                         "Short lines. Real scars. It failed twice. I was there.",
                         "One look. One fix. The test went red. Then green."]
        fp = fingerprint.compute(punchy_corpus, generated_at="x",
                                 blocking=[{"metric": "short_share",
                                            "direction": "below"}])
        smooth = ("Every sentence in this candidate stretches onward comfortably "
                  "past the six word threshold without a single short burst. "
                  "Nothing here lands quickly or punches through the paragraph. "
                  "The rhythm stays long and even throughout the entire text.")
        assert fingerprint.out_of_band(smooth, fp) == ["short_share"]
        punchier = "It broke. I saw. Fixed. Done. True. Fast. Real. Short."
        assert fingerprint.out_of_band(punchier, fp) == [], (
            "a floor must never fire ABOVE the band")

    def test_partial_band_degrades_instead_of_raising(self):
        fp = {"metrics": {"sentence_mean": {"p10": None, "p50": None, "p90": None,
                                            "min": 3.0, "max": 9.0}},
              "blocking": [{"metric": "sentence_mean", "direction": "above"}]}
        assert fingerprint.out_of_band("Anything at all here.", fp) == []
        assert fingerprint.score("Anything at all here.", fp) == {}


class TestVoice2ReviewChecks:
    """voice-2 review round: placeholder markers, hashtag tails, corrections schema."""

    def test_placeholder_marker_is_red(self, tmp_path):
        rows = _rows(6)
        rows[0]["text"] += " 60% of their time {{UNVALIDATED}}"
        d = _voice_dir(tmp_path, rows=rows)
        assert any("placeholder" in p for p in
                   validate.check_exemplars(str(tmp_path / "voice" / "exemplars.jsonl")))

    def test_trailing_hashtag_line_is_red(self, tmp_path):
        rows = _rows(6)
        rows[0]["text"] += "\n\n#AI #BuildInPublic #FounderTools"
        _voice_dir(tmp_path, rows=rows)
        assert any("hashtag" in p for p in
                   validate.check_exemplars(str(tmp_path / "voice" / "exemplars.jsonl")))

    def test_hashtag_mid_text_is_not_flagged(self, tmp_path):
        """The check must catch the TAIL, not any # -- '#1 priority' is prose."""
        rows = _rows(6)
        rows[0]["text"] = "It was the #1 priority. Nobody worked it. That was the tell."
        _voice_dir(tmp_path, rows=rows)
        assert not any("hashtag" in p for p in
                       validate.check_exemplars(str(tmp_path / "voice" / "exemplars.jsonl")))

    def test_corrections_schema_negative_selftest(self, tmp_path):
        d = tmp_path / "voice"
        d.mkdir()
        (d / corpus.CORRECTIONS).write_text("\n".join([
            json.dumps({"id": "c1", "instruction": "x", "class": "interpretive",
                        "status": "active", "scope": ["linkedin"]}),
            json.dumps({"id": "c1", "instruction": "", "class": "nonsense",
                        "status": "weird", "scope": ["myspace"]}),
            "{torn",
        ]))
        problems = "\n".join(validate.check_corrections(str(d / corpus.CORRECTIONS)))
        for needle in ("duplicate id", "empty instruction", "class", "status",
                       "unknown scope", "unparseable"):
            assert needle in problems, needle

    def test_clean_corrections_pass(self, tmp_path):
        d = tmp_path / "voice"
        d.mkdir()
        (d / corpus.CORRECTIONS).write_text(json.dumps(
            {"id": "c1", "instruction": "Do the thing.", "class": "deterministic",
             "status": "promoted", "scope": ["dm"]}))
        assert validate.check_corrections(str(d / corpus.CORRECTIONS)) == []


class TestLoaderAdversarialScars:
    """voice-3 review: two scars from the retired glob-loader suite were claimed
    re-homed and were not. Pinned here against the corpus loader."""

    def test_permission_denied_file_degrades_to_empty(self, tmp_path):
        import os as _os
        p = tmp_path / "identity.md"
        p.write_text("secret")
        _os.chmod(p, 0o000)
        try:
            assert corpus.read_text(str(p)) == ""
            rows, skipped = corpus.read_jsonl(str(p))
            assert rows == [] and skipped == 0
        finally:
            _os.chmod(p, 0o644)

    def test_undecodable_byte_is_replaced_not_fatal(self, tmp_path):
        """The ASK-461-era scar: a plugin update writing a file mid-read produced a
        lone undecodable byte and UnicodeDecodeError killed the daily job."""
        p = tmp_path / "pov.md"
        p.write_bytes(b"good text \xff\xfe more text")
        out = corpus.read_text(str(p))
        assert "good text" in out and "more text" in out
        j = tmp_path / "rows.jsonl"
        j.write_bytes(b'{"id": "a", "text": "ok"}\n\xff{torn\n')
        rows, skipped = corpus.read_jsonl(str(j))
        assert [r["id"] for r in rows] == ["a"] and skipped == 1
