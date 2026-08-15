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


def test_a_mode_change_carrying_content_drift_is_not_a_mode_fix(world):
    """THE MISSING REFUSAL (added 2026-08-14 while auditing the three actions).

    `commit` and `unstage` each had a test proving they refuse when their proof
    is absent -- test_founder_edit_is_refused and
    test_staged_add_with_no_rescued_copy_is_refused. `restore-mode` had none.
    Its proof is "index and worktree hold the SAME blob", and nothing asserted
    what happens when they do not.

    That is the dangerous direction. decide() checks mode FIRST, so if the
    same-blob condition were ever loosened, a file that lost +x AND was edited
    would be chmodded, the tree would go clean, the guard would clear, and the
    edit would ride into the next sync unattributed. Cleanliness is not the
    property that matters here; attribution is.
    """
    skel, inst = world
    rel = "plugins/kipi-core/tool.py"
    write(inst, rel, "#!/usr/bin/env python3\nprint('hi')\n", mode=0o755)
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")

    # Both at once: the mode dropped AND somebody changed the bytes.
    write(inst, rel, "#!/usr/bin/env python3\nprint('edited by a human')\n")
    (inst / rel).chmod(0o644)

    rc, out = run(skel, "--apply")
    assert rc == 0, out
    assert "restore-mode" not in out, (
        "a content edit was treated as a mode fix; chmod would clear the guard "
        "and carry the edit along unattributed\n" + out)
    assert "REFUSE" in out, out
    assert is_dirty(inst, rel), "the drift must still be there for a human to see"


def test_the_mode_refusal_would_notice_if_the_same_blob_proof_were_dropped(world):
    """Negative control for the test above: prove the assertion has teeth.

    Same fixture, but the content is left ALONE so the row really is mode-only.
    If restore-mode fires here and not above, the classifier is discriminating
    on the proof rather than on the mode difference -- which is the thing the
    test above is actually asserting.
    """
    skel, inst = world
    rel = "plugins/kipi-core/tool.py"
    write(inst, rel, "#!/usr/bin/env python3\nprint('hi')\n", mode=0o755)
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")
    (inst / rel).chmod(0o644)

    rc, out = run(skel, "--apply")
    assert rc == 0, out
    assert "restore-mode" in out, (
        "the mode-only case stopped firing, so the refusal test above proves "
        "nothing -- it would pass even if restore-mode were deleted entirely\n"
        + out)


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
    # Was `rc == 0`, asserting the exit code the PR #165 review found wrong: a
    # run that repaired nothing reported success. The unwind is still the point
    # of this test; the exit code now says the repair did not happen. See
    # test_a_refused_commit_does_not_report_success.
    assert rc != 0, out
    assert "REFUSED" in out, out
    assert git(inst, "rev-parse", "HEAD") == head_before, "commit landed despite the hook"
    assert git(inst, "diff", "--cached", "--name-only") == staged_before, (
        "index left staged by a commit that failed"
    )
    assert (inst / "plugins/prd-os/runner.py").read_text() == "v1\n", "content lost"


def test_a_staged_skeleton_blob_with_a_founder_worktree_edit_is_refused(world):
    """PR #165 review, major #1. The mixed staged/worktree case.

    The index holds a blob the skeleton really did ship, so the fleet-written
    branch of decide() matches and schedules a commit. But the WORKTREE holds
    founder bytes the skeleton never had. Committing the index clears the
    dirty-tree guard while leaving the founder's edit uncommitted, and the very
    next sync overwrites it -- founder work destroyed by the tool whose entire
    job is to avoid exactly that.

    Attribution has to hold for BOTH sides of a path. One side matching the
    skeleton is not attribution, it is half of one.
    """
    skel, inst = world
    rel = "plugins/prd-os/runner.py"
    seed_skeleton_blob(skel, rel, "v1\n")
    write(inst, rel, "old\n")
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")

    write(inst, rel, "v1\n")          # index: the skeleton's own blob
    git(inst, "add", rel)
    write(inst, rel, "founder was here\n")   # worktree: bytes the skeleton never had

    head_before = git(inst, "rev-parse", "HEAD")
    rc, out = run(skel, "--apply")

    assert "REFUSE" in out, out
    assert git(inst, "rev-parse", "HEAD") == head_before, (
        "committed the staged skeleton blob while a founder edit sat in the "
        "worktree; the next sync overwrites that edit")
    assert (inst / rel).read_text() == "founder was here\n", "founder bytes lost"


def test_a_refused_commit_does_not_report_success(world):
    """PR #165 review, major #2.

    main() returned 0 unconditionally and counted a REFUSED commit toward
    `acted`, so a run that repaired nothing printed a success line and exited
    clean. This is the script an unattended fleet job calls: an exit code that
    cannot distinguish "repaired" from "refused and gave up" makes the job
    report green while every instance stays blocked -- the same silent-success
    class the fleet reach work exists to end.
    """
    skel, inst = world
    rel = "plugins/prd-os/runner.py"
    seed_skeleton_blob(skel, rel, "v1\n")
    write(inst, rel, "old\n")
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")
    write(inst, rel, "v1\n")

    hook = inst / ".git/hooks/pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)

    rc, out = run(skel, "--apply")
    assert "REFUSED" in out, out
    assert rc != 0, (
        "exited 0 after repairing nothing; an unattended caller cannot tell "
        "this from a successful run")


def test_a_clean_successful_run_still_exits_zero(world):
    """Negative control for the test above. If every run exited non-zero the
    assertion would pass while telling the caller nothing."""
    skel, inst = world
    rel = "plugins/prd-os/runner.py"
    seed_skeleton_blob(skel, rel, "v1\n")
    write(inst, rel, "old\n")
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")
    write(inst, rel, "v1\n")

    rc, out = run(skel, "--apply")
    assert rc == 0, out
    assert not is_dirty(inst, rel), out


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
