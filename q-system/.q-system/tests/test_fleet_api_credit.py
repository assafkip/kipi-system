#!/usr/bin/env python3
"""The fleet API-credit path: key injection, failover, pause, budget (ASK-4311).

FIXTURES ONLY. KIPI_TEST=1 on every case, so `read_key` reads
KIPI_FLEET_FAKE_KEY_* and the macOS Keychain is never touched. No real key, no
network, no `claude` binary: the subject under test runs a FAKE claude written
into the case's own tmpdir, which records the environment it was handed.

THE MUTATION THESE CASES EXIST TO KILL. Drop the `env["ANTHROPIC_API_KEY"] = key`
line in `fleet_api_key._run_once` and the fleet silently goes back to billing the
founder's plan: every run still succeeds, so nothing else in the suite notices.
`test_child_is_handed_the_key` and `test_no_key_refuses_rather_than_billing_the_plan`
are the two that turn red for it.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, SCRIPTS)


def _load(name):
    path = os.path.join(SCRIPTS, name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


spend = _load("fleet_api_spend")
keymod = _load("fleet_api_key")

#: Handed to the fake claude as the key for slot 1 in the failover cases. The
#: fake refuses any run carrying it, which is how "Anthropic refuses this key for
#: an exhausted credit" is modelled without an exhausted credit.
DEAD_KEY = "fake-key-1-exhausted"
LIVE_KEY_1 = "fake-key-1-live"
LIVE_KEY_2 = "fake-key-2-live"

FAKE_CLAUDE = r'''#!/usr/bin/env python3
"""A fake `claude`. Records the env it was handed, then answers like the CLI."""
import json, os, sys

record = os.environ["FAKE_CLAUDE_RECORD"]
seen = os.environ.get("ANTHROPIC_API_KEY")
with open(record, "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "key": seen,
                         "slot": os.environ.get("KIPI_FLEET_KEY_SLOT")}) + "\n")

if seen is None:
    # A run with no key would bill the plan. Make that loud, not a pass.
    sys.stderr.write("fake claude: no ANTHROPIC_API_KEY in env\n")
    sys.exit(90)

if seen == os.environ.get("FAKE_CLAUDE_DEAD_KEY"):
    # FAKE_CLAUDE_REFUSAL picks the SHAPE of the refusal. The default is the
    # friendly one: non-zero exit, Anthropic's own wording on stdout. The others
    # are the shapes the first build of the detector missed (PR #717 finding 3),
    # and each is a real `claude -p --output-format json` shape: the field names
    # come from the captured response in
    # plugins/kipi-core/voiceloop/tests/fixtures/claude-p-capture-2026-09-22.json.
    shape = os.environ.get("FAKE_CLAUDE_REFUSAL", "prose-rc1")
    if shape == "ui-string-402":
        # The CLI rewrote the API error into its own short string. No pattern in
        # the list appears anywhere; only api_error_status says what happened.
        print(json.dumps({"type": "result", "is_error": True,
                          "subtype": "error_during_execution",
                          "api_error_status": 402,
                          "result": "API Error: request failed",
                          "total_cost_usd": 0.0}))
        sys.exit(1)
    if shape == "prose-rc0":
        # A failed turn that still exits 0. The envelope is the only signal that
        # the turn failed at all.
        print(json.dumps({"type": "result", "is_error": True, "subtype": "error",
                          "api_error_status": 400,
                          "result": "Your credit balance is too low to access "
                                    "the Anthropic API.", "total_cost_usd": 0.0}))
        sys.exit(0)
    if shape == "stderr-only":
        # The envelope says nothing useful; the sentence is on stderr.
        sys.stderr.write("API Error: your account has run out of credit\n")
        print(json.dumps({"type": "result", "is_error": True, "subtype": "error",
                          "result": "request failed", "total_cost_usd": 0.0}))
        sys.exit(1)
    if shape == "rate-limited-429":
        # NOT an exhausted credit. Failing over here would burn key 2 on a
        # transient limit.
        print(json.dumps({"type": "result", "is_error": True,
                          "subtype": "error_during_execution",
                          "api_error_status": 429,
                          "result": "API Error: rate limited",
                          "total_cost_usd": 0.0}))
        sys.exit(1)
    print(json.dumps({"type": "result", "is_error": True, "subtype": "error",
                      "result": "Your credit balance is too low to access the "
                                "Anthropic API.", "total_cost_usd": 0.0}))
    sys.exit(1)

cost = float(os.environ.get("FAKE_CLAUDE_COST", "0.25"))
print(json.dumps({"type": "result", "is_error": False, "subtype": "success",
                  "result": "ok from " + seen, "total_cost_usd": cost}))
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.record = os.path.join(d, "calls.jsonl")
        self.fake = os.path.join(d, "claude")
        with open(self.fake, "w") as fh:
            fh.write(FAKE_CLAUDE)
        os.chmod(self.fake, os.stat(self.fake).st_mode | stat.S_IEXEC)

        self._saved = dict(os.environ)
        os.environ.update({
            "KIPI_TEST": "1",
            "KIPI_FLEET_SPEND_LEDGER": os.path.join(d, "spend.jsonl"),
            "KIPI_FLEET_EVENTS": os.path.join(d, "events.jsonl"),
            "KIPI_FLEET_STATE": os.path.join(d, "state.json"),
            "KIPI_FLEET_FAKE_KEY_1": LIVE_KEY_1,
            "KIPI_FLEET_FAKE_KEY_2": LIVE_KEY_2,
            "FAKE_CLAUDE_RECORD": self.record,
            "KIPI_DISPATCH_RESET_HOUR": "7",
        })
        os.environ.pop("KIPI_FLEET_NOW", None)
        os.environ.pop("FAKE_CLAUDE_DEAD_KEY", None)
        os.environ.pop("KIPI_FLEET_MONTHLY_CREDIT", None)
        spend._WARNED.clear()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)
        self.tmp.cleanup()

    # -- helpers --
    def calls(self):
        if not os.path.exists(self.record):
            return []
        with open(self.record) as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def run_exec(self, actor="worker"):
        return keymod.cmd_exec([self.fake, "-p", "hello"], actor=actor)

    def kill_key_1(self):
        """Make the fake refuse slot 1's key for an exhausted credit."""
        os.environ["FAKE_CLAUDE_DEAD_KEY"] = DEAD_KEY
        os.environ["KIPI_FLEET_FAKE_KEY_1"] = DEAD_KEY


