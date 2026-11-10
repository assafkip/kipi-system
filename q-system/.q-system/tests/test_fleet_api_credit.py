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

import datetime as dt
import importlib.util
import io
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
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

#: THE SUITE CLOCK, DERIVED FROM A DATE RATHER THAN TYPED AS AN EPOCH (PR #717
#: review round 2, finding 3). The literal was 1762700400, which is 2025-11-09
#: 07:00 local, while every comment beside it said 2026-11-09 and the report
#: suite printed the 2025 date into its own output. A derived constant cannot
#: drift from its comment: change the date here and the number follows.
#: Mid-day on purpose, well inside the 07:00-to-07:00 budget day, so adding a
#: day cannot land on the boundary.
NOW_DT = dt.datetime(2026, 11, 9, 12, 0, 0)
NOW = str(int(NOW_DT.timestamp()))
NEXT_DAY = str(int((NOW_DT + dt.timedelta(days=1)).timestamp()))
#: The first of the next calendar month. NOT a credit boundary any more: the
#: credit renews per billing cycle (Help Center article 17154008), so a mark
#: made on 2026-11-09 must not clear here just because the month rolled.
DEC_FIRST = str(int(dt.datetime(2026, 12, 1, 12, 0, 0).timestamp()))
#: 08:00 on 2026-11-26: after the fixture cycle's expiry (07:00 local that day).
NOV_26_0800 = str(int(dt.datetime(2026, 11, 26, 8, 0, 0).timestamp()))
#: 03:00 on 2026-11-26: still the old budget day, and before the expiry.
NOV_26_0300 = str(int(dt.datetime(2026, 11, 26, 3, 0, 0).timestamp()))



def utc_of_local(*parts):
    """The Console writes a cycle expiry in UTC. Derived from a LOCAL instant so
    every budget-day assertion holds in any zone the suite runs in (CI is UTC,
    this Mac is Pacific)."""
    return dt.datetime(*parts).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


#: Cycle expiries at 07:00 local, exactly a budget-day boundary, so the cycle
#: arithmetic below reads in whole budget days.
EXP_NOV26 = utc_of_local(2026, 11, 26, 7, 0, 0)
EXP_DEC26 = utc_of_local(2026, 12, 26, 7, 0, 0)

#: The facts every case starts from, shaped like ~/.config/kipi/fleet-api.json.
#: Fixture amounts, not the live ones: key 1 $100 and key 2 $200, both expiring
#: EXP_NOV26 so the failover cases have somewhere to go, both confirmed so they
#: are billable. Cases about an unknown, ended or unconfirmed key overwrite rows.
CONFIRMED = "2026-11-10T21:00:00Z"
FACTS = {"keys": {
    "1": {"monthly_credit_usd": 100, "current_cycle_expires_utc": EXP_NOV26,
          "auto_reload_off_confirmed_at": CONFIRMED},
    "2": {"monthly_credit_usd": 200, "current_cycle_expires_utc": EXP_NOV26,
          "auto_reload_off_confirmed_at": CONFIRMED},
}}


def facts_with(**rows):
    """FACTS with whole key rows replaced, e.g. facts_with(**{"2": {...}})."""
    out = json.loads(json.dumps(FACTS))
    out["keys"].update(rows)
    return out


def write_facts(path, facts=None):
    with open(path, "w") as fh:
        json.dump(facts if facts is not None else FACTS, fh)

