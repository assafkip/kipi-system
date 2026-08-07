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
    take the other's work: nothing is staged, moved, or committed away from it.
    Note carefully what this does NOT say. A Stop hook cannot attribute a dirty
    path to a session, so each ref is a snapshot of the WHOLE checkout and does
    contain the other session's in-flight edits. The safety property is that
    nothing is taken, not that the ref is session-scoped -- an operator who
    believes the latter will cherry-pick a stranger's half-finished work onto
    their branch, which is the 2026-08-02 damage rebuilt by hand. Every message
    this hook prints says which of the two it means.
  - Nothing is lost: a ref is a real ref, so gc will not prune it, and recovery
    is `git cherry-pick` or `git checkout <ref> -- <path>`. The session ref
    always holds the LATEST snapshot by build time; a turn that finishes with an
    older tree goes to `<ref>-superseded` instead, so recovery reads the newest
    work by default and the older tree is still there to go find. Every message
    this hook prints names the ref it actually wrote.

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
import time

PROJ_DIR = os.environ.get("CLAUDE_PROJECT_DIR", ".")

WIP_NAMESPACE = "refs/kipi/wip"

# Every snapshot commit carries the time its CONTENT was read, as a trailer.
# Commit date cannot stand in for it: the stale run commits LAST, precisely
# because it retried after losing the race. See land_snapshot.
BUILT_TRAILER = "kipi-wip-built"

# Where a snapshot goes when a newer one already holds the session ref. A
# sibling ref name, not a subpath: refs/kipi/wip/<s> and refs/kipi/wip/<s>/old
# cannot coexist (git's directory/file conflict), <s>-superseded can.
SUPERSEDED_SUFFIX = "-superseded"

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
    """All uncommitted paths, split into (snapshotted, skipped).

    Skipped paths are RETURNED rather than dropped. A hook that prints only
    "snapshotted N files" reads as "everything dirty is safe", and the one
    2026-08-02 loss that no WIP ref could have recovered was a working-tree-only
    edit nobody knew was still uncommitted. Naming what was left behind is the
    cheap half of that fix.
    """
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

    kept, skipped = [], []
    for f in sorted(files):
        if not f:
            continue
        (skipped if f.startswith(SKIP_PREFIXES) else kept).append(f)
    return kept, skipped


