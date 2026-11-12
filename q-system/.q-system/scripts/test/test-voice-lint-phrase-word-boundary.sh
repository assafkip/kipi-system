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
print("PASS: banned phrases match whole words only; whole-phrase controls still fire")
PY
