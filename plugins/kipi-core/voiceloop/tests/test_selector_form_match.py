#!/usr/bin/env python3
"""Form-matching and anchor diversity: the two halves that only work together.

The scar (prd-content-engine-sameness-2026-08-09, finding-5). `selector.select`
concatenated the primary and fallback tiers before walking, so its own docstring
claim -- "a post slot gets post-shaped exemplars first" -- was false in code. Over
rotation counters 0-29, 18/30 rotations gave a post slot at most one post-kind
exemplar and 12/30 gave zero. Article excerpts teach article rhythm, which is the
essay-shaped output the founder read back as word salad.

Fixing tier exhaustion alone makes it WORSE in a way a naive test cannot see. The
anchor is drawn from `pool`; once `pool` is primary-only, a corpus carrying one
post-kind anchor pins that single row into every prompt -- which `selector.py`'s
own docstring names as a scar: "a pinned anchor is the same 3-exemplars-forever
failure with extra steps."

So the assertion here is deliberately COMPOSITE, and the weaker one is rejected:

- "zero article-excerpt exemplars in a post slot" passes while the pinning
  regression ships.
- "distinct anchor ids >= 3" passes TODAY, before any fix, because the unfixed
  concatenated pool rotates across article-kind anchors. Green for the wrong
  reason is the exact instrument failure this PRD exists to stop.

Both clauses in one test, so neither fix can land alone and report success.

No founder data: the fixtures are synthetic rows mirroring the real corpus's
SHAPE (12 post / 18 article-excerpt, anchors split across both kinds), never its
content. test_no_founder_data.py polices the other direction.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voiceloop import selector  # noqa: E402

ROTATION = range(30)          # one full lap of the real corpus's 30 rows


def _corpus(post_anchors=3, article_anchors=2, n_post=12, n_article=18):
    """A corpus with the real one's shape. Anchors land on the LOW ids of each
    kind, which is where sorted-by-id rotation reaches them first."""
    rows = []
    for i in range(n_post):
        rows.append({"id": f"p-{i:02d}", "kind": "post", "channel": "any",
                     "anchor": i < post_anchors, "text": f"post body {i}"})
    for i in range(n_article):
        rows.append({"id": f"a-{i:02d}", "kind": "article-excerpt",
                     "channel": "any", "anchor": i < article_anchors,
                     "text": f"article body {i}"})
    return rows


def _anchors_over_rotation(rows, slot_kind="post", channel="x"):
    """Every anchor row that rides in a prompt across one rotation lap."""
    out = []
    for counter in ROTATION:
        picked = selector.select(rows, channel, counter, slot_kind=slot_kind)
        out.extend(r for r in picked if r.get("anchor"))
    return out


def test_a_post_slot_anchor_is_post_kind_and_rotates_across_three_rows():
    """THE issue's bypass_check, both clauses. Fails today on clause 1 (article
    anchors ride in a post slot); fails on clause 2 if tier exhaustion ships
    against a corpus with a single post-kind anchor."""
    anchors = _anchors_over_rotation(_corpus())
    assert anchors, "an anchor must ride in every selection"

    kinds = sorted({r["kind"] for r in anchors})
    assert kinds == ["post"], (
        f"a post slot drew anchors of kind {kinds}: the fallback tier is being "
        f"walked before the primary tier is exhausted, so article rhythm is "
        f"teaching post slots")

    distinct = {r["id"] for r in anchors}
    assert len(distinct) >= 3, (
        f"the anchor pinned to {sorted(distinct)}: rotating one row into every "
        f"prompt is the 3-exemplars-forever failure with extra steps")


def test_a_post_slot_never_pads_with_articles_while_posts_remain():
    """The form-matching half on its own, so a failure is diagnosable. The whole
    selection -- not just the anchor -- stays inside the primary tier when the
    primary tier can fill k."""
    for counter in ROTATION:
        picked = selector.select(_corpus(), "x", counter, slot_kind="post")
        assert picked, "a non-empty corpus must yield a selection"
        assert all(r["kind"] == "post" for r in picked), (
            f"counter={counter} drew {[(r['id'], r['kind']) for r in picked]}")


def test_negative_selftest_a_single_post_anchor_pins():
    """Prove clause 2 can fail. One post-kind anchor + tier exhaustion = the
    pinned-anchor regression, which is why the data fix is not optional."""
    anchors = _anchors_over_rotation(_corpus(post_anchors=1))
    assert {r["kind"] for r in anchors} == {"post"}
    assert len({r["id"] for r in anchors}) == 1, (
        "this fixture exists to reproduce the pin; if it no longer pins, the "
        "test above no longer proves anything")


def test_a_thin_primary_tier_still_pads_from_fallback():
    """Exhaustion is not starvation. Below k post rows, articles pad rather than
    the slot shrinking -- and the corpus-level floor is validate's job, not a
    runtime refusal."""
    rows = _corpus(post_anchors=1, n_post=2)
    picked = selector.select(rows, "x", 0, slot_kind="post")
    assert len(picked) == selector.DEFAULT_K
    assert {r["kind"] for r in picked} == {"post", "article-excerpt"}


def _voice_dir(tmp_path, rows):
    """A minimal on-disk voice dir. Returns the PATH, because `check_all` takes a
    directory while the individual checks take a loaded Voice."""
    from voiceloop import corpus, fingerprint

    d = tmp_path / f"voice-{len(list(tmp_path.iterdir()))}"
    d.mkdir()
    (d / corpus.EXEMPLARS).write_text(
        "\n".join(json.dumps(dict(r, status="active", weight=1.0)) for r in rows))
    texts = [r["text"] for r in rows if r["kind"] == "post"]
    (d / "fingerprint.json").write_text(
        json.dumps(fingerprint.compute(texts, generated_at="2026-08-09")))
    (d / "identity.md").write_text("The practitioner.")
    (d / "pov.md").write_text("Learning disappears.")
    return str(d)


def _loaded(tmp_path, rows):
    """The same corpus, loaded, so validate's per-check functions can run on it."""
    from voiceloop import corpus

    return corpus.load(_voice_dir(tmp_path, rows))


