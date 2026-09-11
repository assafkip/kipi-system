#!/usr/bin/env python3
"""Tests for audhd-output-eval.py (H2 output-quality harness).

All stubs and tempfiles; zero model calls, zero live data paths. The two
properties that MUST be provable red (lesson: a-check-must-be-able-to-fail):
the release gate fails on a correctness regression, and the judge prompt
never leaks a condition name (unblinding input exists in test_blind_leak).
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE_PATH = os.path.join(HERE, "..", "audhd-output-eval.py")
spec = importlib.util.spec_from_file_location("audhd_output_eval", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def scores(c=4, a=4, act=4, s=4, con=4):
    return {"correctness": c, "autonomy": a, "actionability": act,
            "safety": s, "concision": con}


def result(case_id, base, cand, base_block=False, cand_block=False):
    return {"case_id": case_id,
            "scores": {"baseline": base, "candidate": cand},
            "blocker": {"baseline": base_block, "candidate": cand_block}}


CASE = {"id": "c1", "category": "x", "prompt": "p", "risk": "low", "criteria": ["k"]}


class TestValidate(unittest.TestCase):
    def test_good_cases_pass(self):
        self.assertEqual(mod.validate_cases([CASE]), [])

    def test_missing_field_caught(self):
        bad = {k: v for k, v in CASE.items() if k != "criteria"}
        self.assertTrue(any("missing" in e for e in mod.validate_cases([bad])))

    def test_duplicate_id_caught(self):
        self.assertTrue(any("duplicate" in e for e in mod.validate_cases([CASE, dict(CASE)])))

    def test_bad_risk_caught(self):
        bad = dict(CASE, risk="extreme")
        self.assertTrue(any("risk" in e for e in mod.validate_cases([bad])))

    def test_empty_file_caught(self):
        self.assertTrue(mod.validate_cases([]))

    def test_shipped_case_file_is_valid(self):
        # The one live-path READ this suite makes, asserting on the shipped
        # fixture the harness will actually load. Read-only, never written.
        shipped = os.path.join(HERE, "..", "..", "skill-evals", "audhd-output-cases.json")
        self.assertEqual(mod.validate_cases(mod.load_cases(shipped)), [])


class TestBlind(unittest.TestCase):
    def test_labels_flip_by_parity(self):
        self.assertEqual(mod.blind_labels(0), ("baseline", "candidate"))
        self.assertEqual(mod.blind_labels(1), ("candidate", "baseline"))

    def test_blind_leak(self):
        # Unblinding input: if the prompt builder ever names a condition, this
        # goes red. The judge must see A/B only.
        prompt = mod.build_judge_prompt(CASE, "resp one", "resp two")
        self.assertNotIn("baseline", prompt.lower())
        self.assertNotIn("candidate", prompt.lower())
        self.assertIn("RESPONSE A:", prompt)
        self.assertIn("RESPONSE B:", prompt)


class TestGate(unittest.TestCase):
    def test_fails_on_correctness_regression(self):
        # Candidate wins the weighted total but drops correctness by 0.5:
        # the gate must FAIL. This is the negative self-test for the gate.
        rows = [result("c1", scores(c=4), scores(c=3.5, a=5, act=5, s=4, con=5))]
        passed, reasons = mod.gate(rows)
        self.assertFalse(passed)
        self.assertTrue(any("correctness regressed" in r for r in reasons))

    def test_fails_on_safety_regression(self):
        rows = [result("c1", scores(s=5), scores(c=5, a=5, act=5, s=4, con=5))]
        passed, reasons = mod.gate(rows)
        self.assertFalse(passed)
        self.assertTrue(any("safety regressed" in r for r in reasons))

    def test_fails_on_candidate_blocker(self):
        rows = [result("c1", scores(), scores(c=5, a=5, act=5, s=5, con=5), cand_block=True)]
        passed, reasons = mod.gate(rows)
        self.assertFalse(passed)
        self.assertTrue(any("blocker" in r for r in reasons))

    def test_fails_when_weighted_does_not_beat_baseline(self):
        rows = [result("c1", scores(), scores())]
        passed, reasons = mod.gate(rows)
        self.assertFalse(passed)
        self.assertTrue(any("does not beat" in r for r in reasons))

    def test_passes_when_candidate_better_within_tolerance(self):
        rows = [result("c1", scores(), scores(c=4, a=5, act=5, s=4, con=5)),
                result("c2", scores(), scores(c=4, a=4, act=5, s=4, con=4))]
        passed, reasons = mod.gate(rows)
        self.assertTrue(passed, reasons)

    def test_empty_results_fail(self):
        self.assertFalse(mod.gate([])[0])


class TestRunEvalStubbed(unittest.TestCase):
    def test_label_flip_maps_scores_back_to_conditions(self):
        # Two cases so both parities run. The judge stub scores the response
        # containing CANDTEXT higher; if the label-to-condition mapping is
        # wrong on either parity, the candidate score lands on baseline and
        # the assertions below go red.
        cases = [dict(CASE, id="c1"), dict(CASE, id="c2", prompt="q")]

        def respond(prompt, condition):
            return "CANDTEXT" if condition == "candidate" else "BASETEXT"

        def judge(judge_prompt):
            a_seg = judge_prompt.split("RESPONSE A:")[1].split("RESPONSE B:")[0]
            hi = json.dumps(scores(c=5, a=5, act=5, s=5, con=5))
            lo = json.dumps(scores(c=3, a=3, act=3, s=3, con=3))
            a_hi = "CANDTEXT" in a_seg
            return '{"A": %s, "B": %s}' % ((hi, lo) if a_hi else (lo, hi))

        results = mod.run_eval(cases, "style", respond=respond, judge=judge)
        self.assertEqual(len(results), 2)
        for row in results:
            self.assertEqual(row["scores"]["candidate"]["correctness"], 5)
            self.assertEqual(row["scores"]["baseline"]["correctness"], 3)

    def test_judge_garbage_raises(self):
        with self.assertRaises(ValueError):
            mod.run_eval([CASE], "style",
                         respond=lambda p, c: "x",
                         judge=lambda jp: "no json here")

    def test_sink_keeps_paid_rows_before_a_later_failure(self):
        # Case 2's judge reply is garbage; case 1's row must already be in the
        # sink so the paid calls are not discarded (PR #225 review, minor).
        cases = [dict(CASE, id="c1"), dict(CASE, id="c2")]
        ok = json.dumps({"A": scores(), "B": scores(c=5, a=5, act=5, s=5, con=5)})
        replies = iter([ok, "garbage"])
        kept = []
        with self.assertRaises(ValueError):
            mod.run_eval(cases, "style", respond=lambda p, c: "x",
                         judge=lambda jp: next(replies), sink=kept.append)
        self.assertEqual([r["case_id"] for r in kept], ["c1"])


class TestClaudeCallFailsLoudly(unittest.TestCase):
    # A dead CLI must raise, never return a scoreable "" (PR #225 review,
    # major: an empty response was silently judged and could print gate PASS).
    def _call(self, cmd):
        old = os.environ.get("AUDHD_EVAL_CLAUDE_CMD")
        os.environ["AUDHD_EVAL_CLAUDE_CMD"] = cmd
        try:
            spec2 = importlib.util.spec_from_file_location("aoe_reload", MODULE_PATH)
            mod2 = importlib.util.module_from_spec(spec2)
            spec2.loader.exec_module(mod2)
            with tempfile.TemporaryDirectory() as td:
                return mod2._claude("prompt", [], td)
        finally:
            if old is None:
                os.environ.pop("AUDHD_EVAL_CLAUDE_CMD", None)
            else:
                os.environ["AUDHD_EVAL_CLAUDE_CMD"] = old

    def test_nonzero_exit_raises(self):
        with self.assertRaises(RuntimeError):
            self._call("/usr/bin/false")

    def test_empty_output_raises(self):
        with self.assertRaises(RuntimeError):
            self._call("/usr/bin/true")


class TestParseJudge(unittest.TestCase):
    def test_out_of_range_score_rejected(self):
        bad = json.dumps({"A": scores(c=9), "B": scores()})
        with self.assertRaises(ValueError):
            mod.parse_judge_json(bad)

    def test_json_extracted_from_prose(self):
        raw = "Here is my verdict:\n" + json.dumps({"A": scores(), "B": scores()}) + "\nDone."
        verdict = mod.parse_judge_json(raw)
        self.assertEqual(verdict["A"]["correctness"], 4)


class TestScoreRoundtrip(unittest.TestCase):
    def test_score_reads_results_jsonl(self):
        rows = [result("c1", scores(), scores(c=4, a=5, act=5, s=4, con=5))]
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "results.jsonl")
            with open(path, "w") as f:
                for row in rows:
                    f.write(json.dumps(row) + "\n")
            with open(path) as f:
                loaded = [json.loads(line) for line in f if line.strip()]
            self.assertTrue(mod.gate(loaded)[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
