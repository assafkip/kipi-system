#!/usr/bin/env python3
"""The skeleton's guard set, for a dispatch target that carries no project
settings of its own (ASK-3529).

Usage:
  skeleton-guard-settings.py          print the set as one compact JSON object, exit 0;
                                      exit 1 and print nothing on stdout if it does not resolve
  skeleton-guard-settings.py --check  one line on stdout; exit 0 resolves, exit 1 refuses

The set is <root>/settings-template.json cut down to what GUARDS an agent:
  - "hooks": every "$CLAUDE_PROJECT_DIR/" rewritten to this skeleton's absolute
    root, and every hook that names an EXCLUDED script removed;
  - "permissions": {"deny": [...]}, verbatim.
Never model, plugins, allow rules or a default permission mode. Those change
what the agent CAN do, not what stops it, and a target's run must not change
behaviour because the worker reached it.

The root is derived from THIS file's location, the same rule repo-preflight.sh
uses for SKELETON: the reference follows the code, so the pinned checkout that
runs the worker is the one whose guards the agent gets.

WHY ONLY FOR A TREE WITH NO SETTINGS. Measured 2026-10-31 with a counter hook in
a scratch repo, `claude -p --settings <x>`:
  project hook only                     -> fired once
  project + --settings, other command   -> BOTH fired (additive, not a replacement)
  project + --settings, same command    -> fired once (identical commands dedupe)
  no project settings + --settings      -> the supplied hook fired
A rewritten "<root>/q-system/..." command never equals an instance's own
"$CLAUDE_PROJECT_DIR/q-system/..." command, so handing this set to a tree that
has settings fires every guard twice (auto-commit, every lint, session start).
Consumers supply it only when the tree has no .claude/settings.json.

Consumers: linear-worker.sh (`claude -p --settings`, at every call site that
starts an agent session in an issue tree) and repo-preflight.sh check 3
(--check, for a target with no settings). One renderer, so the set the
preflight approves is byte-for-byte the set the agent gets.
"""
import json
import os
import re
import sys

ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
PREFIX = "$CLAUDE_PROJECT_DIR/"
# The same extraction repo-preflight.sh check 3 uses to name a hook's script.
SCRIPT_NAME = re.compile(r"[\w.-]+\.(?:py|sh)")
# The rewritten root lands inside template commands, most of them inside double
# quotes but not all. A root needing shell quoting would split or expand there,
# so it is refused rather than escaped.
SAFE_ROOT = re.compile(r"^/[A-Za-z0-9._/+-]+$")

# HOOKS THAT BREAK OUTSIDE AN INSTANCE, BY SCRIPT NAME. Each was found by running
# every template hook row once against a throwaway worktree of a non-instance
# target, prefix rewritten to a copy of the skeleton, and once against the
# skeleton copy as an instance-like control, with the filesystem of both trees
# diffed per row (ASK-3529 PR body holds the 66-row table). "Breaks" means: it
# writes into the pinned skeleton, writes instance layout into the target,
# needs q-system/ in the target, or puts wrong or false text in the agent's
# context. A hook is dropped when its command names any key here, so a row
# naming two scripts goes if either one is listed.
EXCLUDED = {
    "md-prune.py":
        "Resolves its root from __file__, so with the rewrite it prunes and archives markdown "
        "inside the pinned skeleton checkout, never the target.",
    "sycophancy-monthly-check.py":
        "Stamp and harness resolve from __file__: on the first session of a month it runs the "
        "skeleton's harness and writes its stamp into the pinned checkout.",
    "fleet-board-refresh.py":
        "Its subject is the skeleton's fleet board by construction (root from __file__); when it "
        "fires it tells the agent to regenerate and republish that board.",
    "claude-integrity-tripwire.py":
        "Measured: writes its baseline, lock and armed files into the pinned checkout's "
        "q-system/.q-system/, one file shared by every concurrent worker. Also drops the "
        "self-heal row that names it, whose restore would run git checkout in the target tree.",
    "hook-path-resolve-check.py":
        "Fires only on a settings.json edit, then reports on the skeleton's own settings files "
        "(REPO_ROOT from __file__), never on the target's.",
    "auto-update.sh":
        "Creates q-system/output in the target before its own instance test, and its only "
        "message tells the agent to run the fleet updater, which a target never takes.",
    "stop-logger.sh":
        "Measured: writes q-system/output/session-effort-<date>.log into the target tree at "
        "the end of every turn.",
    "code_claim_grounding_guard.py":
        "Measured on a fresh target tree: injects a false 'manifest is UNREADABLE' warning on "
        "every Stop, names a script the target does not have, and writes q-system/output/ there.",
    "knowledge-inject.py":
        "Measured: appends a manifest_missing receipt to memory/.knowledge-supply-receipts.jsonl "
        "in the target on every prompt, and injects nothing.",
}


