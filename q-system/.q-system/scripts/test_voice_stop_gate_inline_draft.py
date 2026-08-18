#!/usr/bin/env python3
"""A draft written with no fence is measured; ordinary chat still is not.

sp-88029341. `extract_setoff_draft` returned '' whenever the assistant wrote the
post straight into the message, so that draft was never scored and nothing about
the miss was observable -- the same silence-shaped failure the corpus-similarity
work keeps hitting.

## Why the fixtures are synthetic

This repo is PUBLIC. The detector was tuned against 14,034 real turns from the
founder's own session logs, and the numbers from that run are recorded in
`extract_inline_draft`'s docstring, but the message bodies themselves are private
chat and are not reproduced here. The fixtures below are written to the SHAPES
that measurement found, one class each:

    negative  a reply with markdown headings
    negative  a reply with a bullet list
    negative  a reply with code spans and file paths
    negative  a short conversational acknowledgement
    negative  a MIXTURE: real prose plus an engineering section
    positive  a post written inline with a lead-in sentence
    positive  a post written inline with nothing around it

The mixture case is the one that matters most, because it is what the obvious fix
(reusing `extract_publishable`'s whole-message fallback) gets wrong. Measured on
the real logs, that fallback fires on 47 engineering messages at 3.66s of torch
each; this detector fires on 0 of 62.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

STOP_GATE = Path(__file__).resolve().parent / "voice-stop-gate.py"


def _gate():
    spec = importlib.util.spec_from_file_location("_vsg_inline", STOP_GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POST = (
    "I counted rows in an append-only ledger and reported the total as a backlog.\n"
    "The number was wrong by forty three percent.\n"
    "An append-only file holds one row per state change, and I never collapsed\n"
    "them by id. The wrong total also hid the distribution, which was the part\n"
    "that actually mattered. Recompute any count somebody hands you, including\n"
    "the one you wrote down yourself."
)

CHAT_HEADINGS = (
    "Straight answer, and the second half is the one that matters.\n\n"
    "## Did the fix address the whole complaint\n\n"
    "Half of it. The opening was a shape problem and that part is closed.\n"
    "The other reading is structural and it is still open, which is why the\n"
    "count keeps moving between runs and nobody can explain the gap yet.\n"
)

CHAT_BULLETS = (
    "Both holes are silence-shaped, and that is the structural reason.\n\n"
    "- The scorer only speaks when a hook fires, so a miss makes no sound.\n"
    "- Nothing cannot page anyone, and a guard cannot report its own miss.\n"
    "- So both were found the way silence gets found, by a human noticing.\n"
)

CHAT_CODE = (
    "The pointer resolves, and the load path is the part that was wrong.\n"
    "`resolve_reporter` reads the pointer file and returns the named path even\n"
    "when it is missing, so a test can say the pointer names something absent\n"
    "instead of saying there is no pointer at all. That distinction is the fix.\n"
)

CHAT_SHORT = "Done. The suite is green and the gate holds now."

MIXTURE = POST + "\n\n## What changed\n\n- the extractor\n- the counter\n\n" + POST

INLINE_WITH_LEADIN = "Here's the post for LinkedIn.\n\n" + POST
INLINE_BARE = POST


@pytest.mark.parametrize("text,why", [
    (CHAT_HEADINGS, "markdown headings"),
    (CHAT_BULLETS, "a bullet list"),
    (CHAT_CODE, "code spans"),
    (CHAT_SHORT, "too short to be a post"),
    (MIXTURE, "prose glued to an engineering section"),
])
def test_ordinary_chat_is_never_taken_as_an_inline_draft(text, why):
    """THE EXPENSIVE DIRECTION. Each false positive here is a 319MB torch load
    on a turn that contains no draft, which is the compute the founder refused
    and the reason ASK-896 left this hole open rather than closing it badly."""
    assert _gate().extract_inline_draft(text) == "", why


@pytest.mark.parametrize("text", [INLINE_WITH_LEADIN, INLINE_BARE])
def test_a_post_written_inline_is_recovered(text):
    got = _gate().extract_inline_draft(text)
    assert got, "the inline draft was dropped; sp-88029341 is not fixed"
    assert got.startswith("I counted rows"), got
    assert "Here's the post" not in got, (
        "the lead-in sentence was swept into the thing being measured")


def test_a_set_off_draft_still_wins_over_the_inline_path():
    """The inline path is a FALLBACK, never a replacement. A fenced draft with
    chat around it must still yield only the fence body -- the property ASK-896
    built `extract_setoff_draft` for in the first place."""
    text = ("Here's the post.\n\n"
            "## Notes\n\n- one\n- two\n\n"
            "```\n" + POST + "\n```\n\nWant a shorter opener?")
    got = _gate().extract_setoff_draft(text)
    assert got.startswith("I counted rows"), got
    assert "Notes" not in got and "shorter opener" not in got, got


def test_the_share_floor_is_what_refuses_the_mixture():
    """A negative self-test on the specific guard, not on the whole function.

    Deleting the share floor must make the mixture case pass, or the floor is
    not the thing doing the work and this suite is asserting a coincidence.
    """
    gate = _gate()
    assert gate.extract_inline_draft(MIXTURE) == ""
    gate.INLINE_DRAFT_MIN_SHARE = 0.0
    assert gate.extract_inline_draft(MIXTURE) != "", (
        "with the share floor removed the mixture is still refused, so some "
        "other rule is carrying this case and the floor is untested")


# ---------------------------------------------------------------- hr fences ----
# sp-3bec4a5e: the FIRST live post after ASK-902 shipped was delivered between
# `---` horizontal rules with a framing line above and a "what changed" analysis
# below -- and extract_setoff_draft returned nothing. Measured on the real
# transcript (2026-08-18): the ``` fence list does not know `---`, and the
# inline fallback's 70% share floor refuses the mixture. The founder's most
# common delivery shape was structurally invisible.

HR_REPLY = (
    "The version carrying both of your corrections - no CTA ending:\n"
    "\n---\n\n"
    "A 40 hour week with ADHD is a joke. Or a curse, depending on the day. "
    + ("His brain gives him hyperfocus hours that outrun whole teams. " * 6)
    + "\n\nSeat time is what the 40 hour week actually measures. "
    + ("Force presence and you trade the best hours for the worst ones. " * 4)
    + "\n\n---\n\n"
    "What changed:\n\n- the ending is a statement now\n- the scaffold is gone\n"
    "\nReady to paste."  # the marker: the REAL missed turn carried this trailer,
                          # and since round 6 no extraction path runs without one
)


def test_an_hr_fenced_draft_is_extracted():
    draft = _gate().extract_setoff_draft(HR_REPLY)
    assert draft, "a --- set-off draft must be extracted, not dropped"
    assert "40 hour week" in draft
    assert "What changed" not in draft, "analysis after the fences leaked in"
    assert "corrections - no CTA" not in draft, "framing above the fences leaked in"


def test_an_hr_pair_inside_ordinary_prose_is_not_a_draft():
    """Negative: two horizontal rules used as section dividers in an engineering
    reply must not turn the middle section into a "draft"."""
    text = (
        "Status update on the pipeline run.\n\n---\n\n"
        "The `gate_post.py` run failed on q-consult/pipeline/decide.py with a "
        "Traceback, see plugins/prd-os/scripts/prd_runner.py output.\n\n---\n\n"
        "Next step is rerunning the suite."
    )
    assert _gate().extract_setoff_draft(text) == ""


def test_an_unpaired_trailing_rule_opens_no_segment():
    """Codex major on PR #217: a lone --- (signature divider, section break at
    end of message) must not turn everything after it into a "draft". The
    docstring promised this; the code did not deliver it."""
    text = ("Framing line here.\n\n---\n\n"
            + "Real prose words follow the single rule and keep going for a while now. " * 5)
    assert _gate()._hr_draft_segments(text) == []



def test_a_draft_with_prose_slashes_is_not_refused():
    """sp-a2dbef28: the \\w+/\\w+ furniture alternative refused any draft
    carrying "serve/harm", "FB/Meta", "24/7", or a t.co link. Measured against
    the live corpus 2026-08-18: 14 of 72 of the founder's REAL posts hit it --
    a fifth of his writing silently unscored. Slash-pairs are his prose."""
    text = ("Here's the post:\n\n---\n\n"
            "Day one at FB/Meta taught me the serve/harm question never sleeps. "
            "The cameras run 24/7 and someone still asks who watches them. "
            + "Real prose continues for long enough to clear the word floor here. " * 3
            + "Full story: https://t.co/Vte8fVfPfB"
            "\n\n---\n")
    draft = _gate().extract_setoff_draft(text)
    assert draft and "serve/harm" in draft and "24/7" in draft


def test_a_real_path_still_reads_as_furniture():
    """The other direction: multi-segment paths and extension-bearing files
    stay furniture, so engineering prose keeps failing to qualify."""
    g = _gate()
    assert g._FURNITURE_RE.search("see q-system/.q-system/scripts/voice-stop-gate.py")
    assert g._FURNITURE_RE.search("run `prd_runner.py gates run` first")


def test_a_multi_segment_url_is_not_furniture():
    """github.com/user/repo is a link he would paste, not a repo path."""
    g = _gate()
    assert not g._FURNITURE_RE.search("my project lives at github.com/assafkip/kipi-system now")
    # and a real multi-segment repo path still is furniture
    assert g._FURNITURE_RE.search("edit q-consult/pipeline/tests before running")


def test_a_bare_rule_never_leaks_into_scored_text():
    """The inline run must break on a --- line, not carry it as prose."""
    g = _gate()
    text = ("Here's the post:\n\n"
            + "Plain prose that reads like a post and keeps going for a while longer here. " * 4
            + "\n\n---\n\n"
            + "More prose after a divider that also keeps going for quite a while longer. " * 4)
    draft = g.extract_setoff_draft(text)
    assert "---" not in draft


def test_plain_chat_is_not_swept_even_on_a_post_shaped_turn():
    """Codex major, round 5, MEASURED before fixing: with a matching founder
    request, a 47-word conversational reply swept through the inline fallback
    AND cleared is_post_shaped -- ordinary chat scored as his draft. The
    measured 0-FP population was publish-FRAMED messages, so the inline
    fallback now requires the marker that population actually carried."""
    chat = ("Good question. The scorer only fires when the turn looks post "
            "shaped, and the counter tracks what got detected against what "
            "got surfaced. Nothing needs you until the merge ping arrives, "
            "and the whole chain runs itself once the review lands.")
    assert _gate().extract_setoff_draft(chat) == ""


def test_a_publish_framed_inline_draft_is_still_recovered():
    """The other direction: the 47-of-14034 real shape (framing, no fence)
    keeps working."""
    text = "Here's the post:\n\n" + POST
    assert "append-only ledger" in _gate().extract_setoff_draft(text)


def test_a_slash_date_does_not_disqualify_a_draft():
    """2026/08/18 is a date, not a path (Codex round 5)."""
    g = _gate()
    assert not g._FURNITURE_RE.search("On 2026/08/18 I rebuilt the corpus from scratch")


def test_unframed_hr_chat_is_not_a_draft():
    """Round 6, the design question settled on the reviewer's line: NO
    extraction path runs without the assistant's explicit handoff marker.
    An unframed ---divided status message is chat, whatever its shape."""
    text = ("Status recap after the merge went through fine today.\n\n---\n\n"
            + "Plain prose about the day that keeps going for long enough to qualify. " * 5
            + "\n\n---\n\nNext step lands tomorrow.")
    assert _gate().extract_setoff_draft(text) == ""


def test_a_framed_hr_draft_still_extracts_the_longest_segment_only():
    """The marker admits extraction; multiple qualifying bodies are not
    concatenated into a mixture -- the longest qualifying segment IS the post
    (Codex round 6: post + what-changed note scored as one text)."""
    post = "A real post paragraph that keeps going long enough to clear every floor here. " * 4
    note = "A shorter qualifying afterthought that is prose too and slips past furniture. " * 2
    text = f"Here's the post:\n\n---\n\n{post}\n\n---\n\nand also\n\n---\n\n{note}\n\n---\n"
    draft = _gate().extract_setoff_draft(text)
    assert "real post paragraph" in draft
    assert "afterthought" not in draft


def test_a_multi_label_domain_is_not_a_path():
    """www.github.com/user/repo and docs.python.org/3/library are links."""
    g = _gate()
    assert not g._FURNITURE_RE.search("see www.github.com/assafkip/kipi-system for the code")
    assert not g._FURNITURE_RE.search("read docs.python.org/3/library first")
    assert g._FURNITURE_RE.search("edit q-consult/pipeline/tests before running")


def test_mentioning_a_platform_is_not_publish_framing():
    """'posts to reddit' in ordinary prose must not read as a handoff."""
    g = _gate()
    assert not g._PUBLISH_MARKER_RE.search(
        "the pipeline posts to reddit twice a week from the queue")
    assert g._PUBLISH_MARKER_RE.search("Here's the LinkedIn post you asked for:")


def test_engineering_status_with_copy_paste_vocab_is_not_a_draft():
    """Fallback-reviewer major, round 7, their own repro shape: furniture-FREE
    status prose plus fleet vocabulary ('copy-paste' is in this repo's own
    CLAUDE.md) must not open extraction. The previous guard test passed only
    because its fixture was stuffed with furniture."""
    text = ("The migration finished and every row now carries a stable id, "
            "so the counter reports eighteen instead of thirty one and the "
            "copy-paste step is gone from the runbook entirely now.\n\n---\n\n"
            + "The gap that nobody could explain closed once the ids were stable "
              "and the recount matched the ledger on every machine we tried. " * 3
            + "\n\n---\n\nNothing else moved.")
    assert _gate().extract_setoff_draft(text) == ""


def test_heres_the_response_is_not_a_handoff():
    """'here's the response payload' is engineering prose, not a draft handoff."""
    assert not _gate()._PUBLISH_MARKER_RE.search(
        "here's the response payload from the retry, decoded")


def test_a_draft_split_by_an_internal_rule_is_scored_whole():
    """Round-7 minor: comparable-size qualifying segments are ONE post split by
    an internal divider; joining them beats silently scoring half."""
    a = "First half of the post that keeps going long enough to clear the floor. " * 3
    b = "Second half of the same post, comparable in size to the first half here. " * 3
    text = f"Here's the post:\n\n---\n\n{a}\n\n---\n\n{b}\n\n---\n"
    draft = _gate().extract_setoff_draft(text)
    assert "First half" in draft and "Second half" in draft


if __name__ == "__main__":
    # The capability gate runs this file as `python3 <file>` (runner=python3).
    # Without this block that invocation executes ZERO assertions and exits 0 --
    # a test that cannot fail (Codex major on PR #217). pytest.main returns its
    # own exit code, so a gutted feature now reds the gate.
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
