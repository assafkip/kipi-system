#!/usr/bin/env python3
"""Test for check_budget.py (moved from q-system/.q-system/scripts/issue-check-budget.py by ASK-1810).
Temp specs only; never reads .prd-os/."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "check_budget.py"
MARKER = "<!-- generated-by: prd_split.py prd=p finding=f at=2026-09-18T00:00:00Z -->"


def spec(issue_id, allowed, checks):
    lines = ["---", f"id: {issue_id}", "title: t", "status: open", "priority: p1",
             "parent_prd: p", "allowed_files:"]
    lines += [f"  - {a}" for a in allowed]
    lines += ["disallowed_files: []", "required_checks:"]
    lines += [f"  - {c}" for c in checks]
    lines += ["required_reviews: []", "---", MARKER, "", "# t", ""]
    return "\n".join(lines)


class BudgetTest(unittest.TestCase):
    def run_on(self, *specs):
        with tempfile.TemporaryDirectory() as td:
            paths = []
            for i, text in enumerate(specs):
                p = Path(td) / f"s{i}.md"
                p.write_text(text)
                paths.append(str(p))
            r = subprocess.run([sys.executable, str(SCRIPT), *paths], capture_output=True, text=True)
            return r.returncode, r.stdout + r.stderr

    def test_narrow_issue_with_narrow_check_passes(self):
        code, out = self.run_on(spec("small", ["q-system/.q-system/scripts/design-chain-gate.py"],
                                     ["python3 q-system/.q-system/scripts/test_design_chain_gate.py"]))
        self.assertEqual(code, 0, out)
        self.assertIn("small: narrow", out)

    def test_small_issue_carrying_the_full_suite_is_refused(self):
        for full in ("bash q-system/.q-system/verify.sh --full", "pytest -q", "python3 -m pytest", "kipi check"):
            code, out = self.run_on(spec("small", ["docs/x.md"], [full, "python3 docs/test_x.py"]))
            self.assertEqual(code, 2, f"{full!r} should be refused on a non-fleet issue\n{out}")
            self.assertIn("small", out)

    def test_a_fleet_blast_issue_is_refused_the_full_suite_too(self):
        # CI runs verify.sh --full on every PR (.github/workflows/verify.yml), so it runs
        # once at merge for every issue. No spec carries it, fleet-wide files or not.
        code, out = self.run_on(spec("sync", ["settings-template.json", "kipi-update.sh"],
                                     ["bash q-system/.q-system/verify.sh --full",
                                      "bash q-system/.q-system/scripts/test/test-settings-sync.sh"]))
        self.assertEqual(code, 2, out)
        self.assertIn("sync", out)

    def test_a_fleet_blast_issue_with_narrow_checks_passes(self):
        code, out = self.run_on(spec("sync", ["settings-template.json", "q-system/.q-system/scripts/x.py"],
                                     ["python3 q-system/.q-system/scripts/test_x.py"]))
        self.assertEqual(code, 0, out)
        self.assertIn("sync: narrow", out)

    def test_a_scoped_pytest_is_not_the_full_suite(self):
        code, out = self.run_on(spec("p", ["plugins/prd-os/scripts/prd_split.py"],
                                     ["pytest -q plugins/prd-os/tests"]))
        self.assertEqual(code, 0, out)

    def test_every_check_unrelated_to_the_issue_is_refused(self):
        code, out = self.run_on(spec("drift", ["plugins/kipi-design/hooks/dogfood_gate.py"],
                                     ["python3 automation/test_voice_refresh_schedule.py"]))
        self.assertEqual(code, 2, out)
        self.assertIn("no check targets", out)

    def test_one_bad_spec_among_good_ones_fails_the_run_and_is_named(self):
        good = spec("ok", ["a/b.py"], ["python3 a/test_b.py"])
        bad = spec("bloated", ["a/c.md"], ["pytest", "python3 a/test_c.py"])
        code, out = self.run_on(good, bad)
        self.assertEqual(code, 2, out)
        self.assertIn("bloated", out)
        self.assertIn("ok: narrow", out)

    def test_no_specs_is_an_error_not_a_pass(self):
        r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
