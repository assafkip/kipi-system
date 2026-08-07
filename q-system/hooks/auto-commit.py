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

# NO FALLBACK. An unclassified path is REPORTED, never committed (2026-08-07, ASK-498).
#
# This used to be `("chore", "update project files")`, so every path not named in
# AREA_MAP above -- an instance's own source tree, its tests, its config -- was swept
# into one unattended commit with a generic subject and no issue id.
#
# Measured cost in a single session on the consulting instance: three sweeps
# (d96e621, 7a252f4, f0a3183) carried real feature work onto `main` under
# "chore: update project files". Two of them also RACED the agent writing the files:
# a `git add` of new files reported success and staged nothing, because the hook had
# already committed them a moment earlier, and the agent's own commit then silently
# contained only half its change.
#
# The hook's purpose is a safety net for GENERATED STATE -- canonical files, session
# memory, marketing content -- that nobody would otherwise commit. Source code is the
# opposite case: it is exactly what an agent commits deliberately, with a real message
# and a Linear id. Sweeping it is not a safety net, it is a second writer to the same
# branch.
#
# Uncommitted is not lost: the files are on disk. What is removed here is an
# unattended commit nobody asked for. `report_skipped` makes the remainder loud
# rather than silent, so the safety net becomes a NOTICE for source code and stays a
# COMMIT for the generated state it was built for.


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


SKIP_DECLARED = "declared-skip"       # matched AREA_MAP with commit_type None
SKIP_UNCLASSIFIED = "unclassified"    # matched nothing: never auto-committed


def classify(filepath):
    """(type, message) for an auto-committable file, else a SKIP_* reason string.

    Returns a STRING rather than None for both skip cases so the caller can tell
    "deliberately ignored" (q-system/output, gitignored) from "nobody classified
    this" (an instance's source tree). The second one is the whole point: it is
    reported to the operator instead of being swept.
    """
    for prefix, commit_type, msg in AREA_MAP:
        if filepath.startswith(prefix):
            if commit_type is None:
                return SKIP_DECLARED
            return (commit_type, msg)
    return SKIP_UNCLASSIFIED


def group_files(files):
    """(groups, unclassified). Only classified files are ever committed."""
    groups = defaultdict(list)
    unclassified = []
    for f in sorted(files):
        result = classify(f)
        if result == SKIP_UNCLASSIFIED:
            unclassified.append(f)
            continue
        if result == SKIP_DECLARED:
            continue
        groups[result].append(f)
    return groups, unclassified


def report_skipped(unclassified):
    """Say out loud what was left uncommitted, and why.

    Silence here would recreate the original defect in reverse: work sitting
    uncommitted with nobody told. The hook prints to the Stop transcript, which is
    where the operator or the next session sees it.
    """
    if not unclassified:
        return
    print(f"auto-commit: {len(unclassified)} file(s) NOT committed "
          f"(unclassified path, commit these yourself with a real message + issue id):")
    for f in unclassified[:20]:
        print(f"  - {f}")
    if len(unclassified) > 20:
        print(f"  - ... and {len(unclassified) - 20} more")


def commit_group(commit_type, message, files):
    """Stage files and create a commit."""
    # Stage
    run(["git", "add", "--"] + files)

    # Build commit message
    header = f"{commit_type}: {message}"
    body_lines = [f"- {f}" for f in files[:20]]
    if len(files) > 20:
        body_lines.append(f"- ... and {len(files) - 20} more files")

    # The linear-first commit-msg gate refuses any commit with no issue id.
    # This hook fires unattended on Stop and has no way to know which issue the
    # session belonged to, so it declares itself as a bypass rather than being
    # silently blocked -- which would kill the safety net that makes work
    # survive a context loss or a parallel-session branch switch.
    # Consequence on purpose: every auto-commit shows up in the bypass ledger,
    # so "how much work never reached Linear" is a number, not a guess.
    body_lines.append("")
    body_lines.append("[no-issue: auto-commit safety net, unattended Stop hook]")

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

    groups, unclassified = group_files(files)
    if not groups:
        print("auto-commit: no committable changes")
        report_skipped(unclassified)
        return

    print(f"auto-commit: {len(files)} files in {len(groups)} groups")
    for (commit_type, message), group_files_list in groups.items():
        commit_group(commit_type, message, group_files_list)

    report_skipped(unclassified)
    print("auto-commit: done")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Never block session exit
        print(f"auto-commit error: {e}", file=sys.stderr)
        sys.exit(0)
