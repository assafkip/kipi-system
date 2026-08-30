#!/usr/bin/env python3
"""Shared vocabulary for auto-memory file frontmatter.

One table, two readers -- `memory-confidence-validator.py` (the write-side hook)
and `memory-lint.py` (the sweep). Both import from here so the status enum and
the `as_of` date shape exist in exactly one place.

Scar this shape comes from (2026-07-28, recorded in .claude/rules/memory-confidence.md):
the `provenance` enum was hardcoded inside the validator, and three days later
`handoff-provenance-lint.py` shipped a DIFFERENT vocabulary for the same idea.
Nothing collided, because their file scopes differ, so the drift was invisible
rather than absent. `provenance_vocabulary.py` was the fix for that enum; this
module is the same fix applied to the supersession fields.

stdlib only, no side effects on import: a PostToolUse hook imports it on every
memory write.
"""
from __future__ import annotations

import datetime
import re

# --- the supersession vocabulary -------------------------------------------

# A memory that turns out to be WRONG is superseded, not deleted. Deletion stays
# reserved for a memory that was NEVER true (a mis-file, a test artifact), where
# there is no successor to point at and nothing to learn from the correction.
STATUS_VALUES = ("current", "superseded")

# Absent status is legal and means `current`. The ~100 memory files that predate
# this convention carry no status, and a convention that made them all invalid on
# day one would be a gate unsatisfiable for its own population -- which is how a
# gate gets switched off and then protects nothing.
DEFAULT_STATUS = "current"

# Fields that name another memory by its `name:` slug.
LINK_FIELDS = ("superseded_by", "supersedes")

AS_OF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def effective_status(frontmatter: dict) -> str:
    """The status to reason about, applying the grandfather default."""
    raw = (frontmatter.get("status") or "").strip()
    return raw or DEFAULT_STATUS


def as_of_date(frontmatter: dict):
    """Parse `as_of` into a date, or None if absent/unparseable.

    `as_of` means "when the claim was actually true", which is NOT the file's
    mtime: a memory rewritten for formatting today can still be as-of a fact
    verified three months ago. Callers that judge staleness must use this and
    never the filesystem timestamp.
    """
    raw = (frontmatter.get("as_of") or "").strip()
    if not AS_OF_RE.match(raw):
        return None
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        return None


def as_of_errors(frontmatter: dict) -> list:
    """Shape errors in the supersession fields. Empty list = acceptable.

    Absent fields produce NO error (grandfathering). This is the whole
    write-side contract, so the hook and the sweep agree by construction.
    """
    errors = []

    if "status" in frontmatter:
        raw = frontmatter["status"].strip()
        if raw not in STATUS_VALUES:
            errors.append(
                "status %r not in %s" % (raw, list(STATUS_VALUES)))

    if "as_of" in frontmatter:
        raw = frontmatter["as_of"].strip()
        if not AS_OF_RE.match(raw):
            errors.append(
                "as_of %r is not YYYY-MM-DD (it means WHEN THE CLAIM WAS TRUE, "
                "not when the file was written)" % raw)
        else:
            try:
                datetime.date.fromisoformat(raw)
            except ValueError:
                errors.append("as_of %r is not a real calendar date" % raw)

    # A superseded memory with no successor is a dead end: the reader learns the
    # memory is wrong and nothing about what replaced it. That is strictly worse
    # than the deletion this convention replaced, so it is refused at the write.
    if frontmatter.get("status", "").strip() == "superseded":
        target = frontmatter.get("superseded_by", "").strip()
        if not target:
            errors.append(
                "status: superseded requires superseded_by: <successor name slug> "
                "(deletion is reserved for memories that were never true)")

    for field in LINK_FIELDS:
        if field in frontmatter and not frontmatter[field].strip():
            errors.append("%s is present but empty" % field)

    return errors


def parse_frontmatter(text: str):
    """Top-level frontmatter scalars, or None when the file has no frontmatter.

    Same shape as memory-confidence-validator.parse_frontmatter: nested keys
    (`metadata:` children) are skipped on purpose -- every field this convention
    defines is top-level, and a nested reader would collide with the `name:` that
    lives under `metadata:` in some corpora.
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fm = {}
    for line in text[3:end].strip("\n").splitlines():
        if not line or line[0].isspace() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        fm[key.strip()] = val.strip().strip('"').strip("'")
    return fm


if __name__ == "__main__":
    print("status values : %s (absent = %s)" % (
        ", ".join(STATUS_VALUES), DEFAULT_STATUS))
    print("as_of format  : YYYY-MM-DD, meaning when the claim was true")
    print("link fields   : %s" % ", ".join(LINK_FIELDS))
