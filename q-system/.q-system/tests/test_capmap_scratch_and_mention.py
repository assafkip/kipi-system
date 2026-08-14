#!/usr/bin/env python3
"""A committed scratch tree is not a capability, and a mention is not a test.

Both reproducers are for codex majors raised on PR #122 round 4 against
capability-map-gen.py (a file that PR does not touch -- captured as sp-5e33aebc
and sp-7b7a1c72, fixed here).

1. SCRATCH_DIR_RE knew `.prNNrev` but not `.review-scratch/` or `.review-tmp-*`,
   which are COMMITTED: `git ls-files` returns 20 tracked files under them,
   including whole copies of linear-worker.sh and linear-claim.py. Every copy was
   walked as a live surface and emitted as its own capability, eligible to sync a
   DUPLICATE permanent Linear issue for a script that already has one. Being
   committed is what hid them from this rule and from a dirty-tree check alike.

2. `tests` collected any file NAMED test*, extension included, and `has_test`
   asked whether the engine stem appeared as a SUBSTRING of one. So a Markdown
   fixture certified a script as tested, and `_sync_all` inherited
   `test_sync_all_helpers.md`.
"""
import importlib.util
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve()
SCRIPT = HERE.parents[1] / "scripts" / "capability-map-gen.py"


def load():
    spec = importlib.util.spec_from_file_location("capability_map_gen", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ScratchTreesAreNotCapabilities(unittest.TestCase):
    def setUp(self):
        if not SCRIPT.exists():
            self.skipTest(f"no capability-map-gen.py at {SCRIPT}")
        self.m = load()

    def test_committed_review_scratch_is_excluded(self):
        self.assertTrue(self.m._is_excluded_part(".review-scratch"),
                        "a COMMITTED .review-scratch tree is walked as live wiring")

    def test_review_tmp_prefix_is_excluded(self):
        self.assertTrue(self.m._is_excluded_part(".review-tmp-pr11"))

    def test_the_other_scratch_prefixes_stay_in_step_with_repo_preflight(self):
        # repo-preflight.sh's _shipping() already excludes exactly this set. Two
        # scratch definitions that disagree is the defect this file keeps
        # rediscovering (sp-505140ae was the same shape one file over).
        for part in (".pr31rev", ".wt-ask741", ".fable-wt", ".sana-tmp", "worktrees"):
            self.assertTrue(self.m._is_excluded_part(part), f"{part} not excluded")

    def test_primary_wiring_dirs_are_NOT_excluded(self):
        # THE NEGATIVE SELF-TEST. A bare leading-dot rule would pass every
        # assertion above and destroy the map -- .claude/ and .q-system/ are this
        # fleet's primary wiring locations.
        for part in (".claude", ".q-system", "plugins", "scripts", "hooks"):
            self.assertFalse(self.m._is_excluded_part(part),
                             f"{part} is a real wiring surface and must not be excluded")


class AMentionIsNotAPairing(unittest.TestCase):
    def setUp(self):
        if not SCRIPT.exists():
            self.skipTest(f"no capability-map-gen.py at {SCRIPT}")
        self.m = load()

    def test_a_real_paired_test_still_counts(self):
        # Guarding the fix against being its own bug: tighten too far and every
        # engine reads UNWIRED.
        self.assertTrue(self.m._names_this_engine("_sync_all", "test_sync_all.py"))
        self.assertTrue(self.m._names_this_engine("linear-worker", "test-linear-worker.sh"))

    def test_a_longer_name_does_not_adopt_a_shorter_engines_test(self):
        self.assertFalse(
            self.m._names_this_engine("_sync_all", "test_sync_all_helpers.py"),
            "an engine inherited a neighbour's test by substring match")

    def test_markdown_fixtures_are_not_collected_as_tests(self):
        # The suffix filter is what stops a document from certifying a script.
        src = SCRIPT.read_text()
        self.assertIn("TEST_SUFFIXES", src)
        self.assertIn('p.suffix in TEST_SUFFIXES', src,
                      "the tests set no longer filters by executable extension")


if __name__ == "__main__":
    unittest.main(verbosity=2)
