#!/usr/bin/env python3
"""A refused auto-commit leaves the index as it found it, and says why (ASK-2824).

THE REAL CASE. The running consulting checkout, 2026-10-16 to 10-22: the hook ran
`git add` on a group, the pathspec commit was refused, and nothing undid the add.
Ten state files (my-project/*.json, crm-working.md, the handoff, session recall) sat
staged for days and blocked the merge that keeps the checkout on main. The only
trace was `skipped: ... - <stderr[:80]>`, and the first 80 characters of a lefthook
refusal are its banner box. The hook is wired async with `2>/dev/null`, so even
that went nowhere.

The pre-commit hook below plays the refusing gate: a banner wider than 80
characters, then the real reason, then exit 1, the shape lefthook prints.

`AUTO_COMMIT_HOOK_UNDER_TEST` points the suite at another copy of the hook, so the
same tests run against the pre-fix file and are seen going red.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest

HOOK = os.environ.get("AUTO_COMMIT_HOOK_UNDER_TEST") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))), "q-system", "hooks", "auto-commit.py")

BANNER = "+" + "-" * 100 + "+"
REASON = "BLOCK: gate-x refused this commit"
REFUSING_HOOK = f'#!/bin/sh\necho "{BANNER}" >&2\necho "{REASON}" >&2\nexit 1\n'


@pytest.fixture
def pager(tmp_path, monkeypatch):
    """A stub pager and an isolated marker cache. No test reaches a live alert."""
    log = tmp_path / "pages.log"
    stub = tmp_path / "notify.sh"
    stub.write_text(f'#!/bin/bash\nprintf "%s\\n" "$1" >> "{log}"\n')
    stub.chmod(0o755)
    monkeypatch.setenv("KIPI_AUTOCOMMIT_NOTIFY", str(stub))
    monkeypatch.setenv("KIPI_CACHE_HOME", str(tmp_path / "cache"))
    return log


def _repo(tmp_path):
    d = tmp_path / "repo"
    (d / "memory").mkdir(parents=True)

    def run(*a, **kw):
        return subprocess.run(a, cwd=d, capture_output=True, text=True, **kw)

    run("git", "init", "-q")
    run("git", "config", "user.email", "t@t.t")
    run("git", "config", "user.name", "t")
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    # Explicit, so a machine-wide core.hooksPath cannot swap in other hooks.
    run("git", "config", "core.hooksPath", str(hooks))
    (d / "memory" / "MEMORY.md").write_text("- note\n")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "seed")
    return d, run, hooks


def _gate(hooks, body=REFUSING_HOOK):
    p = hooks / "pre-commit"
    p.write_text(body)
    p.chmod(0o755)


def _fire(root, *args):
    return subprocess.run([sys.executable, HOOK, *args], capture_output=True,
                          text=True, cwd=root,
                          env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))


def _staged(run):
    return run("git", "diff", "--cached", "--name-only").stdout.split()


def _pages(log):
    return log.read_text().splitlines() if log.exists() else []


def _commit_log(root):
    p = root / ".git" / "kipi-auto-commit.log"
    return p.read_text() if p.exists() else ""


def test_a_refused_commit_leaves_nothing_staged(tmp_path, pager):
    """THE case: the old hook left the group staged after the refusal."""
    root, run, hooks = _repo(tmp_path)
    _gate(hooks)
    head = run("git", "rev-parse", "HEAD").stdout
    (root / "memory" / "MEMORY.md").write_text("- note\n- new note\n")
    _fire(root)
    assert run("git", "rev-parse", "HEAD").stdout == head, "the refusing gate let it in"
    assert _staged(run) == [], f"a refused group was left staged: {_staged(run)}"
    assert (root / "memory" / "MEMORY.md").read_text().endswith("- new note\n"), \
        "the file on disk must be untouched"


def test_a_new_file_is_not_left_added(tmp_path, pager):
    """deal-ai.json's shape: a new state file sat as `A` in the index for hours."""
    root, run, hooks = _repo(tmp_path)
    _gate(hooks)
    (root / "memory" / "fresh.md").write_text("new\n")
    _fire(root)
    assert _staged(run) == []
    assert "memory/fresh.md" in run("git", "ls-files", "--others").stdout


def test_another_writers_staged_blob_survives_a_refusal(tmp_path, pager):
    """Undo means back to what was there, not back to HEAD.

    git cannot say who staged a path. A reset to HEAD would drop a blob another
    writer staged before this run, and that blob may exist nowhere else."""
    root, run, hooks = _repo(tmp_path)
    _gate(hooks)
    (root / "memory" / "MEMORY.md").write_text("- staged by someone else\n")
    run("git", "add", "memory/MEMORY.md")
    theirs = run("git", "ls-files", "-s", "memory/MEMORY.md").stdout
    (root / "memory" / "MEMORY.md").write_text("- edited again on disk\n")
    _fire(root)
    assert run("git", "ls-files", "-s", "memory/MEMORY.md").stdout == theirs


def test_the_log_carries_the_reason_the_banner_hid(tmp_path, pager):
    """`stderr[:80]` was all banner. The reason must reach a file a human can read."""
    root, run, hooks = _repo(tmp_path)
    _gate(hooks)
    (root / "memory" / "MEMORY.md").write_text("- changed\n")
    out = _fire(root)
    assert REASON in _commit_log(root), (
        f"the refusal reason is not in the log\nstdout={out.stdout!r}")
    assert REASON in out.stdout, "the stdout line must name the reason, not the banner"


