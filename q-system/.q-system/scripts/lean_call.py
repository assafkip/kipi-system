"""The lean-call contract for background `claude -p` calls. One place.

    import lean_call
    r = lean_call.run([binary, "-p", prompt], capture_output=True, text=True,
                      timeout=t, stdin=subprocess.DEVNULL, env=_subscription_env())

By default the call runs:
  - with cwd = a fresh EMPTY temp dir (removed afterwards),
  - with `--setting-sources ""` (no user/project/local settings: no hooks),
  - with `--tools ""` (no built-in tools at all),
  - with `--strict-mcp-config --mcp-config '{"mcpServers":{}}'` (no MCP tools),
  - with a one-line `--system-prompt` instead of the CLI's long default.

A caller that needs more says so, and the declaration is visible in the argv
and on stderr:
  needs_tools=["Read", "Grep"]  -> `--tools Read,Grep` instead of `--tools ""`
  needs_settings=True           -> `--setting-sources` is not passed
  cwd="/some/dir"               -> runs there instead of an empty temp dir
  needs_mcp=True                -> the account's MCP connectors stay attached
  system_prompt="..."           -> that prompt instead of the lean one;
  system_prompt=None            -> the CLI's default system prompt (declared)

Why MCP is stripped too (measured 2026-10-06, after the first version shipped
with only the two flags): claude.ai account connectors arrive as MCP tool
definitions from the LOGIN, not from settings, so `--setting-sources ""` does
not remove them. They attach asynchronously, so the cost was a race: the same
empty dir measured 6.7k on one run and overflowed at 271k to 458k on the next,
tracking the connector count. With strict MCP: 6.7k on every repeat. The rest
of that 6.7k was the CLI's default system prompt (Haiku 6.7k, Sonnet 2.7k);
a one-line system prompt measured 513 on Haiku and 587 on Sonnet.

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

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path


def _route():
    """model_route, loaded from beside this file, on first use only."""
    mod = sys.modules.get("model_route")
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            "model_route", Path(__file__).resolve().parent / "model_route.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["model_route"] = mod
        spec.loader.exec_module(mod)
    return mod

LEAN_FLAGS = ("--setting-sources", "--tools", "--mcp-config", "--no-session-persistence",
              "--strict-mcp-config", "--system-prompt")
EMPTY_MCP = '{"mcpServers":{}}'
LEAN_SYSTEM_PROMPT = ("You are a careful assistant running as a background job. "
                      "Answer the request exactly as asked.")


def lean_argv(argv, *, needs_tools=None, needs_settings=False, needs_mcp=False,
              system_prompt=LEAN_SYSTEM_PROMPT):
    """Return argv with the lean flags appended, honoring declared needs."""
    argv = list(argv)
    clash = [a for a in argv if isinstance(a, str) and a.split("=", 1)[0] in LEAN_FLAGS]
    if clash:
        raise ValueError(
            "lean_call: argv already carries %s; declare it with needs_tools= / "
            "needs_settings= / needs_mcp= / system_prompt= instead so the need "
            "is visible" % ", ".join(clash))
    if not needs_settings:
        argv += ["--setting-sources", ""]
    # One background call per issue/lesson must not leave a session dir per call
    # under ~/.claude/projects (PR 531 review: 144 temp-cwd dirs already piled up).
    argv += ["--no-session-persistence"]
    if not needs_mcp:
        argv += ["--strict-mcp-config", "--mcp-config", EMPTY_MCP]
    if system_prompt is not None:
        argv += ["--system-prompt", system_prompt]
    # --tools LAST: it is variadic and must not swallow the flags after it.
    argv += ["--tools", ",".join(needs_tools) if needs_tools else ""]
    return argv


def declared(needs_tools=None, needs_settings=False, cwd=None, needs_mcp=False,
             system_prompt=LEAN_SYSTEM_PROMPT):
    """The non-lean needs a call declared, as one log-ready string ('' if none)."""
    parts = []
    if needs_tools:
        parts.append("tools=" + ",".join(needs_tools))
    if needs_settings:
        parts.append("settings=on")
    if cwd is not None:
        parts.append("cwd=" + str(cwd))
    if needs_mcp:
        parts.append("mcp=on")
    if system_prompt is None:
        parts.append("system_prompt=cli-default")
    elif system_prompt != LEAN_SYSTEM_PROMPT:
        parts.append("system_prompt=custom")
    return " ".join(parts)


def run(argv, *, needs_tools=None, needs_settings=False, cwd=None,
        needs_mcp=False, system_prompt=LEAN_SYSTEM_PROMPT, job=None, runner=None,
        **kwargs):
    """subprocess.run with the lean contract. Same return and exceptions.

    `job` names this call's row in q-system/.q-system/model-routing.json and adds
    `--model` from it (ASK-4013). Before it, every lean call passed no --model and
    ran on whatever the CLI defaulted to with no settings loaded: measured
    2026-11-08, that was claude-opus-5-5, chosen by nobody.

    `runner` replaces subprocess.run for the spawn, with the same signature. The
    fleet passes `fleet_door.runner(actor)` so the lean call is billed to a fleet
    API key and lands in the spend ledger (ASK-4311). The lean flags are built
    here either way, so the bound does not depend on who spawns."""
    spawn = runner or subprocess.run
    if job and "--model" not in argv:
        argv = [*argv, "--model", _route().pick(job)]
    full = lean_argv(argv, needs_tools=needs_tools, needs_settings=needs_settings,
                     needs_mcp=needs_mcp, system_prompt=system_prompt)
    note = declared(needs_tools, needs_settings, cwd, needs_mcp, system_prompt)
    if note:
        print("lean_call: declared " + note, file=sys.stderr)
    if cwd is not None:
        return spawn(full, cwd=cwd, **kwargs)
    with tempfile.TemporaryDirectory(prefix="kipi-lean-") as empty:
        return spawn(full, cwd=empty, **kwargs)
