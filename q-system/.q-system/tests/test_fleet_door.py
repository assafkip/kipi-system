#!/usr/bin/env python3
"""The Python fleet door: how a Python call site reaches `claude -p` (ASK-4311).

FIXTURES ONLY. KIPI_TEST=1 and fake keys on every case, so the real helper
(fleet_api_key.py) never reads the macOS Keychain. The subject runs a FAKE
`claude` written into each case's tmpdir; the fake records what it was handed.

WHAT THESE CASES EXIST TO KILL:
  * a site that "goes through the door" while its child still runs on whatever
    key the caller inherited (or on no key, which bills the founder's plan);
  * a missing key that quietly falls back to the plan login;
  * a timeout that kills the helper and leaves the billed `claude` running as
    an orphan, unmetered (subprocess.run(timeout=) kills only the direct child);
  * a test that reaches the real Keychain because nobody set KIPI_TEST.
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import os
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
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


door = _load("fleet_door")
lean_call = _load("lean_call")

LIVE_KEY_1 = "fake-key-1-live"
INHERITED = "sk-ant-inherited-from-the-caller"

#: Records argv, the key it saw, its pid and its stdin, then answers like the CLI:
#: a JSON envelope when the door asked for one, plain text otherwise.
FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys, time
# stdin only when a case hands one over: under a runner whose stdin is a pipe
# that never closes (mutate.py), an unconditional read hung the baseline 300s.
stdin = sys.stdin.read() if os.environ.get("FAKE_READ_STDIN") else ""
with open(os.environ["FAKE_RECORD"], "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "key": os.environ.get("ANTHROPIC_API_KEY"),
                         "slot": os.environ.get("KIPI_FLEET_KEY_SLOT"),
                         "ticket_env": [k for k in ("KIPI_TICKET", "KIPI_FOCUS_GATE") if k in os.environ],
                         "pid": os.getpid(), "stdin": stdin}) + "\n")
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
who = os.environ.get("ANTHROPIC_API_KEY") or "plan"
if "--output-format" in sys.argv:
    print(json.dumps({"type": "result", "is_error": False, "subtype": "success",
                      "result": "ok from " + who, "total_cost_usd": 0.5}))
else:
    print("ok from " + who)
sys.exit(int(os.environ.get("FAKE_RC") or 0))
'''

def write_facts(path):
    """A billable key 1, shaped like ~/.config/kipi/fleet-api.json. Under KIPI_TEST
    the helper has no default facts file, and a key with no facts is never used.
    The cycle ends 20 days after the REAL now: these cases run on the real clock."""
    end = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=20))
    row = {"monthly_credit_usd": 200, "auto_reload_off_confirmed_at": "2026-11-10T21:00:00Z",
           "current_cycle_expires_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ")}
    with open(path, "w") as fh:
        json.dump({"keys": {"1": row, "2": dict(row)}}, fh)


#: A `security` that only records it was called. On PATH first in the case that
#: proves a test-context run never reaches the real Keychain.
FAKE_SECURITY = "#!/bin/sh\necho \"$*\" >> \"$FAKE_SECURITY_LOG\"\nexit 44\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.record = os.path.join(d, "calls.jsonl")
        self.fake = os.path.join(d, "claude")
        self._write_exe(self.fake, FAKE_CLAUDE)
        self.ledger = os.path.join(d, "spend.jsonl")
        self.facts = os.path.join(d, "fleet-api.json")
        write_facts(self.facts)
        self._saved = dict(os.environ)
        os.environ.update({
            "KIPI_FLEET_API_FACTS": self.facts,
            "KIPI_TEST": "1",
            "KIPI_FLEET_SPEND_LEDGER": self.ledger,
            "KIPI_FLEET_EVENTS": os.path.join(d, "events.jsonl"),
            "KIPI_FLEET_STATE": os.path.join(d, "state.json"),
            "KIPI_FLEET_FAKE_KEY_1": LIVE_KEY_1,
            "FAKE_RECORD": self.record,
            "ANTHROPIC_API_KEY": INHERITED,
            # These classes test the API-key door, which is opt-in since the plan became the
            # default (RULE-2026-11-26-PLAN45). The plan-path test sets 0 itself.
            "KIPI_FLEET_API_KEYS": "1",
            # A fresh 10% reading, so the plan path's weekly gate never reads the Keychain.
            "KIPI_PLAN_USAGE_STATE": os.path.join(d, "plan-usage.json"),
        })
        with open(os.environ["KIPI_PLAN_USAGE_STATE"], "w") as fh:
            json.dump({"pct": 10.0, "resets_at": "x", "at": time.time()}, fh)
        for k in ("KIPI_FLEET_FAKE_KEY_2", "KIPI_FLEET_KEY_SLOT",
                  "KIPI_FLEET_RUN", "FAKE_SLEEP", "KIPI_FLEET_NOW", "FAKE_READ_STDIN", "FAKE_RC"):
            os.environ.pop(k, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)
        self.tmp.cleanup()

    def _write_exe(self, path, body):
        with open(path, "w") as fh:
            fh.write(body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

    def calls(self):
        if not os.path.exists(self.record):
            return []
        with open(self.record) as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def rows(self):
        if not os.path.exists(self.ledger):
            return []
        with open(self.ledger) as fh:
            return [json.loads(line) for line in fh if line.strip()]


class TestTheDoorBillsTheFleetKey(Base):
    def test_the_child_gets_the_fleet_key_not_the_inherited_one(self):
        res = door.run([self.fake, "-p", "hi"], actor="t-site",
                       capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout, "ok from %s\n" % LIVE_KEY_1)
        (call,) = self.calls()
        self.assertEqual(call["key"], LIVE_KEY_1)
        self.assertEqual(call["slot"], "1")
        self.assertNotEqual(call["key"], INHERITED)

    def test_every_run_lands_in_the_spend_ledger_with_its_cost(self):
        door.run([self.fake, "-p", "hi"], actor="t-site", capture_output=True, text=True)
        (row,) = self.rows()
        self.assertEqual(row.get("actor"), "t-site")
        self.assertAlmostEqual(float(row.get("cost_usd", row.get("cost", -1))), 0.5)

    def test_the_caller_sees_its_own_argv_not_the_door_argv(self):
        res = door.run([self.fake, "-p", "hi"], actor="t", capture_output=True, text=True)
        self.assertEqual(res.args, [self.fake, "-p", "hi"])

    def test_stdin_input_reaches_the_child(self):
        os.environ["FAKE_READ_STDIN"] = "1"
        door.run([self.fake, "-p", "--model", "m"], actor="t", input="the packet",
                 capture_output=True, text=True)
        self.assertEqual(self.calls()[0]["stdin"], "the packet")


class TestNoKeyMeansNoRun(Base):
    def test_no_key_refuses_and_never_runs_the_plan(self):
        os.environ.pop("KIPI_FLEET_FAKE_KEY_1")
        res = door.run([self.fake, "-p", "hi"], actor="t-site",
                       capture_output=True, text=True)
        self.assertEqual(res.returncode, door.EXIT_NO_KEY)
        self.assertEqual(self.calls(), [], "the child ran with no fleet key: a plan fallback")

    def test_the_refusal_is_said_on_the_callers_stderr(self):
        os.environ.pop("KIPI_FLEET_FAKE_KEY_1")
        saved, sys.stderr = sys.stderr, _Capture()
        try:
            door.run([self.fake, "-p", "hi"], actor="t-site", capture_output=True, text=True)
            said = sys.stderr.text
        finally:
            sys.stderr = saved
        self.assertIn("t-site", said)
        self.assertIn("did NOT fall back to the plan", said)


class TestDoorRefusedTellsTheDoorFromTheChild(Base):
    """PR #736 review round 1: every Python site asks door_refused() to tell the
    machine's refusal (stop the batch, name the door) from a child's own exit 4."""

    def test_a_real_refusal_reads_as_refused(self):
        os.environ.pop("KIPI_FLEET_FAKE_KEY_1")
        res = door.run([self.fake, "-p", "hi"], actor="t", capture_output=True, text=True)
        self.assertTrue(door.door_refused(res))

    def test_a_child_that_exits_4_itself_is_not_the_door(self):
        os.environ["FAKE_RC"] = "4"
        res = door.run([self.fake, "-p", "hi"], actor="t", capture_output=True, text=True)
        self.assertEqual(res.returncode, 4)
        self.assertFalse(door.door_refused(res))

    def test_the_marker_names_no_path(self):
        self.assertNotIn("/", door.REFUSED)

    # ROUND 2 (PR #736): the REAL helper's refusal sentences, one case each, so a
    # reworded refusal turns this suite red instead of blinding door_refused().
    def _refused_with(self, facts=None, state=None):
        if facts is not None:
            with open(self.facts, "w") as fh:
                json.dump(facts, fh)
        if state is not None:
            with open(os.environ["KIPI_FLEET_STATE"], "w") as fh:
                json.dump(state, fh)
        res = door.run([self.fake, "-p", "hi"], actor="t", capture_output=True, text=True)
        return res, self.calls()

    def test_no_known_credit_is_a_refusal(self):
        os.environ["KIPI_FLEET_API_FACTS"] = os.path.join(self.tmp.name, "absent.json")
        res, calls = self._refused_with()
        self.assertEqual((door.door_refused(res), calls), (True, []), res.stderr)

    def test_auto_reload_unconfirmed_is_a_refusal(self):
        with open(self.facts) as fh:
            facts = json.load(fh)
        for row in facts["keys"].values():
            row["auto_reload_off_confirmed_at"] = None
        res, calls = self._refused_with(facts=facts)
        self.assertEqual((door.door_refused(res), calls), (True, []), res.stderr)

    def test_a_paused_fleet_is_a_refusal(self):
        spend = sys.modules.get("fleet_api_spend") or _load("fleet_api_spend")
        res, calls = self._refused_with(state={
            "active_slot": 1, "exhausted": {}, "paused": True,
            "paused_since": "2026-11-10T00:00:00", "last_probe_day": spend.budget_day()})
        self.assertEqual((door.door_refused(res), calls), (True, []), res.stderr)

    def test_a_helper_warning_then_a_child_exit_4_is_not_a_refusal(self):
        """The round-2 reproducer: an unreadable state file makes the helper warn
        with its prefix and run the child anyway; the child exits 4 itself."""
        with open(os.environ["KIPI_FLEET_STATE"], "w") as fh:
            fh.write("{not json")
        os.environ["FAKE_RC"] = "4"
        res = door.run([self.fake, "-p", "hi"], actor="t", capture_output=True, text=True)
        self.assertEqual(res.returncode, 4)
        self.assertIn("fleet_api_key:", res.stderr)
        self.assertEqual(len(self.calls()), 1, "the child must have run")
        self.assertFalse(door.door_refused(res))


class TestTimeoutKillsTheWholeRun(Base):
    def test_a_timeout_leaves_no_orphan_and_an_unmetered_row(self):
        os.environ["FAKE_SLEEP"] = "60"
        started = time.time()
        with self.assertRaises(subprocess.TimeoutExpired):
            door.run([self.fake, "-p", "hi"], actor="t", timeout=3,
                     capture_output=True, text=True)
        self.assertLess(time.time() - started, 30, "the stop did not land")
        (call,) = self.calls()
        deadline = time.time() + 5
        while time.time() < deadline and _alive(call["pid"]):
            time.sleep(0.1)
        self.assertFalse(_alive(call["pid"]),
                         "the billed claude outlived its caller's timeout")
        rows = self.rows()
        self.assertEqual(len(rows), 1, rows)
        self.assertTrue(rows[0].get("unmetered"), rows[0])


class TestOffSwitchIsLoud(Base):
    def test_keys_off_runs_the_plan_and_says_so(self):
        os.environ["KIPI_FLEET_API_KEYS"] = "0"
        saved, sys.stderr = sys.stderr, _Capture()
        try:
            res = door.run([self.fake, "-p", "hi"], actor="t", capture_output=True, text=True)
            said = sys.stderr.text
        finally:
            sys.stderr = saved
        self.assertEqual(res.stdout, "ok from plan\n")
        self.assertIsNone(self.calls()[0]["key"], "the plan path kept the inherited key")
        self.assertIn("bills the PLAN", said)
        self.assertEqual(self.rows(), [])


class TestRunForCallerFollowsTheParent(Base):
    def test_outside_a_fleet_run_it_bills_the_plan_with_the_key_stripped(self):
        res = door.run_for_caller([self.fake, "-p", "hi"], actor="t",
                                  capture_output=True, text=True)
        self.assertEqual(res.stdout, "ok from plan\n")
        self.assertIsNone(self.calls()[0]["key"])
        self.assertEqual(self.rows(), [], "a founder-session run reached the API ledger")

    def test_inside_a_fleet_run_it_goes_through_the_door(self):
        os.environ["KIPI_FLEET_KEY_SLOT"] = "2"   # set by the helper for a keyed parent
        res = door.run_for_caller([self.fake, "-p", "hi"], actor="t",
                                  capture_output=True, text=True)
        self.assertEqual(res.stdout, "ok from %s\n" % LIVE_KEY_1)
        self.assertEqual(len(self.rows()), 1)

    def test_a_launchd_fleet_job_marks_itself(self):
        os.environ["KIPI_FLEET_RUN"] = "1"
        door.run_for_caller([self.fake, "-p", "hi"], actor="t", capture_output=True, text=True)
        self.assertEqual(self.calls()[0]["key"], LIVE_KEY_1)


class TestATestNeverReachesTheRealKeychain(Base):
    def test_a_temp_dir_binary_forces_fixture_mode_without_kipi_test(self):
        os.environ.pop("KIPI_TEST")
        os.environ.pop("PYTEST_CURRENT_TEST", None)
        bindir = os.path.join(self.tmp.name, "bin")
        os.makedirs(bindir)
        self._write_exe(os.path.join(bindir, "security"), FAKE_SECURITY)
        log = os.path.join(self.tmp.name, "security.log")
        os.environ["FAKE_SECURITY_LOG"] = log
        os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
        res = door.run([self.fake, "-p", "hi"], actor="t", capture_output=True, text=True)
        self.assertFalse(os.path.exists(log), "the door asked the real Keychain from a test")
        self.assertEqual(res.stdout, "ok from %s\n" % LIVE_KEY_1)

    def test_fixture_mode_points_unset_ledgers_at_a_temp_dir(self):
        for k in ("KIPI_FLEET_SPEND_LEDGER", "KIPI_FLEET_EVENTS", "KIPI_FLEET_STATE"):
            os.environ.pop(k)
        env = door.door_env([self.fake, "-p", "x"])
        home = os.path.expanduser("~")
        for k in ("KIPI_FLEET_SPEND_LEDGER", "KIPI_FLEET_EVENTS", "KIPI_FLEET_STATE"):
            self.assertIn(k, env)
            self.assertFalse(env[k].startswith(os.path.join(home, ".local")), env[k])

    def test_the_door_env_never_carries_an_inherited_key(self):
        self.assertNotIn("ANTHROPIC_API_KEY", door.door_env([self.fake, "-p", "x"]))
        self.assertNotIn("ANTHROPIC_API_KEY", door.plan_env())


class TestLeanCallRidesTheDoor(Base):
    def test_lean_flags_and_the_key_both_reach_the_child(self):
        res = lean_call.run([self.fake, "-p", "hi"], capture_output=True, text=True,
                            runner=door.runner("t-lean"))
        self.assertEqual(res.returncode, 0, res.stderr)
        (call,) = self.calls()
        self.assertEqual(call["key"], LIVE_KEY_1)
        self.assertIn("--strict-mcp-config", call["argv"])
        self.assertEqual(call["argv"][call["argv"].index("--tools") + 1], "")
        self.assertEqual(self.rows()[0].get("actor"), "t-lean")


class _Capture:
    def __init__(self):
        self.text = ""

    def write(self, s):
        self.text += s

    def flush(self):
        pass


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie still answers kill(0); ps says whether it is really running.
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                         capture_output=True, text=True).stdout.strip()
    return bool(out) and not out.startswith("Z")



def _focus_gate(dirname, critical, active=True):
    path = os.path.join(dirname, "focus.json")
    with open(path, "w") as fh:
        json.dump({"active": active, "critical": critical}, fh)
    return path


class TestACriticalTicketRunsOnThePlan(Base):
    """Founder, 2026-11-24, verbatim: "for the critical jobs we use the normal account, not the
    api key. this is settled already". The earlier ruling is the focus gate's (2026-11-23):
    tickets off the critical list "wait for when the credits are back", so a critical one
    does not wait on credit. Live: the review of kipi-system PR #874 (ASK-5586, critical)
    refused "every known key's cycle credit is spent"."""

    def test_a_critical_ticket_bills_the_plan_and_says_so(self):
        import fleet_api_key as fak
        gate = _focus_gate(self.tmp.name, ["ASK-5586"])
        saved, sys.stderr = sys.stderr, _Capture()
        try:
            rc = fak.cmd_exec([self.fake, "-p", "hi"], actor="t", ticket="ask-5586",
                              focus_gate=gate)
            said = sys.stderr.text
        finally:
            sys.stderr = saved
        self.assertEqual(rc, 0)
        self.assertIsNone(self.calls()[-1]["key"])
        self.assertIn("critical ticket ASK-5586", said)
        self.assertEqual(self.rows(), [])

    def test_control_off_the_list_or_an_inactive_gate_names_nothing(self):
        gate = _focus_gate(self.tmp.name, ["ASK-5586"])
        self.assertEqual(door.critical_ticket("ask-5586", gate), "ASK-5586")
        self.assertIsNone(door.critical_ticket("ASK-9999", gate))
        self.assertIsNone(door.critical_ticket("", gate))
        self.assertIsNone(door.critical_ticket("ASK-5586", ""))
        off = _focus_gate(self.tmp.name, ["ASK-5586"], active=False)
        self.assertIsNone(door.critical_ticket("ASK-5586", off),
                          "an inactive focus gate names nothing critical")

    def test_exec_returns_the_childs_code_and_the_caller_lives_on(self):
        """PR #874 review round 3 (major): os.execvpe replaced an in-process caller."""
        import fleet_api_key as fak
        gate = _focus_gate(self.tmp.name, ["ASK-5586"])
        os.environ["FAKE_RC"] = "3"
        self.assertEqual(fak.cmd_exec([self.fake, "-p", "hi"], ticket="ASK-5586",
                                      focus_gate=gate), 3)
        self.assertIsNone(self.calls()[-1]["key"])

    def test_an_unrunnable_binary_is_127_and_a_sentence(self):
        """PR #874 review rounds 3 and 4 (minor): a missing binary, then one without +x."""
        import fleet_api_key as fak
        gate = _focus_gate(self.tmp.name, ["ASK-5586"])
        noexec = os.path.join(self.tmp.name, "claude-noexec")
        with open(noexec, "w") as fh:
            fh.write(FAKE_CLAUDE)
        for argv0 in (os.path.join(self.tmp.name, "no-such-binary"), noexec):
            saved, sys.stderr = sys.stderr, _Capture()
            try:
                rc = fak.cmd_exec([argv0, "-p", "hi"], ticket="ASK-5586", focus_gate=gate)
                said = sys.stderr.text
            finally:
                sys.stderr = saved
            self.assertEqual(rc, 127, argv0)
            self.assertIn("cannot run", said)


