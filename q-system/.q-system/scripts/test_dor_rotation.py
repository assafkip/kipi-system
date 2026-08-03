#!/usr/bin/env python3
"""Reproducer + regression for DoR batch starvation (ASK-338, sp-e7f907a4).

why (measured): linear-dor-drafter picks `plan[:limit]` with no cursor. Within a
mode, prioritise() is deliberately STABLE, so the same head is selected every
night. A persistently-failing head is re-attempted forever and the tail is never
reached. The live board went 80 -> 87 -> 93 -> 137 issues lacking a DoR against
--limit 8. Inflow beat throughput, but the tail would starve even if it did not:
nothing rotates.

The fix is a rotation cursor persisted across runs. Terminals and redrafts keep
absolute priority (they are the redrive, and terminals cost no `claude` call);
rotation applies to the first-draft backlog only.

Pure functions, no Linear, no network.
"""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "linear-dor-drafter.py"
spec = importlib.util.spec_from_file_location("dd", SCRIPT)
dd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dd)


def plan_of(n, mode="draft", start=0):
    return [(mode, {"identifier": f"ASK-{start + i:03d}"}) for i in range(n)]


class RotationTest(unittest.TestCase):
    def ids(self, batch):
        return [i["identifier"] for _, i in batch]

    # --- the reproducer -----------------------------------------------------
    def test_without_rotation_the_same_head_repeats(self):
        """Documents the defect this fixes. plan[:limit] is the old behaviour."""
        plan = plan_of(20)
        first = self.ids(plan[:3])
        second = self.ids(plan[:3])
        self.assertEqual(first, second,
                         "baseline: unrotated selection repeats, which is the bug")

    # --- the fix ------------------------------------------------------------
    def test_rotation_advances_past_the_previous_batch(self):
        plan = plan_of(20)
        b1 = dd.rotate_for_fairness(plan, None, 3)
        b2 = dd.rotate_for_fairness(plan, self.ids(b1)[-1], 3)
        self.assertEqual(self.ids(b1), ["ASK-000", "ASK-001", "ASK-002"])
        self.assertEqual(self.ids(b2), ["ASK-003", "ASK-004", "ASK-005"])
        self.assertFalse(set(self.ids(b1)) & set(self.ids(b2)))

    def test_every_issue_is_reached_within_one_sweep(self):
        """The property that actually matters: no issue starves."""
        plan = plan_of(20)
        seen, cursor = set(), None
        for _ in range(7):  # ceil(20/3)
            batch = dd.rotate_for_fairness(plan, cursor, 3)
            seen.update(self.ids(batch))
            cursor = self.ids(batch)[-1]
        self.assertEqual(len(seen), 20, f"starved: only reached {len(seen)}/20")

    def test_rotation_wraps_at_the_end(self):
        plan = plan_of(5)
        batch = dd.rotate_for_fairness(plan, "ASK-004", 3)
        self.assertEqual(self.ids(batch), ["ASK-000", "ASK-001", "ASK-002"])

    def test_unknown_cursor_starts_from_the_top(self):
        """A cursor naming an issue that has since closed must not wedge the run."""
        plan = plan_of(5)
        batch = dd.rotate_for_fairness(plan, "ASK-999", 2)
        self.assertEqual(self.ids(batch), ["ASK-000", "ASK-001"])

    # --- priority must survive rotation ------------------------------------
    def test_terminals_and_redrafts_are_never_rotated_away(self):
        """Terminals cost no claude call and redrafts ARE the redrive. Rotating
        them out would rebuild the starvation this fixes, one layer up."""
        plan = ([("terminal", {"identifier": "ASK-T01"})]
                + [("redraft", {"identifier": "ASK-R01"})]
                + plan_of(20))
        batch = dd.rotate_for_fairness(plan, "ASK-010", 3)
        self.assertEqual(self.ids(batch)[:2], ["ASK-T01", "ASK-R01"],
                         "redrive must keep absolute priority")

    def test_limit_larger_than_plan_returns_everything_once(self):
        plan = plan_of(3)
        batch = dd.rotate_for_fairness(plan, None, 10)
        self.assertEqual(len(batch), 3)
        self.assertEqual(len(set(self.ids(batch))), 3, "no duplicates on wrap")


if __name__ == "__main__":
    unittest.main(verbosity=2)
