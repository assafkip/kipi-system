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
# .../<repo>/q-system/.q-system/scripts -> <repo>
INSTANCE_ROOT = SCRIPTS_DIR.parents[2]

MIN_TEXT_BYTES = 80

# Explicit publish-intent framing — the only signal that a final chat message hands the
# founder content meant for someone ELSE. Engineering/debug chat carries none of these,
# so it's treated as conversational-to-founder and skipped (voice-enforcement.md).
# 'response' left the set in round 7: "here's the response payload" is
# engineering prose, and the marker now GATES extraction, so a generic noun
# opens the sweep. Same round, same reason, the bare copy-paste alternative
# below is gone -- 'copy-paste' is this fleet's own CLAUDE.md vocabulary.
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
        # 5s ceiling on a state-file read (~0.3s real): drain 5 + page 3 bounds
        # the Stop path's sync reporter cost to 8s inside the 15s hook budget
        # (Codex round 5 counted 13 and called the "detached" wording wrong;
        # the WORKER is detached, these two reads never were).
        r = subprocess.run(argv, capture_output=True, text=True, timeout=5)
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
    """File a pending drift ALERT, detached. The INSTANCE side owns this channel.

    WHO RECEIVES IT (round 7, aligned with the founder's standing directive
    rather than with this docstring's first draft): `slack-notify.sh` is THE
    FLEET ALERT PATH -- founder-directed 2026-08-10, verbatim in that script's
    header: "I dont want to see any of these. Any of the ones that need
    attention should go to Sana - not me." It files a Linear ticket for Sana
    and pages nobody. A reconciliation drift is exactly such an engineering
    signal: the founder's ask was that silence never falls on the floor, and a
    ticket in the engineering queue is the opposite of the floor. The founder
    sees outcomes, never plumbing alerts.

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
    script = SCRIPTS_DIR / "slack-notify.sh"
    if not script.is_file():
        # BEFORE the consuming read, not after: --drain-page deletes what it
        # returns, and an instance without the alert script was eating the
        # page permanently (fallback-review sub-finding, round 7).
        return
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


# A MISSING CHECK IS NOT A PASS. This returned (0, "") when its script was
# absent, and 0 is the same value a clean draft produces, so a run on a machine
# where voice-lint.py had moved was byte-for-byte indistinguishable from a run
# that graded the draft and found nothing wrong. The turn completed, stderr was
# empty, and the founder got a post no gate had read.
#
# The shape is copied from `resolve_reporter` twenty lines up, which was written
# against this same defect: return the NAMED thing even when it is missing and
# let the caller decide, so a reader can say "the check named X, which does not
# exist" instead of seeing silence.
NOT_CHECKED = "NOT_CHECKED"


def report_not_checked(lines, out=None, err=None):
    """Surface NOT CHECKED on the channel a SUCCESSFUL hook is actually read on.

    The first version of this wrote to stderr only, on a path that then exits 0.
    A Stop hook's stderr is fed back when it exits 2; on the success path it goes
    nowhere. So the warning that a draft had not been graded was itself never
    delivered -- the exact defect this whole change exists to close, reproduced
    inside the fix for it (Codex major, PR #290).

    Both streams on purpose. stdout is what a successful hook is read on; stderr
    keeps the line present if this is ever called from the blocking path, where
    stdout is not surfaced. Writing to one and hoping is what got us here.
    """
    for line in lines:
        (out or sys.stdout).write(line + "\n")
        (err or sys.stderr).write(line + "\n")


# --- the OPTIONAL instance channel registry ----------------------------------
#
# The un-shipped half of prd-voice-gate-platform-aware-2026-07-22. That PRD built the
# instance half (cole-gtm/gtm/scripts/voice_channel_registry.py) and named the constraint
# on this half in its section 4: this file lives in the SKELETON and reaches 26 instances
# via `kipi push`, so "the recurrence guard must live where every instance loads it, not
# in one instance's gtm/". Measured 2026-08-30, thirteen months of drift later:
# `grep -c "voice_channel_registry\|channel_registry"` against this file returned 0.
#
# THE HARD CONSTRAINT, and it outranks the feature: an instance with NO registry must
# behave exactly as it did before this block existed. 26 instances have no registry and
# none of them asked for one. So the registry is opt-in, resolved from an INSTANCE-OWNED
# path, and absent means `channel_surface_lint` returns None and the two assaf lints run
# with the identical argv they always ran with.
#
# WHAT THIS HALF CONSUMES, and what it does not. The registry carries two axes: `voice_ref`
# (whose voice) and `surface_ref` + `lint` (what surface the channel imposes). This gate
# has no corpus and no semantic judge -- it runs pattern lints -- so it consumes only the
# SURFACE axis: `lint_script` (the executable) and `lint_input` (how that executable wants
# the draft). The voice axis is consumed by the instance's own judge. Saying so here rather
# than reading `voice_ref` and doing nothing with it, because a field fetched and never
# read is how a docstring starts making promises the code does not keep.
#
# FAIL-CLOSED, same rule as every other check in this file. A registry that is PRESENT and
# unreadable, or that names a lint_script which is absent, HOLDS the turn. Silently falling
# back to the assaf lints there would grade a reddit draft on the wrong rulebook, which is
# the entire defect the registry exists to prevent.
CHANNEL_REGISTRY_REL = Path("q-system") / ".q-system" / "data" / "voice-channels.json"
CHANNEL_REGISTRY_POINTER_REL = (
    Path("q-system") / ".q-system" / "data" / "voice-channels.path")

# How a surface lint wants the draft handed to it. A typo must fail closed, not route a
# channel to an invocation shape its lint cannot parse and read the exit code as a verdict.
KNOWN_LINT_INPUTS = {"text_file", "json_body"}
DEFAULT_LINT_INPUT = "text_file"

# Channels this gate can name from publish framing. Same vocabulary as _PLAT, which the
# publish-intent matcher already captures and then discards.
_CHANNEL_RE = re.compile(r"(?i)\b" + _PLAT + r"\b")
_CHANNEL_ALIASES = {"twitter": "x"}


class ChannelRegistryError(Exception):
    """A registry that is present and cannot be trusted. Callers HOLD the turn."""


def resolve_channel_registry(instance_root):
    """This instance's channel registry path, or None. Shape copied from
    `resolve_reporter` above rather than invented, for the reason written there.

    Two sources, in order:

    1. `q-system/.q-system/data/voice-channels.json` in the instance.
    2. A pointer file beside it naming the real location, because an instance that
       already owns a registry keeps it with its own config (consulting:
       `q-consult/config/voice-channels.json`; cole-gtm: `gtm/config/voice-channels.json`)
       and there is no fleet-wide answer to which subtree that is.

    Both live under `q-system/.q-system/data/`, which is in the skeleton sync's
    INSTANCE_OWNED_SUBTREES, so `kipi update` never overwrites or deletes them
    (RULE-2026-06-30-A). A file next to this script would be erased by the next sync.

    Returns the NAMED path even when it does not exist, so a caller can say "the pointer
    names X, which is missing" instead of "no registry" -- the resolve_reporter scar.
    """
    local = Path(instance_root) / CHANNEL_REGISTRY_REL
    if local.is_file():
        return local
    pointer = Path(instance_root) / CHANNEL_REGISTRY_POINTER_REL
    try:
        named = pointer.read_text(encoding="utf-8")
    except OSError:
        return None
    named = "".join(ln for ln in named.splitlines()
                    if ln.strip() and not ln.lstrip().startswith("#")).strip()
    if not named:
        return None
    named_path = Path(os.path.expanduser(named))
    if not named_path.is_absolute():
        named_path = Path(instance_root) / named_path
    return named_path.resolve()


def detect_channel(text):
    """The channel the draft is FRAMED for, or ''. Read out of the publish marker.

    `_PLAT` already sits inside `_PUBLISH_MARKER_RE`, which matched to get here and then
    throws the platform away. This reads the same vocabulary rather than a second one:
    two lists of channel names is the drift this whole change is about.

    IT MUST NOT BE A FREE SCAN OF THE WHOLE RESPONSE, and it was one until Codex found
    it on PR #291 (sp-9fd6dafd). `_CHANNEL_RE.search(text)` returned the first platform
    named ANYWHERE, so a response that mentions LinkedIn as comparison or rewrite
    context and then ships a Reddit draft was graded against the LinkedIn rulebook --
    the exact "wrong rulebook, shipped AI-sounding" scar (2026-07-22) this registry
    exists to close, re-entering through the channel picker.

    So the platform is taken from inside a PUBLISH MARKER match. Markers that name no
    platform ("here's the draft", "ready to paste") are skipped rather than ending the
    search, which is what keeps "here's the draft for Twitter" resolving to x.

    Returning '' is the SAFE outcome, not a gap: it routes to the assaf lints, which is
    what all 26 registry-less instances already do. Guessing a channel off unrelated
    prose is the direction that misroutes, so framing that names no platform yields no
    channel even when one is named elsewhere in the message.
    """
    for marker in _PUBLISH_MARKER_RE.finditer(text or ""):
        found = _CHANNEL_RE.search(marker.group(0))
        if found:
            name = found.group(1).lower()
            return _CHANNEL_ALIASES.get(name, name)
    return ""


def channel_surface_lint(registry_path, channel, instance_root):
    """(script Path, input mode) for this channel's SURFACE lint, or None.

    None means "no channel-specific surface": run the assaf lints, which is what every
    instance without a registry does and what a registered assaf channel does too.

    Raises ChannelRegistryError when the registry is present and untrustworthy.
    """
    if registry_path is None:
        return None
    try:
        data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ChannelRegistryError(
            f"voice-channels registry named at {registry_path} is unreadable: {exc}") from exc
    except ValueError as exc:
        raise ChannelRegistryError(
            f"voice-channels registry at {registry_path} is malformed: {exc}") from exc
    if not isinstance(data, dict):
        raise ChannelRegistryError(
            f"voice-channels registry at {registry_path} must be an object")
    channels = data.get("channels") or {}
    entry = channels.get(channel) if channel else None
    if entry is None:
        entry = data.get("default")
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise ChannelRegistryError(
            f"voice-channels entry for {channel!r} must be an object")
    script = entry.get("lint_script")
    if not script:
        return None
    mode = entry.get("lint_input", DEFAULT_LINT_INPUT)
    if mode not in KNOWN_LINT_INPUTS:
        raise ChannelRegistryError(
            f"voice-channels entry for {channel!r} has unknown lint_input {mode!r}; "
            f"known: {sorted(KNOWN_LINT_INPUTS)}")
    script_path = Path(script)
    if not script_path.is_absolute():
        script_path = Path(instance_root) / script_path
    if not script_path.is_file():
        raise ChannelRegistryError(
            f"voice-channels entry for {channel!r} names lint_script {script_path}, "
            f"which does not exist; holding rather than grading on the wrong rulebook")
    return (script_path, mode)


def _lint_argv(script, file_path, mode):
    """The invocation shape a lint declared. text_file is the shape every skeleton lint
    has always used, so an instance with no registry produces a byte-identical argv."""
    if mode == "json_body":
        return ["python3", str(script), "--file", file_path]
    return ["python3", str(script), file_path]


def run_check(script, file_path, mode=DEFAULT_LINT_INPUT, json_path=None):
    if not script.exists():
        return (NOT_CHECKED,
                "voice-stop-gate: %s is MISSING at %s, so this draft was NOT "
                "CHECKED by it. That is not a pass." % (script.name, script))
    target = json_path if mode == "json_body" else file_path
    try:
        result = subprocess.run(
            _lint_argv(script, target, mode),
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
    # SessionStart is the one drain event (see the SessionEnd note above): it
    # covers every way a session begins -- startup, resume, clear, compact --
    # so the score survives a killed terminal, a /clear, and a compaction. A
    # day-late number is worse than a same-session one and far better than
    # none, which is why the drained line names its own age when it is stale.
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
    # WHICH RULEBOOK. An instance with no registry resolves to None here and the two
    # assaf lints below run exactly as they did before this block existed -- the hard
    # constraint, because 26 instances have no registry. An instance WITH one routes the
    # channel to its surface lint instead, which is what "a reddit draft was graded on the
    # wrong rulebook and shipped AI-sounding" (scar 2026-07-22) was waiting for.
    #
    # A present-but-broken registry HOLDS. Falling back to the assaf lints there would be
    # the wrong-rulebook bug wearing a fix.
    try:
        surface = channel_surface_lint(
            resolve_channel_registry(INSTANCE_ROOT), detect_channel(text), INSTANCE_ROOT)
    except ChannelRegistryError as exc:
        sys.stderr.write(
            "voice-stop-gate: channel registry error, holding the turn (fail-closed).\n"
            f"{exc}\n")
        sys.exit(2)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(draft)
        tmp_path = tmp.name
    # A surface lint may want the draft as JSON rather than a text file (the reddit
    # persona lint reads {title?,subject?,body}). Written ONLY when a lint asked for that
    # form. Writing it unconditionally would be simpler and would spend a tempfile per
    # gated turn on 26 instances that have no registry and get nothing from it -- and it
    # would make "an instance with no registry behaves exactly as before" false in a way
    # no test here would have caught, because none of them look at the filesystem.
    tmp_json_path = None
    if surface and surface[1] == "json_body":
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp_json:
            json.dump({"body": draft}, tmp_json)
            tmp_json_path = tmp_json.name
    try:
        violations_output = []
        not_checked = []
        lint_failures = []
        checks = ([(surface[0], surface[1])] if surface
                  else [(VOICE_LINT, DEFAULT_LINT_INPUT),
                        (SUBSTANCE_LINT, DEFAULT_LINT_INPUT)])
        # EVERY OUTCOME IS CLASSIFIED, and the else-branch is the fix. Codex MAJOR on
        # PR #291 (sp-5b4b3c35): this handled 2 and NOT_CHECKED and let every other
        # exit fall through to the clean path. `run_check` returns 1 for a timeout AND
        # for an ordinary crash, so a lint that graded nothing reported the draft clean
        # and it shipped. A gate whose checker crashed has not cleared anything.
        #
        # The contract is 0 = pass, 2 = block (skill-hook-pairing.md). Anything else is
        # the gate NOT KNOWING, and not knowing holds the turn. `code == 2` no longer
        # requires output either: a lint that blocked without printing was read as
        # clean, which is the same fail-open wearing a different exit code.
        for script, mode in checks:
            code, out = run_check(script, tmp_path, mode, tmp_json_path)
            if code == NOT_CHECKED:
                not_checked.append(out)
            elif code == 0:
                continue
            elif code == 2:
                violations_output.append(out or (
                    "%s exited 2 (block) without saying why." % script.name))
            else:
                lint_failures.append(
                    "%s exited %s instead of grading this draft.\n%s"
                    % (script.name, code, out.strip() or "(no output)"))
        report_not_checked(not_checked)
        if lint_failures:
            sys.stderr.write(
                "voice-stop-gate: a voice check FAILED TO RUN, so this draft was "
                "NOT graded. Holding the turn (fail-closed).\n"
                "Fix the lint, then complete the turn.\n\n"
            )
            for output in lint_failures:
                sys.stderr.write(output + "\n")
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
        if lint_failures:
            # Same reasoning as the violations path above: no drain, no spool. A
            # draft nothing graded is not a draft to score.
            sys.exit(2)
    finally:
        for path in (tmp_path, tmp_json_path):
            if path is None:
                continue
            try:
                os.unlink(path)
            except OSError:
                pass

    # THE CLEAN PATH. Score this draft (backgrounded, arrives next turn) and
    # surface whatever a previous turn's worker finished.
    authorship_spool(extract_setoff_draft(text), text, request)
    finish_ok()


if __name__ == "__main__":
    main()
