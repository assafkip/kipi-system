#!/usr/bin/env python3
"""ASK-1144: the installer must land the hook, and must refuse to disarm one.

Every case runs against a synthetic `.claude/` under a tmp dir (`--home`).
Nothing here reads or writes the real one.

The blocker this answers (codex, PR #279): the repository held a corrected
destructive-op-deny.sh and `~/.claude/settings.json` ran a stale one, with
nothing connecting them. `checked_in_equals_installed=no`. A security fix that
does not reach the running program is not a fix.

An installer is a write path into the one directory an agent must not be able to
write, so the tests that matter most here are the REFUSALS.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DOTQ = os.path.abspath(os.path.join(HERE, ".."))          # q-system/.q-system
REPO = os.path.abspath(os.path.join(DOTQ, "..", ".."))    # repo root
INSTALLER = os.path.join(DOTQ, "scripts", "install-claude-hooks.py")
SOURCE = os.path.join(DOTQ, "hooks", "destructive-op-deny.sh")


def run(home, *flags):
    return subprocess.run(
        [sys.executable, INSTALLER, "--home", home, *flags],
        capture_output=True, text=True, cwd=REPO, timeout=60)


class InstallerCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hookinstall-")
        self.hooks = os.path.join(self.tmp, ".claude", "hooks")
        self.dst = os.path.join(self.hooks, "destructive-op-deny.sh")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_missing_hook_is_installed_and_executable(self):
        proc = run(self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(os.path.isfile(self.dst), "the hook was not installed")
        with open(self.dst) as a, open(SOURCE) as b:
            self.assertEqual(a.read(), b.read(), "installed bytes differ from source")
        self.assertTrue(os.access(self.dst, os.X_OK),
                        "installed non-executable, which is OFF, not installed")

    def test_check_reports_drift_and_writes_nothing(self):
        proc = run(self.tmp, "--check")
        self.assertEqual(proc.returncode, 1, "clean exit on an uninstalled hook")
        self.assertIn("NOT INSTALLED", proc.stdout)
        self.assertFalse(os.path.exists(self.dst), "--check wrote to disk")

    def test_check_is_green_after_an_install(self):
        run(self.tmp)
        proc = run(self.tmp, "--check")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_check_goes_red_when_the_installed_copy_is_disarmed_by_hand(self):
        """The scar's own signature: content correct in the repo, off on disk."""
        run(self.tmp)
        os.chmod(self.dst, 0o644)
        proc = run(self.tmp, "--check")
        self.assertEqual(proc.returncode, 1, "a 0644 hook was reported clean")
        self.assertIn("NOT EXECUTABLE", proc.stdout)

    def test_a_source_that_removes_denies_is_refused(self):
        """The negative self-test. If this passes, the installer is the hole."""
        run(self.tmp)
        before = open(self.dst).read()
        with tempfile.TemporaryDirectory() as fake_repo:
            src_dir = os.path.join(fake_repo, "q-system", ".q-system", "hooks")
            os.makedirs(src_dir)
            scripts = os.path.join(fake_repo, "q-system", ".q-system", "scripts")
            os.makedirs(scripts)
            gutted = before.replace("emit_deny", "echo_allow")
            with open(os.path.join(src_dir, "destructive-op-deny.sh"), "w") as fh:
                fh.write(gutted)
            shutil.copy2(INSTALLER, os.path.join(scripts, "install-claude-hooks.py"))
            proc = subprocess.run(
                [sys.executable, os.path.join(scripts, "install-claude-hooks.py"),
                 "--home", self.tmp],
                capture_output=True, text=True, timeout=60)
        self.assertNotEqual(proc.returncode, 0, "a disarming source was installed")
        self.assertIn("REFUSED", proc.stdout + proc.stderr)
        self.assertEqual(open(self.dst).read(), before,
                         "the installed hook was modified by a refused install")

    def _install_from(self, transform):
        """Install into self.tmp from a synthetic repo whose hook is transform(orig)."""
        original = open(SOURCE).read()
        fake = tempfile.mkdtemp(prefix="fakerepo-")
        self.addCleanup(shutil.rmtree, fake, True)
        src_dir = os.path.join(fake, "q-system", ".q-system", "hooks")
        scripts = os.path.join(fake, "q-system", ".q-system", "scripts")
        os.makedirs(src_dir); os.makedirs(scripts)
        with open(os.path.join(src_dir, "destructive-op-deny.sh"), "w") as fh:
            fh.write(transform(original))
        shutil.copy2(INSTALLER, os.path.join(scripts, "install-claude-hooks.py"))
        return subprocess.run(
            [sys.executable, os.path.join(scripts, "install-claude-hooks.py"),
             "--home", self.tmp],
            capture_output=True, text=True, timeout=60)

    def test_comment_padding_cannot_smuggle_a_gutted_hook(self):
        """PR #279 round 4, BLOCKER, in my own guard.

        The ratchet counted `emit_deny` and `exit 2` as raw text over the whole
        file, so deleting every real call and typing the word into the comments
        keeps the count identical. A guard whose bypass is a comment is not a
        guard. Counted on code lines only now.
        """
        run(self.tmp)
        before = open(self.dst).read()
        n_deny = before.count("emit_deny")
        n_exit = before.count("exit 2")

        def gut_and_pad(text):
            body = text.replace("emit_deny", "echo_allow").replace("exit 2", "exit 0")
            padding = "\n".join(["# emit_deny exit 2"] * (n_deny + n_exit))
            return body + "\n" + padding + "\n"

        proc = self._install_from(gut_and_pad)
        self.assertNotEqual(proc.returncode, 0,
                            "comment padding installed a gutted hook")
        self.assertIn("REFUSED", proc.stdout + proc.stderr)
        self.assertEqual(open(self.dst).read(), before,
                         "the installed hook was modified by a refused install")

    def test_a_source_that_does_not_parse_is_refused(self):
        """PR #279 round 4, major. A hook bash cannot parse fails OPEN."""
        run(self.tmp)
        before = open(self.dst).read()
        proc = self._install_from(lambda t: t + "\nif [ broken\n")
        self.assertNotEqual(proc.returncode, 0, "an unparseable hook was installed")
        self.assertIn("does not parse", (proc.stdout + proc.stderr))
        self.assertEqual(open(self.dst).read(), before)

    def test_check_flags_an_installed_hook_that_does_not_parse(self):
        """--check must ask the same question, or the gate is greener than the
        installer that fed it."""
        run(self.tmp)
        with open(self.dst, "a") as fh:
            fh.write("\nif [ broken\n")
        proc = run(self.tmp, "--check")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("DOES NOT PARSE", proc.stdout)

    def test_an_empty_source_dir_is_a_refusal_not_a_pass(self):
        """A run that finds nothing to install must not report success."""
        with tempfile.TemporaryDirectory() as fake_repo:
            scripts = os.path.join(fake_repo, "q-system", ".q-system", "scripts")
            os.makedirs(scripts)
            os.makedirs(os.path.join(fake_repo, "q-system", ".q-system", "hooks"))
            shutil.copy2(INSTALLER, os.path.join(scripts, "install-claude-hooks.py"))
            proc = subprocess.run(
                [sys.executable, os.path.join(scripts, "install-claude-hooks.py"),
                 "--home", self.tmp],
                capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 2, "an empty source dir exited clean")

    def test_dry_run_writes_nothing(self):
        proc = run(self.tmp, "--dry-run")
        self.assertIn("WOULD INSTALL", proc.stdout)
        self.assertFalse(os.path.exists(self.dst), "--dry-run wrote to disk")

    def test_installing_twice_is_idempotent(self):
        run(self.tmp)
        first = os.stat(self.dst)
        proc = run(self.tmp)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("already installed", proc.stdout)
        self.assertEqual(os.stat(self.dst).st_size, first.st_size)


if __name__ == "__main__":
    unittest.main(verbosity=2)
