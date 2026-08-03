#!/usr/bin/env python3
"""Pairs with q-system/hooks/auto-commit.py: the unattended committer must never
write to a named branch.

Scar (2026-08-02, ASK-314, RCA rca-unattended-committer-misattribution). The
Stop hook staged whatever was dirty and committed it to whatever branch happened
to be checked out, under the fixed subject `chore: update system infrastructure`:

  - 7383d6c swept finished ASK-122 work onto `sana/ask-294`, an unrelated
    issue's branch. Recovery cost a worktree extraction, a reland, and a revert.
  - 4559194 swept an in-flight ASK-312 fix plus an unrelated config change into
    one generic commit, discarding the message its author was about to write.
  - A session that switched branches mid-run landed its work split across both.

The mechanism was one property: the hook wrote to HEAD. Everything downstream
(misattribution, the generic subject, the cross-session sweep) follows from a
writer with no scope committing at a moment it cannot interpret.

So the assertions here are about the BRANCH, not about the message. A fix that
only improved the subject line would still strand work on the wrong branch.

The durability assertions are load-bearing and deliberately paired with the
refusal assertions. The hook exists so an unattended run does not lose work; a
"fix" that simply stops committing would pass a branch-only test and silently
delete the safety net. Every refusal case below has a matching recovery case
that proves the content is still reachable.

Hermetic: builds its own repo in a temp dir, sets its own identity, and never
touches the real repo, the real index, or the real refs.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Ref hatch: point this at a pre-fix copy of the hook to watch these cases FAIL.
# A regression test that has never been observed red is an assumption.
#   git show <pre-fix-sha>:q-system/hooks/auto-commit.py > /tmp/old.py
#   KIPI_AUTOCOMMIT_HOOK=/tmp/old.py python3 <this file>
HOOK = Path(
    os.environ.get("KIPI_AUTOCOMMIT_HOOK")
    or HERE.parent.parent.parent / "hooks" / "auto-commit.py"
)

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}{(': ' + detail) if detail else ''}")


def git(repo: Path, *args: str, check_rc: bool = True) -> str:
    r = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True
    )
    if check_rc and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def make_repo(tmp: Path, branch: str = "sana/ask-294") -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", branch)
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("baseline\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "baseline (ASK-1)")
    return repo


def run_hook(repo: Path, session_id: str, extra_env: dict | None = None):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    # A real Stop payload carries session_id; the hook must key its ref on it.
    env.pop("KIPI_AUTOCOMMIT", None)
    if extra_env:
        env.update(extra_env)
    payload = json.dumps({"session_id": session_id, "cwd": str(repo)})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=repo,
        input=payload,
        capture_output=True,
        text=True,
        env=env,
    )


def dirty(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def wip_ref(session_id: str) -> str:
    return f"refs/kipi/wip/{session_id}"


# --------------------------------------------------------------------------
# 1. THE REPRODUCER. Dirty a file that belongs to no branch in particular and
#    fire the hook. The checked-out branch must not gain a commit.
#    The path is under q-system/.q-system/ on purpose: that is the exact
#    AREA_MAP entry that produced "chore: update system infrastructure".
# --------------------------------------------------------------------------
def test_named_branch_untouched(tmp: Path) -> None:
    repo = make_repo(tmp)
    before_head = git(repo, "rev-parse", "HEAD")
    before_count = git(repo, "rev-list", "--count", "HEAD")

    dirty(repo, "q-system/.q-system/unrelated.txt", "work from another issue\n")
    r = run_hook(repo, "sess-aaa")

    after_head = git(repo, "rev-parse", "HEAD")
    after_count = git(repo, "rev-list", "--count", "HEAD")

    check(
        "checked-out branch gains no commit",
        after_head == before_head and after_count == before_count,
        f"HEAD {before_head[:8]} -> {after_head[:8]}, "
        f"count {before_count} -> {after_count}; rc={r.returncode}",
    )
    # The generic subject is the fingerprint of the old behaviour. Assert the
    # literal string is absent from the branch, not merely that HEAD moved --
    # a future variant that commits under a BETTER message is still wrong.
    log = git(repo, "log", "--format=%s")
    check(
        "no 'update system infrastructure' commit on the branch",
        "update system infrastructure" not in log,
        log,
    )


# --------------------------------------------------------------------------
# 2. NEGATIVE SELF-TEST. Durability is the whole point of the hook. If the fix
#    merely stopped committing, test 1 would pass and the safety net would be
#    gone. The dirty content must be recoverable from the session's WIP ref.
# --------------------------------------------------------------------------
def test_work_is_recoverable(tmp: Path) -> None:
    repo = make_repo(tmp)
    body = "the reasoning the author was about to write\n"
    dirty(repo, "q-system/.q-system/unrelated.txt", body)
    run_hook(repo, "sess-bbb")

    ref = wip_ref("sess-bbb")
    exists = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        cwd=repo, capture_output=True, text=True,
    ).returncode == 0
    check("session WIP ref created", exists, ref)

    if not exists:
        check("dirty content recoverable from WIP ref", False, "no ref")
        return

    got = subprocess.run(
        ["git", "cat-file", "-p", f"{ref}:q-system/.q-system/unrelated.txt"],
        cwd=repo, capture_output=True, text=True,
    )
    check(
        "dirty content recoverable from WIP ref",
        got.returncode == 0 and got.stdout == body,
        f"rc={got.returncode} out={got.stdout!r}",
    )


# --------------------------------------------------------------------------
# 3. The author keeps their work. The hook must not consume the dirty state --
#    that is what discarded the in-progress message three times.
# --------------------------------------------------------------------------
def test_working_tree_left_dirty(tmp: Path) -> None:
    repo = make_repo(tmp)
    rel = "q-system/.q-system/unrelated.txt"
    body = "still mine\n"
    dirty(repo, rel, body)
    run_hook(repo, "sess-ccc")
    # --untracked-files=all: plain --porcelain collapses a wholly-untracked
    # directory to "?? q-system/", which hid the path and made this assertion
    # read as a production failure when the tree was in fact correctly dirty.
    status = git(repo, "status", "--porcelain", "--untracked-files=all")
    check(
        "path still uncommitted after the hook",
        rel in status,
        f"status={status!r}",
    )
    check(
        "file still on disk with the author's content",
        (repo / rel).exists() and (repo / rel).read_text() == body,
    )
    # The strong form: the author's work must not have reached the branch.
    tracked = git(repo, "ls-tree", "-r", "--name-only", "HEAD")
    check("path absent from the branch tree", rel not in tracked, tracked)


# --------------------------------------------------------------------------
# 4. Two sessions sharing a checkout get two refs. Neither may reach a branch.
#    This is the cross-session sweep (2ba1532) in miniature.
# --------------------------------------------------------------------------
def test_sessions_do_not_collide(tmp: Path) -> None:
    repo = make_repo(tmp)
    before_head = git(repo, "rev-parse", "HEAD")

    dirty(repo, "q-system/.q-system/from-a.txt", "session a\n")
    run_hook(repo, "sess-ddd")
    dirty(repo, "q-system/.q-system/from-b.txt", "session b\n")
    run_hook(repo, "sess-eee")

    check(
        "branch untouched across two sessions",
        git(repo, "rev-parse", "HEAD") == before_head,
    )
    refs = git(repo, "for-each-ref", "--format=%(refname)", "refs/kipi/wip/")
    check(
        "each session gets its own ref",
        wip_ref("sess-ddd") in refs and wip_ref("sess-eee") in refs,
        refs,
    )


# --------------------------------------------------------------------------
# 5. Explicit off-switch. An operator must be able to turn the writer off
#    without editing settings.json mid-session.
# --------------------------------------------------------------------------
def test_off_switch(tmp: Path) -> None:
    repo = make_repo(tmp)
    before_head = git(repo, "rev-parse", "HEAD")
    dirty(repo, "q-system/.q-system/unrelated.txt", "nope\n")
    run_hook(repo, "sess-fff", extra_env={"KIPI_AUTOCOMMIT": "off"})

    check("off-switch: branch untouched", git(repo, "rev-parse", "HEAD") == before_head)
    refs = git(repo, "for-each-ref", "--format=%(refname)", "refs/kipi/wip/")
    check("off-switch: no WIP ref written", refs == "", refs)


# --------------------------------------------------------------------------
# 6. A mid-rebase / mid-merge tree must not be committed to the branch. Under
#    the old design this corrupted the operation in progress; the snapshot is
#    still taken, because that is exactly when losing work hurts most.
# --------------------------------------------------------------------------
def test_operation_in_progress(tmp: Path) -> None:
    repo = make_repo(tmp)
    # Fabricate an in-progress merge marker without actually conflicting.
    (repo / ".git" / "MERGE_HEAD").write_text(git(repo, "rev-parse", "HEAD") + "\n")
    before_head = git(repo, "rev-parse", "HEAD")
    dirty(repo, "q-system/.q-system/unrelated.txt", "mid-merge\n")
    run_hook(repo, "sess-ggg")

    check(
        "mid-merge: branch untouched",
        git(repo, "rev-parse", "HEAD") == before_head,
    )
    exists = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", wip_ref("sess-ggg")],
        cwd=repo, capture_output=True, text=True,
    ).returncode == 0
    check("mid-merge: work still snapshotted", exists)


# --------------------------------------------------------------------------
# 7. Idempotence. A Stop hook fires on every turn; an unchanged tree must not
#    grow the ref forever.
# --------------------------------------------------------------------------
def test_no_duplicate_snapshot(tmp: Path) -> None:
    repo = make_repo(tmp)
    dirty(repo, "q-system/.q-system/unrelated.txt", "once\n")
    run_hook(repo, "sess-hhh")
    first = git(repo, "rev-parse", wip_ref("sess-hhh"))
    run_hook(repo, "sess-hhh")
    second = git(repo, "rev-parse", wip_ref("sess-hhh"))
    check("unchanged tree makes no second snapshot", first == second,
          f"{first[:8]} -> {second[:8]}")


def main() -> int:
    if not HOOK.exists():
        print(f"FAIL: hook not found at {HOOK}")
        return 1
    print(f"testing {HOOK}")
    tests = [
        test_named_branch_untouched,
        test_work_is_recoverable,
        test_working_tree_left_dirty,
        test_sessions_do_not_collide,
        test_off_switch,
        test_operation_in_progress,
        test_no_duplicate_snapshot,
    ]
    for t in tests:
        print(f"\n{t.__name__}")
        with tempfile.TemporaryDirectory() as td:
            try:
                t(Path(td))
            except Exception as e:  # noqa: BLE001
                check(t.__name__, False, f"raised {type(e).__name__}: {e}")
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
