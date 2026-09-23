#!/usr/bin/env python3
"""The auto-commit Stop hook refuses to cement a mass deletion (ASK-1515).

THE REAL CASE, reproduced here by shape. 2026-09-10 14:44, an instance checkout:
the working tree was overwritten with an older snapshot without HEAD moving, and
the next turn end committed it as eleven unattended commits in two seconds. The
line counts below are that event's numstat, file for file (commits
`content: update canonical files (9 file(s), +4/-581)` and
`content: update project state (13 file(s), +441/-1701)`). Names are scrubbed to
`q-inst/` because this repo is public; the before/after counts are the real ones.

`AUTO_COMMIT_HOOK_UNDER_TEST` points the suite at another copy of the hook, so the
same tests can be run against the pre-fix file and watched going red.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

HOOK = os.environ.get("AUTO_COMMIT_HOOK_UNDER_TEST") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))), "q-system", "hooks", "auto-commit.py")

# (path, lines before, lines added, lines deleted): the 09-10 numstat.
REAL_ROLLBACK = [
    ("q-inst/canonical/content-intelligence.md", 205, 1, 1),
    ("q-inst/canonical/decisions.md", 249, 3, 24),
    ("q-inst/canonical/market-intelligence.md", 220, 0, 22),
    ("q-inst/canonical/objections.md", 123, 0, 54),
    ("q-inst/canonical/positioning-evolution.md", 304, 0, 33),
    ("q-inst/canonical/post-jobs.md", 271, 0, 28),
    ("q-inst/canonical/social-writing-method.md", 591, 0, 307),
    ("q-inst/canonical/talk-tracks.md", 135, 0, 61),
    ("q-inst/canonical/the-business.md", 217, 0, 51),
    ("q-inst/my-project/crm-working.md", 815, 5, 494),
    ("q-inst/my-project/icp-working.md", 4211, 1, 177),
]
APPEND_ONLY = ["q-inst/canonical/decisions.md",
               "q-inst/my-project/crm-working.md",
               "q-inst/my-project/icp-working.md"]
# What the guard must name: the three append-only logs, and the canonical files
# that lost at least 20% (44%, 52%, 45%, 24%).
MUST_REFUSE = set(APPEND_ONLY) | {
    "q-inst/canonical/objections.md", "q-inst/canonical/social-writing-method.md",
    "q-inst/canonical/talk-tracks.md", "q-inst/canonical/the-business.md"}
# Lost 10-11%: under the fraction, so NOT named. If these show up, the threshold
# is not what decides and the guard would refuse ordinary edits.
BELOW_FRACTION = {"q-inst/canonical/market-intelligence.md",
                  "q-inst/canonical/positioning-evolution.md",
                  "q-inst/canonical/post-jobs.md"}


def _body(n, tag="entry"):
    return "".join(f"{tag} {i}\n" for i in range(n))


def _shaped(before, adds, dels):
    kept = [f"entry {i}\n" for i in range(before - dels)]
    return "".join(kept) + _body(adds, "new")


def _repo(tmp_path, append_only=True, files=REAL_ROLLBACK):
    d = tmp_path / "repo"
    d.mkdir()

    def run(*a):
        return subprocess.run(a, cwd=d, capture_output=True, text=True)

    run("git", "init", "-q")
    run("git", "config", "user.email", "t@t.t")
    run("git", "config", "user.name", "t")
    for rel, before, _a, _d in files:
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_body(before))
    if append_only:
        cfg = d / ".kipi" / "append-only.txt"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("# instance-supplied\n" + "".join(p + "\n" for p in APPEND_ONLY))
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "seed")
    return d, run


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


def _fire(root):
    return subprocess.run([sys.executable, HOOK], capture_output=True, text=True,
                          cwd=root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))


def _head(run):
    return run("git", "rev-parse", "HEAD").stdout.strip()


def _pages(log):
    return log.read_text().splitlines() if log.exists() else []


def _apply(root, files=REAL_ROLLBACK):
    for rel, before, adds, dels in files:
        (root / rel).write_text(_shaped(before, adds, dels))


def test_the_real_rollback_commits_nothing(tmp_path, pager):
    root, run = _repo(tmp_path)
    head = _head(run)
    _apply(root)
    out = _fire(root)
    assert _head(run) == head, (
        "the 09-10 rollback shape was committed:\n"
        + run("git", "log", "--oneline", "-15").stdout)
    assert "REFUSED" in out.stdout, out.stdout


def test_it_names_exactly_the_files_that_tripped(tmp_path, pager):
    root, run = _repo(tmp_path)
    _apply(root)
    out = _fire(root).stdout
    named = {ln.strip()[2:].split(":", 1)[0] for ln in out.splitlines()
             if ln.strip().startswith("- ")}
    assert MUST_REFUSE <= named, f"missing {MUST_REFUSE - named}"
    assert not (BELOW_FRACTION & named), f"below-fraction files named: {BELOW_FRACTION & named}"


def test_nothing_is_left_staged_and_the_files_are_untouched(tmp_path, pager):
    """Staging then refusing would hand the shrunk file to the next bare commit."""
    root, run = _repo(tmp_path)
    _apply(root)
    _fire(root)
    assert run("git", "diff", "--cached", "--name-only").stdout.strip() == ""
    for rel, before, adds, dels in REAL_ROLLBACK:
        assert (root / rel).read_text() == _shaped(before, adds, dels), rel


def test_it_pages_once_per_event_not_once_per_turn(tmp_path, pager):
    root, run = _repo(tmp_path)
    _apply(root)
    _fire(root)
    assert len(_pages(pager)) == 1, _pages(pager)
    assert "REFUSED" in _pages(pager)[0]
    second = _fire(root)
    assert "REFUSED" in second.stdout, "the refusal must still print every turn"
    assert len(_pages(pager)) == 1, "a standing refusal re-paged on the next turn end"


def test_the_refusal_reaches_stderr_too(tmp_path, pager):
    root, _run = _repo(tmp_path)
    _apply(root)
    assert "REFUSED" in _fire(root).stderr


def test_an_append_to_every_log_still_commits(tmp_path, pager):
    """Negative control: the ordinary shape. Deleting the safety net passes the
    tests above; this one fails it."""
    root, run = _repo(tmp_path)
    head = _head(run)
    for rel in APPEND_ONLY:
        with open(root / rel, "a") as fh:
            fh.write("**2026-09-23 a new entry**\n")
    _fire(root)
    assert _head(run) != head, "an ordinary append was refused"
    assert run("git", "status", "--porcelain").stdout.strip() == ""
    assert _pages(pager) == []


def test_the_start_here_count_edit_is_not_a_loss(tmp_path, pager):
    """A +1/-1 on an append-only file (the index count line) is net zero."""
    root, run = _repo(tmp_path)
    head = _head(run)
    p = root / "q-inst/my-project/icp-working.md"
    lines = p.read_text().splitlines(keepends=True)
    lines[0] = "entry 0 (count updated)\n"
    p.write_text("".join(lines) + "**2026-09-23 appended**\n")
    _fire(root)
    assert _head(run) != head


def test_an_append_only_file_is_refused_below_the_fraction(tmp_path, pager):
    """decisions.md lost 24 of 249 lines (8%): the fraction alone lets it through,
    the instance's list is what stops it."""
    one = [r for r in REAL_ROLLBACK if r[0].endswith("decisions.md")]
    root, run = _repo(tmp_path, files=one)
    head = _head(run)
    _apply(root, one)
    _fire(root)
    assert _head(run) == head