class TestKeyInjection(Base):
    def test_child_is_handed_the_key(self):
        """The whole point: the child runs WITH a key, not stripped of one."""
        rc = self.run_exec()
        self.assertEqual(rc, 0)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["key"], LIVE_KEY_1)
        self.assertEqual(calls[0]["slot"], "1")

    def test_json_flags_are_added_so_the_run_reports_its_cost(self):
        # The literal, not keymod.JSON_FLAGS: a test comparing the subject to
        # itself passes when the flag is mutated and the meter goes dead.
        argv = keymod._with_json_flags(["claude", "-p", "x"])
        self.assertEqual(argv, ["claude", "-p", "x", "--output-format", "json"])

    def test_an_explicit_output_format_is_left_alone(self):
        argv = keymod._with_json_flags(["claude", "-p", "x", "--output-format", "text"])
        self.assertEqual(argv.count("--output-format"), 1)

    def test_stdout_is_the_bytes_a_plain_p_call_printed(self):
        import io
        buf = io.StringIO()
        saved, sys.stdout = sys.stdout, buf
        try:
            self.run_exec()
        finally:
            sys.stdout = saved
        self.assertEqual(buf.getvalue(), "ok from %s\n" % LIVE_KEY_1)

    def test_no_key_refuses_rather_than_billing_the_plan(self):
        os.environ.pop("KIPI_FLEET_FAKE_KEY_1")
        os.environ.pop("KIPI_FLEET_FAKE_KEY_2")
        rc = self.run_exec()
        self.assertEqual(rc, keymod.EXIT_NO_KEY)
        self.assertEqual(self.calls(), [], "no key must mean no run at all")

    def test_test_mode_never_reads_the_keychain(self):
        self.assertTrue(keymod.in_test_mode())
        os.environ["KIPI_FLEET_FAKE_KEY_1"] = "from-fixture"
        self.assertEqual(keymod.read_key(1), "from-fixture")


