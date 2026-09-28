#!/usr/bin/env python3
"""Reproducer for jev_backlog_rank.py (ASK-2015).

One test per decision point the ranker makes, and each one was watched RED
before the module existed. The decision points are:

  1. client exclusion   -- a client ticket must never reach the vendor
  2. gold derivation    -- canceled=close, completed=keep, duplicate dropped,
                           45-day window, a Sana ruling outranks the state
  3. auc                -- the ordering metric the whole gate rests on
  4. the gate           -- Jev must STRICTLY beat the control or ranking refuses
  5. cut-point honesty  -- minority-class recall printed beside every floor
                           (RULE-2026-09-19-A: a floor without it is not reported)
  6. close/undo         -- no close without a verified receipt; the receipt
                           carries the pre-close state so undo is exact
"""
import datetime as dt
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_sp = importlib.util.spec_from_file_location("jbr", HERE / "jev_backlog_rank.py")
jbr = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(jbr)

NOW = dt.datetime(2026, 9, 28, tzinfo=dt.timezone.utc)

# SYNTHETIC roots, never the real client names. This repo is public and
# client-name-guard.py's commit-msg check refuses real names in staged content, so
# a fixture carrying them could not be committed even if it were acceptable. The
# guard's behaviour is what these test, and that behaviour does not depend on which
# strings are in the list -- test_roots_are_read_from_the_guard_not_from_this_module
# is what pins the module to the real owner of the list.
FAKE_ROOTS = ("acme foundry", "bluewave labs", "cinder", "42 owls")


