#!/usr/bin/env python3
"""Regression tests for launchd-health-check.py (the silent-job-death watchdog).

Covers the two pure decision functions. The launchd end-to-end path (creating a
failing job, kickstarting it, reading LastExitStatus) is macOS-launchd-specific and
verified manually on wiring; these tests guard the logic that a refactor could break.

Run: python3 test_launchd_health_check.py   (exit 0 = pass, 1 = fail)
"""
import contextlib
import importlib.util
import io
import subprocess
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
check("--dry is a dry flag", wd.is_dry_run(["--dry"]), True)
check("--dry-run is a dry flag", wd.is_dry_run(["--dry-run"]), True)
check("-n is a dry flag", wd.is_dry_run(["-n"]), True)
check("no flag carries no dry request", wd.is_dry_run([]), False)
check("an unrelated flag is not a dry flag", wd.is_dry_run(["--verbose"]), False)
check("a dry flag anywhere is seen", wd.is_dry_run(["--verbose", "--dry-run"]), True)
# is_dry_run answers "was a dry flag typed", nothing more. What the script DOES
# with an unrecognized flag is parse_mode's call, asserted further down -- the
# review's finding 3 was that no code path enforced the docstring's promise.

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
# `owed` rides along on every return path: it is the denominator `unfiled_count`
# needs, and a path that omitted it would silently fall back to reading one bucket.
check("a paused-only run files nothing", _none,
      {"created": 0, "existing": 0, "skipped_no_key": 0, "owed": 0})

# --- a dead filer must not read like a clean run (ASK-181 review, finding 1) --
# THE REPRODUCER: `file_findings` catches its own network errors and returns
# {created: 0, existing: 0, skipped_no_key: N}. The report read `created` and
# `existing` only, so "Linear is unreachable, 2 findings went nowhere" printed the
# byte-identical line to "the fleet is clean, nothing to file". Every kipi instance
# without ~/.config/kipi/linear-api-key takes that branch, and this script ships
# fleet-wide via kipi update. A false all-clear at 3am is the same class of harm as
# crying wolf -- it is the fleet's own lesson "a zero result must prove it is empty,
# not broken", which this very job exists to honor.


def _fh_stub(created=0, existing=0, unfiled=0, record=None):
    """A stand-in fleet-health module with a scripted file_findings outcome."""

    class _Stub:
        @staticmethod
        def finding_key(detector, subject):
            return _fh.finding_key(detector, subject)

        @staticmethod
        def file_findings(findings, apply, filer=None):
            if record is not None:
                record.append({"n": len(findings), "apply": apply, "filer": filer})
            n = len(findings)
            return {
                "created": n if created == "all" else created,
                "existing": n if existing == "all" else existing,
                "skipped_no_key": n if unfiled == "all" else unfiled,
            }

    return _Stub


def run_capture(problems, fleet_health, dry=False, state=None):
    """Drive run() with every side-effecting edge stubbed.

    Returns (stdout, stderr, pings, state_writes) so an assertion can read what
    the operator would actually SEE, not just what the function returned."""
    saved = (wd.discover_problems, wd.load_state, wd.write_state,
             wd.send_ping, wd._FLEET_HEALTH)
    pings, writes = [], []
    wd.discover_problems = lambda: problems
    wd.load_state = lambda: dict(state or {})
    wd.write_state = lambda s: writes.append(s)
    wd.send_ping = lambda message: pings.append(message)
    wd._FLEET_HEALTH = fleet_health
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            wd.run(dry)
    finally:
        (wd.discover_problems, wd.load_state, wd.write_state,
         wd.send_ping, wd._FLEET_HEALTH) = saved
    return out.getvalue(), err.getvalue(), pings, writes


_TWO_REAL = [("com.claudedaddy.pinterest", "failing", "exit 127"),
             ("com.kipi.opp-scan", "not_loaded", "installed but not running")]
_NOTHING_TO_FILE = [("com.cole.gamma", "paused", "paused on purpose")]

_dead_out = run_capture(_TWO_REAL, _fh_stub(unfiled="all"))[0].strip().splitlines()[-1]
_empty_out = run_capture(_NOTHING_TO_FILE, _fh_stub())[0].strip().splitlines()[-1]
_tracked_out = run_capture(_TWO_REAL, _fh_stub(existing="all"))[0].strip().splitlines()[-1]

