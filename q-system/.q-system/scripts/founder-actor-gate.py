#!/usr/bin/env python3
"""founder-actor-gate.py - the assistant may not hand the founder work without naming why.

Stop hook. Reads the final assistant message and BLOCKS (exit 2) when it names the
founder as the actor without declaring which class of founder-only authority makes
that necessary.

WHY THIS EXISTS (ASK-310, RCA rca-work-routed-to-the-founder-2026-08-02.md)

Three script-layer gates were built to stop work being routed to the founder --
notify-callsite-audit.py, ff-merge-if-safe.sh, and their tests -- and all three
shipped with zero callers. Wiring them was the fix for the SCRIPT layer. But the
measured highest-volume producer of founder-directed work in the session that
found all this was the assistant's own prose: a project update whose top line was
"Clear the PR queue", a five-item "what's yours" list, and a question the
autonomy contract had already answered. Every existing gate inspects scripts.
Nothing observed the text. This closes that.

THE RULE IS NOT "NEVER ASK". It is "if you name the founder as the actor, name
the class". Some work genuinely is his: an irreversible git operation, a write
outside the tree, money, publishing, a credential. Those are exactly the classes
slack-notify.sh already allowlists for `--kind decision --class <...>`, so the
prose layer and the script layer answer to ONE vocabulary rather than two that
drift. A message that says "this needs you because it is a spend decision" passes.
A message that says "clear the PR queue" does not.

WHY IT MUST NOT BE TRIGGER-HAPPY. A gate that fires on every turn is a gate the
operator disables, and "a permanently red gate teaches the operator to skim RED"
is root cause #3 of the RCA this implements. So the patterns below match
IMPERATIVE TASKING and HANDED-OVER COMMANDS only -- never a status report, never a
question, never a description of what a script does. The corpus in
test-founder-actor-gate.sh pins both directions, including this file's own
sibling messages that must pass.

Exit codes (Claude Code hook contract):
  0  nothing to say
  2  block, stderr is fed back to the assistant
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# The SAME classes slack-notify.sh allowlists. One vocabulary for both layers.
JUSTIFIED_CLASSES = (
    "irreversible-git", "out-of-tree-write", "spend", "publish", "credential",
)

# Naming a class, or plainly stating the authority is the founder's, satisfies the
# gate. These are deliberately easy to write correctly -- the gate is meant to be
# cheap to satisfy honestly and impossible to satisfy by accident.
JUSTIFICATION = re.compile(
    r"(" + "|".join(re.escape(c) for c in JUSTIFIED_CLASSES) + r")"
    r"|only you can\b"
    r"|your (authority|call|decision|judgement|judgment) (is|because|since)"
    r"|an agent (must not|cannot|may not)\b"
    r"|requires (your|founder) (approval|authority|sign-?off)"
    r"|founder-actor-ack",
    re.IGNORECASE,
)

# A section heading that exists to enumerate founder chores.
TASK_HEADING = re.compile(
    r"^\s{0,3}(?:#{1,6}\s*|\*\*|__)?\s*"
    r"(what'?s (?:yours|on you)"
    # `(?:\w+\s+)?` so a COUNT in front still matches: the real miss was
    # "**Five things waiting on you**", which the countless form did not catch.
    # Bounded to one word on purpose -- widening this to \s+ would start matching
    # ordinary prose sentences that happen to end "...waiting on you".
    r"|(?:\w+\s+)?(?:things?|items?)\s+(?:waiting|needing)\s+(?:on |from )?(?:you|founder)"
    r"|(?:waiting|needs?) (?:on |from )?(?:you|founder)\b"
    r"|(?:your|founder) (?:to-?dos?|tasks?|actions?|queue)"
    r"|(?:needs|requires) (?:a )?founder"
    r"|action items? for you"
    r"|over to you)",
    re.IGNORECASE | re.MULTILINE,
)

# A command handed over for the founder to run. The literal shape from the scar:
#   "Do: cd $REPO && git merge --ff-only origin/main"
HANDED_COMMAND = re.compile(
    r"^\s*(?:[-*]\s*|\d+\.\s*)?(?:\*\*)?(?:Do|Run|Fix)(?:\*\*)?\s*:\s*"
    r"[`$]?\s*(?:cd|git|gh|python3|bash|npm|kipi|launchctl|brew)\b",
    re.IGNORECASE | re.MULTILINE,
)

# An imperative next-step pointed at the founder. Anchored on "Next:" / "Next
# step:" so ordinary imperative prose about what the SYSTEM will do is untouched.
IMPERATIVE_NEXT = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?next(?: step)?(?:\*\*)?\s*:\s*"
    r"(?:you\b|your\b|clear |merge |approve |decide |review |go )",
    re.IGNORECASE | re.MULTILINE,
)

# "nothing here moves until you do" and its family: the system declaring itself
# blocked on the founder.
BLOCKED_ON_FOUNDER = re.compile(
    r"(nothing .{0,40}until you"
    r"|blocked (?:on|until) you\b"
    r"|waiting on you to\b"
    r"|you(?:'ll| will) need to (?:run|merge|clear|approve))",
    re.IGNORECASE,
)

PATTERNS = (
    ("a founder to-do heading", TASK_HEADING),
    ("a command handed to the founder to run", HANDED_COMMAND),
    ("an imperative next-step aimed at the founder", IMPERATIVE_NEXT),
    ("the system declaring itself blocked on the founder", BLOCKED_ON_FOUNDER),
)


def find_final_assistant_text(transcript_path: str) -> str:
    """Last assistant message's text blocks.

    Lifted deliberately from voice-stop-gate.py rather than re-derived: two
    readers of "the assistant's final message" with drifting semantics is the
    exact defect class this repo keeps finding.
    """
    if not transcript_path or not Path(transcript_path).exists():
        return ""
    text_parts: list[str] = []
    for line in Path(transcript_path).read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except Exception:
            continue
        message = record.get("message", {})
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        text_parts = []
        for item in message.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                if item.get("text"):
                    text_parts.append(item["text"])
            elif isinstance(item, str):
                text_parts.append(item)
    return "\n\n".join(text_parts)


def violations(text: str) -> list[str]:
    """Which founder-tasking shapes appear, if none of them are justified."""
    if not text.strip():
        return []
    if JUSTIFICATION.search(text):
        return []
    return [label for label, pat in PATTERNS if pat.search(text)]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    # A hook that re-fires on its own block would wedge the session.
    if payload.get("stop_hook_active"):
        return 0

    text = find_final_assistant_text(payload.get("transcript_path", ""))
    found = violations(text)
    if not found:
        return 0

    sys.stderr.write(
        "founder-actor-gate: this message hands the founder work without saying "
        "why it has to be his.\n\n"
        "  Found: " + "; ".join(found) + "\n\n"
        "The autonomy contract is pre-authorization: the founder picking work is "
        "the thing it removes. Before re-sending, do ONE of:\n"
        "  1. Do the work instead of reporting it. This is almost always the answer.\n"
        "  2. If it truly needs him, name the class that makes it his -- one of: "
        + ", ".join(JUSTIFIED_CLASSES) + " -- the same vocabulary slack-notify.sh "
        "uses for --kind decision --class.\n"
        "  3. If a script could do it and does not exist yet, say that plainly and "
        "build it; a to-do for the founder is not a substitute for the missing code.\n\n"
        "Deliberate exception: include the token founder-actor-ack with a reason.\n"
        "Why: q-system/output/rca/rca-work-routed-to-the-founder-2026-08-02.md\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
