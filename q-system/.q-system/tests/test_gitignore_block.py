#!/usr/bin/env python3
"""The skeleton's never-commit stanza must reach every instance (sp-097d2e23).

RED FIRST. The reproducer that opens this file is
TestTheDefectThatWasMeasured::test_an_instance_without_the_stanza_commits_its_own_tripwire_state
-- it drives the REAL auto-commit classifier against a REAL git repo laid out
like an instance, and asserts the integrity paths are not offered to the fleet
sync. Before the managed block existed that test failed, because git reported
the paths as untracked and auto-commit classified them ("chore", "update system
infrastructure"). That is not a hypothetical: five of the 22 skeleton-managed
instances had already committed them, most recently 2026-08-14 14:22.

Nothing here touches a live instance. Every test builds its own tree under
tmp_path, which is the whole point -- a test that reads the real fleet would
pass or fail on whatever state the fleet happened to be in that morning.
"""
import importlib.util
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
SCRIPT = os.path.join(REPO, "kipi-update-gitignore-block.py")
HOOK = os.path.join(REPO, "q-system", "hooks", "auto-commit.py")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


blockmod = load("gitignore_block", SCRIPT)
auto_commit = load("auto_commit", HOOK)


# The paths the skeleton's .gitignore says are instance-local. Named here so a
# test can fail on a path SILENTLY LEAVING the stanza, which a test that only
# read the stanza back could never notice.
INSTANCE_LOCAL = (
    "q-system/.q-system/claude-integrity-baseline.json",
    "q-system/.q-system/claude-integrity-baseline.json.lock",
    "q-system/.q-system/.claude-integrity-armed",
)


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True, check=False)


def make_instance(tmp_path, name="instance"):
    """A git repo laid out the way a kipi instance is."""
    root = tmp_path / name
    (root / "q-system" / ".q-system").mkdir(parents=True)
    (root / "q-system" / "output").mkdir(parents=True)
    git(str(root), "init", "-q")
    git(str(root), "config", "user.email", "t@t")
    git(str(root), "config", "user.name", "t")
    (root / "README.md").write_text("instance\n")
    git(str(root), "add", "-A")
    git(str(root), "commit", "-qm", "init")
    return root


def write_tripwire_state(root):
    """Exactly what the tripwire and the update-check write into an instance."""
    (root / "q-system" / ".q-system" / "claude-integrity-baseline.json").write_text(
        '{"entries": {}}\n')
    (root / "q-system" / ".q-system" / "claude-integrity-baseline.json.lock").write_text("")
    (root / "q-system" / ".q-system" / ".claude-integrity-armed").write_text("armed\n")
    (root / "q-system" / "output" / ".update-check-2026-08-14").write_text("")


def untracked(root):
    out = git(str(root), "status", "--porcelain", "--untracked-files=all").stdout
    return [line[3:] for line in out.splitlines() if line.startswith("??")]


class TestTheDefectThatWasMeasured:
    """The reproducer. It fails with no managed block and passes with one."""

    def test_an_instance_without_the_stanza_commits_its_own_tripwire_state(self, tmp_path):
        """THE red test. Drives the real classifier, not a restatement of it."""
        root = make_instance(tmp_path)
        write_tripwire_state(root)

        # Before: git reports the tripwire state, so the fleet sync takes it.
        offered_before = auto_commit.system_state_paths(untracked(root))
        assert any(p in offered_before for p in INSTANCE_LOCAL), (
            "precondition: without the managed block the classifier must offer "
            "the integrity paths -- if this fails the defect changed shape")

        rc = blockmod.main(["--skeleton", REPO, "--instance", str(root)])
        assert rc == 0

        offered_after = auto_commit.system_state_paths(untracked(root))
        for path in INSTANCE_LOCAL:
            assert path not in offered_after, (
                f"{path} is still offered to the fleet sync after the block")

    def test_the_update_check_stamp_is_ignored_too(self, tmp_path):
        root = make_instance(tmp_path)
        write_tripwire_state(root)
        blockmod.main(["--skeleton", REPO, "--instance", str(root)])
        assert "q-system/output/.update-check-2026-08-14" not in untracked(root)


