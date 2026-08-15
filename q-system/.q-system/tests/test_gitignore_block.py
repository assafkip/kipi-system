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


class TestTheWiringIntoTheUpdater:
    """The block is useless unwired, and worse than useless wired in the wrong
    order. Both halves are asserted here rather than trusted."""

    UPDATER = os.path.join(REPO, "kipi-update.sh")

    def text(self):
        with open(self.UPDATER, encoding="utf-8") as handle:
            return handle.read()

    def test_the_updater_actually_calls_it(self):
        assert "kipi-update-gitignore-block.py" in self.text(), (
            "the writer is not called from the updater -- a built, tested, "
            "wired-to-nothing engine (the sp-0f773063 class)")

    def test_it_runs_BEFORE_the_untrack_migration(self):
        """ORDER IS THE WHOLE POINT. `git rm --cached` leaves the file on disk
        untracked; if it is not yet ignored at that moment, git reports it and
        the next auto-commit puts it straight back."""
        text = self.text()
        block_at = text.index("kipi-update-gitignore-block.py")
        untrack_at = text.index('for sys_path in "${SYSTEM_NEVER_COMMIT[@]}"')
        assert block_at < untrack_at, (
            "the .gitignore block is written AFTER the untrack migration, so "
            "every untracked marker is visible to auto-commit until the next run")

    def test_it_also_runs_before_the_updater_scans_for_system_state(self):
        """Belt and braces, and worth pinning.

        SYSTEM_NEVER_COMMIT already stops the updater committing the three
        integrity paths, so this ordering is not what protects them today. It is
        what protects the NEXT path added to the stanza: a path that is ignored
        before `git status` runs is never offered to the classifier at all, so it
        needs no second entry in a hand-kept array to be safe. Ignoring is the
        layer every writer reads; the array is one writer's opt-out list."""
        text = self.text()
        block_at = text.index("kipi-update-gitignore-block.py")
        # The INVOCATION, not the first mention. `--system-state` appears in a
        # comment ~1300 lines above the call site, and anchoring on that made
        # this test pass for the wrong reason on its first run.
        scan_at = text.index('"$sys_classifier" --system-state')
        assert block_at < scan_at, (
            "the .gitignore block is written after the updater scans for "
            "system state, so a newly-stanza'd path is still offered to the "
            "classifier on the run that introduces it")

    def test_the_updater_still_parses(self):
        r = subprocess.run(["bash", "-n", self.UPDATER],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


class TestTheFileTheWriterCreatesCanActuallyBeCommitted:
    """A defect in THIS fix, found by running it against real instances.

    Dry-checked on three live instances 2026-08-14: none of them has a root
    .gitignore AT ALL, so the writer does not edit a file, it CREATES one. Git
    honours an untracked .gitignore, so the ignore rules work either way -- but
    an untracked file is one nobody committed, in a repo nobody looks at, and
    auto-commit.py classified `.gitignore` as `unclassified`.

    Unclassified means REPORTED, never committed (ASK-498). So the fix would
    have left every one of the 22 instances printing the same unclassifiable
    path on every single run, forever, and the file itself unversioned -- not in
    the instance's history, not recoverable if something removed it.

    That is the exact shape this whole PR is about: state the system writes for
    itself that nothing is allowed to commit, sitting dirty until it becomes
    background noise. Fixing it in the same breath rather than filing it.
    """

    def test_a_created_gitignore_is_offered_to_the_fleet_sync(self, tmp_path):
        root = make_instance(tmp_path)
        assert not (root / ".gitignore").exists()
        blockmod.main(["--skeleton", REPO, "--instance", str(root)])

        assert ".gitignore" in untracked(root), "precondition: it is untracked"
        assert auto_commit.system_state_paths([".gitignore"]) == [".gitignore"], (
            "the writer creates a file the fleet sync is not allowed to commit, "
            "so it stays untracked and unclassified on every instance forever")

    def test_it_is_chore_not_founder_content(self):
        """It must be `chore`. system_state_paths narrows to chore precisely so
        an unattended fleet-wide sweep never takes founder-authored content."""
        assert auto_commit.classify(".gitignore")[0] == "chore"

    def test_an_instance_gitignore_is_not_swept_as_unclassified(self):
        """The negative half: `unclassified` is what REPORTS a path instead of
        committing it. If this regresses, the noise comes straight back."""
        assert auto_commit.classify(".gitignore") != auto_commit.SKIP_UNCLASSIFIED


class TestUntrackingWithoutIgnoringRegresses:
    """The behavioural half of the ordering argument, run for real."""

    def track_the_marker(self, root):
        rel = "q-system/.q-system/.claude-integrity-armed"
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("armed 2026-08-14T20:13:59Z\n")
        git(str(root), "add", "-f", rel)
        git(str(root), "commit", "-qm", "the state five instances were in")
        assert git(str(root), "ls-files", "--error-unmatch", rel).returncode == 0
        return rel

    def test_untrack_alone_hands_the_marker_straight_back_to_auto_commit(self, tmp_path):
        """NEGATIVE CONTROL for the ordering. Untracking without the block
        leaves the marker untracked AND unignored, which is exactly the state
        auto-commit sweeps."""
        root = make_instance(tmp_path)
        rel = self.track_the_marker(root)

        git(str(root), "rm", "--cached", "--quiet", "--", rel)
        git(str(root), "commit", "-qm", "untrack")

        assert (root / rel).exists(), "the untrack must never delete the file"
        assert rel in untracked(root)
        assert auto_commit.system_state_paths(untracked(root)) == [rel], (
            "if this is empty the regression closed some other way -- find out "
            "where before deleting this test")

    def test_block_then_untrack_ends_clean(self, tmp_path):
        """The wired order. Same fixture, block first."""
        root = make_instance(tmp_path)
        rel = self.track_the_marker(root)

        blockmod.main(["--skeleton", REPO, "--instance", str(root)])
        git(str(root), "rm", "--cached", "--quiet", "--", rel)
        git(str(root), "commit", "-qm", "untrack")

        assert (root / rel).exists(), "the untrack must never delete the file"
        assert rel not in untracked(root)
        # Names the MARKER rather than asserting the offered list is empty.
        # The broad version was written before .gitignore itself became
        # committable, and it then failed for the right reason: the writer
        # creates a root .gitignore, which IS now offered to the fleet sync on
        # purpose (see TestTheFileTheWriterCreatesCanActuallyBeCommitted). An
        # assertion that breaks when an unrelated path is correctly added was
        # testing the wrong thing.
        assert rel not in auto_commit.system_state_paths(untracked(root))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
