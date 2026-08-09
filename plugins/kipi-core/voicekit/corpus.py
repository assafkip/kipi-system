#!/usr/bin/env python3
"""Read a founder's voice/ directory. Degrade, never die.

The daily job that consumes this runs unattended in launchd. The contract, paid
for by ASK-461 and its cousins: a missing file is LESS GUIDANCE, a corrupt JSONL
row is SKIPPED AND COUNTED, and nothing on this read path raises. The counts ride
back to the caller so a deadman check can surface decay instead of a crash hiding
it. Loud failure belongs to the VALIDATOR (validate.py), which runs in a pytest
suite at edit time, not inside the publishing run.
"""
from __future__ import annotations

import json
import os

EXEMPLARS = "exemplars.jsonl"
CORRECTIONS = "corrections.jsonl"
IDENTITY = "identity.md"
POV = "pov.md"
LEXICON = "lexicon.json"
FINGERPRINT = "fingerprint.json"

EXEMPLAR_KINDS = ("post", "article-excerpt", "comment", "dm", "email")
EXEMPLAR_CHANNELS = ("linkedin", "x", "substack", "medium", "any")


def read_jsonl(path):
    """(rows, skipped_count). Missing file = ([], 0): absence is a fact, not an error."""
    if not os.path.exists(path):
        return [], 0
    rows, skipped = [], 0
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    skipped += 1       # a torn row loses ITS row, never the file
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                else:
                    skipped += 1
    except OSError:
        return [], 0
    return rows, skipped


def read_text(path):
    """File content, or '' when missing/unreadable. Same errors= as the old loader:
    a plugin update writing while we read must not kill the run on one bad byte."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def read_json(path):
    """Parsed JSON dict, or None. None means the consumer runs without this input."""
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        return loaded if isinstance(loaded, dict) else None
    except (OSError, ValueError):
        return None


def _weight(row):
    """A row's weight as a number, or None when the field is not a number
    (ASK-508, sp-18daaa21 + the codex minor on PR #127).

    read_jsonl only guarantees the LINE parsed, never that a numeric field holds a
    number -- so `{"weight": "heavy"}` is valid JSON, is counted as no skip, and
    reached a bare float() that raised ValueError from inside active_exemplars().
    That walked straight past the degrade-without-dying boundary this loader
    exists to hold: one junk field in one row took down every other row with it.
    Unreadable weight means unusable row, which is what a zero already means here.
    """
    try:
        return float(row.get("weight", 1.0) or 0)
    except (TypeError, ValueError):
        return None


def _drop_malformed_weights(rows):
    """(usable rows, count dropped). Partitioned at LOAD, never in a filter.

    The first cut of the crash fix coerced a junk weight to 0.0 inside
    active_exemplars() and said nothing, so the row vanished and skipped_rows --
    the deadman signal validation and provenance read -- stayed clean. A corpus
    rotting to zero usable rows would have looked identical to a healthy one.

    Counted HERE because __init__ is the single owner of skipped_rows. Doing it
    in active_exemplars() would make a read path mutate the decay count, so the
    number would change depending on how many times a caller happened to filter.
    """
    usable, dropped = [], 0
    for row in rows:
        if _weight(row) is None:
            dropped += 1
        else:
            usable.append(row)
    return usable, dropped


class Voice:
    """Everything one voice/ dir holds, read once, with decay counts."""

    def __init__(self, voice_dir):
        self.voice_dir = voice_dir
        self.exemplars, ex_skipped = read_jsonl(os.path.join(voice_dir, EXEMPLARS))
        self.exemplars, wt_skipped = _drop_malformed_weights(self.exemplars)
        self.corrections, co_skipped = read_jsonl(os.path.join(voice_dir, CORRECTIONS))
        self.identity = read_text(os.path.join(voice_dir, IDENTITY))
        self.pov = read_text(os.path.join(voice_dir, POV))
        self.lexicon = read_json(os.path.join(voice_dir, LEXICON)) or {}
        self.fingerprint = read_json(os.path.join(voice_dir, FINGERPRINT))
        self.skipped_rows = ex_skipped + co_skipped + wt_skipped

    def active_exemplars(self):
        """Usable rows only: active status, non-empty text, weight above zero."""
        return [r for r in self.exemplars
                if r.get("status", "active") == "active"
                and (r.get("text") or "").strip()
                and (_weight(r) or 0) > 0]

    def active_corrections(self):
        """Rows still carried as prose. A `promoted` row's gate carries it instead."""
        return [r for r in self.corrections
                if r.get("status") == "active"
                and (r.get("instruction") or "").strip()]


def load(voice_dir):
    """The one entry point. Never raises on a readable-or-absent tree."""
    return Voice(voice_dir)