check("a dead filer does NOT print the same line as a run with nothing to file",
      _dead_out == _empty_out, False)
check("a dead filer names how many findings never reached Linear",
      "unfiled=2" in _dead_out, True)
check("a clean run reports nothing unfiled", "unfiled=0" in _empty_out, True)
check("an all-already-tracked run still reports nothing unfiled",
      "unfiled=0" in _tracked_out, True)

# The layer above the counter: the Slack ping is the only channel the founder
# actually reads. Fixing the stdout line alone would leave the ping saying "here
# are 2 problems" while the issues meant to hold them never reached the board.
# No NEW ping is created -- the ping that already fires carries the truth.
_dead_pings = run_capture(_TWO_REAL, _fh_stub(unfiled="all"))[2]
_ok_pings = run_capture(_TWO_REAL, _fh_stub(created="all"))[2]
check("a dead filer adds no extra ping", len(_dead_pings), 1)
check("the ping says the findings did not reach Linear",
      any("NOT filed to Linear: 2" in p for p in _dead_pings), True)
check("a healthy filer leaves the ping text alone",
      any("NOT filed" in p for p in _ok_pings), False)

# --- a REFUSED write must not read like a clean run either (PR #19 review, major)
# THE REPRODUCER: ASK-204 gave `file_findings` per-finding error handling, so a
# Linear write that fails now RETURNS {..., "errors": N} where it used to raise.
# This reporter read `skipped_no_key` alone, so a refused write printed the
# byte-identical line to a clean run AND lost the `[NOT filed to Linear: N]`
# annotation on the ping -- in the job whose whole purpose is catching silence.
# Same class as the ASK-181 scar above, one bucket further out.


def _fh_stub_shape(record=None, **buckets):
    """A stand-in emitting the FULL bucket shape `file_findings` returns.

    `_fh_stub` above predates ASK-204 and emits three keys; the real filer emits
    created/existing/skipped_no_key/updated/reopened/relisted/errors. Reporting
    has to be proved against the shape production actually produces, and against
    shapes it does not produce YET -- hence **buckets rather than a fixed list.
    """

    class _Stub:
        @staticmethod
        def finding_key(detector, subject):
            return _fh.finding_key(detector, subject)

        @staticmethod
        def file_findings(findings, apply, filer=None):
            if record is not None:
                record.append({"n": len(findings), "apply": apply, "filer": filer})
            outcome = {"created": 0, "existing": 0, "skipped_no_key": 0, "updated": 0,
                       "reopened": 0, "relisted": 0, "errors": 0}
            outcome.update(buckets)
            return outcome

    return _Stub


def _last_line(problems, fleet_health):
    return run_capture(problems, fleet_health)[0].strip().splitlines()[-1]


# two findings, one filed and one the write refused
_rejected_line = _last_line(_TWO_REAL, _fh_stub_shape(created=1, errors=1))
_clean_line = _last_line(_TWO_REAL, _fh_stub_shape(created=2))
check("a REFUSED Linear write does not print the same line as a clean run",
      _rejected_line == _clean_line, False)
check("a refused write is counted as unfiled", "unfiled=1" in _rejected_line, True)
# the reviewer's exact shape: EVERY write refused reads byte-for-byte like a run
# that had nothing to file, because both print filed=0 already-tracked=0.
check("an all-refused run does not print the same line as a run with nothing to file",
      _last_line(_TWO_REAL, _fh_stub_shape(errors=2))
      == _last_line(_NOTHING_TO_FILE, _fh_stub_shape()), False)
check("a clean run still reports nothing unfiled", "unfiled=0" in _clean_line, True)
_rejected_pings = run_capture(_TWO_REAL, _fh_stub_shape(created=1, errors=1))[2]
check("the ping says the board does NOT have the refused finding",
      any("NOT filed to Linear: 1" in p for p in _rejected_pings), True)
check("a refused write adds no extra ping", len(_rejected_pings), 1)
check("a clean run leaves the ping text alone",
      any("NOT filed" in p for p in run_capture(_TWO_REAL, _fh_stub_shape(created=2))[2]),
      False)