class TestFailover(Base):
    def test_exhausted_key_1_makes_the_next_run_use_key_2(self):
        self.kill_key_1()
        rc = self.run_exec()
        self.assertEqual(rc, 0, "the retry on key 2 should succeed")
        keys = [c["key"] for c in self.calls()]
        self.assertEqual(keys, [DEAD_KEY, LIVE_KEY_2])
        self.assertEqual(keymod.read_state()["active_slot"], 2)

    def test_the_run_after_a_failover_goes_straight_to_key_2(self):
        self.kill_key_1()
        self.run_exec()
        before = len(self.calls())
        rc = self.run_exec()
        self.assertEqual(rc, 0)
        self.assertEqual([c["key"] for c in self.calls()[before:]], [LIVE_KEY_2])

    def test_both_exhausted_pauses_the_fleet(self):
        os.environ["FAKE_CLAUDE_DEAD_KEY"] = DEAD_KEY
        os.environ["KIPI_FLEET_FAKE_KEY_1"] = DEAD_KEY
        os.environ["KIPI_FLEET_FAKE_KEY_2"] = DEAD_KEY
        rc = self.run_exec()
        self.assertEqual(rc, keymod.EXIT_NO_KEY)
        self.assertTrue(keymod.read_state()["paused"])
        self.assertIsNone(keymod.usable_slot(), "a paused fleet offers no key")

    def test_a_paused_fleet_re_probes_once_on_the_next_budget_day(self):
        os.environ["KIPI_FLEET_NOW"] = "1762700400"   # 2026-11-09 ~12:00 local
        os.environ["FAKE_CLAUDE_DEAD_KEY"] = DEAD_KEY
        os.environ["KIPI_FLEET_FAKE_KEY_1"] = DEAD_KEY
        os.environ["KIPI_FLEET_FAKE_KEY_2"] = DEAD_KEY
        self.run_exec()
        self.assertIsNone(keymod.usable_slot(), "same day: no second probe")

        # Next budget day, and the credits are live again.
        os.environ["KIPI_FLEET_NOW"] = str(1762700400 + 86400)
        os.environ["KIPI_FLEET_FAKE_KEY_1"] = LIVE_KEY_1
        os.environ.pop("FAKE_CLAUDE_DEAD_KEY")
        self.assertEqual(keymod.usable_slot(), 1, "a new budget day re-probes")
        rc = self.run_exec()
        self.assertEqual(rc, 0)
        self.assertFalse(keymod.read_state()["paused"],
                         "the first success resumes the fleet")

    def test_a_reader_does_not_spend_the_days_re_probe(self):
        """`status` and `probe` are inspections; only a RUN consumes the probe.

        Written from the dispatcher's side: kipi-dispatch.sh pages and clears on
        every tick (`page_once` / `page_clear`, 15 minutes apart), so its gate is
        a READER by construction. A reader that consumed the probe left the fleet
        paused for the rest of the day with nothing having run.
        """
        os.environ["KIPI_FLEET_NOW"] = "1762700400"
        os.environ["FAKE_CLAUDE_DEAD_KEY"] = DEAD_KEY
        os.environ["KIPI_FLEET_FAKE_KEY_1"] = DEAD_KEY
        os.environ["KIPI_FLEET_FAKE_KEY_2"] = DEAD_KEY
        self.run_exec()
        probe_day_after_pause = keymod.read_state()["last_probe_day"]

        os.environ["KIPI_FLEET_NOW"] = str(1762700400 + 86400)
        os.environ["KIPI_FLEET_FAKE_KEY_1"] = LIVE_KEY_1
        os.environ.pop("FAKE_CLAUDE_DEAD_KEY")
        for _ in range(3):
            self.assertEqual(keymod.usable_slot(), 1,
                             "a read must not burn the probe")
        self.assertEqual(keymod.read_state()["last_probe_day"],
                         probe_day_after_pause,
                         "reads left the stored probe day untouched")
        self.assertEqual(self.run_exec(), 0, "the run still gets its probe")

    def test_a_new_month_hands_both_credits_back(self):
        os.environ["KIPI_FLEET_NOW"] = "1764590400"   # 2026-12-01
        state = keymod.read_state()
        state["exhausted"] = {"1": "2026-11", "2": "2026-11"}
        state["paused"] = True
        keymod.write_state(state)
        # A reader SEES the heal (both credits are back) and persists nothing;
        # the run is what writes it. Same readers-degrade split as the re-probe.
        self.assertEqual(keymod.usable_slot(), 1)
        self.assertEqual(keymod.read_state()["exhausted"],
                         {"1": "2026-11", "2": "2026-11"},
                         "a read must not rewrite the stored marks")
        self.assertEqual(self.run_exec(), 0)
        self.assertEqual(keymod.read_state()["exhausted"], {},
                         "the run persists the new month's heal")

    def test_an_ordinary_failure_is_not_read_as_an_exhausted_credit(self):
        """A non-zero run whose text says nothing about credit keeps key 1."""
        self.assertFalse(keymod.reads_as_exhausted("Error: file not found"))
        self.assertTrue(keymod.reads_as_exhausted(
            "Your credit balance is too low to access the Anthropic API."))


