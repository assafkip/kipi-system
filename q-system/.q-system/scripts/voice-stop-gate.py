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
    torch load, so this path takes the strict reading.

    THE INLINE CASE, added 2026-08-18 (sp-88029341). It is no longer simply
    dropped: `extract_inline_draft` recovers a draft written with no fence and no
    blockquote, and it is tried ONLY when nothing is set off. The whole-message
    fallback stays refused -- see that function for the measurement that killed
    it.
    """
    segments = [body for info, body in _FENCE_RE.findall(text)
                if info.strip().lower() in _PROSE_FENCE_LANGS]
    segments += _QUOTE_RE.findall(text)
    segments += _hr_draft_segments(text)
    setoff = "\n\n".join(s.strip() for s in segments if s.strip())
    return setoff if setoff else extract_inline_draft(text)


_HR_RE = re.compile(r"(?m)^\s*-{3,}\s*$")


def _hr_draft_segments(text):
    """Drafts set off by `---` horizontal rules (sp-3bec4a5e).

    The first live post after ASK-902 shipped was delivered exactly this way --
    framing line, `---`, the post, `---`, a what-changed analysis -- and it was
    structurally invisible: the fence list knows ``` only, and the inline
    fallback's share floor correctly refuses the mixture. Measured on the real
    transcript before this was written.

    NO SHARE FLOOR here, refused on purpose (Codex minor, PR #217): the real
    missed turn this exists for was framing + draft + what-changed analysis,
    where the draft held WELL under the inline path's 70% -- a floor here
    re-opens the exact hole. The fences are the author's own set-off; the word
    and furniture requirements below are the qualification.

    The pairing reads like fences: segment 1 sits between rules 1 and 2, segment
    2 between rules 3 and 4. An odd trailing rule opens no segment. Each segment
    must EARN draft status -- at least INLINE_DRAFT_MIN_WORDS words and no
    furniture line -- because two rules used as section dividers around
    engineering prose are the ordinary non-draft case, and a divider section
    full of paths and code spans must stay invisible to a 319MB model load.
    """
    parts = _HR_RE.split(text)
    out = []
    # parts[0] is before the first rule; fenced bodies are the odd indices of
    # consecutive rule pairs: parts[1], parts[3], ...
    for i in range(1, len(parts), 2):
        if i + 1 >= len(parts):
            # An odd trailing rule CLOSED nothing: parts[i] is the text after a
            # lone ---, not a fenced body. Codex major on PR #217 -- the first
            # cut treated it as fenced, gluing post-divider chat into the draft.
            break
        body = parts[i].strip()
        if not body:
            continue
        if len(body.split()) < INLINE_DRAFT_MIN_WORDS:
            continue
        if _FURNITURE_RE.search(body):
            continue
        out.append(body)
    return out


# Markdown and engineering furniture. A post he would paste into LinkedIn carries
# none of it; this fleet's chat is built out of it. Membership is what separates
# an inline draft from an ordinary reply, so each entry is a measured claim, not a
# guess -- see extract_inline_draft for the corpus it was tuned against.
_FURNITURE_RE = re.compile(
    r"(^\s{0,3}#{1,6}\s"            # markdown heading
    r"|^\s*([-*+]|\d+[.)])\s"       # bullet or numbered list
    r"|^\s*>"                       # blockquote line
    r"|^\s*\|"                      # table row
    r"|^\s*-{3,}\s*$"               # a bare horizontal rule (never draft text)
    r"|`"                           # any code span
    r"|\*\*"                        # any bold run
    r"|\]\("                        # markdown link
    # Paths: THREE+ segments only (sp-a2dbef28). The first cut used \w+/\w+ and
    # it refused 14 of the founder's 72 real posts -- "serve/harm", "FB/Meta",
    # "24/7", t.co links are his PROSE (measured against the live corpus,
    # 2026-08-18). Two-segment mentions in chat are held out by the other
    # furniture marks plus the post-shaped gate in the reporter, which is the
    # layer that bounds a false qualify to one wasted score on a post-shaped
    # turn, never a habit.
    # Segments are SLASH-FREE, so a URL cannot match: \S+ swallows slashes and
    # made https://t.co/x count as three segments -- and t.co links appear in 4
    # of his real X posts. A residual known cost, accepted and named: a prose
    # triple like "small/medium/up-and-comer" (2 corpus rows) still reads as a
    # path. Pairs were 14 rows; triples are the smaller wrong side of the line.
    # A domain-shaped first segment (github.com/user/repo, t.co/x/y) is a URL
    # fragment, not a repo path -- his posts name repos and carry links. Dotted
    # HIDDEN dirs (.claude/...) are not domain-shaped (\w+\.\w+ requires a
    # word char before the dot), so real paths keep matching.
    # Anchored to TOKEN START ((?:^|(?<=\s))): without it the engine restarts
    # one character into the token and matches ".com/user/repo" past the guard.
    r"|(?:^|(?<=\s))(?![\w-]+\.[A-Za-z]{2,}/)[^\s/]+(?:/[^\s/]+){2,}"
    r"|\w+\.(py|sh|json|md|jsonl|yml|yaml|txt)\b"   # a filename
    r")", re.MULTILINE)

