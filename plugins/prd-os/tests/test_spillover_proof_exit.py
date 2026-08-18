#!/usr/bin/env python3
"""The fourth exit: a check that FLIPS, not a name in a commit message. sp-1dfc48a8.

## The hole

The third exit (`--resolution-commit`) requires a merged commit whose MESSAGE
names the item id. Three items are fixed at main HEAD and cannot leave the
ledger because that binding was never made at fix time: sp-9066e068 (a1f33b15),
sp-43b11b74 (6ef8278d), sp-cd9ccc16 (b3d95c66). The commit carrying each fix
never named the item, and the commit that names it does not contain the fix --
checked both directions with `merge-base --is-ancestor`.

## Why the two obvious patches were rejected

- An empty or retroactive commit naming the id FABRICATES the proxy and adds no
  evidence. The third exit's real claim is "somebody holding the context bound
  this fix to this item". A commit written today to satisfy a checker is that
  claim with the context removed, and the next reader cannot tell the two apart.
- Loosening `--resolution-commit` to accept any sha whose ANCESTRY contains a
  named fix degrades to `--because-i-said-so`: every sha's ancestry contains
  every older commit.

## What replaces them

A demonstration that stays re-runnable: the command passes against HEAD and
fails against a named pre-fix tree. `{tree}` is substituted and BOTH runs happen
from the main checkout, so the CHECKER is always HEAD's and only the SUBJECT
moves. That is the reproducer-ref-hatch discipline, and it exists because the
check that proves a fix normally shipped WITH the fix -- run with cwd set to the
pre-fix tree it would fail because the file is missing, which is a false
positive wearing a green suit.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
RUNNER = REPO / "plugins" / "prd-os" / "scripts" / "prd_runner.py"
sys.path.insert(0, str(RUNNER.parent))
import prd_runner  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    """A real two-commit repo where a checker genuinely flips.

    Distinct content per commit on purpose: git derives a sha from tree +
    message + timestamp, so two commits made in the same second with the same
    content collide and the 'before' tree silently equals HEAD.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    (root / "subject.txt").write_text("THE DEFECT IS PRESENT\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "before: the defect")
    before = _git(root, "rev-parse", "HEAD").stdout.strip()
    (root / "subject.txt").write_text("THE DEFECT IS FIXED\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "after: the fix")

    prd = root / ".prd-os"
    (prd / "issues").mkdir(parents=True)
    (prd / "config.json").write_text(json.dumps({"version": 1}))
    cfg = prd_runner.load_config(root, strict=False)
    prd_runner._spillover_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    prd_runner._spillover_path(cfg).write_text(json.dumps(
        {"id": "sp-stuck", "status": "open", "severity": "major",
         "description": "fixed at HEAD by a commit that never named it"}) + "\n")
    return cfg, root, before


# The checker lives OUTSIDE both trees and takes the tree as an argument. That is
# the whole shape: one checker, two subjects.
GOOD = "grep -q 'IS FIXED' {tree}/subject.txt"


def test_a_check_that_flips_resolves_the_item(repo):
    """FIRES. Passes at HEAD, fails at the pre-fix tree."""
    cfg, root, before = repo
    ev = prd_runner._verify_resolution_proof(cfg, "sp-stuck", GOOD, before)
    assert ev["resolution_tracker"] == "proof"
    assert ev["resolution_proof_broken_at"] == before
    assert ev["resolution_proof_before_exit"] != 0
    assert ev["resolution_proof_after_exit"] == 0
    assert ev["resolution_proof_command"] == GOOD


def test_a_check_that_passes_at_the_pre_fix_tree_is_refused(repo):
    """REFUSED, and this is the assertion that carries the exit's whole value.

    A command that passes in both trees demonstrates nothing about this item. It
    is the shape a careless operator produces first: `true`, or a check aimed at
    something that was never broken.
    """
    cfg, root, before = repo
    with pytest.raises(prd_runner.CommitRefError, match="ALSO passes"):
        prd_runner._verify_resolution_proof(
            cfg, "sp-stuck", "test -f {tree}/subject.txt", before)


def test_a_check_that_is_red_at_head_is_refused(repo):
    cfg, root, before = repo
    with pytest.raises(prd_runner.CommitRefError, match="does not pass at HEAD"):
        prd_runner._verify_resolution_proof(
            cfg, "sp-stuck", "grep -q 'NOT THERE' {tree}/subject.txt", before)


def test_a_command_without_the_tree_placeholder_is_refused(repo):
    """Without `{tree}` both runs inspect the same code, so the command cannot
    flip and a passing one would resolve every item."""
    cfg, root, before = repo
    with pytest.raises(prd_runner.CommitRefError, match=r"must contain"):
        prd_runner._verify_resolution_proof(cfg, "sp-stuck", "true", before)


def test_broken_at_head_is_refused(repo):
    cfg, root, _ = repo
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    with pytest.raises(prd_runner.CommitRefError, match="nothing for the check to flip"):
        prd_runner._verify_resolution_proof(cfg, "sp-stuck", GOOD, head)


def test_a_failed_worktree_never_falls_back_to_the_main_checkout(repo, monkeypatch):
    """The scar this guards, forced rather than hoped for.

    A failed `git worktree add` that is allowed to fall through grades the
    BEFORE case against FIXED code, sees it pass, and reports that the check did
    not flip -- refusing a genuinely resolvable item, or in the mirror case
    accepting one that was never broken. It must raise, and the message must say
    the worktree is what failed.
    """
    cfg, root, before = repo
    real = prd_runner._git

    def sabotage(cwd, *args):
        if args and args[0] == "worktree" and args[1] == "add":
            return subprocess.CompletedProcess(args, 1, "", "disk full")
        return real(cwd, *args)

    monkeypatch.setattr(prd_runner, "_git", sabotage)
    with pytest.raises(prd_runner.CommitRefError, match="could not create a worktree"):
        prd_runner._verify_resolution_proof(cfg, "sp-stuck", GOOD, before)


def test_the_checker_comes_from_head_even_when_it_did_not_exist_before(repo):
    """THE CASE THE NAIVE DESIGN GETS WRONG.

    The check that proves a fix almost always shipped WITH the fix. Here the
    checker is a file that exists only at HEAD. Run with cwd set to each tree it
    would fail at `before` because the file is missing -- green, and for
    entirely the wrong reason. Run from HEAD against each tree it fails because
    the DEFECT is there, which is the thing being claimed.
    """
    cfg, root, before = repo
    checker = root / "check.sh"
    checker.write_text("#!/bin/sh\ngrep -q 'IS FIXED' \"$1/subject.txt\"\n")
    checker.chmod(0o755)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "the checker itself, added with the fix")
    ev = prd_runner._verify_resolution_proof(
        cfg, "sp-stuck", "sh check.sh {tree}", before)
    assert ev["resolution_proof_before_exit"] != 0
    # The worktree at `before` has no check.sh at all. Proof that the checker was
    # taken from HEAD rather than from the tree being graded.
    assert ev["resolution_proof_after_exit"] == 0


def test_resolve_records_the_proof_through_the_cli(repo):
    """Wiring. An exit nobody can reach from the command line is not an exit."""
    cfg, root, before = repo
    out = subprocess.run(
        [sys.executable, str(RUNNER), "--repo-root", str(root), "spillover",
         "resolve", "sp-stuck", "--resolution-proof", GOOD, "--broken-at", before],
        capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stdout + out.stderr
    rec = prd_runner._read_spillover(cfg)["sp-stuck"]
    assert rec["status"] == "resolved"
    assert rec["resolution_proof_broken_at"] == before
    assert rec["resolution_proof_command"] == GOOD


def test_proof_without_broken_at_is_refused_through_the_cli(repo):
    cfg, root, _ = repo
    out = subprocess.run(
        [sys.executable, str(RUNNER), "--repo-root", str(root), "spillover",
         "resolve", "sp-stuck", "--resolution-proof", GOOD],
        capture_output=True, text=True, timeout=120)
    assert out.returncode == 2
    assert "never been watched fail" in out.stderr
    assert prd_runner._read_spillover(cfg)["sp-stuck"]["status"] == "open"


def test_proof_cannot_be_combined_with_another_exit(repo):
    """EXACTLY one exit. Two would let the weaker one silently win."""
    cfg, root, before = repo
    out = subprocess.run(
        [sys.executable, str(RUNNER), "--repo-root", str(root), "spillover",
         "resolve", "sp-stuck", "--resolution-proof", GOOD,
         "--broken-at", before, "--void", "actually not real"],
        capture_output=True, text=True, timeout=120)
    assert out.returncode == 2
    assert "exactly one exit" in out.stderr


def test_a_broken_at_outside_the_integration_branch_is_refused(repo):
    """The flip must cross THIS repo's history (Codex review PR #213).

    A commit that merely EXISTS -- here, a dangling side branch holding the
    'defective' content -- can host the failing half of any flip. Accepting it
    made the proof exit a hand-clear: pick any unrelated broken tree, watch the
    check fail there, and the item resolves. Ancestry of the integration branch
    is the same rule the commit exit already enforces.
    """
    cfg, root, before = repo
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    _git(root, "checkout", "-q", "-b", "unrelated", before)
    (root / "subject.txt").write_text("THE DEFECT IS PRESENT elsewhere\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "a commit main never merged")
    stray = _git(root, "rev-parse", "HEAD").stdout.strip()
    _git(root, "checkout", "-q", "main")
    assert _git(root, "rev-parse", "HEAD").stdout.strip() == head
    with pytest.raises(prd_runner.CommitRefError, match="not an ancestor"):
        prd_runner._verify_resolution_proof(cfg, "sp-stuck", GOOD, stray)


def test_the_proof_record_names_the_item_it_was_run_for(repo):
    """The stored record binds proof to item, so a proof pasted onto a
    different row is detectable by a later reader (Codex review PR #213)."""
    cfg, root, before = repo
    ev = prd_runner._verify_resolution_proof(cfg, "sp-stuck", GOOD, before)
    assert ev["resolution_proof_item"] == "sp-stuck"


def test_an_unpushed_local_fix_cannot_be_recorded_as_shipped(repo):
    """When an origin exists, the proof measures against ORIGIN's view.

    Local main here is one commit ahead of the simulated origin/main (which
    sits at the pre-fix commit). Certifying that unpushed HEAD as shipped is
    the laundering Codex named on PR #213 round 2.
    """
    cfg, root, before = repo
    _git(root, "update-ref", "refs/remotes/origin/main", before)
    with pytest.raises(prd_runner.CommitRefError, match="has not merged"):
        prd_runner._verify_resolution_proof(cfg, "sp-stuck", GOOD, before)


def test_a_missing_api_key_is_unreachable_not_still_open(monkeypatch):
    """Auth absence means the tracker was never ASKED (Codex PR #213 r2)."""
    monkeypatch.delenv("KIPI_LINEAR_API_KEY", raising=False)
    monkeypatch.setattr(prd_runner.Path, "is_file", lambda self: False)
    with pytest.raises(prd_runner.LinearUnreachableError):
        prd_runner._linear_api_key()