def test_the_validator_reports_a_pinning_anchor_set(tmp_path):
    """The corpus-side half of the pairing: selector rotates what the corpus gives
    it, so the floor has to live in validate. Loud at edit time, never a runtime
    refusal -- corpus.py's degrade posture is unchanged."""
    from voiceloop import validate

    pinned = validate.check_anchor_diversity(_loaded(tmp_path, _corpus(
        post_anchors=1)))
    assert any("anchor row" in p for p in pinned), pinned

    rotating = validate.check_anchor_diversity(_loaded(tmp_path, _corpus(
        post_anchors=3)))
    assert rotating == [], rotating

    # A corpus that marks NOTHING pins nothing; `select` guards with `if anchors:`.
    # Firing here would red every anchorless fleet instance for a defect they do
    # not have, and a check that cries wolf gets switched off.
    anchorless = validate.check_anchor_diversity(_loaded(tmp_path, _corpus(
        post_anchors=0, article_anchors=0)))
    assert anchorless == [], anchorless


def test_anchors_that_exist_but_no_post_slot_can_reach_are_reported(tmp_path):
    """The exemption is scoped to the CORPUS, not to the kind (adversarial review,
    2026-08-09). Keying it on the per-kind count let the worst case through: the
    author marked anchors, and after tier exhaustion not one of them can ride in a
    post prompt."""
    from voiceloop import validate

    rows = _corpus(post_anchors=0, article_anchors=2)
    rode = [r for r in _anchors_over_rotation(rows) if r]
    assert rode == [], (
        "fixture no longer reproduces the case: the point is that anchors exist "
        "and ZERO of them reach a post slot")
    assert any(r.get("anchor") for r in rows), "the corpus must still mark anchors"

    problems = validate.check_anchor_diversity(_loaded(tmp_path, rows))
    assert any("anchor row" in p for p in problems), problems


def test_a_pool_the_same_size_as_k_cannot_rotate_and_says_so(tmp_path):
    """B1, adversarial review 2026-08-09. Choosing k of k is the same set forever,
    and the cliff is invisible at k-1 and k+1. `select` stays form-pure rather than
    padding with the wrong kind to fake variety; the shortage surfaces in validate.
    """
    from voiceloop import validate

    distinct = {}
    for n_post in (3, 4, 5, 12):
        rows = _corpus(post_anchors=min(3, n_post), n_post=n_post)
        distinct[n_post] = len({
            tuple(sorted(r["id"] for r in selector.select(
                rows, "x", c, slot_kind="post")))
            for c in ROTATION})

    assert distinct[4] == 1, distinct
    assert distinct[5] > 1 and distinct[12] > 1, distinct

    at_k = [p for p in validate.check_rotation_headroom(
        _loaded(tmp_path, _corpus(n_post=4))) if p.startswith("slot (x, post)")]
    assert any("exactly one possible set" in p for p in at_k), at_k

    above_k = [p for p in validate.check_rotation_headroom(
        _loaded(tmp_path, _corpus(n_post=12))) if p.startswith("slot (x, post)")]
    assert above_k == [], above_k


