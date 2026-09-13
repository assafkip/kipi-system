#!/usr/bin/env python3
"""Is every PreToolUse guard wired in settings.json present and executable? (ASK-1250)

destructive-op-deny.sh is wired as a BARE PATH, so its execute bit is part of
the wiring: `chmod -x` disarms it and Claude Code reports nothing. Its own
header asked a human to notice a file mode, and nothing else did (checked
2026-09-04: no launchd job or heartbeat read its mode).

dead-hooks (github.com/assafkip/dead-hooks) was asked first, as the DoR
required. Its judge() checks is_file() only, so a 0644 bare-path guard reads
WIRED there. It does not cover this.

Only PreToolUse entries are read, because those are the guards that refuse.
Per command segment:
  - a program named by a PATH (contains "/") must exist AND be executable
  - a script handed to an interpreter (`python3 x.py`) must exist; its mode is
    irrelevant because the interpreter reads it
A bare program name (`python3`, `bash`) is resolved by PATH and is not ours.

The outward channel is fleet-health-daily.py's `hook-not-executable` detector:
one permanent Linear issue per broken guard, in Sana's triage, plus the one
summary line through slack-notify.sh. A local suite alone cannot see a live mode.

HONEST BOUNDARY: a wrapper that execs the real guard is checked only at the
wrapper. A token carrying any variable other than $HOME / $CLAUDE_PROJECT_DIR,
or a command substitution, is skipped, never guessed at. $CLAUDE_PROJECT_DIR in
the user-scope settings has no single meaning, so those tokens are skipped too.

Usage: hook_liveness.py [settings.json ...]   (default: user + this repo)
Exit 1 when any guard is broken, 0 when every one is live.
"""
import importlib.util
import json
import os
import re
import shlex
import sys
from collections import namedtuple
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent
USER_SETTINGS = Path.home() / ".claude" / "settings.json"
REPO_SETTINGS = REPO_ROOT / ".claude" / "settings.json"

Problem = namedtuple("Problem", "settings path reason")

# Shell words that PRECEDE a program rather than being one (`if [ -x X ]; then X; fi`).
_SHELL_KEYWORDS = frozenset({"if", "then", "else", "elif", "fi", "do", "done",
                             "while", "until", "time", "!", "{", "}", "("})
_HOME_VAR = re.compile(r"^(?:~|\$HOME|\$\{HOME\})(?=/)")
_PROJECT_VAR = re.compile(r"^\$\{?CLAUDE_PROJECT_DIR\}?(?=/)")


def _claim_lint():
    """enforced-claim-lint.py owns the segment split and the interpreter set.

    Borrowed, not restated: a second copy of which programs run a script is the
    drift the derive-from-owner lesson is about.
    """
    spec = importlib.util.spec_from_file_location("ecl", HERE / "enforced-claim-lint.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pretooluse_commands(settings_path):
    """Every PreToolUse command string. Raises ValueError on an unreadable config.

    Raising, not returning [], because a guard list that failed to parse would
    otherwise read as "no guards, nothing broken".
    """
    try:
        data = json.loads(Path(settings_path).read_text())
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"{settings_path}: {exc.__class__.__name__}") from exc
    out = []
    for matcher in (data.get("hooks") or {}).get("PreToolUse") or []:
        for hook in (matcher or {}).get("hooks") or []:
            if isinstance(hook, dict) and hook.get("type") == "command" \
                    and isinstance(hook.get("command"), str):
                out.append(hook["command"])
    return out


def _resolve(token, project_dir):
    """Absolute path for a token, or None when it cannot be resolved honestly."""
    token = _HOME_VAR.sub(str(Path.home()), token)
    if project_dir is not None:
        token = _PROJECT_VAR.sub(str(project_dir), token)
    if "$" in token or "`" in token:
        return None
    path = Path(token)
    if not path.is_absolute():
        if project_dir is None:
            return None
        path = Path(project_dir) / path
    return path


def _segment_targets(segment, interpreters):
    """(token, must_be_executable) pairs this segment RUNS."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    while tokens and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0])
                      or tokens[0] in _SHELL_KEYWORDS):
        tokens = tokens[1:]
    if not tokens:
        return []
    program = tokens[0]
    if os.path.basename(program) in interpreters:
        script = next((t for t in tokens[1:] if not t.startswith("-")), None)
        return [(script, False)] if script else []
    return [(program, True)] if "/" in program else []


def command_problems(settings_path, command, project_dir, claim_lint=None, checked=None):
    """Problems for one wired command: missing, or a bare path without +x.

    `checked`, when given, collects every path that was actually judged, so a
    caller can tell "all guards live" from "resolved no guard at all".
    """
    claim_lint = claim_lint or _claim_lint()
    found = []
    for segment in claim_lint._SEGMENT_SPLIT.split(command):
        for token, must_exec in _segment_targets(segment, claim_lint.INTERPRETERS):
            path = _resolve(token, project_dir)
            if path is None:
                continue
            if checked is not None:
                checked.append(str(path))
            if not path.is_file():
                found.append(Problem(str(settings_path), str(path), "missing"))
            elif must_exec and not os.access(path, os.X_OK):
                mode = oct(path.stat().st_mode & 0o777)
                found.append(Problem(str(settings_path), str(path),
                                     f"not executable ({mode})"))
    return found


def audit(settings_paths, checked=None):
    """Every broken PreToolUse guard across these configs. Absent configs are skipped."""
    claim_lint = _claim_lint()
    problems = []
    for settings in settings_paths:
        settings = Path(settings)
        if not settings.exists():
            continue
        project_dir = None if settings == USER_SETTINGS else settings.parent.parent
        try:
            commands = pretooluse_commands(settings)
        except ValueError as exc:
            problems.append(Problem(str(settings), str(settings), f"unreadable: {exc}"))
            continue
        for command in commands:
            problems.extend(command_problems(settings, command, project_dir,
                                             claim_lint, checked))
    return problems


def main(argv):
    paths = [Path(a) for a in argv] or [USER_SETTINGS, REPO_SETTINGS]
    checked = []
    problems = audit(paths, checked)
    for p in problems:
        print(f"BROKEN  {p.path}  {p.reason}  (wired in {p.settings})")
    print(f"{len(problems)} broken of {len(checked)} PreToolUse guard path(s) "
          f"judged across {len(paths)} config(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
