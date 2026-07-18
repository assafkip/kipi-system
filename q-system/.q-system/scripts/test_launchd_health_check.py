#!/usr/bin/env python3
"""Regression tests for launchd-health-check.py (the silent-job-death watchdog).

Covers the two pure decision functions. The launchd end-to-end path (creating a
failing job, kickstarting it, reading LastExitStatus) is macOS-launchd-specific and
verified manually on wiring; these tests guard the logic that a refactor could break.

Run: python3 test_launchd_health_check.py   (exit 0 = pass, 1 = fail)
"""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "wd", Path(__file__).resolve().parent / "launchd-health-check.py"
)
wd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wd)

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")


# normalize_exit: launchctl reports raw wait(2) status; we want the human exit code.
check("clean zero", wd.normalize_exit(0), 0)
check("exit 3 encoded (3<<8)", wd.normalize_exit(768), 3)
check("exit 127 encoded (127<<8)", wd.normalize_exit(32512), 127)
check("exit 1 encoded (1<<8)", wd.normalize_exit(256), 1)
check("small value passthrough 3", wd.normalize_exit(3), 3)
check("small value passthrough 127", wd.normalize_exit(127), 127)
check("sigkill (signal 9)", wd.normalize_exit(9), 9)  # <256 passes through

# classify_status: the pure decision behind job_status (no launchctl shell).
# rc != 0 -> the label is not loaded (silently never runs).
check("not loaded", wd.classify_status(1, ""), ("not_loaded", None))
# loaded, clean last run.
check("clean loaded", wd.classify_status(0, '"LastExitStatus" = 0;'), ("ok", 0))
# loaded, real non-zero exit (exit 1 encoded 1<<8=256) -> failing.
check("real exit 1 fails", wd.classify_status(0, '"LastExitStatus" = 256;'), ("failing", 1))
# THE REPRODUCER (scar 2026-07-18): KeepAlive job, LastExitStatus=15 (SIGTERM),
# live PID present -> benign relaunch, NOT a failure.
sigterm_live = '"LastExitStatus" = 15;\n\t"PID" = 78511;'
check("sigterm + live pid = ok", wd.classify_status(0, sigterm_live), ("ok", 0))
# SIGTERM but NO live pid (dead, not restarted) -> still surfaced.
check("sigterm no pid still fails", wd.classify_status(0, '"LastExitStatus" = 15;'),
      ("failing", 15))
# a real exit(15) is raw 15<<8=3840, decodes to 15, not the SIGTERM raw 15 -> still fails
# even with a live pid (only the SIGTERM signal signature is carved out).
check("real exit 15 with pid still fails",
      wd.classify_status(0, '"LastExitStatus" = 3840;\n\t"PID" = 999;'), ("failing", 15))
# a crash-loop signal (SIGKILL 9) with a live pid is NOT carved out -> still pages.
check("sigkill with pid still fails",
      wd.classify_status(0, '"LastExitStatus" = 9;\n\t"PID" = 999;'), ("failing", 9))

# problems_to_ping: dedupe so a persistently-failing job does not spam every run.
TTL = wd.FAIL_PING_TTL_SECONDS
now = 1_000_000

# never-pinged failing job -> ping
check("never pinged", wd.problems_to_ping([("a", "failing", "exit 127")], {}, now),
      [("a", "failing", "exit 127")])

# pinged within TTL, same kind -> suppress
recent = {"a": {"pinged_at": now - 60, "kind": "failing"}}
check("pinged recently suppressed",
      wd.problems_to_ping([("a", "failing", "exit 127")], recent, now), [])

# pinged longer ago than TTL -> ping again
stale = {"a": {"pinged_at": now - TTL - 1, "kind": "failing"}}
check("stale ping re-fires", wd.problems_to_ping([("a", "failing", "exit 127")], stale, now),
      [("a", "failing", "exit 127")])

# kind changed (failing -> not_loaded) re-fires even within TTL
changed = {"a": {"pinged_at": now - 60, "kind": "failing"}}
check("kind change re-fires",
      wd.problems_to_ping([("a", "not_loaded", "installed but not running")], changed, now),
      [("a", "not_loaded", "installed but not running")])

if failures:
    print("FAIL:")
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)
print("PASS: all launchd-health-check logic checks green")
sys.exit(0)