FAKE_CLAUDE = r'''#!/usr/bin/env python3
"""A fake `claude`. Records the env it was handed, then answers like the CLI."""
import json, os, sys, time

record = os.environ["FAKE_CLAUDE_RECORD"]
seen = os.environ.get("ANTHROPIC_API_KEY")
with open(record, "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "key": seen,
                         "slot": os.environ.get("KIPI_FLEET_KEY_SLOT")}) + "\n")

# A HUNG RUN, for the watchdog cases. The record above is written FIRST, so the
# test can wait for the child to be up and kill it while it is genuinely mid-run
# rather than racing the spawn. `claude -p` prints total_cost_usd only at the
# end, which is exactly why a killed run's cost cannot be recovered.
if os.environ.get("FAKE_CLAUDE_SLEEP"):
    time.sleep(float(os.environ["FAKE_CLAUDE_SLEEP"]))

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

        self.facts = os.path.join(d, "fleet-api.json")
        write_facts(self.facts)

        self._saved = dict(os.environ)
        os.environ.update({
            "KIPI_TEST": "1",
            "KIPI_FLEET_API_FACTS": self.facts,
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
        os.environ["KIPI_FLEET_NOW"] = NOW
        os.environ["FAKE_CLAUDE_DEAD_KEY"] = DEAD_KEY
        os.environ["KIPI_FLEET_FAKE_KEY_1"] = DEAD_KEY
        os.environ["KIPI_FLEET_FAKE_KEY_2"] = DEAD_KEY
        self.run_exec()
        self.assertIsNone(keymod.usable_slot(), "same day: no second probe")

        # Next budget day, and the credits are live again.
        os.environ["KIPI_FLEET_NOW"] = NEXT_DAY
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
        os.environ["KIPI_FLEET_NOW"] = NOW
        os.environ["FAKE_CLAUDE_DEAD_KEY"] = DEAD_KEY
        os.environ["KIPI_FLEET_FAKE_KEY_1"] = DEAD_KEY
        os.environ["KIPI_FLEET_FAKE_KEY_2"] = DEAD_KEY
        self.run_exec()
        probe_day_after_pause = keymod.read_state()["last_probe_day"]

        os.environ["KIPI_FLEET_NOW"] = NEXT_DAY
        os.environ["KIPI_FLEET_FAKE_KEY_1"] = LIVE_KEY_1
        os.environ.pop("FAKE_CLAUDE_DEAD_KEY")
        for _ in range(3):
            self.assertEqual(keymod.usable_slot(), 1,
                             "a read must not burn the probe")
        self.assertEqual(keymod.read_state()["last_probe_day"],
                         probe_day_after_pause,
                         "reads left the stored probe day untouched")
        self.assertEqual(self.run_exec(), 0, "the run still gets its probe")

    def test_a_new_cycle_hands_the_credit_back(self):
        """A new expiry in the facts file is a new cycle: marks carrying the old
        expiry read stale and both keys come back."""
        write_facts(self.facts, facts_with(**{
            "1": dict(FACTS["keys"]["1"], current_cycle_expires_utc=EXP_DEC26),
            "2": dict(FACTS["keys"]["2"], current_cycle_expires_utc=EXP_DEC26)}))
        os.environ["KIPI_FLEET_NOW"] = NOV_26_0800
        state = keymod.read_state()
        state["exhausted"] = {"1": EXP_NOV26, "2": EXP_NOV26}
        state["paused"] = True
        keymod.write_state(state)
        # A reader SEES the heal (both credits are back) and persists nothing;
        # the run is what writes it. Same readers-degrade split as the re-probe.
        self.assertEqual(keymod.usable_slot(), 1)
        self.assertEqual(keymod.read_state()["exhausted"],
                         {"1": EXP_NOV26, "2": EXP_NOV26},
                         "a read must not rewrite the stored marks")
        self.assertEqual(self.run_exec(), 0)
        self.assertEqual(keymod.read_state()["exhausted"], {},
                         "the run persists the new cycle's heal")

    def test_a_mark_lasts_until_the_keys_own_cycle_ends(self):
        """The calendar month is not the credit's period. A key exhausted on
        2026-11-09 is still out at 03:00 on the 26th (its cycle has not ended)
        and comes back once the file names its next expiry. The month_key build
        handed it back on the 1st whatever its cycle said."""
        self.kill_key_1()
        os.environ["KIPI_FLEET_NOW"] = NOW
        self.run_exec()
        self.assertEqual(keymod.read_state()["exhausted"].get("1"), EXP_NOV26)
        os.environ["KIPI_FLEET_NOW"] = NOV_26_0300
        self.assertEqual(keymod.usable_slot(), 2,
                         "03:00 before the expiry is still the old cycle")
        write_facts(self.facts, facts_with(**{
            "1": dict(FACTS["keys"]["1"], current_cycle_expires_utc=EXP_DEC26),
            "2": dict(FACTS["keys"]["2"], current_cycle_expires_utc=EXP_DEC26)}))
        os.environ["KIPI_FLEET_NOW"] = NOV_26_0800
        self.assertEqual(keymod.usable_slot(), 1,
                         "the next cycle's expiry did not hand key 1 back")

    def test_an_ended_cycle_with_no_new_expiry_is_not_used(self):
        """Past the expiry the next cycle's end is unknown, and it is never
        inferred. The key stops and the line says which field to set."""
        os.environ["KIPI_FLEET_NOW"] = NOV_26_0800
        self.assertEqual(spend.billable_slots(), ())
        self.assertEqual(self.run_exec(), keymod.EXIT_NO_KEY)
        self.assertEqual(self.calls(), [], "a key past its cycle's end was billed")
        line = spend.describe_key(spend.credit(), 1)
        self.assertIn("its billing cycle ended at %s" % EXP_NOV26, line)
        self.assertIn("current_cycle_expires_utc", line)

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
        self.assertAlmostEqual(spend.spent_cycle(1), 0.37, places=6)
        self.assertAlmostEqual(spend.spent_cycle(2), 0.0, places=6)

    def test_the_allowance_is_each_keys_credit_left_over_its_days_left(self):
        # 2026-11-09 sits in the 2026-10-26 -> 2026-11-26 cycle: 17 budget days
        # left, today included. Both keys expire EXP_NOV26 in the fixture.
        os.environ["KIPI_FLEET_NOW"] = NOW
        self.assertEqual(spend.cycle(1), ("2026-10-26", "2026-11-26"))
        self.assertEqual(spend.days_left_in_cycle(1), 17)
        b = spend.budget()
        self.assertAlmostEqual(b["total_credit_left_usd"], 300.0, places=2)
        self.assertAlmostEqual(b["allowance_usd"], 100.0 / 17 + 200.0 / 17, places=4)
        self.assertFalse(b["exhausted"])

    def test_two_keys_on_two_cycles_are_paced_separately(self):
        facts = json.loads(json.dumps(FACTS))
        facts["keys"]["2"]["current_cycle_expires_utc"] = \
            utc_of_local(2026, 11, 12, 7, 0, 0)          # 3 budget days out
        write_facts(self.facts, facts)
        os.environ["KIPI_FLEET_NOW"] = NOW
        self.assertEqual(spend.days_left_in_cycle(2), 3)
        self.assertAlmostEqual(spend.budget()["allowance_usd"],
                               100.0 / 17 + 200.0 / 3, places=4)

    def test_spending_today_does_not_shrink_todays_allowance(self):
        """The allowance is divided out of the credit left when the day BEGAN.
        Divided out of what is left now, every dollar spent today would lower
        the bar it is measured against, and the day would stop short."""
        os.environ["KIPI_FLEET_NOW"] = NOW
        before = spend.budget()["allowance_usd"]
        spend.record(1, 3.0, actor="worker")
        self.assertAlmostEqual(spend.budget()["allowance_usd"], before, places=6)

    def test_a_day_at_its_budget_reads_exhausted(self):
        os.environ["KIPI_FLEET_NOW"] = NOW
        allowance = spend.budget()["allowance_usd"]
        spend.record(1, allowance + 0.01, actor="worker")
        b = spend.budget()
        self.assertTrue(b["exhausted"], "the day's budget is spent")
        self.assertEqual(b["reason"], "today's allowance is spent")
        self.assertAlmostEqual(b["remaining_usd"], 0.0, places=6)

    def test_a_spent_day_does_not_spill_into_the_next_one(self):
        os.environ["KIPI_FLEET_NOW"] = NOW
        spend.record(1, 40.0, actor="worker")
        self.assertTrue(spend.budget()["exhausted"])
        os.environ["KIPI_FLEET_NOW"] = NEXT_DAY
        self.assertAlmostEqual(spend.spent_today(), 0.0, places=6)
        self.assertFalse(spend.budget()["exhausted"])

    def test_the_first_hours_of_the_1st_do_not_read_the_new_allowance_as_spent(self):
        """PR #717 review round 3, minor 2. budget() divided a budget day's
        spend (still the 30th until 07:00) by a calendar month that had rolled
        at midnight, so from 00:00 to 07:00 on the 1st the previous day's spend
        exhausted the new month's allowance with the credit intact. A cycle now
        starts at the reset hour, so one budget day never straddles two
        periods. Expiring on the 1st here to put the old boundary under test."""
        exp_dec1 = utc_of_local(2026, 12, 1, 7, 0, 0)
        exp_jan1 = utc_of_local(2027, 1, 1, 7, 0, 0)
        facts = json.loads(json.dumps(FACTS))
        facts["keys"]["1"]["current_cycle_expires_utc"] = exp_dec1
        facts["keys"]["2"]["current_cycle_expires_utc"] = exp_dec1
        write_facts(self.facts, facts)
        os.environ["KIPI_FLEET_NOW"] = str(int(dt.datetime(2026, 11, 30, 12).timestamp()))
        spend.record(1, 20.0, actor="worker")
        os.environ["KIPI_FLEET_NOW"] = str(int(dt.datetime(2026, 12, 1, 3).timestamp()))
        b = spend.budget()
        self.assertEqual(b["day"], "2026-11-30")
        self.assertFalse(b["exhausted"],
                         "03:00 on the 1st read the day as spent: %r" % b)
        # The next cycle, as the orchestrator records it from the Console.
        facts["keys"]["1"]["current_cycle_expires_utc"] = exp_jan1
        facts["keys"]["2"]["current_cycle_expires_utc"] = exp_jan1
        write_facts(self.facts, facts)
        os.environ["KIPI_FLEET_NOW"] = str(int(dt.datetime(2026, 12, 1, 8).timestamp()))
        b = spend.budget()
        self.assertEqual(spend.cycle(1), ("2026-12-01", "2027-01-01"))
        self.assertAlmostEqual(b["allowance_usd"], 300.0 / 31, places=4)
        self.assertAlmostEqual(b["spent_usd"], 0.0, places=6)

    def test_the_cycle_credit_is_a_hard_ceiling_no_run_may_cross(self):
        write_facts(self.facts, facts_with(**{
            "1": dict(FACTS["keys"]["1"], monthly_credit_usd=1),
            "2": dict(FACTS["keys"]["2"], monthly_credit_usd=1)}))
        spend.record(1, 1.0, actor="worker")
        spend.record(2, 1.0, actor="worker")
        self.assertAlmostEqual(spend.credit()["total_left_usd"], 0.0, places=6)
        rc = self.run_exec()
        self.assertEqual(rc, keymod.EXIT_CREDIT_GONE)
        self.assertEqual(self.calls(), [], "a spent cycle must not run at all")

    def test_the_budget_day_starts_at_the_reset_hour_not_midnight(self):
        # 03:00 local belongs to the previous budget day, same rule the
        # dispatcher's issue counter already uses.
        at = spend.dt.datetime(2026, 11, 9, 3, 0, 0)
        self.assertEqual(spend.budget_day(at), "2026-11-08")
        at = spend.dt.datetime(2026, 11, 9, 8, 0, 0)
        self.assertEqual(spend.budget_day(at), "2026-11-09")

    def test_a_cycle_ending_on_the_31st_starts_on_the_last_day_a_month_before(self):
        write_facts(self.facts, {"keys": {"1": {
            "monthly_credit_usd": 100,
            "current_cycle_expires_utc": utc_of_local(2027, 3, 31, 7, 0, 0)}}})
        at = dt.datetime(2027, 3, 15, 12)
        self.assertEqual(spend.cycle(1, at), ("2027-02-28", "2027-03-31"))

    def test_a_corrupt_cost_is_charged_as_zero_not_as_a_refund(self):
        spend.record(1, 1.0, actor="worker")
        with open(os.environ["KIPI_FLEET_SPEND_LEDGER"], "a") as fh:
            fh.write(json.dumps({"day": spend.budget_day(),
                                 "slot": 1, "cost_usd": -500.0}) + "\n")
            fh.write("not json at all\n")
        self.assertAlmostEqual(spend.spent_cycle(1), 1.0, places=6)

    def test_an_unreadable_ledger_does_not_fail_the_meter(self):
        os.environ["KIPI_FLEET_SPEND_LEDGER"] = os.path.join(self.tmp.name, "nope", "x.jsonl")
        self.assertAlmostEqual(spend.spent_today(), 0.0, places=6)
        self.assertEqual(self.run_exec(), 0, "a missing ledger must not fail the run")


class TestCreditFactsComeFromTheFile(Base):
    """Founder-measured facts, 2026-11-10: the credit is not $250 and not one
    number. It lives in ~/.config/kipi/fleet-api.json, per key, with its source.
    These cases pin that the code reads it and invents nothing."""

    def test_the_credit_is_the_files_number(self):
        c = spend.credit()
        self.assertEqual(c["per_key_credit_usd"], {1: 100.0, 2: 200.0})
        write_facts(self.facts, facts_with(**{
            "1": dict(FACTS["keys"]["1"], monthly_credit_usd=37),
            "2": dict(FACTS["keys"]["2"], monthly_credit_usd=5)}))
        self.assertEqual(spend.credit()["per_key_credit_usd"], {1: 37.0, 2: 5.0})

    def test_no_credit_amount_is_written_in_the_code(self):
        """The 250 default is gone, and no env var can stand in for the file."""
        src = open(os.path.join(SCRIPTS, "fleet_api_spend.py")).read()
        self.assertNotIn("KIPI_FLEET_MONTHLY_CREDIT", src)
        os.environ["KIPI_FLEET_MONTHLY_CREDIT"] = "250"
        os.environ.pop("KIPI_FLEET_API_FACTS")
        self.assertEqual(spend.configured_slots(), (),
                         "a credit was found with no facts file")

    def test_a_test_run_never_reads_the_live_file(self):
        os.environ.pop("KIPI_FLEET_API_FACTS")
        self.assertIsNone(spend.facts_path(),
                          "under KIPI_TEST=1 the live facts path was the default")

    def test_with_no_facts_nothing_runs_and_the_budget_says_why(self):
        os.environ.pop("KIPI_FLEET_API_FACTS")
        b = spend.budget()
        self.assertTrue(b["exhausted"])
        self.assertIn("no key is billable", b["reason"])
        self.assertIn("current_cycle_expires_utc", b["reason"])
        self.assertEqual(self.run_exec(), keymod.EXIT_NO_KEY)
        self.assertEqual(self.calls(), [], "a run with no known credit ran")
        self.assertIn("no_key", [e["kind"] for e in spend.events()])

    def test_a_bad_value_is_unknown_not_zero(self):
        os.environ["KIPI_FLEET_NOW"] = NOW
        for bad in ("100", True, -5, None, float("nan")):
            write_facts(self.facts, {"keys": {"1": {
                "monthly_credit_usd": bad, "current_cycle_expires_utc": EXP_NOV26}}})
            self.assertFalse(spend.configured(1), "credit %r was accepted" % (bad,))
        # A NAIVE timestamp is refused: guessing its zone moves the cycle's end.
        for bad in ("2026-11-26", "2026-11-26T07:00:00", "garbage", "", None,
                    1795000000, True):
            write_facts(self.facts, {"keys": {"1": {
                "monthly_credit_usd": 100, "current_cycle_expires_utc": bad}}})
            self.assertFalse(spend.configured(1), "expiry %r was accepted" % (bad,))
        write_facts(self.facts, {"keys": {"1": {
            "monthly_credit_usd": 100, "current_cycle_expires_utc": "2026-11-29T00:00:00+00:00"}}})
        self.assertTrue(spend.configured(1), "an explicit +00:00 offset was refused")


class TestAKeyWithAnUnknownCreditIsNotUsed(Base):
    """Key 2's plan is pending the founder's reply, so its credit is null in the
    live file. Chosen behaviour, never a guess: the key is not run, not failed
    over to, adds $0 to the allowance, and the report names it every day."""

    def setUp(self):
        super().setUp()
        write_facts(self.facts, facts_with(**{"2": {
            "monthly_credit_usd": None, "current_cycle_expires_utc": None}}))
        os.environ["KIPI_FLEET_NOW"] = NOW

    def test_it_adds_nothing_to_the_allowance(self):
        b = spend.budget()
        self.assertEqual(b["known_keys"], [1])
        self.assertAlmostEqual(b["allowance_usd"], 100.0 / 17, places=4)
        self.assertIsNone(spend.credit()["per_key_usd"][2])
        self.assertEqual(spend.credit()["unknown_keys"], [2])

    def test_it_is_never_failed_over_to(self):
        self.kill_key_1()
        rc = self.run_exec()
        self.assertEqual(rc, keymod.EXIT_NO_KEY, "the fleet failed over to an unknown credit")
        self.assertEqual([c["key"] for c in self.calls()], [DEAD_KEY])
        self.assertTrue(keymod.read_state()["paused"])

    def test_probe_does_not_ask_the_keychain_about_it(self):
        os.environ.pop("KIPI_FLEET_FAKE_KEY_2")
        buf = io.StringIO()
        saved, sys.stdout = sys.stdout, buf
        try:
            rc = keymod._main(["probe"])
        finally:
            sys.stdout = saved
        self.assertEqual((rc, buf.getvalue().strip()), (0, "key 1"))

    def test_the_line_names_the_key_and_the_file(self):
        line = spend.describe_key(spend.credit(), 2)
        self.assertIn("key 2: NOT USED, credit unknown", line)
        self.assertIn(self.facts, line)

    def test_a_known_credit_with_an_unknown_cycle_is_not_used_either(self):
        """Key 2's live state since 20:30Z: $200 confirmed, expiry pending."""
        write_facts(self.facts, facts_with(**{"2": {
            "monthly_credit_usd": 200, "current_cycle_expires_utc": None,
            "auto_reload_off_confirmed_at": CONFIRMED}}))
        self.assertEqual(spend.billable_slots(), (1,))
        line = spend.describe_key(spend.credit(), 2)
        self.assertIn("key 2: NOT USED, billing cycle unknown", line)
        self.assertIn("current_cycle_expires_utc", line)
        self.kill_key_1()
        self.assertEqual(self.run_exec(), keymod.EXIT_NO_KEY)
        self.assertEqual([c["key"] for c in self.calls()], [DEAD_KEY],
                         "the fleet failed over to a key whose cycle is unknown")


class TestAutoReloadMustBeConfirmedOff(Base):
    """Orchestrator, 2026-11-10, binding: a key is NOT usable unless
    keys.<slot>.auto_reload_off_confirmed_at holds a timestamp. The founder's
    spend rule holds only while Anthropic refuses at the credit; with auto-reload
    on, or the credit not yet claimed, a run past it charges his card. Treated
    exactly like a missing key: no run, a loud event, a report line, and probe
    red so the dispatcher gate and the pacer both stop on it."""

    def _probe(self):
        buf = io.StringIO()
        saved, sys.stdout = sys.stdout, buf
        try:
            rc = keymod._main(["probe"])
        finally:
            sys.stdout = saved
        return rc, buf.getvalue().strip()

    def _unconfirm(self, *slots):
        rows = {}
        for slot in slots:
            row = dict(FACTS["keys"][str(slot)])
            row.pop("auto_reload_off_confirmed_at")
            rows[str(slot)] = row
        write_facts(self.facts, facts_with(**rows))

    def test_an_unconfirmed_key_never_runs(self):
        self._unconfirm(1, 2)
        self.assertEqual(self.run_exec(), keymod.EXIT_NO_KEY)
        self.assertEqual(self.calls(), [], "a key with auto-reload unconfirmed was billed")

    def test_the_refusal_leaves_a_loud_event(self):
        self._unconfirm(1, 2)
        self.run_exec()
        ev = [e for e in spend.events() if e["kind"] == "unconfirmed"]
        self.assertEqual(len(ev), 1)
        self.assertIn("auto-reload off is not confirmed", ev[0]["text"])

    def test_probe_is_red_for_an_unconfirmed_key(self):
        self._unconfirm(1)
        rc, out = self._probe()
        self.assertEqual(rc, keymod.EXIT_NO_KEY)
        self.assertTrue(out.startswith("no key"), out)
        self.assertIn("1 (auto-reload off not confirmed)", out)

    def test_an_unconfirmed_key_is_never_failed_over_to(self):
        self._unconfirm(2)
        self.kill_key_1()
        self.assertEqual(self.run_exec(), keymod.EXIT_NO_KEY)
        self.assertEqual([c["key"] for c in self.calls()], [DEAD_KEY])

    def test_an_unconfirmed_key_adds_nothing_to_the_allowance(self):
        self._unconfirm(2)
        os.environ["KIPI_FLEET_NOW"] = NOW
        self.assertAlmostEqual(spend.budget()["allowance_usd"], 100.0 / 17, places=4)

    def test_the_report_line_names_the_slot_and_why(self):
        self._unconfirm(2)
        line = spend.describe_key(spend.credit(), 2)
        self.assertIn("key 2: NOT USED, auto-reload off is not confirmed", line)
        self.assertIn("auto_reload_off_confirmed_at", line)
        self.assertIn(self.facts, line)

    def test_an_empty_timestamp_is_not_a_confirmation(self):
        for bad in ("", "   ", None, True, 1731272400):
            write_facts(self.facts, facts_with(**{"1": dict(
                FACTS["keys"]["1"], auto_reload_off_confirmed_at=bad)}))
            self.assertFalse(spend.billable(1), "%r confirmed auto-reload off" % (bad,))

    def test_the_confirmed_fixture_is_billable(self):
        """The positive half: the guard does not refuse a confirmed key."""
        self.assertEqual(spend.billable_slots(), (1, 2))
        self.assertEqual(self._probe(), (0, "key 1"))


class TestTheStateLockCoversTheReadModifyWrite(Base):
    """PR #717 review round 3, minor 4. The flock sat inside write_state only, so
    it ordered two WRITES and nothing else: two runs each read the same state,
    and the second write erased the first. Reproduced with two real processes
    whose read_state is slowed so their reads overlap; each marks a different
    key. With the lock across the read and the write, both marks survive."""

    RACER = r'''
