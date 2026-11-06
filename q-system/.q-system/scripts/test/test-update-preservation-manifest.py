#!/usr/bin/env python3
"""The kipi update sync guard refuses to delete recent instance work (ASK-3821).

Built on the REAL objects of the incident: fixtures/sync-guard-f00ee9d7 holds
prd_runner.py exactly as plugin-sync 1d2568c5 wrote it (blob 67fc9808) and the
`git format-patch` of kipi-investigations f00ee9d7, which added
_deferral_tracking_gate and its test file the day before. Every case checks the
blob ids, so the fixture cannot drift into a hand-written stand-in, and nothing
here needs that repo to exist.

Two layers:
  * GuardTests run `check` on rsync's own itemized preview of the replay, at the
    literal paths. Each property has a mutant beside it (window moved, skeleton
    given the function, override added), so a pass cannot come from the guard
    refusing everything.
  * WiringTests run `probe`, which drives the updater this checkout ships through
    a throwaway fixture. The negative case deletes the call site from a copy of
    kipi-update.sh and must read NOT WIRED, or the positive case proves nothing.

Every repo and directory is under a TemporaryDirectory; no live path is read or
written.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "q-system/.q-system/scripts/update-preservation-manifest.py"
FIXTURE = REPO_ROOT / "q-system/.q-system/scripts/test/fixtures/sync-guard-f00ee9d7"

_spec = importlib.util.spec_from_file_location("upm", SCRIPT)
upm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(upm)

RUNNER = "plugins/prd-os/scripts/prd_runner.py"
TESTFILE = "plugins/prd-os/tests/test_archive_deferral_gate.py"
SUBJECT = "prd-os: gate archive on deferral prose without a tracked issue"


def g(repo: Path, *args: str, env: dict | None = None) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.email=t@t.t", "-c", "user.name=test", "-c", "commit.gpgsign=false",
         "-C", str(repo), *args],
        capture_output=True, text=True, env=env,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {proc.stderr}")
    return proc.stdout.strip()


def stamp(days_ago: float) -> str:
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return when.strftime("%Y-%m-%dT%H:%M:%S+0000")


class Replay:
    """Instance: prd_runner.py 40 days old, then the real f00ee9d7 patch a day
    before the sync. Skeleton: prd_runner.py as 1d2568c5 delivered it."""

    def __init__(self, root: Path, skeleton_had_it: bool = False):
        self.root = root
        self.inst = root / "inst"
        self.skel = root / "skel"
        before = FIXTURE / "prd_runner.py.at-1d2568c5"

        (self.inst / RUNNER).parent.mkdir(parents=True)
        shutil.copy2(before, self.inst / RUNNER)
        old = {**os.environ, "GIT_AUTHOR_DATE": stamp(40), "GIT_COMMITTER_DATE": stamp(40)}
        g(self.inst, "init", "-q", "-b", "main")
        g(self.inst, "add", "-A", env=old)
        g(self.inst, "commit", "-qm", "instance base", env=old)
        g(self.inst, "am", "-q", str(FIXTURE / "f00ee9d7.patch"),
          env={**os.environ, "GIT_COMMITTER_DATE": stamp(1)})
        self.commit = g(self.inst, "rev-parse", "HEAD")
        blobs = (g(self.inst, "rev-parse", f"HEAD~1:{RUNNER}"),
                 g(self.inst, "rev-parse", f"HEAD:{RUNNER}"),
                 g(self.inst, "rev-parse", f"HEAD:{TESTFILE}"))
        assert blobs == (upm.BEFORE_BLOB, upm.AFTER_BLOB, upm.TEST_BLOB), blobs

        (self.skel / RUNNER).parent.mkdir(parents=True)
        g(self.skel, "init", "-q", "-b", "main")
        if skeleton_had_it:
            # The skeleton shipped the function and its tests, then removed them
            # on purpose. The skeleton owns that removal.
            shutil.copy2(self.inst / RUNNER, self.skel / RUNNER)
            (self.skel / TESTFILE).parent.mkdir(parents=True)
            shutil.copy2(self.inst / TESTFILE, self.skel / TESTFILE)
            g(self.skel, "add", "-A")
            g(self.skel, "commit", "-qm", "skeleton ships the gate")
            (self.skel / TESTFILE).unlink()
        shutil.copy2(before, self.skel / RUNNER)
        g(self.skel, "add", "-A")
        g(self.skel, "commit", "-qm", "skeleton as 1d2568c5 delivered it")

    def stream(self, end: bool = True) -> str:
        """The framed stream kipi-update.sh builds: rsync's itemized preview."""
        src, dest = self.skel / "plugins/prd-os", self.inst / "plugins/prd-os"
        items = subprocess.run(["rsync", "-ain", "--delete", f"{src}/", f"{dest}/"],
                               capture_output=True, text=True, check=True).stdout
        head = f"@@scope\t{src}\t{dest}\tplugins/prd-os\tplugins/prd-os\n"
        return head + items + ("@@end\n" if end else "")

    def check(self, *extra: str, overrides: dict | None = None, end: bool = True):
        ov = self.root / "overrides.json"
        ov.write_text(json.dumps(overrides or {"schema_version": 1, "overrides": []}))
        return subprocess.run(
            ["python3", str(SCRIPT), "check", "--instance-root", str(self.inst),
             "--skeleton-root", str(self.skel), "--overrides", str(ov), *extra],
            input=self.stream(end), capture_output=True, text=True,
        )


class GuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_replay_of_1d2568c5_is_refused_and_names_the_commit_it_would_undo(self):
        r = Replay(self.root)
        res = r.check()
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("REFUSING SYNC", res.stdout)
        self.assertIn(f"{RUNNER}: def _deferral_tracking_gate", res.stdout)
        self.assertIn(f"{TESTFILE}: test file", res.stdout)
        self.assertIn(f"this sync would undo {r.commit[:12]}", res.stdout)
        self.assertIn(SUBJECT, res.stdout)
        # One line per lost item: the refused test file covers its own defs.
        self.assertNotIn(f"{TESTFILE}: def ", res.stdout)

    def test_a_commit_older_than_the_window_is_not_protected(self):
        r = Replay(self.root)
        later = (datetime.now(timezone.utc) + timedelta(days=31)).isoformat()
        res = r.check("--now", later)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("0 refusals", res.stdout)

    def test_a_removal_the_skeleton_made_itself_is_not_refused(self):
        r = Replay(self.root, skeleton_had_it=True)
        res = r.check()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("0 refusals", res.stdout)

    def test_an_override_lets_exactly_the_named_removal_through(self):
        r = Replay(self.root)
        fn = {"commit": r.commit[:10], "path": RUNNER, "symbol": "_deferral_tracking_gate",
              "reason": "gate moved into issue_runner"}
        res = r.check(overrides={"schema_version": 1, "overrides": [fn]})
        self.assertEqual(res.returncode, 2, "an override for the function must not cover the test file")
        self.assertIn(f"{TESTFILE}: test file", res.stdout)
        self.assertIn("allowed by override", res.stdout)
        tf = {"commit": r.commit, "path": TESTFILE, "symbol": "<file>",
              "reason": "tests moved with the gate"}
        res = r.check(overrides={"schema_version": 1, "overrides": [fn, tf]})
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("gate moved into issue_runner", res.stdout)

    def test_an_override_without_a_reason_is_an_error_not_a_pass(self):
        r = Replay(self.root)
        bad = {"commit": r.commit, "path": RUNNER, "symbol": "_deferral_tracking_gate", "reason": " "}
        res = r.check(overrides={"schema_version": 1, "overrides": [bad]})
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("missing: reason", res.stdout)

    def test_a_stream_without_its_end_marker_is_an_error_not_a_pass(self):
        r = Replay(self.root)
        res = r.check(end=False)
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("no @@end", res.stdout)

    def test_a_recent_shell_function_is_protected_too(self):
        inst, skel = self.root / "inst", self.root / "skel"
        for repo in (inst, skel):
            (repo / "hooks").mkdir(parents=True)
            (repo / "hooks/guard.sh").write_text("#!/bin/bash\nold_fn() {\n  :\n}\n")
            g(repo, "init", "-q", "-b", "main")
            g(repo, "add", "-A")
            g(repo, "commit", "-qm", "base")
        (inst / "hooks/guard.sh").write_text(
            "#!/bin/bash\nold_fn() {\n  :\n}\nfunction new_fn {\n  :\n}\n")
        g(inst, "commit", "-qam", "add new_fn")
        items = subprocess.run(["rsync", "-ain", "--delete", f"{skel}/hooks/", f"{inst}/hooks/"],
                               capture_output=True, text=True, check=True).stdout
        stream = f"@@scope\t{skel}/hooks\t{inst}/hooks\thooks\thooks\n{items}@@end\n"
        ov = self.root / "ov.json"
        ov.write_text('{"schema_version": 1, "overrides": []}')
        res = subprocess.run(["python3", str(SCRIPT), "check", "--instance-root", str(inst),
                              "--skeleton-root", str(skel), "--overrides", str(ov)],
                             input=stream, capture_output=True, text=True)
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("hooks/guard.sh: def new_fn", res.stdout)
        self.assertNotIn("old_fn", res.stdout)


def mutant_home(dst: Path) -> Path:
    """A kipi home holding exactly what the probe copies, so one file can be broken."""
    for rel in upm.UPDATER_FILES + upm.OPTIONAL_FILES:
        if (REPO_ROOT / rel).is_file():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / rel, dst / rel)
    shutil.copytree(FIXTURE, dst / upm.FIXTURE_REL)
    return dst


class WiringTests(unittest.TestCase):
    def probe(self, home: Path, *extra: str):
        return subprocess.run(["python3", str(SCRIPT), "probe", "--kipi-home", str(home), *extra],
                              capture_output=True, text=True)

    def test_the_shipped_updater_refuses_the_replay_dry_and_real(self):
        for mode in ([], ["--real"]):
            res = self.probe(REPO_ROOT, *mode)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn("update sync guard: WIRED", res.stdout)
            self.assertIn("_deferral_tracking_gate and its tests kept", res.stdout)

    def test_without_the_call_site_the_probe_says_not_wired_and_the_work_is_lost(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = mutant_home(Path(tmp))
            updater = home / "kipi-update.sh"
            text = updater.read_text()
            call = 'if ! sync_guard_preflight "$path" "$prefix" "$itype"; then'
            self.assertEqual(text.count(call), 1, "call site moved; update this mutant")
            updater.write_text(text.replace(call, "if false; then"))
            res = self.probe(home, "--real")
            self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
            self.assertIn("update sync guard: NOT WIRED", res.stdout)
            self.assertIn("_deferral_tracking_gate removed", res.stdout)
            self.assertIn("test_archive_deferral_gate.py deleted", res.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