def iso(days_ago):
    return (NOW - dt.timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def issue(ident, state_type, *, project="kipi-system", title="t", desc="",
          created=200, terminal=10):
    # `duplicate` gets canceledAt too, because Linear's duplicate states are
    # canceled-type and do set it. Leaving it null made the duplicate fixture
    # pass the window check instead of the duplicate check, so the duplicate
    # exclusion survived its own mutant (mutation sweep, 2026-09-28).
    key = {"canceled": "canceledAt", "completed": "completedAt",
           "duplicate": "canceledAt"}.get(state_type)
    r = {"identifier": ident, "title": title, "description": desc,
         "createdAt": iso(created), "updatedAt": iso(terminal),
         "canceledAt": None, "completedAt": None,
         "state": {"name": state_type, "type": state_type},
         "project": {"name": project} if project else None,
         "labels": {"nodes": []}}
    if key:
        r[key] = iso(terminal)
    return r


class RootsFixture(unittest.TestCase):
    """Every test in this file runs against FAKE_ROOTS, never the real list."""

    def setUp(self):
        self._saved = jbr._ROOTS
        jbr._ROOTS = FAKE_ROOTS

    def tearDown(self):
        jbr._ROOTS = self._saved


class TestClientExclusion(RootsFixture):
    """Decision point 1. The 'Not doing' line of the DoR is the binding one."""

    def test_named_client_project_is_excluded(self):
        for p in ("Acme_Foundry", "bluewave_labs", "Cinder", "42_owls_consulting"):
            self.assertTrue(jbr.is_client(issue("X-1", "canceled", project=p)),
                            f"{p} must be treated as a client project")

    def test_non_client_project_is_kept(self):
        for p in ("kipi-system", "cole-GTM", "Chief", None):
            self.assertFalse(jbr.is_client(issue("X-2", "canceled", project=p)),
                             f"{p} is not a client project")

    def test_client_name_in_text_is_excluded_even_with_no_project(self):
        # A project-less ticket is not covered by the project list, so the text
        # guard is what stops client content reaching a vendor with a perpetual
        # licence over outputs (jev-evaluation-2026-09-21.md, terms section).
        self.assertTrue(jbr.is_client(
            issue("X-3", "canceled", project=None, title="Acme Foundry sync broke")))
        self.assertTrue(jbr.is_client(
            issue("X-4", "canceled", project=None, desc="cinder ingest is red")))

    def test_mutant_dropping_the_text_guard_would_be_caught(self):
        # Mutation: if is_client only read the project field, this case passes
        # through. Asserting the pair keeps the guard honest.
        leaky = issue("X-5", "canceled", project=None, title="bluewave labs survey ids")
        self.assertTrue(jbr.is_client(leaky))


class TestClientRootsSource(unittest.TestCase):
    """Where the roots come from, and what happens when they are not there.

    The names are outside this public repo. ROOTS_FILE is authoritative and
    required; the commit guard's tokens are unioned in and may only WIDEN the
    refusal. That split is a scar: on 2026-09-28 this module read the commit
    guard's list alone, three of the forbidden projects were missing from it, and
    18 tickets went to the vendor.
    """

    def setUp(self):
        self._saved = jbr._ROOTS
        self._saved_guard = jbr.CLIENT_GUARD
        self._saved_roots_file = jbr.ROOTS_FILE
        jbr._ROOTS = None

    def tearDown(self):
        jbr._ROOTS = self._saved
        jbr.CLIENT_GUARD = self._saved_guard
        jbr.ROOTS_FILE = self._saved_roots_file

    def test_roots_come_from_the_file_and_not_from_this_module(self):
        jbr.ROOTS_FILE = self._file("jev-client-roots",
                                    "# a comment\nacme foundry\nab\n\ncinder\n")
        jbr.CLIENT_GUARD = self._stub_guard("return []")
        self.assertEqual(jbr.client_roots(), ("acme foundry", "cinder"),
                         "comments and sub-3-char lines are dropped")

    def test_guard_tokens_are_unioned_in_and_can_only_widen(self):
        jbr.ROOTS_FILE = self._file("jev-client-roots", "acme foundry\n")
        jbr.CLIENT_GUARD = self._stub_guard("return ['Bluewave_Labs']")
        self.assertEqual(jbr.client_roots(), ("acme foundry", "bluewave labs"))

    def test_an_unreadable_guard_never_narrows_the_required_list(self):
        # The union is a bonus. Losing it must not cost the roots the DoR binds.
        jbr.ROOTS_FILE = self._file("jev-client-roots", "acme foundry\n")
        jbr.CLIENT_GUARD = Path(self._tmpdir()) / "no-such-guard.py"
        self.assertEqual(jbr.client_roots(), ("acme foundry",))

    def test_a_missing_roots_file_refuses_instead_of_running_unguarded(self):
        jbr.ROOTS_FILE = Path(self._tmpdir()) / "absent"
        with self.assertRaises(SystemExit) as cm:
            jbr.client_roots()
        self.assertIn("refusing to run", str(cm.exception))

    def test_an_empty_roots_file_refuses_too(self):
        # Reach the branch, do not merely reach the function. An earlier version
        # of this test pointed at a path that does not exist, died in the module
        # loader, and never touched the empty check -- that mutant SURVIVED.
        jbr.ROOTS_FILE = self._file("jev-client-roots", "# only comments\n\nab\n")
        with self.assertRaises(SystemExit) as cm:
            jbr.client_roots()
        self.assertIn("refusing to run", str(cm.exception))

    def test_the_real_list_on_this_machine_covers_every_forbidden_project(self):
        # Coverage against the live file, without naming a client here: the check
        # is that the file declares at least the DoR's seven roots. A list that
        # shrinks below seven is the 2026-09-28 failure returning.
        if not jbr.ROOTS_FILE.exists():
            self.skipTest(f"no roots file at {jbr.ROOTS_FILE} on this machine")
        self.assertGreaterEqual(len(jbr.client_roots()), 7,
                                "the DoR forbids seven projects; the list must "
                                "declare at least that many roots")

    def _file(self, name, body):
        p = Path(self._tmpdir()) / name
        p.write_text(body)
        return p

    def _stub_guard(self, body):
        p = Path(self._tmpdir()) / "stub_guard.py"
        p.write_text("from pathlib import Path\n"
                     "TOKENS_FILE = Path('/nowhere/client-tokens')\n"
                     f"def load_tokens():\n    {body}\n")
        return p

    def _tmpdir(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return d.name


class TestGold(RootsFixture):
    """Decision point 2."""

    def setUp(self):
        super().setUp()
        self.issues = [
            issue("A-1", "canceled", terminal=10),
            issue("A-2", "completed", terminal=10),
            issue("A-3", "canceled", terminal=60),          # outside the window
            issue("A-4", "duplicate", terminal=10),          # not a value judgment
            issue("A-5", "backlog"),                          # still open
            issue("A-6", "canceled", terminal=10, project="Cinder"),  # client
        ]

    def test_labels_and_window(self):
        gold = {c.ident: c for c in jbr.build_gold(self.issues, [], now=NOW)}
        self.assertEqual(gold["A-1"].label, 1, "canceled inside the window = close")
        self.assertEqual(gold["A-2"].label, 0, "completed inside the window = keep")
        self.assertNotIn("A-3", gold, "60 days old is outside the 45-day window")
        self.assertNotIn("A-4", gold, "duplicate is not a keep/close ruling")
        self.assertNotIn("A-5", gold, "an open ticket has no outcome yet")
        self.assertNotIn("A-6", gold, "a client ticket never enters the key")

    def test_sana_ruling_outranks_the_state(self):
        # ASK-2015 names Sana's rulings as the answer key. Where a ruling and the
        # board disagree, the ruling is the label.
        decisions = [{"kind": "sana_decision", "issue": "A-2", "action": "close",
                      "comment": "closed by hand later"}]
        gold = {c.ident: c for c in jbr.build_gold(self.issues, decisions, now=NOW)}
        self.assertEqual(gold["A-2"].label, 1)
        self.assertEqual(gold["A-2"].source, "sana")

    def test_sana_ruling_on_an_unseen_ticket_still_lands(self):
        decisions = [{"kind": "sana_decision", "issue": "A-1", "action": "keep",
                      "comment": "still failing"}]
        gold = {c.ident: c for c in jbr.build_gold(self.issues, decisions, now=NOW)}
        self.assertEqual(gold["A-1"].label, 0)

    def test_mutant_ignoring_duplicates_would_change_the_count(self):
        gold = jbr.build_gold(self.issues, [], now=NOW)
        self.assertEqual(len(gold), 2, "only A-1 and A-2 are scoreable")


class TestAuc(unittest.TestCase):
    """Decision point 3. The gate rests on this number, so it gets a known answer."""

    def test_perfect_and_inverted_and_tied(self):
        self.assertEqual(jbr.auc([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0]), 1.0)
        self.assertEqual(jbr.auc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]), 0.0)
        self.assertEqual(jbr.auc([0.5, 0.5, 0.5, 0.5], [1, 1, 0, 0]), 0.5,
                         "an all-ties ranker is a coin flip, not a winner")

    def test_one_class_only_is_undefined_not_a_win(self):
        self.assertIsNone(jbr.auc([0.9, 0.1], [1, 1]))

    def test_mutant_ignoring_ties_would_break_this(self):
        # Half credit for a tie is what makes an all-constant scorer read 0.500.
        self.assertAlmostEqual(jbr.auc([0.9, 0.5, 0.5, 0.1], [1, 1, 0, 0]), 0.875)


