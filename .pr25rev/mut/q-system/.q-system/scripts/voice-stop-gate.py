#!/usr/bin/env python3
"""
voice-stop-gate.py - Final voice check on assistant chat output.

Stop hook for Claude Code.

The voice-lint PostToolUse hook only fires on file writes. Most voice
failures happen in chat output — drafts I produce for the founder to
copy-paste into X, LinkedIn, email, DMs. None of those reach a file.

This hook closes that gap WITHOUT gating ordinary conversation. Per
.claude/rules/voice-enforcement.md, voice rules apply to content sent to
another person, NOT to "conversational responses to the founder." A Stop
hook can't see the founder's request, so it keys on explicit publish-intent
framing in the assistant's own message ("here's the post/reply/DM/email…",
"draft for LinkedIn", "ready to send"). No such framing means conversational,
which is skipped. When framing IS present, it lints the set-off draft (fenced
prose blocks + blockquotes) rather than the whole message, so surrounding chat
and any code fences are not themselves linted. Exits 2 only on a real draft
violation; Claude must then re-draft before the turn can complete.

Pairs with voice-substance-lint.py for positive-pattern enforcement.

Stdlib only. Reuses voice-lint.py and voice-substance-lint.py via subprocess.

Exit codes:
    0 = clean (turn completes)
    2 = violation (turn blocked, Claude must re-draft)
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
VOICE_LINT = SCRIPTS_DIR / "voice-lint.py"
SUBSTANCE_LINT = SCRIPTS_DIR / "voice-substance-lint.py"

MIN_TEXT_BYTES = 80

# Explicit publish-intent framing — the only signal that a final chat message hands the
# founder content meant for someone ELSE. Engineering/debug chat carries none of these,
# so it's treated as conversational-to-founder and skipped (voice-enforcement.md).
_NOUN = (r"(post|reply|comment|dm|email|draft|thread|tweet|caption|message|outreach|"
         r"response|blurb)")
_PLAT = r"(linkedin|x|twitter|medium|reddit|instagram|threads)"
_PUBLISH_MARKER_RE = re.compile(
    r"(?im)("
    # "here's / here is / below is  the/a/your/my  [up to 2 words]  post/reply/…"
    r"\b(here'?s|here\s+is|below\s+is)\s+(the|a|your|my)\s+(\w+\s+){0,2}" + _NOUN + r"\b"
    r"|\bdraft(ed|ing)?\s+(the|a|your|my|for|below|:)"
    r"|\b" + _NOUN + r"\s+draft\b"
    r"|\bready\s+to\s+(post|send|paste|publish)\b"
    r"|\bcopy[-\s]?paste\b"
    r"|\b(for|on|to)\s+" + _PLAT + r"\b"          # "for LinkedIn", "to X"
    r"|\b" + _PLAT + r"\s+" + _NOUN + r"\b"       # "LinkedIn post", "X reply"
    r")"
)
# Fenced blocks: lint the body only for PROSE fences (no language, or a prose tag). A
# code fence (```python / ```bash) is not a draft and must not be voice-linted.
_FENCE_RE = re.compile(r"```([^\n]*)\n(.*?)```", re.DOTALL)
_PROSE_FENCE_LANGS = {"", "text", "txt", "md", "markdown", "quote", "draft"}
_QUOTE_RE = re.compile(r"(?m)^>\s?(.*)$")


def extract_publishable(text):
    """The draft content to lint, or '' when the message is conversational.

    '' (skip) unless the message carries explicit publish framing. When it does, return
    the set-off draft — prose fences + blockquotes — so surrounding chat and code fences
    aren't linted; if framing is present but nothing is set off (draft written inline),
    fall back to the whole message."""
    if not _PUBLISH_MARKER_RE.search(text):
        return ""
    segments = [body for info, body in _FENCE_RE.findall(text)
                if info.strip().lower() in _PROSE_FENCE_LANGS]
    segments += _QUOTE_RE.findall(text)
    draft = "\n\n".join(s.strip() for s in segments if s.strip())
    return draft if draft else text


def find_final_assistant_text(transcript_path):
    if not transcript_path or not Path(transcript_path).exists():
        return ""
    text_parts = []
    for line in Path(transcript_path).read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except Exception:
            continue
        message = record.get("message", {})
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue
        text_parts = []
        for item in message.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                if text:
                    text_parts.append(text)
            elif isinstance(item, str):
                text_parts.append(item)
    return "\n\n".join(text_parts)


def run_check(script, file_path):
    if not script.exists():
        return (0, "")
    try:
        result = subprocess.run(
            ["python3", str(script), file_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return (result.returncode, result.stdout + result.stderr)
    except subprocess.TimeoutExpired:
        return (1, f"voice-stop-gate: {script.name} timed out")


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    transcript_path = payload.get("transcript_path", "")
    text = find_final_assistant_text(transcript_path)
    # Gate only real drafts; a conversational reply to the founder is not voice-checked.
    draft = extract_publishable(text)
    if len(draft.encode("utf-8")) < MIN_TEXT_BYTES:
        sys.exit(0)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(draft)
        tmp_path = tmp.name
    try:
        violations_output = []
        code1, out1 = run_check(VOICE_LINT, tmp_path)
        if code1 == 2 and out1:
            violations_output.append(out1)
        code2, out2 = run_check(SUBSTANCE_LINT, tmp_path)
        if code2 == 2 and out2:
            violations_output.append(out2)
        if violations_output:
            sys.stderr.write(
                "voice-stop-gate: assistant final message has voice violations.\n"
                "Re-draft before completing the turn.\n\n"
            )
            for output in violations_output:
                sys.stderr.write(output + "\n")
            sys.exit(2)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
