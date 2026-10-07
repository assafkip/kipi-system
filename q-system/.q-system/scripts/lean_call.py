"""The lean-call contract for background `claude -p` calls. One place.

    import lean_call
    r = lean_call.run([binary, "-p", prompt], capture_output=True, text=True,
                      timeout=t, stdin=subprocess.DEVNULL, env=_subscription_env())

By default the call runs:
  - with cwd = a fresh EMPTY temp dir (removed afterwards),
  - with `--setting-sources ""` (no user/project/local settings: no hooks),
  - with `--tools ""` (no built-in tools at all).

A caller that needs more says so, and the declaration is visible in the argv
and on stderr:
  needs_tools=["Read", "Grep"]  -> `--tools Read,Grep` instead of `--tools ""`
  needs_settings=True           -> `--setting-sources` is not passed
  cwd="/some/dir"               -> runs there instead of an empty temp dir

Why this shape (RCA 2026-10-06, root cause #3): every headless `claude -p` was
built on the same command as an interactive session, so a background judgment
paid for the cwd's whole interactive setup (the CLAUDE.md tree, rules,
UserPromptSubmit hooks). Measured with a two-word prompt: about 350k input-side
tokens from a runner root, 76k from an instance dir, 3.6k from an empty dir
with `--setting-sources "" --tools ""`. The cost grew every time a rule or hook
was added, with no change in the job. So lean is the DEFAULT and setup is an
opt-in, not the other way round.

The flags are APPENDED, never prepended: `--tools` is variadic, so `--tools ""
<prompt>` would swallow a positional prompt that follows it.

A caller must not put `--tools` or `--setting-sources` in its own argv. That
would be an undeclared need hiding in a list, which is exactly what this module
exists to make visible. It raises instead.

Pinned by q-system/.q-system/tests/test_lean_call.py (stubbed binary, sealed
PATH) and, against the real model, by its LIVE case behind KIPI_LIVE_MODEL_TEST=1.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile

LEAN_FLAGS = ("--setting-sources", "--tools")


def lean_argv(argv, *, needs_tools=None, needs_settings=False):
    """Return argv with the lean flags appended, honoring declared needs."""
    argv = list(argv)
    clash = [a for a in argv if isinstance(a, str) and a.split("=", 1)[0] in LEAN_FLAGS]
    if clash:
        raise ValueError(
            "lean_call: argv already carries %s; declare it with needs_tools= / "
            "needs_settings= instead so the need is visible" % ", ".join(clash))
    if not needs_settings:
        argv += ["--setting-sources", ""]
    argv += ["--tools", ",".join(needs_tools) if needs_tools else ""]
    return argv


def declared(needs_tools=None, needs_settings=False, cwd=None):
    """The non-lean needs a call declared, as one log-ready string ('' if none)."""
    parts = []
    if needs_tools:
        parts.append("tools=" + ",".join(needs_tools))
    if needs_settings:
        parts.append("settings=on")
    if cwd is not None:
        parts.append("cwd=" + str(cwd))
    return " ".join(parts)


def run(argv, *, needs_tools=None, needs_settings=False, cwd=None, **kwargs):
    """subprocess.run with the lean contract. Same return and exceptions."""
    full = lean_argv(argv, needs_tools=needs_tools, needs_settings=needs_settings)
    note = declared(needs_tools, needs_settings, cwd)
    if note:
        print("lean_call: declared " + note, file=sys.stderr)
    if cwd is not None:
        return subprocess.run(full, cwd=cwd, **kwargs)
    with tempfile.TemporaryDirectory(prefix="kipi-lean-") as empty:
        return subprocess.run(full, cwd=empty, **kwargs)
