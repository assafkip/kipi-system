#!/usr/bin/env python3
"""Prompt plumbing: strip what the model prepended, count what it was told, run it.

why these three (2026-09-05, VoiceLoop package extraction, slice 11). Every operator
strips the same model preamble, counts constraints the same way, and shells the same
binary. None of that is anyone's copy.

WHAT DELIBERATELY STAYED BEHIND, and the plan expected two of them here.

`format_rules` and `render_constraints` render Amber's copy, and both pull deployment
data to do it: `format_rules` reads `config/channel-guidance.json` through
`channel_guidance` and the corpus through `form.writer_guidance`. Moving them would
have meant an adapter whose only job is to hand the engine two values back, in exchange
for relocating text that `.claude/rules/social-belongs-to-amber.md` says is a different
owner's work. The trade is bad in both directions, so they stayed and the commit says so.

`CLAUDE_BIN` did not come either, and that one is not a judgement call.
`os.path.expanduser("~/.local/bin/claude")` at module level in a package that ships
fleet-wide is one machine's path in every instance, and `drift_check.probe_unisolated_live_paths`
exists to block exactly that. `run_model` therefore takes `claude_bin` as a REQUIRED
argument here; the deployment holds the path and passes it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from . import usage_ledger

#: Where the instruction ends and the INPUTS begin. Everything after it is the voice
#: corpus and the source material, neither of which is a constraint.
VOICE_MARKER = "VOICE REFERENCE:"
#: How a rendered constraint is COUNTED. One numbered item per registry entry, matched at
#: line start. This is the whole reason the list is numbered: a count taken from the
#: registry proves nothing about what the model was handed.
CONSTRAINT_LINE = re.compile(r"^(\d+)\. [A-Z$]", re.M)
# A model told "output only the post" still opens with "Here's the post:" often enough
# that it must be stripped rather than requested. Observed live 2026-08-05: the first end
# to end generation returned "Here's the post:\n\n---\n\n..." and would have published
# that preamble as the opening line. An instruction is not an enforcement.
_PREAMBLE = re.compile(
    r"^\s*(?:here(?:'|’)?s|here is|this is)\b[^\n:]{0,60}:\s*\n+", re.I)
_LEADING_RULE = re.compile(r"^\s*(?:---+|\*\*\*+)\s*\n+")
_TRAILING_RULE = re.compile(r"\n+\s*(?:---+|\*\*\*+)\s*$")
TIMEOUT_SECONDS = 120


def strip_preamble(text):
    """Remove a model's framing so only the post survives. Idempotent."""
    out = text.strip()
    for _ in range(3):
        before = out
        out = _PREAMBLE.sub("", out)
        out = _LEADING_RULE.sub("", out)
        out = _TRAILING_RULE.sub("", out)
        out = out.strip()
        if out == before:
            break
    return out


def instruction_section(prompt):
    """Everything the model is TOLD, with the voice corpus and the material removed."""
    return prompt.split(VOICE_MARKER)[0]


def count_constraints(prompt):
    """How many constraints this rendered prompt actually hands the model.

    SCOPED TO THE INSTRUCTION SECTION, and the scoping is a measured fix rather than a
    tidy one (2026-08-12, claims finding 5). Counting `CONSTRAINT_LINE` over the WHOLE
    live prompt returned 8 on LinkedIn while the header the model reads said 6: one
    exemplar body in `voice/exemplars.jsonl` carries its own numbered list, and the
    counter matched two of its lines.

    Every test proving "under 10 constraints" rendered with a STUBBED voice, so the
    proof was taken off an artifact the runtime never produces. That is
    RULE-2026-08-12-E's own failure shape turned on the proof instead of on the wiring,
    and the cap held live only because that exemplar happened to contribute exactly two
    strays.

    The voice corpus is his own published posts and the material is harvested news.
    Both are INPUTS. Neither may move a constraint count in either direction, so the
    count stops at the marker.
    """
    return len(CONSTRAINT_LINE.findall(instruction_section(prompt)))


def _meter(row_fn, *args, **kwargs):
    """Build and append one ledger row, swallowing anything the ledger raises.

    THE METER CAN NEVER FAIL THE CALL, on any path. Round 5 guarded only the
    success arm; round 6 showed the timeout and non-zero-exit arms raising out
    of failure_row on a malformed usage value. Every ledger write goes through
    here now, so there is no unguarded arm left.
    """
    try:
        usage_ledger.append(row_fn(*args, **kwargs))
    except Exception as exc:  # noqa: BLE001
        try:
            usage_ledger.append(usage_ledger.failure_row(
                "meter:" + type(exc).__name__, stderr=str(exc)[:200],
                bot=kwargs.get("bot") or "voiceloop", job=kwargs.get("job"), model=kwargs.get("model")))
        except Exception:  # noqa: BLE001
            pass


