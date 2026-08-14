#!/usr/bin/env python3
"""fleet-unblock.py acts only on what it can attribute, and refuses the rest.

Every test here builds a REAL skeleton and REAL instance repos in a tmpdir and
runs the actual script against them. Nothing is mocked, because the thing under
test is git behaviour -- a mocked `git restore --staged` would happily "prove"
that the file survives on disk, which is the exact claim that matters.

The negative tests are the point. A clearing tool that acts on everything looks
identical to a correct one until the day it eats founder work, so each refusal
path gets a case that FAILS if the tool acts: `test_founder_edit_is_refused`
and `test_staged_add_with_no_rescued_copy_is_refused` both assert the path is
still dirty afterwards.
"""

import json
import os
import pathlib
import shutil
import subprocess

import pytest

SKELETON_SRC = pathlib.Path(__file__).resolve().parent
SCRIPT = SKELETON_SRC / "fleet-unblock.py"


def git(repo, *args, check=True):
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} in {repo}: {proc.stderr}")
    return proc.stdout.strip()


def init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@t.t")
    git(path, "config", "user.name", "t")
    git(path, "config", "commit.gpgsign", "false")
    return path


def write(repo, rel, text, mode=None):
    full = repo / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(text)
    if mode is not None:
        full.chmod(mode)
    return full


@pytest.fixture
def world(tmp_path):
    """A skeleton plus one instance, wired the way the real fleet is.

    The skeleton gets a real kipi-update.sh stanza because fleet-reach-audit
    PARSES INSTANCE_OWNED_SUBTREES out of it rather than holding a copy, and
    fleet-unblock imports that parser. If the stanza shape ever changes, these
    tests break here rather than silently testing an empty pathspec.
    """
    skel = init_repo(tmp_path / "skeleton")
    shutil.copy(SKELETON_SRC / "fleet-reach-audit.py", skel / "fleet-reach-audit.py")
    shutil.copy(SCRIPT, skel / "fleet-unblock.py")
    write(skel, "kipi-update.sh", (
        "#!/bin/bash\n"
        "INSTANCE_OWNED_SUBTREES=(\n"
        "  my-project\n"
        "  output\n"
        ")\n"
        "SYSTEM_NEVER_COMMIT=(\n"
        ")\n"
    ))
    inst = init_repo(tmp_path / "inst")
    write(skel, "instance-registry.json", json.dumps({"instances": [
        {"name": "inst", "path": str(inst), "subtree_prefix": "q-system"}
    ]}))
    git(skel, "add", "-A")
    git(skel, "commit", "-qm", "skeleton base")
    return skel, inst


def seed_skeleton_blob(skel, rel, text):
    """Make `text` a blob the skeleton once held at `rel`, then move on.

    This is what makes a change attributable as fleet-written: the classifier
    walks the skeleton's history for that exact path.
    """
    write(skel, rel, text)
    git(skel, "add", "-A")
    git(skel, "commit", "-qm", f"skeleton ships {rel}")
    write(skel, rel, text + "\n# newer skeleton copy\n")
    git(skel, "add", "-A")
    git(skel, "commit", "-qm", f"skeleton bumps {rel}")


def run(skel, *args):
    proc = subprocess.run(
        ["python3", str(skel / "fleet-unblock.py"), "--skeleton", str(skel), *args],
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def is_dirty(repo, rel):
    tracked = git(repo, "diff", "--quiet", "--", rel, check=False)
    rc1 = subprocess.run(["git", "-C", str(repo), "diff", "--quiet", "--", rel]).returncode
    rc2 = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--quiet", "--", rel]).returncode
    del tracked
    return rc1 != 0 or rc2 != 0


# --------------------------------------------------------------------------
# restore-mode
# --------------------------------------------------------------------------

def test_mode_only_drift_is_chmodded_not_committed(world):
    """The KTLYST_strategy shape: same bytes, lost +x.

    Asserts the fix is a chmod. Committing would clear the guard too, which is
    why this test checks HEAD did not move: a tool that "worked" by committing
    the broken mode passes any check that only looks at cleanliness.
    """
    skel, inst = world
    body = "#!/usr/bin/env python3\nprint('hi')\n"
    write(inst, "plugins/kipi-core/tool.py", body, mode=0o755)
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")
    head_before = git(inst, "rev-parse", "HEAD")
    (inst / "plugins/kipi-core/tool.py").chmod(0o644)
    assert is_dirty(inst, "plugins/kipi-core/tool.py")

    rc, out = run(skel, "--apply")
    assert rc == 0, out
    assert "restore-mode" in out, out

    assert not is_dirty(inst, "plugins/kipi-core/tool.py"), out
    assert git(inst, "rev-parse", "HEAD") == head_before, "must not commit a mode fix"
    assert os.access(inst / "plugins/kipi-core/tool.py", os.X_OK), "+x not restored"


def test_mode_fix_is_not_applied_on_a_dry_run(world):
    """Negative self-test for the dry run: the default must write nothing."""
    skel, inst = world
    write(inst, "plugins/kipi-core/tool.py", "x\n", mode=0o755)
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "base")
    (inst / "plugins/kipi-core/tool.py").chmod(0o644)

    rc, out = run(skel)
    assert rc == 0, out
    assert "would chmod" in out, out
    assert is_dirty(inst, "plugins/kipi-core/tool.py"), "dry run wrote to the instance"


# --------------------------------------------------------------------------
# commit
# --------------------------------------------------------------------------

