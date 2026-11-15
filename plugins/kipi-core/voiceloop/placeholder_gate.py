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
import bisect
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

# A MARKDOWN TASK BOX (ASK-4945, 2026-11-14). A written plan refused on `[ ]` from task lines
# like `- [ ] the client runs the morning routine`. The box is a checklist mark, not a slot.
# Exempt ONLY as the first thing in a list item (bullet `-*+` or `1.` `1)`, then space, then
# `[ ]` `[x]` `[X]`, then space or end of line). A box in prose, after the item text, or
# glued to a word still blocks, and so does any other token on the same line.
# A list inside a blockquote (`> - [ ] step`, `>> 1. [x] done`) is the same list (ASK-4984):
# any run of `>` markers may come first. `> [ ]` with no bullet is prose and still blocks.
# No `^`: _is_task_box calls match() at the line start, so an anchor here was inert and a
# mutant dropping it survived review (ASK-4995 nit).
_TASK_BOX = re.compile(
    r"[ \t]*(?:>[ \t]*)*(?:[-*+]|\d{1,9}[.)])[ \t]+(\[[ xX]\])(?=[ \t\r]|$)", re.M)


# CODE AND QUOTED EXAMPLES (ASK-4900, 2026-11-14). Run on written reports, this row refused
# a JSON array in a fenced MCP config (`["-y", "@scope/server"]`), `[player]` inside a quoted
# scam message, and a bracket inside a quoted seller listing. None is a template slot: code is
# literal, and a quote is someone else's words held as evidence. A token whose bracket starts
# inside a closed fence, closed inline code, or a closed double quote is skipped.
# Each span must CLOSE, because one stray mark must not switch the gate off: an unclosed or
# refused fence exempts nothing, inline or fenced, and an odd count of backtick runs in a
# paragraph pairs none of them (see _inline_code_spans, and its residuals: a stray used to
# pair with the NEXT code span's opener, ASK-4922, ASK-4995). A quote cannot cross a blank
# line (LF or CRLF), and a double
# quote right after a digit neither opens nor closes one (so the inch mark in `55"` is not a
# quote; PR 810 review round 1 found it could still CLOSE one and blank a paragraph). Curly
# double quotes are read as straight ones first, so both obey the same open and close rules
# (round 2 found the curly path had none, and autocorrect turns `55"` into a curly close).
# Pinned in test_placeholder_gate_code_and_quotes.py.
# Residuals, said plainly: single quotes are not treated as quotes (an apostrophe cannot be
# told from one), a `>` blockquote is not exempt, and a template token kept INSIDE closed code
# or double quotes now passes. So a draft wrapped in a fence or in quotes, with or without a
# lead-in line, is not checked inside that span. That includes the quoted creator_ops
# directive at the top of this module, the source of the 2026-08-11 scar, if a reviser
# restates it with its quote marks; only the published shape, which dropped them, still
# blocks. A whole-body guard was tried in round 1 and dropped in round 2: one lead-in word
# defeated it, so it read as coverage it did not give.
# `post_repair._protected_spans` has its own idea of code, read from the linter's regexes.
# This parser is separate because that linter lives outside this package.
_FENCE = re.compile(r"[ \t]{0,3}(`{3,}|~{3,})")
_PARA = r"(?:[^\n{stop}]|\n(?![ \t\r]*\n))"
_BACKTICKS = re.compile(r"`+")
# A paragraph ends at a blank line (LF or CRLF), and a table row at a newline before a pipe.
_SEGMENT_BREAK = re.compile(r"\n[ \t\r]*\n|\n(?=[ \t]*\|)")
_STRAIGHT_QUOTE = re.compile(
    r'(?<![^\s(\[{:;,/\u2013\u2014-])"(?=[^\s"])' + _PARA.format(stop='"')
    + r'+(?<=[^\s\d])"(?![^\s.,;:!?)\]}\u2019\u2013\u2014-])')


def _fenced_spans(text):
    spans, open_at, fence, pos = [], None, None, 0
    for line in text.splitlines(keepends=True):
        mark = _FENCE.match(line)
        if mark and open_at is None:
            open_at, fence = pos, mark.group(1)
        elif (mark and mark.group(1)[0] == fence[0] and len(mark.group(1)) >= len(fence)
              and not line[mark.end():].strip()):
            spans.append((open_at, pos + len(line)))
            open_at = None
        pos += len(line)
    return spans