def test_the_rotation_message_is_true_about_the_corpus_it_describes(tmp_path):
    """Both reviewers, by different methods, caught the first version printing
    'every prompt gets the SAME set' at n=1,2,3, where padding makes selection
    vary. A validator that says something false about its own data is worse than
    silence, so the claim and the measurement are asserted TOGETHER."""
    from voiceloop import validate

    for n_post in (1, 2, 3, 4, 5, 12):
        rows = _corpus(post_anchors=min(3, n_post), n_post=n_post)
        distinct = len({
            tuple(sorted(r["id"] for r in selector.select(
                rows, "x", c, slot_kind="post"))) for c in ROTATION})
        said = [p for p in validate.check_rotation_headroom(_loaded(tmp_path, rows))
                if p.startswith("slot (x, post)")]
        claims_one_set = any("exactly one possible set" in p for p in said)
        assert claims_one_set == (distinct == 1), (
            f"n_post={n_post}: measured {distinct} distinct selections, but the "
            f"check {'claims' if claims_one_set else 'does not claim'} there is "
            f"exactly one. Said: {said}")


def test_the_anchor_message_counts_what_the_slot_can_actually_reach(tmp_path):
    """The by-kind count equals the real pool only above k. Below k the selector
    pads, so article-kind anchors DO ride in a post slot -- adversarial review
    measured 38 rides from 2 distinct ids while the check said 0 post anchors
    pinned one row, a sentence false in both halves."""
    from voiceloop import validate

    for n_post, p_anch, a_anch in ((3, 0, 2), (3, 1, 0), (12, 4, 2), (12, 0, 2)):
        rows = _corpus(post_anchors=p_anch, article_anchors=a_anch, n_post=n_post)
        ids = {r["id"] for r in _anchors_over_rotation(rows)}
        said = [p for p in validate.check_anchor_diversity(_loaded(tmp_path, rows))
                if p.startswith("slot (x, post)")]
        if said:
            assert f"can reach {len(ids)} of" in said[0], (
                f"n_post={n_post} anchors=({p_anch},{a_anch}): {len(ids)} distinct "
                f"anchors actually ride, but the check said: {said[0]}")
        else:
            assert len(ids) >= 3, (n_post, p_anch, a_anch, ids)


def test_both_new_checks_are_wired_into_check_all(tmp_path):
    """V4/V5: adversarial review deleted each `check_all` call line and all 60
    voiceloop tests plus all 19 pipeline tests stayed green. Unwiring the two OLD
    checks was killed, so this was a real hole -- the checks existed and nothing
    proved the entry point ran them."""
    from voiceloop import validate

    from voiceloop import corpus

    # Built to trip BOTH: 4 post rows is the rotation cliff, 1 anchor is below the
    # reachable floor.
    rows = _corpus(post_anchors=1, n_post=4)
    voice_dir = _voice_dir(tmp_path, rows)
    reported = validate.check_all(voice_dir)
    loaded = corpus.load(voice_dir)

    for check in (validate.check_anchor_diversity, validate.check_rotation_headroom):
        own = check(loaded)
        assert own, (
            f"{check.__name__} reported nothing on a corpus built to trip it; "
            f"this test proves WIRING and cannot do that against a silent check")
        for problem in own:
            assert problem in reported, (
                f"{check.__name__} is not wired into check_all: it reports "
                f"{problem!r} and check_all does not")


def test_selection_does_not_depend_on_the_order_rows_sit_in_the_file(tmp_path):
    """M9: a mutant that drops the id sort in `eligible` survived the whole suite.

    The property the sort actually buys is INPUT-ORDER INDEPENDENCE: the corpus is
    a JSONL file that gets appended to, re-ordered by hand edits, and re-emitted by
    tooling, and none of that may change which exemplars a given counter selects.
    Without the sort, the rotation is a function of line order, so moving a row
    silently re-deals every prompt while every other test stays green.

    NOT asserted here, because it is arithmetic rather than a defect: that ADDING a
    row leaves rotations unchanged. `offset` is `counter % len(pool)`, so a pool
    growing from 12 to 13 re-indexes by construction. The first version of this
    test asserted that and failed for a reason that was not a bug -- measured, 20
    of 30 rotations move.
    """
    rows = _corpus(n_post=12)
    straight = {c: [r["id"] for r in selector.select(rows, "x", c, slot_kind="post")]
                for c in ROTATION}

    for shuffle in (list(reversed(rows)), rows[7:] + rows[:7], rows[1::2] + rows[0::2]):
        assert {r["id"] for r in shuffle} == {r["id"] for r in rows}, "same rows"
        got = {c: [r["id"] for r in selector.select(shuffle, "x", c, slot_kind="post")]
               for c in ROTATION}
        assert got == straight, (
            "re-ordering the corpus file changed the selection; rotation is keyed "
            "to line order rather than to ids, so a hand edit re-deals every prompt")


