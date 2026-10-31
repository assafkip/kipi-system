#!/usr/bin/env python3
"""Tests for lessons-fanout-check.py (ASK-3574).

Every fixture is built in a fresh tmpdir. The suite never reads the live
skeleton, the live registry, the live log or the live streak file: all five are
passed in through the script's own seam flags, so a green run here says nothing
about the real fleet and a broken fleet cannot turn this suite red.

The one exception is deliberate and is the point of the last class: the REAL
`lessons-daily.sh` is read to prove the producer still writes the marker this
checker derives. Those two have to agree or the log cannot be split, and a test
that asserts a hand-typed marker string would agree with itself forever.
"""

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE / "lessons-fanout-check.py"
PRODUCER = HERE / "lessons-daily.sh"
MARKER = "=== lessons-daily run ==="
# PRODUCER-SHAPED, not invented. With an origin, lessons-daily.sh writes the run
# marker, then "jobs:", then the fan-out verdict, then "slacked:". It does NOT
# write "lessons publish:" -- that string lives only in its no-origin DISARMED
# branch, which is exactly how the old split degenerated (PR #584 finding 1).
def run_block(marker: str, verdict: str, day: str) -> str:
    return (f"{day}T06:00:00+0000 {marker}\n"
            f"{day}T06:00:01+0000 jobs: nothing to arm\n"
            f"{day}T06:00:02+0000 {verdict}\n"
            f"{day}T06:00:05+0000 slacked: Fleet learning ({day})\n")


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
        self.producer = self.base / "lessons-daily.sh"
        self.set_producer_marker(MARKER)
        self.log = self.base / "lessons-daily.log"
        self.log.write_text(run_block(MARKER, "propagated to fleet", "2026-10-22"),
                            encoding="utf-8")
        self.streak = self.base / "streak.json"
        self.streak.write_text(json.dumps({"streak": 0}), encoding="utf-8")
        self.registry = self.base / "registry.json"

    def tearDown(self):
        self.tmp.cleanup()

    def set_producer_marker(self, marker):
        body = "#!/bin/bash\nset -uo pipefail\n"
        if marker is not None:
            body += f'KIPI_FANOUT_RUN_MARKER="{marker}"\necho "$KIPI_FANOUT_RUN_MARKER"\n'
        self.producer.write_text(body, encoding="utf-8")

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
             "--streak", str(self.streak),
             "--producer", str(self.producer), *extra],
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
        self.log.write_text(run_block(MARKER, "propagate FAILED", "2026-10-22"),
                            encoding="utf-8")
        code, out = self.run_check()
        self.assertEqual(code, 2, out)
        self.assertIn("propagate FAILED", out)

    def test_stale_failure_in_an_older_producer_shaped_block_is_green(self):
        # PR #584 review finding 1, as a reproducer. Observed RED before the fix:
        # the 2026-10-01 failure was reported as "in the newest run block" while
        # the newest block said "propagated to fleet", because the old marker
        # never appears in a real log and the split returned the whole file.
        self.set_instances([self.add_instance("a", 5)])
        self.log.write_text(
            run_block(MARKER, "propagate FAILED", "2026-10-01")
            + run_block(MARKER, "propagated to fleet", "2026-10-22"),
            encoding="utf-8")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("propagate FAILED in the newest", out)

    def test_marker_absent_from_the_log_is_red_not_a_whole_file_search(self):
        # The degenerate case itself: a log with no marker must refuse to judge,
        # never fall back to searching every run ever written.
        self.set_instances([self.add_instance("a", 5)])
        self.log.write_text("2026-10-01T06:00:01+0000 propagate FAILED\n"
                            "2026-10-22T06:00:02+0000 propagated to fleet\n",
                            encoding="utf-8")
        code, out = self.run_check()
        self.assertEqual(code, 2, out)
        self.assertIn("no run marker", out)

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

    # --- the derivation, and its floor ----------------------------------
    def test_missing_producer_is_red(self):
        self.set_instances([self.add_instance("a", 5)])
        self.producer.unlink()
        code, out = self.run_check()
        self.assertEqual(code, 2, out)
        self.assertIn("COULD NOT READ the producer", out)

    def test_producer_without_the_assignment_is_red(self):
        self.set_instances([self.add_instance("a", 5)])
        self.set_producer_marker(None)
        code, out = self.run_check()
        self.assertEqual(code, 2, out)
        self.assertIn("KIPI_FANOUT_RUN_MARKER", out)

    def test_the_split_follows_the_producer_when_the_marker_changes(self):
        # Mutate the source of truth and confirm the check changes its answer.
        # Without this the derivation could be reading nothing and every case
        # above would still pass (lesson: derive-a-value-from-its-owner).
        self.set_instances([self.add_instance("a", 5)])
        renamed = "### other run banner ###"
        self.set_producer_marker(renamed)
        self.log.write_text(
            run_block(renamed, "propagate FAILED", "2026-10-01")
            + run_block(renamed, "propagated to fleet", "2026-10-22"),
            encoding="utf-8")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        # The OLD marker is now the one that cannot split this log.
        self.set_producer_marker(MARKER)
        code, out = self.run_check()
        self.assertEqual(code, 2, out)
        self.assertIn("no run marker", out)

    # --- counts-only, the in-run caller's mode ---------------------------
    def test_counts_only_ignores_the_log_and_the_streak(self):
        # lessons-daily.sh owns both while it runs; re-reading them there would
        # be a second reader of one input with different semantics.
        self.set_instances([self.add_instance("a", 5)])
        self.log.unlink()
        self.streak.unlink()
        self.producer.unlink()
        code, out = self.run_check("--counts-only")
        self.assertEqual(code, 0, out)
        self.assertNotIn("log:", out)
        self.assertNotIn("streak:", out)

    def test_counts_only_still_reds_on_a_short_instance(self):
        self.set_instances([self.add_instance("laggard", 2)])
        code, out = self.run_check("--counts-only")
        self.assertEqual(code, 2, out)
        self.assertIn("1 instance(s) short", out)

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

    def test_registry_row_with_no_path_is_red_not_counted_from_the_cwd(self):
        # PR #584 review finding 3. Observed before the fix, run from the repo
        # root: "surplus nopath: 205 lessons" -- Path("") is the cwd, so the row
        # was classified from whatever corpus the caller stood in.
        self.set_instances([self.add_instance("a", 5), {"name": "nopath"}])
        code, out = self.run_check()
        self.assertEqual(code, 2, out)
        self.assertIn("MALFORMED ROW nopath", out)
        self.assertNotIn("surplus nopath", out)
        self.assertNotIn("level with skeleton: 2", out)

    def test_registry_row_with_a_blank_path_is_red_too(self):
        self.set_instances([self.add_instance("a", 5), {"name": "blank", "path": "  "}])
        code, out = self.run_check()
        self.assertEqual(code, 2, out)
        self.assertIn("MALFORMED ROW blank", out)

    # --- the check itself failing ---------------------------------------
    def test_unreadable_skeleton_corpus_exits_one(self):
        self.set_instances([])
        code, out = self.run_check("--skeleton", str(self.base / "nope"))
        self.assertEqual(code, 1, out)
        self.assertIn("COULD NOT READ", out)


