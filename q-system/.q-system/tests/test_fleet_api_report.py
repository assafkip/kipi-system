#!/usr/bin/env python3
"""The daily API-credit report to chief (ASK-4311).

FIXTURES ONLY. The worker is a fake script printing a canned pick list, chief's
alert path is a fake script recording what it was handed, and both ledgers are
per-case temp files. Nothing calls Linear, chief or a model.

THE LINE THE FOUNDER ASKED FOR: "have the report to chief also include How many
tickets are left to be done every day". The executable holding that is this file,
`test_the_report_carries_the_ready_count` plus the failure-shape cases in
TestFailureShapes. A report that silently says zero on a failed read would answer
that question wrongly in the one direction that looks like success, so the
failure shape is pinned by a case of its own, not by a comment asking for care.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, SCRIPTS)


def _load(name, filename=None):
    path = os.path.join(SCRIPTS, filename or (name + ".py"))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


spend = _load("fleet_api_spend")
report = _load("fleet_api_report", "fleet-api-report.py")

READY = {
    "ready": [
        {"id": "ASK-1", "project": "kipi-system", "priority": 1},
        {"id": "ASK-2", "project": "kipi-system", "priority": 2},
        {"id": "ASK-3", "project": "consulting", "priority": 3},
        {"id": "ASK-4", "project": None, "priority": 4},
    ],
    "total_open": 99,
}

FAKE_CHIEF = r'''#!/usr/bin/env python3
import os, sys
with open(os.environ["FAKE_CHIEF_RECORD"], "a") as fh:
    fh.write(repr(sys.argv[1:]) + "\n")
'''


def _script(path, body, mode="w"):
    with open(path, mode) as fh:
        fh.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.chief_record = os.path.join(d, "chief.log")
        self.chief = os.path.join(d, "chief.py")
        _script(self.chief, FAKE_CHIEF)
        self.worker = os.path.join(d, "worker.py")
        _script(self.worker,
                "#!/usr/bin/env python3\nimport json\nprint(json.dumps(%r))\n" % (READY,))

        self._saved = dict(os.environ)
        os.environ.update({
            "KIPI_TEST": "1",
            "KIPI_FLEET_SPEND_LEDGER": os.path.join(d, "spend.jsonl"),
            "KIPI_FLEET_EVENTS": os.path.join(d, "events.jsonl"),
            "KIPI_FLEET_REPORT_RECEIPT": os.path.join(d, "receipt.json"),
            "KIPI_WORKER_READY_CMD": "python3 " + self.worker,
            "KIPI_CHIEF_ALERT": "python3 " + self.chief,
            "FAKE_CHIEF_RECORD": self.chief_record,
            "KIPI_DISPATCH_RESET_HOUR": "7",
            "KIPI_FLEET_NOW": "1762700400",     # 2026-11-09, mid-day local
            "KIPI_FLEET_MONTHLY_CREDIT": "250",
        })
        spend._WARNED.clear()
        # closed_today() would reach Linear; every case stubs it, and one case
        # pins what the report says when it fails.
        self._real_closed = report.closed_today
        report.closed_today = lambda: (7, None)

    def tearDown(self):
        report.closed_today = self._real_closed
        os.environ.clear()
        os.environ.update(self._saved)
        self.tmp.cleanup()

    def sent(self):
        if not os.path.exists(self.chief_record):
            return []
        with open(self.chief_record) as fh:
            return [l.strip() for l in fh if l.strip()]


class TestContent(Base):
    def test_the_report_carries_the_ready_count(self):
        """The founder's own line: how many tickets are left to be done."""
        r = report.build()
        self.assertEqual(r["ready_total"], 4)
        self.assertIsNone(r["ready_error"])
        self.assertIn("tickets left to be done: 4", r["text"])

    def test_the_ready_count_is_broken_out_per_project(self):
        r = report.build()
        self.assertEqual(r["ready_by_project"]["kipi-system"], 2)
        self.assertEqual(r["ready_by_project"]["consulting"], 1)
        self.assertEqual(r["ready_by_project"]["(no project)"], 1)
        self.assertIn("  kipi-system: 2", r["text"])

    def test_spend_and_per_key_credit_are_in_the_text(self):
        spend.record(1, 3.50, actor="worker")
        r = report.build()
        self.assertIn("spent today: $3.50", r["text"])
        self.assertIn("key 1: $246.50 left of $250.00", r["text"])
        self.assertIn("key 2: $250.00 left of $250.00", r["text"])

    def test_tickets_closed_today_is_in_the_text(self):
        self.assertIn("tickets closed today: 7", report.build()["text"])

    def test_state_changes_are_named_not_counted(self):
        spend.event("failover", "key 1 read as exhausted; switching to key 2")
        r = report.build()
        self.assertEqual(r["state_changes"], 1)
        self.assertIn("failover: key 1 read as exhausted", r["text"])


