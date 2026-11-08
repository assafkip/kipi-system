"""The reviewer's measurement seams (ASK-4038) can never reach a posted verdict.

Why they exist: to measure a model as the reviewer, the eval re-reviews old PRs
with an explicit model, and writes its rounds somewhere other than the live
record dir. Those live round files and verdict records ARE the history the
routing table is measured from; an eval round written there adds a round to a
merged PR and overwrites its record.

Why the refusals: a posted verdict gates a merge. If --model could ride along
with --post, the table would stop deciding who reviews; if the record dir could
move under --post, converge would read a record that is not there.

Every case here exits at the seam check, before any gh or model call; `gh` and
`claude` are stubs on a sealed PATH so a regression cannot reach either.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
AGENT = SCRIPTS / "pr-review-agent.sh"
SEAM = "REFUSING: --model and KIPI_REVIEW_OUT_DIR are measurement seams"


class Seams(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        stub = Path(self.d.name) / "bin"
        stub.mkdir()
        for name in ("gh", "claude"):
            (stub / name).write_text("#!/bin/sh\necho STUB-CALLED >&2\nexit 1\n")
            (stub / name).chmod(0o755)
        self.env = {**os.environ, "PATH": f"{stub}:/usr/bin:/bin:/opt/homebrew/bin",
                    "KIPI_NOTIFY": "/usr/bin/true"}
        self.env.pop("KIPI_REVIEW_OUT_DIR", None)

    def tearDown(self):
        self.d.cleanup()

    def run_agent(self, *args, **env):
        e = {**self.env, **env}
        return subprocess.run(["bash", str(AGENT), "999999", *args], capture_output=True, text=True,
                              env=e, timeout=60)

    def test_model_with_post_is_refused_before_any_call(self):
        r = self.run_agent("--post", "--model", "claude-sonnet-5-5")
        self.assertEqual(r.returncode, 2)
        self.assertIn(SEAM, r.stderr)
        self.assertNotIn("STUB-CALLED", r.stderr)

    def test_out_dir_with_post_is_refused_before_any_call(self):
        r = self.run_agent("--post", KIPI_REVIEW_OUT_DIR=self.d.name)
        self.assertEqual(r.returncode, 2)
        self.assertIn(SEAM, r.stderr)
        self.assertNotIn("STUB-CALLED", r.stderr)

    def test_unknown_model_is_refused(self):
        r = self.run_agent("--model", "claude-bogus-9")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not in the routing table's known_models", r.stderr)

    def test_negative_self_test_a_dry_known_model_passes_the_seam(self):
        # the refusals above must be the seam, not a script that refuses everything
        r = self.run_agent("--model", "claude-sonnet-5-5", KIPI_REVIEW_OUT_DIR=self.d.name)
        self.assertNotIn(SEAM, r.stderr)
        self.assertNotIn("known_models", r.stderr)

    def test_the_explicit_model_wins_over_the_routed_one(self):
        text = AGENT.read_text()
        routed = text.index('[ -n "$_ROUTED" ] && CLAUDE_MODEL="$_ROUTED"')
        explicit = text.index('[ -n "$MODEL_ARG" ] && CLAUDE_MODEL="$MODEL_ARG"')
        self.assertLess(routed, explicit)
        self.assertIn('OUT_DIR="${KIPI_REVIEW_OUT_DIR:-$HOME/.config/kipi/pr-reviews}"', text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
