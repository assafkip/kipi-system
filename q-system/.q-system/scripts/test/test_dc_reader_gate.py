#!/usr/bin/env python3
"""dc-06: design-reader-gate.py lives in the skeleton, shoots the served page itself, and every
row carries the HTML and PNG shas and a provenance block.

WHY. The only reader gate lived in one instance (consulting's gate_icp.py) and read PNGs the round
supplied, so the readers could be shown a screenshot of a page other than the one being sealed,
and nothing on a row said which page bytes or which image the answers were about. Here the script
renders every page itself from the served round, at the configured viewports, hashes both, and
never opens a PNG from the round.

The REAL script at its tracked path with real playwright; the model call is the injected runner,
so no test spends one. The real-model run is recorded once in the closeout (Sana, 2026-09-19).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "design-reader-gate.py"
PAGE = ("<!doctype html><html><head><meta charset='utf-8'><style>body{font:18px/1.6 Georgia,serif;"
        "margin:48px;color:#1a1a1a}</style></head><body><h1>Two records that should agree</h1>"
        "<p>A small firm retypes the same client data into three systems.</p>"
        "<p><a href='#book'>Book a 30-minute call</a></p></body></html>")
ANSWERS = ["yes, retyping", "workflow fixes", "fewer errors", "the example", "a week of fixes",
           "ops consultant", "STAY: clear", "nothing", "STAY", "ops consulting", "unknown"]


LABELS = ["ops consulting", "data cleanup"]


def keyed(answers):
    return {str(i + 1): a for i, a in enumerate(answers)}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        try:
            import playwright  # noqa: F401
        except ImportError:
            msg = "playwright is not installed: the PRODUCTION path was NOT exercised"
            if os.environ.get("DC_REQUIRE_REAL_PRODUCERS") == "1":
                self.fail(msg)
            self.skipTest(msg)
        self.tmp = Path(tempfile.mkdtemp(prefix="dc06-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inst = self.tmp / "inst"
        self.rd = self.inst / "site" / "design" / "r1"
        self.rd.mkdir(parents=True)
        self.page = self.rd / "Home-laptop.html"
        self.page.write_bytes(PAGE.encode())
        (self.inst / "canonical").mkdir()
        self.persona = self.inst / "canonical" / "persona.md"
        self.persona.write_text("You run a small tax practice. You are paid to be accurate.\n")
        self.config()
        self.answers = self.tmp / "answers.json"
        self.answers.write_text(json.dumps(keyed(ANSWERS)))
        self.keep = self.tmp / "screens"

    def config(self, **readers):
        (self.inst / "design-chain.json").write_text(json.dumps({"project": "dc06", "owners": [], "readers": {
            "persona_file": "canonical/persona.md", "n": 1, "labels": LABELS, **readers}}))

    def run_gate(self, *extra, env=None, runner="injected"):
        e = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        e.update(env or {})
        args = [sys.executable, str(SCRIPT), str(self.rd),
                "--config", str(self.inst / "design-chain.json"), "--runner", runner,
                "--keep-screens", str(self.keep)]
        if runner == "injected":
            args += ["--answers", str(self.answers)]
        r = subprocess.run(args + list(extra), capture_output=True, text=True, env=e, timeout=300)
        return r.returncode, r.stdout + r.stderr

    def rows(self):
        return [json.loads(l) for l in (self.rd / "gate" / "reader-runs.jsonl").read_text().splitlines()]


class ReaderGate(Base):
    def test_every_row_carries_the_page_sha_the_screenshot_sha_and_provenance(self):
        rc, out = self.run_gate()
        self.assertEqual(rc, 0, out)
        rows = self.rows()
        self.assertEqual(len(rows), 1, rows)
        r = rows[0]
        self.assertEqual(r["page"], "Home-laptop.html")
        self.assertEqual(r["html_sha256"], sha(PAGE.encode()))
        shots = sorted(self.keep.glob("*.png"))
        self.assertEqual(len(shots), 1, shots)
        self.assertEqual(r["png_sha256"], sha(shots[0].read_bytes()))
        self.assertEqual(r["answers"], ANSWERS)
        p = r["_provenance"]
        self.assertEqual(p["runner"], "injected")
        self.assertEqual(p["model"], "injected")
        self.assertEqual(p["persona_sha256"], sha(self.persona.read_bytes()))
        self.assertTrue(p["at"])

    def test_it_never_reads_a_png_the_round_supplied(self):
        decoy = self.rd / "Home-laptop.png"
        decoy.write_bytes(b"\x89PNG\r\n\x1a\n decoy the builder supplied")
        rc, out = self.run_gate()
        self.assertEqual(rc, 0, out)
        r = self.rows()[0]
        self.assertNotEqual(r["png_sha256"], sha(decoy.read_bytes()))
        self.assertEqual(r["png_sha256"], sha(next(self.keep.glob("*.png")).read_bytes()))

    def test_one_row_per_configured_viewport_each_with_its_own_screenshot(self):
        self.config(viewports=[[1440, 900], [390, 844]])
        rc, out = self.run_gate()
        self.assertEqual(rc, 0, out)
        rows = self.rows()
        self.assertEqual(sorted(tuple(r["viewport"]) for r in rows), [(390, 844), (1440, 900)])
        self.assertEqual(len({r["png_sha256"] for r in rows}), 2)

    # served-bytes check: replaced by the script serving the round itself (ASK-1836,
    # test_dc_reader_gate_serves_itself.py)

    def test_the_real_model_is_never_called_from_a_test(self):
        # PYTEST_CURRENT_TEST is how a test run is recognised; the claude runner refuses under it
        rc, out = self.run_gate(runner="claude", env={"PYTEST_CURRENT_TEST": "test_dc_reader_gate.py::x"})
        self.assertEqual(rc, 2, out)
        self.assertIn("refusing to call a model from a test", out)
        self.assertFalse((self.rd / "gate" / "reader-runs.jsonl").exists())

    def test_a_persona_file_that_is_missing_refuses(self):
        self.persona.unlink()
        rc, out = self.run_gate()
        self.assertEqual(rc, 2, out)
        self.assertIn("persona", out)


FAKE_CLAUDE = r"""#!/usr/bin/env python3
import json, os, sys
open(os.environ["FAKE_LOG"], "a").write(json.dumps(sys.argv[1:]) + "\n")
answers = json.loads(os.environ.get("FAKE_ANSWERS", "[]"))
answers = {str(i + 1): a for i, a in enumerate(answers)}
print(json.dumps({"result": json.dumps({"answers": answers}),
                  "modelUsage": {os.environ.get("FAKE_MODEL", "claude-haiku-4-5"): {}}}))
