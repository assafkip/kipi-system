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

import hashlib
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
# .../<repo>/q-system/.q-system/scripts -> <repo>
INSTANCE_ROOT = SCRIPTS_DIR.parents[2]

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


def extract_setoff_draft(text):
    """The set-off draft ONLY -- prose fences and blockquotes, never the
    whole-message fallback.

    Separate from `extract_publishable` on purpose (authorship reporting,
    2026-08-17). That function falls back to the ENTIRE message when framing is
    present but nothing is set off, which is right for the lint: a draft written
    inline still has to pass the voice bar. It is wrong for the authorship
    scorer, because the fallback sweeps the surrounding engineering chat into the
    thing being measured, and the scorer then reports a number about a mixture.
    The lint's false positive costs one stdlib subprocess; this one costs a 319MB
    torch load, so this path takes the strict reading and accepts missing the
    inline case.
    """
    segments = [body for info, body in _FENCE_RE.findall(text)
                if info.strip().lower() in _PROSE_FENCE_LANGS]
    segments += _QUOTE_RE.findall(text)
    return "\n\n".join(s.strip() for s in segments if s.strip())


# --- the optional authorship reporter ----------------------------------------
#
# This file is a FLEET script: the skeleton sync rsyncs
# `q-system/.q-system/scripts/` over every registered instance, so the copy that
# runs anywhere is whatever the skeleton last shipped. The authorship scorer it
# hands off to is NOT fleet code -- it lives in the one publishing pipeline
# (`consulting/q-consult/`), with the one voice corpus, and must never be copied
# (ASK-699: two voice sources was a measured drift machine that took nine
# consumer repoints to kill).
#
# So this file holds a POINTER RESOLVER, never an import and never a copy.
#
# THE SCAR THIS SHAPE EXISTS FOR (2026-08-17). The first wiring probed exactly
# one path, `<instance>/q-consult/pipeline/authorship_stop_report.py`, which is
# correct in consulting and resolves to nothing anywhere else. The founder does
# not write posts in consulting; he writes them in `social-voice`, where that
# probe silently no-opped. The code was right, the tests were green, and the
# instrument reached nobody. A probe that cannot fail is indistinguishable from
# one that works, which is why `resolve_reporter` returns the NAMED path even
# when it is missing and lets the caller decide -- a test can then say "the
# pointer names X, which does not exist" instead of "no pointer".
POINTER_REL = Path("q-system") / ".q-system" / "data" / "authorship-reporter.path"
REPORTER_REL = Path("q-consult") / "pipeline" / "authorship_stop_report.py"
AUTHORSHIP_SPOOL_TIMEOUT = 10


def resolve_reporter(instance_root):
    """Where this instance's authorship reporter lives, or None.

    Two sources, in order:

    1. **In-repo.** The instance that OWNS the pipeline (consulting) finds it
       under its own root. Nothing to configure, and no absolute path baked into
       a fleet script.
    2. **A pointer file** at `q-system/.q-system/data/authorship-reporter.path`.
       That directory is in the skeleton sync's INSTANCE_OWNED_SUBTREES, so the
       sync never overwrites or deletes it -- which is the whole reason the
       pointer lives there rather than next to this script, where the next sync
       would erase it (RULE-2026-06-30-A).

    No pointer means no authorship reporting in that instance, silently. That is
    the default for the fleet: the founder's stated objection is compute, so the
    scorer is opt-in per instance rather than on everywhere a post-shaped
    sentence might appear.
    """
    local = Path(instance_root) / REPORTER_REL
    if local.is_file():
        return local
    pointer = Path(instance_root) / POINTER_REL
    try:
        named = pointer.read_text(encoding="utf-8")
    except OSError:
        return None
    named = "".join(ln for ln in named.splitlines()
                    if ln.strip() and not ln.lstrip().startswith("#")).strip()
    if not named:
        return None
    return Path(os.path.expanduser(named)).resolve()


AUTHORSHIP_REPORTER = resolve_reporter(INSTANCE_ROOT)


def _reporter_argv(*args):
    """A reporter invocation, or None when this instance has no reporter.

    `--instance-root` is not decoration: it is what keeps two instances from
    reading each other's scores. The reporter derives its spool directory from
    it, so a draft written in social-voice can never surface as a number in
    consulting.
    """
    if AUTHORSHIP_REPORTER is None or not AUTHORSHIP_REPORTER.is_file():
        return None
    return (["python3", str(AUTHORSHIP_REPORTER),
             "--instance-root", str(INSTANCE_ROOT)] + list(args))