# A re-filed (`relisted`) finding DID land on the board -- counting it as unfiled
# would trade this silence for a nightly false alarm, which is the other half of
# the same failure.
check("a re-filed finding counts as filed, not unfiled",
      "unfiled=0" in _last_line(_TWO_REAL, _fh_stub_shape(created=1, relisted=1)), True)

# The layer above this fix: `errors` will not be the last bucket `file_findings`
# grows. A reporter that lists FAILURE buckets by name goes dark again on the day
# the next one lands -- which is precisely how this regression happened. So
# unfiled is owed-minus-LANDED: a bucket this reporter has never been taught
# about counts as not-filed until someone declares it landed.
check("a bucket the reporter has never heard of still counts as unfiled",
      "unfiled=1" in _last_line(_TWO_REAL, _fh_stub_shape(created=1, quarantined=1)), True)

# One layer deeper: if the findings cannot even be BUILT (fleet-health-daily.py
# missing -- literally the kipi-update rsync --delete scar this watchdog exists
# for) the outcome is all-zeros, which would print the clean-run line again.
# `unfiled` has to count the problems that were owed an issue, not the findings
# that were never constructed.
class _BuildBoom:
    @staticmethod
    def finding_key(detector, subject):
        raise ImportError("no module named fleet-health-daily")


_boom_out, _boom_err, _, _ = run_capture(_TWO_REAL, _BuildBoom)
check("a findings-build crash reports the problems it could not file",
      "unfiled=2" in _boom_out.strip().splitlines()[-1], True)
check("a findings-build crash says why on stderr", "could not be built" in _boom_err, True)
check("a findings-build crash does not count the paused job",
      "unfiled=0" in run_capture(_NOTHING_TO_FILE, _BuildBoom)[0], True)

# --- the dry preview must match what the live run does (finding 2) -----------
# `[dry] would file 2` while the live run files 0 over-states a PERMANENT,
# undeletable action. The cause was two readers of one input: dry counted the
# findings it built, live counted what the filer actually created after dedup.
# One reader now -- the same file_findings, with apply=False.
_calls = []
_dry_out, _, _dry_pings, _dry_writes = run_capture(
    _TWO_REAL, _fh_stub(existing="all", record=_calls), dry=True)
check("the dry preview does not claim it would file already-tracked findings",
      "would-file=0" in _dry_out, True)
check("the dry preview reports what is already tracked",
      "already-tracked=2" in _dry_out, True)
check("dry runs the SAME filer, with apply off", [c["apply"] for c in _calls], [False])
check("dry names itself as the filer", [c["filer"] for c in _calls],
      ["launchd-health-check.py"])
check("dry still writes no state", _dry_writes, [])
check("dry still sends no ping", _dry_pings, [])
check("dry still previews the ping count", "[dry] would ping 2 job(s)" in _dry_out, True)

# and a dead filer during a dry run is just as visible as during a live one
check("a dry run against a dead filer says so too",
      "unfiled=2" in run_capture(_TWO_REAL, _fh_stub(unfiled="all"), dry=True)[0], True)

# --- an unrecognized flag must not arm anything (finding 3) ------------------
# The docstring claimed this; no code path enforced it. `--dry-run=1`, `--dryrun`
# and `--dry_run` all fell through to the LIVE path -- the same shape as the
# original scar (a flag the operator believed was read-only was not).
for _required in ("parse_mode", "main"):
    if not hasattr(wd, _required):
        failures.append(f"{_required}(): not implemented on launchd-health-check.py")
        setattr(wd, _required, lambda *_a, **_k: None)

check("no flag is live", wd.parse_mode([]), ("live", []))
check("--dry-run is dry", wd.parse_mode(["--dry-run"]), ("dry", []))
check("--dry is dry", wd.parse_mode(["--dry"]), ("dry", []))
check("-n is dry", wd.parse_mode(["-n"]), ("dry", []))
check("--dry-run=1 refuses instead of arming the live path",
      wd.parse_mode(["--dry-run=1"]), ("refuse", ["--dry-run=1"]))
check("--dryrun refuses", wd.parse_mode(["--dryrun"]), ("refuse", ["--dryrun"]))
check("--dry_run refuses", wd.parse_mode(["--dry_run"]), ("refuse", ["--dry_run"]))
check("-dry refuses", wd.parse_mode(["-dry"]), ("refuse", ["-dry"]))
check("an unknown flag NEXT TO a dry flag still refuses -- intent is unknown",
      wd.parse_mode(["--verbose", "--dry-run"]), ("refuse", ["--verbose"]))

