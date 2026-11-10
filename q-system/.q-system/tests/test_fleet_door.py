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
                         "pid": os.getpid(), "stdin": stdin}) + "\n")
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
who = os.environ.get("ANTHROPIC_API_KEY") or "plan"
if "--output-format" in sys.argv:
    print(json.dumps({"type": "result", "is_error": False, "subtype": "success",
                      "result": "ok from " + who, "total_cost_usd": 0.5}))
else:
    print("ok from " + who)
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
        })
        for k in ("KIPI_FLEET_FAKE_KEY_2", "KIPI_FLEET_API_KEYS", "KIPI_FLEET_KEY_SLOT",
                  "KIPI_FLEET_RUN", "FAKE_SLEEP", "KIPI_FLEET_NOW", "FAKE_READ_STDIN"):
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


if __name__ == "__main__":
    unittest.main()
