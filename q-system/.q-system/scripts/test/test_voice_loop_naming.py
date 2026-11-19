#!/usr/bin/env python3
"""Pins the naming rule: band-lint and the word lists are advisory linters, not "the voice loop".

Rule-ID: RULE-2026-11-18-VOICELOOP-NAMING
(ASK-5398, part of ASK-4969; founder ruling RULE-2026-11-14-A: one voice loop, the full path.)

why this exists: `voiceloop-band-lint.py` exits 0 on every path and `voice-stop-gate.py` /
`voice-lint.py` / `voice-substance-lint.py` are word lists. Calling any of them "the voice
loop" is how a half-run check read as a full one (the ASK-4637 census, causes A to E). The
voice loop is the full path: voice_full_gate.py (gate_draft --full). No exit counts a lint as
that check.

What it holds, on the files that carry the wording:
  - the phrase "voice loop" appears only on a line that also names the full path;
  - the rule and the two scripts each say "advisory linter" and that no exit counts it.
It does not hold lint behavior (that is not what ASK-5398 changes).

CONTROL FIRST: test_the_reserved_wording_is_allowed_where_it_belongs proves the checker lets
the correct sentence through, so a red result cannot come from a checker that rejects every
mention.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
RULE = REPO / ".claude" / "rules" / "voice-loop-anywhere.md"
SCRIPTS = REPO / "q-system" / ".q-system" / "scripts"
BAND = SCRIPTS / "voiceloop-band-lint.py"
STOP = SCRIPTS / "voice-stop-gate.py"
FILES = (RULE, BAND, STOP)
# A space, not a hyphen: the file name voice-loop-anywhere.md is a path, not the claim.
PHRASE = re.compile(r"voice loop\b", re.I)
RESERVED = re.compile(r"full path|gate_draft|voice_full_gate", re.I)


def misnamed(text: str) -> list:
    return [ln.strip() for ln in text.splitlines() if PHRASE.search(ln) and not RESERVED.search(ln)]


def test_the_reserved_wording_is_allowed_where_it_belongs():
    ok = "The voice loop is the full path: voice_full_gate.py."
    assert misnamed(ok) == []
    assert misnamed("# Voice Loop Anywhere: the style half") != []


def test_no_file_calls_a_lint_the_voice_loop():
    for f in FILES:
        assert misnamed(f.read_text()) == [], (f.name, misnamed(f.read_text()))


def test_each_file_labels_the_lints_advisory():
    for f in FILES:
        head = f.read_text()
        assert "advisory linter" in head.lower(), f.name
        assert re.search(r"no exit counts", head, re.I), f.name


def test_the_rule_names_its_own_enforcer_and_id():
    text = RULE.read_text()
    assert "Rule-ID: RULE-2026-11-18-VOICELOOP-NAMING" in text
    assert "Enforced by:" in text and "test_voice_loop_naming.py" in text