# A draft has to BE the message, not sit inside it. Below this share the message
# is a mixture -- surrounding chat plus some prose -- and scoring the prose half
# reports a number about something he never wrote as a post.
INLINE_DRAFT_MIN_SHARE = 0.70
INLINE_DRAFT_MIN_WORDS = 25


# A one-line "here's the post" lead-in and a one-line "want a shorter opener?"
# trailer are furniture-free prose, so the run finder keeps them. They are the
# assistant talking to HIM, not part of the post, and leaving them in makes the
# score describe a text he never wrote (caught by
# test_a_post_written_inline_is_recovered before this existed).
HANDOFF_MAX_WORDS = 15


def _trim_handoff_paragraphs(paragraphs):
    """Drop a leading publish-framing line and a trailing question line."""
    out = list(paragraphs)
    while out and len(out[0].split()) <= HANDOFF_MAX_WORDS \
            and _PUBLISH_MARKER_RE.search(out[0]):
        out.pop(0)
    while out and len(out[-1].split()) <= HANDOFF_MAX_WORDS \
            and out[-1].rstrip().endswith("?"):
        out.pop()
    return out


def extract_inline_draft(text):
    """A draft written straight into the message body, or ''.

    THE MEASUREMENT THAT SHAPED THIS (2026-08-18, 14,034 real turns across the
    social-voice and consulting session logs, sp-88029341's DoR asked for it
    before any extraction change):

        assistant messages carrying strong publish framing ....... 76
          with a set-off block (already scored) .................. 29
          with NO set-off block .................................. 47

    Those 47 are the population this function sees, and reading them is what
    rejected the obvious fix. `extract_publishable` already has a whole-message
    fallback and reusing it here would have scored all 47 -- every one of them
    ordinary engineering prose with headings, bullets and backticks, at 3.66s of
    torch each. A wrong number is worse than a missing one, which is exactly why
    ASK-896 left this hole open rather than closing it that way.

    So the discriminator is not "no fence was used". It is "the message is
    nothing but clean prose": consecutive paragraphs free of markdown furniture,
    together making up at least INLINE_DRAFT_MIN_SHARE of the message. A lead-in
    ("Here's the post:") or a trailing question is allowed to sit around it; a
    heading, a bullet list or a backtick anywhere in the body is not.

    The share floor is the part that does the work. Without it a single clean
    paragraph inside a long engineering answer reads as a draft, which is the
    mixture problem one level down.
    """
    if not text or not text.strip():
        return ""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return ""
    total_words = sum(len(p.split()) for p in paragraphs)
    if not total_words:
        return ""
    # The longest run of consecutive furniture-free paragraphs. Runs, not the sum
    # of all clean paragraphs: a post is contiguous, and stitching clean scraps
    # from either side of a bullet list rebuilds the mixture this rejects.
    best, current = [], []
    for para in paragraphs:
        if _FURNITURE_RE.search(para):
            current = []
            continue
        current.append(para)
        if sum(len(p.split()) for p in current) > sum(len(p.split()) for p in best):
            best = list(current)
    best = _trim_handoff_paragraphs(best)
    if not best:
        return ""
    draft = "\n\n".join(best)
    words = len(draft.split())
    if words < INLINE_DRAFT_MIN_WORDS:
        return ""
    if words / total_words < INLINE_DRAFT_MIN_SHARE:
        return ""
    return draft


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