class TestFailureShapes(Base):
    def test_a_failed_ready_read_says_so_and_never_says_zero(self):
        """Zero is the one wrong answer that reads as a finished queue."""
        _script(self.worker, "#!/usr/bin/env python3\nimport sys\n"
                             "sys.stderr.write('boom\\n')\nsys.exit(3)\n")
        r = report.build()
        self.assertIsNone(r["ready_total"])
        self.assertIn("tickets left to be done: COULD NOT READ", r["text"])
        self.assertNotIn("tickets left to be done: 0", r["text"])

    def test_a_worker_that_prints_junk_is_a_failed_read(self):
        _script(self.worker, "#!/usr/bin/env python3\nprint('not json')\n")
        self.assertIn("COULD NOT READ", report.build()["text"])

    def test_linear_unreachable_is_a_failed_read_not_an_empty_queue(self):
        _script(self.worker, "#!/usr/bin/env python3\nimport json\n"
                             "print(json.dumps({'ready': [], 'infra_error': 'timeout'}))\n")
        r = report.build()
        self.assertIsNone(r["ready_total"])
        self.assertIn("Linear unreachable", r["text"])

    def test_a_failed_closed_count_says_so(self):
        report.closed_today = lambda: (None, "Linear would not answer (timeout)")
        self.assertIn("tickets closed today: COULD NOT READ", report.build()["text"])

    def test_a_truly_empty_queue_still_reports_zero(self):
        _script(self.worker, "#!/usr/bin/env python3\nimport json\n"
                             "print(json.dumps({'ready': []}))\n")
        r = report.build()
        self.assertEqual(r["ready_total"], 0)
        self.assertIn("tickets left to be done: 0", r["text"])


class TestCadence(Base):
    def test_one_message_a_day(self):
        self.assertEqual(report.main([]), 0)
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(report.main([]), 0)
        self.assertEqual(len(self.sent()), 1, "a second run the same day sends nothing")

    def test_a_new_day_sends_again(self):
        report.main([])
        os.environ["KIPI_FLEET_NOW"] = str(1762700400 + 86400)
        report.main([])
        self.assertEqual(len(self.sent()), 2)

    def test_a_state_change_earns_its_own_message(self):
        report.main([])
        spend.event("pause", "both credits exhausted")
        report.main([])
        self.assertEqual(len(self.sent()), 2, "the pause sends immediately")
        report.main([])
        self.assertEqual(len(self.sent()), 2, "and only once")
        spend.event("resume", "a run succeeded")
        report.main([])
        self.assertEqual(len(self.sent()), 3, "the resume is a second event")

    def test_dry_sends_nothing(self):
        self.assertEqual(report.main(["--dry"]), 0)
        self.assertEqual(self.sent(), [])

    def test_a_broken_chief_path_does_not_fail_the_job(self):
        os.environ["KIPI_CHIEF_ALERT"] = "python3 /nonexistent/chief.py"
        self.assertEqual(report.main([]), 0, "a reporter must not fail the fleet")
        self.assertEqual(report.read_receipt(), {},
                         "a failed send leaves no receipt, so the next run retries")

    def test_the_message_reaches_chiefs_alert_path_not_slack(self):
        """founder-notifications.md: slack-notify.sh files a Sana ticket and pages
        nobody. A report the founder asked to RECEIVE goes through chief."""
        report.main([])
        self.assertEqual(len(self.sent()), 1)
        self.assertIn("FLEET API CREDIT", self.sent()[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