class TestSpendAndBudget(Base):
    def test_a_run_records_its_own_reported_cost(self):
        os.environ["FAKE_CLAUDE_COST"] = "0.37"
        self.run_exec()
        self.assertAlmostEqual(spend.spent_today(), 0.37, places=6)
        self.assertAlmostEqual(spend.spent_month(1), 0.37, places=6)
        self.assertAlmostEqual(spend.spent_month(2), 0.0, places=6)

    def test_the_allowance_is_the_credit_left_over_the_days_left(self):
        os.environ["KIPI_FLEET_NOW"] = "1764590400"   # 2026-12-01, 31 days left
        os.environ["KIPI_FLEET_MONTHLY_CREDIT"] = "250"
        b = spend.budget()
        self.assertEqual(b["days_left_in_month"], 31)
        self.assertAlmostEqual(b["total_credit_left_usd"], 500.0, places=2)
        self.assertAlmostEqual(b["allowance_usd"], 500.0 / 31, places=4)
        self.assertFalse(b["exhausted"])

    def test_a_day_at_its_budget_reads_exhausted(self):
        os.environ["KIPI_FLEET_NOW"] = "1764590400"
        os.environ["KIPI_FLEET_MONTHLY_CREDIT"] = "250"
        allowance = spend.budget()["allowance_usd"]
        spend.record(1, allowance + 0.01, actor="worker")
        b = spend.budget()
        self.assertTrue(b["exhausted"], "the day's budget is spent")
        self.assertAlmostEqual(b["remaining_usd"], 0.0, places=6)

    def test_a_spent_day_does_not_spill_into_the_next_one(self):
        os.environ["KIPI_FLEET_NOW"] = "1764590400"
        os.environ["KIPI_FLEET_MONTHLY_CREDIT"] = "250"
        spend.record(1, 400.0, actor="worker")
        self.assertTrue(spend.budget()["exhausted"])
        os.environ["KIPI_FLEET_NOW"] = str(1764590400 + 86400)
        self.assertAlmostEqual(spend.spent_today(), 0.0, places=6)

    def test_the_month_credit_is_a_hard_ceiling_no_run_may_cross(self):
        os.environ["KIPI_FLEET_MONTHLY_CREDIT"] = "1"
        spend.record(1, 1.0, actor="worker")
        spend.record(2, 1.0, actor="worker")
        self.assertAlmostEqual(spend.credit()["total_left_usd"], 0.0, places=6)
        rc = self.run_exec()
        self.assertEqual(rc, keymod.EXIT_CREDIT_GONE)
        self.assertEqual(self.calls(), [], "a spent month must not run at all")

    def test_the_budget_day_starts_at_the_reset_hour_not_midnight(self):
        # 03:00 local belongs to the previous budget day, same rule the
        # dispatcher's issue counter already uses.
        at = spend.dt.datetime(2026, 11, 9, 3, 0, 0)
        self.assertEqual(spend.budget_day(at), "2026-11-08")
        at = spend.dt.datetime(2026, 11, 9, 8, 0, 0)
        self.assertEqual(spend.budget_day(at), "2026-11-09")

    def test_a_corrupt_cost_is_charged_as_zero_not_as_a_refund(self):
        spend.record(1, 1.0, actor="worker")
        with open(os.environ["KIPI_FLEET_SPEND_LEDGER"], "a") as fh:
            fh.write(json.dumps({"month": spend.month_key(), "day": spend.budget_day(),
                                 "slot": 1, "cost_usd": -500.0}) + "\n")
            fh.write("not json at all\n")
        self.assertAlmostEqual(spend.spent_month(1), 1.0, places=6)

    def test_an_unreadable_ledger_does_not_fail_the_meter(self):
        os.environ["KIPI_FLEET_SPEND_LEDGER"] = os.path.join(self.tmp.name, "nope", "x.jsonl")
        self.assertAlmostEqual(spend.spent_today(), 0.0, places=6)
        self.assertEqual(self.run_exec(), 0, "a missing ledger must not fail the run")


