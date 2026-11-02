#!/usr/bin/env python3
"""instance-hook-dispatch: run an instance's own hook from a skeleton-shipped entry.

    instance-hook-dispatch.py <name>     # runs $CLAUDE_PROJECT_DIR/automation/<name>.py

why this exists (ASK-3685, PR #598 review). An instance wanted a blocking PostToolUse
hook for its own social drafts. The skeleton template cannot wire a path it does not
ship: `skeleton-guard-settings.py` exits 1 on it (so linear-worker stops taking tickets
in repos with no .claude/settings.json) and `hook-path-resolve-check` refuses every later
settings edit. The path is ALWAYS dead in every instance but the one that wrote the file.

So the template wires THIS script, which does ship. It runs the instance file when one
exists, with the same stdin, and passes the exit code and stderr straight through (exit 2
blocks, as for any hook). When the file is absent it exits 0 silently, so every other
instance no-ops. One entry per instance hook name; the name is fixed in the template.

The name is restricted to [a-z0-9_-]: it is joined into a path, and `..` or `/` must not
be able to leave `automation/`. A bad name is refused with exit 2 (loud), because only a
broken template can produce one.

Fail-open on an unset CLAUDE_PROJECT_DIR (no project, nothing to dispatch to). Fail-closed
on the child: a crash exits with the child's own nonzero code, never 0.
"""
import os
import re
import subprocess
import sys

NAME_RE = re.compile(r"^[a-z0-9_-]+$")


def main(argv, stdin_bytes, env):
    if len(argv) != 2 or not NAME_RE.fullmatch(argv[1]):
        print("instance-hook-dispatch REFUSED: usage `instance-hook-dispatch.py <name>` "
              "with name in [a-z0-9_-]", file=sys.stderr)
        return 2
    root = env.get("CLAUDE_PROJECT_DIR")
    if not root:
        return 0
    target = os.path.join(root, "automation", argv[1] + ".py")
    if not os.path.isfile(target):
        return 0
    result = subprocess.run([sys.executable, target], input=stdin_bytes, env=env,
                            capture_output=True)
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv, sys.stdin.buffer.read(), dict(os.environ)))
