#!/usr/bin/env python3
"""Auto-commit hook - groups changed files by area and creates organized commits.

Runs on Stop (async). Creates one commit per area with conventional commit messages.
Never pushes. Skips if no uncommitted changes.
"""
import subprocess
import sys
import os
from collections import defaultdict

PROJ_DIR = os.environ.get("CLAUDE_PROJECT_DIR", ".")

# Map file paths to commit areas
AREA_MAP = [
    ("q-system/canonical/",           "content",  "update canonical files"),
    ("q-system/my-project/",          "content",  "update project state"),
    ("q-system/marketing/",           "content",  "update marketing content"),
    ("q-system/memory/",              "chore",    "update session memory"),
    ("q-system/output/",              None,       None),  # skip - gitignored
    ("q-system/hooks/",               "chore",    "update hooks"),
    ("q-system/.q-system/agent-pipeline/", "feat", "update agent pipeline"),
    ("q-system/.q-system/",           "chore",    "update system infrastructure"),
    ("plugins/",                      "feat",     "update plugins"),
    (".claude/rules/",                "chore",    "update rules"),
    (".claude/agents/",               "chore",    "update agent definitions"),
    (".claude/output-styles/",        "chore",    "update output styles"),
    (".claude/settings",              "chore",    "update settings"),
    ("sites/",                        "feat",     "update site pages"),
    ("memory/",                       "chore",    "update auto-memory"),
]

FALLBACK_AREA = ("chore", "update project files")


def run(cmd, **kwargs):
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=PROJ_DIR, **kwargs
    )


def get_changed_files():
    """Get all uncommitted files (staged + unstaged + untracked)."""
    # Staged and unstaged
    r = run(["git", "diff", "--name-only", "HEAD"])
    files = set(r.stdout.strip().splitlines()) if r.stdout.strip() else set()

    # Untracked
    r = run(["git", "ls-files", "--others", "--exclude-standard"])
    if r.stdout.strip():
        files.update(r.stdout.strip().splitlines())

    # Staged but not yet diffed against HEAD (new files)
    r = run(["git", "diff", "--cached", "--name-only"])
    if r.stdout.strip():
        files.update(r.stdout.strip().splitlines())

    # Filter out empty strings and gitignored patterns
    return {f for f in files if f and not f.startswith("q-system/output/")}


def classify(filepath):
    """Map a file path to (type, message) based on AREA_MAP."""
    for prefix, commit_type, msg in AREA_MAP:
        if filepath.startswith(prefix):
            if commit_type is None:
                return None  # skip this file
            return (commit_type, msg)
    return FALLBACK_AREA


def group_files(files):
    """Group files by their commit area."""
    groups = defaultdict(list)
    for f in sorted(files):
        result = classify(f)
        if result is None:
            continue
        key = result  # (type, message)
        groups[key].append(f)
    return groups


def commit_group(commit_type, message, files):
    """Stage files and create a commit."""
    # Stage
    run(["git", "add", "--"] + files)

    # Build commit message
    header = f"{commit_type}: {message}"
    body_lines = [f"- {f}" for f in files[:20]]
    if len(files) > 20:
        body_lines.append(f"- ... and {len(files) - 20} more files")

    full_msg = header + "\n\n" + "\n".join(body_lines)

    r = run(["git", "commit", "-m", full_msg])
    if r.returncode == 0:
        print(f"  committed: {header} ({len(files)} files)")
    else:
        # Could be nothing to commit (already staged), not fatal
        print(f"  skipped: {header} - {r.stderr.strip()[:80]}")


def main():
    # Check we're in a git repo
    r = run(["git", "rev-parse", "--is-inside-work-tree"])
    if r.returncode != 0:
        return

    files = get_changed_files()
    if not files:
        print("auto-commit: no changes")
        return

    groups = group_files(files)
    if not groups:
        print("auto-commit: no committable changes")
        return

    print(f"auto-commit: {len(files)} files in {len(groups)} groups")
    for (commit_type, message), group_files_list in groups.items():
        commit_group(commit_type, message, group_files_list)

    print("auto-commit: done")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Never block session exit
        print(f"auto-commit error: {e}", file=sys.stderr)
        sys.exit(0)