class TestEvents(Base):
    def test_a_failover_leaves_an_event_for_the_daily_report(self):
        self.kill_key_1()
        self.run_exec()
        kinds = [e["kind"] for e in spend.events()]
        self.assertIn("failover", kinds)

    def test_a_pause_and_a_resume_both_leave_events(self):
        os.environ["KIPI_FLEET_NOW"] = "1762700400"
        os.environ["FAKE_CLAUDE_DEAD_KEY"] = DEAD_KEY
        os.environ["KIPI_FLEET_FAKE_KEY_1"] = DEAD_KEY
        os.environ["KIPI_FLEET_FAKE_KEY_2"] = DEAD_KEY
        self.run_exec()
        self.assertIn("pause", [e["kind"] for e in spend.events()])

        os.environ["KIPI_FLEET_NOW"] = str(1762700400 + 86400)
        os.environ["KIPI_FLEET_FAKE_KEY_1"] = LIVE_KEY_1
        os.environ.pop("FAKE_CLAUDE_DEAD_KEY")
        self.run_exec()
        self.assertIn("resume", [e["kind"] for e in spend.events()])


class TestNoSecretsLeak(Base):
    def test_there_is_no_subcommand_that_prints_a_key(self):
        """A `key` verb would put the secret in shell history and set -x traces."""
        import io
        buf = io.StringIO()
        saved, sys.stdout = sys.stdout, buf
        try:
            keymod._main(["status", "--json"])
        finally:
            sys.stdout = saved
        self.assertNotIn(LIVE_KEY_1, buf.getvalue())
        self.assertNotIn(LIVE_KEY_2, buf.getvalue())

    def test_no_ledger_or_state_row_carries_a_key(self):
        self.run_exec()
        for path in (os.environ["KIPI_FLEET_SPEND_LEDGER"],
                     os.environ["KIPI_FLEET_STATE"]):
            if not os.path.exists(path):
                continue
            with open(path) as fh:
                body = fh.read()
            self.assertNotIn(LIVE_KEY_1, body)
            self.assertNotIn(LIVE_KEY_2, body)


