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


class OneTestFileMayCoverManyEngines(unittest.TestCase):
    """The scar from PR #164 round 2, kept as an executable guard.

    Tightening has_test from a substring to an EXACT stem match looks obviously
    right and is wrong. plugins/kipi-core/voiceloop/echo.py is genuinely tested by
    voiceloop/tests/test_voiceloop.py, which imports echo and exercises
    echo.prompt_echo and echo.opener_echo. That file's stem is "voiceloop", not
    "echo", so exact matching flipped a real, covered engine to UNWIRED -- a
    false alarm eligible for a permanent Linear issue, which is worse than the
    false LIVE it replaced.

    One test file legitimately covers several engines. Filename equality can
    never be the rule; the content reference is the real signal (ASK-810).
    """

    def setUp(self):
        if not SCRIPT.exists():
            self.skipTest(f"no capability-map-gen.py at {SCRIPT}")

    def test_the_substring_match_is_still_in_place(self):
        src = SCRIPT.read_text()
        self.assertIn("has_test = any(p.stem in t for t in tests)", src,
                      "the exact-stem match was reintroduced; it flips voiceloop/echo.py to UNWIRED")

    def test_markdown_fixtures_are_still_excluded(self):
        # The half of the fix that WAS correct: a document is not a test.
        src = SCRIPT.read_text()
        self.assertIn("TEST_SUFFIXES", src)
        self.assertIn("p.suffix in TEST_SUFFIXES", src)

    def test_the_real_world_case_this_protects_still_exists(self):
        # If voiceloop's test stops importing echo, this guard is stale and should
        # be re-derived rather than trusted.
        root = SCRIPT.parents[3]
        t = root / "plugins" / "kipi-core" / "voiceloop" / "tests" / "test_voiceloop.py"
        if not t.exists():
            self.skipTest("voiceloop tests not present in this checkout")
        body = t.read_text()
        self.assertIn("echo", body,
                      "the engine this scar is about is no longer covered there")


if __name__ == "__main__":
    unittest.main(verbosity=2)
