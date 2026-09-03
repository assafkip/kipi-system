"""One draft definition, and the assistant cannot pick its own coverage.

REPRODUCER for F13 (`prd-voice-gate-totality-2026-08-25`, issue
`vg-one-draft-definition`). Measured 2026-09-01 against the two extractors this
file replaces, using ONE 1465-byte LinkedIn post delivered five ways:

    delivery shape                        extract_publishable  extract_setoff_draft
    hr-rules, no announcing sentence          0                    0     <- SHIPPED
    hr-rules + "Here's the post"           1494                    0
    prose fence, no sentence                  0                 1465
    blockquote, no sentence                   0                 1465
    bare text                                 0                    0

Four of five deliveries were invisible to the voice lint. Three of five were
invisible to the authorship scorer. The turn that actually shipped was invisible
to BOTH: it fell under MIN_TEXT_BYTES, was never linted, and spooled an EMPTY
string to the scorer.

None of that was a decision. It was prose habit. A gate whose scope is set by how
the writer happened to format the turn is not a gate, because the writer selects
its own enforcement.

`candidate_draft` is the single definition both consumers use. It does not
require an announcing sentence and it does not require a fence.
"""
import importlib.util
import pathlib

import pytest

_HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "voice_stop_gate", _HERE / "voice-stop-gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vsg = _load()

# The real post from the 2026-09-01 turn, verbatim. Kept here rather than read
# from output/ so the fixture cannot rot when a scratch file is cleaned up.
POST = """Two of my investigation cases independently rewrote the same 250-line script from scratch. Same Maltego parsing, same confidence tiers, same Excel writer. The only difference between them was the subject's SSN and date of birth.

That was the moment I stopped writing scripts and started building a system.

I've been running my investigations practice inside Claude Code for a few months now. 42 cases, 287 evidence items, all of it under one process I built and could hand to another investigator tomorrow.

The part worth talking about is not the speed. It's that the process now refuses.

One case skipped evidence intake completely. A classification script got run against a document that was never registered, never extracted, never given an evidence ID. The findings were probably correct. They were also unusable, because I could not show where they came from.

So I wrote a hook. It blocks any script from running in a case folder if the source document was not ingested first. Not a note in a README. Code that says no.

That is what I would want to see from anyone joining a fraud team today. Not "I use AI." Show me something you built that takes work off your own plate, and show me the place where it stops you from being sloppy.

Knowledge in someone's head is folklore with a timestamp. It leaves when they do. A repo is a receipt.

The attackers already operate this way. Every operation they run teaches the next one. Our side keeps starting over."""


def _hr_bare():
    return ("Voice lint clean. 254 words, LinkedIn shape.\n\n---\n\n" + POST +
            "\n\n---\n\n**What I changed and why:**\n\n- cut the unmeasured claim\n")


def _hr_announced():
    return ("Here's the post.\n\n---\n\n" + POST +
            "\n\n---\n\n**What I changed and why:**\n\n- cut the unmeasured claim\n")


def _prose_fence():
    return "Voice lint clean.\n\n```\n" + POST + "\n```\n"


def _blockquote():
    return ("Voice lint clean.\n\n" +
            "\n".join("> " + line if line else ">" for line in POST.split("\n")) + "\n")


def _bare():
    return POST


DELIVERIES = {
    "hr_rules_bare_SHIPPED": _hr_bare,
    "hr_rules_announced": _hr_announced,
    "prose_fence": _prose_fence,
    "blockquote": _blockquote,
    "bare_text": _bare,
}


@pytest.mark.parametrize("name", sorted(DELIVERIES))
def test_every_delivery_shape_yields_the_same_draft(name):
    """The whole point. Five shapes, one post, one answer.

    RED before the fix for four of the five: the two old extractors returned 0
    bytes on hr_rules_bare (both), 0 from the scorer's on hr_rules_announced, and
    0 from the lint's on prose_fence and blockquote.
    """
    got = vsg.candidate_draft(DELIVERIES[name]())
    assert got == POST, (
        f"{name}: candidate_draft returned {len(got.encode())} bytes, "
        f"expected the {len(POST.encode())}-byte post")


def test_all_five_agree_with_each_other():
    """Stated as its own assertion so a partial fix cannot look like a pass."""
    results = {name: vsg.candidate_draft(build()) for name, build in DELIVERIES.items()}
    assert len(set(results.values())) == 1, {k: len(v) for k, v in results.items()}


def test_the_announcing_sentence_is_not_a_precondition():
    """`_PUBLISH_MARKER_RE` used to decide whether ANYTHING was checked.

    The shipped turn carried no marker, so the lint declined to look. The marker
    may inform; it may not gate.
    """
    assert not vsg._PUBLISH_MARKER_RE.search(_hr_bare()), \
        "fixture no longer reproduces the no-marker condition"
    assert vsg.candidate_draft(_hr_bare()) == POST


def test_a_draft_under_the_old_byte_floor_is_still_a_draft():
    """MIN_TEXT_BYTES=80 was the branch the shipped turn fell through (F9)."""
    short = ("Dont talk to me about AGI while I have to ask claude and codex "
             "to mark each others code for errors.")
    assert len(short.encode()) < 120
    assert vsg.candidate_draft("---\n\n" + short + "\n\n---\n") == short


