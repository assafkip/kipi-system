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
import shutil
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


# --------------------------------------------------------------------------
# 8. Skipped paths are NAMED, not silently dropped. SKIP_PREFIXES leaves some
#    dirty paths out of the snapshot; an operator reading only "snapshotted N
#    files" would believe everything dirty was safe. The one loss on
#    2026-08-02 that no ref would have recovered was a working-tree-only edit
#    nobody knew was still uncommitted, so silence about what was left behind
#    is the same failure mode in a smaller box.
# --------------------------------------------------------------------------
def test_skipped_paths_are_reported(tmp: Path) -> None:
    repo = make_repo(tmp)
    dirty(repo, "q-system/.q-system/kept.txt", "snapshotted\n")
    dirty(repo, "q-system/output/left-behind.txt", "not snapshotted\n")
    r = run_hook(repo, "sess-iii")
    out = r.stdout + r.stderr

    check(
        "skipped path is named in the hook's output",
        "q-system/output/left-behind.txt" in out,
        out.strip(),
    )
    # It must be reported as LEFT DIRTY, not blurred into the snapshot count.
    check(
        "skipped paths are labelled as not snapshotted",
        "not snapshotted" in out.lower() or "left dirty" in out.lower(),
        out.strip(),
    )
    # And the skip must still be a real skip: naming it is not the same as
    # quietly starting to include it.
    got = subprocess.run(
        ["git", "cat-file", "-p",
         f"{wip_ref('sess-iii')}:q-system/output/left-behind.txt"],
        cwd=repo, capture_output=True, text=True,
    )
    check("skipped path is genuinely absent from the snapshot",
          got.returncode != 0, got.stdout)


# --------------------------------------------------------------------------
# 9. A path the hook ENUMERATED but could not STAGE must not be counted as
#    snapshotted. (Codex PR #83, major.) `git add` can refuse a path that
#    `ls-files`/`diff` happily listed a moment earlier -- the real case is a
#    rename or delete landing between the two calls. The hook retries such a
#    chunk one path at a time and then prints `len(files)`, which is the
#    enumerated count, not the staged count.
#
#    That is the SAME failure as test 8 in a smaller box: an operator reading
#    "snapshotted 7 files" believes 7 files are safe. Here one of them is not
#    in the tree at all, and nothing said so.
#
#    Reproduced hermetically with a mode-000 untracked file: git lists it in
#    `ls-files --others` (stat is enough) and then refuses it with
#    "unable to index file" (open is not). Verified against real git before
#    being relied on -- see the probe output in the ASK-314 thread. Same
#    enumerated-then-unstageable shape as the rename, without a race.
# --------------------------------------------------------------------------
def test_unstageable_path_is_not_counted(tmp: Path) -> None:
    repo = make_repo(tmp)
    dirty(repo, "q-system/.q-system/staged-fine.txt", "this one really is safe\n")
    bad = repo / "q-system" / ".q-system" / "unstageable.txt"
    dirty(repo, "q-system/.q-system/unstageable.txt", "cannot be indexed\n")
    os.chmod(bad, 0o000)
    try:
        r = run_hook(repo, "sess-jjj")
        out = r.stdout + r.stderr

        ref = wip_ref("sess-jjj")
        in_tree = subprocess.run(
            ["git", "cat-file", "-p", f"{ref}:q-system/.q-system/unstageable.txt"],
            cwd=repo, capture_output=True, text=True,
        ).returncode == 0
        # Precondition for the finding: git really did refuse it.
        check(
            "unstageable path is genuinely absent from the snapshot",
            not in_tree,
            "git staged it after all; reproducer no longer reproduces",
        )
        # The finding itself: the hook must not report it as snapshotted.
        check(
            "unstageable path is named as NOT snapshotted",
            "q-system/.q-system/unstageable.txt" in out
            and ("not snapshotted" in out.lower() or "left dirty" in out.lower()),
            out.strip(),
        )
        # And the count must be the staged count, not the enumerated one.
        check(
            "snapshot count excludes the path git refused",
            "snapshotted 1 file" in out,
            out.strip(),
        )
        # The good path must still be there: refusing to lie about one file is
        # not a licence to drop the other.
        good = subprocess.run(
            ["git", "cat-file", "-p", f"{ref}:q-system/.q-system/staged-fine.txt"],
            cwd=repo, capture_output=True, text=True,
        )
        check(
            "the stageable path is still snapshotted",
            good.returncode == 0 and good.stdout == "this one really is safe\n",
            f"rc={good.returncode} out={good.stdout!r}",
        )
    finally:
        os.chmod(bad, 0o644)  # so TemporaryDirectory can clean up


