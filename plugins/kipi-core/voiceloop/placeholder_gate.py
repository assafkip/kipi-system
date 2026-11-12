#!/usr/bin/env python3
"""Refuse a post that still carries a template token. The unfilled-blank gate.

why this exists (2026-08-11, RCA rca-agent-prompt-published-as-a-post-2026-08-11): an X
post went live reading

    I have ADHD and I built [specific thing] beats any pitch I could write

`[specific thing]` came from `.q-system/agent-pipeline/agents/05-engagement-hitlist.md`,
whose creator_ops line instructs `Use first person: "I have ADHD and I built [thing]."`
The reviser restated that whole directive in the founder's voice and kept the token.

All fourteen checks in `decide._violations` passed it. Every one of them asks a lexical
or structural question -- banned words, a number, a mechanism, a client name, an ending,
a length, a price -- and an unfilled blank is none of those. The single machine-detectable
signature the defect had was the bracket, and nothing looked for one.

`case_study.unfilled_placeholders` has enforced exactly this idea since long before, and
REFUSES to render a case study with blanks left. It matches `{{...}}` only, and it was
never wired to the social path. So the check existed in this repo and the posts were
outside it.

## Negative control, run before this file was written

The founder's own corpus, because a list-based gate that fires on his real vocabulary
gets switched off within a week and then protects nothing:

    51 published bodies (output/published-text.jsonl)  -> 1 square-bracket hit
    30 banked posts     (output/post-queue.jsonl)      -> 0 hits
                                                          ---
    81 real texts, 1 hit, and the 1 hit IS the defect.

Zero curly-brace and zero angle-bracket hits across all 81. So blocking outright costs
nothing he actually writes. If that ever stops being true, the fix is a narrower pattern,
never turning this off.

## Deliberately NOT matched

A markdown link, `[label](url)`. It is wrong in a post for its own reasons (neither X nor
LinkedIn renders it), but blocking it HERE would report the wrong reason, and a gate that
misnames what it caught teaches the next reader the wrong lesson.
"""
import re

# Square brackets are the shape the agent prompts use; curly is the shape
# `case_study` already refuses. Both are template tokens and neither survives
# into finished prose.
_SQUARE = re.compile(r"\[[^\]\n]{1,60}\]")
_CURLY = re.compile(r"\{\{[^}\n]{1,60}\}\}")
_MARKDOWN_LINK = re.compile(r"\[[^\]\n]{1,60}\]\(")

# THE IOC DEFANG (ASK-4651, 2026-11-12). Run on his own long-form writing for the first
# time, this gate refused a published article on `example[.]com`: the standard
# threat-intel way to write an indicator so it cannot be clicked. The 81-text control in
# the docstring was all social posts, a genre that never defangs, so it could not see
# this. The set is the bracket forms the common defang tools write (dot, colon, at,
# scheme separator "://", and the words dot and at); `hxxp` has no bracket and never matched.
# `[colon]` and `[/]` are NOT in the set and still block (ASK-4658 F3: the comment used to
# claim every form common tools write).
# A defang sits INSIDE an indicator, so it is exempt only with non-space on both sides.
# `[at]` between spaces still reads as a blank, and that case is pinned by a test.
_DEFANG = frozenset({".", ":", "@", "://", "dot", "at"})

# THE CITATION FORMS OF A WRITTEN REPORT (ASK-4658, 2026-11-12). Same shape as the defang:
# the 81-text control was social posts, which carry none of these. Each is narrow on purpose,
# so a near-miss of each still blocks (pinned in test_placeholder_gate_citations.py):
#   a number bracket, `[1]` `[1, 2]` `[3-5]`: digits only, never a template slot.
#   an editorial word, `[sic]` `[REDACTED]`: the whole bracket, exact, any case.
#   a link definition, `[1]: https://...` at a line start: a URL must follow the colon, and only
#     the label bracket is exempt, never a bracket inside the URL tail. The label may be prose
#     (`[vendor writeup]: https://...`) but not slot-shaped.
#   a reference link, `[label][1]`: exempt ONLY when the ref is a NUMBER that `[1]: https://...`
#     defines in the same text, and the label is not slot-shaped. `[label][1]` and `[TBD][3]` are
#     the same characters, so syntax cannot separate them; two reviews of this gate found the
#     hole twice (a bare `[` after the token, then any defined ref). A closed positive shape
#     is what is left: named refs (`[text][kroll]`) are dropped because a name is as free as a
#     slot, and a slot-shaped label blocks even before a defined number.
#   SLOT-SHAPED: the label has no lowercase letter and is not plain digits (`[TBD]`, `[N]`,
#     `[CLIENT NAME]`, `[SOURCE 1]`). Residual, said plainly: a lowercase instruction label
#     directly before a number the text defines (`[paste the list][1]` with `[1]: https://...`)
#     is still read as a reference link.
_NUMBER = re.compile(r"\[\d{1,3}(?:\s*[,\-\u2013]\s*\d{1,3})*\]")
_EDITORIAL = frozenset({"sic", "redacted"})
_LINK_DEF = re.compile(
    r"^[ \t]{0,3}(\[(?P<ref>[^\]\n]{1,60})\]):[ \t]*(?:https?://|/|\./)\S+", re.M)
_REF_USE = re.compile(r"\[(\d{1,3})\]")


def _slot_shaped(label):
    return not any(c.islower() for c in label) and not label.strip().isdigit()


def _is_citation(text, match):
    inner = match.group(0)[1:-1]
    if _NUMBER.fullmatch(match.group(0)) or inner.strip().lower() in _EDITORIAL:
        return True
    ref = _REF_USE.match(text, match.end())
    if ref and not _slot_shaped(inner):
        defined = {d.group("ref").strip() for d in _LINK_DEF.finditer(text)}
        if ref.group(1) in defined:
            return True
    line_start = text.rfind("\n", 0, match.start()) + 1
    link = _LINK_DEF.match(text, line_start)
    return bool(link) and match.start() == link.start(1) and not _slot_shaped(link.group("ref"))


def _is_defang(text, match):
    if match.group(0)[1:-1].lower() not in _DEFANG:
        return False
    start, end = match.start(), match.end()
    if start == 0 or end >= len(text):
        return False
    return not text[start - 1].isspace() and not text[end].isspace()


def tokens(text):
    """Every unfilled template token in the text, in order, deduplicated."""
    if not text:
        return []
    found = []
    for match in _SQUARE.finditer(text):
        # A markdown link's bracket is a label, not a blank. See the docstring.
        if _MARKDOWN_LINK.match(text, match.start()):
            continue
        if _is_defang(text, match) or _is_citation(text, match):
            continue
        if match.group(0) not in found:
            found.append(match.group(0))
    for match in _CURLY.finditer(text):
        if match.group(0) not in found:
            found.append(match.group(0))
    return found


def check(text):
    """Violations in the gates' shape, so callers merge reports without special-casing."""
    found = tokens(text)
    if not found:
        return []
    return [{
        "rule": "unfilled-placeholder",
        "line": 1,
        # No `warn_only` key, which is what `decide.decide_candidate` reads to decide
        # blocking-vs-advisory. That absence is the enforcement; this sentence is not.
        "detail": ("the post still carries a template token: " + ", ".join(found)
                   + ". This is scaffolding from a prompt or an instruction file, not "
                     "finished text. On 2026-08-11 one shipped inside a post that was "
                     "otherwise an internal directive restated in the founder's voice."),
    }]
