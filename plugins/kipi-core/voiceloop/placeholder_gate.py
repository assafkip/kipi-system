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


def tokens(text):
    """Every unfilled template token in the text, in order, deduplicated."""
    if not text:
        return []
    found = []
    for match in _SQUARE.finditer(text):
        # A markdown link's bracket is a label, not a blank. See the docstring.
        if _MARKDOWN_LINK.match(text, match.start()):
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
