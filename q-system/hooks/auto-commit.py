#!/usr/bin/env python3
"""Auto-commit hook - groups changed files by area and creates organized commits.

Runs on Stop (async). Creates one commit per area with conventional commit messages.
Never pushes. Skips if no uncommitted changes.
"""
import hashlib
import json
import subprocess
import sys
import os
import time
from collections import defaultdict

PROJ_DIR = os.environ.get("CLAUDE_PROJECT_DIR", ".")

# Map file paths to commit areas
AREA_MAP = [
    ("q-system/canonical/",           "content",  "update canonical files"),
    ("q-system/my-project/",          "content",  "update project state"),
    ("q-system/marketing/",           "content",  "update marketing content"),
    ("q-system/memory/",              "chore",    "update session memory"),
    # Append-only ledgers the system writes for itself (spillover, gates,
    # findings). ASK-605: these were unclassified, so cole-gtm's dirty
    # .prd-os/spillover.jsonl blocked its sync with no path out -- the updater
    # would not take it and no rule said who should.
    (".prd-os/",                      "chore",    "update prd-os ledgers"),
    # skip - gitignored. That claim is now TESTED against `git check-ignore`
    # rather than trusted: it used to be FALSE for any extension the .gitignore
    # did not list (*.md was not listed), and such a file is never committed,
    # never ignored and never even reported, so it blocks the fleet sync
    # invisibly. cole-gtm sat stuck on two of them.
    ("q-system/output/",              None,       None),
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


# AREA_MAP's prefixes all start `q-system/`, which is the SKELETON. In an INSTANCE the
# real content lives one segment over -- q-consult/canonical, q-consult/my-project and
# so on -- so none of it matched any row. Measured on the consulting instance: 1047 of
# 2099 tracked files unclassified, including my-project (the system of record) and
# marketing. Removing the fallback without this would have disabled the safety net for
# exactly the generated state it exists to protect (adversarial review finding-2).
#
# Matched against the path with its FIRST segment stripped, so one row covers every
# instance without reading a registry. Source trees (pipeline/, email-watch/) are
# deliberately absent: code is what an agent commits deliberately, and sweeping it is
# the defect this whole change removes.
INSTANCE_AREAS = [
    ("canonical/",   "content", "update canonical files"),
    ("my-project/",  "content", "update project state"),
    ("marketing/",   "content", "update marketing content"),
    ("memory/",      "chore",   "update session memory"),
    ("output/",      None,      None),   # generated churn; never committed
]


SKIP_DECLARED = "declared-skip"       # matched AREA_MAP with commit_type None
SKIP_UNCLASSIFIED = "unclassified"    # matched nothing: never auto-committed


# Checked BEFORE any prefix match. A prefix is a blunt instrument: `.prd-os/`
# is mostly machine-written ledgers, but it also holds authored issue specs, and
# every resolve drops a `.lock` beside the ledger it is writing.
NEVER_AUTO_COMMIT = (
    ".lock",                 # sp-a21cb27c: ephemeral, and sweeping it is a race
)
NEVER_AUTO_COMMIT_DIRS = (
    ".prd-os/issues/",       # issue SPECS are authored, not exhaust
    ".prd-os/findings/",     # review findings are authored
)

# Executable source, in ANY area. See the note in `classify`: the AREA_MAP rows
# `plugins/` and `q-system/.q-system/` are named for directories that happen to
# contain Python, so code was still being swept under a generic subject with no
# Linear id after ASK-498 supposedly ended that. Extension is the durable axis --
# a new code directory appears far more often than a new language does.
SOURCE_EXTENSIONS = (
    ".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
)


def classify(filepath):
    """(type, message) for an auto-committable file, else a SKIP_* reason string.

    Returns a STRING rather than None for both skip cases so the caller can tell
    "deliberately ignored" (q-system/output, gitignored) from "nobody classified
    this" (an instance's source tree). The second one is the whole point: it is
    reported to the operator instead of being swept.
    """
    if filepath.endswith(NEVER_AUTO_COMMIT) or \
            filepath.startswith(NEVER_AUTO_COMMIT_DIRS):
        return SKIP_UNCLASSIFIED
    # EXECUTABLE SOURCE IS NEVER SWEPT, whatever area it lands in (2026-08-13).
    #
    # ASK-498 removed the generic fallback and this file's own comment says source
    # trees are "deliberately absent: code is what an agent commits deliberately".
    # Two AREA_MAP rows still contradicted that, because they are named for
    # DIRECTORIES that happen to contain code: `plugins/` (the kipi-core plugin,
    # which is a Python package) and `q-system/.q-system/` (which holds scripts/).
    #
    # Measured 2026-08-13 on this instance, in one session: `test_length_axis.py`
    # was committed as "feat: update plugins" and `voice-dna-loader.py` as "chore:
    # update system infrastructure", both while the agent was still working on them
    # and before it could write a real message with a Linear id. That is the same
    # race and the same generic-subject outcome ASK-498 was opened to end; the fix
    # was scoped by directory when the real axis is WHAT THE FILE IS.
    #
    # Extension, not directory, because a new code directory is added far more often
    # than a new language is.
    if filepath.endswith(SOURCE_EXTENSIONS):
        return SKIP_UNCLASSIFIED
    for prefix, commit_type, msg in AREA_MAP:
        if filepath.startswith(prefix):
            if commit_type is None:
                return SKIP_DECLARED
            return (commit_type, msg)
    if "/" in filepath:
        tail = filepath.split("/", 1)[1]
        for prefix, commit_type, msg in INSTANCE_AREAS:
            if tail.startswith(prefix):
                if commit_type is None:
                    return SKIP_DECLARED
                return (commit_type, msg)
    return SKIP_UNCLASSIFIED


# Commit types that are the SYSTEM's own exhaust rather than the founder's
# writing. "chore" is session memory and system infrastructure; "content" and
# "feat" are canonical, my-project, marketing and plugins, all founder-authored.
SYSTEM_STATE_TYPES = frozenset(("chore",))


def system_state_paths(paths):
    """Subset of paths safe for the FLEET SYNC to commit unattended.

    why (ASK-605): kipi-update.sh carried its own three-entry
    SYSTEM_OWNED_PATHS list meaning exactly what classify() already means, and
    the two disagreed. `q-system/memory/open-loops.json` is written by a
    background heartbeat, is `chore` here, was absent there -- and on
    2026-08-10 it alone left 4 of 7 instances permanently unsyncable. One
    concept, one list, and this is the list.

    Deliberately NARROWER than classify(). The Stop hook may commit content in
    an active session where the founder is present; a fleet-wide sweep across
    every instance at once is a different blast radius, and half-finished
    canonical edits are not the updater's to take.
    """
    return [p for p in paths
            if isinstance(classify(p), tuple)
            and classify(p)[0] in SYSTEM_STATE_TYPES]


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

    TRANSCRIPT ONLY. This hook does NOT alert. Founder-directed 2026-08-10 after
    reading #general: 51 of 100 messages in one 4.5-hour window were this
    notification, and the four security reverts and one dead job posted into the
    same window were unreadable underneath them.

    An earlier round (ASK-603) tried to fix that with a throttle -- speak on a
    CHANGED file set, otherwise stay quiet for 12h. It did not work, and the
    reason is structural rather than a tuning miss: during active work the file
    set changes on nearly every turn, so the digest changes on nearly every turn,
    so the throttle passes. The condition being reported (files are uncommitted
    right now) is TRUE almost continuously while someone is working, and a
    continuously-true condition is not an event. No throttle value fixes that;
    only not alerting does.

    The information is not lost. It prints below, which is where the operator or
    the next session reads it. Anything here that genuinely needs a human is
    caught by the commit gates, not by a Stop-hook ping.
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

    # PATHSPEC, not a bare commit (2026-08-07, adversarial review finding-1).
    # `git commit -m` with no pathspec commits the ENTIRE INDEX, so anything an agent
    # had staged and not yet committed was swept in anyway -- while report_skipped
    # printed that it had NOT been committed. A false report is worse than the silence
    # it replaced: it tells the next session the file is still theirs to commit.
    # Reproduced before the fix: the hook printed "NOT committed
    # q-consult/pipeline/repo_links.py" and the commit contained that exact file.
    # kipi-update.sh already fixed this same defect once (its PR #98 note says so);
    # it came back through a different door.
    r = run(["git", "commit", "-m", full_msg, "--"] + files)
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
    # `--system-state`: read paths on stdin, print the subset the FLEET SYNC may
    # commit unattended. This is the shared-classifier chokepoint for ASK-605 --
    # kipi-update.sh shells this instead of keeping a second list that drifts.
    # Pure and side-effect free: it touches no git state and commits nothing.
    if "--system-state" in sys.argv:
        for path in system_state_paths(
                [ln.strip() for ln in sys.stdin if ln.strip()]):
            print(path)
        sys.exit(0)
    try:
        main()
    except Exception as e:
        # Never block session exit
        print(f"auto-commit error: {e}", file=sys.stderr)
        sys.exit(0)
