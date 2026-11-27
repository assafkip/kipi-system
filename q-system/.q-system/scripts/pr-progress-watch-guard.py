#!/usr/bin/env python3
"""PreToolUse(Bash) guard: a hand-rolled PR wait loop must use pr-progress-watch.sh (ASK-5842).

Pairs with q-system/.q-system/scripts/pr-progress-watch.sh, the one watcher that
exits on MERGED, CLOSED, a stall or a deadline.

why: 2026-11-27 a session armed `while ...; gh pr view 903 --json state,mergeCommit;
sleep 300; done` that woke only on merge. The PR was stuck on a reviewer nothing had
started and the session idled about 5h. A loop with one exit is a hang with extra
steps, so the loop is refused and the refusal names the script that has the other exits.

Blocks when ONE command text holds all three: a shell loop (while/until/for ... do), a
`gh pr view`, `gh pr checks`, `gh pr status` or `gh api .../pulls/N` call, and `sleep`, and does not mention
pr-progress-watch. Bypass for a command that only QUOTES the pattern (a commit
message, an echo): `pr-watch-skip: <why>` in the command.

Honest boundary: a regex reads text, not intent. A loop inside a script file the
command merely runs is invisible here, and so is a loop built on `watch` or a
recursive re-arm, or one polling through `gh run`, `gh pr list` or a raw `curl`. A bounded
multi-PR sweep with a short sleep is blocked and needs the bypass (its why is 10+
characters). It catches the inline shape that cost the 5h.

Exit codes: 2 = block (stderr goes back to Claude), 0 = allow. Malformed input
allows: failing closed on the harness's own bug would block every Bash call.
"""
from __future__ import annotations

import json
import re
import sys

# why `do` is required: a bare `for` matched English in a comment and refused a one-shot
# `sleep 120; gh pr checks 904` (PR #904 review round 1). A shell loop always has `do`.
LOOP_RE = re.compile(r"\b(while|until|for)\b[^\n]*?\bdo\b")
GH_RE = re.compile(r"\bgh\s+(pr\s+(view|checks|status)\b|api\s+\S*pulls/)")
SLEEP_RE = re.compile(r"\bsleep\b")
WATCHER = "pr-progress-watch"
BYPASS_RE = re.compile(r"pr-watch-skip:\s*\S[^\n]{9,}")

MESSAGE = (
    "BLOCKED: this command loops `gh pr view`/`gh pr checks` with `sleep`, so it wakes "
    "only on one event.\n\n"
    "Use the watcher, which also wakes on a stall:\n"
    "  bash q-system/.q-system/scripts/pr-progress-watch.sh <pr> [-R owner/repo] "
    "[--stall-min N] [--deadline-min M]\n"
    "  exit 0 = PR<n> MERGED <oid> or PR<n> CLOSED\n"
    "  exit 3 = PR<n> STALLED <reason> (no change for N min, default 30, or deadline, "
    "default 360); the reason names red checks, a conflict, changes requested, or no "
    "verdict at the head\n"
    "Run it in the background and act on the exit.\n\n"
    "Scar: a 6h merge-only loop on PR 903 idled a session about 5h while the PR waited "
    "on a reviewer nothing had started (ASK-5842).\n"
    "If this command only QUOTES the pattern, or is a bounded sweep over several PRs and not a\n"
    "wait, add `pr-watch-skip: <why>` to it; the why must be at least 10 characters.\n"
)


def blocked(command: str) -> bool:
    if WATCHER in command or BYPASS_RE.search(command):
        return False
    return bool(LOOP_RE.search(command) and GH_RE.search(command) and SLEEP_RE.search(command))


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(data, dict) or data.get("tool_name") not in (None, "Bash"):
        return 0
    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not blocked(command):
        return 0
    sys.stderr.write(MESSAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main())
