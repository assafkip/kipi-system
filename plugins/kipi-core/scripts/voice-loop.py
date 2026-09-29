#!/usr/bin/env python3
"""/voice-loop: run the voice engine on one draft by hand (ASK-2226).

usage: voice-loop.py <file> [--channel c]

The draft-write hook `voiceloop-band-lint.py` already decides which engine a path
gets: `review --channel c` when the path names a channel, `score` otherwise
(ASK-2220). This command IMPORTS that decision from the instance's own copy of the
hook instead of holding a second channel table. Two tables would drift, and then
the command and the hook would judge the same file two different ways.

Exit: the engine's own exit code (0 clean, 1 findings). 2 when nothing ran: no
file, an unknown channel, or an instance without the hook. A refusal says why on
stderr; it never falls back to a default channel, because `voiceloop review`
accepts any channel string silently and a typo would pass as a clean review.
"""
import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

HOOK_REL = Path("q-system") / ".q-system" / "scripts" / "voiceloop-band-lint.py"
DEFAULT_CORPUS = "~/projects/consulting/q-consult/voice"


def _refuse(message):
    print(f"voice-loop NOT RUN: {message}", file=sys.stderr)
    sys.exit(2)


def _load_hook():
    """The instance's hook module, the one owner of the path-to-channel table."""
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    target = root / HOOK_REL
    if not target.is_file():
        _refuse(f"{target} not found, so there is no channel table to read. "
                "This instance predates ASK-2220; run the fleet sync first.")
    spec = importlib.util.spec_from_file_location("_voiceloop_hook_for_command", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "CHANNEL_BY_PATH"):
        _refuse(f"{target} has no CHANNEL_BY_PATH. This instance predates ASK-2220; "
                "run the fleet sync first.")
    return module


def _build_command(hook, file_path, channel):
    if channel is None:
        command, label = hook._engine_command(file_path)
        return command, label
    known = sorted({name for _, name in hook.CHANNEL_BY_PATH})
    if channel not in known:
        _refuse(f"unknown channel {channel!r}. Known: {', '.join(known)}.")
    return ["voiceloop", "review", "--channel", channel, file_path], f"review, channel {channel}"


def main():
    parser = argparse.ArgumentParser(prog="voice-loop")
    parser.add_argument("file")
    parser.add_argument("--channel")
    args = parser.parse_args()

    draft = Path(args.file).expanduser()
    if not draft.is_file():
        _refuse(f"{draft} is not a file.")
    hook = _load_hook()
    command, label = _build_command(hook, str(draft.resolve()), args.channel)

    if shutil.which("voiceloop") is None:
        _refuse("`voiceloop` is not on PATH.")
    corpus = Path(os.path.expanduser(os.environ.get("VOICE_LOOP_CORPUS") or DEFAULT_CORPUS))
    if not corpus.is_dir():
        _refuse(f"corpus directory {corpus} does not exist. Set VOICE_LOOP_CORPUS.")

    # flush: the engine writes to the same stdout directly, so an unflushed header
    # lands AFTER its findings when stdout is a pipe (measured on the first smoke run).
    print(f"voiceloop ({label}): {' '.join(command[1:-1])} {draft}", flush=True)
    env = dict(os.environ, VOICE_LOOP_CORPUS=str(corpus))
    result = subprocess.run(command, env=env)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
