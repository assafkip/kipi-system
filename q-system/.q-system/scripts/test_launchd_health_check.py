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

# jobs_to_ping: dedupe so a persistently-failing job does not spam every run.
TTL = wd.FAIL_PING_TTL_SECONDS
now = 1_000_000

# never-pinged failing job -> ping
check("never pinged", wd.jobs_to_ping([("a", 127)], {}, now), [("a", 127)])

# pinged within TTL -> suppress
recent = {"a": {"pinged_at": now - 60}}
check("pinged recently suppressed", wd.jobs_to_ping([("a", 127)], recent, now), [])

# pinged longer ago than TTL -> ping again
stale = {"a": {"pinged_at": now - TTL - 1}}
check("stale ping re-fires", wd.jobs_to_ping([("a", 127)], stale, now), [("a", 127)])

# mixed: one due, one suppressed
mixed = {"a": {"pinged_at": now - TTL - 1}, "b": {"pinged_at": now - 10}}
check("mixed due/suppressed",
      wd.jobs_to_ping([("a", 1), ("b", 2)], mixed, now), [("a", 1)])

if failures:
    print("FAIL:")
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)
print("PASS: all launchd-health-check logic checks green")
sys.exit(0)
