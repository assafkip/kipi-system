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


def _drive(bin_dir, state_dir, budget=3, wall=60, extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("KIPI_LUAR")}
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = PLUGIN_ROOT
    env["KIPI_LUAR_ENV_BUILD_TIMEOUT"] = str(budget)
    env["TMPDIR"] = state_dir
    env["KIPI_LUAR_CACHE_DIR"] = os.path.join(state_dir, "cache")   # never the live cache
    # Floor off unless a test sets it: these tests ran red on 2026-11-23 only
    # because the real disk sat at 4 GB, which is not what they test (ASK-5577).
    env["KIPI_LUAR_MIN_FREE_GB"] = "0"
    env.update(extra or {})
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

    def test_low_disk_refuses_with_the_named_error_and_never_runs_uv(self):
        with tempfile.TemporaryDirectory() as d:
            _fake_uv(d, "touch %s/uv-ran; exit 0" % d)
            out, _ = _drive(d, d, budget=5, extra={"KIPI_LUAR_MIN_FREE_GB": "99999999"})
            ran = os.path.exists(os.path.join(d, "uv-ran"))
        self.assertIn("LUAR_ENV_UNAVAILABLE", out)
        self.assertIn("MiB free", out)
        self.assertFalse(ran)

    def test_model_is_seeded_by_copy_and_child_gets_local_caches(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "srchf", "hub", "models--rrivera1849--LUAR-MUD")
            os.makedirs(src)
            open(os.path.join(src, "weights.bin"), "w").write("w")
            _fake_uv(d, 'echo "$UV_CACHE_DIR|$HF_HOME" > %s/seen; exit 0' % d)
            _drive(d, d, budget=5, extra={"KIPI_LUAR_SEED_HF": os.path.join(d, "srchf")})
            seen = open(os.path.join(d, "seen")).read().strip()
            copied = os.path.isfile(os.path.join(
                d, "cache", "hf", "hub", "models--rrivera1849--LUAR-MUD", "weights.bin"))
        self.assertEqual(seen, "%s|%s" % (os.path.join(d, "cache", "uv"),
                                          os.path.join(d, "cache", "hf")))
        self.assertTrue(copied)

    # ASK-5577, 2026-11-23: every CRM "Draft comment" failed with
    # LUAR_ENV_UNAVAILABLE at 4086 MiB free while ~/.cache/kipi-luar held a
    # built 4.4 GB env. The floor guards a BUILD; a built env needs none.
    def _built_cache(self, d, weights=True, torch=True):
        snap = os.path.join(d, "cache", "hf", "hub", "models--rrivera1849--LUAR-MUD",
                            "snapshots", "abc")
        os.makedirs(snap)
        open(os.path.join(snap, "config.json"), "w").write("{}")
        if weights:
            open(os.path.join(snap, "model.safetensors"), "w").write("w")
        # The real layout: environments-v2/<key>/<key2> -> archive-v0/<id> (venv).
        arch = os.path.join(d, "cache", "uv", "archive-v0", "id1")
        sp = os.path.join(arch, "lib", "python3.12", "site-packages")
        os.makedirs(os.path.join(d, "cache", "uv", "environments-v2", "k1"))
        os.symlink(arch, os.path.join(d, "cache", "uv", "environments-v2", "k1", "k2"))
        os.makedirs(os.path.join(sp, "transformers"))
        if torch:
            os.makedirs(os.path.join(sp, "torch"))

    def test_built_env_under_the_floor_is_reused_after_an_offline_check(self):
        with tempfile.TemporaryDirectory() as d:
            self._built_cache(d)
            # Succeeds only offline: a probe that would download cannot pass.
            _fake_uv(d, 'case "$*" in *--offline*) echo "$*" >> %s/offline;'
                        ' exit 0;; esac; echo "$*" >> %s/online; exit 0' % (d, d))
            out, _ = _drive(d, d, budget=5, extra={"KIPI_LUAR_MIN_FREE_GB": "99999999"})
            probed = os.path.exists(os.path.join(d, "offline"))
            online = open(os.path.join(d, "online")).read() if os.path.exists(
                os.path.join(d, "online")) else ""
        self.assertNotIn("LUAR_ENV_UNAVAILABLE", out)
        self.assertTrue(probed, out)
        self.assertNotIn('-c pass', online)       # no online build was attempted

    def test_built_env_whose_offline_check_fails_still_refuses_under_the_floor(self):
        with tempfile.TemporaryDirectory() as d:
            self._built_cache(d)
            _fake_uv(d, 'case "$*" in *--offline*) exit 3;; esac;'
                        ' touch %s/uv-built; exit 0' % d)
            out, _ = _drive(d, d, budget=5, extra={"KIPI_LUAR_MIN_FREE_GB": "99999999"})
            built = os.path.exists(os.path.join(d, "uv-built"))
        self.assertIn("LUAR_ENV_UNAVAILABLE", out)
        self.assertIn("MiB free", out)
        self.assertIn("offline reuse check failed (exit 3)", out)
        self.assertFalse(built)

    def test_reused_env_runs_the_worker_with_the_hub_offline(self):
        with tempfile.TemporaryDirectory() as d:
            self._built_cache(d)
            _fake_uv(d, 'case "$*" in *--worker*) echo "hub=$HF_HUB_OFFLINE" > %s/worker;; esac;'
                        ' exit 0' % d)
            _drive(d, d, budget=5, extra={"KIPI_LUAR_MIN_FREE_GB": "99999999"})
            seen = open(os.path.join(d, "worker")).read().strip()
        self.assertEqual(seen, "hub=1")

    def test_built_env_worker_keeps_the_hub_online(self):
        with tempfile.TemporaryDirectory() as d:
            _fake_uv(d, 'case "$*" in *--worker*) echo "hub=$HF_HUB_OFFLINE" > %s/worker;; esac;'
                        ' exit 0' % d)
            _drive(d, d, budget=5)
            seen = open(os.path.join(d, "worker")).read().strip()
        self.assertEqual(seen, "hub=")

    def _refuses_without_uv(self, d):
        _fake_uv(d, "touch %s/uv-ran; exit 0" % d)
        out, _ = _drive(d, d, budget=5, extra={"KIPI_LUAR_MIN_FREE_GB": "99999999"})
        self.assertIn("LUAR_ENV_UNAVAILABLE", out)
        self.assertIn("MiB free", out)
        self.assertFalse(os.path.exists(os.path.join(d, "uv-ran")))

    def test_model_dir_without_weights_is_not_reused(self):
        with tempfile.TemporaryDirectory() as d:
            self._built_cache(d, weights=False)     # an interrupted download
            self._refuses_without_uv(d)

    def test_half_downloaded_blob_is_not_reused(self):
        with tempfile.TemporaryDirectory() as d:
            self._built_cache(d)
            blobs = os.path.join(d, "cache", "hf", "hub", "models--rrivera1849--LUAR-MUD", "blobs")
            os.makedirs(blobs)
            open(os.path.join(blobs, "x.incomplete"), "w").write("")
            self._refuses_without_uv(d)

    def test_evicted_env_is_not_reinstalled_under_the_floor(self):
        with tempfile.TemporaryDirectory() as d:
            self._built_cache(d, torch=False)       # wheels may be cached, env is not
            self._refuses_without_uv(d)

    def test_reuse_has_its_own_hard_floor(self):
        with tempfile.TemporaryDirectory() as d:
            self._built_cache(d)
            _fake_uv(d, "touch %s/uv-ran; exit 0" % d)
            out, _ = _drive(d, d, budget=5, extra={"KIPI_LUAR_MIN_FREE_GB": "99999999",
                                                   "KIPI_LUAR_REUSE_MIN_FREE_GB": "99999999"})
            self.assertIn("LUAR_ENV_UNAVAILABLE", out)
            self.assertFalse(os.path.exists(os.path.join(d, "uv-ran")))

    def test_unbuilt_env_under_the_floor_refuses_without_probing(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "cache", "uv"))   # uv dir, no model
            _fake_uv(d, "touch %s/uv-ran; exit 0" % d)
            out, _ = _drive(d, d, budget=5, extra={"KIPI_LUAR_MIN_FREE_GB": "99999999"})
            ran = os.path.exists(os.path.join(d, "uv-ran"))
        self.assertIn("LUAR_ENV_UNAVAILABLE", out)
        self.assertIn("MiB free", out)
        self.assertFalse(ran)


if __name__ == "__main__":
    unittest.main()
