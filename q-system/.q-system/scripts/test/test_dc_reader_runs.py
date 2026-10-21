#!/usr/bin/env python3
"""dc-08: reader runs append to one file, and every run on the current page bytes counts.

WHY. design-reader-gate.py overwrote gate/reader-runs.jsonl on every run, so a run that said STAY
erased the run that said LEAVE, and re-running until the readers liked the page was free. Seal
counted rows, not runs, so rows spliced from several runs formed a full set, and it read floor and
n from today's config, so lowering them after the readers answered passed (dc-07 adversarial
review, adv-3, adv-4, adv-5; std-1: a run for one page wiped the other page's rows).

The REAL reader gate (injected runner) writes every row; the REAL gate seals with real producers.
"""
import json
import os
import subprocess
import sys
import unittest

from test_dc_reader_verdicts import IDS, LABELS, PAGE, READER, Round, answers


class Runs(Round):
    def read_page(self, *responses, page=None):
        f = self.tmp / "answers.json"
        f.write_text(json.dumps({"responses": list(responses)}))
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        args = [sys.executable, str(READER), str(self.rd), "--config", str(self.inst / "design-chain.json"),
                "--runner", "injected", "--answers", str(f)] + (["--page", page] if page else [])
        r = subprocess.run(args, capture_output=True, text=True, env=env, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def rows(self):
        return [json.loads(x) for x in (self.rd / "gate" / "reader-runs.jsonl").read_text().splitlines() if x.strip()]

    STAY = [answers("STAY", "ops consulting")] * 3


class AppendOnly(Runs):
    def test_a_later_all_stay_run_does_not_erase_an_earlier_leave(self):
        self.read_page(answers("LEAVE", "ops consulting"), *[answers("STAY", "ops consulting")] * 2)
        self.read_page(*self.STAY)
        self.assertEqual(len(self.rows()), 6)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn(f"reader {IDS[0]} said LEAVE", out)

    def test_a_run_for_one_page_keeps_the_other_page_s_rows(self):
        # dc-07 std-1
        (self.rd / "About-laptop.html").write_text(PAGE.replace("Two records", "About the work"))
        (self.rd / "proof.md").write_text("Home-laptop.html: proof\nAbout-laptop.html: proof\n")
        self.read_page(*self.STAY, page="Home-laptop.html")
        self.read_page(*self.STAY, page="About-laptop.html")
        self.assertEqual({r["page"] for r in self.rows()}, {"Home-laptop.html", "About-laptop.html"})
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)


class Waivers(Runs):
    def test_a_founder_line_answers_one_run_not_the_next(self):
        # dc-08 adv-3: a waiver keyed by slot exempted that slot in every later run and page version
        self.read_page(answers("LEAVE", "ops consulting"), *[answers("STAY", "ops consulting")] * 2)
        first = self.rows()[0]["_provenance"]["run_id"][:8]
        (self.rd / "gate" / "dispositions.md").write_text(f"- reader {IDS[0]} run {first}: FOUNDER waived that run\n")
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        (self.rd / "receipts.json").unlink()
        (self.rd / "Home-laptop.html").write_text(PAGE.replace("Two records", "Two ledgers"))
        self.read_page(answers("LEAVE", "ops consulting"), *[answers("STAY", "ops consulting")] * 2)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn(f"reader {IDS[0]} said LEAVE", out)


class TornLines(Runs):
    def test_a_run_after_a_torn_line_starts_on_a_line_of_its_own(self):
        # dc-08 adv-4: the next append glued its first row onto the fragment
        self.read_page(*self.STAY)
        p = self.rd / "gate" / "reader-runs.jsonl"
        p.write_bytes(p.read_bytes()[:-40])
        self.read_page(*self.STAY)
        lines = p.read_text().splitlines()
        for ln in lines[-3:]:
            json.loads(ln)                      # the new run's rows are whole lines
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)            # the torn line still refuses: it could hide a LEAVE
        self.assertIn("is not JSON", out)


