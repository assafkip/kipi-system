#!/usr/bin/env python3
"""PreToolUse gate: refuse a new git worktree when the disk is under the floor (ASK-2882).

A worktree of the consulting repo is ~390 MB. On 2026-10-22 agents kept adding
them until the disk hit 0 bytes free and every write on the Mac failed. This
refuses `git worktree add` (Bash) and EnterWorktree when free space is under
`refuse_worktree_below_gb` in worktree-reaper.json. Entering an existing
worktree (EnterWorktree with `path`) and everything else is allowed.

Contract: PreToolUse hook JSON on stdin. Deny = permissionDecision JSON on
stdout, exit 0. Allow = no output, exit 0. A crash on a command that names a
worktree add denies (the gate fails closed in its own jurisdiction); a crash on
anything else allows, so this can never block unrelated work.

`--check` (ASK-3648): the same floor for the shell producers that cut trees with
no tool call, so this hook never sees them: kipi-dispatch.sh before a tick and
linear-worker.sh before `git worktree add`. On 2026-11-08 those producers took the
disk to 0 bytes free while this hook stood guard over a door nobody used.
Prints one line. Exit 0 = at or over the floor, 1 = under it, 2 = could not
measure. The callers proceed on 2: a full disk makes `git worktree add` fail
loudly anyway, while refusing on a broken measurement would hold every tick
with nothing that clears it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE_ADD = re.compile(r"\bworktree\s+add\b")


def _reaper():
    spec = importlib.util.spec_from_file_location(
        "worktree_reaper", os.path.join(HERE, "worktree-reaper.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def in_jurisdiction(payload: dict) -> bool:
    if payload.get("tool_name") == "EnterWorktree":
        # `path` enters a worktree that already exists and allocates nothing;
        # only a create costs disk (PR #556 review). Refusing re-entry would
        # block the agent from committing and freeing its own tree.
        return not (payload.get("tool_input") or {}).get("path")
    if payload.get("tool_name") != "Bash":
        return False
    command = (payload.get("tool_input") or {}).get("command") or ""
    return bool(WORKTREE_ADD.search(command))


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"worktree-disk-floor: {reason}",
    }}))


def check() -> int:
    # The floor read and the comparison sit INSIDE the try (PR #656 review,
    # finding 2): exit 1 holds the whole fleet, so a crash after the measure (a
    # hand-edited "5 GB" in the config) must read as "could not measure", not as
    # "under the floor".
    try:
        reaper = _reaper()
        cfg = reaper.load_config()
        free = float(reaper.free_gb())
        floor = float(cfg["refuse_worktree_below_gb"])
        under = free < floor
    except Exception as exc:  # noqa: BLE001
        print(f"disk-floor: could not measure free disk space ({exc!r})")
        return 2
    print(f"disk-floor: {free:.1f} GB free, floor {floor:g} GB -> {'UNDER' if under else 'OK'}")
    return 1 if under else 0


def main() -> int:
    if "--check" in sys.argv[1:]:
        return check()   # never reads stdin: a caller inside `while read` keeps its input
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        if WORKTREE_ADD.search(raw):
            deny("could not read the hook input for a worktree add; refusing")
        return 0
    if not in_jurisdiction(payload):
        return 0
    try:
        reaper = _reaper()
        cfg = reaper.load_config()
        free = reaper.free_gb()
    except Exception as exc:  # noqa: BLE001
        deny(f"could not measure free disk space ({exc!r}); refusing the worktree")
        return 0
    floor = cfg["refuse_worktree_below_gb"]
    if free < floor:
        deny(f"{free:.1f} GB free, under the {floor} GB floor. A worktree is "
             f"~0.4 GB. Free space first: python3 {HERE}/worktree-reaper.py "
             f"lists finished worktrees, and --apply removes them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
