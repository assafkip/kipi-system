#!/usr/bin/env python3
"""Reproducer for ASK-1247: destructive-op-deny.sh matches invocations, not effects.

Feeds the guard PreToolUse payloads the way Claude Code does and prints the
decision it returns, one row per command:

    python3 q-system/.q-system/tests/probe_hook.py [--hook PATH]

Exit 0 when every row matches what RULE-2026-09-13-A (canonical/decisions.md)
says the guard does, 1 when one diverges. The guard only DECIDES here; nothing
is executed, and HOME is redirected so its audit log never lands in the real one.

WHY IT LIVES HERE AND NOT IN A SCRATCHPAD. The first run of this (2026-09-04)
was a scratchpad file. The four ALLOW rows it printed were then true only in the
memory of whoever ran it. Here it is imported by
test_destructive_guard_interpreter_bound.py, which CI runs, so the rows are a
measurement on every run instead of a recollection.

Which copy of the guard it drives, in order: $KIPI_DESTRUCTIVE_HOOK, then the
live ~/.claude/hooks file, then the repo reference fixture. Same order as
test_destructive_op_deny_anchor.py, so the two suites agree about what "the
guard" is on any given machine.
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "destructive-op-deny.reference.sh"
LIVE = pathlib.Path(os.environ.get("HOME", "")) / ".claude/hooks/destructive-op-deny.sh"

TARGET = "/tmp/ask1247-probe-target"

# The shapes the guard was built for. If either comes back ALLOW the guard is
# not running at all, and every ALLOW below proves nothing about its bound.
CONTROLS = [
    {"label": "rm -rf <dir>", "command": "rm -rf %s" % TARGET, "expect": "deny"},
    {"label": "find <dir> -name '...' -delete",
     "command": "find %s -name '*.tmp' -delete" % TARGET, "expect": "deny"},
]

# The same effect through an interpreter. `expect` is what RULE-2026-09-13-A
# decided the guard does, NOT what it should do: the bound is accepted and
# stated, and each `label` is quoted verbatim in the guard's header.
INTERPRETER_FORMS = [
    {"label": 'python3 -c "import shutil; shutil.rmtree(...)"',
     "command": 'python3 -c "import shutil; shutil.rmtree(\'%s\')"' % TARGET,
     "expect": "allow"},
    {"label": 'python3 -c "import os; os.unlink(...)"',
     "command": 'python3 -c "import os; os.unlink(\'%s/f\')"' % TARGET,
     "expect": "allow"},
    {"label": "node -e \"require('fs').rmSync(..., {recursive: true})\"",
     "command": "node -e \"require('fs').rmSync('%s',{recursive:true,force:true})\""
                % TARGET,
     "expect": "allow"},
    {"label": "perl -e 'unlink(...)'",
     "command": "perl -e 'unlink(\"%s/f\")'" % TARGET, "expect": "allow"},
    {"label": "bash /path/to/script.sh",
     "command": "bash /tmp/ask1247-probe-script.sh", "expect": "allow"},
]

ROWS = CONTROLS + INTERPRETER_FORMS


def resolve_hook():
    override = os.environ.get("KIPI_DESTRUCTIVE_HOOK")
    if override:
        return pathlib.Path(override)
    if LIVE.is_file():
        return LIVE
    return FIXTURE


def decide(hook, command, home):
    """Run a COPY of the hook the way the harness does; return 'deny' or 'allow'."""
    copy = pathlib.Path(home) / "under-test.sh"
    shutil.copy(hook, copy)
    payload = json.dumps({"tool_name": "Bash",
                          "tool_input": {"command": command},
                          "cwd": str(home)})
    env = dict(os.environ)
    env["HOME"] = str(home)
    env.pop("ALLOW_DESTRUCTIVE", None)
    proc = subprocess.run(["bash", str(copy)], input=payload,
                          capture_output=True, text=True, env=env)
    out = proc.stdout.strip()
    if not out:
        return "allow"
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


def probe(hook):
    """[(row, decision)] for every row, each in its own throwaway HOME."""
    results = []
    for row in ROWS:
        with tempfile.TemporaryDirectory() as home:
            results.append((row, decide(hook, row["command"], home)))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hook", help="guard to drive (default: see module doc)")
    args = parser.parse_args(argv)
    hook = pathlib.Path(args.hook) if args.hook else resolve_hook()
    print("guard: %s" % hook)
    diverged = 0
    for row, decision in probe(hook):
        mark = "" if decision == row["expect"] else "   <- decision says %s" % row["expect"]
        diverged += bool(mark)
        print("%-6s %s%s" % (decision.upper(), row["label"], mark))
    return 1 if diverged else 0


if __name__ == "__main__":
    sys.exit(main())