class TestGate(unittest.TestCase):
    """Decision point 4. 'Only if Jev beats the control' is the whole issue."""

    def test_losing_or_tying_refuses_to_rank(self):
        self.assertFalse(jbr.beats_control(0.70, 0.70)[0], "a tie is not a win")
        self.assertFalse(jbr.beats_control(0.65, 0.70)[0])

    def test_winning_by_less_than_the_margin_refuses(self):
        # Linear routing was dropped at 0.779 vs 0.745 as 'not worth a vendor'
        # (jev-evaluation-2026-09-21.md section 4A #3). A win has to be a real one.
        self.assertFalse(jbr.beats_control(0.779, 0.745)[0],
                         "the routing run's own margin is the documented floor")

    def test_landing_exactly_on_the_bar_is_not_a_win(self):
        # The boundary case. Without it, flipping `>` to `>=` inside
        # beats_control changes nothing any other test can see.
        bar = 0.70 + jbr.MIN_MARGIN
        self.assertFalse(jbr.beats_control(bar, 0.70)[0],
                         "equal to the bar is not above it")
        self.assertTrue(jbr.beats_control(bar + 1e-9, 0.70)[0])

    def test_a_clear_win_passes(self):
        self.assertTrue(jbr.beats_control(0.90, 0.70)[0])

    def test_beating_a_weak_control_still_has_to_beat_a_coin_flip(self):
        # A control that scores 0.40 does not lower the bar below chance.
        self.assertFalse(jbr.beats_control(0.52, 0.40)[0])

    def test_undefined_auc_never_passes(self):
        self.assertFalse(jbr.beats_control(None, 0.70)[0])