class TestTheStanzaIsDerivedNotTranscribed:
    """sp-3d5a247e's lesson, applied before it can happen again here."""

    def test_every_instance_local_path_comes_from_the_skeleton_gitignore(self):
        stanza = blockmod.skeleton_stanza(REPO)
        paths = [l for l in stanza if not l.startswith("#")]
        for path in INSTANCE_LOCAL:
            assert path in paths, (
                f"{path} left the skeleton stanza; either it is genuinely no "
                "longer instance-local (update this test and say why) or the "
                "stanza lost a line")

    def test_a_skeleton_with_no_markers_refuses_rather_than_guessing(self, tmp_path):
        fake = tmp_path / "skel"
        fake.mkdir()
        (fake / ".gitignore").write_text("*.pyc\n")
        with pytest.raises(RuntimeError, match="refuses to guess"):
            blockmod.skeleton_stanza(str(fake))

    def test_a_stanza_declaring_no_paths_refuses(self, tmp_path):
        fake = tmp_path / "skel"
        fake.mkdir()
        (fake / ".gitignore").write_text(
            f"{blockmod.SKELETON_BEGIN}\n# only a comment\n{blockmod.SKELETON_END}\n")
        with pytest.raises(RuntimeError, match="refusing to write an empty"):
            blockmod.skeleton_stanza(str(fake))


class TestItIsSafeToRunOnEveryUpdate:
    """The updater calls this on all 22 instances on every run."""

    def test_it_is_idempotent(self, tmp_path):
        root = make_instance(tmp_path)
        blockmod.main(["--skeleton", REPO, "--instance", str(root)])
        first = (root / ".gitignore").read_text()
        for _ in range(3):
            blockmod.main(["--skeleton", REPO, "--instance", str(root)])
        assert (root / ".gitignore").read_text() == first

    def test_it_never_touches_a_line_the_instance_wrote(self, tmp_path):
        root = make_instance(tmp_path)
        own = "# the instance's own rules\nnode_modules/\n*.local\n"
        (root / ".gitignore").write_text(own)
        blockmod.main(["--skeleton", REPO, "--instance", str(root)])
        after = (root / ".gitignore").read_text()
        assert after.startswith(own)
        assert blockmod.BEGIN in after

    def test_a_refreshed_block_replaces_in_place_and_keeps_the_tail(self, tmp_path):
        root = make_instance(tmp_path)
        (root / ".gitignore").write_text(
            f"head\n\n{blockmod.BEGIN}\nstale-path\n{blockmod.END}\ntail\n")
        blockmod.main(["--skeleton", REPO, "--instance", str(root)])
        after = (root / ".gitignore").read_text()
        assert after.startswith("head\n")
        assert after.rstrip().endswith("tail")
        assert "stale-path" not in after
        assert "q-system/.q-system/.claude-integrity-armed" in after

    def test_it_creates_the_file_when_the_instance_has_no_gitignore(self, tmp_path):
        root = make_instance(tmp_path)
        assert not (root / ".gitignore").exists()
        assert blockmod.main(["--skeleton", REPO, "--instance", str(root)]) == 0
        assert blockmod.BEGIN in (root / ".gitignore").read_text()

    def test_check_mode_writes_nothing_and_reports(self, tmp_path):
        root = make_instance(tmp_path)
        assert blockmod.main(
            ["--skeleton", REPO, "--instance", str(root), "--check"]) == 1
        assert not (root / ".gitignore").exists()
        blockmod.main(["--skeleton", REPO, "--instance", str(root)])
        assert blockmod.main(
            ["--skeleton", REPO, "--instance", str(root), "--check"]) == 0

    def test_it_refuses_to_write_into_the_skeleton_itself(self):
        assert blockmod.main(["--skeleton", REPO, "--instance", REPO]) == 2


class TestTheNegativeControl:
    """A test that cannot fail is not a test. These prove the ones above can."""

    def test_removing_the_stanza_breaks_the_reproducer(self, tmp_path):
        """If the block stopped listing the armed marker, the red test must go
        red again. Proven by running the real thing against a stanza with that
        line removed, rather than by trusting that it would."""
        fake_skel = tmp_path / "skel"
        fake_skel.mkdir()
        stanza = [l for l in blockmod.skeleton_stanza(REPO)
                  if "claude-integrity-armed" not in l]
        (fake_skel / ".gitignore").write_text(
            blockmod.SKELETON_BEGIN + "\n" + "\n".join(stanza) + "\n"
            + blockmod.SKELETON_END + "\n")

        root = make_instance(tmp_path)
        write_tripwire_state(root)
        blockmod.main(["--skeleton", str(fake_skel), "--instance", str(root)])
        offered = auto_commit.system_state_paths(untracked(root))
        assert "q-system/.q-system/.claude-integrity-armed" in offered, (
            "the assertion has no teeth: dropping the armed marker from the "
            "stanza left the reproducer green")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
