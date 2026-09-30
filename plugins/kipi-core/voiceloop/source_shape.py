#!/usr/bin/env python3
"""Reject text that is SOURCE MATERIAL rather than a post. The backstop, not the feature.

why this exists (2026-08-05, after the engine was switched on and had to be switched off
again): `material.py` mines the git log, and its own docstring says it "does not WRITE
posts; it finds the material that can become one and hands it to the generator." There
was no generator. Mined text went straight to the publisher, so the engine was one week
of X volume away from putting this on the founder's LinkedIn:

    Feat(content-engine): the scheduled job, loaded and live (ASK-409)
    ORDER OF OPERATIONS IS THE SAFETY. Brake, then due slots, then fill...

**Every gate passed it.** Bound numbers, named mechanisms, clean voice, repaired
capitalization. The gates ask whether the writing is good; none of them asks whether the
thing is a post at all. Same class as the draft-scaffolding near miss: the text is not
wrong, it is the WRONG TEXT.

## Why a detector and not just a generator

The generator is the feature and it can fail: a model call times out, returns empty, or
returns the prompt back. **If the only thing standing between raw source and the founder's
profile is a model behaving well, then nothing is standing there.** This module is
deterministic, runs inside the gate stack, and cannot be talked out of it.

It is deliberately biased toward false positives. Rejecting a real post costs one slot,
and discard-and-replace refills it in the same cycle. Publishing a commit message costs
the founder's credibility with the exact audience he is trying to reach.
"""
from __future__ import annotations

import re

# Conventional-commit subjects. The single strongest tell.
#
# MATCHED BY SHAPE, NOT BY A TYPE ALLOWLIST (2026-08-13). The allowlist was
# feat|fix|docs|chore|refactor|test|perf|build|ci|style|revert, and this repo writes
# commits with types outside it. Two real mined commits scored ZERO signals and
# would have reached a platform unconverted:
#
#   crm(10a-labs): both documents sent, ball is Bobby's
#   content(10a-labs): the investigations one-pager, built off the real engine
#
# Both name a client and a person by name. An allowlist of types is a guess about
# vocabulary; the SHAPE (`word(scope):` opening a line) is the actual tell, and it
# does not need updating every time someone invents a commit type.
#
# The asymmetry decides the false-positive question: a false positive means a post
# gets routed through conversion it did not strictly need. A false negative means a
# client name ships publicly, which is the one guardrail with no undo. A scope in
# parentheses is required for unlisted types so ordinary prose ("Marketing: we...")
# does not trip it; the known types still match bare.
COMMIT_SUBJECT = re.compile(
    r"^\s*(?:"
    r"(?:feat|fix|docs|chore|refactor|test|perf|build|ci|style|revert)"
    r"\s*(?:\([^)]{1,40}\))?"
    r"|[a-z][a-z0-9_-]{1,20}\s*\([^)]{1,40}\)"
    r")\s*!?:",
    re.I | re.M)

# An issue key in parentheses is how this repo tags every commit.
TICKET_REF = re.compile(r"\((?:[A-Z]{2,6}-\d+|#\d+)\)|\b[A-Z]{2,6}-\d{1,5}\b")

# Repo-shaped paths and filenames.
CODE_PATH = re.compile(
    r"(?:^|\s)(?:[\w.-]+/){1,}[\w.-]+\.(?:py|md|json|ya?ml|sh|html|txt|plist)\b"
    r"|\b\w+\.(?:py|json|ya?ml|plist)\b")

# Function/CLI shapes that belong in a terminal, not on a feed.
CODE_TOKEN = re.compile(
    r"\b\w+\(\)|\b\w+_\w+\(|--[a-z][\w-]{2,}\b|\b[a-z_]+\.[a-z_]+\(")