def test_slot_index_advances_the_rotation():
    """M2: 7 of 8 mutants survived the suite because `slot_index` had no coverage
    anywhere in voiceloop. A multi-slot day must not hand both slots the same set."""
    rows = _corpus()
    for counter in (0, 7, 29):
        first = [r["id"] for r in selector.select(rows, "x", counter, slot_index=0,
                                                  slot_kind="post")]
        second = [r["id"] for r in selector.select(rows, "x", counter, slot_index=1,
                                                   slot_kind="post")]
        assert first != second, (counter, first)
        # slot_index and counter feed one offset, so slot 1 IS the next counter.
        assert second == [r["id"] for r in selector.select(
            rows, "x", counter + 1, slot_index=0, slot_kind="post")]


def test_k_is_honored_and_the_exhaustion_boundary_sits_at_k():
    """M2: the `>= k` threshold was indistinguishable from `> k`. It is the line
    between a form-pure selection and one padded with article excerpts, so it gets
    an assertion on both sides of the boundary."""
    rows_at_k = _corpus(post_anchors=3, n_post=4)
    picked = selector.select(rows_at_k, "x", 0, slot_kind="post")
    assert len(picked) == selector.DEFAULT_K
    assert {r["kind"] for r in picked} == {"post"}, (
        "at exactly k the primary tier is sufficient; padding here would import "
        "article rhythm to buy variety")

    rows_below_k = _corpus(post_anchors=1, n_post=3)
    padded = selector.select(rows_below_k, "x", 0, slot_kind="post")
    assert len(padded) == selector.DEFAULT_K
    assert "article-excerpt" in {r["kind"] for r in padded}

    for k in (2, 3, 6):
        got = selector.select(_corpus(), "x", 0, k=k, slot_kind="post")
        assert len(got) == k, (k, len(got))
        assert {r["kind"] for r in got} == {"post"}


def test_a_comment_slot_still_falls_back_to_posts():
    """Fleet regression guard (finding-20). ELIGIBLE_KINDS maps comment/dm to a
    ('comment','dm') primary tier that most instances have ZERO rows for. Tier
    exhaustion must not turn an empty primary into an empty selection."""
    rows = _corpus()
    assert not [r for r in rows if r["kind"] in ("comment", "dm")]
    picked = selector.select(rows, "x", 0, slot_kind="comment")
    assert len(picked) == selector.DEFAULT_K
    assert {r["kind"] for r in picked} == {"post"}


def test_the_comment_mapping_exists_and_is_not_a_fallthrough():
    """The guard above could not tell a correct mapping from its own absence.

    Standard review 2026-08-09: deleting the `"comment"` entry from
    ELIGIBLE_KINDS entirely passed all 73 tests. `eligible()` does
    `ELIGIBLE_KINDS.get(slot_kind, ELIGIBLE_KINDS["post"])`, so a comment slot
    silently degrades to a POST slot -- whose fallback tier is article-excerpt.
    That is the wrong-form-teaching failure this whole PRD exists to remove,
    re-entering on the comment path, fleet-wide, green.

    The fixture was why: with zero comment-kind rows, `len == k` and
    `kinds == {"post"}` are satisfied identically by the real mapping and by the
    fallthrough. One comment-kind row discriminates them, so this test supplies
    one, and asserts the mapping's existence directly as a backstop.
    """
    assert "comment" in selector.ELIGIBLE_KINDS, (
        "the comment slot mapping is gone, so `eligible` falls through to the "
        "post mapping and a comment slot is padded with article excerpts")

    rows = _corpus() + [{"id": "c-00", "kind": "comment", "channel": "any",
                         "anchor": False, "text": "a real comment row"}]
    picked = selector.select(rows, "x", 0, slot_kind="comment")

    assert picked[0]["kind"] == "comment" or any(
        r["kind"] == "comment" for r in picked), (
        f"a comment-kind row exists and the comment slot did not select it: "
        f"{[(r['id'], r['kind']) for r in picked]}. The slot resolved to the post "
        f"mapping instead of its own.")
    assert "article-excerpt" not in {r["kind"] for r in picked}, (
        f"a comment slot drew article excerpts: "
        f"{[(r['id'], r['kind']) for r in picked]}")
