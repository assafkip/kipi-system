#!/usr/bin/env python3
"""An untracked file the skeleton itself wrote is exhaust, not work (sp-940bcf47).

kipi-update.sh refuses an instance when an untracked file collides with a
skeleton path, because overwriting somebody's work-in-progress is unrecoverable.
Right instinct. But the only non-work it could recognise was a file byte-identical
to the skeleton's CURRENT copy -- this same sync's own output. An OLDER skeleton
blob looked like work and refused the instance forever.

Measured 2026-08-15 on a real --dry-run: KTLYST_strategy carried an untracked
q-system/.q-system/scripts/merge-bypass-gate.py from an earlier sync and failed
with "untracked WIP collides with skeleton path" -- while fleet-reach-audit.py
reported WOULD-SYNC for it, because the audit does not model this check. Real
reach was 21 of 22 behind a number that said 22.

THE POINT OF THIS FILE is the refusals. Widening a guard that protects founder
work is the dangerous direction, so every test that proves the exemption fires is
paired with one proving it does NOT fire on bytes the skeleton never wrote.
"""
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
CHECK = REPO / "kipi-update-wip-check.py"

NOT_WORK = 0      # the skeleton demonstrably shipped this blob here
IS_WORK = 1       # it did not; refuse
UNDECIDED = 2     # could not tell; refuse (fail closed)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=False)


def run_check(skeleton, skeleton_path, file_path):
    proc = subprocess.run(
        [sys.executable, str(CHECK), "--skeleton", str(skeleton),
         "--skeleton-path", skeleton_path, "--file", str(file_path)],
        capture_output=True, text=True)
    return proc.returncode


@pytest.fixture
def skeleton(tmp_path):
    """A skeleton that shipped one file twice, so it has an OLD and a NEW blob."""
    skel = tmp_path / "skeleton"
    (skel / "q-system" / ".q-system").mkdir(parents=True)
    git(skel, "init", "-q", "-b", "main")
    git(skel, "config", "user.email", "t@t")
    git(skel, "config", "user.name", "t")
    # fleet-reach-audit.py is IMPORTED by the helper, never transcribed.
    (skel / "fleet-reach-audit.py").write_bytes(
        (REPO / "fleet-reach-audit.py").read_bytes())

    rel = "q-system/.q-system/tool.py"
    (skel / rel).write_text("version one\n")
    git(skel, "add", "-A")
    git(skel, "commit", "-qm", "ships v1")
    (skel / rel).write_text("version two\n")
    git(skel, "add", "-A")
    git(skel, "commit", "-qm", "ships v2")
    return skel


class TestExhaustIsExcused:

    def test_an_older_skeleton_blob_is_not_work(self, skeleton, tmp_path):
        """THE reproducer. The instance holds v1 while the skeleton is on v2 --
        exactly KTLYST_strategy's shape, and the case the byte-identical test
        could never see."""
        stale = tmp_path / "instance-copy.py"
        stale.write_text("version one\n")
        assert run_check(skeleton, "q-system/.q-system/tool.py", stale) == NOT_WORK

    def test_the_current_skeleton_blob_is_not_work_either(self, skeleton, tmp_path):
        same = tmp_path / "same.py"
        same.write_text("version two\n")
        assert run_check(skeleton, "q-system/.q-system/tool.py", same) == NOT_WORK


class TestWorkIsStillRefused:
    """The half that matters. Each of these must NOT be excused."""

    def test_bytes_the_skeleton_never_wrote_are_work(self, skeleton, tmp_path):
        wip = tmp_path / "wip.py"
        wip.write_text("the founder was here\n")
        assert run_check(skeleton, "q-system/.q-system/tool.py", wip) == IS_WORK

    def test_a_real_skeleton_blob_at_the_WRONG_path_is_work(self, skeleton, tmp_path):
        """Path-scoped, not blob-scoped. A blob the skeleton shipped SOMEWHERE
        proves nothing about the file sitting at a different path -- that is the
        same trap fleet-unblock's commit proof avoids."""
        elsewhere = tmp_path / "elsewhere.py"
        elsewhere.write_text("version one\n")
        assert run_check(
            skeleton, "q-system/.q-system/other.py", elsewhere) == IS_WORK

    def test_an_empty_file_is_not_silently_excused(self, skeleton, tmp_path):
        empty = tmp_path / "empty.py"
        empty.write_text("")
        assert run_check(skeleton, "q-system/.q-system/tool.py", empty) == IS_WORK


class TestItFailsClosed:
    """Undecided must never mean excused: the caller only treats 0 as non-work."""

    def test_a_missing_file_is_undecided(self, skeleton, tmp_path):
        assert run_check(
            skeleton, "q-system/.q-system/tool.py", tmp_path / "nope.py") == UNDECIDED

    def test_a_skeleton_without_the_audit_refuses_rather_than_guessing(self, tmp_path):
        bare = tmp_path / "bare"
        bare.mkdir()
        probe = tmp_path / "probe.py"
        probe.write_text("x\n")
        assert run_check(bare, "q-system/x.py", probe) == UNDECIDED

    def test_a_directory_is_undecided_not_excused(self, skeleton, tmp_path):
        d = tmp_path / "adir"
        d.mkdir()
        assert run_check(skeleton, "q-system/.q-system/tool.py", d) == UNDECIDED


class TestTheWiringIntoTheUpdater:

    UPDATER = REPO / "kipi-update.sh"

    def text(self):
        return self.UPDATER.read_text(encoding="utf-8")

    def test_the_updater_calls_it(self):
        assert "kipi-update-wip-check.py" in self.text(), (
            "the helper is wired to nothing (the sp-0f773063 class)")

    def test_the_collision_site_passes_the_skeleton_repo_path(self):
        """The 4th argument is the mapping. Without it the helper would be asked
        about the INSTANCE's spelling of the path and would answer about the
        wrong file -- silently, since a miss just means 'work'."""
        assert 'is_instance_wip "$uf" "$source_path" "" "q-system/$relative"' \
            in self.text(), "the collision call site no longer passes the mapping"

    def test_the_updater_still_parses(self):
        r = subprocess.run(["bash", "-n", str(self.UPDATER)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
