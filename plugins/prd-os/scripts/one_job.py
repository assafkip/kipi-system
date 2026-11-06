#!/usr/bin/env python3
"""One deliverable PR per job: the deterministic detector (ASK-2541).

Single source for two callers, so the rule cannot drift between them:
  - prd_split.py refuses a manifest entry or Linear DoR that names more than
    one PR / branch / deliverable job.
  - q-system/.q-system/scripts/agent-brief-one-job-guard.py (PreToolUse on
    the Agent tool) flags a brief that asks one agent for more than one PR.

why: RCA token-burn-recurs-after-gate-2026-10-06, root cause #4. "Fresh agent
per task" was followed as "fresh agent per brief", and one brief bundled five
jobs (three PRs, a dry run, a review loop). Every waiting turn of that agent
re-read about 180k tokens of context: 57 turns, 10.3M cached tokens read for
6.4k tokens of output. A spec or brief that carries one PR keeps the context
small and the wait cheap.

What it reads, and what it does not:
  - ordinal PR labels ("PR 1", "PR 2", "PR-A", "PR B"): two or more DISTINCT
    labels mean more than one PR. A real PR number ("PR #233", "PR 233") is a
    reference, never a label, so it does not count.
  - a counted plural ("three PRs", "two small PRs", "separate branches").
  - a per-item PR ("a PR each", "each fix in its own PR", "split it into PRs").
  - for a manifest entry, two or more deliverables that each name a PR/branch.
It cannot tell a request from a quotation: a brief that DESCRIBES an old
"three PRs" scar reads the same as one that asks for three. That is measured,
not argued; see the guard's docstring for the hit rate on real briefs.
"""
from __future__ import annotations

import re

_COUNT_WORDS = (
    r"two|three|four|five|six|seven|eight|nine|ten|[2-9]|several|multiple|separate"
)

# "PR 1", "PR-2", "PR A", "PRs A and B" is handled by the count rule instead.
# Case-sensitive on purpose: "pr" in prose ("pr-review-agent") is a tool name.
# The lookahead refuses "PR 1234" (a real PR number) and "PR A." is fine.
_LABEL_RE = re.compile(r"\bPR[ -]?([1-9]|[A-H])(?![\w#/])")

# A count alone is usually a description ("three PRs merged green today",
# "acted on only 9 PRs"). Measured on real briefs, the request shape always
# had a verb or a preposition of making right before it: "split it into two
# PRs", "ship as two separate PRs", "open three PRs".
_COUNTED_RE = re.compile(
    r"\b(?:open|ship|land|cut|raise|make|create|build|deliver|into|as|in)\s+"
    r"(?:the\s+|these\s+)?"
    rf"(?:{_COUNT_WORDS})\s+(?:[a-z][a-z-]*\s+){{0,2}}?"
    r"(?:PRs|pull requests|branches)\b",
    re.I,
)

# A sibling label named only to fence it off ("build exactly PR-A, nothing
# from PR-B..F", "another agent is merging PR-C") is not a second job. Measured:
# 6 of 7 label hits on real single-PR briefs were this shape.
_FENCE_RE = re.compile(
    r"(?:nothing from|not\b|never\b|don't|do not|another agent|other agents?|"
    r"is merged|merged|already|previous agent)[^.\n]{0,80}$"
    r"|\b(?:from|where|holds)\s*\W?$",
    re.I,
)
# ...and the same fence written AFTER the label: "PR-A is merged (chief #82)",
# "PR-B (#83) and PR-C/D are being built in parallel by other agents".
_FENCE_AFTER_RE = re.compile(
    r"^\W{0,3}(?:\s*(?:is|was|are|and|/\w|\(#\d+\)))*\s*"
    r"(?:is merged|merged|landed|lands|fixed|are being built|being built|\(#\d)",
    re.I,
)


def _is_fenced(text: str, start: int, end: int) -> bool:
    return bool(
        _FENCE_RE.search(text[max(0, start - 100):start])
        or _FENCE_AFTER_RE.search(text[end:end + 60])
    )

_PER_ITEM_RES = (
    re.compile(r"\b(?:a|one)\s+(?:PR|pull request|branch)\s+each\b", re.I),
    re.compile(
        r"\beach\b[^.\n]{0,60}?\b(?:in|as|on|gets?)\s+its own\s+"
        r"(?:PR|pull request|branch)\b",
        re.I,
    ),
    re.compile(
        r"\bseparate\s+(?:PR|pull request|branch)\s+(?:for|per)\s+each\b", re.I
    ),
    re.compile(
        r"\bsplit\b[^.\n]{0,60}?\binto\b[^.\n]{0,30}?\b(?:PRs|pull requests)\b",
        re.I,
    ),
)

_DELIVERABLE_PR_RE = re.compile(r"\b(?:PR|pull request|branch)\b", re.I)

SPLIT_HOWTO = (
    "Split it: one PR per spec, one job per agent. Give each PR its own "
    "manifest entry (prd_split) or its own Linear issue (--from-linear), and "
    "launch one agent per PR. A dry run or a review loop is its own job too."
)


def multi_pr_reasons(text: str) -> list[str]:
    """Why `text` asks for more than one PR. Empty list means one job."""
    if not text:
        return []
    reasons: list[str] = []
    labels = sorted({
        m.group(1).upper()
        for m in _LABEL_RE.finditer(text)
        if not _is_fenced(text, m.start(), m.end())
    })
    if len(labels) >= 2:
        reasons.append(
            "names %d distinct PR labels (%s)"
            % (len(labels), ", ".join("PR " + x for x in labels))
        )
    counted = _COUNTED_RE.search(text)
    if counted:
        reasons.append(f"asks for a counted plural: {counted.group(0)!r}")
    for rx in _PER_ITEM_RES:
        m = rx.search(text)
        if m:
            reasons.append(f"asks for a PR per item: {m.group(0)!r}")
            break
    return reasons


def multi_pr_deliverables(deliverables: list[str]) -> list[str]:
    """Deliverables that each name a PR or branch. Two or more is two PRs."""
    named = [d for d in deliverables if _DELIVERABLE_PR_RE.search(d)]
    return named if len(named) >= 2 else []