class Unresolved(Exception):
    """The set cannot be built, or names a guard the skeleton does not have."""


def render(root=ROOT):
    """The set the agent gets: exactly hooks and permissions, nothing else."""
    return build(root)[0]


def build(root=ROOT):
    """(set, dropped): dropped counts template hook ROWS removed, which is not the
    number of EXCLUDED names, because one row can name two scripts (PR #583 review)."""
    if not SAFE_ROOT.match(root):
        raise Unresolved("skeleton root %r holds characters a hook command cannot carry unquoted" % root)
    try:
        with open(os.path.join(root, "settings-template.json")) as fh:
            tpl = json.load(fh)
    except (OSError, ValueError) as e:
        raise Unresolved("settings-template.json is unreadable: %s" % e)
    excluded = set(EXCLUDED)
    hooks = {}
    dropped = 0
    for event, groups in (tpl.get("hooks") or {}).items():
        kept_groups = []
        for group in groups or []:
            kept = []
            for hook in group.get("hooks") or []:
                cmd = hook.get("command") or ""
                if set(SCRIPT_NAME.findall(cmd)) & excluded:
                    dropped += 1
                    continue
                kept.append(dict(hook, command=cmd.replace(PREFIX, root + "/")))
            if kept:
                kept_groups.append(dict(group, hooks=kept))
        if kept_groups:
            hooks[event] = kept_groups
    if not hooks:
        raise Unresolved("no hook is left after the exclusions, and an empty set guards nothing")
    # A NAME IS NOT AN EXECUTABLE (the scar repo-preflight.sh check 3 carries): every
    # script a kept hook runs must exist under this root, or the guard it names is
    # silently off. Most commands are `test -f X && python3 X`, which would hide it.
    path_rx = re.compile(re.escape(root) + r"/[\w./-]+\.(?:py|sh)")
    absent = sorted({os.path.relpath(p, root)
                     for groups in hooks.values() for g in groups for h in g["hooks"]
                     for p in path_rx.findall(h["command"]) if not os.path.isfile(p)})
    if absent:
        raise Unresolved("guards the template wires are absent from the skeleton: " + ", ".join(absent))
    deny = (tpl.get("permissions") or {}).get("deny") or []
    return {"hooks": hooks, "permissions": {"deny": list(deny)}}, dropped


def main(argv):
    args = argv[1:]
    if args not in ([], ["--check"]):
        print("usage: skeleton-guard-settings.py [--check]", file=sys.stderr)
        return 2
    check = args == ["--check"]
    try:
        s, dropped = build()
    except Unresolved as e:
        print("skeleton guard set does not resolve: %s" % e, file=sys.stdout if check else sys.stderr)
        return 1
    if check:
        # This line is what repo-preflight.sh shows the operator, so each number
        # says exactly what it counts: rows kept, rows dropped, names that drop them.
        n = sum(len(g["hooks"]) for groups in s["hooks"].values() for g in groups)
        print("skeleton guard set resolves: %d hook commands across %d events, %d deny rules; "
              "%d template hooks dropped, naming %d excluded scripts"
              % (n, len(s["hooks"]), len(s["permissions"]["deny"]), dropped, len(EXCLUDED)))
        return 0
    json.dump(s, sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