# Git commit TRAILERS. The highest-precision tell in this file (2026-08-20).
#
# MEASURED, not guessed (sp-2214f302, re-measured at 4d0bcaa3): mining the real
# branch produced 91 candidates and this module missed 4, every one scoring
# signals() == []. All four open with a lowercase one-word type and NO
# parenthesised scope -- `gtm:`, `correct:`, `voice:` -- which COMMIT_SUBJECT
# deliberately does not match, because the bare branch would trip ordinary prose
# like "Marketing: we...". The regex is re.I, so case cannot separate them.
#
# So the fix is NOT to widen COMMIT_SUBJECT, which is the change that would have
# started rejecting real posts. Three of the four carry a trailer block instead,
# and a trailer is a thing no human post can contain: it is written by the commit
# tooling, at the end of a message, in a fixed `Key: value` shape at line start.
# False-positive cost measured before shipping, not after: 0 hits across 109 live
# voice-corpus exemplars and 12 real human seed drafts.
# KEY LIST IS MEASURED, and two candidates were REMOVED after review rather than
# kept for completeness. `git log -500 --format=%B` on this branch: Co-Authored-By
# 452, Claude-Session 229, Co-authored-by 4 (so re.I is load-bearing), and zero for
# every other key. Of the zero-use keys, two collide with ordinary English and were
# dropped: "Refs: terrible last night" and "Reviewed-by: nobody, which is the
# point." both matched. The rest are machine-written spellings with no prose
# collision, so they stay as cheap coverage.
#
# THE CLAIM THIS SIGNAL MAKES, stated narrowly on purpose: a trailer is written by
# commit tooling at the end of a message. It is not a claim about hex, shas, or
# anything a human might quote. That narrowness is what keeps gate_scope's
# "source_shape is DEAD on the external and seed lanes" declaration TRUE -- neither
# a news item nor a post the founder wrote himself contains a `Co-Authored-By:`
# line, so this signal adds no new way to reject his own words.
COMMIT_TRAILER = re.compile(
    r"^[ \t]*(?:Co-Authored-By|Claude-Session|Signed-off-by"
    r"|Acked-by|Tested-by|Change-Id)[ \t]*:[ \t]*\S",
    re.I | re.M)

# A BARE SHORT SHA SIGNAL WAS BUILT HERE AND DELIBERATELY NOT SHIPPED (2026-08-20).
# Recorded because the next person will have the same idea, and the reason it was
# dropped is not obvious from the code that is left.
#
# It would have closed the fourth mined leak, `correct: d670ef9 credited its
# findings to a review that had not run (c2w-b1)`, which carries no trailer and
# cites two commits by short sha. The regex was [0-9a-f]{7,40} with lookaheads
# requiring at least one digit and one a-f letter, which does correctly drop
# "defaced", "effaced", "deadbeef" and any all-digit number.
#
# Review found seven further false-positive classes it does NOT drop, every one
# verified by running it: a "#dec2026" hashtag, a "feb2026" URL segment, an
# 8-digit RGBA colour "#1e3a8aff", a UUID's first group "550e8400", a hex path
# segment in a link, and whole MD5 and SHA1 digests. The last is the one that
# decided it: this founder writes about threat intelligence, so an IOC hash is
# realistic post content, and the cutoff was arbitrary anyway -- {7,40} cannot
# match inside a 64-char SHA256 run, so it blocked MD5 and SHA1 and waved SHA256
# through.
#
# Boundary patches (reject when adjacent to #, / or -) close the listed cases and
# not the class; a bare "dec2026" in prose still matches. Patching a detector once
# per counter-example found by the last reviewer is the shape that produces a rule
# nobody can reason about. The deciding argument is scope, not FP count: gate_scope
# declares source_shape DEAD on the seed lane, meaning this gate is not supposed to
# be judging text the founder wrote himself, and a sha signal fires exactly there --
# "I shipped d670ef9 last night" is a sentence he would write. Shipping it would
# have made that DEAD declaration false while the test pinning it kept passing,
# because that test reads the declaration instead of probing the gate.
#
# The honest cost: one of four known mined leaks is still uncaught. That is tracked,
# and a red audit is better than a gate that can discard the founder's own post.
# Reopening this needs source_shape to be LANE-AWARE first (decide._violations
# passes no lane today), which is its own issue.

# Test/suite reporting.
SUITE_REPORT = re.compile(r"\b\d+\s+(?:passed|failed|tests? pass)\b", re.I)

# Shouted section headers, which is how a commit body is organised and never how a post is.
SHOUTED_HEADER = re.compile(r"^[A-Z][A-Z \t,'()/-]{14,}[.:]?\s*$", re.M)


def signals(text):
    """Every source-shape tell found. Named, so a rejection can explain itself."""
    found = []
    if COMMIT_SUBJECT.search(text or ""):
        found.append("conventional-commit subject")
    if TICKET_REF.search(text or ""):
        found.append("issue key")
    if CODE_PATH.search(text or ""):
        found.append("repo path or filename")
    if CODE_TOKEN.search(text or ""):
        found.append("code identifier or CLI flag")
    if COMMIT_TRAILER.search(text or ""):
        found.append("git commit trailer")
    if SUITE_REPORT.search(text or ""):
        found.append("test-suite report")
    if SHOUTED_HEADER.search(text or ""):
        found.append("shouted section header")
    return found


def looks_like_source(text):
    return bool(signals(text))


def check(text):
    """Violations in the gates' shape, so callers merge reports without special-casing."""
    found = signals(text)
    if not found:
        return []
    return [{
        "rule": "source-shape",
        "line": 1,
        "detail": ("this is source material, not a post: " + ", ".join(found)
                   + ". It needs to go through the generator first."),
    }]
