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


def load_script():
    """Import fleet-unblock.py as a module, for the pure helpers.

    Everything else here drives the script as a subprocess against real repos,
    which is right for git behaviour. `succeeded()` is a pure string predicate
    and deserves a direct test rather than one that has to provoke a rare IO
    failure to observe it.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("fleet_unblock", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
    # SEEDED (PR #165 review round 3). This test used to build the file only in
    # the instance, so it was exercising restore-mode on a blob the skeleton
    # never shipped -- encoding the very bug that review found. The real scar is
    # a SKELETON file whose +x rsync dropped, which is what this now models.
    seed_skeleton_blob(skel, "plugins/kipi-core/tool.py", body)
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
    # Seeded for the same reason as the mode tests above (review round 3):
    # without it this exercises a blob the skeleton never shipped.
    seed_skeleton_blob(skel, rel, "#!/usr/bin/env python3\nprint('hi')\n")
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
    # Seeded for the same reason as the mode tests above (review round 3):
    # without it this exercises a blob the skeleton never shipped.
    seed_skeleton_blob(skel, rel, "#!/usr/bin/env python3\nprint('hi')\n")
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


def test_a_founder_chmod_on_a_file_the_skeleton_never_shipped_is_refused(world):
    """PR #165 review round 3, major.

    decide() checks mode FIRST, before it looks at the row's kind at all. That
    ordering is deliberate for the fleet case -- a mode-only row also classifies
    as fleet-written, and committing it would bake the broken mode in. But it
    swallowed the founder case with it: a script the founder wrote and
    deliberately made executable has an unchanged blob and a changed mode, which
    is exactly the shape the restore-mode branch matches. The tool would chmod
    it back and report the instance repaired.

    The scar this branch exists for (KTLYST_strategy) was a SKELETON file whose
    +x rsync had dropped. Attribution is what separates the two, and mode-first
    ordering skipped it.
    """
    skel, inst = world
    # INSIDE the guard's pathspec (plugins/), or the audit never produces a row
    # and decide() is never called. A first draft used scripts/, which is
    # outside it, and both assertions passed while exercising nothing.
    rel = "plugins/kipi-core/founders-own-tool.sh"   # never seeded into skeleton
    write(inst, rel, "#!/bin/sh\necho mine\n", mode=0o644)
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")

    (inst / rel).chmod(0o755)                     # the founder makes it runnable
    assert is_dirty(inst, rel)

    rc, out = run(skel, "--apply")

    assert "restore-mode" not in out, (
        "reverted a mode change on a file the skeleton never shipped\n" + out)
    assert os.access(inst / rel, os.X_OK), "the founder's +x was taken away"


def test_the_skeleton_owned_mode_fix_still_fires(world):
    """Negative control for the test above. If restore-mode stopped firing
    entirely, that assertion would pass while the KTLYST_strategy scar -- the
    whole reason this branch exists -- silently regressed."""
    skel, inst = world
    rel = "plugins/kipi-core/tool.py"
    seed_skeleton_blob(skel, rel, "#!/usr/bin/env python3\nprint('hi')\n")
    write(inst, rel, "#!/usr/bin/env python3\nprint('hi')\n", mode=0o755)
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")
    (inst / rel).chmod(0o644)

    rc, out = run(skel, "--apply")
    assert "restore-mode" in out, out
    assert os.access(inst / rel, os.X_OK), "+x not restored on a skeleton file"


def test_mode_fix_is_not_applied_on_a_dry_run(world):
    """Negative self-test for the dry run: the default must write nothing."""
    skel, inst = world
    # Seeded for the same reason as the test above (review round 3).
    seed_skeleton_blob(skel, "plugins/kipi-core/tool.py", "x\n")
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


def test_founder_staged_content_under_a_skeleton_worktree_blob_is_refused(world):
    """PR #165 review round 4, major. The MIRROR of the round-1 finding.

    Round 1 was: index holds a skeleton blob, worktree holds a founder edit.
    Guarded. This is the other way round -- the founder STAGED their own version
    and the worktree happens to hold a skeleton blob. The round-1 guard passes,
    because it only asks whether the WORKTREE is attributable.

    Then `git add` replaces the founder's staged entry with the worktree blob and
    the commit succeeds. Round 2's unwind restores the staged entry only when the
    commit FAILS; on the success path the founder's staged version is committed
    away and gone.

    Both sides of a path have to be attributable, and 'attributable' for the
    index means either the skeleton wrote it or nothing was staged at all.
    """
    skel, inst = world
    rel = "plugins/prd-os/runner.py"
    seed_skeleton_blob(skel, rel, "v1\n")
    write(inst, rel, "old\n")
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")

    write(inst, rel, "founder staged this\n")
    git(inst, "add", rel)                     # index: founder's own content
    staged_before = git(inst, "rev-parse", ":" + rel)
    write(inst, rel, "v1\n")                  # worktree: the skeleton's blob

    head_before = git(inst, "rev-parse", "HEAD")
    rc, out = run(skel, "--apply")

    assert "REFUSE" in out, out
    assert git(inst, "rev-parse", "HEAD") == head_before, (
        "committed over content the founder had staged\n" + out)
    assert git(inst, "rev-parse", ":" + rel) == staged_before, (
        "the founder's staged version was replaced by git add\n" + out)


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


def test_the_unwind_restores_content_the_founder_had_already_staged(world):
    """PR #165 review round 2, major #1.

    The unwind skipped every path that was ALREADY staged before the run, on the
    reasoning that the tool did not stage it so the tool should not unstage it.
    But `git add` has already overwritten that index entry with the worktree
    content by then. So a founder who had staged their own version of the path
    lost it, and the tool printed 'index unwound' while saying so.

    Skipping a path is not restoring it. The unwind now records the exact index
    entry -- mode and blob -- and puts it back.
    """
    skel, inst = world
    rel = "plugins/prd-os/runner.py"
    seed_skeleton_blob(skel, rel, "v1\n")
    write(inst, rel, "old\n")
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")

    write(inst, rel, "founder staged this\n")
    git(inst, "add", rel)
    staged_before = git(inst, "rev-parse", ":" + rel)
    write(inst, rel, "v1\n")            # worktree: the skeleton's own blob

    hook = inst / ".git/hooks/pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)

    rc, out = run(skel, "--apply")

    staged_after = git(inst, "rev-parse", ":" + rel)
    assert staged_after == staged_before, (
        "the founder's staged version was overwritten by git add and never "
        "restored, while the tool reported the index unwound\n" + out)


def test_a_failed_add_or_restore_is_not_counted_as_success(world):
    """PR #165 review round 2, major #2 -- a hole in my own round-1 fix.

    Round 1 made a REFUSED commit exit non-zero, but it tested the outcome
    string with startswith('REFUSED'). The other producers emit 'FAILED add: ',
    'FAILED <err>' and 'STILL <mode>', none of which start with REFUSED, so
    every one of them still counted as a successful action and still exited 0.

    A denylist of failure strings is the wrong shape for something an unattended
    job reads as its exit code. Success is now an allowlist: an outcome counts
    only if it SAYS it succeeded.

    Tested against the predicate directly rather than by provoking a rare IO
    failure: an earlier draft chmod'ed .git/index read-only, git rewrote it
    anyway, and the test SKIPPED. A skipped test proves nothing, and this is
    about which strings count, which is exactly what a predicate test settles.
    """
    mod = load_script()

    # Every outcome string the shipped code can emit, taken from the source so
    # a new producer cannot quietly land on the success side.
    failures = [
        "FAILED add: fatal: unable to write new index file",
        "FAILED fatal: could not restore",
        "STILL 100644",
        "REFUSED (index unwound): ['gate says no']",
    ]
    successes = ["clean", "committed", "would chmod to 100755",
                 "would restore --staged", "would stage + commit"]

    for outcome in failures:
        assert not mod.succeeded(outcome), f"{outcome!r} counted as success"
    for outcome in successes:
        assert mod.succeeded(outcome), f"{outcome!r} counted as failure"


def test_every_outcome_the_code_emits_is_classified(world):
    """The allowlist must cover what the code actually produces, not what I
    remembered it producing. Derived from the source, so a new outcome string
    with no classification fails here instead of silently counting as success."""
    import re
    src = SCRIPT.read_text(encoding="utf-8")
    mod = load_script()
    # Third element of every `done.append((action, path, <outcome>))` and the
    # outcome in each `return [(...)]` in commit_with_unwind.
    literals = set(re.findall(r'"(clean|committed|would [^"]*|STILL [^"]*|FAILED[^"]*|REFUSED[^"]*)"', src))
    literals |= set(re.findall(r'f"(FAILED[^"]*|STILL [^"]*|REFUSED[^"]*)"', src))
    assert literals, "no outcome literals found; the shape of the code moved"
    for literal in literals:
        probe = literal.replace("{", "").replace("}", "")
        # Every literal must land on one side deliberately; the assertion is
        # that succeeded() has an opinion, and that failures are not successes.
        if probe.startswith(("FAILED", "STILL", "REFUSED")):
            assert not mod.succeeded(probe), f"{probe!r} counted as success"


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
