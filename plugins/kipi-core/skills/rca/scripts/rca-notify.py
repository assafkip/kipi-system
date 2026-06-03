#!/usr/bin/env python3
"""
rca-notify.py — Deterministic RCA shoulder-tap.

PostToolUse(Bash) hook. When a command fails in a way that looks like a real
test/run failure, it injects a non-blocking nudge to open an RCA. The model
still decides; this just makes sure the moment is not missed.

Deterministic trigger: a non-zero exit, or a strong failure marker in the
output (pytest "= N failed", FAILED, BLOCKED, "Traceback (most recent call
last)"). Tightly scoped to avoid noise; meta-commands (the lint itself, git,
gitleaks, grep) are excluded.

Output contract:
    Always exits 0 (never blocks). On a detected failure it prints a
    PostToolUse additionalContext JSON nudge to stdout.

Override:
    Set RCA_NOTIFY_OFF=1 in the environment to silence.
"""

import json
import os
import re
import sys

# Strong failure markers. Kept tight on purpose.
FAILURE_MARKERS = re.compile(
    r"(Traceback \(most recent call last\)"
    r"|^\s*FAILED\b"
    r"|\bBLOCKED\b"
    r"|=+\s*\d+\s+failed"
    r"|^\s*FAIL\b"
    r"|\bAssertionError\b)",
    re.M,
)

# Commands we do NOT want to nudge on (meta / VCS / search noise).
EXCLUDE_CMD = re.compile(
    r"\b(rca-lint|rca-notify|gitleaks|git\s+(commit|add|status|diff|log)|grep|rg|find|ls|cat)\b"
)


def looks_failed(tool_response):
    """tool_response may be a dict or a string depending on the tool."""
    text = ""
    rc = None
    if isinstance(tool_response, dict):
        rc = tool_response.get("exit_code", tool_response.get("returncode"))
        for k in ("stdout", "stderr", "output", "content"):
            v = tool_response.get(k)
            if isinstance(v, str):
                text += "\n" + v
    elif isinstance(tool_response, str):
        text = tool_response
    if isinstance(rc, int) and rc != 0:
        return True
    return bool(FAILURE_MARKERS.search(text))


def main():
    if os.environ.get("RCA_NOTIFY_OFF") == "1":
        sys.exit(0)
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if payload.get("tool_name", "") != "Bash":
        sys.exit(0)

    cmd = payload.get("tool_input", {}).get("command", "")
    if not cmd or EXCLUDE_CMD.search(cmd):
        sys.exit(0)

    if not looks_failed(payload.get("tool_response", payload.get("tool_result", {}))):
        sys.exit(0)

    nudge = (
        "A command just failed (non-zero exit or FAIL/BLOCKED/Traceback). "
        "If this is a real defect that escaped a test or gate, this is an RCA "
        "moment: use the rca skill to write a root-cause analysis "
        "(surface vs structural cause, evidence-backed verification, checkbox "
        "action items). Skip only for an expected/trivial failure."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": nudge,
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
