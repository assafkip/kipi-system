"""The model-eval harness (ASK-4038) re-measures the routing table; these are its
pure parts, pinned so a re-run reads results the same way the first run did.

Why it is in the repo: PR #664's first review found that nothing could
re-measure the table, so its Sonnet bar could never be met. The harness writes
only under $KIPI_EVAL_DIR (default ~/.config/kipi/eval), never into this tree,
and its PR and ticket lists live there too: this repo is public.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

QS = Path(__file__).resolve().parents[1]
HARNESS = QS / "model-eval"

_TMP = tempfile.TemporaryDirectory()
os.environ["KIPI_EVAL_DIR"] = _TMP.name
Path(_TMP.name, "part1-config.json").write_text(json.dumps({"local": {"r": "~/x"}, "pick": [["r", 1]]}))
Path(_TMP.name, "part2-config.json").write_text(json.dumps({"local": {"r": "~/x"}, "tickets": [["test-only", "r", 1, "ASK-1"]]}))
sys.path.insert(0, str(HARNESS))
import part1_run  # noqa: E402
import part2_run  # noqa: E402
import score_part1  # noqa: E402

REVIEW = """Body text.

**VERDICT: REQUEST CHANGES** the first thing to fix.

FINDINGS:
major|the lock is not exclusive|a/b.sh:10
major|the cap never fires|a/c.py:22|nonblocking
nit|typo|a/d.md:1
END FINDINGS
"""


class Harness(unittest.TestCase):
    def test_results_and_lists_live_outside_the_repo(self):
        self.assertEqual(part1_run.EVAL, _TMP.name)
        self.assertEqual(part2_run.EVAL, _TMP.name)
        self.assertEqual(part1_run.PICK, [("r", 1)])
        for f in HARNESS.glob("*.py"):
            self.assertNotIn("/Users/", f.read_text(), f.name)

    def test_findings_parse_severity_nonblocking_and_verdict(self):
        rows, verdict, ok = part2_run.findings(REVIEW)
        self.assertTrue(ok)
        self.assertEqual(verdict, "REQUEST CHANGES")
        self.assertEqual([(r["sev"], r["nonblocking"]) for r in rows], [("major", False), ("major", True), ("nit", False)])
        md = Path(_TMP.name, "r.md")
        md.write_text(REVIEW)
        self.assertEqual(len(part1_run.findings(str(md))[0]), 3)

    def test_negative_a_review_without_a_block_is_not_findings(self):
        rows, verdict, ok = part2_run.findings("I could not review this PR.\n")
        self.assertEqual((rows, verdict, ok), ([], None, False))

    def test_the_judge_prompt_is_blind(self):
        template = ("You were asked to review pull request #664 in /h/.config/kipi/review-trees/x__pr-664, and\n"
                    "  /h/.config/kipi/review-scratch/ctx.AbC/pr.txt     (gh -R assafkip/kipi-system pr view 664)\n"
                    "  /h/.config/kipi/review-scratch/ctx.AbC/pr.diff    (gh -R assafkip/kipi-system pr diff 664)\n")
        p = part2_run.judge_prompt(template, "kipi-system", "/t/eval-0001", "/e/ctx/eval-0001")
        self.assertIn("#0 in /t/eval-0001,", p)
        self.assertNotIn("664", p)
        for word in ("sonnet", "opus", "sana/"):
            self.assertNotIn(word, p.lower())

    def test_a_catch_is_the_same_file_near_the_same_line(self):
        o = {"claim": "the lock is not exclusive", "loc": "a/b.sh:10"}
        self.assertEqual(score_part1.same(o, {"claim": "x", "loc": "a/b.sh:25"}), 1.0)
        self.assertEqual(score_part1.same(o, {"claim": "the lock is not exclusive", "loc": "z/q.py:10"}), 0.0)

    def test_part3_forces_the_arm_model_into_every_lean_call(self):
        code = ("import sys, subprocess; sys.path.insert(0, %r); import part3_run as p, lean_call\n"
                "seen = {}\n"
                "lean_call.subprocess.run = lambda argv, **k: seen.setdefault('a', argv) or subprocess.CompletedProcess(argv, 0, '', '')\n"
                "p.FORCE['model'] = 'claude-sonnet-5-5'\n"
                "lean_call.run(['claude', '-p', 'x'])\n"
                "a = seen['a']; print(a[a.index('--model') + 1])\n") % str(HARNESS)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env={**os.environ, "KIPI_EVAL_DIR": _TMP.name}, timeout=60)
        self.assertEqual(r.stdout.strip(), "claude-sonnet-5-5", r.stderr[-500:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