class ProducerAgreesCase(unittest.TestCase):
    """The two sides of the marker, read from the real files.

    A hand-typed expectation here would agree with itself forever; what matters
    is that the shipping producer declares the marker AND echoes it, and that
    the checker's own regex is what reads that declaration.
    """

    def test_producer_declares_and_echoes_the_run_marker(self):
        text = PRODUCER.read_text(encoding="utf-8")
        self.assertIn('KIPI_FANOUT_RUN_MARKER="', text,
                      "lessons-daily.sh no longer declares the run marker")
        self.assertIn('echo "$(TS) $KIPI_FANOUT_RUN_MARKER" >> "$LOG"', text,
                      "lessons-daily.sh declares the marker but never writes it")

    def test_the_checker_derives_that_declaration_from_the_producer(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("fanout_check", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        marker, why = mod.producer_run_marker(PRODUCER)
        self.assertIsNotNone(marker, why)
        self.assertTrue(marker.strip(), "derived an empty run marker")

    def test_producer_calls_the_check_and_exits_nonzero_on_a_disagreement(self):
        text = PRODUCER.read_text(encoding="utf-8")
        self.assertIn("lessons-fanout-check.py", text,
                      "lessons-daily.sh has no caller for the fan-out count check")
        self.assertIn("--counts-only", text)
        self.assertIn('if [ -n "$FANOUT_SHORT" ]; then', text,
                      "a count disagreement no longer changes the run's exit code")


if __name__ == "__main__":
    unittest.main(verbosity=2)