class WholeRuns(Runs):
    def test_rows_spliced_from_two_runs_are_not_a_run(self):
        self.read_page(*self.STAY)
        self.read_page(*self.STAY)
        rows = self.rows()
        a, b = rows[:3], rows[3:]
        self.assertNotEqual(a[0]["_provenance"]["run_id"], b[0]["_provenance"]["run_id"])
        (self.rd / "gate" / "reader-runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (a[0], a[1], b[2])))
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("no complete reader run for these bytes of Home-laptop.html: the fullest holds 2 of 3", out)
        self.assertNotIn("said", out)          # refused for the runs, not for the verdicts

    def test_rows_with_no_run_id_are_not_a_run(self):
        # rows written before dc-08 carry no run id: they cannot show they are one whole run
        self.read_page(*self.STAY)
        rows = self.rows()
        for r in rows:
            del r["_provenance"]["run_id"]
        (self.rd / "gate" / "reader-runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("carries no run id", out)

    def test_every_whole_run_meets_the_floor_not_only_the_best(self):
        # re-running until one run's readers all answer is best-of-N on the floor
        self.read_page(*[answers("STAY", "ops consulting")] * 2, answers("perhaps", "ops consulting"))
        self.read_page(*self.STAY)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("readers answered 2 of 3", out)

    def test_an_earlier_run_under_another_config_does_not_count_and_a_fresh_one_does(self):
        self.read_page(*self.STAY)
        self.config(labels=LABELS + ["tax software"])
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("no complete reader run", out)
        self.read_page(*self.STAY)
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)

    def test_a_leave_under_another_config_still_refuses(self):
        self.read_page(answers("LEAVE", "ops consulting"), *[answers("STAY", "ops consulting")] * 2)
        self.config(labels=LABELS + ["tax software"])
        self.read_page(*self.STAY)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn(f"reader {IDS[0]} said LEAVE", out)


class TheConfigCannotBeLoweredAfterTheReadersRan(Runs):
    def test_a_lowered_floor_refuses(self):
        self.read_page(*[answers("STAY", "ops consulting")] * 2, answers("perhaps", "ops consulting"))
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("readers answered 2 of 3", out)
        self.config(floor=0.6)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("readers is weaker than the config run", out)

    def test_a_lowered_n_refuses(self):
        self.read_page(answers("STAY", "ops consulting"), *[answers("LEAVE", "ops consulting")] * 2)
        (self.rd / "gate" / "reader-runs.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in self.rows() if r["instance"] == 1))
        self.config(n=1)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("readers is weaker than the config run", out)

    def test_a_shrunk_narrow_list_refuses(self):
        self.read_page(*self.STAY)
        self.config(narrow=[])
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("readers is weaker than the config run", out)
        self.assertEqual(out.count("readers is weaker than the config run"), 1, out)   # once per run (std-2)

    def test_a_row_with_short_answers_still_carries_its_config(self):
        # dc-08 std-1: the weakening check sat behind the answers-shape guard
        self.read_page(*self.STAY)
        rows = self.rows()
        for r in rows:
            r["answers"] = r["answers"][:1]
        (self.rd / "gate" / "reader-runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.config(floor=0.6)
        self.read_page(*self.STAY)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("readers is weaker than the config run", out)

    def test_a_recorded_config_seal_cannot_read_counts_as_weaker(self):
        # the reader gate no longer records a bad floor; a row edited to carry one must fail closed,
        # never read as 0 (mutant Mg survived without this, 2026-09-19)
        self.read_page(*self.STAY)
        rows = self.rows()
        for r in rows:
            r["_provenance"]["readers_config"]["floor"] = "1"
        (self.rd / "gate" / "reader-runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("readers is weaker than the config run", out)

    def test_a_floor_that_is_not_a_number_refuses_before_any_run(self):
        # dc-08 adv-5: a string floor was recorded raw and read as 0 by the weakening check
        self.config(floor="1")
        f = self.tmp / "answers.json"
        f.write_text(json.dumps({"responses": self.STAY}))
        r = subprocess.run([sys.executable, str(READER), str(self.rd), "--config", str(self.inst / "design-chain.json"),
                            "--runner", "injected", "--answers", str(f)], capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("readers.floor", r.stderr)
        self.assertFalse((self.rd / "gate" / "reader-runs.jsonl").exists())

    def test_renaming_the_page_and_deleting_the_block_refuses(self):
        # dc-08 adv-1: the guard matched rows for the CURRENT page name only
        self.read_page(*[answers("LEAVE", "data cleanup")] * 3)
        (self.rd / "Home-laptop.html").rename(self.rd / "Home-laptop.htm")
        (self.rd / "proof.md").write_text("Home-laptop.htm: proof\n")
        (self.inst / "design-chain.json").write_text(json.dumps(
            {"project": "dc07", "owners": [], "standard": {"min_body_px": 15}}))
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("holds reader rows, and design-chain.json has no readers block", out)

    def test_deleting_the_readers_block_refuses_while_rows_exist(self):
        # dc-07 adv-4
        self.read_page(*[answers("LEAVE", "data cleanup")] * 3)
        (self.inst / "design-chain.json").write_text(json.dumps(
            {"project": "dc07", "owners": [], "standard": {"min_body_px": 15}}))
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("has no readers block", out)


if __name__ == "__main__":
    unittest.main()
