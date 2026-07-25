#!/usr/bin/env python3
"""Fingerprint semantic leak findings so a baseline stays a real statement.

Pairs with q-system/.q-system/scripts/test/test-propagation-leak-gate.py.

A baseline is an allowlist over content that is already known and accepted. Two
properties make it honest, and both are easy to get wrong:

- Key on the offending line's CONTENT, not its line number. Reformatting a file
  must not churn the baseline, or the baseline gets regenerated so often that
  nobody reads the diff.
- Carry the OCCURRENCE COUNT. A bare set of fingerprints is a permanent replay
  permit: bless one `- Client: Northwind` and the same line can be pasted a
  second time, or deleted and reintroduced months later, without ever
  registering as new.

This module owns only the fingerprint algebra. Scanning sources, reading the
baseline file, and wiring the gate into the propagation entry points are
separate issues (pff-dereferenced-sources, pff-baseline-provenance,
pff-baseline-lifecycle, pff-updater-preflight, pff-all-propagation-entrypoints).
"""

from __future__ import annotations

import hashlib


def normalize_line(text: str) -> str:
    """The asserted text, with line endings and surrounding space removed."""
    return text.replace("\r\n", "\n").strip()


def indent_bucket(text: str) -> str:
    """"top" for an unindented line, "nested" for any indented one.

    Indentation cannot be discarded outright: an indented
    `- Client: Northwind` inside a fenced example is not the same thing as the
    same line asserted at top level, and hashing them together lets a baseline
    for the example bless the assertion. Nor can the exact width be kept, or
    re-indenting two spaces would churn the baseline. Bucketing keeps the
    distinction that carries meaning and drops the one that does not.
    """
    stripped = text.replace("\r\n", "\n").lstrip("\n")
    return "nested" if stripped[:1].isspace() else "top"


def fingerprint(finding: dict) -> tuple:
    """(path, fact_class, indent bucket, sha256 of the offending line).

    The finding must carry its own text. Re-reading the line from disk here
    would fingerprint whatever is at that line NOW, which is not necessarily
    the line the classifier judged.
    """
    text = finding.get("text")
    if not isinstance(text, str):
        raise ValueError(
            f"finding for {finding.get('path')!r} carries no text to fingerprint"
        )
    path = finding.get("path")
    fact_class = finding.get("fact_class")
    if not isinstance(path, str) or not path:
        raise ValueError("finding carries no path")
    if not isinstance(fact_class, str) or not fact_class:
        raise ValueError(f"finding for {path!r} carries no fact_class")
    digest = hashlib.sha256(normalize_line(text).encode("utf-8")).hexdigest()
    return (path, fact_class, indent_bucket(text), digest)


def fingerprint_findings(findings) -> dict:
    """{fingerprint: occurrence count}."""
    counts: dict = {}
    for finding in findings:
        key = fingerprint(finding)
        counts[key] = counts.get(key, 0) + 1
    return counts


def new_findings(baseline: dict, current: dict) -> list:
    """Everything in `current` the baseline does not already account for.

    An increased count is an addition too: one blessed occurrence does not
    bless the second one.
    """
    additions = []
    for key in sorted(current):
        allowed = baseline.get(key, 0)
        found = current[key]
        if found > allowed:
            path, fact_class, indent, digest = key
            additions.append(
                {
                    "path": path,
                    "fact_class": fact_class,
                    "indent": indent,
                    "line_sha256": digest,
                    "baseline_count": allowed,
                    "current_count": found,
                    "count_delta": found - allowed,
                }
            )
    return additions


def prune_baseline(baseline: dict, current: dict) -> dict:
    """Drop permits for content that is gone, and lower ones that shrank.

    Without this a retired fingerprint parks in the baseline forever and
    silently re-authorizes the same line when it comes back.
    """
    pruned = {}
    for key, allowed in baseline.items():
        found = current.get(key, 0)
        if found > 0:
            pruned[key] = min(allowed, found)
    return pruned


def baseline_delta(baseline: dict, current: dict) -> dict:
    """Adds and removals reported separately.

    One combined number lets an unrelated real leak ride along with expected
    classifier churn during a re-baseline.
    """
    return {
        "added": new_findings(baseline, current),
        "removed": [
            {
                "path": key[0],
                "fact_class": key[1],
                "indent": key[2],
                "line_sha256": key[3],
                "baseline_count": allowed,
                "current_count": current.get(key, 0),
            }
            for key, allowed in sorted(baseline.items())
            if current.get(key, 0) < allowed
        ],
    }
