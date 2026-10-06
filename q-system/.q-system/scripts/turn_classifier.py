#!/usr/bin/env python3
"""turn_classifier: one answer to "does this turn deserve injected context?"

Shared by every UserPromptSubmit injector in this directory (voice-dna-loader.py,
lessons-inject.py, knowledge-inject.py), so they agree. An instance-local hook can
load it by path from the synced tree and must fail open when it is absent.
Tests: test_turn_classifier.py. Stdlib only, no I/O.

WHY (ASK-2511, 2026-10-06). Each injector had its own keyword trigger and none of
them looked at the SHAPE of the turn. A background task-notification is a block of
agent prose; it carries words like "post", "reply", "test", "fix", so all four
fired on it. Measured on one session's notification turn: voice 6,141 bytes +
lessons 11,912 + knowledge 7,589 = about 25 KB, and that session had 60+ such
turns. Nobody typed any of them. bank_corrected_post fired "Bank it" on two
notifications that held no post at all.

WHY STRUCTURE AND NOT MORE KEYWORDS. Another word list loses the same way the
old ones did: agent prose uses every word. The notification envelope, the word
count, and pasted content are properties of the turn, not of its vocabulary.

THE ONE RULE THAT OUTRANKS THE REST: a writing verb or pasted content always
means "inject". The founder's voice must never silently drop, so "write the
post" (3 words) is a writing request, not a trivial turn.

Classes:
  notification  system event, not a person. Nothing is injected.
  trivial       3 words or fewer, no writing verb, nothing pasted ("ok", "go").
  status        a short question about progress, no writing verb, nothing pasted.
  writing       a writing verb or pasted content. Every injector may run.
  other         everything else. Each injector applies its own trigger.
"""
from __future__ import annotations

import re
from pathlib import Path

# Envelopes are matched at the START of the prompt only: a person who pastes a
# notification and asks for something about it has typed text first, and that
# turn must not be silenced.

# The verbs from the ASK-2511 spec plus the surfaces that only ever mean a
# writing request. Deliberately NOT voice-dna-loader's 60-pattern list: words
# like "text", "message", "thread", "send", "offer" are status vocabulary too,
# and that overlap is what made the loader fire on progress questions.
WRITING_VERB_RE = re.compile(
    r"(?i)\b("
    r"draft\w*|re-?draft\w*|write|writes|writing|written|wrote|rewrit\w*|"
    r"compose|composing|post|posts|posting|repl(?:y|ies|ying)|e-?mail\w*|"
    # Short revision asks the voice loader always matched (PR #523 review):
    # "edit it", "polish this", "reword the opener" must never lose the voice.
    r"edit|edits|editing|revis\w*|polish\w*|rephras\w*|reword\w*|"
    r"comment|comments|dm|dms|tweet\w*|caption\w*|headline\w*|"
    r"essay|newsletter|outreach|"
    # Outreach and surface words the voice loader always matched that have no
    # status reading here (PR #523 review, round 2): "pitch it", "counter-offer".
    r"pitch|pitches|proposal|counter-?offer\w*|negotiat\w*|rebut\w*|"
    r"linkedin|substack|reddit|article|opener|cta|subject\s+line"
    r")\b"
)

# How a short progress question or ack opens. Typos stay in: "whats", "is this done/".
_STATUS_OPENERS = frozenset(
    "how what whats what's why is are was were did does do has have can could "
    "would will when where who which still done any explain status eta so "
    # Short acks and go-aheads: "go to round 3", "go with a new agent".
    "go ok okay yes yeah yep continue proceed".split()
)

TRIVIAL_MAX_WORDS = 3
# Measured on the fixture session: the longest progress question was 8 words
# ("what is making it run for 13 minutes?"); the shortest real design question
# was 9 ("Would this mechanism be different and separate from VoiceLoop?").
STATUS_MAX_WORDS = 8


# WHICH OPENERS MEAN "THE HARNESS WROTE THIS TURN" HAS ONE AUTHORITY:
# voice-stop-gate.py `_INJECTED_OPENER`, which answers the same question for the
# Stop gate and carries the scars (cross-session-message, the bare
# "[SYSTEM NOTIFICATION" opener, and command-* deliberately OUT because a
# slash-command turn is his turn). A second list here drifted within one review
# round (PR #523, consulting PR #226), so this reads that regex instead of
# keeping a copy. If it cannot load, nothing is treated as a notification and
# the reason goes to stderr: fail open, never silent.
_OPENER = None