"""


class ReviewOfC911e33f(Base):
    """Sana's triage of dc-06's reviews (adv-2..5, std-7, std-8). No real model: a fake `claude`
    on PATH records every call, so even the pre-fix script cannot spend one here."""

    def fake(self, answers=ANSWERS, model="claude-haiku-4-5"):
        bin_ = self.tmp / "bin"
        bin_.mkdir(exist_ok=True)
        f = bin_ / "claude"
        f.write_text(FAKE_CLAUDE)
        f.chmod(0o755)
        self.log = self.tmp / "fake.log"
        return {"PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_LOG": str(self.log),
                "FAKE_ANSWERS": json.dumps(answers), "FAKE_MODEL": model}

    def run_bare(self, *args, env=None):
        e = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "PYTEST_CURRENT_TEST")}
        e.update(env or {})
        base = [sys.executable, str(SCRIPT), str(self.rd),
                "--config", str(self.inst / "design-chain.json")]
        r = subprocess.run(base + list(args), capture_output=True, text=True, env=e, timeout=300)
        return r.returncode, r.stdout + r.stderr

    def calls(self):
        return self.log.read_text().splitlines() if self.log.is_file() else []

    def test_a_reader_with_the_wrong_number_of_answers_refuses(self):
        self.answers.write_text(json.dumps({"1": "unknown"}))
        rc, out = self.run_gate()
        self.assertEqual(rc, 2, out)
        self.assertIn("answers not keyed exactly 1..11", out)

    def test_the_control_passes_only_when_the_answer_starts_with_unknown(self):
        for control, contaminated in (("Unknown. Not on the page.", False),
                                      ("Stanford, though his school is not unknown to me", True)):
            with self.subTest(control=control):
                self.answers.write_text(json.dumps(keyed(ANSWERS[:-1] + [control])))
                rc, out = self.run_gate()
                self.assertEqual(rc, 0, out)
                self.assertIs(self.rows()[0]["contaminated"], contaminated)

    def test_no_runner_named_is_refused_before_any_model_call(self):
        rc, out = self.run_bare(env=self.fake())
        self.assertEqual(rc, 2, out)
        self.assertIn("--runner", out)
        self.assertEqual(self.calls(), [], "a model was called with no runner named")

    def test_the_row_names_the_model_that_answered_and_a_different_one_refuses(self):
        rc, out = self.run_bare("--runner", "claude", env=self.fake())
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.rows()[0]["_provenance"]["model_reported"], ["claude-haiku-4-5"])
        rc, out = self.run_bare("--runner", "claude", env=self.fake(model="some-other-model"))
        self.assertEqual(rc, 2, out)
        self.assertIn("some-other-model", out)

    def test_a_page_outside_the_round_is_refused(self):
        (self.rd.parent / "outside.html").write_text(PAGE)
        for page in ("../outside.html", str(self.rd.parent / "outside.html")):
            with self.subTest(page=page):
                rc, out = self.run_gate("--page", page)
                self.assertEqual(rc, 2, out)
                self.assertIn("not a page in the round", out)

    def test_a_persona_file_outside_the_config_dir_is_refused(self):
        (self.tmp / "elsewhere.md").write_text("persona\n")
        for pf in ("../elsewhere.md", str(self.tmp / "elsewhere.md")):
            with self.subTest(persona_file=pf):
                self.config(persona_file=pf)
                rc, out = self.run_gate()
                self.assertEqual(rc, 2, out)
                self.assertIn("persona_file", out)

    def test_questions_come_from_config_and_the_default_is_not_personal(self):
        qs = ["What is this page for?", "Would you stay or leave?", "CONTROL: What year was it founded?"]
        self.config(questions=qs)
        import importlib.util
        spec = importlib.util.spec_from_file_location("drg", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        FULL = mod.full_questions({"questions": qs, "labels": LABELS})
        self.assertEqual(len(FULL), 5)
        self.answers.write_text(json.dumps(keyed(["a tool", "STAY", "STAY", "ops consulting", "unknown"])))
        rc, out = self.run_gate()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.rows()[0]["_provenance"]["questions_sha256"], sha(json.dumps(FULL).encode()))
        words = " ".join(mod.QUESTIONS).lower().replace("?", " ").replace(",", " ").split()
        self.assertFalse({"he", "him", "his", "she", "her"} & set(words), mod.QUESTIONS)


class KeyedAnswersAndRetries(Base):
    """A real reader skipped or merged a question in 2 of 5 real calls on 2026-09-19. Answers are
    keyed by question number, a wrong key set is retried, and nothing else is (Sana)."""

    def responses(self, *resps):
        self.answers.write_text(json.dumps({"responses": list(resps)}))

    def test_a_missing_key_is_retried_and_the_retry_is_recorded(self):
        short = keyed(ANSWERS)
        del short["5"]
        self.responses(short, keyed(ANSWERS))
        rc, out = self.run_gate()
        self.assertEqual(rc, 0, out)
        r = self.rows()[0]
        self.assertEqual(r["_provenance"]["attempts"], 2)
        self.assertEqual(r["answers"], ANSWERS)

    def test_a_missing_key_on_every_attempt_refuses(self):
        short = keyed(ANSWERS)
        del short["9"]
        self.responses(short, short, short, keyed(ANSWERS))
        rc, out = self.run_gate()
        self.assertEqual(rc, 2, out)
        self.assertIn("3 attempts", out)

    def test_the_right_number_of_answers_under_the_wrong_keys_refuses(self):
        # eleven answers keyed 0..10: a count check passes it, the key check must not
        shifted = {str(i): a for i, a in enumerate(ANSWERS)}
        self.responses(shifted)
        rc, out = self.run_gate()
        self.assertEqual(rc, 2, out)
        self.assertIn("answers not keyed exactly 1..11", out)

    def test_an_answer_that_is_not_text_is_a_wrong_shape(self):
        # review of 2d342634: {"9": null} passed the key check and was stored as the text "None"
        for bad in (None, 7, ["unknown"], {"note": "unknown"}):
            with self.subTest(value=bad):
                broken = keyed(ANSWERS)
                broken["9"] = bad
                self.responses(broken)
                rc, out = self.run_gate()
                self.assertEqual(rc, 2, out)
                self.assertIn("3 attempts", out)

    def test_an_answer_the_run_dislikes_is_never_retried(self):
        leave = keyed(ANSWERS[:6] + ["LEAVE: generic", "everything", "LEAVE", "data cleanup", "Stanford"])
        self.responses(leave, keyed(ANSWERS))
        rc, out = self.run_gate()
        self.assertEqual(rc, 0, out)
        r = self.rows()[0]
        self.assertEqual(r["_provenance"]["attempts"], 1)
        self.assertTrue(r["contaminated"])
        self.assertEqual(r["answers"][6], "LEAVE: generic")


if __name__ == "__main__":
    unittest.main()