class TestCutPointHonesty(unittest.TestCase):
    """Decision point 5. RULE-2026-09-19-A."""

    def test_every_floor_row_carries_minority_recall(self):
        scores = {f"I-{i}": i / 10 for i in range(10)}
        labels = {f"I-{i}": 1 if i >= 7 else 0 for i in range(10)}
        table = jbr.cutpoint_table(scores, labels)
        self.assertTrue(table, "the table must have rows")
        for row in table:
            self.assertIn("minority_recall", row)
            self.assertIsNotNone(row["minority_recall"])
            self.assertIn("minority_class", row)

    def test_rendered_table_names_recall_in_the_header(self):
        scores = {f"I-{i}": i / 10 for i in range(10)}
        labels = {f"I-{i}": 1 if i >= 7 else 0 for i in range(10)}
        text = jbr.render_cutpoints(jbr.cutpoint_table(scores, labels))
        self.assertIn("minority recall", text.lower(),
                      "a floor printed without minority recall is not reported at all")

    def test_a_floor_that_catches_none_of_the_minority_is_marked(self):
        # The email run printed accuracy 1.000 while catching 0 of 41 replies.
        scores = {"a": 0.99, "b": 0.01, "c": 0.02}
        labels = {"a": 0, "b": 1, "c": 1}
        rows = [r for r in jbr.cutpoint_table(scores, labels) if r["floor"] >= 0.9]
        self.assertTrue(rows)
        self.assertEqual(rows[0]["minority_recall"], 0.0)


class TestCloseAndUndo(RootsFixture):
    """Decision point 6. 'Every close is labelled and can be undone.'"""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.receipts = Path(self.tmp.name) / "batches"

    def tearDown(self):
        self.tmp.cleanup()

    def test_close_refuses_an_unverified_batch(self):
        batch = {"batch": "b1", "verified": False,
                 "items": [{"identifier": "A-1", "state_id": "s-open"}]}
        with self.assertRaises(jbr.NotVerified):
            jbr.close_batch(batch, receipts_dir=self.receipts, apply=False)

    def test_close_refuses_a_client_ticket_even_when_verified(self):
        batch = {"batch": "b1", "verified": True,
                 "items": [{"identifier": "A-1", "state_id": "s", "project": "Cinder"}]}
        with self.assertRaises(jbr.ClientTicket):
            jbr.close_batch(batch, receipts_dir=self.receipts, apply=False)

    def test_receipt_records_the_pre_close_state_for_undo(self):
        batch = {"batch": "b1", "verified": True,
                 "items": [{"identifier": "A-1", "state_id": "s-open",
                            "state_name": "Backlog", "project": "kipi-system"}]}
        rc = jbr.close_batch(batch, receipts_dir=self.receipts, apply=False)
        self.assertEqual(rc["items"][0]["prior_state_id"], "s-open")
        self.assertEqual(rc["label"], jbr.CLOSE_LABEL)
        self.assertFalse(rc["applied"])
        self.assertTrue((self.receipts / "b1.json").exists())

    def test_undo_reads_the_prior_state_back(self):
        batch = {"batch": "b1", "verified": True,
                 "items": [{"identifier": "A-1", "state_id": "s-open",
                            "state_name": "Backlog", "project": "kipi-system"}]}
        jbr.close_batch(batch, receipts_dir=self.receipts, apply=False)
        plan = jbr.undo_plan("b1", receipts_dir=self.receipts)
        self.assertEqual(plan, [{"identifier": "A-1", "state_id": "s-open",
                                 "state_name": "Backlog"}])

    def test_undo_without_a_receipt_raises(self):
        with self.assertRaises(jbr.NoReceipt):
            jbr.undo_plan("nope", receipts_dir=self.receipts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
