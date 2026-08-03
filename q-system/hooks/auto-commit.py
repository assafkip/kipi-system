#!/usr/bin/env python3
"""Auto-commit hook - snapshots dirty work to a per-session WIP ref.

Runs on Stop (async). Never pushes. Never writes to a named branch.

WHY A REF AND NOT A COMMIT (scar 2026-08-02, ASK-314, RCA
`rca-unattended-committer-misattribution-2026-08-02.md`):

This hook used to `git add` whatever was dirty and `git commit` it to whatever
branch happened to be checked out, under a fixed subject line. In one session it
did three kinds of damage:

  - 7383d6c swept finished ASK-122 work onto `sana/ask-294`, an unrelated
    issue's branch. Recovery cost a worktree extraction, a reland, and a revert.
  - 4559194 swept an in-flight ASK-312 fix plus an unrelated config change into
    one `chore: update system infrastructure`, discarding the message its author
    was about to write. Cost an hour of chasing the wrong cause.
  - A session that switched branches mid-run landed its work split across both.

All three follow from ONE property: it wrote to HEAD. "Everything dirty" in a
repo where several issues are in flight is a snapshot of a moment, and a moment
is not a unit of work. Improving the subject line would not have helped; the
work would still have been on the wrong branch.

So the writer keeps its durability job and loses its history-writing power. It
builds the snapshot in a throwaway index and lands it on `refs/kipi/wip/<session>`
via commit-tree/update-ref. Consequences, all intended:

  - HEAD, the real index, and the working tree are never touched, so the author
    still holds their dirty work and still writes their own commit message.
  - No named branch can gain a commit nobody intended, on any branch, ever.
  - Two sessions sharing a checkout write to two different refs, so neither can
    sweep up the other's uncommitted work.
  - Nothing is lost: a ref is a real ref, so gc will not prune it, and recovery
    is `git cherry-pick` or `git checkout <ref> -- <path>`.

Note it no longer declares a `[no-issue]` bypass. That marker existed because
the `linear-issue-ref` commit-msg gate refuses a commit with no issue id, and an
unattended hook cannot know the issue -- which meant the one gate positioned to
catch this writer was disarmed by design. This is not a quieter bypass: the hook
no longer writes to history at all, so there is nothing for that gate to check.
The gate's purpose is now satisfied structurally rather than waived.

Off switch: KIPI_AUTOCOMMIT=off (also 0/false/no).
"""
import json
import os
import subprocess
import sys
import tempfile

PROJ_DIR = os.environ.get("CLAUDE_PROJECT_DIR", ".")

WIP_NAMESPACE = "refs/kipi/wip"

# q-system/output/ is scratch/generated and is gitignored in most instances.
# Kept as an explicit skip so an instance that tracks it still does not get its
# generated churn snapshotted on every single turn.
SKIP_PREFIXES = ("q-system/output/",)

# Markers git leaves while an operation is mid-flight. We still snapshot in this
# state -- a half-finished merge is exactly when losing work hurts most -- but
# the state is recorded in the message so a later cherry-pick is warned that the
# tree may contain conflict markers.
IN_PROGRESS_MARKERS = (
    ("MERGE_HEAD", "merge"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("REVERT_HEAD", "revert"),
    ("rebase-merge", "rebase"),
    ("rebase-apply", "rebase"),
)


def run(cmd, **kwargs):
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=PROJ_DIR, **kwargs
    )


def git_ok(cmd, **kwargs):
    """Run git, return stdout stripped, or None on failure."""
    r = run(cmd, **kwargs)
    return r.stdout.strip() if r.returncode == 0 else None


def disabled():
    return os.environ.get("KIPI_AUTOCOMMIT", "").strip().lower() in (
        "off", "0", "false", "no",
    )


def read_session_id():
    """Stop payload carries session_id. Fall back rather than refuse: a snapshot
    under a generated name still beats losing the work."""
    sid = ""
    try:
        raw = sys.stdin.read()
        if raw.strip():
            sid = str(json.loads(raw).get("session_id", "") or "")
    except Exception:
        sid = ""
    if not sid:
        sid = "unknown-" + str(os.getppid())
    # Ref components: keep it conservative rather than trusting the payload.
    safe = "".join(c if (c.isalnum() or c in "._-") else "-" for c in sid)
    return safe.strip("-.") or "unknown"


def get_changed_files():
    """All uncommitted paths: tracked modifications, staged, and untracked."""
    files = set()

    r = run(["git", "diff", "--name-only", "HEAD"])
    if r.stdout.strip():
        files.update(r.stdout.strip().splitlines())

    r = run(["git", "ls-files", "--others", "--exclude-standard"])
    if r.stdout.strip():
        files.update(r.stdout.strip().splitlines())

    r = run(["git", "diff", "--cached", "--name-only"])
    if r.stdout.strip():
        files.update(r.stdout.strip().splitlines())

    return sorted(
        f for f in files if f and not f.startswith(SKIP_PREFIXES)
    )


