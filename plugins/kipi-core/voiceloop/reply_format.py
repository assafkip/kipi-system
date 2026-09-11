"""The length contract for a REPLY to someone else's thread.

## What already existed, checked before this file was written

The comment surface is NOT new here, and most of it was already built:

  `route_classifier`                       already emitted a `social-reply` surface
  `linkedin-brand/SKILL.md:102`            already defines `kind="comment"`, and the
                                           Reaction-Mode Gate at :78
  the fleet MCP linter's LinkedIn gate    already takes `kind="comment"` and correctly
                                           drops the body-link and day-of-week rules
  `.claude/rules/social-reaction-gate.md`  already governs how a reaction is drafted
  `canonical/social-writing-method.md:552` already states a FLOOR: "Comments must
                                           exceed roughly 15 words"
  `pipeline/comment.py`                    already has MIN_CHARS 30 / MAX_CHARS 320

What did NOT exist anywhere, verified 2026-08-31 by reading all six:

  - a registered PRODUCER for `social-reply` in `route_registry`
  - a linkedin/x twin of the classifier's reddit reply branch
  - **any word CEILING for a comment, on any surface, in any file**

`linkedin_gate` has no length rule for any `kind`. `comment.MAX_CHARS` is 320 and
belongs to the FIRST-COMMENT surface, the link comment under his own post, whose prompt
says "one or two sentences" -- a different artifact. The canonical 552 floor is prose
with no executable behind it.

So a 250-word comment violated NOTHING, on any of the six surfaces above. That is why
this file exists, and it is deliberately only the missing half rather than a seventh
place that restates the other six.

## The band is MEASURED

The founder's report, verbatim: "Nobody picked those numbers for a comment; the agent
guessed 250, I said too long, it guessed 110." Both were model guesses. Measured
2026-08-31 from his nine approved comments in the deployment's approved-comment corpus,
headers stripped:

    41  53  71  74  84  100  141  160  173     words

n=9, which clears the three-observation floor, so this is a claim rather than an
observation. min 41, median 84, max 173. His rejected draft was 250, above the max. The
accepted rewrite was 110, inside the band. `DEFAULT_TARGET_WORDS["linkedin"]` is 200,
above EVERY comment he has ever approved, which is the whole defect in one number.

The band widens to 35..185 rather than pinning at the observed extremes: nine samples do
not fix the true edges, and a floor set exactly at his shortest approved comment would
refuse the next one a word shorter. 35 also stays above canonical 552's roughly-15-word
floor, so the two agree instead of contradicting. The measurement is re-run by
`test_reply_lane_and_style_honesty.py` rather than trusted.

## The honest gaps

This is a LINKEDIN measurement. There is no corpus of his approved X replies, so the
same band is applied to X and that is a borrowed number. `X_BAND_IS_BORROWED` makes the
gap machine-readable instead of leaving it in this paragraph.

This file is LENGTH ONLY. It does not write anything. The reply WRITE PROMPT is social
copy and belongs to Amber (`.claude/rules/social-belongs-to-amber.md`), so the lane
currently drafts through the existing post prompt at reply length, and says so in its
trail rather than pretending otherwise.
"""
from __future__ import annotations

MIN_WORDS = 35
# 200, founder-directed 2026-09-03, verbatim: "youre trying to cut it down too much.
# a comment with 200 words is fine." It was 185, derived from the nine LinkedIn
# comments below by widening past his longest approved one. Two things that
# measurement could not see, both surfaced by a live run (sp-fae4c737):
#   - the band is applied to a reply on ANY surface, and a Reddit thread's comment
#     norm is longer than LinkedIn's. Four runs on the same material refused at
#     195, 189, 227 and 201 words, so the ceiling was the binding constraint on
#     every attempt and no draft reached him at all.
#   - the writer does not track the length of the idea it is handed, so a refusal
#     here cannot be answered by trimming the input. Trimming produced LONGER
#     output twice.
# His directive is the authority over a nine-sample inference. The numbers stay
# below so a later change faces them rather than re-arguing from memory.
MAX_WORDS = 200
DEFAULT_WORDS = 85          # the corpus median, 84, rounded

# Measured 2026-08-31. Kept as data so a later change to the band has to face the
# numbers rather than re-argue from memory (the working-files rule).
APPROVED_COMMENT_WORDS = (41, 53, 71, 74, 84, 100, 141, 160, 173)

# X gets the LinkedIn band because no X reply corpus exists. Not a measurement.
X_BAND_IS_BORROWED = True

CHANNELS = ("linkedin", "x")


def band(channel):
    """(min, max, default) for a reply on this channel."""
    if channel not in CHANNELS:
        raise ValueError(f"no reply band for channel {channel!r}")
    return MIN_WORDS, MAX_WORDS, DEFAULT_WORDS


def length_violations(text, channel):
    """Same shape as `x_format.length_violations`: a list of gate rows, never a raise."""
    low, high, _ = band(channel)
    words = len((text or "").split())
    if words < low:
        return [{"rule": "reply-too-short",
                 "detail": f"{words} words, below the {low}-word floor measured from "
                           f"his own approved comments"}]
    if words > high:
        return [{"rule": "reply-too-long",
                 "detail": f"{words} words, above the {high}-word ceiling; his longest "
                           f"approved comment is {max(APPROVED_COMMENT_WORDS)} words "
                           f"and he rejected a 250-word draft as 'way too long'"}]
    return []
