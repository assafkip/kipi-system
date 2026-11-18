"""Did every part of a check actually run? The one answer, shared by every caller.

A check is made of parts, and each part reports how many of its units ran: `ran` of `of`.
This module says what those counts mean, so no caller re-derives it:

  - ZERO: ran 0, including ran 0 of 0. The part examined nothing.
  - PARTIAL: 0 < ran < of. Some units ran, some did not.
  - EMPTY: no parts at all. Nothing was checked.

`complete` is true only with none of the three. A partial run never yields complete.

why one module: the 2026-11-06 RCA (x drafts shown after a partial voice check) counted 33
drafts shown as checked when a part had run 0, and the rule was being written per caller.
The fleet voice entry point (ASK-4969, ASK-4327) and the critic's quality wave (ASK-5411)
both need it. Two copies of this rule is how one of them drifts to fail open.

Pure and dependency-free on purpose: it ships with the public engine too.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PartRuns:
    zero: list = field(default_factory=list)      # [(name, of)]
    partial: list = field(default_factory=list)   # [(name, ran, of)]
    empty: bool = False

    @property
    def complete(self) -> bool:
        return not (self.empty or self.zero or self.partial)

    def reasons(self) -> list:
        out = ["no part ran: nothing was checked"] if self.empty else []
        out += ["part %s ran 0 of %s" % (n, of) for n, of in self.zero]
        out += ["part %s ran %s of %s" % (n, r, of) for n, r, of in self.partial]
        return out


def _count(value):
    """An int count, or None for anything else (a bool, a string, a float)."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def assess(parts) -> PartRuns:
    """`parts` maps a part name to {"ran": n, "of": m} or to a (ran, of) pair.

    A count that is missing or not an int reads as ran 0: an unreadable count must not
    pass as a part that ran."""
    if not parts:
        return PartRuns(empty=True)
    zero, partial = [], []
    for name, counts in parts.items():
        if isinstance(counts, dict):
            ran, of = counts.get("ran"), counts.get("of")
        elif isinstance(counts, (tuple, list)) and len(counts) == 2:
            ran, of = counts
        else:
            ran, of = None, None
        ran, of = _count(ran), _count(of)
        # why `of is None` is zero too (Codex P1, #839): {"ran": 1} with no total passed as
        # complete. Under engine version skew a missing total means the count is unreadable.
        if ran is None or ran <= 0 or of is None:
            zero.append((name, "?" if of is None else of))
        elif ran < of:
            partial.append((name, ran, of))
    return PartRuns(zero=zero, partial=partial)
