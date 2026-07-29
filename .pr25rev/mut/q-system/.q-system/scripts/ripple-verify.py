#!/usr/bin/env python3
"""
Verify that all ripple targets were addressed after canonical edits.

Two checks:
1. For every changelog entry today, verify ripple targets also have entries.
2. For every canonical file in the ripple graph that was modified on disk
   (git diff), verify it HAS a changelog entry. This prevents silent bypass
   where Claude edits a canonical file without calling changelog-write.py.

Usage:
    python3 ripple-verify.py <changelog-path> <date> [--json]

Exit 0 = all targets addressed, no unlogged edits
Exit 1 = missing targets or unlogged edits (printed to stdout)
Exit 2 = ripple-graph.json missing or malformed
"""

import json
import os
import re
import subprocess
import sys

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
# Subtree instances nest q-system/ inside q-system/
if not os.path.isdir(os.path.join(QROOT, "canonical")) and os.path.isdir(os.path.join(QROOT, "q-system", "canonical")):
    QROOT = os.path.join(QROOT, "q-system")
PROJECT_ROOT = os.path.normpath(os.path.join(QROOT, ".."))
RIPPLE_GRAPH = os.path.join(QROOT, ".q-system", "ripple-graph.json")


def load_ripple_graph():
    try:
        with open(RIPPLE_GRAPH) as f:
            return json.load(f)["graph"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        print(f"ERROR: ripple-graph.json: {e}", file=sys.stderr)
        sys.exit(2)


def parse_changelog_entries(changelog_path, target_date):
    entries = []
    files_touched = set()
    try:
        with open(changelog_path) as f:
            content = f.read()
    except FileNotFoundError:
        return entries, files_touched

    pattern = rf"### {re.escape(target_date)} \| ([^\|]+) \| ([^\n]+)"
    for match in re.finditer(pattern, content):
        file_key = match.group(2).strip()
        entries.append({"file": file_key})
        files_touched.add(file_key)

    return entries, files_touched


def get_all_ripple_targets(graph, entries):
    required = {}
    for entry in entries:
        file_key = entry["file"]
        targets = graph.get(file_key, [])
        for t in targets:
            if t != file_key:
                if t not in required:
                    required[t] = []
                required[t].append(file_key)
    return required


def get_modified_canonical_files(graph):
    """Check git for canonical files in the ripple graph with uncommitted changes.
    Returns set of graph keys (relative to q-system/) that were modified."""
    modified = set()

    # Build set of all files the graph knows about
    graph_keys = set(graph.keys())
    for targets in graph.values():
        graph_keys.update(targets)

    try:
        # Unstaged changes
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=10,
            cwd=PROJECT_ROOT,
        )
        # Staged changes
        staged = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            capture_output=True, text=True, timeout=10,
            cwd=PROJECT_ROOT,
        )
        changed_files = set()
        for line in (result.stdout + staged.stdout).splitlines():
            line = line.strip()
            if line:
                changed_files.add(line)

        # Git paths are relative to project root (e.g. q-system/canonical/objections.md)
        # Graph keys are relative to q-system/ (e.g. canonical/objections.md)
        for git_path in changed_files:
            if git_path.startswith("q-system/"):
                graph_key = git_path[len("q-system/"):]
                if graph_key in graph_keys:
                    modified.add(graph_key)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # git not available - skip this check silently
        pass

    return modified


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: ripple-verify.py <changelog-path> <date> [--json]",
            file=sys.stderr,
        )
        sys.exit(1)

    changelog_path = sys.argv[1]
    target_date = sys.argv[2]
    json_mode = "--json" in sys.argv

    graph = load_ripple_graph()
    entries, files_touched = parse_changelog_entries(changelog_path, target_date)

    # Check 1: ripple target coverage (did we propagate to all affected files?)
    required = get_all_ripple_targets(graph, entries)
    missing = {}
    for target, sources in required.items():
        if target not in files_touched:
            missing[target] = sources

    # Check 2: unlogged edits (did someone edit a canonical file without changelog?)
    modified_on_disk = get_modified_canonical_files(graph)
    unlogged = sorted(modified_on_disk - files_touched)

    has_problems = bool(missing) or bool(unlogged)

    if json_mode:
        print(
            json.dumps(
                {
                    "date": target_date,
                    "entries": len(entries),
                    "files_touched": sorted(files_touched),
                    "ripple_targets_required": len(required),
                    "missing_targets": missing,
                    "unlogged_edits": unlogged,
                    "complete": not has_problems,
                },
                indent=2,
            )
        )
    else:
        if not entries and not unlogged:
            print(f"No changelog entries for {target_date}. Nothing to verify.")
            sys.exit(0)

        if unlogged:
            print(
                f"UNLOGGED EDITS ({len(unlogged)} canonical files "
                f"modified without changelog entry):\n"
            )
            for f in unlogged:
                print(f"  x {f}  (run changelog-write.py before continuing)")
            print()

        if missing:
            print(f"INCOMPLETE RIPPLE ({len(missing)} targets not addressed):\n")
            for target, sources in missing.items():
                print(f"  x {target}")
                for s in sources:
                    print(f"      triggered by: {s}")
            print(f"\nRun content-lint.py after addressing these.")

        if not has_problems:
            print(
                f"Ripple complete. {len(entries)} edits, "
                f"{len(required)} targets, all addressed. No unlogged edits."
            )

    sys.exit(1 if has_problems else 0)


if __name__ == "__main__":
    main()