def test_it_pages_once_per_event_and_again_after_a_clean_turn(tmp_path, pager):
    root, run, hooks = _repo(tmp_path)
    _gate(hooks)
    (root / "memory" / "MEMORY.md").write_text("- one\n")
    _fire(root)
    _fire(root)
    assert len(_pages(pager)) == 1, f"a standing refusal re-paged: {_pages(pager)}"
    assert REASON in _pages(pager)[0]
    _gate(hooks, "#!/bin/sh\nexit 0\n")
    _fire(root)                                   # commits: the event ends
    assert _staged(run) == []
    _gate(hooks)
    (root / "memory" / "MEMORY.md").write_text("- two\n")
    _fire(root)
    assert len(_pages(pager)) == 2, f"the second event paged nobody: {_pages(pager)}"


def test_a_lock_collision_is_logged_and_unstaged_but_not_paged(tmp_path, pager):
    """Two turn ends racing for index.lock is the another_commit_in_flight case:
    the next turn retries. Paging each race is the report_skipped flood."""
    root, run, hooks = _repo(tmp_path)
    _gate(hooks, "#!/bin/sh\necho \"fatal: Unable to create '/r/.git/index.lock': "
                 "File exists.\" >&2\nexit 128\n")
    (root / "memory" / "MEMORY.md").write_text("- raced\n")
    _fire(root)
    assert _staged(run) == []
    assert "index.lock" in _commit_log(root)
    assert _pages(pager) == []


def test_a_lost_lock_race_on_add_reports_the_index_truthfully(tmp_path, pager):
    """PR #547 review, finding 1: `git add` refused on a held index.lock stages
    nothing, yet the hook said the files were still staged and paged, because its
    restore then lost the same lock. The lock is held for the whole run here."""
    root, run, hooks = _repo(tmp_path)
    (root / "memory" / "MEMORY.md").write_text("- raced\n")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    code = ("import importlib.util, sys\n"
            f"spec = importlib.util.spec_from_file_location('ac', {HOOK!r})\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "open('.git/index.lock', 'w').close()\n"   # held from here to exit
            "m.commit_group('chore', 'update session memory', ['memory/MEMORY.md'])\n")
    out = subprocess.run([sys.executable, "-c", code], cwd=root, env=env,
                         capture_output=True, text=True)
    (root / ".git" / "index.lock").unlink()
    assert _staged(run) == []
    assert "still staged" not in out.stdout, out.stdout
    assert _pages(pager) == [], _pages(pager)


def test_a_non_ascii_path_is_committed_not_refused(tmp_path, pager):
    """PR #547 review, finding 3: git C-quotes such a path without -z, and the
    quoted string matches no pathspec, so the file was never committable."""
    root, run, hooks = _repo(tmp_path)
    (root / "memory" / "café notes.md").write_text("x\n")
    _fire(root)
    assert "memory/café notes.md" in run(
        "git", "-c", "core.quotePath=false", "ls-files").stdout
    assert _pages(pager) == []


def test_the_shipped_invocation_writes_its_refusals_to_the_log(tmp_path, pager):
    """PR #547 review, finding 2. The wiring passes --detach, so the worker's
    stdout, the hook's only readable channel, is the log. Fired the shipped way."""
    root, run, hooks = _repo(tmp_path)
    (root / "memory" / "MEMORY.md").write_text("- waits\n")
    lock = root / ".git" / "index.lock"
    lock.write_text("held")
    try:
        parent = _fire(root, "--detach")
        deadline = time.time() + 20
        while time.time() < deadline and "another commit is in flight" \
                not in _commit_log(root):
            time.sleep(0.2)
    finally:
        lock.unlink()
    assert "kipi-auto-commit.log" in parent.stdout, parent.stdout
    assert "another commit is in flight" in _commit_log(root)


def test_a_clean_commit_pages_nobody_and_logs_nothing(tmp_path, pager):
    root, run, hooks = _repo(tmp_path)
    (root / "memory" / "MEMORY.md").write_text("- fine\n")
    _fire(root)
    assert "fine" in run("git", "show", "HEAD:memory/MEMORY.md").stdout
    assert _pages(pager) == []
    assert "REFUSED" not in _commit_log(root)


def test_a_session_exit_does_not_leave_the_group_staged(tmp_path, pager):
    """Measured under Claude Code 2.1.307: a one-shot session SIGTERMs its async
    Stop hook as it exits and SIGKILLs it about 2s later. Replayed here on the
    hook's process group, while the pre-commit is still running."""
    root, run, hooks = _repo(tmp_path)
    _gate(hooks, "#!/bin/sh\nsleep 2\nexit 0\n")
    (root / "memory" / "MEMORY.md").write_text("- written just before exit\n")
    p = subprocess.Popen([sys.executable, HOOK, "--detach"], cwd=root,
                         env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)   # its own group, so pytest survives
    time.sleep(1.0)                                 # inside the 2s pre-commit
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(p.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass    # macOS answers EPERM for a group whose only member is a zombie
        time.sleep(0.3)
    p.wait(timeout=10)
    deadline = time.time() + 20
    while time.time() < deadline:
        landed = "written just before exit" in run(
            "git", "show", "HEAD:memory/MEMORY.md").stdout
        if landed and not (root / ".git" / "index.lock").exists():
            break
        time.sleep(0.2)
    assert landed, "the session exit killed the commit"
    assert _staged(run) == [], f"left staged: {_staged(run)}"
