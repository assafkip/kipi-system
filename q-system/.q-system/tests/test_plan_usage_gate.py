"""The Sana ticket fleet bills the plan and stops at 45% weekly (RULE-2026-11-26-PLAN45).

Founder, 2026-11-26: "Move the fleet work to the claude account - Ensure it stops when
usage gets to 45% of the weekly usage".

Drives the real gate, the real shim (fleet-claude.sh) and the real Python door
(fleet_door.run) against a local stand-in for the usage endpoint, with a fake `claude`
that records whether it ran and whether it saw an API key. No Keychain, no network.
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "q-system/.q-system/scripts"
GATE = SCRIPTS / "plan_usage_gate.py"
SHIM = SCRIPTS / "fleet-claude.sh"


class _Usage(http.server.BaseHTTPRequestHandler):
    reply = (200, {"seven_day": {"utilization": 10.0, "resets_at": "2026-12-01T21:00:00Z"}})

    def do_GET(self):
        code, body = type(self).reply
        raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


class PlanUsageGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), _Usage)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mark = os.path.join(self.tmp, "ran")
        fake = os.path.join(self.tmp, "claude")
        with open(fake, "w") as fh:
            fh.write('#!/bin/sh\necho "key=${ANTHROPIC_API_KEY:-none}" > "%s"\n'
                     '[ -n "$FAKE_SAY" ] && echo "$FAKE_SAY" >&2\nexit 0\n' % self.mark)
        os.chmod(fake, 0o755)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("KIPI_")}
        self.env.update({
            "KIPI_PLAN_USAGE_URL": "http://127.0.0.1:%d/usage" % self.srv.server_port,
            "KIPI_PLAN_USAGE_TOKEN": "test-token",
            "KIPI_PLAN_USAGE_STATE": os.path.join(self.tmp, "state.json"),
            "KIPI_CLAUDE_BIN": fake,
            "ANTHROPIC_API_KEY": "sk-should-be-stripped",
            "KIPI_FLEET_API_KEY_SLOT": "",
            "KIPI_PLAN_USAGE_LOG": os.path.join(self.tmp, "gate.log"),
            # The repo's one under-test signal (fleet_door.in_test). The seams above are read
            # only under it, so this class drives the real stop logic and nothing live.
            "KIPI_TEST": "1",
        })

    def weekly(self, pct):
        _Usage.reply = (200, {"seven_day": {"utilization": pct, "resets_at": "x"}})

    def gate(self):
        return subprocess.run([sys.executable, str(GATE)], env=self.env, capture_output=True, text=True)

    def shim(self):
        return subprocess.run(["bash", str(SHIM), "-p", "hi"], env=self.env, capture_output=True, text=True)

    def test_gate_line(self):
        self.weekly(44.0)
        self.assertEqual(self.gate().returncode, 0)
        os.remove(self.env["KIPI_PLAN_USAGE_STATE"])
        self.weekly(45.0)
        r = self.gate()
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertIn("RULE-2026-11-26-PLAN45", r.stdout)

    def test_gate_fails_closed(self):
        _Usage.reply = (500, "boom")
        self.assertEqual(self.gate().returncode, 4)
        _Usage.reply = (200, {"no": "week"})
        self.assertEqual(self.gate().returncode, 4)
        self.assertFalse(os.path.exists(self.env["KIPI_PLAN_USAGE_STATE"]), "a failed read is never cached")

    def test_shim_default_bills_plan_under_line(self):
        self.weekly(17.0)
        r = self.shim()
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.mark) as fh:
            self.assertEqual(fh.read().strip(), "key=none", "the plan run must not see an API key")

    def test_shim_stops_at_line(self):
        self.weekly(45.0)
        r = self.shim()
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertFalse(os.path.exists(self.mark), "claude ran past the 45% line")

    def test_shim_stops_when_unreadable(self):
        _Usage.reply = (401, "nope")
        r = self.shim()
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertFalse(os.path.exists(self.mark))

    def test_python_door_stops_at_line(self):
        self.weekly(46.0)
        code = ("import sys; sys.path.insert(0, %r); import fleet_door; "
                "r = fleet_door.run([%r, '-p', 'hi'], 'test'); sys.exit(r.returncode)"
                % (str(SCRIPTS), self.env["KIPI_CLAUDE_BIN"]))
        r = subprocess.run([sys.executable, "-c", code], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertFalse(os.path.exists(self.mark))

    def test_python_door_bills_plan_under_line(self):
        self.weekly(17.0)
        code = ("import sys; sys.path.insert(0, %r); import fleet_door; "
                "r = fleet_door.run([%r, '-p', 'hi'], 'test'); sys.exit(r.returncode)"
                % (str(SCRIPTS), self.env["KIPI_CLAUDE_BIN"]))
        r = subprocess.run([sys.executable, "-c", code], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.mark) as fh:
            self.assertEqual(fh.read().strip(), "key=none")


    # --- PR #885 review round 1. The worker (2>&1 | tee), the heartbeat (2>&1 | tee, then
    # is_environmental before its per-instance failure path) and the reviewer all classify
    # the shim's output with env-failure-lib.sh. A stop must read as the machine refusing,
    # and a run must add no line, or a real plan outage reads as a ticket failure.
    def environmental(self, text):
        lib = SCRIPTS / "env-failure-lib.sh"
        r = subprocess.run(["bash", "-c", '. "$1"; is_environmental "$2"', "_", str(lib), text])
        return r.returncode == 0

    def test_a_run_adds_no_line_so_a_real_outage_still_reads_as_one(self):
        self.weekly(17.0)
        self.env["FAKE_SAY"] = "You've hit your 5-hour limit - resets 3pm (America/Los_Angeles)"
        r = subprocess.run(["bash", "-c", 'bash "$1" -p hi 2>&1', "_", str(SHIM)],
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), self.env["FAKE_SAY"], "the shim spoke on a run")
        self.assertTrue(self.environmental(r.stdout))

    def test_a_stop_reads_as_the_machine_refusing_not_the_ticket_failing(self):
        for reply, want in (((200, {"seven_day": {"utilization": 45.0}}), 3), ((401, "nope"), 4)):
            _Usage.reply = reply
            if os.path.exists(self.env["KIPI_PLAN_USAGE_STATE"]):
                os.remove(self.env["KIPI_PLAN_USAGE_STATE"])
            r = self.shim()
            self.assertEqual(r.returncode, want, r.stderr)
            self.assertTrue(self.environmental(r.stderr), r.stderr)

    def test_the_python_door_stop_reads_as_environmental(self):
        self.weekly(46.0)
        code = ("import sys; sys.path.insert(0, %r); import fleet_door; "
                "r = fleet_door.run([%r, '-p', 'hi'], 'test', capture_output=True, text=True); "
                "print(r.stderr, end='')" % (str(SCRIPTS), self.env["KIPI_CLAUDE_BIN"]))
        r = subprocess.run([sys.executable, "-c", code], env=self.env, capture_output=True, text=True)
        self.assertTrue(self.environmental(r.stdout), r.stdout)

    def _sentinel_env(self):
        """No seams, no `security` on PATH, HOME a sentinel dir: the live path, if taken,
        can only show up as a file under the sentinel or a `security` error."""
        home = os.path.join(self.tmp, "home")
        os.makedirs(home)
        env = {k: v for k, v in self.env.items() if not k.startswith("KIPI_")
               and k != "PYTEST_CURRENT_TEST"}
        env.update({"PATH": self.tmp, "HOME": home})
        return env, home

    def _files_under(self, d):
        return [os.path.join(r, f) for r, _, fs in os.walk(d) for f in fs]

    def test_no_test_signal_reaches_the_live_account(self):
        # PR #885 rounds 2 and 3: the dispatcher suite (KIPI_TEST=1, real `claude`) read
        # the founder's Keychain and overwrote ~/.local/state/kipi/plan-usage.json. Every
        # signal fleet_door.in_test knows must keep the gate off the live path.
        # (rca-pr885-plan-gate-test-isolation-2026-11-26)
        signals = [
            ("KIPI_TEST=1", {"KIPI_TEST": "1"}, "/usr/bin/true"),
            ("pytest running", {"PYTEST_CURRENT_TEST": "x (call)"}, "/usr/bin/true"),
            ("temp-dir fake by path", {}, self.env["KIPI_CLAUDE_BIN"]),
            ("temp-dir fake found on PATH", {}, "claude"),
        ]
        for name, extra, binary in signals:
            with self.subTest(name):
                env, home = self._sentinel_env()
                env.update(extra)
                r = subprocess.run([sys.executable, str(GATE), "--binary", binary],
                                   env=env, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("live account is never read", r.stdout)
                self.assertEqual(self._files_under(home), [], "a test wrote a live path")
                os.rmdir(home)

    def test_without_a_test_signal_the_live_path_is_taken(self):
        # The negative half: same sentinel env, no signal, a literal non-temp binary. The
        # gate must try the Keychain (absent here, so rc 4 naming `security`) and write the
        # live log under HOME. If this ever reads "run", the test mode has leaked into
        # production. Seams set here must be ignored outside a test.
        env, home = self._sentinel_env()
        env["KIPI_PLAN_USAGE_URL"] = self.env["KIPI_PLAN_USAGE_URL"]
        env["KIPI_PLAN_USAGE_TOKEN"] = "test-token"
        self.weekly(10.0)
        r = subprocess.run([sys.executable, str(GATE), "--binary", "/usr/bin/true"],
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("security", r.stdout)
        self.assertTrue(os.path.exists(os.path.join(home, ".local/state/kipi/plan-usage-gate.log")))

    def test_a_keychain_failure_names_security_and_the_item(self):
        # PR #887 round 1: security's rc and stderr were dropped, so every Keychain
        # failure read "Expecting value: line 1 column 1 (char 0)".
        env, home = self._sentinel_env()
        sec = os.path.join(self.tmp, "security")
        with open(sec, "w") as fh:
            fh.write("#!/bin/sh\necho 'The specified item could not be found in the keychain.' >&2\nexit 44\n")
        os.chmod(sec, 0o755)
        r = subprocess.run([sys.executable, str(GATE), "--binary", "/usr/bin/true"],
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("Keychain item 'Claude Code-credentials' (rc 44", r.stdout)
        self.assertIn("could not be found", r.stdout)

    def test_the_unreadable_page_body_is_constant(self):
        # PR #887 round 1, major: the page interpolated the gate's varying error text, so
        # page_once's hash changed per wording and alert-to-linear filed one undeletable
        # ticket per wording. The page_once line must carry no gate output.
        src = (REPO / "kipi-dispatch.sh").read_text()
        lines = [ln for ln in src.splitlines() if "page_once plan-usage-unreadable" in ln]
        self.assertEqual(len(lines), 1, lines)
        self.assertNotIn("$PLAN_GATE_LINE", lines[0])
        self.assertNotIn("$PLAN_GATE_RC", lines[0])

    def test_tmpdir_holding_home_is_not_a_temp_root(self):
        # TMPDIR=$HOME made the real install under ~/.local read as a fake (round 3 minor).
        import pwd
        home = os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)
        code = ("import sys; sys.path.insert(0, %r); import fleet_door; "
                "print(any(%r == r or %r.startswith(r.rstrip('/') + '/') for r in fleet_door._temp_roots()))"
                % (str(SCRIPTS), home, home))
        for tmpdir in (home, os.path.dirname(home), "/"):
            with self.subTest(tmpdir):
                r = subprocess.run([sys.executable, "-c", code], env=dict(self.env, TMPDIR=tmpdir),
                                   capture_output=True, text=True)
                self.assertEqual(r.stdout.strip(), "False", r.stderr)

    def test_a_cached_reading_from_another_login_is_not_used(self):
        import time
        with open(self.env["KIPI_PLAN_USAGE_STATE"], "w") as fh:
            json.dump({"pct": 1.0, "at": time.time(), "login": "Claude Code-credentials-other"}, fh)
        self.weekly(45.0)
        self.assertEqual(self.gate().returncode, 3)


if __name__ == "__main__":
    unittest.main()