def authorship_drain():
    """The pending advisory line from a PREVIOUS turn's worker, or ''.

    Costs one `stat` when there is nothing pending, which is almost every turn.
    """
    argv = _reporter_argv("--drain")
    if argv is None:
        return ""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def authorship_spool(draft, framing, request):
    """Hand a clean draft to the reporter, which decides whether it is worth
    scoring and detaches its own worker. Never blocks on the score itself.

    The reporter owns the trigger predicate rather than this file, because the
    predicate has to be tighter than `_PUBLISH_MARKER_RE` (which is tuned for the
    lint's cost model) and because it is tested as one unit there.

    `request` is the founder's own last message, and it is the reliable half of
    the trigger. `framing` is the assistant's -- model output, which is exactly
    the thing that cannot be depended on to say "here's the post" every time. A
    trigger keyed only on the model's phrasing misses a draft whenever the model
    words the handoff differently, and nothing about that failure is visible.
    """
    argv = _reporter_argv()
    if argv is None:
        return
    paths = []
    try:
        for blob in (framing, request):
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                             encoding="utf-8") as fh:
                fh.write(blob or "")
                paths.append(fh.name)
        subprocess.run(argv + ["--framing", paths[0], "--request", paths[1]],
                       input=draft, capture_output=True, text=True,
                       timeout=AUTHORSHIP_SPOOL_TIMEOUT)
    except Exception:
        return
    finally:
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass


def finish_ok():
    """Exit 0, surfacing any advisory line a previous turn's worker finished.

    EVERY exit-0 path routes through here, and that placement is the whole fix
    (caught by test_a_post_shaped_turn_spools_a_score..., 2026-08-17). The first
    wiring drained only at the bottom of `main`, after the conversational
    short-circuit had already returned. The score is published ~3s AFTER the
    drafting turn ends, so the turn that surfaces it is by definition a later
    one -- and a later turn is almost always conversational, which is exactly
    the path that never reached the drain. The number would have appeared only
    if he asked for two posts back to back.
    """
    line = authorship_drain()
    if line:
        # `systemMessage` on exit 0 is the ONLY hook field that puts text in
        # front of the USER rather than the model. Plain stdout from a Stop hook
        # is dropped, and `additionalContext` reaches Claude, not him.
        print(json.dumps({"systemMessage": line}))
    sys.exit(0)


def _walk_transcript(transcript_path):
    if not transcript_path or not Path(transcript_path).exists():
        return
    for line in Path(transcript_path).read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except Exception:
            continue
        message = record.get("message", {})
        if isinstance(message, dict):
            yield message


def _message_text(message):
    parts = []
    content = message.get("content", [])
    if isinstance(content, str):
        return content
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            if item.get("text"):
                parts.append(item["text"])
        elif isinstance(item, str):
            parts.append(item)
    return "\n\n".join(parts)


def find_final_assistant_text(transcript_path):
    text_parts = []
    for message in _walk_transcript(transcript_path):
        if message.get("role") != "assistant":
            continue
        text_parts = [_message_text(message)]
    return "\n\n".join(p for p in text_parts if p)


def find_final_user_text(transcript_path):
    """His last message. The trigger signal the model cannot get wrong.

    Deliberately NOT used by the lint: voice-enforcement.md scopes the lint to
    what the assistant hands over, and reading his request into that decision
    would gate his own words. It is used only to decide whether the draft is
    worth measuring.
    """
    text = ""
    for message in _walk_transcript(transcript_path):
        if message.get("role") != "user":
            continue
        candidate = _message_text(message)
        if candidate:
            text = candidate
    return text


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
    request = find_final_user_text(transcript_path)
    # Gate only real drafts; a conversational reply to the founder is not voice-checked.
    draft = extract_publishable(text)
    if len(draft.encode("utf-8")) < MIN_TEXT_BYTES:
        # NOT a bare `finish_ok()`, and the difference is the founder's actual
        # workflow. He types "write me a post"; the assistant answers with the
        # post in a fence and no "here's the post" sentence. `_PUBLISH_MARKER_RE`
        # sees nothing, the lint correctly declines to gate, and the old code
        # returned here -- so the ONE turn shape he uses most was the one shape
        # that never reached the scorer. The lint's scope is unchanged; the
        # measurement no longer rides on it.
        authorship_spool(extract_setoff_draft(text), text, request)
        finish_ok()
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
            # NO drain and NO spool on this path, both deliberate. Draining here
            # would emit the advisory line into a turn that is being blocked and
            # re-drafted, where it reads as a verdict on the redraft; the result
            # file is left alone so the next completed turn surfaces it. Spooling
            # here would spend 3s of torch on a draft the voice gates just
            # refused, which Claude is about to replace.
            sys.exit(2)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # THE CLEAN PATH. Score this draft (backgrounded, arrives next turn) and
    # surface whatever a previous turn's worker finished.
    authorship_spool(extract_setoff_draft(text), text, request)
    finish_ok()


if __name__ == "__main__":
    main()
