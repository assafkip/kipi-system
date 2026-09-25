#!/usr/bin/env python3
"""Refuse a commit when machine Linear writes would silently run as the founder.

Why this exists (ASK-1967): machine Linear writes authenticate as the Sana OAuth
app so a bot's tickets and closures are attributable. The whole wire lives
outside version control: `~/.zshenv` exports KIPI_LINEAR_API_KEY from
`~/.config/kipi/linear-sana-token`, and both key resolvers
(`linear-sync.py linear_api_key()`, `prd_runner.py _linear_api_key()`) read that
env var before any file. When it is empty they fall back to the founder's
personal key. That fail-soft is right for availability and is exactly what makes
the regression invisible: no error, just the founder's name back on every write.

A port of the consulting instance's `automation/check_linear_identity.py`, which
guarded one instance only because `automation/` is never synced by kipi update.

Verdicts:
  exit 0  KIPI_LINEAR_IDENTITY=founder declares the fallback on purpose (an
          instance or machine that has never had a Sana token)
  exit 0  KIPI_LINEAR_API_KEY equals the Sana token AND ~/.zshenv carries the
          export, so launchd jobs inherit it too
  exit 2  anything else, with the reason on stderr

Modes:
  (no args)  run the check, print the verdict
  --hook     Claude Code PreToolUse(Bash) hook: acts only on a `git commit`
             command, fast-exits 0 on every other call

HONEST BOUNDARY: this compares the env var to the token FILE; it never calls
Linear, so a revoked Sana token passes. The ~/.zshenv check is a line match on
an export naming both the variable and the token file, not a shell evaluation.
The hook sees commits made through Claude's Bash tool only; a commit typed in a
terminal is not gated.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ENV_KEY = "KIPI_LINEAR_API_KEY"
ENV_IDENTITY = "KIPI_LINEAR_IDENTITY"
FOUNDER_DECLARED = "founder"
TOKEN_NAME = "linear-sana-token"
GIT_COMMIT_RE = re.compile(r"\bgit\b[^;&|\n]*\bcommit\b")

FIX = (
    "Fix one of two ways:\n"
    f"  1. Restore the export in ~/.zshenv:\n"
    f"       export {ENV_KEY}=\"$(cat ~/.config/kipi/{TOKEN_NAME})\"\n"
    "     then open a new shell.\n"
    f"  2. This machine or instance has no Sana token on purpose: export "
    f"{ENV_IDENTITY}={FOUNDER_DECLARED}\n"
    "     to declare that Linear writes run as the founder."
)


def token_path(home: Path) -> Path:
    return home / ".config" / "kipi" / TOKEN_NAME


def zshenv_exports_token(home: Path) -> bool:
    """True when ~/.zshenv has an uncommented line exporting the key from the token file."""
    zshenv = home / ".zshenv"
    if not zshenv.is_file():
        return False
    for line in zshenv.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if ENV_KEY in stripped and TOKEN_NAME in stripped:
            return True
    return False


def check(env: dict, home: Path) -> tuple[int, str]:
    """Return (exit_code, message). Pure: reads only env and files under home."""
    if env.get(ENV_IDENTITY, "").strip() == FOUNDER_DECLARED:
        return 0, f"linear identity: founder (declared by {ENV_IDENTITY}={FOUNDER_DECLARED})"
    key = env.get(ENV_KEY, "").strip()
    if not key:
        return 2, (f"linear identity: {ENV_KEY} is empty, so every machine Linear "
                   "write falls back to the founder's personal key.\n" + FIX)
    token_file = token_path(home)
    if not token_file.is_file():
        return 2, (f"linear identity: {token_file} is missing, so {ENV_KEY} cannot "
                   "be confirmed as the Sana token.\n" + FIX)
    if key != token_file.read_text(errors="replace").strip():
        return 2, (f"linear identity: {ENV_KEY} does not hold the Sana token from "
                   f"{token_file}; writes would run as whoever owns that key.\n" + FIX)
    if not zshenv_exports_token(home):
        return 2, (f"linear identity: ~/.zshenv does not export {ENV_KEY} from "
                   f"{TOKEN_NAME}. This shell has it; launchd jobs will not.\n" + FIX)
    return 0, "linear identity: sana"


def is_commit_call(payload: dict) -> bool:
    if payload.get("tool_name") != "Bash":
        return False
    command = (payload.get("tool_input") or {}).get("command") or ""
    return bool(GIT_COMMIT_RE.search(command))


def run_hook() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict) or not is_commit_call(payload):
        return 0
    code, message = check(dict(os.environ), Path.home())
    if code != 0:
        print(f"BLOCKED commit (check-linear-identity.py): {message}", file=sys.stderr)
    return code


def main(argv: list[str]) -> int:
    if "--hook" in argv:
        return run_hook()
    code, message = check(dict(os.environ), Path.home())
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