# --------------------------------------------------------------------------
# 10. A LOST compare-and-swap must not lose the snapshot. (Codex PR #83,
#     major.) One session's Stop hook can overlap itself: turn N's hook is
#     still running when turn N+1's fires. Both read the same `prev`, both
#     build a tree, one lands, and the other's update-ref is refused.
#
#     Refusing is correct -- clobbering is what a CAS exists to prevent. What
#     is not correct is giving up: the refused run is usually the one holding
#     the FRESHER tree, so "ref update refused" means the newest work is the
#     work that was dropped. The ref is left stale and the hook says so in a
#     line nobody reads at 3am.
#
#     Deterministic without threads: a `git` shim on PATH advances the ref
#     once, at exactly the moment the hook is between reading `prev` and
#     calling update-ref (it wedges on `commit-tree`). That is the real
#     interleaving, made repeatable.
# --------------------------------------------------------------------------
def _install_racing_git_shim(tmp: Path, repo: Path, ref: str) -> dict:
    """A `git` that lets a competitor land the ref once, mid-hook."""
    real_git = shutil.which("git")
    bindir = tmp / "shim-bin"
    bindir.mkdir()
    marker = tmp / "raced-once"
    shim = bindir / "git"
    shim.write_text(
        "#!/usr/bin/env python3\n"
        "import os, subprocess, sys\n"
        f"REAL = {real_git!r}\n"
        f"MARKER = {str(marker)!r}\n"
        f"REPO = {str(repo)!r}\n"
        f"REF = {ref!r}\n"
        "# Wedge between the hook reading `prev` and the hook calling\n"
        "# update-ref: land a competing value exactly once.\n"
        "if 'commit-tree' in sys.argv and not os.path.exists(MARKER):\n"
        "    open(MARKER, 'w').close()\n"
        "    head = subprocess.run([REAL, 'rev-parse', 'HEAD'], cwd=REPO,\n"
        "                          capture_output=True, text=True).stdout.strip()\n"
        "    subprocess.run([REAL, 'update-ref', REF, head], cwd=REPO,\n"
        "                   capture_output=True, text=True)\n"
        "os.execv(REAL, [REAL] + sys.argv[1:])\n"
    )
    shim.chmod(0o755)
    return {"PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"}


def test_lost_cas_still_lands(tmp: Path) -> None:
    repo = make_repo(tmp)
    before_head = git(repo, "rev-parse", "HEAD")
    ref = wip_ref("sess-kkk")
    body = "the fresher tree, the one that must not be dropped\n"
    dirty(repo, "q-system/.q-system/racy.txt", body)

    r = run_hook(repo, "sess-kkk", extra_env=_install_racing_git_shim(tmp, repo, ref))
    out = r.stdout + r.stderr

    # The competitor really did land first, or this proves nothing.
    check(
        "the shim landed a competing ref update",
        (tmp / "raced-once").exists(),
        "shim never fired; reproducer no longer reproduces",
    )
    # The finding: after losing the race, the hook must re-parent and retry,
    # so its content ends up on the ref rather than in the bin.
    got = subprocess.run(
        ["git", "cat-file", "-p", f"{ref}:q-system/.q-system/racy.txt"],
        cwd=repo, capture_output=True, text=True,
    )
    check(
        "snapshot survives a lost compare-and-swap",
        got.returncode == 0 and got.stdout == body,
        f"rc={got.returncode} out={got.stdout!r} hook-said={out.strip()!r}",
    )
    # Retrying must not become clobbering: the competitor's commit stays
    # reachable from the ref, which is what re-parenting (not force) buys.
    reachable = subprocess.run(
        ["git", "merge-base", "--is-ancestor", before_head, ref],
        cwd=repo, capture_output=True, text=True,
    ).returncode == 0
    check("the competing commit is still reachable from the ref", reachable)
    # And the branch is still untouched, which is the whole point of ASK-314.
    check("racing does not put a commit on the branch",
          git(repo, "rev-parse", "HEAD") == before_head)


# --------------------------------------------------------------------------
# 11. The snapshot spans the WHOLE checkout, and the hook must say so.
#     (Codex PR #83, minor.) The hook's own docstring claimed two sessions
#     sharing a checkout meant "neither can sweep up the other's uncommitted
#     work". Half true, and the false half is the dangerous half: a Stop hook
#     cannot attribute a dirty path to a session, so session B's ref really
#     does contain session A's work.
#
#     What is actually true -- and worth keeping -- is that nothing is TAKEN:
#     A's working tree is untouched and no branch gains a commit. Both halves
#     are asserted here, because an operator who believes the ref is
#     session-scoped will read a `wip` ref as "my work" and cherry-pick a
#     stranger's half-finished edit onto their branch.
# --------------------------------------------------------------------------
def test_snapshot_scope_is_stated_honestly(tmp: Path) -> None:
    repo = make_repo(tmp)
    others = "q-system/.q-system/from-session-a.txt"
    a_body = "session A's in-flight work\n"
    dirty(repo, others, a_body)
    dirty(repo, "q-system/.q-system/from-session-b.txt", "session B's work\n")

    r = run_hook(repo, "sess-lll")  # only B's hook fires
    out = r.stdout + r.stderr

    # The true state of affairs: B's ref DOES carry A's file.
    got = subprocess.run(
        ["git", "cat-file", "-p", f"{wip_ref('sess-lll')}:{others}"],
        cwd=repo, capture_output=True, text=True,
    )
    check(
        "another session's dirty path is inside this session's snapshot",
        got.returncode == 0 and got.stdout == a_body,
        f"rc={got.returncode}",
    )
    # So the hook must not let an operator believe otherwise.
    check(
        "the hook states the snapshot covers the whole checkout",
        "checkout" in out.lower() and "not only this session" in out.lower(),
        out.strip(),
    )
    # The half that IS true, and is the actual safety property: A keeps its work.
    check(
        "the other session's working tree copy is untouched",
        (repo / others).exists() and (repo / others).read_text() == a_body,
    )


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
        test_skipped_paths_are_reported,
        test_unstageable_path_is_not_counted,
        test_lost_cas_still_lands,
        test_snapshot_scope_is_stated_honestly,
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