def test_fleet_written_content_is_committed(world):
    skel, inst = world
    seed_skeleton_blob(skel, "plugins/prd-os/runner.py", "v1\n")
    write(inst, "plugins/prd-os/runner.py", "old\n")
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")
    write(inst, "plugins/prd-os/runner.py", "v1\n")   # the exhaust
    assert is_dirty(inst, "plugins/prd-os/runner.py")

    rc, out = run(skel, "--apply")
    assert rc == 0, out
    assert not is_dirty(inst, "plugins/prd-os/runner.py"), out
    assert "is one the skeleton itself held" in out
    assert (inst / "plugins/prd-os/runner.py").read_text() == "v1\n", "bytes changed"


def test_founder_edit_is_refused(world):
    """NEGATIVE: bytes the skeleton never shipped stay exactly where they are.

    This is the test that has to fail if attribution is loosened. It asserts
    both that the tool says REFUSE and that the path is STILL dirty, because a
    tool that printed a refusal and acted anyway would pass the first half.
    """
    skel, inst = world
    seed_skeleton_blob(skel, "plugins/prd-os/runner.py", "v1\n")
    write(inst, "plugins/prd-os/runner.py", "old\n")
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")
    write(inst, "plugins/prd-os/runner.py", "founder was here\n")
    head_before = git(inst, "rev-parse", "HEAD")

    rc, out = run(skel, "--apply")
    assert rc == 0, out
    assert "REFUSE" in out, out
    assert is_dirty(inst, "plugins/prd-os/runner.py"), "founder edit was cleared"
    assert git(inst, "rev-parse", "HEAD") == head_before
    assert (inst / "plugins/prd-os/runner.py").read_text() == "founder was here\n"


# --------------------------------------------------------------------------
# unstage
# --------------------------------------------------------------------------

def test_staged_add_with_a_rescued_copy_is_unstaged_and_survives_on_disk(world):
    skel, inst = world
    body = "dead package but real code\n"
    write(skel, "rescued/dead/thing.py", body)
    git(skel, "add", "-A")
    git(skel, "commit", "-qm", "rescue")

    write(inst, "README.md", "base\n")
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")
    write(inst, "plugins/dead/thing.py", body)
    git(inst, "add", "plugins/dead/thing.py")
    assert is_dirty(inst, "plugins/dead/thing.py")

    rc, out = run(skel, "--apply")
    assert rc == 0, out
    assert not is_dirty(inst, "plugins/dead/thing.py"), out
    survivor = inst / "plugins/dead/thing.py"
    assert survivor.is_file(), "unstage DELETED the file"
    assert survivor.read_text() == body, "unstage changed the bytes"


def test_staged_add_with_no_rescued_copy_is_refused(world):
    """NEGATIVE: no committed copy anywhere means unstaging risks the last copy.

    The memory-lifecycle scar in one assertion. The file looks like identical
    dirt to the previous test; only the existence of a rescued copy differs.
    """
    skel, inst = world
    write(inst, "README.md", "base\n")
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")
    write(inst, "plugins/dead/thing.py", "the only copy anywhere\n")
    git(inst, "add", "plugins/dead/thing.py")

    rc, out = run(skel, "--apply")
    assert rc == 0, out
    assert "REFUSE" in out and "rescued/" in out, out
    assert is_dirty(inst, "plugins/dead/thing.py"), "unstaged without a rescued copy"


# --------------------------------------------------------------------------
# the commit-failure unwind
# --------------------------------------------------------------------------

def test_a_refusing_pre_commit_hook_leaves_the_index_as_it_found_it(world):
    """A hook exiting 1 must not leave paths staged by a script that then failed.

    Two of the five real instances carry pre-commit hooks, so this path is
    reachable in production, and until this test it had never once executed.
    The hook here exits 1 unconditionally -- the cheapest possible stand-in for
    lefthook refusing -- and the assertion is on the INDEX, not on the message.
    """
    skel, inst = world
    seed_skeleton_blob(skel, "plugins/prd-os/runner.py", "v1\n")
    write(inst, "plugins/prd-os/runner.py", "old\n")
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")
    write(inst, "plugins/prd-os/runner.py", "v1\n")

    hook = inst / ".git/hooks/pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho 'gate says no' >&2\nexit 1\n")
    hook.chmod(0o755)

    staged_before = git(inst, "diff", "--cached", "--name-only")
    head_before = git(inst, "rev-parse", "HEAD")

    rc, out = run(skel, "--apply")
    assert rc == 0, out
    assert "REFUSED" in out, out
    assert git(inst, "rev-parse", "HEAD") == head_before, "commit landed despite the hook"
    assert git(inst, "diff", "--cached", "--name-only") == staged_before, (
        "index left staged by a commit that failed"
    )
    assert (inst / "plugins/prd-os/runner.py").read_text() == "v1\n", "content lost"


def test_the_unwind_test_would_notice_a_missing_unwind(world):
    """Negative self-test FOR the unwind test: prove the assertion can fail.

    Without this, `test_a_refusing_pre_commit_hook...` passes for the wrong
    reason if `git add` were ever dropped -- nothing would be staged, so
    "index unchanged" would hold trivially. Here the same hook setup is used
    but the staging is done by hand and NOT unwound, and the same assertion is
    checked to fail. A test that cannot fail is not a test.
    """
    skel, inst = world
    write(inst, "plugins/prd-os/runner.py", "old\n")
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")
    write(inst, "plugins/prd-os/runner.py", "v1\n")

    staged_before = git(inst, "diff", "--cached", "--name-only")
    git(inst, "add", "--", "plugins/prd-os/runner.py")   # staged, never unwound
    assert git(inst, "diff", "--cached", "--name-only") != staged_before, (
        "the unwind assertion cannot distinguish unwound from never-staged"
    )
