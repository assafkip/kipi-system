#!/usr/bin/env python3
"""Reproducer + regression pin for ASK-504: the escalation-cap page.

THE DEFECT, measured not guessed (2026-08-08, 63 ledger rows):

    capped rows      6
    diagnosis on them  None, all 6

`escalate()` returns at the cap BEFORE it ever calls Fable. So the page it
sends can never carry a diagnosis -- not "usually empty", structurally always
empty. The founder receives "cross-model triage did not unstick this" with zero
content about what was stuck. That is what he called useless, and he is right.

Two more facts from the same 63 rows:
  - 4 of the 6 capped rows are `volume-ceiling`, a TOKEN-BUDGET heuristic that
    fires on sessions making steady progress. Not a stuckness signal.
  - two capped rows share one timestamp with different triggers
    (2026-08-04T03:35:31Z, 2026-08-08T22:07:13Z). Parallel PreToolUse hooks
    race an unlocked cache, so `capped_notified` is stale in both and BOTH page.

`founder-notifications.md` says do not ping for routine progress. A content-free
page fired by a budget heuristic off a race is exactly that. So the page is
DELETED rather than tuned: the refusal already reaches the founder through the
agent's own reply in-session, which the cap-path comment itself concedes is the
reliable route to a human. The ledger row survives, so the episode stays
auditable -- deleting the page is not deleting the record.

ISOLATION: KIPI_FABLE_LEDGER_DIR and KIPI_FABLE_NOTIFY_CMD are redirected into a
tempdir, so this suite never touches the live ledger and never reaches Slack.
The cap path does not call Fable at all, so no run here can spend a real call.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "fable-escalate.py"


class CapPageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ledger = root / "ledger"
        self.marker = root / "PAGED"
        # A stub notifier that RECORDS being called. Asserting on the stub's own
        # artifact, not on stderr text: an `or` across signals passes on the weak
        # half and never tests the page (feedback_or_across_signals).
        self.notify = root / "notify-stub.sh"
        self.notify.write_text(
            "#!/usr/bin/env bash\nprintf '%%s' \"$1\" > '%s'\nexit 0\n" % self.marker)
        self.notify.chmod(0o755)
        self.addCleanup(self.tmp.cleanup)

    def _run(self, trigger="volume-ceiling", count=2, capped_notified=False):
        env = dict(
            os.environ,
            KIPI_FABLE_LEDGER_DIR=str(self.ledger),
            KIPI_FABLE_NOTIFY_CMD=str(self.notify),
            KIPI_FABLE_CAP="2",
        )
        cmd = [sys.executable, str(SCRIPT), "--json", "--trigger", trigger,
               "--reason", "reproducer", "--count", str(count)]
        if capped_notified:
            cmd.append("--capped-notified")
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                              timeout=60)
        return proc

    def _rows(self):
        rows = []
        if self.ledger.is_dir():
            for name in sorted(os.listdir(self.ledger)):
                for line in (self.ledger / name).read_text().splitlines():
                    if line.strip():
                        rows.append(json.loads(line))
        return rows

    # --- the assertion that was RED before the fix ---------------------------

    def test_cap_does_not_page_the_founder(self):
        """THE REPRODUCER. Before the fix the stub marker exists (a page went
        out). After the fix it must not."""
        self._run()
        self.assertFalse(
            self.marker.exists(),
            "the cap path paged the founder; the page carries no diagnosis "
            "because escalate() returns before calling Fable, so it is noise",
        )

    def test_cap_still_records_the_episode(self):
        """Deleting the page must NOT delete the record. A silent cap would be a
        worse defect than a noisy one -- the episode has to stay auditable."""
        self._run()
        rows = self._rows()
        self.assertEqual(len(rows), 1, "the cap must still write exactly one row")
        self.assertTrue(rows[0]["capped"])
        self.assertEqual(rows[0]["trigger"], "volume-ceiling")

    def test_row_states_no_page_was_attempted(self):
        """The row must not claim a page. A receipt for an action that did not
        occur is the rca-specification-reported-as-state class."""
        self._run()
        row = self._rows()[0]
        self.assertFalse(row["notify_attempted"])
        self.assertFalse(row["notify_delivered"])
        self.assertIn("notify_note", row)

    def test_json_result_reports_not_notified(self):
        """token-guard reads this JSON. It must not be told a human was reached."""
        proc = self._run()
        out = json.loads(proc.stdout)
        self.assertTrue(out["capped"])
        self.assertFalse(out["notified"])
        self.assertFalse(out["delivered"])

    # --- negative self-test: prove the check can actually fail ---------------

    def test_stub_notifier_is_wired_and_can_fire(self):
        """NEGATIVE SELF-TEST. If the stub could never write its marker, every
        assertion above would pass against a broken harness rather than against
        a fixed one. Fire the stub directly and prove the marker appears.
        (feedback_check_must_be_able_to_fail)"""
        self.assertFalse(self.marker.exists())
        subprocess.run([str(self.notify), "direct probe"], check=True, timeout=30)
        self.assertTrue(
            self.marker.exists(),
            "the stub notifier never wrote its marker, so the no-page assertions "
            "prove nothing",
        )
        self.assertEqual(self.marker.read_text(), "direct probe")


if __name__ == "__main__":
    unittest.main(verbosity=2)