def test_without_the_instance_list_the_same_edit_commits(tmp_path, pager):
    """The list is instance config, not a skeleton constant: no file, no refusal."""
    one = [r for r in REAL_ROLLBACK if r[0].endswith("decisions.md")]
    root, run = _repo(tmp_path, append_only=False, files=one)
    head = _head(run)
    _apply(root, one)
    _fire(root)
    assert _head(run) != head


def test_a_small_canonical_trim_still_commits(tmp_path, pager):
    one = [("q-inst/canonical/talk-tracks.md", 135, 0, 5)]
    root, run = _repo(tmp_path, append_only=False, files=one)
    head = _head(run)
    _apply(root, one)
    _fire(root)
    assert _head(run) != head


def test_a_deleted_canonical_file_is_refused(tmp_path, pager):
    """The 2026-04-13 shape: the hook's old fallback deleted 26 canonical files."""
    one = [("q-inst/canonical/pricing-framework.md", 91, 0, 91)]
    root, run = _repo(tmp_path, append_only=False, files=one)
    head = _head(run)
    (root / one[0][0]).unlink()
    out = _fire(root)
    assert _head(run) == head, "a deleted canonical file was committed"
    assert "pricing-framework.md" in out.stdout


def test_the_skeleton_canonical_dir_is_guarded_too(tmp_path, pager):
    one = [("q-system/canonical/objections.md", 123, 0, 54)]
    root, run = _repo(tmp_path, append_only=False, files=one)
    head = _head(run)
    _apply(root, one)
    _fire(root)
    assert _head(run) == head


def test_unrelated_state_is_not_committed_either_while_refused(tmp_path, pager):
    """Whole-run refusal: in the 09-10 event a per-file refusal would still have
    committed clients.json's -649 and three canonical files at 10-11%."""
    root, run = _repo(tmp_path)
    head = _head(run)
    _apply(root)
    (root / "memory").mkdir(exist_ok=True)
    (root / "memory" / "MEMORY.md").write_text("- note\n")
    _fire(root)
    assert _head(run) == head