def in_progress_ops(git_dir):
    found = []
    for marker, label in IN_PROGRESS_MARKERS:
        if os.path.exists(os.path.join(git_dir, marker)):
            if label not in found:
                found.append(label)
    return found


def build_tree(files):
    """Stage `files` into a THROWAWAY index and write the tree.

    The real index is never opened. That is the point: the author's staged state
    is theirs, and a Stop hook that consumed it is what discarded three
    in-progress commit messages on 2026-08-02.
    """
    fd, tmp_index = tempfile.mkstemp(prefix="kipi-wip-index-")
    os.close(fd)
    os.unlink(tmp_index)  # git wants to create it itself
    env = dict(os.environ, GIT_INDEX_FILE=tmp_index)
    try:
        # Seed from HEAD so the snapshot is a full tree, not just the dirty set.
        if run(["git", "read-tree", "HEAD"], env=env).returncode != 0:
            run(["git", "read-tree", "--empty"], env=env)

        # Chunked: a large dirty set can blow the argv limit, and a snapshot
        # that silently truncates is worse than no snapshot.
        for i in range(0, len(files), 400):
            chunk = files[i:i + 400]
            r = run(["git", "add", "--"] + chunk, env=env)
            if r.returncode != 0:
                # One bad path (vanished mid-run, ignored) must not sink the
                # whole snapshot. Retry the chunk one path at a time.
                for f in chunk:
                    run(["git", "add", "--", f], env=env)

        return git_ok(["git", "write-tree"], env=env)
    finally:
        if os.path.exists(tmp_index):
            os.unlink(tmp_index)


def main():
    if run(["git", "rev-parse", "--is-inside-work-tree"]).returncode != 0:
        return

    if disabled():
        print("auto-commit: disabled via KIPI_AUTOCOMMIT")
        return

    session_id = read_session_id()

    files = get_changed_files()
    if not files:
        print("auto-commit: no changes")
        return

    tree = build_tree(files)
    if not tree:
        print("auto-commit: could not write tree, nothing snapshotted")
        return

    ref = f"{WIP_NAMESPACE}/{session_id}"
    prev = git_ok(["git", "rev-parse", "--verify", "--quiet", ref])
    head = git_ok(["git", "rev-parse", "--verify", "--quiet", "HEAD"])
    parent = prev or head

    # A Stop hook fires every turn. Without this the ref grows an identical
    # commit per turn and the useful history is buried in noise.
    if parent and git_ok(["git", "rev-parse", f"{parent}^{{tree}}"]) == tree:
        print("auto-commit: no change since last snapshot")
        return

    git_dir = git_ok(["git", "rev-parse", "--absolute-git-dir"]) or ".git"
    branch = git_ok(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or "(detached)"
    ops = in_progress_ops(git_dir)

    subject = f"wip: session snapshot on {branch} ({len(files)} files)"
    body = [
        "",
        "Unattended Stop-hook snapshot. NOT a commit on any branch -- it exists",
        "only on the ref below so nothing is lost if this session dies.",
        "",
        f"session: {session_id}",
        f"branch:  {branch}",
        f"head:    {head or '(none)'}",
    ]
    if ops:
        body.append(f"WARNING: {', '.join(ops)} in progress -- tree may contain")
        body.append("conflict markers. Inspect before reusing this snapshot.")
    body.append("")
    body += [f"- {f}" for f in files[:40]]
    if len(files) > 40:
        body.append(f"- ... and {len(files) - 40} more")

    args = ["git", "commit-tree", tree]
    if parent:
        args += ["-p", parent]
    args += ["-m", subject + "\n" + "\n".join(body)]
    commit = git_ok(args)
    if not commit:
        print("auto-commit: commit-tree failed, nothing snapshotted")
        return

    # Compare-and-swap. Two sessions never share a ref, but a session whose
    # hook overlaps itself would otherwise race. Empty oldvalue asserts the ref
    # does not yet exist.
    r = run(["git", "update-ref", ref, commit, prev if prev else ""])
    if r.returncode != 0:
        print(f"auto-commit: ref update refused ({r.stderr.strip()[:80]})")
        return

    print(f"auto-commit: snapshotted {len(files)} files -> {ref} ({commit[:8]})")
    if ops:
        print(f"auto-commit: note - {', '.join(ops)} in progress")
    print(f"auto-commit: recover with  git checkout {ref} -- <path>")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Never block session exit.
        print(f"auto-commit error: {e}", file=sys.stderr)
    sys.exit(0)