_refuse_out, _refuse_err = io.StringIO(), io.StringIO()
_saved_run = wd.run
wd.run = lambda dry: _refuse_out.write("RAN\n")
try:
    with contextlib.redirect_stdout(_refuse_out), contextlib.redirect_stderr(_refuse_err):
        _rc = wd.main(["--dryrun"])
finally:
    wd.run = _saved_run
check("a refused flag never reaches run()", "RAN" in _refuse_out.getvalue(), False)
check("a refused flag still exits 0 (a watchdog never fails its own job)", _rc, 0)
check("a refused flag says what IS valid", "--dry-run" in _refuse_err.getvalue(), True)

# --- a crash inside run() must be loud, not silent (finding 4) ---------------
# `finally: sys.exit(0)` supersedes a propagating exception, so an unhandled crash
# printed NOTHING and launchd recorded SUCCESS. The watchdog dying silently is the
# exact failure mode it was built to catch, one level up.
_crash_err = io.StringIO()
_saved_run = wd.run


def _explode(_dry):
    raise RuntimeError("fleet-health-daily.py vanished")


wd.run = _explode
try:
    with contextlib.redirect_stderr(_crash_err):
        _crash_rc = wd.main([])
finally:
    wd.run = _saved_run
check("a crash still exits 0", _crash_rc, 0)
check("a crash prints its traceback", "Traceback" in _crash_err.getvalue(), True)
check("the traceback names the real error",
      "fleet-health-daily.py vanished" in _crash_err.getvalue(), True)

# --- the key must match what fleet-health's PRODUCERS emit (finding 5) -------
# Comparing against finding_key() only restates this file's own formula. If
# fleet-health's dark-job detector ever changed `subject` (label -> label.plist,
# a plausible "improve the issue" edit), both suites would stay green while the
# fleet filed TWO permanent Linear issues for one job, forever. So drive the real
# producers and compare the key each side would actually file.
class _FakeCompleted:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


class _FakeSubprocess:
    """Only the two calls fleet-health's launchd producers make."""
    TimeoutExpired = subprocess.TimeoutExpired

    @staticmethod
    def run(cmd, **_kw):
        if list(cmd) == ["launchctl", "list"]:
            return _FakeCompleted(0, "PID\tStatus\tLabel\n-\t127\tcom.kipi.alpha\n")
        return _FakeCompleted(1, "")


_fh_saved = (_fh._launchd_labels, _fh._paused_labels, _fh._is_loaded, _fh.subprocess)
_fh._launchd_labels = lambda: ["com.kipi.beta"]
_fh._paused_labels = lambda: set()
_fh._is_loaded = lambda _label: False
_fh.subprocess = _FakeSubprocess
try:
    _produced_dark = _fh.detect_dark_jobs(None)
    _produced_failing = _fh.detect_failing_jobs(None)
finally:
    (_fh._launchd_labels, _fh._paused_labels, _fh._is_loaded, _fh.subprocess) = _fh_saved

check("fleet-health's dark producer emitted the job under test",
      [f["subject"] for f in _produced_dark], ["com.kipi.beta"])
check("fleet-health's failing producer emitted the job under test",
      [f["subject"] for f in _produced_failing], ["com.kipi.alpha"])
check("the watchdog's dark key equals the key fleet-health's PRODUCER files",
      _found[1]["key"], _fh.finding_key("launchd-dark", _produced_dark[0]["subject"]))
check("the watchdog's failing key equals the key fleet-health's PRODUCER files",
      _found[0]["key"], _fh.finding_key("launchd-failing", _produced_failing[0]["subject"]))

# ...and the detector ids themselves have to exist in fleet-health's registry, or
# the shared namespace is shared with nothing.
_registry_ids = {d["id"] for d in _fh.DETECTORS}
check("every detector the watchdog files under is in fleet-health's registry",
      sorted(set(wd.LINEAR_DETECTOR_BY_KIND.values()) - _registry_ids), [])

if failures:
    print("FAIL:")
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)
print("PASS: all launchd-health-check logic checks green")
sys.exit(0)
