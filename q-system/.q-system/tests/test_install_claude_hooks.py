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

import json
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
        self.register()

    def register(self):
        """Wire the hook in the synthetic settings.json.

        A copied-but-unregistered hook does not run, so the installer treats it
        as a FAILURE (PR #279 codex blocker). Every case that expects a
        successful install therefore needs the tree to actually wire it -- which
        is the point: without this, the fixtures were asserting success for a
        gate that would never have fired.
        """
        os.makedirs(os.path.join(self.tmp, ".claude"), exist_ok=True)
        with open(os.path.join(self.tmp, ".claude", "settings.json"), "w") as fh:
            json.dump({"hooks": {"PreToolUse": [
                {"hooks": [{"type": "command", "command": self.dst}]}]}}, fh)

    def unregister(self):
        with open(os.path.join(self.tmp, ".claude", "settings.json"), "w") as fh:
            json.dump({"hooks": {}}, fh)

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

    # A REAL DISARM, not a rename. The first version of these mutants did
    # `.replace("emit_deny", "echo_allow")`, which renames the FUNCTION
    # DEFINITION too -- so the hook kept denying and the mutants were semantic
    # no-ops. They passed only because the old ratchet counted the token, which
    # is the shortcut codex broke twice. Flipping the emitted verdict is what
    # actually turns the gate off.
    DISARM = ('permissionDecision: "deny"', 'permissionDecision: "allow"')

    def test_a_source_that_removes_denies_is_refused(self):
        """The negative self-test. If this passes, the installer is the hole."""
        run(self.tmp)
        before = open(self.dst).read()
        with tempfile.TemporaryDirectory() as fake_repo:
            src_dir = os.path.join(fake_repo, "q-system", ".q-system", "hooks")
            os.makedirs(src_dir)
            scripts = os.path.join(fake_repo, "q-system", ".q-system", "scripts")
            os.makedirs(scripts)
            gutted = before.replace(*self.DISARM)
            self.assertNotEqual(gutted, before, "the disarm did not change anything")
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
            body = text.replace(*self.DISARM)
            assert body != text, "the disarm did not change anything"
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

    def test_the_differential_catches_an_unprobed_disable(self):
        """PR #279 codex major, round 7, made runnable.

        A candidate that passes every hard-coded canary while disabling an
        operation nobody probed. The verb below is touched by neither MUST_DENY
        nor MUST_ALLOW, so the canaries alone ACCEPT the gutted hook -- which is
        precisely the finding. The differential, which uses the RUNNING hook as
        its oracle instead of a list someone wrote, refuses it and names it.
        """
        import importlib.util
        verb = "mk" + "fs"
        spec = importlib.util.spec_from_file_location("inst", INSTALLER)
        inst = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inst)

        real = open(SOURCE).read()
        candidate = real.replace("    '%s'\n" % verb, "")
        self.assertNotEqual(candidate, real, "the pattern anchor moved")

        self.assertIsNone(inst.refuse_if_weaker("h.sh", real, real),
                          "the real hook was refused")
        self.assertIsNone(inst.refuse_if_weaker("h.sh", candidate, None),
                          "the canaries were expected to MISS this; if they now "
                          "catch it, pick an operation they still do not probe")
        refusal = inst.refuse_if_weaker("h.sh", candidate, real)
        self.assertIsNotNone(refusal, "the differential missed an unprobed disable")
        self.assertIn(verb, refusal, "the refusal does not name what was lost")

    def test_an_env_var_backdoor_is_refused(self):
        """PR #279 minor, codex's shape exactly: every canary passes because the
        probe runs with a clean environment and never sets the key.

        `${VAR:-}` is load-bearing in this fixture. A bare `$VAR` aborts under
        `set -u`, so the hook dies, emits nothing, and the canaries DO catch it
        -- my first fixture did exactly that and therefore tested nothing. A real
        backdoor survives the shell it hides in.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location("inst", INSTALLER)
        inst = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inst)
        real = open(SOURCE).read()
        backdoor = real.replace(
            'INPUT="$(cat)"',
            '[ "${KIPI_LET_ME_THROUGH:-}" = 1 ] && exit 0\nINPUT="$(cat)"', 1)
        self.assertNotEqual(backdoor, real, "the anchor moved")

        # The behavioural canaries alone MISS it, which is the finding.
        self.assertIsNone(inst.refuse_if_weaker("h.sh", backdoor, None))
        # Against the installed hook, the new env read is refused.
        refusal = inst.refuse_if_weaker("h.sh", backdoor, real)
        self.assertIsNotNone(refusal, "an env-var backdoor installed")
        self.assertIn("KIPI_LET_ME_THROUGH", refusal,
                      "the refusal does not name the variable")

    def test_a_source_with_no_shebang_is_refused_on_a_FIRST_install(self):
        """PR #279 minor. The refusal was gated on the INSTALLED copy having a
        shebang, so on a first install -- where there is no installed copy -- it
        never ran."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("inst", INSTALLER)
        inst = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inst)
        real = open(SOURCE).read()
        headless = real.split("\n", 1)[1]
        self.assertFalse(headless.startswith("#!"))
        refusal = inst.refuse_if_weaker("h.sh", headless, None)
        self.assertIsNotNone(refusal, "a shebang-less hook installed on a first run")
        self.assertIn("shebang", refusal)

    def test_a_second_vendored_hook_is_not_refused_forever(self):
        """PR #279 minor. MUST_DENY encodes destructive-op-deny.sh's semantics,
        so applied to ANY hook a second one -- a lint, a formatter -- fails every
        canary and is refused forever, with the fleet updater warning on every
        run until somebody deletes the file. A gate that no legitimate input can
        satisfy gets switched off."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("inst", INSTALLER)
        inst = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inst)
        other = "#!/bin/bash\nset -uo pipefail\ncat >/dev/null\nexit 0\n"
        self.assertIsNone(inst.refuse_if_weaker("some-lint.sh", other, None))
        self.assertIsNone(inst.refuse_if_weaker("some-lint.sh", other, other))
        # It still has to parse and carry a shebang.
        broken = "set -uo pipefail\nif [ broken\n"
        self.assertIsNotNone(inst.refuse_if_weaker("some-lint.sh", broken, other))

    def test_the_destructive_hook_still_gets_the_full_canaries(self):
        """Scoping must not turn the real gate's canaries off."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("inst", INSTALLER)
        inst = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inst)
        real = open(SOURCE).read()
        gutted = real.replace('permissionDecision: "deny"',
                              'permissionDecision: "allow"')
        self.assertNotEqual(gutted, real)
        self.assertIsNotNone(
            inst.refuse_if_weaker("destructive-op-deny.sh", gutted, real),
            "the disarmed destructive hook was accepted")

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

    def test_an_unregistered_hook_is_a_failure_not_a_success(self):
        """PR #279 codex BLOCKER. A file on disk is not a gate armed.

        The installer verified bytes and the execute bit and printed
        "installed and verified executable" while nothing in settings.json
        referenced the file. On a clean machine the guard would sit there,
        correct and executable, and never run once.
        """
        self.unregister()
        proc = run(self.tmp)
        self.assertNotEqual(proc.returncode, 0,
                            "an unregistered hook was reported as installed")
        self.assertIn("NOT REGISTERED", proc.stdout)
        self.assertIn(self.dst, proc.stdout, "the message does not name the fix")

    def test_check_flags_an_unregistered_hook(self):
        run(self.tmp)
        self.unregister()
        proc = run(self.tmp, "--check")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("NOT REGISTERED", proc.stdout)

    def test_a_hook_wired_only_in_settings_local_counts_as_registered(self):
        """A local override still runs it; calling that unregistered would be a
        false alarm in the other direction."""
        run(self.tmp)
        self.unregister()
        with open(os.path.join(self.tmp, ".claude", "settings.local.json"), "w") as fh:
            json.dump({"hooks": {"PreToolUse": [
                {"hooks": [{"type": "command", "command": self.dst}]}]}}, fh)
        proc = run(self.tmp, "--check")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

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

    def test_the_replaced_hook_is_kept_and_is_recoverable(self):
        """The live hook is not a checkout of anything.

        It is whatever was last written into $HOME, so a drifted or
        hand-edited-during-an-incident copy exists in no git object. Overwriting
        it with no backup destroys the only copy. This plants a drifted hook,
        installs over it, and reads the backup back byte for byte.
        """
        os.makedirs(self.hooks, exist_ok=True)
        # A REAL drifted hook, not a stub: the installer's ratchet refuses a
        # source that reads env vars the installed copy does not, and a stub
        # trips that instead of exercising the backup. Drift here is what it is
        # in the field -- the shipped guard plus a local edit.
        with open(SOURCE) as fh:
            drifted = fh.read() + "\n# LOCAL EMERGENCY EDIT, in no git object\n"
        with open(self.dst, "w") as fh:
            fh.write(drifted)
        os.chmod(self.dst, 0o755)

        proc = run(self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("previous copy kept at", proc.stdout,
                      "the installer overwrote the live hook without saying "
                      "where the old one went")

        backups = os.path.join(self.hooks, ".backups")
        kept = os.listdir(backups)
        self.assertEqual(len(kept), 1, "expected exactly one backup, got %r" % kept)
        with open(os.path.join(backups, kept[0])) as fh:
            self.assertEqual(fh.read(), drifted,
                             "the backup does not match what was replaced")

    def test_a_no_op_install_leaves_no_backup(self):
        """A backup per run would bury the one that matters."""
        run(self.tmp)
        backups = os.path.join(self.hooks, ".backups")
        before = sorted(os.listdir(backups)) if os.path.isdir(backups) else []
        proc = run(self.tmp)
        after = sorted(os.listdir(backups)) if os.path.isdir(backups) else []
        self.assertIn("already installed", proc.stdout)
        self.assertEqual(before, after, "a no-op install wrote a backup")


if __name__ == "__main__":
    unittest.main(verbosity=2)