class TestTheShimCarriesTheTicketAsFlags(Base):
    """pr-review-agent.sh passes the ticket and gate as fleet-claude.sh's own leading flags; the
    shim reads no env for them, so nothing reaches the model or its tool runs
    (rca-critical-ticket-routing-test-isolation-2026-11-24, PR #875 round 1)."""

    def _shim(self, args, **env):
        shim = os.path.join(SCRIPTS, "fleet-claude.sh")
        full = dict(os.environ, KIPI_CLAUDE_BIN=self.fake)
        # Only what the case passes: a runner's own ambient ticket env (a reviewer session) is
        # not what these cases are about, and the nested whole-file run below sets it.
        for k in ("KIPI_TICKET", "KIPI_FOCUS_GATE"):
            full.pop(k, None)
        full["KIPI_FLEET_API_KEYS"] = "1"   # the key door; a case passes 0 for the plan
        full.update(env)
        return subprocess.run(["bash", shim] + args, env=full, capture_output=True,
                              text=True, timeout=60)

    def test_a_critical_ticket_by_flag_bills_the_plan(self):
        gate = _focus_gate(self.tmp.name, ["ASK-5586"])
        res = self._shim(["--kipi-ticket", "ASK-5586", "--kipi-focus-gate", gate, "-p", "hi"])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout, "ok from plan\n")
        call = self.calls()[-1]
        self.assertEqual(call["argv"], ["-p", "hi"])
        self.assertEqual(call["ticket_env"], [])

    def test_the_off_switch_drops_the_flags_too(self):
        gate = _focus_gate(self.tmp.name, ["ASK-5586"])
        res = self._shim(["--kipi-ticket", "ASK-5586", "--kipi-focus-gate", gate, "-p", "hi"],
                         KIPI_FLEET_API_KEYS="0")
        self.assertEqual(res.returncode, 0, res.stderr)
        call = self.calls()[-1]
        self.assertEqual(call["argv"], ["-p", "hi"])
        self.assertEqual(call["ticket_env"], [])

    def test_a_stray_kipi_flag_is_refused_not_handed_to_the_model(self):
        gate = _focus_gate(self.tmp.name, ["ASK-5586"])
        res = self._shim(["-p", "--kipi-ticket", "ASK-5586", "--kipi-focus-gate", gate, "hi"])
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertIn("--kipi-ticket", res.stderr)
        self.assertEqual(self.calls(), [])

    def test_an_ambient_ticket_env_is_ignored_by_the_shim(self):
        res = self._shim(["-p", "hi"], KIPI_TICKET="ASK-5586",
                         KIPI_FOCUS_GATE=_focus_gate(self.tmp.name, ["ASK-5586"]))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(LIVE_KEY_1, res.stdout)


