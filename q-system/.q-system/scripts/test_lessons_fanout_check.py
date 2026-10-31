#!/usr/bin/env python3
"""Tests for lessons-fanout-check.py (ASK-3574).

Every fixture is built in a fresh tmpdir. The suite never reads the live
skeleton, the live registry, the live log or the live streak file: all four are
passed in through the script's own seam flags, so a green run here says nothing
about the real fleet and a broken fleet cannot turn this suite red.
"""

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "lessons-fanout-check.py"
CLEAN_LOG = "lessons publish: DISARMED\npropagated to fleet\n"


def write_corpus(root: pathlib.Path, n: int) -> pathlib.Path:
    """Build <root>/q-system/lessons with n lesson files, producer-shaped."""
    lessons = root / "q-system" / "lessons"
    lessons.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (lessons / f"lesson-{i:03d}.md").write_text(f"# lesson {i}\n", encoding="utf-8")
    return lessons


class FanoutCheckCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name)
        self.skel = self.base / "skeleton"
        write_corpus(self.skel, 5)
        self.log = self.base / "lessons-daily.log"
        self.log.write_text(CLEAN_LOG, encoding="utf-8")
        self.streak = self.base / "streak.json"
        self.streak.write_text(json.dumps({"streak": 0}), encoding="utf-8")
        self.registry = self.base / "registry.json"

    def tearDown(self):
        self.tmp.cleanup()

    def set_instances(self, rows):
        self.registry.write_text(json.dumps({"instances": rows}), encoding="utf-8")

    def add_instance(self, name: str, n_lessons, make_dir=True):
        path = self.base / name
        if make_dir:
            path.mkdir(parents=True, exist_ok=True)
            if n_lessons is not None:
                write_corpus(path, n_lessons)
        return {"name": name, "path": str(path)}

    def run_check(self, *extra):
        proc = subprocess.run(
            [sys.executable, "-I", str(SCRIPT),
             "--skeleton", str(self.skel),
             "--registry", str(self.registry),
             "--log", str(self.log),
             "--streak", str(self.streak), *extra],
            capture_output=True, text=True,
        )
        return proc.returncode, proc.stdout + proc.stderr

    # --- green ----------------------------------------------------------
    def test_every_instance_level_is_green(self):
        self.set_instances([self.add_instance("a", 5), self.add_instance("b", 5)])
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("GREEN", out)

    # --- the ASK-3574 shape ---------------------------------------------
    def test_one_short_instance_is_red_and_named(self):
        self.set_instances([self.add_instance("level", 5), self.add_instance("laggard", 2)])
        code, out = self.run_check()
        self.assertEqual(code, 2, out)
        self.assertIn("SHORT   laggard: 2 lessons, 3 missing", out)
        self.assertIn("RED", out)

    def test_surplus_is_reported_but_not_red_by_default(self):
        self.set_instances([self.add_instance("ahead", 8)])
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("surplus ahead: 8 lessons, 3", out)

    def test_surplus_is_red_under_strict(self):
        self.set_instances([self.add_instance("ahead", 8)])
        code, out = self.run_check("--strict")
        self.assertEqual(code, 2, out)
        self.assertIn("--strict", out)

    # --- log and streak -------------------------------------------------
    def test_propagate_failed_in_newest_block_is_red(self):
        self.set_instances([self.add_instance("a", 5)])
        self.log.write_text(CLEAN_LOG + "lessons publish: ok\npropagate FAILED\n",
                            encoding="utf-8")
        code, out = self.run_check()
        self.assertEqual(code, 2, out)
        self.assertIn("propagate FAILED", out)

    def test_propagate_failed_in_an_older_block_only_is_green(self):
        # Guards the newest-block split against degenerating into a whole-file
        # substring search, which would stay red forever after one bad night.
        self.set_instances([self.add_instance("a", 5)])
        self.log.write_text("lessons publish: ok\npropagate FAILED\n" + CLEAN_LOG,
                            encoding="utf-8")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)

    def test_missing_log_is_red_not_silent(self):
        self.set_instances([self.add_instance("a", 5)])
        self.log.unlink()
        code, out = self.run_check()
        self.assertEqual(code, 2, out)
        self.assertIn("COULD NOT READ", out)

    def test_missing_streak_file_is_red(self):
        self.set_instances([self.add_instance("a", 5)])
        self.streak.unlink()
        code, out = self.run_check()
        self.assertEqual(code, 2, out)
        self.assertIn("streak", out)

    # --- registry hygiene is somebody else's issue ----------------------
    def test_dead_registry_path_is_reported_not_red(self):
        self.set_instances([self.add_instance("a", 5),
                            self.add_instance("gone", None, make_dir=False)])
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("dead path (ASK-3404, not red) gone", out)

    def test_live_instance_with_no_lessons_dir_is_red(self):
        self.set_instances([self.add_instance("empty", None)])
        code, out = self.run_check()
        self.assertEqual(code, 2, out)
        self.assertIn("NO CORPUS empty", out)

    # --- the check itself failing ---------------------------------------
    def test_unreadable_skeleton_corpus_exits_one(self):
        self.set_instances([])
        code, out = self.run_check("--skeleton", str(self.base / "nope"))
        self.assertEqual(code, 1, out)
        self.assertIn("COULD NOT READ", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