import sys, time, glob, contextlib, importlib.util
spec = importlib.util.spec_from_file_location("fleet_api_key", sys.argv[1])
k = importlib.util.module_from_spec(spec); sys.modules["fleet_api_key"] = k
spec.loader.exec_module(k)
real = k.read_state
def slow():
    s = real(); time.sleep(0.6); return s
k.read_state = slow
if sys.argv[3] == "unlocked":
    k.state_lock = contextlib.nullcontext
open(sys.argv[4], "w").close()
while len(glob.glob(sys.argv[5])) < 2:
    time.sleep(0.01)
k.mark_exhausted(int(sys.argv[2]))
'''

    def _race(self, mode):
        racer = os.path.join(self.tmp.name, "racer.py")
        with open(racer, "w") as fh:
            fh.write(self.RACER)
        os.environ["KIPI_FLEET_NOW"] = NOW
        keymod.write_state(keymod._blank_state())
        ready = os.path.join(self.tmp.name, "ready-%s-*" % mode)
        procs = [subprocess.Popen(
            [sys.executable, racer, os.path.join(SCRIPTS, "fleet_api_key.py"),
             str(slot), mode, os.path.join(self.tmp.name, "ready-%s-%d" % (mode, slot)),
             ready], env=dict(os.environ)) for slot in (1, 2)]
        for p in procs:
            self.assertEqual(p.wait(timeout=30), 0)
        return keymod.read_state()["exhausted"]

    def test_negative_self_test_without_the_lock_an_update_is_lost(self):
        marks = self._race("unlocked")
        self.assertEqual(len(marks), 1,
                         "the race did not reproduce, so the locked case proves nothing: %r"
                         % marks)

    def test_with_the_lock_both_marks_survive(self):
        marks = self._race("locked")
        self.assertEqual(sorted(marks), ["1", "2"], "an update was lost: %r" % marks)


class TestARunWithNoReadableCostIsUnmetered(Base):
    """PR #717 review round 3, minor 3. A run whose stdout was not the JSON
    envelope was booked cost 0 with ok:true and nothing else, so the ledger
    called it free and the report printed no FLOOR caveat."""

    def _plain_fake(self, body):
        with open(self.fake, "w") as fh:
            fh.write("#!/usr/bin/env python3\nimport os, sys\n"
                     "open(os.environ['FAKE_CLAUDE_RECORD'], 'a').write('{}\\n')\n"
                     + body)

    def _rows(self):
        with open(os.environ["KIPI_FLEET_SPEND_LEDGER"]) as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def test_plain_text_output_is_an_unmetered_row(self):
        self._plain_fake("print('just text, no envelope')\n")
        self.assertEqual(self.run_exec(), 0)
        row = self._rows()[-1]
        self.assertTrue(row.get("unmetered"), "a run nobody could price was booked free")
        self.assertEqual(spend.unmetered_today(), 1)

    def test_an_envelope_without_a_cost_is_unmetered_too(self):
        self._plain_fake("import json\nprint(json.dumps({'result': 'hi'}))\n")
        self.assertEqual(self.run_exec(), 0)
        self.assertTrue(self._rows()[-1].get("unmetered"))

    def test_a_priced_envelope_is_metered(self):
        self.assertEqual(self.run_exec(), 0)
        self.assertFalse(self._rows()[-1].get("unmetered"))
        self.assertEqual(spend.unmetered_today(), 0)


class TestEvents(Base):
    def test_a_failover_leaves_an_event_for_the_daily_report(self):
        self.kill_key_1()
        self.run_exec()
        kinds = [e["kind"] for e in spend.events()]
        self.assertIn("failover", kinds)

    def test_a_pause_and_a_resume_both_leave_events(self):
        os.environ["KIPI_FLEET_NOW"] = NOW
        os.environ["FAKE_CLAUDE_DEAD_KEY"] = DEAD_KEY
        os.environ["KIPI_FLEET_FAKE_KEY_1"] = DEAD_KEY
        os.environ["KIPI_FLEET_FAKE_KEY_2"] = DEAD_KEY
        self.run_exec()
        self.assertIn("pause", [e["kind"] for e in spend.events()])

        os.environ["KIPI_FLEET_NOW"] = NEXT_DAY
        os.environ["KIPI_FLEET_FAKE_KEY_1"] = LIVE_KEY_1
        os.environ.pop("FAKE_CLAUDE_DEAD_KEY")
        self.run_exec()
        self.assertIn("resume", [e["kind"] for e in spend.events()])


class TestTheSuiteClock(unittest.TestCase):
    """PR #717 review round 2, finding 3 (minor).

    The clock was the epoch literal 1762700400 with `# 2026-11-09` beside it, and
    the number is 2025-11-09. Nothing was computed wrongly -- the suites are
    internally consistent either way -- but every date in their comments and in
    the report suite's own printed output named a year the code was not using,
    which is how a later reader derives a window from the wrong month. This case
    is what makes the clock's own label checkable rather than commented.
    """

    def setUp(self):
        self._saved = dict(os.environ)
        os.environ["KIPI_DISPATCH_RESET_HOUR"] = "7"
        os.environ["KIPI_FLEET_NOW"] = NOW

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)

    def test_the_clock_is_the_date_its_name_claims(self):
        self.assertEqual(spend.now().strftime("%Y-%m-%d %H:%M"), "2026-11-09 12:00")
        self.assertEqual(spend.budget_day(), "2026-11-09")

    def test_the_next_day_constant_is_the_next_budget_day(self):
        os.environ["KIPI_FLEET_NOW"] = NEXT_DAY
        self.assertEqual(spend.budget_day(), "2026-11-10")

    def test_the_cycle_constants_straddle_the_reset(self):
        os.environ["KIPI_FLEET_NOW"] = NOV_26_0300
        self.assertEqual(spend.budget_day(), "2026-11-25")
        os.environ["KIPI_FLEET_NOW"] = NOV_26_0800
        self.assertEqual(spend.budget_day(), "2026-11-26")
        os.environ["KIPI_FLEET_NOW"] = DEC_FIRST
        self.assertEqual(spend.budget_day(), "2026-12-01")


class TestProbeAnswersAboutKEYS(Base):
    """PR #717 review round 2, finding 1 (major).

    `probe` asked `usable_slot()`, which answers from the credit ledger and the
    pause state and knows nothing about whether a key EXISTS. With nothing in the
    Keychain -- which is the state on merge day, because nothing in this PR
    creates the two items -- probe printed `key 1` and exited 0, the dispatcher's
    gate read green, and every run it launched then died at `read_key` with exit
    4: no spend row, no event, no ticket. The daily report read as a quiet day.
    """

    def _probe(self):
        buf = io.StringIO()
        saved, sys.stdout = sys.stdout, buf
        try:
            rc = keymod._main(["probe"])
        finally:
            sys.stdout = saved
        return rc, buf.getvalue().strip()

    def _no_keys(self):
        os.environ.pop("KIPI_FLEET_FAKE_KEY_1", None)
        os.environ.pop("KIPI_FLEET_FAKE_KEY_2", None)

    def test_probe_is_green_with_a_key_and_a_live_credit(self):
        rc, out = self._probe()
        self.assertEqual(rc, 0)
        self.assertEqual(out, "key 1")

    def test_probe_is_red_when_nothing_is_in_the_keychain(self):
        self._no_keys()
        rc, out = self._probe()
        self.assertEqual(rc, keymod.EXIT_NO_KEY,
                         "probe answered green with no key installed")
        self.assertIn("no key", out)

    def test_an_installed_key_2_does_not_mask_a_missing_key_1(self):
        """The partial install is the worse shape: `read_key` returns None before
        any refusal is detected, so there is no failover either -- the fleet
        wedges on the slot whose item was never created."""
        os.environ.pop("KIPI_FLEET_FAKE_KEY_1", None)
        rc, out = self._probe()
        self.assertEqual(rc, keymod.EXIT_NO_KEY)
        self.assertIn("no key", out)
        self.assertIn("1", out, "the page has to name which slot is missing")

    def test_a_missing_key_leaves_one_event_a_day_not_ninety_six(self):
        """The dispatcher probes every 15 minutes. One row a budget day is signal;
        96 is the noise that gets an alert channel muted."""
        # THE SUITE CLOCK, not the wall clock: the assertions below name the
        # budget days 2026-11-09 and -10. Without this line the case read the
        # real clock and passed only while the local budget day was 2026-11-09
        # (green at 03:48Z, red from 15:00Z the same day).
        os.environ["KIPI_FLEET_NOW"] = NOW
        self._no_keys()
        for _ in range(5):
            self._probe()
        self.assertEqual(
            [e["kind"] for e in spend.events(day="2026-11-09")].count("no_key"), 1,
            "a 15-minute reader turned one condition into N events")
        os.environ["KIPI_FLEET_NOW"] = NEXT_DAY
        self._probe()
        self.assertEqual(
            [e["kind"] for e in spend.events(day="2026-11-10")].count("no_key"), 1,
            "the next budget day earns its own event")
        self.assertEqual(
            [e["kind"] for e in spend.events(day="2026-11-09")].count("no_key"), 1,
            "the new day's event rewrote yesterday's")

    def test_probe_stays_a_reader_even_when_it_goes_red(self):
        """`usable_slot(consume=False)` exists because a 15-minute reader used to
        burn the paused fleet's one daily re-probe. The missing-key answer must
        not reintroduce that: it writes an EVENT, never the key state."""
        self._no_keys()
        before = keymod.read_state()
        self._probe()
        self.assertEqual(keymod.read_state(), before,
                         "a red probe rewrote the key state")

    def test_a_run_with_no_key_also_leaves_the_event(self):
        """Belt and braces for the case where dispatch is bypassed: the trace has
        to exist whether the gate or the run is the thing that noticed."""
        self._no_keys()
        self.assertEqual(self.run_exec(), keymod.EXIT_NO_KEY)
        self.assertIn("no_key", [e["kind"] for e in spend.events()])

    def test_presence_never_reads_the_secret_itself(self):
        """`key_present` answers yes/no. It must not be a wrapper that pulls the
        key into this process, because the founder's constraint is that a key
        never lands anywhere a presence check could log it."""
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(keymod.key_present).lstrip())
        argv = [[c.value for c in n.elts if isinstance(c, ast.Constant)]
                for n in ast.walk(tree) if isinstance(n, ast.List)]
        self.assertTrue(argv, "no argv list found in key_present")
        flat = [v for row in argv for v in row]
        self.assertIn("find-generic-password", flat)
        self.assertNotIn("-w", flat,
                         "the presence check asked `security` for the password "
                         "itself; presence is answerable without it")


class TestAWatchdogKill(Base):
    """PR #717 review round 2, finding 2 (major, marked nonblocking).

    `linear-worker.sh` kills a hung run by process GROUP at 1800s (the rc=143 in
    this issue's own worker log). `spend.record` sits after `proc.communicate()`,
    so the kill lands before it and the ledger gets NOTHING: an Opus turn that
    really was charged is absent from the number the day's allowance is divided
    out of, and the fleet's own meter reads the day as cheaper than it was.

    The cost itself is unrecoverable -- `claude -p` prints `total_cost_usd` only
    at the end -- so the fix does not invent one. It makes the GAP countable: a
    row marked `unmetered`, which the report then names, so today's spend reads
    as a floor rather than a total.

    Reproduced the way the worker does it: a real subprocess in its own process
    group, killed with `killpg`. In-process SIGTERM would kill the test runner.
    """

    def _killed_run(self):
        os.environ["FAKE_CLAUDE_SLEEP"] = "60"
        proc = subprocess.Popen(
            [sys.executable, os.path.join(SCRIPTS, "fleet_api_key.py"),
             "exec", "--actor", "worker", "--", self.fake, "-p", "hello"],
            env=dict(os.environ), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, start_new_session=True)
        deadline = time.time() + 30
        while time.time() < deadline and not self.calls():
            time.sleep(0.05)
        self.assertTrue(self.calls(), "the fake claude never started; nothing to kill")
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        try:
            proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            self.fail("the SIGTERM handler did not let the process die")
        return proc

    def _rows(self):
        path = os.environ["KIPI_FLEET_SPEND_LEDGER"]
        if not os.path.exists(path):
            return []
        with open(path) as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def test_a_killed_run_still_leaves_a_row(self):
        self._killed_run()
        rows = self._rows()
        self.assertEqual(len(rows), 1,
                         "a killed run left the ledger empty: %r" % rows)
        self.assertEqual(rows[0]["slot"], 1)
        self.assertFalse(rows[0]["ok"])

    def test_the_row_says_its_cost_was_never_read(self):
        self._killed_run()
        row = self._rows()[0]
        self.assertTrue(row.get("unmetered"),
                        "the row claims a measured $0 for a run that was charged")
        self.assertIn("SIGTERM", row.get("note") or "")

    def test_an_unmetered_row_is_counted_so_the_report_can_say_so(self):
        self._killed_run()
        self.assertEqual(spend.unmetered_today(), 1)

    def test_the_handler_does_not_swallow_the_kill(self):
        """The worker reads the exit status. A handler that recorded and then
        exited 0 would turn a timeout into a success."""
        proc = self._killed_run()
        self.assertEqual(proc.returncode, -signal.SIGTERM,
                         "the process survived its own watchdog kill")

    def test_a_normal_run_records_exactly_one_metered_row(self):
        """The negative: the handler must not double-record, and an ordinary run
        must not be marked unmetered."""
        self.assertEqual(self.run_exec(), 0)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].get("unmetered"))
        self.assertEqual(spend.unmetered_today(), 0)


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
