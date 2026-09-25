#!/usr/bin/env python3
"""Tests for check-linear-identity.py (ASK-1967).

Every case runs the real script as a subprocess with HOME pointed at a temp
dir, so no case reads the operator's real ~/.zshenv or token file.

The negative control is `test_empty_env_var_blocks`: an empty KIPI_LINEAR_API_KEY
is the state every launchd job is in once the ~/.zshenv block is lost.
Mutation (run 2026-09-21): delete the empty-env-var branch in check() and that
test goes RED, 1 of 9 failing. The token comparison still exits 2 on "", so only
the named-cause assertion catches it: the branch is what tells the reader WHY.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
CHECKER = SCRIPTS / "check-linear-identity.py"
FLEET_HEALTH = SCRIPTS / "fleet-health-daily.py"
TOKEN = "lin_oauth_fixture_not_a_secret"
EXPORT_LINE = 'export KIPI_LINEAR_API_KEY="$(cat ~/.config/kipi/linear-sana-token)"\n'


def make_home(root: Path, *, token: bool = True, zshenv: str | None = EXPORT_LINE) -> Path:
    home = root / "home"
    (home / ".config" / "kipi").mkdir(parents=True)
    if token:
        (home / ".config" / "kipi" / "linear-sana-token").write_text(TOKEN + "\n")
    if zshenv is not None:
        (home / ".zshenv").write_text(zshenv)
    return home


def run(home: Path, extra_env: dict, args: list[str] | None = None, stdin: str = "") -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ("KIPI_LINEAR_API_KEY", "KIPI_LINEAR_IDENTITY")}
    env["HOME"] = str(home)
    env.update(extra_env)
    return subprocess.run([sys.executable, str(CHECKER), *(args or [])], input=stdin,
                          capture_output=True, text=True, env=env, timeout=30)


class CheckLinearIdentity(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_sana_token_and_zshenv_block_passes(self):
        home = make_home(self.root)
        res = run(home, {"KIPI_LINEAR_API_KEY": TOKEN})
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("sana", res.stdout)

    def test_empty_env_var_blocks(self):
        home = make_home(self.root)
        res = run(home, {"KIPI_LINEAR_API_KEY": ""})
        self.assertEqual(res.returncode, 2)
        self.assertIn("KIPI_LINEAR_API_KEY is empty", res.stderr)

    def test_founder_declaration_passes_without_any_token(self):
        home = make_home(self.root, token=False, zshenv=None)
        res = run(home, {"KIPI_LINEAR_IDENTITY": "founder"})
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("founder", res.stdout)

    def test_instance_without_sana_token_blocks_until_declared(self):
        home = make_home(self.root, token=False, zshenv=None)
        res = run(home, {"KIPI_LINEAR_API_KEY": "some-personal-key"})
        self.assertEqual(res.returncode, 2)
        self.assertIn("KIPI_LINEAR_IDENTITY=founder", res.stderr)

    def test_env_var_holding_another_key_blocks(self):
        home = make_home(self.root)
        res = run(home, {"KIPI_LINEAR_API_KEY": "founder-personal-key"})
        self.assertEqual(res.returncode, 2)
        self.assertIn("does not hold the Sana token", res.stderr)

    def test_missing_zshenv_export_blocks(self):
        home = make_home(self.root, zshenv="# " + EXPORT_LINE)
        res = run(home, {"KIPI_LINEAR_API_KEY": TOKEN})
        self.assertEqual(res.returncode, 2)
        self.assertIn("launchd jobs will not", res.stderr)

    def test_hook_blocks_git_commit_only(self):
        home = make_home(self.root)
        commit = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git -C x commit -m 'a (ASK-1)'"}})
        other = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}})
        blocked = run(home, {"KIPI_LINEAR_API_KEY": ""}, ["--hook"], commit)
        ignored = run(home, {"KIPI_LINEAR_API_KEY": ""}, ["--hook"], other)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("BLOCKED commit", blocked.stderr)
        self.assertEqual(ignored.returncode, 0, ignored.stderr)

    def test_hook_passes_commit_when_identity_is_sana(self):
        home = make_home(self.root)
        commit = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}})
        res = run(home, {"KIPI_LINEAR_API_KEY": TOKEN}, ["--hook"], commit)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_fleet_health_hint_names_the_sana_token_file(self):
        text = FLEET_HEALTH.read_text()
        self.assertFalse("~/.config/kipi/linear-api-key" in text,
                         "fleet-health-daily.py still points at the founder key file")
        self.assertTrue("linear-sana-token" in text,
                        "fleet-health-daily.py does not name the Sana token file")


if __name__ == "__main__":
    unittest.main(verbosity=2)
