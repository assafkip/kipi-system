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

import datetime as dt
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

#: THE SUITE CLOCK, DERIVED FROM A DATE (PR #717 review round 2, finding 3).
#: The literal was 1762700400, which is 2025-11-09 07:00 local, while the
#: comment beside it said 2026-11-09 -- and this suite PRINTS the budget day
#: into the report text it asserts on, so the 2025 date was in the output a
#: reader would check against. Derived, the number cannot drift from its label.
NOW_DT = dt.datetime(2026, 11, 9, 12, 0, 0)
NOW = str(int(NOW_DT.timestamp()))
NEXT_DAY = str(int((NOW_DT + dt.timedelta(days=1)).timestamp()))
#: 04:00 local: before the 07:00 reset, so it belongs to the PREVIOUS budget day.
BEFORE_RESET = str(int(dt.datetime(2026, 11, 9, 4, 0, 0).timestamp()))

#: Per-key facts, shaped like ~/.config/kipi/fleet-api.json. Fixture amounts:
#: key 1 $100 and key 2 $200, both expiring 07:00 local 2026-11-26, so both
#: lines render as billable; cases about an unknown or unconfirmed key overwrite.
CONFIRMED = "2026-11-10T21:00:00Z"
#: 07:00 local on 2026-11-26 as the Console would print it, in UTC. Derived from
#: the local instant so the budget-day count holds in any zone (CI is UTC).
EXP = dt.datetime(2026, 11, 26, 7, 0, 0).astimezone(dt.timezone.utc) \
    .strftime("%Y-%m-%dT%H:%M:%SZ")
FACTS = {"keys": {
    "1": {"monthly_credit_usd": 100, "current_cycle_expires_utc": EXP,
          "auto_reload_off_confirmed_at": CONFIRMED},
    "2": {"monthly_credit_usd": 200, "current_cycle_expires_utc": EXP,
          "auto_reload_off_confirmed_at": CONFIRMED},
}}


