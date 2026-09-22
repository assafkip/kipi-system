#!/usr/bin/env python3
"""unknown_terms.py -- the "Terms I do not know" section of the morning brief.

Plan item 2c of prd-morning-brief-learns-2026-09-01: a context-gap detector.
Registered in morning-brief.py's OPTIONAL_SECTIONS as ("unknown_terms",
"unknown_terms", "Terms I do not know"); the brief loads this module by name
and calls `collect(now, sources)` behind its guard. This file never edits the
brief and never pulls anything: it reads the calendar and mail ROWS the brief
already fetched (a second pull is the defect the registry exists to avoid).

Why the normalization is long (Codex finding-13 on the PRD): a naive
"capitalized word not in canonical" detector fills its five slots with
sentence starts, attendee names, email senders and signature lines, and the
section becomes noise the founder learns to skip. So, before the diff against
the canonical vocabulary, this drops:

- the attendee list on a calendar row (the parenthesised names) and the sender
  field on a mail row (people are not terms);
- a capitalized word that appears ONLY at the start of a title or subject
  (sentence-initial capitalisation is grammar, not a name), unless it recurs
  mid-sentence somewhere else in today's rows;
- signature blocks (anything after a line that is only `--` or starts with
  `Sent from`), for callers that pass raw bodies via `texts=`;
- a stopword list (weekdays, months, common English, common mail words);
- anything already present anywhere under q-system/canonical/.

Precision is a measured property, not a hope: test_unknown_terms.py plants 5
unknowns and 10 decoys and requires at least 4 of 5 with 0 decoys. Cap is 5.
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
QROOT = HERE.parent.parent
CANONICAL_DIR = QROOT / "canonical"
CAP = 5

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-']*")
_CAPITALIZED = re.compile(r"\b([A-Z][a-zA-Z0-9\-']{2,})\b")
_PAREN = re.compile(r"\([^)]*\)")
_SIGNATURE = re.compile(r"^(--\s*$|sent from )", re.IGNORECASE)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

STOPWORDS = frozenset("""
monday tuesday wednesday thursday friday saturday sunday january february march
april may june july august september october november december today tomorrow
yesterday the and for with from this that these those your our their his her its
you are was were will would could should have has had not but new old re fwd fw
meeting call sync standup review update updates invoice reminder urgent action
required please thanks thank hello hi hey dear regards best team week weekly
daily monthly quarterly q1 q2 q3 q4 am pm est pst pdt utc zoom google meet slack
email mail draft drafts follow up followup intro introduction question quick
notes note agenda minutes sent via mobile iphone android outlook gmail
""".split())


def _canonical_vocab(canonical_dir=None) -> set:
    root = Path(canonical_dir) if canonical_dir else CANONICAL_DIR
    vocab: set = set()
    if not root.is_dir():
        return vocab
    # rglob, not glob: "present anywhere under canonical/" includes nested
    # directories (both Codex reviewers on this issue, 2026-09-01).
    for path in sorted(root.rglob("*.md")):
        try:
            vocab.update(w.lower() for w in _WORD.findall(path.read_text(encoding="utf-8")))
        except OSError:
            continue
    return vocab


def _strip_signature(text: str) -> str:
    kept = []
    for line in text.splitlines():
        if _SIGNATURE.match(line.strip()):
            break
        if _GREETING.match(line):
            continue  # a greeting line names a person, never a term
        kept.append(line)
    return "\n".join(kept)


def _calendar_fragment(row: str) -> str:
    """'09:00  Title (alice, bob)' -> 'Title'. Attendees are not terms."""
    parts = row.split("  ", 1)
    body = parts[1] if len(parts) == 2 else row
    return _PAREN.sub(" ", body)


def _mail_fragment(row: str) -> str:
    """'Sender Name  Subject (2h)' -> 'Subject'. The sender is not a term."""
    parts = row.split("  ", 1)
    body = parts[1] if len(parts) == 2 else ""
    return _PAREN.sub(" ", body)


# Sentence boundaries: terminal punctuation or a line break. NOT a colon: in
# "Introduction: Quillfeather pilot" the word after the colon is a
# continuation, and splitting there dropped a planted unknown (measured).
_SENTENCE_SPLIT = re.compile(r"(?:[.!?]+\s+|\n+)")
_GREETING = re.compile(r"^\s*(hi|hey|hello|dear|good (morning|afternoon|evening))\b", re.IGNORECASE)


def candidate_terms(fragments: list) -> list:
    """Capitalized tokens, minus sentence-initial ones that never recur.

    "Sentence-initial" is judged per SENTENCE, not per fragment (both Codex
    reviewers on this issue): a fragment is split on sentence punctuation and
    line breaks first, so "We discussed it. Question remains" drops both
    "We" and "Question" unless one of them recurs mid-sentence elsewhere."""
    initial, elsewhere = set(), set()
    order: list = []
    for frag in fragments:
        frag = _EMAIL.sub(" ", frag)
        for sentence in _SENTENCE_SPLIT.split(frag):
            sentence = sentence.strip()
            words = _CAPITALIZED.findall(sentence)
            if not words:
                continue
            first_token = _WORD.match(sentence)
            first = first_token.group(0) if first_token else ""
            for w in words:
                if w.isupper() and len(w) <= 4:
                    continue  # SOW, CRM, API: an acronym is jargon, not a context gap
                if w == first and sentence.startswith(w):
                    initial.add(w)
                else:
                    elsewhere.add(w)
                if w not in order:
                    order.append(w)
    return [w for w in order if w in elsewhere]


def unknown_terms(fragments: list, canonical_dir=None, cap: int = CAP) -> list:
    vocab = _canonical_vocab(canonical_dir)
    out = []
    for term in candidate_terms(fragments):
        low = term.lower()
        if low in STOPWORDS or low in vocab or low.rstrip("s") in vocab:
            continue
        if term not in out:
            out.append(term)
        if len(out) >= cap:
            break
    return out


def collect(now, sources: dict, canonical_dir=None, texts=None):
    """(rows, error). The registry contract. `sources` is the brief's dict of
    key -> (rows, error) for the fixed four; `texts` is an optional list of raw
    bodies (signature-stripped here) for callers that have them."""
    missing = [k for k in ("calendar", "mail") if k not in sources]
    if missing:
        return [], f"inputs not collected: {', '.join(missing)}"
    fragments: list = []
    cal_rows, cal_err = sources["calendar"]
    mail_rows, mail_err = sources["mail"]
    if cal_err and mail_err:
        return [], "calendar and mail both unreadable; nothing to scan"
    if not cal_err:
        fragments += [_calendar_fragment(r) for r in cal_rows]
    if not mail_err:
        fragments += [_mail_fragment(r) for r in mail_rows]
    for text in texts or []:
        fragments.append(_strip_signature(str(text)))
    return unknown_terms(fragments, canonical_dir), None