def _injected_opener():
    global _OPENER
    if _OPENER is None:
        import importlib.util
        import sys
        try:
            path = Path(__file__).resolve().parent / "voice-stop-gate.py"
            spec = importlib.util.spec_from_file_location("_vsg_for_turn_classifier", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _OPENER = mod._INJECTED_OPENER
        except Exception as exc:
            sys.stderr.write(f"turn_classifier: voice-stop-gate opener unavailable, "
                             f"notification check OFF: {exc!r}\n")
            _OPENER = False
    return _OPENER


def is_notification(prompt: str) -> bool:
    opener = _injected_opener()
    return bool(opener) and bool(opener.match(prompt or ""))


def has_pasted_content(prompt: str) -> bool:
    s = (prompt or "").strip()
    if "<pasted_content" in s:
        return True
    # A post, an email or a transcript is multi-paragraph or multi-line. A status
    # question is one line.
    return "\n\n" in s or s.count("\n") >= 2


def has_writing_verb(prompt: str) -> bool:
    return bool(WRITING_VERB_RE.search(prompt or ""))


def classify(prompt: str) -> str:
    if is_notification(prompt):
        return "notification"
    if has_pasted_content(prompt) or has_writing_verb(prompt):
        return "writing"
    words = (prompt or "").split()
    if len(words) <= TRIVIAL_MAX_WORDS:
        return "trivial"
    if len(words) <= STATUS_MAX_WORDS and not names_something(words):
        first = re.sub(r"[^a-z']", "", words[0].lower())
        if "?" in prompt or first in _STATUS_OPENERS:
            return "status"
    return "other"


def names_something(words) -> bool:
    """A capitalised word after the first: a person, a client, a product.

    WHY (PR #523 CI): "what do we know about <Full Name>" is 7 words and opens
    with "what", so the first cut called it status and knowledge-inject went
    silent on exactly the question it exists for. A progress question names a
    duration or a step, not a proper noun. "I" and "I'm" are not names.
    """
    for w in words[1:]:
        core = re.sub(r"^[^A-Za-z]+|[^A-Za-z']+$", "", w)
        if core[:1].isupper() and core not in ("I", "I'm", "I've", "I'd", "I'll"):
            return True
    return False


# Which classes each injector stays silent on. One classifier, one table, so the
# hooks agree on WHAT a turn is and differ only where a measurement says so.
# knowledge-inject keeps "status": its own entity resolver already returned 0
# bytes on every status turn in the replay, and silencing it there only lost
# short lookups like "what did we promise her?" (PR #523 review, round 2).
_SILENT = {
    "default": frozenset({"notification", "trivial", "status"}),
    "knowledge-inject": frozenset({"notification", "trivial"}),
}


def should_inject(prompt: str, hook: str = "default") -> bool:
    """False means this injector stays silent on this turn."""
    return classify(prompt) not in _SILENT.get(hook, _SILENT["default"])


# ---------------------------------------------------------------------------
# The per-turn byte budget, split into fixed shares.
#
# WHY FIXED SHARES AND NOT A SHARED COUNTER: Claude Code runs the hooks of one
# event in parallel, as separate processes. A running total would need a file
# all three write, which is two writers on one file and a race on every turn.
# Fixed shares need no shared state and still bound the sum.
#
# Numbers measured 2026-10-06 over the real non-notification prompts of three
# sessions (see the ASK-2511 PR body). The two advisory injectors are cut to the
# size of one good item each.
#
# VOICE IS NOT CAPPED, on purpose. A 7,000-byte voice share cut the legacy
# fallback (voice-dna.md + writing-samples.md, ~42 KB) to 6,886 bytes and
# writing-samples never reached the model (PR #523 review, round 2). The
# founder's voice must never silently drop, so the budget bounds only what is
# advisory. The corpus path measured 5,981 bytes at most.
SHARES = {
    # 175 of 176 lessons fit in 5000; the largest (4,777 bytes) plus the
    # header needs 5,400, and a share that can never carry a lesson whole
    # starves it silently.
    "lessons-inject": 5500,
    "knowledge-inject": 4000,
}
# The cap on ADVISORY bytes per turn. Voice is outside it (see above).
TURN_BYTE_CAP = sum(SHARES.values())


def cap(text: str, hook: str) -> str:
    """Trim `text` to the hook's share, at a line boundary, and SAY so.

    A silent cut reads as "that was everything". The marker names the cap and
    the ticket so a reader knows more existed.
    """
    limit = SHARES[hook]
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    marker = f"\n[{hook}: cut at {limit} bytes, per-turn budget ASK-2511; open the source for the rest]\n"
    room = limit - len(marker.encode("utf-8"))
    head = data[:max(room, 0)].decode("utf-8", errors="ignore")
    nl = head.rfind("\n")
    if nl > room // 2:
        head = head[:nl]
    return head + marker
