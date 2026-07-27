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

# --- a deliberately paused job is never a ping -------------------------------
# Scar 2026-07-26: 26 com.cole.* jobs were paused by commenting `com.cole.` out
# of launchd-watch-prefixes.txt. That can never work -- load_watched_prefixes()
# only ADDS from that file, so a comment cannot remove a prefix hardcoded in
# WATCHED_PREFIXES. The pause was real, the silence was not, and one manual run
# fired 26 false pings at the founder. Recurring false alarms are the mechanism
# that teaches an operator to ignore the channel, which costs the REAL alert.
check("a paused job is never pinged",
      wd.problems_to_ping([("a", "paused", "paused on purpose")], {}, now),
      [])

check("paused stays silent even after the TTL",
      wd.problems_to_ping([("a", "paused", "paused on purpose")],
                          {"a": {"pinged_at": 0, "kind": "paused"}}, now),
      [])

# ...but a genuinely dark job in the same batch must still get through, or the
# suppression would hide real rot behind an intentional pause.
check("a real not_loaded still pings alongside a paused one",
      wd.problems_to_ping([("paused-one", "paused", "paused on purpose"),
                           ("dark-one", "not_loaded", "installed but not running")],
                          {}, now),
      [("dark-one", "not_loaded", "installed but not running")])

check("a paused label that starts FAILING still pings",
      wd.problems_to_ping([("a", "failing", "exit 1")], {}, now),
      [("a", "failing", "exit 1")])

# the ledger reader must ignore comments and blanks, like every other kipi list
_paused = wd.load_paused_labels()
check("load_paused_labels returns a set", isinstance(_paused, set), True)

# --- dry-run flag parsing (ASK-181) ------------------------------------------
# THE REPRODUCER: the old test was `"--dry" in sys.argv`, an exact string match, so
# `--dry-run` fell through to the LIVE path -- writing state and pinging the
# founder's phone from what the operator typed as a read-only check. This job's own
# migration Definition of Ready tells the verifier to run `--dry-run`.
check("--dry is dry", wd.is_dry_run(["--dry"]), True)
check("--dry-run is dry", wd.is_dry_run(["--dry-run"]), True)
check("-n is dry", wd.is_dry_run(["-n"]), True)
check("no flag is live", wd.is_dry_run([]), False)
check("an unrelated flag is live", wd.is_dry_run(["--verbose"]), False)
check("a dry flag anywhere counts", wd.is_dry_run(["--verbose", "--dry-run"]), True)

# --- findings reach Linear, not only Slack (ASK-181) -------------------------
# Bar 2 of the job-migration contract: a finding that only ever exists as a Slack
# line is read once and scrolls away. Linear holds state.
_probs = [
    ("com.kipi.alpha", "failing", "exit 127"),
    ("com.kipi.beta", "not_loaded", "installed but not running"),
    ("com.cole.gamma", "paused", "paused on purpose"),
]
_found = wd.linear_findings(_probs)
check("paused is never filed", [f["subject"] for f in _found],
      ["com.kipi.alpha", "com.kipi.beta"])
check("failing routes to the launchd-failing detector",
      _found[0]["detector"], "launchd-failing")
check("not_loaded routes to the launchd-dark detector",
      _found[1]["detector"], "launchd-dark")
check("the failing title carries the exit code",
      _found[0]["title"], "launchd job failing: com.kipi.alpha (exit 127)")
check("the dark title names the job", _found[1]["title"],
      "launchd job is dark: com.kipi.beta")
check("every finding carries a body", all(f.get("body") for f in _found), True)

# The dedup key must be fleet-health-daily.py's key, byte for byte. That job runs
# the SAME two checks at 08:15; a second key namespace would file a permanent
# duplicate Linear issue for every finding both jobs see, and Linear issues do not
# get deleted here.
_fh_spec = importlib.util.spec_from_file_location(
    "fh", Path(__file__).resolve().parent / "fleet-health-daily.py"
)
_fh = importlib.util.module_from_spec(_fh_spec)
_fh_spec.loader.exec_module(_fh)
check("failing key matches fleet-health's",
      _found[0]["key"], _fh.finding_key("launchd-failing", "com.kipi.alpha"))
check("dark key matches fleet-health's",
      _found[1]["key"], _fh.finding_key("launchd-dark", "com.kipi.beta"))

# ...and fleet-health's filer must be able to say who filed it, or every issue
# this watchdog files claims to come from a job that did not file it.
import inspect  # noqa: E402 - local to this assertion

check("file_findings accepts a filer", "filer",
      "filer" if "filer" in inspect.signature(_fh.file_findings).parameters else "MISSING")

# Linear being unreachable must never take the watchdog down -- a watchdog that
# dies on a network error stops watching launchd, which is the exact silent death
# it exists to catch. Swap the cached fleet-health module for one that raises.
class _Boom:
    @staticmethod
    def finding_key(detector, subject):
        return _fh.finding_key(detector, subject)

    @staticmethod
    def file_findings(findings, apply, filer=None):
        raise RuntimeError("linear unreachable")


_saved_fh = wd._FLEET_HEALTH
wd._FLEET_HEALTH = _Boom
try:
    _broken = wd.file_linear_findings([("com.kipi.alpha", "failing", "exit 127")])
finally:
    wd._FLEET_HEALTH = _saved_fh
check("a filing error is swallowed, not raised", _broken["created"], 0)
check("a filing error is counted", _broken["skipped_no_key"], 1)

# Nothing to file must not reach the network at all.
wd._FLEET_HEALTH = _Boom
try:
    _none = wd.file_linear_findings([("com.cole.gamma", "paused", "paused on purpose")])
finally:
    wd._FLEET_HEALTH = _saved_fh
check("a paused-only run files nothing", _none,
      {"created": 0, "existing": 0, "skipped_no_key": 0})

if failures:
    print("FAIL:")
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)
print("PASS: all launchd-health-check logic checks green")
sys.exit(0)
