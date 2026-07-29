#!/usr/bin/env python3
"""provenance_vocabulary: the ONE table both provenance validators read.

WHY (PRD prd-deterministic-reading-2026-07-28 Part C, the only part of that PRD to
survive three adversarial Codex rounds): `memory-confidence-validator.py`
hardcoded a six-value provenance enum. Three days later `handoff-provenance-lint.py`
shipped a DIFFERENT vocabulary for the same idea. Nothing collided, because their
file scopes differ, so the drift was invisible rather than absent. Two words for
one thing in one repo is the drift class this repo writes rules against.

The values live in `provenance-vocabulary.json` next to this file, not in Python,
so adding one is a data change in a single place. Same reason the client's own QA
validator loads its nickname map from a table at runtime and says so in a comment.

Precedence answers the round-2 review finding that only `ev-<id>` versus
everything else was defined: every accepted form now has a rank, so any pair has a
winner, and callers can report the pair instead of silently picking.

HONEST BOUNDARY: this decides which marker a line CARRIES and which of two wins.
It cannot tell whether the marker is true. `provenance: validated` on a line
nobody checked passes here and proves nothing. What it removes is ambiguity about
which kind of claim is being made, not the ability to lie.

Self-test: `python3 test_provenance_vocabulary.py`. stdlib only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

TABLE_PATH = Path(__file__).resolve().parent / "provenance-vocabulary.json"

_TABLE = json.loads(TABLE_PATH.read_text(encoding="utf-8"))

CLAIM_ID_RE = re.compile(_TABLE["claim_id"]["pattern"])
CLAIM_ID_RANK = int(_TABLE["claim_id"]["rank"])

#: The enum, identical to the one `.claude/rules/memory-confidence.md` documents.
PROVENANCE = set(_TABLE["provenance"])

#: marker text -> rank, for the enum forms and their shorthand aliases.
_ALIASES = dict(_TABLE.get("aliases", {}))

_PROV_RE = re.compile(r"provenance:\s*([a-z_]+)", re.IGNORECASE)


def enum_rank(value: str):
    """Rank of a bare enum value, or None if it is not in the table."""
    entry = _TABLE["provenance"].get(str(value).strip().lower())
    return int(entry["rank"]) if entry else None


def _markers(line: str):
    """Every recognised provenance marker in `line`, as (text, rank) pairs."""
    found = []
    for m in CLAIM_ID_RE.finditer(line):
        found.append((m.group(0), CLAIM_ID_RANK))
    for m in _PROV_RE.finditer(line):
        r = enum_rank(m.group(1))
        if r is not None:  # a typo'd value must not satisfy the requirement
            found.append((f"provenance: {m.group(1).strip().lower()}", r))
    for alias, target in _ALIASES.items():
        if alias in line:
            r = enum_rank(target)
            if r is not None:
                found.append((alias, r))
    return found


def rank(line: str):
    """The rank of the strongest marker in `line`, or None if it carries none."""
    found = _markers(line)
    return max(r for _, r in found) if found else None


def strongest(line: str):
    """(winning marker text, every marker seen) for `line`.

    Returns (None, []) when the line carries no provenance. Callers report the
    full list so a downgrade is visible rather than silently resolved.
    """
    found = _markers(line)
    if not found:
        return None, []
    winner = max(found, key=lambda pair: pair[1])
    return winner[0], [text for text, _ in found]


def has_provenance(line: str) -> bool:
    return rank(line) is not None


def accepted_forms() -> list[str]:
    """Human-readable list for a gate's stderr, strongest first."""
    out = [f"ev-<id>  (rank {CLAIM_ID_RANK}, strongest: points at an evidence.jsonl row)"]
    for value, entry in sorted(_TABLE["provenance"].items(),
                               key=lambda kv: -int(kv[1]["rank"])):
        out.append(f"provenance: {value}  (rank {entry['rank']}: {entry['means']})")
    for alias, target in _ALIASES.items():
        out.append(f"{alias}  (alias for provenance: {target})")
    return out


if __name__ == "__main__":
    print(f"table: {TABLE_PATH}")
    for line in accepted_forms():
        print("  " + line)