def report_left_behind(skipped, refused=()):
    """Name every dirty path the snapshot does NOT contain, and say why.

    Two reasons, kept apart on purpose. `skipped` is policy (SKIP_PREFIXES) and
    is expected. `refused` is git declining a path this hook had already
    enumerated -- a rename or delete landing between `ls-files` and `git add`,
    or a file it cannot read. That one is a surprise, and surprises are exactly
    what an unattended writer must not swallow.
    """
    if skipped:
        print(f"auto-commit: {len(skipped)} path(s) left dirty, not snapshotted"
              " (skipped by policy):")
        for f in skipped[:20]:
            print(f"auto-commit:   {f}")
        if len(skipped) > 20:
            print(f"auto-commit:   ... and {len(skipped) - 20} more")
    if refused:
        print(f"auto-commit: {len(refused)} path(s) left dirty, NOT snapshotted"
              " (git refused to index them):")
        for f, why in refused[:20]:
            print(f"auto-commit:   {f}  <- {why}")
        if len(refused) > 20:
            print(f"auto-commit:   ... and {len(refused) - 20} more")


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

    Returns (tree, staged, refused). `staged` is what git ACTUALLY indexed, not
    what was enumerated. Those two lists differ whenever a path is renamed or
    deleted between `ls-files` and `git add`, or cannot be read -- and reporting
    the enumerated count as if it were the staged count is the "snapshotted N
    files" lie that test 8 exists to prevent, one box smaller. A count nobody
    can trust is worse than no count, because it stops the reader from looking.
    """
    fd, tmp_index = tempfile.mkstemp(prefix="kipi-wip-index-")
    os.close(fd)
    os.unlink(tmp_index)  # git wants to create it itself
    env = dict(os.environ, GIT_INDEX_FILE=tmp_index)
    staged, refused = [], []
    try:
        # Seed from HEAD so the snapshot is a full tree, not just the dirty set.
        if run(["git", "read-tree", "HEAD"], env=env).returncode != 0:
            run(["git", "read-tree", "--empty"], env=env)

        # Chunked: a large dirty set can blow the argv limit, and a snapshot
        # that silently truncates is worse than no snapshot.
        for i in range(0, len(files), 400):
            chunk = files[i:i + 400]
            r = run(["git", "add", "--"] + chunk, env=env)
            if r.returncode == 0:
                staged.extend(chunk)
                continue
            # git add is all-or-nothing per invocation: one bad path stages
            # NOTHING from the chunk. So retry one at a time and record each
            # verdict, rather than assuming the retry saved everything.
            for f in chunk:
                r1 = run(["git", "add", "--", f], env=env)
                if r1.returncode == 0:
                    staged.append(f)
                else:
                    why = (r1.stderr.strip().splitlines() or ["git add failed"])[0]
                    refused.append((f, why[:120]))

        return git_ok(["git", "write-tree"], env=env), staged, refused
    finally:
        if os.path.exists(tmp_index):
            os.unlink(tmp_index)


# Matches the 3-attempt cap in .claude/rules/self-healing-retry.md. Bounded on
# purpose: a Stop hook that spins on a contended ref delays session exit, and
# the fallback (say what was dropped, loudly) is safe.
MAX_LAND_ATTEMPTS = 3


def read_built_at(rev):
    """The BUILT_TRAILER stamp on `rev`, or None if it carries none.

    None means "cannot be ordered against", not "old". Refs written before this
    trailer existed, and the HEAD commit used as a first parent, both land here;
    treating them as newer would strand a session on the superseded lane forever.
    """
    body = git_ok(["git", "log", "-1", "--format=%B", rev])
    if not body:
        return None
    stamp = None
    for line in body.splitlines():
        line = line.strip()
        if line.startswith(BUILT_TRAILER + ":"):
            try:
                stamp = int(line.split(":", 1)[1].strip())
            except ValueError:
                continue
    return stamp


def try_land(ref, tree, message, parent, prev):
    """commit-tree + ONE compare-and-swap. Returns (commit, error)."""
    args = ["git", "commit-tree", tree]
    if parent:
        args += ["-p", parent]
    args += ["-m", message]
    commit = git_ok(args)
    if not commit:
        return None, "commit-tree failed"
    # Empty oldvalue asserts the ref does not yet exist.
    r = run(["git", "update-ref", ref, commit, prev if prev else ""])
    if r.returncode == 0:
        return commit, None
    return None, r.stderr.strip()[:100]


def land_superseded(ref, tree, message, winner):
    """Keep an already-superseded tree reachable, off the recovery tip.

    Returns (status, commit, where). Chained on the lane's own tip so several
    superseded turns accumulate instead of overwriting each other, and parented
    on the winner the first time so the lane's history contains the tip's.
    """
    lane = ref + SUPERSEDED_SUFFIX
    last_err = "unknown"
    for _ in range(MAX_LAND_ATTEMPTS):
        prev = git_ok(["git", "rev-parse", "--verify", "--quiet", lane])
        parent = prev or winner
        if parent and git_ok(["git", "rev-parse", f"{parent}^{{tree}}"]) == tree:
            return "unchanged", None, lane
        commit, err = try_land(lane, tree, message, parent, prev)
        if commit:
            return "superseded", commit, lane
        last_err = err
    return (f"superseded snapshot lost {MAX_LAND_ATTEMPTS} races ({last_err}); "
            "NOTHING was snapshotted this turn"), None, lane


def land_snapshot(ref, tree, message, built_at):
    """Point `ref` at a new commit holding `tree`. Returns (status, commit, where).

    Status is "landed", "superseded", "unchanged", or a human-readable failure.

    The update is a compare-and-swap, so a second hook for the same session --
    turn N still running when turn N+1 fires -- cannot clobber. But losing the
    swap must not mean losing the snapshot, because the loser can be the run
    holding the FRESHER tree (Codex, PR #83 round 1). So on refusal we re-read
    the ref, RE-PARENT on whatever landed, and try again.

    Re-parenting alone then has the mirror bug (Codex, PR #83 round 3): the
    loser can equally be the STALER run, and re-parenting makes its older tree
    the ref TIP. The tip is what this hook's own recovery line reads --
    `git checkout <ref> -- <path>` -- so a crash recovery would hand back turn
    N's content and silently drop turn N+1's edits. That is the 2026-08-02
    damage class (work restored from the wrong moment) rebuilt inside its fix.

    So the tip is ordered by BUILT_TRAILER, the time each snapshot's content was
    read. Commit date cannot do this job: the stale run commits last, because it
    retried. A snapshot older than what already holds the ref goes to the
    superseded lane instead -- reachable, gc-safe, named in the output, and not
    the thing a recovery reads first. Two runs whose builds truly OVERLAP are
    genuinely ambiguous; the stamp then reflects who started reading last, which
    is the best an unattended writer can know.
    """
    head = git_ok(["git", "rev-parse", "--verify", "--quiet", "HEAD"])
    last_err = "unknown"
    for _ in range(MAX_LAND_ATTEMPTS):
        prev = git_ok(["git", "rev-parse", "--verify", "--quiet", ref])
        parent = prev or head

        # A Stop hook fires every turn. Without this the ref grows an identical
        # commit per turn and the useful history is buried in noise. Re-checked
        # each attempt: the run that beat us may have written our exact tree.
        if parent and git_ok(["git", "rev-parse", f"{parent}^{{tree}}"]) == tree:
            return "unchanged", None, ref

        # Checked every attempt, not only after a refusal: a slow run can find a
        # newer snapshot already on the ref and clobber the tip on its FIRST
        # try, with no race to lose.
        if prev:
            theirs = read_built_at(prev)
            if theirs is not None and theirs >= built_at:
                return land_superseded(
                    ref,
                    tree,
                    message + f"\nSUPERSEDED by {prev[:8]}, a newer snapshot of "
                              f"this session. Older tree, kept for recovery.\n",
                    prev,
                )

        commit, err = try_land(ref, tree, message, parent, prev)
        if commit:
            return "landed", commit, ref
        last_err = err

    return (f"ref update lost {MAX_LAND_ATTEMPTS} races ({last_err}); "
            "NOTHING was snapshotted this turn"), None, ref


def main():
    if run(["git", "rev-parse", "--is-inside-work-tree"]).returncode != 0:
        return

    if disabled():
        print("auto-commit: disabled via KIPI_AUTOCOMMIT")
        return

    session_id = read_session_id()

    files, skipped = get_changed_files()
    if not files:
        print("auto-commit: no changes")
        report_left_behind(skipped)
        return

    # Stamped BEFORE the tree is built: this is when the content was read, and
    # it is what orders two overlapping runs. See land_snapshot.
    built_at = time.time_ns()
    tree, staged, refused = build_tree(files)
    if not tree:
        print("auto-commit: could not write tree, nothing snapshotted")
        report_left_behind(skipped, refused)
        return

    head = git_ok(["git", "rev-parse", "--verify", "--quiet", "HEAD"])
    git_dir = git_ok(["git", "rev-parse", "--absolute-git-dir"]) or ".git"
    branch = git_ok(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or "(detached)"
    ops = in_progress_ops(git_dir)

    # Counts are of what git INDEXED. `files` is what was enumerated, and the
    # two differ exactly when something moved underneath us.
    n = len(staged)
    subject = f"wip: checkout snapshot on {branch} ({n} file{'' if n == 1 else 's'})"
    body = [
        "",
        "Unattended Stop-hook snapshot. NOT a commit on any branch -- it exists",
        "only on the ref below so nothing is lost if this session dies.",
        "",
        "Scope: every dirty path in this checkout, not only this session's work.",
        "A Stop hook cannot tell whose edit is whose, so a parallel session's",
        "in-flight files are in here too. Take paths, not the whole commit.",
        "",
        f"session: {session_id}",
        f"branch:  {branch}",
        f"head:    {head or '(none)'}",
        f"{BUILT_TRAILER}: {built_at}",
    ]
    if ops:
        body.append(f"WARNING: {', '.join(ops)} in progress -- tree may contain")
        body.append("conflict markers. Inspect before reusing this snapshot.")
    if refused:
        body.append("")
        body.append(f"NOT in this snapshot ({len(refused)} path(s) git refused):")
        body += [f"! {f}" for f, _ in refused[:40]]
    body.append("")
    body += [f"- {f}" for f in staged[:40]]
    if n > 40:
        body.append(f"- ... and {n - 40} more")

    ref = f"{WIP_NAMESPACE}/{session_id}"
    status, commit, where = land_snapshot(
        ref, tree, subject + "\n" + "\n".join(body), built_at
    )

    if status == "unchanged":
        print("auto-commit: no change since last snapshot")
    elif status in ("landed", "superseded"):
        print(f"auto-commit: snapshotted {n} file{'' if n == 1 else 's'} "
              f"-> {where} ({commit[:8]})")
        print("auto-commit: scope - every dirty path in this checkout, "
              "not only this session's work")
        if status == "superseded":
            # Say WHY it is not on the session ref. An operator who only sees
            # "snapshotted" will read the tip and believe it is this turn's.
            print(f"auto-commit: a newer snapshot already holds {ref}, so this "
                  f"older tree went to {where} and is NOT the recovery tip")
        if ops:
            print(f"auto-commit: note - {', '.join(ops)} in progress")
        print(f"auto-commit: recover with  git checkout {where} -- <path>")
    else:
        print(f"auto-commit: {status}")

    report_left_behind(skipped, refused)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Never block session exit.
        print(f"auto-commit error: {e}", file=sys.stderr)
    sys.exit(0)