def authorship_page():
    """Send a pending drift page, detached. The INSTANCE side owns this channel.

    The reporter computes the drift but may not send the page: everything in
    `q-consult/pipeline/` is forbidden by that repo's boundary test from reaching
    the Slack webhook, which belongs to the other side of that repo's
    brand-separation boundary (its test_boundary.py names the two sides). So it writes a request and this script -- which lives on the
    instance, already knows INSTANCE_ROOT, and is where founder notifications
    belong -- delivers it.

    `slack-notify.sh` is the only sanctioned channel (founder-notifications.md);
    osascript is banned because a sandboxed process drops it silently, which is
    the same silence this whole counter exists to break.

    FULLY DETACHED, and that is not optional. This runs on the Stop path, and a
    curl to Slack must never sit between him and his text. The page is not urgent
    by construction -- it reports an ongoing silence, not an incident.
    """
    argv = _reporter_argv("--drain-page")
    if argv is None:
        return
    try:
        # 3s, not 10: --drain-page is a state-file read, and this sync call
        # shares a 15s Stop budget with the drain and the spool (Codex minor,
        # PR #217). The Slack send below stays a detached Popen.
        r = subprocess.run(argv, capture_output=True, text=True, timeout=3)
    except Exception:
        return
    line = (r.stdout or "").strip()
    if not line:
        return
    script = SCRIPTS_DIR / "slack-notify.sh"
    if not script.is_file():
        return
    try:
        subprocess.Popen(["bash", str(script), line],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        return


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
    # Before the drain, and detached, so a Slack curl never delays his text.
    authorship_page()
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
    # sp-08c34cf1: SURFACE-ONLY MODE, for SessionStart ONLY.
    #
    # SessionEnd was wired here first and REMOVED after a Codex review checked
    # the premise against the hooks documentation: SessionEnd delivers no
    # systemMessage to the user (only a stderr error notice), so a drain there
    # CONSUMED the score and threw it away, and the SessionStart backstop then
    # found nothing left to surface. A same-session wrap-up surface is not
    # available from any hook; next-session-start is the honest floor.
    #
    # The drain runs on the NEXT Stop event, and the last post of a session has
    # no next Stop -- confirmed against the hooks documentation, not assumed:
    # nothing fires while Claude Code sits idle waiting for input. So the score
    # for the last post he writes reached him only if he happened to write
    # another one.
    #
    # Two events close it, and BOTH are wired rather than one:
    #   SessionEnd   fires on clear / logout / prompt_input_exit. The worker
    #                publishes ~3s after the drafting turn, and he reads a draft
    #                for longer than that, so this is a SAME-session surface for
    #                the ordinary wrap-up.
    #   SessionStart is the backstop for the one shape SessionEnd cannot see: a
    #                terminal killed outright. A day-late number is worse than a
    #                same-session one and far better than none, which is why the
    #                drained line now names its own age when it is not fresh.
    #
    # It is a FLAG and not a `hook_event_name` sniff on the payload. The lint
    # half of this file must never run on those events, and keying that on a
    # field the payload happens to carry makes the safety depend on a schema
    # nobody here controls.
    if "--drain-only" in sys.argv[1:]:
        finish_ok()
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