def run_model(prompt, claude_bin, timeout=TIMEOUT_SECONDS, runner=None,
              caller="run_model()", under_test="raise", model=None, allow_opencode=True):
    """THE model call. One implementation, so every caller gets the same guarantees.

    why one (2026-08-06, founder-directed): "you shouldn't invent a new mechanism. we
    already have the mechanism to write the posts with my voice, so it should use the same
    thing." The comment writer had grown its own copy of this -- its own subprocess call,
    its own timeout, its own test chokepoint -- which is exactly how two callers drift
    until one of them is reading the wrong files again.

    `under_test` is the ONE thing that legitimately differs. A missing POST is a defect and
    must raise; a missing COMMENT is a valid outcome the live path already handles. So a
    caller declares which it is instead of reimplementing the guard.
    """
    if runner is not None:
        return runner(prompt)
    # A suite must never spend a real model call: slow, costs money, non-deterministic.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        if under_test == "raise":
            raise RuntimeError(
                f"{caller} reached the live model from inside a test. Inject `runner=` "
                f"or `seed_generator=` instead.")
        return None
    # THE BINARY IS REQUIRED, and this is the third placement. It must come AFTER both
    # short-circuits, because neither reaches a binary:
    #   a caller with a runner never shells anything  (first version broke 60 tests)
    #   a caller inside pytest must hit the spend guard and get ITS error, not this one
    #      (second version broke 32 more, by pre-empting the guard that exists to say
    #       "you reached the live model from a test")
    # Only a real call needs a real path, so the check belongs exactly here.
    #
    # It exists because `claude_bin or CLAUDE_BIN` survived the slice 11 move as a
    # reference to a name that stayed in the deployment. Nothing caught it: the
    # deployment wrapper always passed a value, so the fallback was unreachable until
    # slice 6 called this directly and it raised NameError.
    if not claude_bin:
        raise ValueError(
            "run_model needs an explicit claude_bin; the engine has no default binary "
            "because a default would be one machine's path shipped fleet-wide")
    binary = claude_bin
    if allow_opencode and os.environ.get("OPENCODE") and shutil.which("opencode"):
        try:
            # The writer is already inside the voice loop. Reloading the global
            # voice-loop plugin here recurses on the prompt and can fail before
            # the model sees the request.
            args = ["opencode", "run", "--pure", "--format", "json"]
            active_model = os.environ.get("OPENCODE_MODEL")
            if active_model:
                args.extend(["--model", active_model])
            args.append(prompt)
            result = subprocess.run(
                args, capture_output=True, text=True,
                timeout=timeout)
            if result.returncode == 0:
                parts = []
                for line in result.stdout.splitlines():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "text":
                        parts.append(event.get("part", {}).get("text", ""))
                # ASK-2008: this provider reports no usage, so the row says so
                # (tokens None) rather than leaving the run invisible. `ok` is
                # whether the CALLER got text: a dead run is not a clean one.
                text = "".join(parts).strip() or None
                _meter(usage_ledger.failure_row, "opencode", ok=text is not None,
                       bot=os.environ.get("CHIEF_BOT") or "voiceloop",
                       job=os.environ.get("CHIEF_JOB") or caller, model=active_model)
                return text
        except (subprocess.SubprocessError, OSError) as exc:
            _meter(usage_ledger.failure_row, f"opencode:{type(exc).__name__}", stderr=str(exc),
                   bot=os.environ.get("CHIEF_BOT") or "voiceloop",
                   job=os.environ.get("CHIEF_JOB") or caller, model=active_model)
            return None
    if not os.path.exists(binary):
        _meter(usage_ledger.failure_row, "no-binary", stderr=f"claude_bin not found: {binary}",
               bot=os.environ.get("CHIEF_BOT") or "voiceloop",
               job=os.environ.get("CHIEF_JOB") or caller, model=model)
        return None
    # ASK-2008: the call is metered. Every path below leaves one row, the failures
    # included: a limit refusal, a timeout that burned tokens before the kill, a
    # non-zero exit. On 2026-09-12 the fleet went dark for a day and a ledger that
    # skipped failed calls would have looked identical to an idle fleet (PR #410
    # review). Every row goes through _meter, so no arm can raise out of here.
    who = dict(bot=os.environ.get("CHIEF_BOT") or "voiceloop",
               job=os.environ.get("CHIEF_JOB") or caller, model=model)
    try:
        # `--model` only when a caller asked for one, so every existing caller keeps the
        # CLI's own default and this stays additive.
        argv = [binary, "-p", prompt, *usage_ledger.JSON_FLAGS]
        if model:
            argv[1:1] = ["--model", model]
        result = subprocess.run(argv, capture_output=True,
                                text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _meter(usage_ledger.failure_row, "timeout", stdout=exc.stdout, stderr=exc.stderr, **who)
        return None
    except (subprocess.SubprocessError, OSError) as exc:
        _meter(usage_ledger.failure_row, type(exc).__name__, stderr=str(exc), **who)
        return None
    if result.returncode != 0 and usage_ledger.rejected_flag(result.stderr):
        # An older CLI that does not know --output-format json: fall back to the
        # plain call so the fleet keeps working, and record an unmetered row.
        try:
            result = subprocess.run([a for a in argv if a not in usage_ledger.JSON_FLAGS],
                                    capture_output=True, text=True, timeout=timeout)
        except (subprocess.SubprocessError, OSError) as exc:
            _meter(usage_ledger.failure_row, type(exc).__name__, stderr=str(exc), **who)
            return None
        ok = result.returncode == 0
        _meter(usage_ledger.failure_row, "cli:no-json-flag", ok=ok, stderr=result.stderr, **who)
        return result.stdout if ok else None
    if result.returncode != 0:
        _meter(usage_ledger.failure_row, f"exit {result.returncode}",
               stdout=result.stdout, stderr=result.stderr, **who)
        return None
    # `finish` hands back the same bytes a plain call printed (result + newline).
    try:
        text, row = usage_ledger.finish(result.stdout, **who)
    except Exception as exc:  # noqa: BLE001
        # A malformed document is the ledger's problem, not the caller's: the
        # plain text is handed back exactly as an unmetered call would have.
        _meter(usage_ledger.failure_row, "meter:" + type(exc).__name__, stderr=str(exc), **who)
        return usage_ledger.plain_text(result.stdout)
    _meter(lambda: row)
    return text  # None when the CLI answered with an error document