def write_facts(path, facts):
    with open(path, "w") as fh:
        json.dump(facts, fh)


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

        self.facts = os.path.join(d, "fleet-api.json")
        write_facts(self.facts, FACTS)

        self._saved = dict(os.environ)
        os.environ.update({
            "KIPI_TEST": "1",
            "KIPI_FLEET_API_FACTS": self.facts,
            "KIPI_FLEET_SPEND_LEDGER": os.path.join(d, "spend.jsonl"),
            "KIPI_FLEET_EVENTS": os.path.join(d, "events.jsonl"),
            "KIPI_FLEET_REPORT_RECEIPT": os.path.join(d, "receipt.json"),
            "KIPI_WORKER_READY_CMD": "python3 " + self.worker,
            "KIPI_CHIEF_ALERT": "python3 " + self.chief,
            "FAKE_CHIEF_RECORD": self.chief_record,
            "KIPI_DISPATCH_RESET_HOUR": "7",
            "KIPI_FLEET_NOW": NOW,              # 2026-11-09 12:00 local
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
        # Each key in its own billing cycle, read from the facts file: a cycle
        # ending 07:00 local on 2026-11-26 has 17 budget days left on 2026-11-09.
        self.assertIn("key 1: $96.50 left of $100.00 this cycle "
                      "(ends %s, 17 budget days left)" % EXP, r["text"])
        self.assertIn("key 2: $200.00 left of $200.00 this cycle", r["text"])

    def test_an_unknown_credit_is_named_every_day_not_shown_as_zero(self):
        facts = json.loads(json.dumps(FACTS))
        facts["keys"]["2"] = {"monthly_credit_usd": None,
                              "current_cycle_expires_utc": None}
        write_facts(self.facts, facts)
        text = report.build()["text"]
        self.assertIn("key 2: NOT USED, credit unknown", text)
        self.assertIn(self.facts, text, "the line must name the file to fix")
        self.assertNotIn("key 2: $0.00", text)

    def test_an_unconfirmed_key_is_named_with_the_reason(self):
        facts = json.loads(json.dumps(FACTS))
        facts["keys"]["1"].pop("auto_reload_off_confirmed_at")
        write_facts(self.facts, facts)
        text = report.build()["text"]
        self.assertIn("key 1: NOT USED, auto-reload off is not confirmed", text)

    def test_an_unconfirmed_key_event_earns_its_own_message(self):
        report.main([])
        spend.event("unconfirmed", "key 1: auto-reload off is not confirmed")
        report.main([])
        self.assertEqual(len(self.sent()), 2, "the condition waited for tomorrow")

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
        os.environ["KIPI_FLEET_NOW"] = NEXT_DAY
        report.main([])
        self.assertEqual(len(self.sent()), 2)

    def test_a_missing_key_cannot_read_as_a_quiet_day(self):
        """PR #717 review round 2, finding 1, the REPORT half.

        With nothing in the Keychain every run refuses, so spend stays $0,
        credit stays whole and no pause is recorded -- the day reads exactly
        like a cheap, quiet one. Fixing probe alone would have left this report
        telling the founder the same lie, which is the ASK-113 round-2 shape:
        the fix landed on the detector and not on the report.
        """
        spend.event("no_key", "no Keychain item for key 1, 2")
        text = report.build()["text"]
        self.assertIn("no_key", text,
                      "the report rendered a keyless day as an ordinary one")
        self.assertIn("no Keychain item", text)

    def test_a_missing_key_earns_its_own_message_immediately(self):
        """It is filed once a budget day, so this costs one message, not 96."""
        report.main([])
        self.assertEqual(len(self.sent()), 1)
        spend.event("no_key", "no Keychain item for key 1, 2")
        report.main([])
        self.assertEqual(len(self.sent()), 2, "the condition waited for tomorrow")
        report.main([])
        self.assertEqual(len(self.sent()), 2, "and only once")

    def test_a_killed_run_makes_the_spend_line_say_it_is_a_floor(self):
        """PR #717 review round 2, finding 2, the REPORT half.

        The allowance is divided out of "spent today". A run the watchdog killed
        was charged and never read, so the number is a floor; a report that
        prints it bare claims a total it does not have.
        """
        spend.record(1, 0.0, actor="worker", ok=False, unmetered=True,
                     note="killed by SIGTERM before its cost was read")
        doc = report.build()
        self.assertEqual(doc["unmetered_runs"], 1)
        self.assertIn("FLOOR", doc["text"])

    def test_a_run_with_no_readable_cost_also_makes_it_a_floor(self):
        """Round 3, minor 3: the caveat covers a run whose output carried no cost,
        not only one the watchdog killed."""
        spend.record(1, 0.0, actor="worker", ok=True, unmetered=True,
                     note="parse_error")
        doc = report.build()
        self.assertEqual(doc["unmetered_runs"], 1)
        self.assertIn("FLOOR", doc["text"])

    def test_an_ordinary_day_says_nothing_about_floors(self):
        """The negative: a day with no killed run must not carry the caveat, or
        it stops meaning anything."""
        spend.record(1, 0.42, actor="worker")
        doc = report.build()
        self.assertEqual(doc["unmetered_runs"], 0)
        self.assertNotIn("FLOOR", doc["text"])

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


#: A stand-in for linear-sync.py, loaded through the report's real load path
#: (KIPI_LINEAR_SYNC) so the document under test is the one the report sends.
FAKE_SYNC = r'''
import json, os


def graphql(query, variables=None):
    with open(os.environ["FAKE_SYNC_RECORD"], "w") as fh:
        json.dump({"query": query, "vars": variables or {}}, fh)
    return {"issues": {"nodes": [{"identifier": "ASK-1", "completedAt": "x"}]}}
'''


def _balanced(doc):
    """(ok, depth_at_end). A GraphQL document's braces, counted."""
    depth = 0
    for ch in doc:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False, depth
    return depth == 0, depth


def _span_of_object_after(doc, marker):
    """The `{...}` that follows `marker`, as (start, end) over `doc`.

    Brace-matched rather than regex-matched, because the whole defect was a
    MISPLACED closing brace: a regex that stops at the first `}` would have
    called the broken document fine.
    """
    at = doc.index(marker) + len(marker)
    while doc[at] in " \t\n":
        at += 1
    assert doc[at] == "{", "no object literal after %r" % marker
    depth = 0
    for i in range(at, len(doc)):
        if doc[i] == "{":
            depth += 1
        elif doc[i] == "}":
            depth -= 1
            if depth == 0:
                return at, i
    raise AssertionError("unclosed object after %r" % marker)


class TestTheClosedQueryItself(unittest.TestCase):
    """THE DOCUMENT THE REPORT ACTUALLY SENDS (PR #717 round 1, finding 1).

    Every other case in this file stubs closed_today() whole, which is right for
    them -- they are about the report's text -- and is exactly why a document
    Linear rejects on every call shipped unnoticed. These cases read
    report.CLOSED_QUERY, the same constant closed_today() hands to graphql().
    """

    def test_the_document_is_brace_balanced(self):
        ok, depth = _balanced(report.CLOSED_QUERY)
        self.assertTrue(ok, "unbalanced by %d: %s" % (depth, report.CLOSED_QUERY))

    def test_state_is_inside_filter_not_beside_it(self):
        """`state:` as a sibling of `filter:` is not a field of IssueFilter, so
        Linear answers with an error and the count is never produced."""
        doc = report.CLOSED_QUERY
        start, end = _span_of_object_after(doc, "filter:")
        self.assertIn("state:", doc[start:end],
                      "state: is not inside filter:{...}: %s" % doc)
        outside = doc[:start] + doc[end + 1:]
        self.assertNotIn("state:", outside,
                         "state: also appears outside filter:{...}: %s" % doc)

    def test_both_window_bounds_are_declared_and_used(self):
        doc = report.CLOSED_QUERY
        for name in ("$after", "$before"):
            self.assertEqual(doc.count(name), 2,
                             "%s must be declared once and used once: %s" % (name, doc))
        self.assertIn("gte:$after", doc.replace(" ", ""))
        self.assertIn("lt:$before", doc.replace(" ", ""))

    def test_closed_today_asks_for_the_budget_days_own_window(self):
        """The window is the budget day, 07:00 local to 07:00 local.

        The shipped code appended "T00:00:00Z" to the day LABEL. In a UTC-8 zone
        that starts 15 hours early and counts the previous afternoon.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        record = os.path.join(tmp.name, "asked.json")
        fake = os.path.join(tmp.name, "linear-sync.py")
        with open(fake, "w") as fh:
            fh.write(FAKE_SYNC)
        env_before = dict(os.environ)
        try:
            os.environ["KIPI_LINEAR_SYNC"] = fake
            os.environ["FAKE_SYNC_RECORD"] = record
            os.environ["KIPI_DISPATCH_RESET_HOUR"] = "7"
            os.environ["KIPI_FLEET_NOW"] = NOW
            count, err = report.closed_today()
            expect_after, expect_before = spend.budget_day_window_utc()
        finally:
            os.environ.clear()
            os.environ.update(env_before)

        self.assertIsNone(err, "the fake answered, so there is no error")
        self.assertEqual(count, 1)
        with open(record) as fh:
            seen = json.load(fh)
        self.assertEqual(seen["vars"].get("after"), expect_after)
        self.assertEqual(seen["vars"].get("before"), expect_before)
        self.assertEqual(seen["query"], report.CLOSED_QUERY,
                         "closed_today must send the constant the tests read")
        os.environ["KIPI_DISPATCH_RESET_HOUR"] = "7"
        os.environ["KIPI_FLEET_NOW"] = NOW

        # And the window is the day it claims, not 15 hours earlier.
        import datetime as dtm
        start = spend.budget_day_start()
        self.assertEqual(start.hour, 7, "a budget day starts at RESET_HOUR local")
        self.assertEqual(start.strftime("%Y-%m-%d"), spend.budget_day())
        back = dtm.datetime.strptime(
            expect_after, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dtm.timezone.utc)
        self.assertEqual(back.astimezone().replace(tzinfo=None), start,
                         "the UTC bound does not round-trip to 07:00 local")


class TestBudgetDayWindow(unittest.TestCase):
    def setUp(self):
        os.environ["KIPI_DISPATCH_RESET_HOUR"] = "7"
        os.environ["KIPI_FLEET_NOW"] = NOW

    def tearDown(self):
        os.environ.pop("KIPI_FLEET_NOW", None)
        os.environ.pop("KIPI_DISPATCH_RESET_HOUR", None)

    def test_a_pre_reset_run_measures_the_day_it_is_counted_against(self):
        """04:00 belongs to yesterday's budget day in BOTH gates, so the window
        it measures has to be yesterday's too."""
        os.environ["KIPI_FLEET_NOW"] = BEFORE_RESET                 # 04:00 local
        day = spend.budget_day()
        after, before = spend.budget_day_window_utc()
        self.assertEqual(spend.budget_day_start().strftime("%Y-%m-%d"), day)
        self.assertLess(after, before)

    def test_the_window_is_exactly_one_day_long(self):
        import datetime as dtm
        after, before = spend.budget_day_window_utc()
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        delta = dtm.datetime.strptime(before, fmt) - dtm.datetime.strptime(after, fmt)
        self.assertEqual(delta, dtm.timedelta(days=1))

    def test_an_explicit_day_overrides_the_clock(self):
        after, _ = spend.budget_day_window_utc(day="2026-03-01")
        self.assertTrue(after.startswith("2026-03-01") or
                        after.startswith("2026-02-28") or
                        after.startswith("2026-03-02"),
                        "2026-03-01 07:00 local must land on an adjacent UTC date: %s"
                        % after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
