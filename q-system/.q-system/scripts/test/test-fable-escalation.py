#!/usr/bin/env python3
"""Pairs with: token-guard.py FABLE_ESCALATION (ASK-310).

Founder-directed 2026-08-02: "you failed 3 times, ask fable".

Every ceiling in token-guard.py used to end its message with "tell the founder
what's blocking you". That is the ASK-310 defect in its purest form: the system
reaching its own limit and converting the remainder into founder work. Three
failed attempts is evidence that THIS model is stuck on THIS problem, not that a
human is needed. A different model is the cheaper and more correct next step; the
founder is what comes after Fable is also stuck.

This pins both directions -- that the cap names Fable, AND that the founder is
still reachable behind it. Removing the human entirely would be the opposite
failure and is just as much a defect.

Isolated: KIPI_STATE_DIR is redirected before import so no live cache is touched.
"""
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile

os.environ["KIPI_STATE_DIR"] = tempfile.mkdtemp()
HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "..", "..", "token-guard.py")

_spec = importlib.util.spec_from_file_location("tg", GUARD)
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)
SRC = open(GUARD, encoding="utf-8").read()

FAILS = []


def check(label, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if not cond:
        FAILS.append(label)


print("the escalation constant")
check("names the exact Agent call, so it is actionable without lookup",
      "Agent(subagent_type='general-purpose', model='fable')" in tg.FABLE_ESCALATION)
check("puts Fable BEFORE the founder",
      tg.FABLE_ESCALATION.index("Fable") < tg.FABLE_ESCALATION.index("founder"))
# NEGATIVE: removing the human is the opposite defect, not the fix.
check("keeps the founder as the final backstop",
      "founder" in tg.FABLE_ESCALATION)
check("RETRY_LIMIT is still 3", tg.RETRY_LIMIT == 3)

print("\nevery ceiling carries it")
check("all three ceiling messages append FABLE_ESCALATION",
      len(re.findall(r'return f"[^"]*" \+ FABLE_ESCALATION', SRC)) == 3)
# Comments are excluded on purpose: the scar comment quotes the old wording, and
# a comment documenting history is not a live code path.
code_lines = [l for l in SRC.splitlines() if not l.lstrip().startswith("#")]
check("no executable line routes a ceiling to the founder first",
      not any("tell the founder" in l for l in code_lines))
check("the scar comment recording the old wording is retained",
      "tell the founder" in SRC)

print("\nlive behaviour at the cap")


def repeat_key(tool, tool_input):
    h = hashlib.md5((tool + json.dumps(tool_input, sort_keys=True)).encode()).hexdigest()[:12]
    return f"{tool}:{h}"


TOOL, INP = "Bash", {"command": "x"}
check("under the cap it does not block",
      tg.check_exact_retry(TOOL, INP, {"repeat_map": {}}) is None)

msg = tg.check_exact_retry(TOOL, INP, {"repeat_map": {repeat_key(TOOL, INP): tg.RETRY_LIMIT}})
check("at the cap it blocks", msg is not None)
check("at the cap the message says to ask Fable", bool(msg) and "fable" in msg.lower())
check("at the cap Fable is named before the founder",
      bool(msg) and msg.lower().index("fable") < msg.lower().index("founder"))

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
