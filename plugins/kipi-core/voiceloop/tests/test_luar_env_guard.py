"""ASK-3515: the LUAR uv env is built once, bounded, and fails fast with a name.

Scar, 2026-10-30: after a disk-full event, 30 xdist workers each ran their own
`uv run --with-requirements ...`, sat at 0% CPU, and two commits hung 54 and 77
minutes. These tests drive the real `encode_via_declared_env` in a child
interpreter against a FAKE uv that never finishes. Nothing here touches a real
uv, a real cache, or a real path: the fake lives in a temp dir on PATH.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DRIVER = r'''
import sys, time
from voiceloop import luar_env_backend as b
from voiceloop.luar_scorer import ScorerUnavailable
t = time.monotonic()
try:
    b.encode_via_declared_env(["x"])
    print("NO-ERROR")
except ScorerUnavailable as exc:
    print("ERR", exc)
print("ELAPSED %.1f" % (time.monotonic() - t))
'''


def _fake_uv(dirpath, body):
    p = os.path.join(dirpath, "uv")
    with open(p, "w") as fh:
        fh.write("#!/bin/sh\n" + body + "\n")
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)


def _drive(bin_dir, state_dir, budget=3, wall=60):
    env = {k: v for k, v in os.environ.items() if not k.startswith("KIPI_LUAR")}
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = PLUGIN_ROOT
    env["KIPI_LUAR_ENV_BUILD_TIMEOUT"] = str(budget)
    env["TMPDIR"] = state_dir
    if state_dir:
        env["KIPI_LUAR_ENV_STATE_DIR"] = state_dir
    t = time.monotonic()
    r = subprocess.run([sys.executable, "-c", DRIVER], env=env, cwd=PLUGIN_ROOT,
                       capture_output=True, text=True, timeout=wall)
    return r.stdout + r.stderr, time.monotonic() - t


class LuarEnvGuard(unittest.TestCase):
    def test_hung_uv_fails_fast_with_the_named_error(self):
        with tempfile.TemporaryDirectory() as d:
            _fake_uv(d, "exec sleep 600")        # a uv that never finishes
            out, secs = _drive(d, d, budget=3)
        self.assertIn("LUAR_ENV_UNAVAILABLE", out)
        self.assertIn("timed out after 3s", out)
        self.assertLess(secs, 20, out)           # old code waits 900s here

    def test_second_call_in_the_run_fails_at_once_from_the_verdict(self):
        with tempfile.TemporaryDirectory() as d:
            _fake_uv(d, "exec sleep 600")
            _drive(d, d, budget=3)
            out, secs = _drive(d, d, budget=3)
        self.assertIn("LUAR_ENV_UNAVAILABLE", out)
        self.assertLess(secs, 2.5, out)          # no second 3s build attempt

    def test_failing_build_names_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            _fake_uv(d, "echo no space left >&2; exit 7")
            out, _ = _drive(d, d, budget=5)
        self.assertIn("LUAR_ENV_UNAVAILABLE", out)
        self.assertIn("exit 7", out)

    def test_negative_control_a_good_env_is_not_blamed(self):
        # A uv that builds (exit 0) and then runs the worker: the env step must
        # pass, so the failure we see is the worker's, never LUAR_ENV_UNAVAILABLE.
        with tempfile.TemporaryDirectory() as d:
            _fake_uv(d, "exit 0")
            out, _ = _drive(d, d, budget=5)
        self.assertNotIn("LUAR_ENV_UNAVAILABLE", out)


if __name__ == "__main__":
    unittest.main()
