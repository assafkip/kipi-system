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


class Voice:
    """Everything one voice/ dir holds, read once, with decay counts."""

    def __init__(self, voice_dir):
        self.voice_dir = voice_dir
        self.exemplars, ex_skipped = read_jsonl(os.path.join(voice_dir, EXEMPLARS))
        self.corrections, co_skipped = read_jsonl(os.path.join(voice_dir, CORRECTIONS))
        self.identity = read_text(os.path.join(voice_dir, IDENTITY))
        self.pov = read_text(os.path.join(voice_dir, POV))
        self.lexicon = read_json(os.path.join(voice_dir, LEXICON)) or {}
        self.fingerprint = read_json(os.path.join(voice_dir, FINGERPRINT))
        self.skipped_rows = ex_skipped + co_skipped

    def active_exemplars(self):
        """Usable rows only: active status, non-empty text, weight above zero."""
        return [r for r in self.exemplars
                if r.get("status", "active") == "active"
                and (r.get("text") or "").strip()
                and float(r.get("weight", 1.0) or 0) > 0]

    def active_corrections(self):
        """Rows still carried as prose. A `promoted` row's gate carries it instead."""
        return [r for r in self.corrections
                if r.get("status") == "active"
                and (r.get("instruction") or "").strip()]


def load(voice_dir):
    """The one entry point. Never raises on a readable-or-absent tree."""
    return Voice(voice_dir)