def _is_fence_marker(text, run):
    # A run of three or more at a line start is a fence, never inline code. Closed fences are
    # already blanked by the time this runs, so one that is left was refused by
    # _fenced_spans, and a refused fence must not come back as an inline span (ASK-4984).
    line_start = text.rfind("\n", 0, run.start()) + 1
    return len(run.group(0)) >= 3 and _FENCE.fullmatch(text, line_start, run.end()) is not None


def _inline_code_spans(text):
    # THE STRAY BACKTICK, BY PARITY (ASK-4995, ASK-4984, 2026-11-15). ASK-4922 found a stray
    # backtick pairing with the NEXT span's opener and exempting the prose between, a real
    # `[CLIENT NAME]` included. PR 818 answered with a one-character test on each side of a
    # candidate closer. Three review rounds retuned that window, and each round left a residual
    # on both sides: a next span starting with punctuation (`--fast`, `.env`) still let the
    # stray through, and real code ending in a space or `([|=:` with a letter glued after it
    # (`grep [x] |`s) stopped being code. A window that small cannot tell a closer from the
    # next opener, so this counts instead of guessing.
    # Inside one paragraph or one table row, runs of one width pair in order, first with
    # second. An odd count of that width means one run is stray and nothing says which, so
    # NONE of that width pairs there and every token in the segment stays visible. Widths go
    # widest first, and each formed span is blanked before the next width is counted, so a
    # single tick inside a double-tick span is not a run of its own.
    # Residuals, said plainly: two strays in one segment are an even count and pair with each
    # other, and a lone tick that closes a pair (`run the `deploy for [CLIENT NAME] then ``)
    # is read as a closer. The opener's position is never checked, because a padded opener
    # (`` [draft] ``) is real code.
    breaks = [m.start() for m in _SEGMENT_BREAK.finditer(text)]
    widths = sorted({len(m.group(0)) for m in _BACKTICKS.finditer(text)}, reverse=True)
    spans = []
    for width in widths:
        by_segment = {}
        for run in _BACKTICKS.finditer(text):
            if len(run.group(0)) == width and not _is_fence_marker(text, run):
                by_segment.setdefault(bisect.bisect(breaks, run.start()), []).append(run)
        formed = []
        for runs in by_segment.values():
            if len(runs) % 2:
                continue
            formed += [(runs[k].start(), runs[k + 1].end()) for k in range(0, len(runs), 2)]
        spans += formed
        text = _blank(text, formed)
    return spans


def _blank(text, spans):
    # Same length and the same newlines, so offsets in the copy are offsets in the text.
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


def _exempt_spans(text):
    spans = _fenced_spans(text)
    # Find inline code with fences blanked, then quotes with all code blanked, so a backtick
    # inside a fence or a quote mark inside code never opens a span of its own.
    without_fences = _blank(text, spans)
    spans += _inline_code_spans(without_fences)
    # One code point for one, so offsets still line up with the text.
    without_code = _blank(text, spans).replace("\u201c", '"').replace("\u201d", '"')
    spans += [m.span() for m in _STRAIGHT_QUOTE.finditer(without_code)]
    return spans


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


def _is_task_box(text, match):
    line_start = text.rfind("\n", 0, match.start()) + 1
    box = _TASK_BOX.match(text, line_start)
    return bool(box) and match.start() == box.start(1)


# GMAIL'S INLINE IMAGE (ASK-5198, 2026-11-15). Gmail writes `[image: <name>]` in the plain
# text where a pasted screenshot or a signature icon sits (`[image: Screen Shot ... .png]`,
# `[image: linkedin]`). On the sent-mail census that shape alone refused 18 of his 59 real
# emails. Exempt only Gmail's exact shape: `image:`, one space, then a label that is not
# slot-shaped, so `[image: CLIENT LOGO]` (a template asking for an image) still blocks.
_GMAIL_IMAGE = re.compile(r"\[image: (?P<label>[^\]\n]*\S[^\]\n]*)\]")


def _is_gmail_image(match):
    image = _GMAIL_IMAGE.fullmatch(match.group(0))
    return bool(image) and not _slot_shaped(image.group("label"))


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
    exempt = _exempt_spans(text)

    def in_code_or_quote(match):
        return any(start <= match.start() < end for start, end in exempt)

    for match in _SQUARE.finditer(text):
        # A markdown link's bracket is a label, not a blank. See the docstring.
        if _MARKDOWN_LINK.match(text, match.start()):
            continue
        if _is_task_box(text, match) or _is_defang(text, match) or _is_citation(text, match) \
                or _is_gmail_image(match) or in_code_or_quote(match):
            continue
        if match.group(0) not in found:
            found.append(match.group(0))
    for match in _CURLY.finditer(text):
        if in_code_or_quote(match):
            continue
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