# --- the negative control, and it is the one that matters --------------------
#
# A fix that returns the whole message is not a fix; it turns every engineering
# answer into a gated turn, which is how a gate gets switched off. These must
# yield NOTHING.

ENGINEERING_PROSE = """I looked at the route classifier and the answer is in `q-consult/pipeline/route_classifier.py:15`.

`_REQUEST` needs a writing verb at a sentence start or after can/could/would you. Your message used "use" and "respond", neither of which is in the list, so `has_request` is False and `classify` returns NOT_ROUTED before it ever looks at a surface.

I reproduced it against seven phrasings and four of them fail the same way. The test file has 26 tests and none of them assert that a founder-vocabulary phrasing must route, so the drift is invisible to the suite.

Traceback (most recent call last):
  File "<stdin>", line 3, in <module>
ImportError: attempted relative import with no known parent package

The fix is in `voice-stop-gate.py`, which lives in the skeleton tree, so it reaches the fleet rather than this instance alone."""


def test_engineering_prose_is_not_a_draft():
    assert vsg.candidate_draft(ENGINEERING_PROSE) == ""


def test_a_code_fence_is_never_a_draft():
    text = ("Here is the fix.\n\n```python\n"
            "def candidate_draft(text):\n"
            "    return text\n"
            "```\n")
    assert vsg.candidate_draft(text) == ""


def test_a_bullet_list_answer_is_not_a_draft():
    text = ("What I ran:\n\n"
            "- `voiceloop score` against the corpus, 0 findings over 117 exemplars\n"
            "- `decide._violations`, 0 of 14\n"
            "- the Stop hook, which never saw the draft at all\n"
            "- `voice-lint.py`, by hand, on a scratchpad file\n")
    assert vsg.candidate_draft(text) == ""


def test_an_empty_or_whitespace_message_is_not_a_draft():
    assert vsg.candidate_draft("") == ""
    assert vsg.candidate_draft("\n\n   \n") == ""


def test_the_route_path_reads_candidate_draft_for_every_delivery_shape():
    """F13's property, kept where it has teeth (ASK-1197 round 9).

    This test used to assert that `extract_publishable` and
    `extract_setoff_draft` BOTH equal `candidate_draft`. Round 9 split them, and
    the reason is a defect that split caused: `candidate_draft` does not require
    framing, so routing the LINT through it voice-linted ordinary conversational
    replies to the founder and exited 2 on them. voice-enforcement.md scopes the
    lint to content sent to another person and excludes replies to the founder,
    so the lint is framing-required again.

    F13's actual concern -- the assistant selecting its own enforcement by how it
    happens to format the turn -- is preserved on the ROUTE path, which is the
    enforcement with teeth. Under a live routed request, every one of the five
    delivery shapes is seen, framed or not. Formatting cannot buy a bypass.

    The residual is real and is recorded, not waved away: with framing required,
    an UNFRAMED post is not voice-linted, which is the hr_rules_bare_SHIPPED
    shape from this file's own header. That is captured as spillover, not left in
    a comment.
    """
    for name, build in DELIVERIES.items():
        text = build()
        assert vsg._output_carries_draft(text), (
            f"{name}: the route path did not see a draft, so an assistant could "
            "skip route enforcement by choosing a delivery shape")


def test_the_two_lint_entry_points_agree_when_the_draft_is_announced_and_set_off():
    """The two-writers defect, stated as the property that is actually true.

    They do NOT agree in general, by design and by their own docstrings:
    `extract_publishable` falls back to the whole message when framing is present
    but nothing is set off, and `extract_setoff_draft` never does, because the
    scorer must not sweep engineering chat into a 319MB torch measurement. My
    first version of this test asserted agreement on a bare prose fence and went
    red against correct code -- the pre-R8 table in this file's header shows that
    disagreement as expected behaviour.

    Where a delivery is BOTH announced and set off, there is nothing to fall back
    to and nothing to be strict about, so both must return the same post. That is
    the overlap the 2026-09-01 measurement showed them disagreeing on.
    """
    announced_and_fenced = "Here's the post.\n\n```\n" + POST + "\n```\n"
    assert vsg.extract_publishable(announced_and_fenced) == POST
    assert vsg.extract_setoff_draft(announced_and_fenced) == POST


def test_an_unframed_delivery_is_not_linted_but_is_still_routed():
    """The round 9 trade, pinned so it is a decision and not an accident.

    An unframed post (the hr_rules_bare shape that actually SHIPPED) is not
    voice-linted, because voice-enforcement.md scopes the lint out of
    conversational replies and framing is the only signal available. It IS seen
    by the route path, so it cannot dodge receipt enforcement. Captured as
    spillover rather than left as a comment.
    """
    bare = _bare()
    assert vsg.extract_publishable(bare) == "", (
        "an unframed message is conversational for the lint; linting it exits 2 "
        "on ordinary replies to the founder")
    assert vsg._output_carries_draft(bare), (
        "but the route path must still see it, or formatting buys a bypass")
