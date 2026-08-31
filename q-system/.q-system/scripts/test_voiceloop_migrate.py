#!/usr/bin/env python3
"""Tests for kipi-update-voiceloop-migrate.py and its call site (sp-8d55455a).

Two halves, and the second is the one that is easy to skip: the engine can be
perfectly green while nothing ever CALLS it. `test_wiring_*` mutation-checks the
call site in kipi-update.sh -- delete it and those tests go red.
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
MIGRATE = os.path.join(REPO, "kipi-update-voiceloop-migrate.py")
UPDATER = os.path.join(REPO, "kipi-update.sh")

_spec = importlib.util.spec_from_file_location("voiceloop_migrate", MIGRATE)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

OLD = "voice" + "kit"          # never a literal: this file is not exempt from
NEW = "voice" + "loop"         # its own subject when the tree is walked.


def build_instance(root, *, package=OLD, extra=()):
    """A minimal instance with the shape that matters."""
    pkg = os.path.join(root, "plugins", "kipi-core", package)
    os.makedirs(os.path.join(pkg, "tests"), exist_ok=True)
    open(os.path.join(pkg, "__init__.py"), "w").write("VERSION = 1\n")
    os.makedirs(os.path.join(root, "pipeline"), exist_ok=True)
    open(os.path.join(root, "pipeline", "voice.py"), "w").write(
        "import sys, os\n"
        "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', "
        "'plugins', 'kipi-core'))\n"
        f"from {package} import __init__ as _  # noqa\n")
    for rel, body in extra:
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(body)
    return root


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_rewrites_imports_and_moves_the_package(self):
        r = build_instance(os.path.join(self.tmp, "i"))
        out = mig.apply(r, commit=False)
        self.assertTrue(out["moved"])
        self.assertTrue(out["verified"], out["errors"])
        self.assertTrue(os.path.isdir(os.path.join(r, "plugins/kipi-core", NEW)))
        self.assertFalse(os.path.isdir(os.path.join(r, "plugins/kipi-core", OLD)))
        self.assertIn(NEW, open(os.path.join(r, "pipeline/voice.py")).read())
        self.assertNotIn(OLD, open(os.path.join(r, "pipeline/voice.py")).read())

    def test_second_run_is_a_clean_noop(self):
        r = build_instance(os.path.join(self.tmp, "i"))
        mig.apply(r, commit=False)
        again = mig.apply(r, commit=False)
        self.assertFalse(again["moved"])
        self.assertEqual(again["rewritten"], [])
        self.assertEqual(again["renamed"], [])
        self.assertFalse(mig.plan(r)["needs_work"])

    def test_already_migrated_instance_is_untouched(self):
        r = build_instance(os.path.join(self.tmp, "i"), package=NEW)
        self.assertFalse(mig.plan(r)["needs_work"])
        out = mig.apply(r, commit=False)
        self.assertFalse(out["moved"])
        self.assertEqual(out["rewritten"], [])

    def test_both_present_never_deletes_either_package(self):
        """A half-synced instance is reported, not resolved by removal.

        Deleting a package directory is a destructive op and not this script's
        call (the 2026-05-17 volume-deletion scar). The stale copy is left for
        the rsync's own --delete or a founder decision.
        """
        r = build_instance(os.path.join(self.tmp, "i"))
        os.makedirs(os.path.join(r, "plugins", "kipi-core", NEW))
        self.assertEqual(mig.plan(r)["package_action"], "both_present")
        mig.apply(r, commit=False)
        self.assertTrue(os.path.isdir(os.path.join(r, "plugins/kipi-core", OLD)))
        self.assertTrue(os.path.isdir(os.path.join(r, "plugins/kipi-core", NEW)))

    def test_records_are_counted_but_never_rewritten(self):
        """.jsonl ledgers and .md docs say what was true when written."""
        r = build_instance(os.path.join(self.tmp, "i"), extra=[
            ("ledger.jsonl", '{"note": "' + OLD + ' shipped"}\n'),
            ("notes/review.md", "the " + OLD + " selector\n"),
        ])
        out = mig.apply(r, commit=False)
        self.assertIn(OLD, open(os.path.join(r, "ledger.jsonl")).read())
        self.assertIn(OLD, open(os.path.join(r, "notes/review.md")).read())
        self.assertTrue(any(p.endswith("ledger.jsonl") for p in out["history_left"]))

    def test_a_fixture_copy_is_left_alone(self):
        """tests/fixtures/* mirror real artifacts byte for byte.

        The skeleton's destructive-op reference fixture records the scar line
        naming the old package. Rewriting the copy makes it stop matching the
        original it exists to compare against.
        """
        r = build_instance(os.path.join(self.tmp, "i"), extra=[
            ("q-system/tests/fixtures/ref.sh", "# scar: " + OLD + " deleted\n"),
        ])
        mig.apply(r, commit=False)
        self.assertIn(OLD, open(os.path.join(r, "q-system/tests/fixtures/ref.sh")).read())

    def test_nested_repo_is_another_repos_problem(self):
        r = build_instance(os.path.join(self.tmp, "i"))
        nested = os.path.join(r, "projects", "child")
        build_instance(nested)
        os.makedirs(os.path.join(nested, ".git"))
        mig.apply(r, commit=False)
        self.assertIn(OLD, open(os.path.join(nested, "pipeline/voice.py")).read())
        self.assertTrue(os.path.isdir(os.path.join(nested, "plugins/kipi-core", OLD)))

    def test_the_script_never_rewrites_itself(self):
        """Negative self-test: without the exemption this rule erases its rule."""
        self.assertTrue(mig._exempt(MIGRATE))
        plan = mig.plan(os.path.dirname(MIGRATE)) if False else None
        # And the exemption is by identity, not by name, so a copy is still subject.
        self.assertFalse(mig._exempt(os.path.join(self.tmp, "elsewhere.py")))

    def test_a_plan_document_filename_is_not_renamed(self):
        """A dated record's NAME is part of the record; other docs cite it."""
        r = build_instance(os.path.join(self.tmp, "i"), extra=[
            (f"q-system/output/plans/ask-565-{OLD}-skew-2026-08-09.md", "history\n"),
        ])
        out = mig.apply(r, commit=False)
        self.assertEqual(out["renamed"], [])
        self.assertTrue(os.path.exists(
            os.path.join(r, f"q-system/output/plans/ask-565-{OLD}-skew-2026-08-09.md")))

    def test_a_failed_commit_is_finished_by_the_next_run(self):
        """Reading the disk cannot see that the commit never happened.

        Measured 2026-08-30 on one instance: its own commit-msg gate refused
        the migration commit, so the bytes were right and the work sat staged. The
        next run saw the new name everywhere and reported already/needs_work=
        False, walking past a dirty tree that the updater's dirty guard would
        then refuse forever.
        """
        r = build_instance(os.path.join(self.tmp, "i"))
        subprocess.run(["git", "-C", r, "init", "-q"], check=True)
        subprocess.run(["git", "-C", r, "add", "-A"], check=True)
        subprocess.run(["git", "-C", r, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "base"], check=True)
        mig.apply(r, commit=False)          # writes, never commits: the mid state
        subprocess.run(["git", "-C", r, "add", "-A"], check=True)

        p = mig.plan(r)
        self.assertEqual(p["package_action"], "already")   # disk looks finished
        self.assertTrue(p["staged_migration"], "staged work not detected")
        self.assertTrue(p["needs_work"], "a staged-but-uncommitted migration "
                                         "reported as finished")

        out = mig.apply(r, commit=True)
        self.assertTrue(out["committed"], out["errors"])
        left = subprocess.run(["git", "-C", r, "diff", "--cached", "--name-only"],
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(left, "", "staged work survived the recovery run")

    def test_the_commit_never_absorbs_unrelated_staged_work(self):
        """Codex MAJOR on PR #292 (sp-27bbf105): the commit carried no pathspec.

        The ADD was already scoped and the COMMIT was not, so `git commit -m`
        wrote the WHOLE index. The updater's dirty guard deliberately PERMITS
        staged work outside q-system/, .claude/ and plugins/, so a founder file
        in that permitted space landed inside a migration commit.

        This is feedback_defect_class_relocates: an earlier fix in this same
        file moved the hole from `git add` to `git commit` and the suite could
        not see it, because the only commit test staged everything with
        `git add -A` and then asserted the index came back EMPTY -- an
        assertion that only passes while the commit is unscoped. That test
        pinned the defect. Both halves are asserted here: unrelated staged work
        SURVIVES staged, and the migration itself still lands.
        """
        r = build_instance(os.path.join(self.tmp, "i"))
        os.makedirs(os.path.join(r, "notes"), exist_ok=True)
        open(os.path.join(r, "notes", "founder.md"), "w").write("before\n")
        subprocess.run(["git", "-C", r, "init", "-q"], check=True)
        subprocess.run(["git", "-C", r, "add", "-A"], check=True)
        subprocess.run(["git", "-C", r, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "base"], check=True)

        # A TRACKED founder file, edited and staged.
        open(os.path.join(r, "notes", "founder.md"), "w").write("staged edit\n")
        subprocess.run(["git", "-C", r, "add", "--", "notes/founder.md"], check=True)
        # A BRAND NEW founder file, staged but never committed. The two are
        # different git paths: one is a modification in HEAD, one is an addition.
        open(os.path.join(r, "notes", "new-wip.md"), "w").write("brand new\n")
        subprocess.run(["git", "-C", r, "add", "--", "notes/new-wip.md"], check=True)

        out = mig.apply(r, commit=True)
        self.assertTrue(out["committed"], out["errors"])

        landed = subprocess.run(
            ["git", "-C", r, "show", "--name-only", "--pretty=format:", "HEAD"],
            capture_output=True, text=True).stdout.split()
        self.assertNotIn("notes/founder.md", landed,
                         "migration commit absorbed a founder's staged edit")
        self.assertNotIn("notes/new-wip.md", landed,
                         "migration commit absorbed a founder's new staged file")

        still = subprocess.run(["git", "-C", r, "diff", "--cached", "--name-only"],
                               capture_output=True, text=True).stdout.split()
        self.assertIn("notes/founder.md", still,
                      "founder's staged edit was swept out of the index")
        self.assertIn("notes/new-wip.md", still,
                      "founder's new staged file was swept out of the index")

        # Negative half: scoping the commit must not stop the migration landing.
        self.assertIn("pipeline/voice.py", landed,
                      "the rewrite this migration exists to make never committed")
        head_voice = subprocess.run(
            ["git", "-C", r, "show", "HEAD:pipeline/voice.py"],
            capture_output=True, text=True).stdout
        self.assertIn(NEW, head_voice)
        self.assertNotIn(OLD, head_voice)

    def test_a_founder_edit_in_a_file_the_migration_rewrites_abandons_it(self):
        """Codex MAJOR round 2 on PR #292: the residual the pathspec did not close.

        Scoping the commit stopped it absorbing an UNRELATED staged file. It left
        the case where the founder's staged edit is in the VERY file the token
        swap has to touch: the swap and the edit are then the same file and no
        pathspec can separate them.

        So the migration does not write at all. It reports the error, the caller
        abandons the instance BEFORE the --delete rsync, and the founder's work is
        exactly where they left it. Loud and reversible beats a migration commit
        that quietly carries somebody's work in progress. The instance stays on
        the old package name, which is inert -- the rsync that would strand its
        imports never runs.
        """
        r = build_instance(os.path.join(self.tmp, "i"))
        subprocess.run(["git", "-C", r, "init", "-q"], check=True)
        subprocess.run(["git", "-C", r, "add", "-A"], check=True)
        subprocess.run(["git", "-C", r, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "base"], check=True)
        voice = os.path.join(r, "pipeline", "voice.py")
        before = open(voice).read()
        open(voice, "a").write("# founder work in progress\n")
        subprocess.run(["git", "-C", r, "add", "--", "pipeline/voice.py"], check=True)

        out = mig.apply(r, commit=True)
        self.assertFalse(out["verified"], "wrote over a file the founder was editing")
        self.assertTrue(out["errors"])
        self.assertFalse(out["committed"])
        self.assertFalse(out["rewritten"], "rewrote despite refusing")

        # Nothing moved, so the instance is unchanged rather than half-migrated.
        self.assertTrue(os.path.isdir(os.path.join(r, "plugins/kipi-core", OLD)))
        # The founder's edit is byte-for-byte where they left it, still staged.
        now = open(voice).read()
        self.assertEqual(now, before + "# founder work in progress\n")
        self.assertIn(OLD, now, "the token was swapped under a refusal")
        staged = subprocess.run(["git", "-C", r, "diff", "--cached", "--name-only"],
                                capture_output=True, text=True).stdout.split()
        self.assertIn("pipeline/voice.py", staged)

    def test_an_untracked_file_in_the_rewrite_set_does_not_abandon(self):
        """Negative control for the refusal, and it pins a DELIBERATE decision.

        An untracked file in the rewrite set is somebody's WIP too, but this
        module already decided to rewrite it and leave it untracked rather than
        let it import a package that no longer exists. If the refusal above
        widened to untracked files it would silently reverse that, so the
        refusal is scoped to TRACKED files with uncommitted changes.
        """
        r = build_instance(os.path.join(self.tmp, "i"), extra=[
            ("scratch/wip.py", "from " + OLD + " import x\n")])
        subprocess.run(["git", "-C", r, "init", "-q"], check=True)
        subprocess.run(["git", "-C", r, "add", "--", "pipeline", "plugins"], check=True)
        subprocess.run(["git", "-C", r, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "base"], check=True)
        out = mig.apply(r, commit=True)
        self.assertTrue(out["verified"], out["errors"])
        self.assertIn("scratch/wip.py", out["rewritten"])
        self.assertIn("scratch/wip.py", out["left_untracked"])

    def test_a_finished_instance_is_still_finished(self):
        """Negative control for the test above: the new signal must not make
        every already-migrated instance look like it needs work."""
        r = build_instance(os.path.join(self.tmp, "i"), package=NEW)
        subprocess.run(["git", "-C", r, "init", "-q"], check=True)
        subprocess.run(["git", "-C", r, "add", "-A"], check=True)
        subprocess.run(["git", "-C", r, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "base"], check=True)
        p = mig.plan(r)
        self.assertEqual(p["staged_migration"], [])
        self.assertFalse(p["needs_work"])

    def test_refuses_to_run_against_the_skeleton(self):
        r = build_instance(os.path.join(self.tmp, "i"))
        open(os.path.join(r, "instance-registry.json"), "w").write("{}")
        rc = mig.main(["--repo", r, "--apply"])
        self.assertEqual(rc, 2)
        self.assertTrue(os.path.isdir(os.path.join(r, "plugins/kipi-core", OLD)))


class WiringTest(unittest.TestCase):
    """The engine being green proves nothing about the engine being CALLED."""

    def setUp(self):
        self.src = open(UPDATER).read()

    def test_the_updater_invokes_the_migration(self):
        self.assertIn("kipi-update-voiceloop-migrate.py", self.src,
                      "the updater does not reference the migration helper")
        self.assertRegex(self.src, r'VOICELOOP_MIGRATE"\s+--repo\s+"\$path"\s+--apply',
                         "the call site does not pass --apply, so it only previews")

    def test_it_runs_before_the_plugins_rsync(self):
        """Order is the whole point: after the rsync, --delete has already
        stranded the imports it was supposed to fix."""
        call = self.src.index("VOICELOOP_MIGRATE=")
        rsync = self.src.index("Syncing $prefix/ from skeleton")
        self.assertLess(call, rsync,
                        "migration runs AFTER the sync; the imports are already stranded")

    def test_it_runs_after_the_dirty_guard_and_checkpoint(self):
        guard = self.src.index("refusing to commit unrelated work")
        ckpt = self.src.index("could not checkpoint the instance")
        call = self.src.index("VOICELOOP_MIGRATE=")
        self.assertLess(guard, call, "migration writes before the tree is proven clean")
        self.assertLess(ckpt, call, "migration writes before the checkpoint is taken")

    def test_a_failed_migration_abandons_the_instance(self):
        window = self.src[self.src.index("VOICELOOP_MIGRATE="):][:1200]
        self.assertIn("abandon_instance", window,
                      "a failed migration falls through to the --delete rsync")

    def test_the_updater_still_parses(self):
        self.assertEqual(
            0, subprocess.run(["bash", "-n", UPDATER],
                              capture_output=True).returncode)


if __name__ == "__main__":
    unittest.main(verbosity=2)
