#!/usr/bin/env bash
# ASK-4608: voice-lint check_banned_phrases matched inside words, so the banned
# phrase 'one flag' fired on 'the one flagged question' and blocked the consulting
# site deploy. A phrase now matches only as whole words. Control: the phrase on its
# own, and at a sentence start, still fires.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
python3 - "$ROOT/q-system/.q-system/scripts/voice-lint.py" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("voice_lint", sys.argv[1])
vl = importlib.util.module_from_spec(spec); spec.loader.exec_module(vl)
def hits(text):
    return [v["detail"] for v in vl.check_banned_phrases(text) if "'one flag'" in v["detail"]]
assert hits("The one flagged question was the refund.") == [], "fired inside a word: 'one flagged'"
assert hits("I flagged someone flagging it, one flagger.") == [], "fired inside a word"
assert len(hits("There is one flag in the report.")) == 1, "control: whole phrase must fire"
assert len(hits("One flag. Then nothing.")) == 1, "control: phrase at a sentence start must fire"
assert len(hits("one flag, one flag")) == 2, "control: each whole occurrence counts"
assert len(hits("Two quick ones: one flags it.")) == 1, "control: a plural still fires"
plurals = [v for v in vl.check_banned_phrases("These are game-changers.") if "game-changer" in v["detail"]]
assert plurals, "control: the plural 'game-changers' still fires"

# ASK-4616: two banned phrases are meant as PREFIXES and the whole-word fix above
# silently stopped them firing on their commonest AI form, 'let's dive into' and
# 'just checking into'. They keep a substring match at the tail; every other
# phrase stays whole-word, which the 'one flag' assertions above pin.
def phrase_hits(text, phrase):
    return [v["detail"] for v in vl.check_banned_phrases(text) if f"'{phrase}'" in v["detail"]]

assert len(phrase_hits("Let's dive into the numbers.", "let's dive in")) == 1, \
    "prefix phrase must fire on 'let's dive into'"
assert len(phrase_hits("just checking into the hotel", "just checking in")) == 1, \
    "prefix phrase must fire on 'just checking into'"
assert len(phrase_hits("Let's dive in.", "let's dive in")) == 1, \
    "control: the bare prefix phrase still fires"
assert len(phrase_hits("Just checking in on the deck.", "just checking in")) == 1, \
    "control: the bare prefix phrase still fires"
assert phrase_hits("We will dive into it.", "let's dive in") == [], \
    "control: a prefix phrase still needs its own left boundary"
assert vl.PREFIX_PHRASES <= set(vl.BANNED_PHRASES), \
    "every prefix phrase must be a banned phrase, or its pattern is never built"

print("PASS: banned phrases match whole words only, prefix phrases match their tail, controls fire")
PY