class TestTheReviewerProducesTheFlags(unittest.TestCase):
    """PR #875 round 2: the shim cases never ran the producer, so deleting pr-review-agent.sh's
    routing block left every suite green, and the plan notice blinded the outage classifier."""

    AGENT = os.path.join(SCRIPTS, "pr-review-agent.sh")
    START, END = "# >>> critical-ticket routing", "# <<< critical-ticket routing"

    def _block(self):
        with open(self.AGENT) as fh:
            text = fh.read()
        self.assertIn(self.START, text, "the routing block is gone from pr-review-agent.sh")
        # From the line after the start marker: the marker line's tail is not code.
        block = text.split(self.START, 1)[1].split("\n", 1)[1].split(self.END, 1)[0]
        # It must run after ISSUE is final and before the reviewer line reads FLEET_CLAUDE.
        self.assertLess(text.index("ISSUE=\"$(printf '%s' \"$PR_TITLE\""), text.index(self.START))
        self.assertLess(text.index(self.END), text.index("KIPI_AGENT=pr-reviewer $FLEET_CLAUDE -p"))
        return block

    def _run(self, issue, **env):
        with tempfile.TemporaryDirectory() as home:
            # The script's own options (set -uo pipefail): an unset name in the block must
            # fail here as it would kill the agent before any status (PR #875 round 3).
            script = ('set -uo pipefail\nFLEET_CLAUDE=/s/fleet-claude.sh\nISSUE=%s\n%s\n'
                      'printf %%s "$FLEET_CLAUDE"' % (issue, self._block()))
            full = {"PATH": os.environ.get("PATH", ""), "HOME": home}
            full.update(env)
            res = subprocess.run(["bash", "-c", script], env=full, capture_output=True,
                                 text=True, timeout=30)
            self.assertEqual(res.returncode, 0, res.stderr)
            if issue and "KIPI_FLEET_CLAUDE" not in env and env.get("KIPI_FLEET_API_KEYS") != "0":
                self.assertEqual(res.stderr, "")
            return res.stdout, home

    def test_a_ticket_reaches_the_shim_as_leading_flags(self):
        out, home = self._run("ASK-5586")
        self.assertEqual(out, "/s/fleet-claude.sh --kipi-ticket 'ASK-5586' --kipi-focus-gate "
                              "'%s/.config/kipi/focus-gate/focus.json'" % home)

    def test_control_the_off_switch_or_an_override_adds_nothing(self):
        self.assertEqual(self._run("ASK-5586", KIPI_FLEET_API_KEYS="0")[0], "/s/fleet-claude.sh")
        self.assertEqual(self._run("ASK-5586", KIPI_FLEET_CLAUDE="/x")[0], "/s/fleet-claude.sh")
        self.assertEqual(self._run("")[0], "/s/fleet-claude.sh")

    def test_the_plan_notice_does_not_hide_an_outage(self):
        lib = os.path.join(SCRIPTS, "env-failure-lib.sh")
        notice = ("fleet_api_key: critical ticket ASK-5586 -- this run bills the PLAN, not the "
                  "API credit (founder 2026-11-24)")
        def env_fail(payload):
            return subprocess.run(["bash", "-c", '. "$1"; is_environmental "$2"', "_", lib,
                                   payload], capture_output=True, timeout=30).returncode == 0
        self.assertTrue(env_fail(notice + "\nPlease run /login"))
        self.assertFalse(env_fail(notice + "\nThe fix looks right."), "an answer is not an outage")


