#!/usr/bin/env python3
"""
voice-stop-gate.py - Final voice check on assistant chat output.

Stop hook for Claude Code.

The voice-lint PostToolUse hook only fires on file writes. Most voice
failures happen in chat output — drafts I produce for the founder to
copy-paste into X, LinkedIn, email, DMs. None of those reach a file.

This hook closes that gap WITHOUT gating ordinary conversation. Per
.claude/rules/voice-enforcement.md, voice rules apply to content sent to
another person, NOT to "conversational responses to the founder." For the LINT
half it keys on explicit publish-intent framing in the assistant's own message
("here's the post/reply/DM/email…", "draft for LinkedIn", "ready to send"). No
such framing means conversational, which is skipped.

It DOES read the founder's request. That line used to say a Stop hook cannot,
which stopped being true when route enforcement landed and was left standing
(Codex minor, ASK-1197). `find_final_user_text` reads THIS turn's founder text
from the transcript: it skips records the harness flags as its own injections,
strips or truncates injected envelopes inside a message, and yields "" rather
than a stale request when his own final message is entirely machine prose.

An injected record does NOT end his turn — not a system reminder, not a hook
context injection, and not this gate's own refusal fed back. His request stays
live until he types something new. Rounds 5-7 tried the opposite and it was a
bypass: after a refusal the assistant may send a CORRECTED DRAFT, which sits in
the same transcript position as an error report, so clearing the request let the
corrected draft ship unverified.

The deadlock those rounds chased is NOT resolved here, and round 15 stopped
pretending it was. Rounds 10-14 relaxed the OUTPUT side -- an unframed completion
got a NOT CHECKED notice and exit 0 -- which measured strictly weaker than the
gate consulting actually runs, on the one instance that has the route lane. This
file syncs over that instance, so the relaxation was a regression. The route path
now enforces unconditionally: a routed request whose completion carries no valid
receipt is refused, whatever the prose looks like. See `enforce_route_receipt`.
The request side still yields three deliberately different values: text he typed (the route lane classifies it and a routed
completion must carry a receipt), "" (no request this turn, so the lane treats it
as not a request), and no transcript at all (the same as ""). The lint half still
does not read it — gating his own words with the voice lint is exactly what
voice-enforcement.md scopes out. When framing IS present, it lints the set-off draft (fenced
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
    # `\b` AFTER the article, and it is load-bearing (ASK-1197 round 12). Without
    # it this matched "drafted a" inside "I have not re-drafted ANYthing yet",
    # so an assistant REPORTING a refusal read as announcing a delivery. That
    # false positive is what made the refusal-echo test look necessary beside a
    # draft, which is the hole round 12 closes. The colon stays outside the
    # boundary group because "drafted:" has no word character after it.
    r"|\bdraft(ed|ing)?\s+((the|a|your|my|for|below)\b|:)"
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

# --- what counts as a draft, and the boundary this gate does not cross ----------
#
# ROUND 10 REMOVED the cherry-picked R8 net (`candidate_draft`, `_blocks`,
# `_disqualified`, from f918134c) from THIS branch. It still lives on
# `fix/candidate-draft-one-definition` and ships on its own PR; nothing here
# calls it any more, and an uncalled symbol in a fanout file is dead weight that
# the next reader has to re-derive.
#
# WHY IT LEFT. It answered "is this draft-shaped prose" without requiring
# framing, and every attempt to use that answer produced either a deadlock or a
# bypass: rounds 5 and 9 refused ordinary replies and clarifying questions, and
# rounds 6, 7 and 8 let a draft through unverified. Two full rounds of size and
# bullet heuristics did not converge.
#
# FRAMING IS THE CONTRACT. The producers of record (consulting `cycle.py`, X/idea
# and reddit) ALWAYS emit RECEIPT then DRAFT. A handoff that lost its framing is
# not something this gate can classify from prose, and pretending otherwise is
# what the last five rounds cost. So: framed output is verified or refused;
# unframed output under a routed request gets a NOT VERIFIED notice and exit 0.
#
# That boundary is a known, recorded gap, not an oversight: spillover sp-6ce17a23.
# The notice text names that id so a reader lands on the decision instead of
# guessing whether the silence is a bug.

_QUOTE_RE = re.compile(r"(?m)^>\s?(.*)$")

# THE LINT FLOOR, and it is the one main uses (ASK-1197 round 14). The port
# briefly dropped it to 40, which newly voice-linted 40-79 byte framed messages
# and could exit 2 on the 24 lane-less instances -- contradicting this PR's own
# "identical to before the port" claim. A port that changes behaviour on 24
# instances is not a port. One value, main's value; `TestTheDraftFloor` pins the
# 40-79 band in both directions so the number cannot drift again.
#
# Raising it back is a KNOWN trade: F9's shipped turn fell through this floor,
# and that stays true on main too. It is not this PR's to change.
MIN_TEXT_BYTES = 80


def extract_publishable(text):
    """The draft content to LINT, or "" when the message is conversational.

    PUBLISH FRAMING ONLY (Codex major, ASK-1197 round 13). Round 12 let this read
    LANE markers too, so on the 24 registered instances with no `q-consult`
    pipeline, pasting a producer's output -- which carries a receipt block and a
    reddit wrapper -- got voice-linted and BLOCKED the turn where main exits 0.
    Lane markers are route framing. They mean "a producer emitted this", which is
    a question for the route path; they are not the founder announcing a delivery.
    The `=== DRAFT ===` marker is read here because it is the delivery separator
    the assistant itself writes, not a producer artifact.

    ECHO_LINT_EXEMPT, evaluated FIRST and unconditionally. The voice lint never
    grades this gate's own refusal, framed or not. Round 12 made the echo test
    unreachable whenever framing was present, so an assistant quoting the refusal
    inside a framed message got its own refusal voice-linted and the turn was held
    again -- the deadlock, through the lint instead of the route lane.

    Evaluated on the SLAB rather than the whole message, which is narrower than
    "framed or not" and deliberately so: a real fenced draft with the token pasted
    in the surrounding chat still gets linted, because the slab does not carry the
    mark. The residual (a token pasted INSIDE the draft itself) is recorded as
    sp-98247c8e; the route path still verifies that turn either way, because
    ECHO_NEVER_EXEMPTS_ROUTE.
    """
    draft = _publish_framed(text) or _draft_marker_slab(text)
    if _is_own_refusal_echo(draft):
        return ""
    return draft


def extract_setoff_draft(text):
    """The set-off draft ONLY -- prose fences and blockquotes, never a fallback.

    Separate from `extract_publishable` on purpose (authorship reporting,
    2026-08-17): that one falls back to the whole message when framing is present
    but nothing is set off, which is right for the lint and wrong for the
    authorship scorer, because the fallback sweeps surrounding engineering chat
    into the thing being measured. The lint's false positive costs one stdlib
    subprocess; this one costs a 319MB torch load.
    """
    draft = _setoff_segments(text)
    return "" if _is_own_refusal_echo(draft) else draft


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
    # ONE ENVELOPE, ONE WRITER. `systemMessage` on exit 0 is the ONLY hook field
    # that puts text in front of the USER rather than the model. Plain stdout from
    # a Stop hook is dropped, and `additionalContext` reaches Claude, not him.
    # The NOT CHECKED notices are joined into this same document rather than
    # printed separately, because two JSON objects on one stream is one object to
    # every consumer that parses it. Notices first: they describe THIS turn, while
    # a drained score is a previous turn's number arriving late.
    parts = list(_PENDING_NOTICES)
    if line:
        parts.append(line)
    if parts:
        print(json.dumps({"systemMessage": "\n".join(parts)}))
    sys.exit(0)


# A record the HARNESS injected, not something a person typed. These are
# top-level fields on the transcript record, and `_walk_transcript` used to
# throw them away by yielding only `record["message"]` -- which is precisely why
# the text filters below kept having to guess from prose.
_META_FLAGS = ("isMeta", "turnCompanion")


def _walk_transcript(transcript_path, want_record=False):
    """Yield each message, or `(record, message)` when the caller needs the flags.

    THE SCAR (2026-09-01, third occurrence of this deadlock). A skill loaded and
    the harness wrote that skill's 16,584-character body as its OWN `user`
    record, carrying `isMeta: true` and `turnCompanion: true` and NO command tags
    at all. This walker dropped those flags, so `find_final_user_text` read the
    skill's documentation as the founder's request. Two of that document's own
    sentences classify UNSUPPORTED, and the gate then refused every completion in
    the session -- including the turn reporting the block -- while his actual
    message, "Explain this simply no tables", is correctly not-routed.

    The two earlier rounds were fixed by enumerating carriers in a regex
    (`_INJECTED_BLOCK`, then `cross-session-message`). That is the shape that
    keeps failing: each round adds the carrier that just bit, and the next one is
    invisible until it bites. The harness already labels these records. Read the
    label.
    """
    if not transcript_path or not Path(transcript_path).exists():
        return
    for line in Path(transcript_path).read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except Exception:
            continue
        message = record.get("message", {})
        if isinstance(message, dict):
            yield (record, message) if want_record else message


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


# A `user` turn the FOUNDER did not type. The harness injects background-task
# results, hook output and context reminders on the user role, so the newest
# `user` message is often a machine's prose. 2026-08-31: a subagent's completion
# report contained the token `reply-lane`, `_UNSUPPORTED_COMPOUND` matched it,
# and `enforce_route_receipt` refused the turn with "surface format has no
# registered generation route" -- a writing request nobody made, from a report
# about the work being finished. Stripping the blocks is not enough: a
# notification whose text sits OUTSIDE any tag would still read as his words,
# so a turn that is entirely machine-injected is skipped whole.
_INJECTED_BLOCK = re.compile(
    # `cross-session-message` added 2026-08-31 (sp-23053db5): a peer Claude
    # session's message arrives in a `user` turn, so without it this enumeration
    # answered "the founder typed this" about another agent's words. Its prose
    # classified AMBIGUOUS and deadlocked every turn in the session, including the
    # one reporting the block. Adding it removes no coverage of his own text.
    r"<(system-reminder|task-notification|command-name|command-message|"
    r"command-args|local-command-stdout|function_results|user-prompt-submit-hook|"
    r"cross-session-message)"
    r"\b.*?</\1>",
    re.I | re.S,
)
_INJECTED_OPENER = re.compile(
    r"^\s*(?:<(?:system-reminder|task-notification|command-name|"
    r"local-command-stdout|user-prompt-submit-hook|cross-session-message)\b"
    r"|\[SYSTEM NOTIFICATION"
    # THE ENVELOPE, NOT THE NAME (Codex minor, ASK-1197 round 4). This arm
    # was `<event>(:matcher)? hook\b`, which matches the founder's OWN first
    # words: "Stop hook keeps eating my linkedin drafts, write me a post about
    # it" opens with a hook name, so his whole request was erased as machine
    # prose, `find_final_user_text` returned "", and route enforcement was
    # skipped on a turn the real classifier routes. A gate that a sentence can
    # switch off is not a gate.
    #
    # A real injection is LABELLED: `PostToolUse:Bash hook additional context:`,
    # `Stop hook feedback:` -- the name, the word hook, then a short label and a
    # colon. That colon is the machine's punctuation and is what is matched now.
    # Prose about a hook does not carry it. This deliberately does NOT enumerate
    # label words: enumerating carriers is the shape that failed twice above.
    # STILL TOO WIDE AFTER ROUND 3 (Codex major, ASK-1197 round 14). Requiring a
    # colon was not enough, because a founder sentence reaches one within four
    # words: "Stop hook broke again: here is the trace" was erased, so
    # `find_final_user_text` returned "" and route enforcement was skipped for
    # that turn. That is the same enforcement bypass round 3 was fixing, one
    # sentence shape over.
    #
    # The machine shape is required in FULL now, in one of the two forms actually
    # measured (11,156 transcript files, 621 records):
    #
    #   (a) the header owns its line -- `Stop hook feedback:` then a newline,
    #       which is the Stop envelope's shape;
    #   (b) the event carries a MATCHER -- `PostToolUse:Bash hook additional
    #       context:` -- which is machine syntax the founder does not type.
    #
    # A sentence that merely opens with a hook name and hits a colon mid-line
    # matches neither. `(?=\n|\Z)` rather than `$` on purpose: this pattern is
    # not compiled with re.M, and adding it would let `^` match at every line
    # start, turning an OPENER test into a scan of the whole record.
    r"|(?:PreToolUse|PostToolUse|Stop|SessionStart|UserPromptSubmit)"
    r"(?::[\w.*-]+\s+hook\s+[\w-]+(?:\s+[\w-]+){0,3}:"
    r"|\s+hook\s+[\w-]+(?:\s+[\w-]+){0,3}:[ \t]*(?=\n|\Z)))",
    re.I,
)
# A SKILL or SLASH-COMMAND invocation injects its whole BODY as bare markdown
# after these tags. The body is not wrapped in anything, so `_INJECTED_BLOCK`
# removed the little tags and left thousands of words of documentation standing
# as "what the founder typed".
#
# THE SCAR, and this is its THIRD occurrence (2026-09-01). The comment on
# `_INJECTED_BLOCK` above records the second: a peer session's prose classified
# AMBIGUOUS and "deadlocked every turn in the session, including the one
# reporting the block." This is the same failure with a skill body as the
# source. `/workflow-authoring` loaded, and two of its own sentences --
# "compose novel harnesses when the task calls for it" and "Write/Edit and
# re-invoke Workflow with scriptPath" -- classify UNSUPPORTED, so the gate
# refused every completion while the founder's actual message,
# "Explain this simply no tables", is correctly not-routed.
#
# His typed words come FIRST and the injection follows, so the fix is a
# truncation, not another tag to enumerate. Enumerating tags is what failed
# twice: each round adds the one carrier that just bit, and the next carrier is
# invisible until it does.
#
# Held by the test script `q-system/.q-system/tests/test_voice_stop_gate_route_receipt.py`
# (TestFounderTypedText), not by this comment: a skill body truncated in prose and
# not in a test is the same hole wearing a paragraph.
_COMMAND_INJECTION_MARK = re.compile(
    r"<(?:command-name|command-message|command-args|skill-format|"
    r"local-command-stdout)\b",
    re.I,
)


def founder_typed_text(candidate):
    """Strip machine-injected prose from one `user` turn, or reject it entirely.

    A command or skill invocation is a TRUNCATION, not a tag removal: his typed
    words come first and the injected body follows unwrapped, so everything from
    the first command marker onward is the machine's text. See the scar note on
    `_COMMAND_INJECTION_MARK`.
    """
    if not candidate:
        return ""
    if _INJECTED_OPENER.search(candidate):
        return ""
    mark = _COMMAND_INJECTION_MARK.search(candidate)
    if mark:
        candidate = candidate[:mark.start()]
    return _INJECTED_BLOCK.sub(" ", candidate).strip()


def find_final_user_text(transcript_path):
    """His last message. The trigger signal the model cannot get wrong.

    Deliberately NOT used by the lint: voice-enforcement.md scopes the lint to
    what the assistant hands over, and reading his request into that decision
    would gate his own words. It is used only to decide whether the draft is
    worth measuring.

    Only text the FOUNDER typed counts. See `_INJECTED_BLOCK` for the scar.

    THIS TURN'S MESSAGE OR NOTHING (ASK-1197 round 2). This kept the last
    NON-EMPTY candidate, so a turn whose own final message is entirely machine
    prose -- a slash command, a hook body, a system-reminder -- silently reverted
    to an OLDER message, and `enforce_route_receipt` then verified THIS draft's
    request hash against words the founder typed some turns ago. Dropping the
    injected prose was right; substituting a different turn is a second defect
    wearing the first one's fix. A turn with no founder text must say so.

    THE SEAM IS TEXT vs NO TEXT, not empty vs non-empty, and getting that wrong
    is how the obvious fix breaks everything. Every agentic turn ends
    user -> assistant(tool_use) -> user(tool_result) -> assistant(text): that
    trailing record is `role: user`, carries no text block, and is NOT flagged
    isMeta. Assigning unconditionally would blank his request on nearly every
    real turn. So a record with no text at all is transport and is skipped; a
    record that HAS text which `founder_typed_text` empties is this turn, and
    yields "". Held by `TestThisTurnsRequestOrNothing`.
    """
    text = ""
    for record, message in _walk_transcript(transcript_path, want_record=True):
        if message.get("role") != "user":
            continue
        raw = _message_text(message)
        if not raw.strip():
            # No text at all: a tool_result or other transport record. It neither
            # ends the turn nor erases anything (round 2 -- otherwise his request
            # is blanked on every tool-using turn).
            continue
        # THE GATE'S OWN FEEDBACK IS SKIPPED, NOT AN ENDING (ASK-1197 round 8,
        # reverting rounds 5-7). Three rounds tried to answer "is his request
        # still live" from transcript ORDER, and it cannot be answered there: after
        # a refusal the assistant may send a CORRECTED DRAFT (which must be
        # verified) or an error report (which must not deadlock), and those two are
        # in the identical position. Clearing the request made the corrected draft
        # bypass verification entirely -- a worse defect than the deadlock it was
        # fixing.
        #
        # The two cases are distinguishable by the OUTPUT, not the input, so the
        # decision moved to `enforce_route_receipt`: no draft in the completion
        # means nothing to verify (notice, exit 0); a draft with no valid receipt
        # is refused. His request stays live until he types something new.
        #
        # `_REFUSAL_MARK` and `refuse()` are kept: the mark is what makes this
        # gate's own feedback identifiable at all, and a single refusal writer is
        # worth having regardless of who reads the mark.
        if any(record.get(flag) is True for flag in _META_FLAGS):
            # (b) EVERY OTHER INJECTED RECORD: a UserPromptSubmit
            # additionalContext, a system reminder, a peer session's message.
            # Skipped -- never his words, and never an ending either. Round 6
            # ended the turn here and that was a real bypass: an injected context
            # record between his routed request and the draft blanked the request
            # and the draft shipped with no receipt check.
            continue
        text = founder_typed_text(raw)
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
#: THE ONE TOKEN THIS GATE PUTS IN ITS OWN REFUSALS (Codex major, ASK-1197
#: round 7). Rounds 2, 5 and 6 each patched `find_final_user_text`'s ordering
#: rule, and round 6 shipped a real bypass because of it: it ended the founder's
#: turn on ANY text-bearing meta record, so a UserPromptSubmit additionalContext
#: (lessons-inject, voice-dna-loader) or a system reminder landing between his
#: routed request and the draft blanked the request and the draft shipped
#: unverified.
#:
#: The wrong assumption was that "this turn's request" is derivable from record
#: ORDER plus the meta flag. It is not: two kinds of injected record mean
#: opposite things.
#:
#:   (a) THIS GATE'S OWN REFUSAL fed back by the harness. The assistant is now
#:       answering the gate; the founder's request is no longer the subject; his
#:       turn is over. Skipping it re-arms the refusal forever (round 5).
#:   (b) EVERYTHING ELSE injected -- hook context, reminders, tool_result
#:       transport. His request is still live and the draft still owes a receipt.
#:
#: The gate can tell (a) from (b) with certainty because it WRITES (a). So the
#: recogniser is one constant, emitted by `refuse` and matched by the walker, and
#: the two cannot drift apart because there is nowhere else to change it. It is
#: deliberately NOT the `voice-stop-gate:` prefix: the NOT CHECKED advisory
#: carries that too, and that advisory does not end anything.
_REFUSAL_MARK = "[voice-stop-gate:held-this-turn]"


def _mask_fences(text):
    """A SAME-LENGTH copy of `text` with fenced blocks blanked out.

    A MARKER INSIDE A FENCE IS A QUOTE, NOT FRAMING (Codex major, ASK-1197 round
    11). Round 10 let the lint key on a bare `=== DRAFT ===`, so an engineering
    message showing that marker inside a code fence -- this file's own tests and
    docs do it constantly -- was treated as a delivery and voice-linted, and the
    Stop hook exited 2 where the base version exited 0.

    Same length, not stripped, because every caller searches this copy and then
    slices the ORIGINAL. Offsets have to line up or the slab is cut in the wrong
    place. Newlines are preserved so line-anchored patterns still see real lines.

    Prose fences are NOT masked away for `_setoff_segments`: that extractor reads
    fence BODIES on purpose. Masking is for marker detection only.
    """
    if not text:
        return ""
    out = list(text)
    for match in _FENCE_RE.finditer(text):
        for index in range(match.start(), match.end()):
            if out[index] != "\n":
                out[index] = " "
    return "".join(out)


def _mask_lane_markers(masked):
    """Blank the lane MARKER LINES in an already-fence-masked copy.

    A LANE WRAPPER IS NOT AN ANNOUNCEMENT (ASK-1197 round 13). The reddit wrapper
    line literally reads `=== REDDIT DRAFT (ATTENDED, PUBLISHES NOTHING) ===`, and
    `_PUBLISH_MARKER_RE` matched "REDDIT DRAFT" inside it -- so a pasted producer
    output framed itself as a publish delivery and got voice-linted on the 24
    lane-less instances. The producer's own wrapper cannot be the founder
    announcing a post.

    Same same-length contract as `_mask_fences`, for the same reason: callers
    slice the original.
    """
    out = list(masked or "")
    for pattern in (_RECEIPT_CLAIM_RE, _REDDIT_DRAFT_RE, _DRAFT_MARKER_RE):
        for match in pattern.finditer(masked or ""):
            for index in range(match.start(), match.end()):
                if out[index] != "\n":
                    out[index] = " "
    return "".join(out)


def _strip_lane_trailers(slab):
    """Drop the producer's posting advice from a draft slab.

    The receipt hashes the draft body ALONE, and the lanes print a reddit title
    line and review footer, or the X how-to-post card and VOICE note, around it.
    Earliest trailer wins, so a slab carrying two of them is cut at the first.
    """
    slab = _REDDIT_TITLE_RE.sub("", (slab or "").lstrip("\n"), count=1)
    cuts = [m.start() for m in
            (rx.search(slab) for rx in (_REDDIT_FOOTER_RE, _ADVISORY_AFTER_DRAFT_RE))
            if m is not None]
    if cuts:
        slab = slab[:min(cuts)]
    return slab.strip()


def _after_receipt_block(text):
    """Everything after the receipt JSON, or None when there is no receipt block.

    None and "" are different answers on purpose: None means no receipt was
    claimed, "" means one was claimed and nothing followed it. The claim is looked
    for in a fence-masked copy, so a quoted receipt marker claims nothing.
    """
    text = text or ""
    claim = _RECEIPT_CLAIM_RE.search(_mask_fences(text))
    if claim is None:
        return None
    payload = text[claim.end():]
    stripped = payload.lstrip()
    try:
        _value, end = json.JSONDecoder().raw_decode(stripped)
    except json.JSONDecodeError:
        return ""
    return stripped[end:]


def _publish_framed(text):
    """The publish-sentence reading: the pre-R8 body, with framing noise masked.

    The sentence is looked for in a copy with fences AND lane marker lines
    blanked, so neither an assistant QUOTING "here's the post" inside a fence nor
    a producer's own `=== REDDIT DRAFT ... ===` wrapper frames a delivery. The
    set-off segments are read from the ORIGINAL, because fence bodies are exactly
    what that reading wants.
    """
    text = text or ""
    # TWO MASKS, KEPT APART. `fence_masked` still carries the lane markers; the
    # publish-sentence test needs them blanked, and the producer test below needs
    # them intact. Collapsing these into one name is a bug I shipped and the
    # round 15 tests caught: searching the lane-masked copy for a receipt marker
    # never matches, because that mask is what removed it.
    fence_masked = _mask_fences(text)
    masked = _mask_lane_markers(fence_masked)
    if not _PUBLISH_MARKER_RE.search(masked):
        return ""
    setoff = _setoff_segments(text)
    if setoff:
        return setoff
    # A PRODUCER RECEIPT BEATS THE WHOLE-MESSAGE FALLBACK (Codex major, PR #295
    # round 15, finding 1). The fallback below returns `text.strip()`, so an
    # assistant that ANNOUNCES a producer handoff ("Here is the post for X.")
    # and pastes it underneath got the entire 5023-byte envelope voice-linted:
    # receipt JSON, how-to-post card and all. Measured -- 10 capitalization
    # violations, every one of them on the producer's own "Image must show one
    # of:" bullets, exit 2, a valid handoff blocked. A gate that false-blocks
    # correct work is a gate that gets switched off.
    #
    # When a receipt (or the reddit wrapper) is present the LANE decided where
    # the draft starts, so read its answer instead of guessing from the message.
    #
    # DELIBERATELY NARROWER THAN "any marker" (which is what the finding
    # proposed). Keyed on a PRODUCER artifact, never on a bare `=== DRAFT ===`,
    # because the assistant can write that line itself: letting it win here
    # would truncate a slab the publish sentence already claimed, which is
    # exactly the round 10 bypass round 11 closed.
    # `test_a_bare_draft_marker_still_does_not_truncate_the_slab` is that control.
    #
    # This can only ever lint LESS than the fallback did, never more, so it
    # cannot newly block a turn on the 24 lane-less instances (round 13).
    if (_RECEIPT_CLAIM_RE.search(fence_masked)
            or _REDDIT_DRAFT_RE.search(fence_masked)):
        produced = _route_draft(text)
        if produced:
            return produced
    return text.strip()


def framed_draft(text):
    """The draft this turn EXPLICITLY hands over, or "" when nothing is framed.

    ONE FRAMING TEST, TWO CONSUMERS: the lint asks it what to grade, the route
    path asks it what to verify.

    PUBLISH FRAMING FIRST, LANE WRAPPER SECOND (Codex minor, round 11). Round 10
    had this backwards, so a trailing bare `=== DRAFT ===` line truncated a slab
    that the publish sentence had already claimed and content the base version
    blocked started passing. When the assistant has announced a delivery, the slab
    it announced is the draft; a lane marker inside it does not shrink it.

    `enforce_route_receipt` still hashes `_route_draft` directly, because the
    receipt covers the producer's draft bytes and not the announcing sentence.

    A STRAIGHT PIPELINE: `_publish_framed` and `_route_draft` are leaves over
    their own helpers, and neither reaches back here. See the DAG test.
    """
    return _publish_framed(text) or _route_draft(text)


def _setoff_segments(text):
    """Prose fences and blockquotes, joined. A LEAF: calls no other extractor."""
    segments = [body for info, body in _FENCE_RE.findall(text or "")
                if info.strip().lower() in _PROSE_FENCE_LANGS]
    segments += _QUOTE_RE.findall(text or "")
    return "\n\n".join(seg.strip() for seg in segments if seg.strip())


def _is_own_refusal_echo(text):
    """Is this completion this gate's own refusal, quoted back?

    PRESENCE IS ENOUGH NOW, and that is a consequence of WHERE this is called
    from rather than a weakening. `classify_output` decides framing first and only
    reaches here when nothing was framed, so there is no draft standing beside the
    token for a presence test to hide. Every earlier version compared the mark
    against the surrounding text -- substring, then dominance -- and both were
    gameable exactly because they ran beside a draft.

    The mark is text this gate WRITES (see `refuse`), so recognising it needs no
    heuristic.
    """
    return bool(text) and _REFUSAL_MARK in text


def refuse(message):
    """Write one refusal to stderr, marked, and hold the turn. Never returns.

    THE ONLY WRITER of an exit-2 refusal in this file, so `_REFUSAL_MARK` is on
    every one of them by construction. Five call-sites used to each format their
    own line; a marker maintained across five copies is a marker that is missing
    from the sixth.
    """
    # The human sentence is unchanged and the mark is its OWN line. The first
    # attempt folded the mark into the prefix and broke
    # `test_a_surface_lint_that_crashes_holds_the_turn`, which pins the wording a
    # reader actually sees. A machine token has no business rewriting the text a
    # person reads; it sits beside it.
    sys.stderr.write(f"voice-stop-gate: {message}\n{_REFUSAL_MARK}\n")
    sys.exit(2)


NOT_CHECKED = "NOT_CHECKED"

#: Notices queued for the single `systemMessage` emitted by `finish_ok`. Module
#: level because the two enforcement call-sites in `main` are far apart and a
#: threaded return value would have to survive every branch between them.
_PENDING_NOTICES = []


def report_not_checked(lines, out=None, err=None):
    """Surface NOT CHECKED on the channel a SUCCESSFUL hook is actually read on.

    The first version of this wrote to stderr only, on a path that then exits 0.
    A Stop hook's stderr is fed back when it exits 2; on the success path it goes
    nowhere. So the warning that a draft had not been graded was itself never
    delivered -- the exact defect this whole change exists to close, reproduced
    inside the fix for it (Codex major, PR #290).

    PLAIN STDOUT IS NOT THAT CHANNEL (Codex major, ASK-1197 round 4; the
    contradiction captured as sp-f5144496). This file already knew the answer and
    disagreed with itself: `finish_ok` twenty lines up says "plain stdout from a
    Stop hook is dropped" and emits `{"systemMessage": ...}` instead, and
    `test_voice_stop_gate_drain_only.py` asserts that JSON shape on a real run.
    This function wrote bare text to the same stream and called it delivered. So
    an UNCHECKED receipt rendered exactly like a verified one in the normal UI --
    the `run_check` scar (PR #290) reproduced a second time inside its own fix.

    QUEUED, NOT PRINTED, and the queue is the point. `finish_ok` already emits one
    `systemMessage` for the drained authorship score; a second `print(json.dumps(...))`
    here would put TWO JSON documents on stdout and a consumer reading one would
    see the notice or the score, never both. One writer to that stream, so the
    two cannot race or truncate each other.

    A REFUSAL STILL WINS. Every exit-2 path leaves via `sys.exit(2)` without
    reaching `finish_ok`, so a queued notice is discarded when the turn is held --
    which is correct: the block is the louder and more accurate message, and the
    stderr copy below keeps the notice in the record either way.
    """
    for line in lines:
        if line not in _PENDING_NOTICES:
            _PENDING_NOTICES.append(line)
        # stderr keeps the line in the run record, and surfaces it if this is ever
        # called from a blocking path. It is NOT the delivery channel at exit 0.
        (err or sys.stderr).write(line + "\n")
    if out is not None:
        # Test seam only: a caller that hands its own stream is inspecting what
        # would be queued. The real path has exactly one stdout writer.
        out.write("\n".join(lines) + ("\n" if lines else ""))


# --- route-receipt enforcement (OPTIONAL, same posture as the registry below) ---
#
# Ported into the skeleton on 2026-09-02 (ASK-1197). It shipped into ONE instance
# and no skeleton, and `q-system/` is an rsync --delete fanout target, so the next
# skeleton fanout would have deleted a working gate -- the voicekit class (19
# instances, 2026-08-07). Measured across the 25 registered instances that day:
# 1 carried these five functions, 0 skeletons did.
#
# THE HARD CONSTRAINT, and it outranks the feature, exactly as it does for the
# channel registry below: 24 of the 24 instances carrying this file have no
# `q-consult/pipeline`. They must behave as they did before this block existed --
# no import error, no traceback, and no per-turn line. A gate that prints on every
# turn of 24 instances gets switched off, and a gate that is off protects nothing.
#
# BUT NOT SILENT WHEN A RECEIPT IS CLAIMED. A turn carrying a `=== ROUTE RECEIPT ===`
# block is a turn whose producer believes a verifier ran. Passing that quietly
# because the verifier is not installed is the `run_check` scar twenty lines up
# (PR #290): the value a missing check returns must differ from the value a clean
# check returns. So an uninstalled lane is silent on an ordinary turn and reports
# NOT CHECKED on a turn that claims a receipt.
#
# AND INSTALLED-BUT-BROKEN HOLDS. `_route_context` raising rather than returning
# None is the difference, and it is the difference Codex found twice in
# `channel_surface_lint`: an exception escaping this file makes Python exit 1, and
# a Stop hook exiting 1 does NOT hold the turn, so a half-installed lane would
# fail OPEN. The three outcomes are separated on purpose.
ROUTE_PIPELINE_REL = Path("q-consult") / "pipeline"
ROUTE_RECEIPT_MARKER = "=== ROUTE RECEIPT ==="
ROUTE_DRAFT_MARKER = "=== DRAFT ==="

# THE REDDIT LANE EMITS A DIFFERENT WRAPPER AND NO `=== DRAFT ===` AT ALL (Codex
# major, ASK-1197 round 3). Captured from the producer of record on 2026-09-02 --
# consulting bc4fba6c, `pipeline.cycle.draft_reddit_original` printed by
# `pipeline.social` -- by running that lane, not from memory:
#
#     === REDDIT DRAFT (ATTENDED, PUBLISHES NOTHING) ===
#     TITLE: <title>
#
#     <body>
#
#     FOUNDER REVIEW REQUIRED: subreddit rules, and the six checks above are flags...
#
# and the receipt hashes `draft.body` ALONE (cycle.py:1387 passes `draft.body` to
# `create_receipt`; `output_hash` normalizes only NFC and line endings, so the bytes
# are exact). `_route_draft` had no reddit branch, so it fell through to
# `extract_publishable`, which returns the title line and the review footer as well.
# Every receipt-bearing Reddit draft therefore failed the output-hash comparison and
# was refused as a mismatch on every direct handoff.
#
# EXTRACTED BY MARKER, NEVER BY POSITION. The title line and the footer are both
# named shapes, so a lane that adds a subreddit header or reorders these blocks
# breaks loudly instead of silently hashing the wrong slab.
ROUTE_REDDIT_DRAFT_MARKER = "=== REDDIT DRAFT (ATTENDED, PUBLISHES NOTHING) ==="
# The parenthetical is not pinned: it is a caption on the same marker, and pinning
# prose is how a consumer breaks on a producer's wording change.
_REDDIT_DRAFT_RE = re.compile(r"(?m)^[ \t]*=== REDDIT DRAFT\b[^\n]*===[ \t]*$")
_REDDIT_TITLE_RE = re.compile(r"\A[ \t]*TITLE:[^\n]*\n")
_REDDIT_FOOTER_RE = re.compile(r"(?m)^[ \t]*FOUNDER REVIEW REQUIRED:")
# Same anchoring as `_RECEIPT_CLAIM_RE`: a producer puts this marker on its own
# line, a sentence about the gate does not.
_DRAFT_MARKER_RE = re.compile(
    r"(?m)^[ \t]*" + re.escape("=== DRAFT ===") + r"[ \t]*$")

# THE IDEA LANE PRINTS ADVISORY BLOCKS AFTER THE DRAFT (Codex major, ASK-1197
# round 5; my own capture sp-20bdfcd9). `social.py` prints `=== DRAFT ===` + text
# and then, still inside the same branch, the VOICE note and the how-to-post card.
# The receipt hashes `final_text` ALONE (cycle.py:1210), so an extractor that
# returned everything after the draft marker hashed roughly twenty lines of
# posting advice into the draft and rejected every genuine X / LinkedIn receipt
# as an output mismatch -- the same defect the reddit branch above fixed, one lane
# over. Fixing one and not its sibling is the asymmetry that keeps recurring here.
#
# Captured from the producer on 2026-09-02 by running
# `pipeline.cycle.draft_from_idea` (consulting bc4fba6c) with a stubbed writer:
#
#     === DRAFT ===
#     <text>
#
#     === HOW TO POST THIS ===
#     Archetype: The Thread
#     ...
#
# ONE SHAPE COVERS X AND LINKEDIN. `social.py`'s `idea` branch has no channel
# fork between the draft marker and the card; the card's CONTENT varies by
# channel, its header does not. Read off the source, not assumed.
#
# TRUNCATED ON THE MARKER, NEVER ON THE WORD. `VOICE: NOT CHECKED` is matched at
# line start only, because a draft may legitimately say "my voice" mid-sentence --
# the captured fixture does exactly that, on purpose.
_ADVISORY_AFTER_DRAFT_RE = re.compile(
    r"(?m)^[ \t]*(?:"
    r"=== HOW TO POST THIS ===[ \t]*$"
    r"|VOICE: NOT CHECKED\b"
    r"|REPLY: \d+ words,"
    r")")

# WHAT COUNTS AS A CLAIMED RECEIPT (Codex minor, ASK-1197 round 2). The
# uninstalled-lane branch decided this by substring, so an assistant that merely
# NAMES the marker in a sentence -- explaining the gate, quoting a review comment,
# writing this very file -- printed NOT CHECKED on 24 instances that were never
# asked to check anything. A false line on ordinary turns is exactly how a gate
# gets switched off, which is the hard constraint the whole block is written under.
#
# A producer emits the marker on a line of its own, with the JSON on the next
# line; a sentence does not. So the shape is the check, and it is defined ONCE and
# used by both the claim test and the extractor, because two spellings of "a
# receipt is present" is how one of them ends up hardened and the other does not.
#
# WHAT IT STILL CANNOT TELL APART: a fenced code block illustrating the format.
# That is a documented turn, not a producer turn, and the residual cost is one
# advisory line rather than a per-turn line on every instance.
_RECEIPT_CLAIM_RE = re.compile(
    r"(?m)^[ \t]*" + re.escape(ROUTE_RECEIPT_MARKER) + r"[ \t]*$")


class RouteBoundaryError(ValueError):
    """A routed completion lacks a current shared route receipt."""


def _route_context():
    """The q-consult route modules, or None when this instance has no route lane.

    None is the 24-instance case and it is SILENT by design (see the block comment).
    Raises RouteBoundaryError when the lane directory IS present and does not
    import, because that is a broken verifier rather than an absent one.
    """
    pipeline_dir = INSTANCE_ROOT / ROUTE_PIPELINE_REL
    if not pipeline_dir.is_dir():
        return None
    # RESOLVED, and both sides of the comparison below are (Codex minor, ASK-1197
    # round 2). The identity check reads `Path(module.__file__).resolve().parents`,
    # which is always the real path; comparing that against an unresolved
    # `pipeline_dir` means an instance whose `q-consult` is a SYMLINK -- which is
    # how the consulting checkout is actually reached -- never matches its OWN
    # modules, so the correct lane is refused and the gate hard-blocks every turn
    # over a path spelling. The message printed the unresolved path too, naming
    # something the code never compared against.
    pipeline_dir = pipeline_dir.resolve()
    sys.path.insert(0, str(INSTANCE_ROOT / "q-consult"))
    try:
        from pipeline import (audit_only_routes, route_classifier, route_contract,
                              route_registry)
    except Exception as exc:
        raise RouteBoundaryError(
            f"route lane is installed at {pipeline_dir} but did not import: {exc}"
        ) from exc
    # WHICH `pipeline` DID WE GET (Codex minor, ASK-1197 round 1). `sys.path.insert`
    # loses to `sys.modules`: if anything in the process already imported a package
    # named `pipeline` -- a sitecustomize, an instrumentation shim, another tool on
    # PYTHONPATH -- Python hands back the cached one and never looks at the path we
    # just prepended. A compatible impostor would then supply the verifier, and the
    # gate would consume receipts against the wrong store while reporting success.
    # Identity is cheap to check and the failure is silent, so it is checked.
    for module in (route_classifier, route_contract, audit_only_routes, route_registry):
        origin = getattr(module, "__file__", None)
        if origin is None or pipeline_dir not in Path(origin).resolve().parents:
            raise RouteBoundaryError(
                f"route lane resolved {module.__name__} to {origin}, which is not "
                f"under {pipeline_dir}. Refusing rather than verifying receipts "
                f"against a package that merely shares the name.")
    return route_classifier, route_contract, audit_only_routes, route_registry


def _draft_marker_slab(text):
    """The slab after a `=== DRAFT ===` marker, or "".

    Split out of `_route_draft` so the LINT can read this marker without also
    reading the producer-only lane markers (round 13, finding 1). Fence-masked,
    like every other marker read.
    """
    text = text or ""
    marker = _DRAFT_MARKER_RE.search(_mask_fences(text))
    if marker is None:
        return ""
    return _strip_lane_trailers(text[marker.end():])


def _route_draft(text):
    """The bytes the producer hashed, for whichever lane emitted this handoff.

    A LEAF apart from its two helpers; see `framed_draft` for the recursion this
    shape replaced.

    Markers are looked for in a FENCE-MASKED copy and sliced out of the original,
    so a message quoting `=== DRAFT ===` or the reddit wrapper inside a fence
    frames nothing (round 11).

    Three branches, most specific first, "" when none match:
      (b) the reddit wrapper -- it carries no `=== DRAFT ===` at all;
      (c) the `=== DRAFT ===` marker;
      (a) a receipt block with neither, which is the case that used to recurse.
    """
    text = text or ""
    masked = _mask_fences(text)
    reddit = _REDDIT_DRAFT_RE.search(masked)
    if reddit is not None:
        return _strip_lane_trailers(text[reddit.end():])
    marker = _DRAFT_MARKER_RE.search(masked)
    if marker is not None:
        return _strip_lane_trailers(text[marker.end():])
    after = _after_receipt_block(text)
    if after is None:
        return ""
    return _strip_lane_trailers(after)


def _receipt_block(text):
    # Same shape test as the claim check, from the same compiled pattern, on a
    # fence-masked copy so a quoted example is not parsed as a receipt.
    text = text or ""
    masked = _mask_fences(text)
    claim = _RECEIPT_CLAIM_RE.search(masked)
    if claim is None:
        return None
    payload = text[claim.end():].lstrip()
    try:
        value, _end = json.JSONDecoder().raw_decode(payload)
    except json.JSONDecodeError as exc:
        raise RouteBoundaryError("route receipt block is not valid JSON") from exc
    return value




#: What `classify_output` saw. Three values because the gate emits three
#: different notices, and a notice that names the wrong thing is worse than none:
#: a reader who is told "no draft found" about an echo goes looking for a bug.
OUTPUT_DRAFT = "draft"
OUTPUT_REFUSAL_ECHO = "refusal_echo"
OUTPUT_NO_DRAFT = "no_draft"


def classify_output(assistant_text):
    """What this completion hands over: a framed draft, this gate's own refusal
    echoed back, or nothing.

    NOT AN ENFORCEMENT PREDICATE ANY MORE (round 15). `enforce_route_receipt`
    used to branch on this to exempt unframed output; that exemption measured
    weaker than the installed gate and was removed. Nothing in this file calls
    this now -- it and `_output_carries_draft` are kept only because the round
    10/11/13 bypass tests read them (a pasted refusal token beside a framed
    draft, a pasted producer block), and those are the regression guards for
    `_publish_framed` / `_route_draft`. Deleting the predicates deletes the
    guards. Do not wire either one back into the route path.

    ECHO_NEVER_EXEMPTS_ROUTE (ASK-1197 round 13). Framing is decided FIRST and the
    echo test cannot turn a framed draft into a non-draft. It only chooses which
    NOTICE an unframed turn gets. That keeps round 10's bypass closed -- a pasted
    `[voice-stop-gate:held-this-turn]` beside a framed draft cannot skip receipt
    verification at any length -- while the lint half stays exempt, which is the
    other job the single predicate used to do badly.

    Route framing is wider than lint framing on purpose: it includes the lane
    markers a PRODUCER emits (receipt block, reddit wrapper), because those are
    exactly what a receipt covers.
    """
    text = assistant_text or ""
    if _publish_framed(text) or _route_draft(text):
        return OUTPUT_DRAFT
    if _is_own_refusal_echo(text):
        return OUTPUT_REFUSAL_ECHO
    return OUTPUT_NO_DRAFT


def _output_carries_draft(assistant_text):
    """Back-compat boolean over `classify_output`. Prefer that; it says WHY."""
    return classify_output(assistant_text) == OUTPUT_DRAFT


def enforce_route_receipt(request, assistant_text):
    """Consume the producer receipt for a routed completion, or refuse it.

    Returns the NOT CHECKED lines to report (usually empty). Raises
    RouteBoundaryError to hold the turn. The consumed row is deliberately NOT
    returned: no caller has ever read it, and a value nobody reads is how a
    docstring starts making promises the code does not keep.
    """
    context = _route_context()
    if context is None:
        # The lane is not installed here. Silent UNLESS something claims a receipt.
        # SHAPE, not substring -- see `_RECEIPT_CLAIM_RE`. The JSON is still
        # deliberately not parsed, because on an instance with no producer a
        # malformed block must not hard-block a turn.
        # MASKED, like every other marker read (Codex minor, ASK-1197 round 13).
        # This one call still searched raw text, so a fenced FORMAT EXAMPLE -- an
        # assistant showing what a receipt block looks like -- emitted a false
        # NOT CHECKED on the 24 lane-less instances. One masking helper, every
        # marker read, no exceptions; `test_every_marker_read_is_fence_masked`
        # derives the call sites from the source so a new one cannot skip it.
        if _RECEIPT_CLAIM_RE.search(_mask_fences(assistant_text or "")) is None:
            return []
        return ["voice-stop-gate: this turn carries a %s block, but no route "
                "verifier is installed at %s, so the receipt was NOT CHECKED. "
                "That is not a pass."
                % (ROUTE_RECEIPT_MARKER, INSTANCE_ROOT / ROUTE_PIPELINE_REL)]
    classifier, contract, audit_only, registry = context
    # NO FOUNDER TEXT THIS TURN IS NOT A REQUEST (Codex major, ASK-1197 round 2).
    # `find_final_user_text` now returns "" for a turn whose own final message is
    # entirely injected rather than reaching back for an older one, and "" has no
    # surface, no channel and no request hash to verify against. Classifying it
    # anyway is the defect this pairs with: it would build a receipt identity out
    # of whatever the classifier makes of an empty string, or out of the stale
    # message that used to stand in for it. Placed AFTER the uninstalled-lane
    # branch on purpose, so a claimed receipt still reports NOT CHECKED.
    if not request:
        return []
    result = classifier.classify(request)
    if result.status == classifier.NOT_ROUTED:
        return []
    # NO OUTPUT-SIDE RELAXATION ON THE ROUTE PATH (ASK-1197 round 15).
    # Rounds 10-14 exempted an unframed completion here: a refusal echo, a
    # question or any prose without framing got a NOT VERIFIED notice and exit 0.
    # MEASURED 2026-09-02 against consulting, the one instance with the lane
    # installed, by loading its running gate and this file side by side:
    #   request "write a linkedin post about detection engineering"
    #   output  three lines of unframed publishable prose, no receipt, no marker
    #   installed -> RouteBoundaryError("routed completion has no route receipt")
    #   relaxed   -> NOT VERIFIED notice, exit 0
    # `voice-stop-gate.py` is not in kipi-update.sh's INSTANCE_OWNED_SUBTREES, so
    # landing this branch REPLACES consulting's running gate. The relaxation was
    # therefore a live enforcement regression, not a port: unframed publishable
    # prose could dodge receipt enforcement on the founder's publishing instance.
    #
    # Separating a draft from a clarifying question needs a semantic signal this
    # gate does not have. `extract_publishable` returns "" for BOTH (it is
    # framing-gated), and `candidate_draft` (f918134c) returns content for BOTH.
    # Rounds 5-9 burned two rounds on size and bullet heuristics without
    # converging. A sixth heuristic is not the fix; it is the same bet again.
    #
    # So this path enforces UNCONDITIONALLY, exactly as the installed gate does.
    # The known cost is the deadlock: a reply to a refusal is refused again, and
    # consulting lives with that today. This PR's value is CONVERGENCE -- one
    # gate in the skeleton and the instance -- and that is not worth buying with
    # a regression on the only instance that enforces anything.
    #
    # THE ACCEPTED PATH FORWARD IS THE PRODUCER MARKER, not classification: the
    # gate should enforce only on output the route PRODUCER marked as a delivery,
    # a structural signal instead of a guess about prose. Recorded on spillover
    # sp-6ce17a23. Do not attempt heuristic number six.
    if result.status != classifier.ROUTE:
        raise RouteBoundaryError(
            f"route request is {result.status}: {result.reason}")
    try:
        registry.resolve(result.surface, result.channel)
    except registry.RouteRegistryError:
        audit_routes = [candidate for candidate in audit_only.routes()
                        if candidate.surface == result.surface
                        and candidate.channel == result.channel]
        if len(audit_routes) == 1:
            try:
                audit_only.deny(audit_routes[0])
            except audit_only.AuditOnlyRouteError as exc:
                raise RouteBoundaryError(str(exc)) from exc
        raise RouteBoundaryError("route has no single registered active owner")
    receipt = _receipt_block(assistant_text)
    if not isinstance(receipt, dict):
        raise RouteBoundaryError("routed completion has no route receipt")
    # The identity is whatever the store matches on, read from the store, so
    # a field added there (R9: loop_sha) is demanded here without a second
    # hand-kept list.
    required = set(contract.route_receipts.MATCH_FIELDS)
    if not required <= receipt.keys():
        raise RouteBoundaryError("route receipt identity is incomplete")
    if (receipt["surface"], receipt["channel"]) != (result.surface, result.channel):
        raise RouteBoundaryError("route receipt does not match the requested surface")
    if contract.request_hash(request, result.surface, result.channel) != receipt["request_hash"]:
        raise RouteBoundaryError("route receipt does not match the user request")
    draft = _route_draft(assistant_text)
    if contract.output_hash(draft, result.surface, result.channel) != receipt["output_hash"]:
        raise RouteBoundaryError("route receipt does not match the assistant output")
    identity = {key: receipt[key] for key in required}
    try:
        # R9: the contract recomputes the receipt's loop evidence against THIS
        # draft and the corpus on disk before the row is consumed.
        contract.verify_and_consume(identity, draft=draft)
    except RouteBoundaryError:
        # Not re-wrapped. A boundary error raised inside the store already says
        # what failed; wrapping it would bury that under this frame's wording.
        raise
    except Exception as exc:
        raise RouteBoundaryError(f"route receipt was not accepted: {exc}") from exc
    return []


def _enforce_route_or_exit(request, text):
    """One call-site shape for the two places main() enforces, so the two cannot
    drift apart. Per-site copies of a guard are how one branch ends up hardened
    and its sibling does not.

    CATCHES `Exception`, NOT just RouteBoundaryError, and that width is the point
    (Codex major, ASK-1197 round 1). `enforce_route_receipt` calls six things
    across the lane boundary -- classify, resolve, routes, request_hash,
    output_hash, MATCH_FIELDS -- and any of them can raise an ordinary exception.
    Catching only the tidy error let a `RuntimeError` from the classifier escape,
    and an escaped exception makes Python exit 1, which a Stop hook treats as
    "hook errored, carry on". The turn then completes with a routed draft nothing
    verified: the gate fails OPEN in exactly the case it exists for. Same shape
    Codex found twice in `channel_surface_lint`.

    A bug in THIS file lands here too and also holds the turn. That is the
    correct direction for a gate: a verifier that cannot run has not cleared
    anything.
    """
    try:
        return enforce_route_receipt(request, text)
    except RouteBoundaryError as exc:
        refuse(str(exc))
    except SystemExit as exc:
        # SystemExit inherits BaseException, NOT Exception, so the arm below
        # cannot see it (Codex minor, ASK-1197 round 3). Without this arm a
        # SystemExit raised anywhere inside `enforce_route_receipt` sails past
        # the fail-closed handler, reaches the top-level `except SystemExit:
        # raise`, and exits carrying its own code. A SystemExit(0) there exits
        # the hook 0 with a routed draft nothing verified: the same fail-OPEN
        # the Exception arm exists to prevent, through the one door it does not
        # cover.
        #
        # Code 2 is `refuse()` doing its job -- it is THE only exit-2 writer in
        # this file -- so it propagates untouched. Swallowing it would convert a
        # real refusal into a second refusal with the wrong message.
        #
        # No live path raises a non-2 SystemExit inside the verifier today. This
        # is hardening against the class, not a fix for a reproduced escape.
        if exc.code == 2:
            raise
        refuse("the route verifier exited unexpectedly with code %r\n"
               "Holding the turn (fail-closed): a check that exited without a "
               "verdict has not cleared this draft." % (exc.code,))
    except Exception as exc:
        refuse("the route verifier itself failed with %s: %s\n"
               "Holding the turn (fail-closed): a check that crashed has not "
               "cleared this draft." % (type(exc).__name__, exc))


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
# Sentence boundaries, and blank-line/newline boundaries too, because a draft is
# not one paragraph. This is the window `detect_channel` searches: wide enough to
# hold framing and subject together, narrow enough that a platform named two
# sentences earlier as CONTEXT cannot claim the draft.
_SENTENCE_RE = re.compile(r"(?<=[.!?:])\s+|\n+")


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


def _sentence_at(text, pos):
    """The sentence (or line) of `text` containing offset `pos`."""
    start, end = 0, len(text)
    for bound in _SENTENCE_RE.finditer(text):
        if bound.end() <= pos:
            start = bound.end()
        elif bound.start() >= pos:
            end = bound.start()
            break
    return text[start:end]


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
    # MASKED, like every other framing read (ASK-1197 round 13). A fenced EXAMPLE
    # naming a platform, or a producer's own `=== REDDIT DRAFT ... ===` wrapper,
    # would otherwise pick the channel -- which is the "wrong rulebook, shipped
    # AI-sounding" scar this function exists to close, re-entering through a
    # quoted example. Offsets are preserved by the masks, so `_sentence_at` still
    # indexes the same positions.
    text = text or ""
    masked = _mask_fences(text)
    masked = _mask_lane_markers(masked)
    markers = list(_PUBLISH_MARKER_RE.finditer(masked))
    if not markers:
        return ""
    # NEAREST THE DRAFT WINS, and this is the rule rather than the fourth patch.
    #
    # Codex found a counterexample in this function four rounds running, and each
    # round the previous shape had one: FIRST-anywhere let context outrank the
    # draft; first-in-the-marker missed framing that names no platform;
    # first-in-the-sentence let "For LinkedIn context, here's the Reddit post"
    # route a reddit draft to LinkedIn. Four counterexamples to three heuristics
    # is a statement about the heuristics, not about the examples.
    #
    # What is actually true of this text: publish framing INTRODUCES the draft
    # that follows it, so of all the framing in a message the piece nearest the
    # draft is the piece describing it, and everything earlier is context. That
    # is one rule, it is a property of how the sentences are written rather than
    # of any example, and every counterexample from all four rounds is in the
    # parametrized corpus in the test file so a fifth change cannot quietly undo
    # an earlier one.
    for marker in reversed(markers):
        found = _CHANNEL_RE.search(marker.group(0))
        if found:
            name = found.group(1).lower()
            return _CHANNEL_ALIASES.get(name, name)
    # No framing named a platform at all. Widen to the sentence holding the LAST
    # piece of framing, which is where "Reddit version, ready to paste" says it.
    # The sentence, not the message: a platform named two sentences earlier as
    # context still cannot claim the draft.
    chunk = _sentence_at(masked, markers[-1].start())
    found = _CHANNEL_RE.search(chunk)
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
    # `.get()` and NOT `.get(...) or {}`, which is the whole point. Codex found
    # this twice. Round 2: a non-object `channels` reached `.get` and raised an
    # uncaught AttributeError -- main() catches ChannelRegistryError and exits 2,
    # an AttributeError escapes it, Python exits 1, and a Stop hook exiting 1
    # does NOT hold the turn. Round 3: the `or {}` I added the guard behind
    # coerced every FALSY non-object ([], "", 0) to {} BEFORE the guard could
    # see it, so exactly the malformed registries that look emptiest sailed
    # through to the default lints unvalidated.
    #
    # PRESENCE, not falsiness, and not `is None` either. Codex narrowed this
    # three rounds running and each round the hole was the same shape: a
    # registry the gate cannot read quietly becoming "no registry". Round 3 was
    # `"channels": null` -- an explicit null is a present-but-wrong value, but
    # `.get()` returns None for it and for an ABSENT key alike, so the null
    # sailed through as an empty mapping.
    #
    # `in` is the only test that separates the two, so it is the test used. Only
    # a key that is genuinely not there means "no channels"; anything present
    # and not an object is a malformed registry and takes the hold path.
    if "channels" not in data:
        channels = {}
    else:
        channels = data["channels"]
    if not isinstance(channels, dict):
        raise ChannelRegistryError(
            f"voice-channels registry at {registry_path}: 'channels' must be an "
            f"object, got {type(channels).__name__}")
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
        report_not_checked(_enforce_route_or_exit(request, text))
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
        refuse("channel registry error, holding the turn (fail-closed).\n%s" % exc)

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
            #
            # MARKED, like every other refusal in this file. When the harness
            # feeds this stderr back as a `Stop hook feedback:` record, the walker
            # has to recognise it as THIS gate's own voice; see `_REFUSAL_MARK`.
            sys.stderr.write(_REFUSAL_MARK + "\n")
            sys.exit(2)
        if lint_failures:
            # Same reasoning as the violations path above: no drain, no spool. A
            # draft nothing graded is not a draft to score. Marked, same as above.
            sys.stderr.write(_REFUSAL_MARK + "\n")
            sys.exit(2)
    finally:
        for path in (tmp_path, tmp_json_path):
            if path is None:
                continue
            try:
                os.unlink(path)
            except OSError:
                pass

    report_not_checked(_enforce_route_or_exit(request, text))

    # THE CLEAN PATH. Score this draft (backgrounded, arrives next turn) and
    # surface whatever a previous turn's worker finished.
    authorship_spool(extract_setoff_draft(text), text, request)
    finish_ok()


if __name__ == "__main__":
    # EXIT 2, NEVER 1, ON AN INTERNAL FAULT (ASK-1197 round 10). A Stop hook that
    # raises exits 1, and the client treats exit 1 as "hook errored, carry on" --
    # so a bug in this file let the turn complete ungated. That is the failure
    # this whole gate exists to prevent, arriving through the gate itself; round
    # 9's extractor recursion reached it for real. `_enforce_route_or_exit`
    # already held this line for the route lane; this holds it for every other
    # line in the file, including the extractors main() calls before enforcement.
    #
    # A verifier that crashed has not cleared anything, so it holds the turn.
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:      # noqa: BLE001 -- fail CLOSED, deliberately
        refuse("the gate itself failed with %s: %s\nHolding the turn "
               "(fail-closed): a check that crashed has not cleared this draft."
               % (type(exc).__name__, exc))