class TestRefusalShapesTheProseMissed(Base):
    """PR #717 review round 1, finding 3 (major).

    The detector read Anthropic's wording out of the child's STDOUT, and gated on
    the process exit code. `claude -p --output-format json` rewrites an API error
    into its own short string, reports failure inside the envelope, and can put
    the sentence on stderr. Each case below is a refusal the first build let
    through: no failover, no pause, no event, and the fleet kept hammering a dead
    key while the daily report showed spend flat.
    """

    def _refuse_key_1(self, shape):
        self.kill_key_1()
        os.environ["FAKE_CLAUDE_REFUSAL"] = shape

    def _failed_over(self):
        """True when the run moved to key 2. Read from the CALLS, not the state."""
        return [c["slot"] for c in self.calls()] == ["1", "2"]

    def test_a_rewritten_ui_string_with_api_error_status_402_fails_over(self):
        self._refuse_key_1("ui-string-402")
        rc = self.run_exec()
        self.assertEqual(rc, 0, "key 2 answered, so the run succeeded")
        self.assertTrue(self._failed_over(),
                        "no failover: the refusal carried no pattern from the "
                        "list, and 402 was not read. Calls: %r"
                        % [c["slot"] for c in self.calls()])
        kinds = [e["kind"] for e in spend.events()]
        self.assertIn("failover", kinds, "the failover left no event: %r" % kinds)

    def test_a_failed_turn_that_exits_zero_still_fails_over(self):
        self._refuse_key_1("prose-rc0")
        rc = self.run_exec()
        self.assertEqual(rc, 0)
        self.assertTrue(self._failed_over(),
                        "exit 0 with is_error:true skipped the detector entirely")
        self.assertIn("failover", [e["kind"] for e in spend.events()])

    def test_a_refusal_only_on_stderr_is_still_seen(self):
        self._refuse_key_1("stderr-only")
        rc = self.run_exec()
        self.assertEqual(rc, 0)
        self.assertTrue(self._failed_over(),
                        "the sentence was on stderr, which the detector never read")

    def test_a_rate_limit_is_not_an_exhausted_credit(self):
        """The negative that keeps the fix honest: a 429 must NOT burn key 2."""
        self._refuse_key_1("rate-limited-429")
        rc = self.run_exec()
        self.assertNotEqual(rc, 0, "the run failed and must be reported as failed")
        self.assertEqual([c["slot"] for c in self.calls()], ["1"],
                         "a rate limit failed over and spent the second key")
        self.assertEqual(keymod.read_state()["exhausted"], {},
                         "a rate limit marked a key exhausted for the month")
        self.assertNotIn("failover", [e["kind"] for e in spend.events()])

    def test_a_failed_turn_that_exits_zero_is_recorded_as_failed(self):
        """The ledger has to agree with reality, or the report lies about it."""
        self._refuse_key_1("prose-rc0")
        self.run_exec()
        with open(os.environ["KIPI_FLEET_SPEND_LEDGER"]) as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
        first = [r for r in rows if r["slot"] == 1][0]
        self.assertFalse(first["ok"],
                         "a turn that reported is_error:true was logged ok")

    def test_the_refusals_own_status_is_recorded_for_the_next_reader(self):
        """The pattern list is {{UNVERIFIED}}; this is what makes the first real
        refusal readable instead of lost."""
        self._refuse_key_1("ui-string-402")
        self.run_exec()
        with open(os.environ["KIPI_FLEET_SPEND_LEDGER"]) as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
        notes = " ".join(r.get("note") or "" for r in rows)
        self.assertIn("api_error_status=402", notes)

    def test_the_childs_stderr_still_reaches_the_caller(self):
        """Capturing it for the scan must not swallow it: every caller's log is
        where a stuck run is diagnosed from."""
        self._refuse_key_1("stderr-only")
        err = io.StringIO()
        real = sys.stderr
        sys.stderr = err
        try:
            self.run_exec()
        finally:
            sys.stderr = real
        self.assertIn("run out of credit", err.getvalue(),
                      "the child's stderr was captured and never re-emitted")


class TestTheDetectorDirectly(Base):
    def test_402_reads_as_exhausted_whatever_the_text_says(self):
        self.assertTrue(keymod.reads_as_exhausted(
            "API Error: request failed", {"api_error_status": 402}))

    def test_429_and_400_do_not(self):
        for status in (400, 429, 500, None, "nonsense"):
            self.assertFalse(
                keymod.reads_as_exhausted("API Error: request failed",
                                          {"api_error_status": status}),
                "status %r was read as an exhausted credit" % (status,))

    def test_declared_error_matches_the_usage_ledgers_reading(self):
        """ONE reading of this envelope in the fleet. `usage_ledger._failed()`
        says is_error, or a subtype starting with "error"; this says the same, so
        the two files cannot disagree about one run."""
        self.assertTrue(keymod.declared_error({"is_error": True}))
        self.assertTrue(keymod.declared_error({"subtype": "error_during_execution"}))
        self.assertFalse(keymod.declared_error({"is_error": False,
                                                "subtype": "success"}))
        self.assertFalse(keymod.declared_error({"subtype": "max_turns"}),
                         "a non-API stop reason is not an API refusal")
        self.assertFalse(keymod.declared_error(None))
        self.assertFalse(keymod.declared_error("not a dict"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