class TestNoTestCanReachTheLiveFocusGate(Base):
    """RCA rca-critical-ticket-routing-test-isolation-2026-11-24 (PR #874 rounds 3 and 4): the
    gate was read from ambient KIPI_TICKET plus a default ~/.config path, and every guess at
    "am I under a test" missed a runner (python3 <file>, python3 -m unittest). The gate is now
    an explicit argument with no default, and no door code reads the ticket from the env, so
    no runner can reach the live file."""

    def test_critical_ticket_takes_the_gate_path_explicitly_with_no_default(self):
        import inspect
        params = inspect.signature(door.critical_ticket).parameters
        self.assertIn("gate_path", params)
        for name, p in params.items():
            self.assertIs(p.default, inspect.Parameter.empty, "%s has a default" % name)

    def test_an_ambient_critical_ticket_never_reroutes_the_door(self):
        # The exact env a review of a critical ticket used to hand every child.
        os.environ["KIPI_TICKET"] = "ASK-5586"
        os.environ["KIPI_FOCUS_GATE"] = _focus_gate(self.tmp.name, ["ASK-5586"])
        res = door.run([self.fake, "-p", "hi"], actor="t", capture_output=True, text=True)
        self.assertEqual(res.stdout, "ok from %s\n" % LIVE_KEY_1)

    def test_the_whole_file_is_green_under_its_own_main_with_a_critical_env(self):
        """Round 4 ran `python3 test_fleet_door.py`; pytest was the only runner proven. The whole
        file, not chosen classes (PR #875 round 1: the class left out was the one that failed)."""
        if os.environ.get("KIPI_FLEET_DOOR_NESTED") == "1":
            self.skipTest("the nested run of this file")
        env = dict(self._saved)
        env.update({"KIPI_TICKET": "ASK-5586", "KIPI_FLEET_DOOR_NESTED": "1",
                    "KIPI_FOCUS_GATE": _focus_gate(self.tmp.name, ["ASK-5586"])})
        env.pop("KIPI_TEST", None)
        env.pop("KIPI_FLEET_API_KEYS", None)
        res = subprocess.run([sys.executable, os.path.abspath(__file__)],
                             env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(res.returncode, 0, res.stderr[-2000:])
        self.assertIn("OK", res.stderr.strip().splitlines()[-1])


if __name__ == "__main__":
    unittest.main()
