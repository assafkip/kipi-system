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

    def test_only_a_temp_dir_fake_claude_skips_the_reading(self):
        # The 23 worker and dispatcher suites run a fake `claude` from a temp dir with no
        # seam set; on CI's Linux there is no `security`, so a real read stopped them all.
        # The real binary (measured 2026-11-26: ~/.local/share/claude/versions/2.1.332) is
        # outside every temp root, so it still gets the real reading: with no `security`
        # on PATH that reading fails, and the stop proves the skip did not apply.
        env = {k: v for k, v in self.env.items()
               if k not in ("KIPI_PLAN_USAGE_URL", "KIPI_PLAN_USAGE_TOKEN")}
        env["PATH"] = self.tmp
        fake = subprocess.run([sys.executable, str(GATE), "--binary", self.env["KIPI_CLAUDE_BIN"]],
                              env=env, capture_output=True, text=True)
        self.assertEqual(fake.returncode, 0, fake.stdout + fake.stderr)
        self.assertIn("temp-dir fake", fake.stdout)
        # A fixed path, never one beside this file: verify.sh runs the tests from a temp copy
        # of the tree, where "beside this file" is itself under a temp root (PR #885 round 3).
        outside = "/usr/local/bin/kipi-test-claude-not-temp"
        real = subprocess.run([sys.executable, str(GATE), "--binary", outside],
                              env=env, capture_output=True, text=True)
        self.assertEqual(real.returncode, 4, real.stdout + real.stderr)

    def test_a_cached_reading_from_another_login_is_not_used(self):
        import time
        with open(self.env["KIPI_PLAN_USAGE_STATE"], "w") as fh:
            json.dump({"pct": 1.0, "at": time.time(), "login": "Claude Code-credentials-other"}, fh)
        self.weekly(45.0)
        self.assertEqual(self.gate().returncode, 3)


if __name__ == "__main__":
    unittest.main()
