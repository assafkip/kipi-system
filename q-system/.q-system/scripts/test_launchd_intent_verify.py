#!/usr/bin/env python3
"""Regression tests for launchd-intent-verify.py (sp-2c7e5819).

Test 1 is the reproducer and it runs BOTH halves: it calls the shipping
`launchd-health-check.discover_problems()` on a paused-but-running job and asserts
it returns nothing (the blind spot, executed rather than described), then asserts
the new `diff_intent` reports it. If someone closes the gap in the watchdog
instead, assertion one goes red and this file is the thing that says so.

Every fixture is a string or a dict. Nothing here reads ~/.config/kipi or
~/Library/LaunchAgents; the two I/O edges (`read_overrides`, `check`) take
injected values and a tmpdir.

Run: python3 test_launchd_intent_verify.py   (exit 0 = pass, 1 = fail)
"""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(filename, name):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


iv = _load("launchd-intent-verify.py", "iv")
wd = _load("launchd-health-check.py", "wd")

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")


def check_raises(name, exc_type, fn):
    try:
        fn()
    except exc_type:
        return
    except Exception as exc:  # noqa: BLE001
        failures.append(f"{name}: raised {type(exc).__name__}, want {exc_type.__name__}")
        return
    failures.append(f"{name}: did not raise {exc_type.__name__}")


# =============================================================================
# 1. THE REPRODUCER: a job declared paused, actually running.
# =============================================================================
# Half A -- the shipping watchdog is blind to it. discover_problems() appends only
# for 'failing' and 'not_loaded'; a healthy job hits neither branch, so a job the
# pause ledger says is stopped, which is actually up, produces no finding, no
# Slack ping and no Linear issue. Executed, not asserted from reading the source.
_tmp = Path(tempfile.mkdtemp())
_agents = _tmp / "LaunchAgents"
_agents.mkdir()
(_agents / "com.kipi.zzz-should-be-paused.plist").write_text("<plist/>")
_ledger = _tmp / "paused.txt"
_ledger.write_text("com.kipi.zzz-should-be-paused\n")

wd.LAUNCH_AGENTS = _agents
wd.PAUSED_LABEL_FILES = (_ledger,)
wd.EXTRA_PREFIXES_FILE = _tmp / "no-such-file.txt"
wd.job_status = lambda label: ("ok", 0)  # loaded and healthy == running

check("REPRODUCER half A: watchdog sees a paused-but-running job as nothing",
      wd.discover_problems(), [])

# Half B -- the verifier reports it, in the direction nothing else covers.
_intent, _conflicts = iv.load_intent(None, ["com.kipi.zzz-should-be-paused\n"])
check("REPRODUCER half B: verifier reports enabled_but_declared_paused",
      iv.diff_intent(_intent, {"com.kipi.zzz-should-be-paused": "enabled"},
                     {"com.kipi.zzz-should-be-paused"}),
      [("com.kipi.zzz-should-be-paused", "enabled_but_declared_paused",
        "declared disabled, override record says enabled")])

# Half B', the same job with NO override row at all. This is the common case: 65
# watched plists on disk, 32 override rows (measured 2026-08-06). If absence were
# read as 'unknown' instead of 'enabled', two thirds of the fleet would go
# unverified and this finding would vanish.
check("REPRODUCER half B': absent override still reports drift",
      iv.diff_intent(_intent, {}, {"com.kipi.zzz-should-be-paused"}),
      [("com.kipi.zzz-should-be-paused", "enabled_but_declared_paused",
        "declared disabled, override record says enabled")])


# =============================================================================
# 2. parse_print_disabled -- fixture captured from the real producer
# =============================================================================
# Verbatim from `launchctl print-disabled gui/$(id -u)` on Darwin 25.3.0,
# 2026-08-06, tabs and all. An invented fixture would only test my assumption
# about the format; this one is what the machine actually printed.
REAL_OUTPUT = '''
	disabled services = {
		"com.docker.helper" => enabled
		"com.cole.content-brain" => disabled
		"com.cole.daily-podcast" => enabled
		"com.apple.Siri.agent" => disabled
		"com.kipi.fractional-cxo.opp-scan" => enabled
	}
'''
check("parses the real producer's output", iv.parse_print_disabled(REAL_OUTPUT), {
    "com.docker.helper": "enabled",
    "com.cole.content-brain": "disabled",
    "com.cole.daily-podcast": "enabled",
    "com.apple.Siri.agent": "disabled",
    "com.kipi.fractional-cxo.opp-scan": "enabled",
})

# Older macOS prints true/false for the same field.
check("parses the true/false vocabulary",
      iv.parse_print_disabled('"a" => true\n"b" => false\n'),
      {"a": "disabled", "b": "enabled"})

# A value token this parser does not know is REFUSED, never guessed. If it were
# skipped, the label would fall through to the absence default (enabled) and a
# genuinely disabled job would read as running.
check_raises("unknown value token refuses", iv.IntentError,
             lambda: iv.parse_print_disabled('"a" => perhaps\n'))

# A services block that parsed to nothing is a format change, not an empty DB.
# Returning {} here would mark EVERY declared-disabled job as drift at once --
# 25 false pages on this machine today.
check_raises("shaped-but-empty output refuses", iv.IntentError,
             lambda: iv.parse_print_disabled("\tdisabled services = {\n\t}\n"))

# A genuinely empty answer (no block at all) is not an error.
check("truly empty output is empty, not an error", iv.parse_print_disabled(""), {})


# =============================================================================
# 3. effective_state -- absence means no override recorded, which launchd runs
# =============================================================================
check("absent label defaults to enabled", iv.effective_state("nope", {}), "enabled")
check("present disabled label", iv.effective_state("a", {"a": "disabled"}), "disabled")


# =============================================================================
# 4. load_intent -- one reader for the manifest and the legacy ledgers
# =============================================================================
check("ledger lines are implicit intent:disabled",
      iv.load_intent(None, ["a\nb  # comment\n\n# whole line\n"])[0],
      {"a": "disabled", "b": "disabled"})

MANIFEST = json.dumps({"schema_version": 1, "jobs": [
    {"label": "a", "intent": "enabled", "reason": "founder confirmed 2026-08-06"},
    {"label": "c", "intent": "disabled"},
]})
_i, _c = iv.load_intent(MANIFEST, ["a\nb\n"])
check("manifest overrides the ledger", _i, {"a": "enabled", "b": "disabled", "c": "disabled"})
check("and the disagreement is reported, not swallowed", _c, ["a"])

check_raises("invalid JSON refuses", iv.IntentError, lambda: iv.load_intent("{oops", []))
check_raises("missing jobs list refuses", iv.IntentError, lambda: iv.load_intent("{}", []))
check_raises("a row with no label refuses", iv.IntentError,
             lambda: iv.load_intent('{"jobs":[{"intent":"enabled"}]}', []))
check_raises("an unknown intent value refuses", iv.IntentError,
             lambda: iv.load_intent('{"jobs":[{"label":"a","intent":"paused"}]}', []))

# Duplicate labels (codex review of PR #134, round 7). Both directions are pinned
# because refusing only the contradicting pair would leave the row-order coupling
# in place for the identical pair -- and a manifest that lists a label twice is a
# defect whether or not the two rows happen to agree today.
check_raises("a label declared twice refuses", iv.IntentError,
             lambda: iv.load_intent(
                 '{"jobs":[{"label":"a","intent":"enabled"},'
                 '{"label":"a","intent":"disabled"}]}', []))
check_raises("even when the two rows agree", iv.IntentError,
             lambda: iv.load_intent(
                 '{"jobs":[{"label":"a","intent":"enabled"},'
                 '{"label":"a","intent":"enabled"}]}', []))
# The assertion that would have caught the shipped bug: not "it refuses" but "the
# answer does not depend on line order". A last-row-wins reader passes every
# single-order test and still pages on one ordering and stays silent on the other.
_dup = [{"label": "a", "intent": "enabled"}, {"label": "a", "intent": "disabled"}]


def _outcome(rows):
    try:
        intent, _ = iv.load_intent(json.dumps({"jobs": rows}), [])
    except iv.IntentError:
        return ("REFUSED",)
    return (intent["a"], tuple(k for _, k, _ in iv.diff_intent(intent, {"a": "enabled"}, {"a"})))


check("the verdict does not depend on manifest row order",
      _outcome(_dup) == _outcome(list(reversed(_dup))), True)
check("and that shared verdict is a refusal, not a silent pick",
      _outcome(_dup), ("REFUSED",))


# =============================================================================
# 5. diff_intent -- all four kinds, and agreement producing silence
# =============================================================================
check("intent matching reality reports nothing",
      iv.diff_intent({"a": "enabled"}, {"a": "enabled"}, {"a"}), [])
check("declared enabled, launchd disabled",
      iv.diff_intent({"a": "enabled"}, {"a": "disabled"}, {"a"}),
      [("a", "disabled_but_declared_running", "declared enabled, override record says disabled")])
check("declared but no plist and no override is an orphan",
      iv.diff_intent({"a": "disabled"}, {}, set()),
      [("a", "orphan", "declared disabled, no plist and no override")])
check("a plist with no declared intent is undeclared coverage",
      iv.diff_intent({}, {}, {"z"}), [("z", "undeclared", "no declared intent")])


# =============================================================================
# 5b. A RETIRED job with a stale override row is an orphan, not a running job
# =============================================================================
# Found by populating intent from the real 2026-08-01 jobs audit instead of a
# synthetic manifest. The audit KILLED two fractional-cxo jobs by renaming their
# plists to `.plist.retired-2026-08-01`; `installed_labels()` globs `*.plist`, so
# neither is installed (verified: the glob returns only the un-renamed sibling).
#
# launchd kept an override row for exactly one of them. Measured 2026-08-06 from
# `launchctl print-disabled gui/$(id -u)`:
#
#     "com.kipi.fractional-cxo.opp-scan" => enabled     <- row survived the retire
#     (com.kipi.fractional-cxo.bolt-on-discovery)       <- no row at all
#
# Two jobs, same retirement, differing only by that leftover row. The orphan
# branch was guarded by `not installed AND label not in overrides`; the second
# clause is False for opp-scan, so it fell through to the drift branch and paged
# `enabled_but_declared_paused` for a job with no executable. A stale override row
# is a statement about the override DB, never evidence that anything is running.
#
# Class scar: the third instance of a signal read on only one side of a branch.
# 4f6bf61f (ASK-113) nested `if label in paused` INSIDE the not_loaded arm, so a
# paused-and-healthy job reached no branch at all -- and its own scar was 26 false
# pings for jobs the founder had deliberately stopped. Same harm, same shape: the
# guard exists, the compound condition stops the path from reaching it.
RETIRED_STALE = "com.kipi.fractional-cxo.opp-scan"
RETIRED_CLEAN = "com.kipi.fractional-cxo.bolt-on-discovery"

# Both retired, both declared disabled by the audit, NEITHER installed.
_retired_intent = {RETIRED_STALE: "disabled", RETIRED_CLEAN: "disabled"}
_retired_findings = iv.diff_intent(_retired_intent, {RETIRED_STALE: "enabled"}, set())

check("a retired job whose override row survived is an orphan, not drift",
      _retired_findings,
      [(RETIRED_CLEAN, "orphan", "declared disabled, no plist and no override"),
       (RETIRED_STALE, "orphan",
        "declared disabled, no plist; stale override row says enabled")])

# The harm this actually prevents: the founder's phone. Before the fix the stale
# row produced a pingable drift kind, which IS in PINGABLE_KINDS, so a job with no
# executable rang a phone. Asserting the kind alone would not have caught the
# consequence if PINGABLE_KINDS ever grew.
check("and it therefore never reaches the founder's phone",
      iv.ping_decision(_retired_findings, {})[0], [])

# The THIRD orphan shape, and on this machine the most common one: no plist, and
# an override row that AGREES with the declared intent. Added after a mutant
# survived the two cases above -- a variant guarding the orphan branch with
# `not installed and want != effective_state(...)` passed both, because in both
# the override disagrees with the intent. Where they agree it falls through to
# the `want == actual: continue` line and the job vanishes from the report
# entirely: not a wrong kind, no finding at all.
#
# Measured 2026-08-06 (44 override rows, 45 installed plists, 4 retired-renamed
# files). Labels with an override row and no plist on disk:
#     disabled  com.ask.ai-podcast
#     disabled  com.cole.linkedin-loop-watchdog
#     disabled  com.cole.linkedin-session
#     enabled   com.cole.pause-resume
#     enabled   com.kipi.fractional-cxo.opp-scan
# Three of five agree with a 'disabled' intent, so the untested sub-shape was the
# MAJORITY of the real population. A retired job is an orphan because there is no
# plist, never because the override happens to disagree.
check("a retired job whose override AGREES with intent is still an orphan",
      iv.diff_intent({"com.ask.ai-podcast": "disabled"},
                     {"com.ask.ai-podcast": "disabled"}, set()),
      [("com.ask.ai-podcast", "orphan",
        "declared disabled, no plist; stale override row says disabled")])


# =============================================================================
# 6. coverage -- the number that separates "nothing wrong" from "nothing checked"
# =============================================================================
check("coverage counts installed-and-declared over installed",
      iv.coverage({"a": "enabled", "gone": "disabled"}, {"a", "b", "c"}), (1, 3))


# =============================================================================
# 7. ping_decision -- transition plus a consecutive count, never the state
# =============================================================================
DRIFT = [("a", "enabled_but_declared_paused", "d")]

due, state = iv.ping_decision(DRIFT, {})
check("first sighting pings", due, [("a", "enabled_but_declared_paused", "d", 1)])
check("and records one run", state, {"a": {"kind": "enabled_but_declared_paused", "runs": 1, "detail": "d"}})

due, state = iv.ping_decision(DRIFT, state)
check("second consecutive run is silent", due, [])
check("but the count still advances", state["a"]["runs"], 2)

# Walk to the repeat threshold. The count is what re-fires, so this cannot be
# defeated by a schedule change the way a wall-clock TTL was (ASK-283).
s = {"a": {"kind": "enabled_but_declared_paused", "runs": iv.REPEAT_EVERY_RUNS - 1}}
due, _ = iv.ping_decision(DRIFT, s)
check("re-pings at the consecutive-run threshold",
      due, [("a", "enabled_but_declared_paused", "d", iv.REPEAT_EVERY_RUNS)])

# A different bad state is a new transition and pings immediately.
s = {"a": {"kind": "disabled_but_declared_running", "runs": 9}}
due, _ = iv.ping_decision(DRIFT, s)
check("a changed kind re-pings and resets the count",
      due, [("a", "enabled_but_declared_paused", "d", 1)])

# Coverage findings never reach the phone.
check("undeclared is never pingable",
      iv.ping_decision([("z", "undeclared", "no declared intent")], {})[0], [])
check("orphan is never pingable",
      iv.ping_decision([("z", "orphan", "x")], {})[0], [])

# One line for the whole run, not one ping per finding.
msg = iv.ping_message([("a", "enabled_but_declared_paused", "d", 1),
                       ("b", "disabled_but_declared_running", "d", 14)])
check("one message names both jobs", msg.count("--"), 1)
check("message says what drifted", "override enabled, declared paused" in msg, True)
check("message carries the consecutive count", "14 runs" in msg, True)


# =============================================================================
# 8. linear_findings -- pingable kinds only, keyed through the shared keyer
# =============================================================================
lf = iv.linear_findings(
    [("a", "enabled_but_declared_paused", "d"), ("z", "undeclared", "x")],
    lambda detector, subject: f"fleet-health/{detector}/{subject}")
check("only drift kinds are filed", [f["subject"] for f in lf], ["a"])
check("filed under the intent-drift detector", lf[0]["detector"], "launchd-intent-drift")
check("body names the label", "`a`" in lf[0]["body"], True)


# =============================================================================
# 8b. REPRODUCER: a launchctl that FAILED is not an override DB with no rows
# =============================================================================
# The default runner returned `.stdout` and never looked at `.returncode`. A
# launchctl that exits nonzero prints nothing on stdout, `parse_print_disabled("")`
# legitimately returns {}, and an empty override map means "no label has an
# override" -- which `effective_state` correctly reads as EVERYTHING ENABLED. So a
# broken launchctl produced one `enabled_but_declared_paused` finding per intended-paused
# job: a Slack page and a PERMANENT Linear issue per job, about a machine nobody
# touched. That is the same false-alarm storm `parse_print_disabled` refuses a
# format change to avoid; the failure just entered one layer lower, where the
# guard could not see it.
class _Proc:
    def __init__(self, returncode, stdout, stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


check_raises("a nonzero launchctl is refused, not read as an empty DB", iv.IntentError,
             lambda: iv.launchctl_print_disabled(
                 run=lambda *a, **k: _Proc(113, "", "Could not find domain")))

# rc 0 with no output is the same lie in a quieter form: a real success always
# prints the `disabled services = { ... }` block.
check_raises("a silent success is refused too", iv.IntentError,
             lambda: iv.launchctl_print_disabled(run=lambda *a, **k: _Proc(0, "  \n")))


def _explode(*a, **k):
    raise FileNotFoundError("launchctl")


check_raises("launchctl missing from PATH is refused", iv.IntentError,
             lambda: iv.launchctl_print_disabled(run=_explode))

check("a real answer is returned unchanged",
      iv.launchctl_print_disabled(run=lambda *a, **k: _Proc(0, REAL_OUTPUT)),
      REAL_OUTPUT)

# The harm, end to end: read_overrides must inherit that refusal from its DEFAULT
# runner, because that is the one the installed job uses.
check("read_overrides defaults to the guarded runner",
      iv.read_overrides.__defaults__, (None,))
check_raises("and so a failed launchctl cannot reach diff_intent", iv.IntentError,
             lambda: iv.read_overrides(
                 runner=lambda: iv.launchctl_print_disabled(
                     run=lambda *a, **k: _Proc(1, ""))))

# Negative self-test: prove the probe above can pass. Without the returncode
# guard, this same input returns {} and the check_raises calls go red.
check("an unguarded read of the same input yields the empty map that caused it",
      iv.parse_print_disabled(_Proc(113, "", "boom").stdout), {})


# =============================================================================
# 9. check() -- the wiring, against a tmpdir, with injected launchd state
# =============================================================================
_home = Path(tempfile.mkdtemp())
iv.INTENT_MANIFEST = _home / "launchd-intent.json"
iv.STATE_FILE = _home / "state.json"
iv.LEGACY_PAUSED_FILES = (_home / "paused.txt",)
(_home / "paused.txt").write_text("com.kipi.paused-job\n")

findings, due, cov, commit = iv.check(
    overrides={"com.kipi.paused-job": "enabled"},
    labels={"com.kipi.paused-job", "com.kipi.other"},
)
check("check() surfaces the drift",
      [(l, k) for l, k, _ in findings if k in iv.PINGABLE_KINDS],
      [("com.kipi.paused-job", "enabled_but_declared_paused")])
check("check() pings the transition", [d[0] for d in due], ["com.kipi.paused-job"])
check("check() reports partial coverage", cov, (1, 2))
check("check() does not persist before the caller has delivered",
      iv.STATE_FILE.exists(), False)
check("committing without a delivery verdict is REFUSED", commit(), False)
check("and nothing was written by the refused commit",
      iv.STATE_FILE.exists(), False)
check("check() persisted the run count once delivery was declared",
      commit(delivered=True) and
      json.loads(iv.STATE_FILE.read_text())["com.kipi.paused-job"]["runs"], 1)

# dry mode must not advance the counter that decides future pings.
before = iv.STATE_FILE.read_text()
_, _, _, _dry_commit = iv.check(
    dry_run=True, overrides={"com.kipi.paused-job": "enabled"},
    labels={"com.kipi.paused-job"})
check("a dry commit reports success without writing", _dry_commit(), True)
check("dry run writes no state", iv.STATE_FILE.read_text(), before)


# =============================================================================
# 9b. REPRODUCER: a crash between persisting and delivering ate the alert
# =============================================================================
# check() used to write_state() before returning, so the run was recorded as
# "seen" the instant it was computed -- before the caller filed the Linear issue
# and before send_ping ran. Anything that killed the process in between (launchd
# timeout, an exception in the filer, the machine sleeping) left runs=1 on disk
# with nothing delivered. The NEXT run then computed runs=2, which is not
# 1 and not a multiple of REPEAT_EVERY_RUNS, so ping_decision returned nothing.
# One transient crash silently converted a real drift into 14 runs (a week) of
# silence, and the founder's phone showed the same thing a clean fleet shows.
_crash = Path(tempfile.mkdtemp())
iv.INTENT_MANIFEST = _crash / "launchd-intent.json"
iv.STATE_FILE = _crash / "state.json"
iv.LEGACY_PAUSED_FILES = (_crash / "paused.txt",)
(_crash / "paused.txt").write_text("com.kipi.drifting\n")

_args = {"overrides": {"com.kipi.drifting": "enabled"},
         "labels": {"com.kipi.drifting"}}

_, due_a, _, _commit_a = iv.check(**_args)
check("run 1 computes a due alert", [d[0] for d in due_a], ["com.kipi.drifting"])
# The crash: _commit_a is never called, because delivery never happened.
check("and nothing was recorded on the way out", iv.STATE_FILE.exists(), False)

_, due_b, _, _commit_b = iv.check(**_args)
check("run 2 still owes the founder that alert",
      [d[0] for d in due_b], ["com.kipi.drifting"])
_commit_b(delivered=True)  # this time delivery succeeded

_, due_c, _, _commit_c = iv.check(**_args)
check("and once delivered it is not re-sent", due_c, [])
check("the committed count is 1 run, not 3", json.loads(iv.STATE_FILE.read_text())
      ["com.kipi.drifting"]["runs"], 1)


# =============================================================================
# 9c. REPRODUCER: the standalone entry point recorded runs it never delivered
# =============================================================================
# main() printed to stdout, called commit(), and argued that printing was its
# delivery. It shares STATE_FILE with run_intent_check in launchd-health-check.py
# -- the only path that files a Linear issue and sends a Slack ping. Measured on
# the shipped code (q-system/output/ask447r4_probe.py): one standalone run
# persisted runs=1 for a real drift and the SCHEDULED watchdog then went silent
# for 12 consecutive runs, first paging at run 13. At 2 runs/day that is six days
# in which the founder's phone looks exactly like a clean fleet.
_solo = Path(tempfile.mkdtemp())
iv.INTENT_MANIFEST = _solo / "launchd-intent.json"
iv.STATE_FILE = _solo / "state.json"
iv.LEGACY_PAUSED_FILES = (_solo / "paused.txt",)
(_solo / "paused.txt").write_text("com.kipi.drifting\n")

_saved_overrides, _saved_installed = iv.read_overrides, iv.installed_labels
try:
    iv.read_overrides = lambda runner=None: {"com.kipi.drifting": iv.ENABLED}
    iv.installed_labels = lambda: {"com.kipi.drifting"}

    with contextlib.redirect_stdout(io.StringIO()) as _solo_out:
        _rc = iv.main([])
    check("the standalone entry point exits 0", _rc, 0)
    check("it still reports the drift it found",
          "ENABLED_BUT_DECLARED_PAUSED: com.kipi.drifting" in _solo_out.getvalue(),
          True)
    check("and it claims no delivery it did not make",
          "nothing sent and nothing recorded" in _solo_out.getvalue(), True)
    check("a standalone run records NOTHING", iv.STATE_FILE.exists(), False)
    check("--dry is accepted and identical", iv.main(["--dry"]), 0)
    check("still nothing recorded", iv.STATE_FILE.exists(), False)

    # Negative self-test: prove the fixture CAN write, so "no state file" is a
    # measured absence and not a broken temp dir or a stub that never ran.
    _, _due_solo, _, _commit_solo = iv.check()
    check("the same fixture is due an alert", [d[0] for d in _due_solo],
          ["com.kipi.drifting"])
    check("and a DELIVERING caller does write it here",
          _commit_solo(delivered=True) and iv.STATE_FILE.exists(), True)

    # The counter main() would have stolen: it must not advance an existing one
    # either. runs stays 1, so the watchdog's next scheduled run still re-alerts
    # on schedule instead of counting a terminal session as a delivered page.
    _before_solo = iv.STATE_FILE.read_text()
    with contextlib.redirect_stdout(io.StringIO()):
        iv.main([])
    check("a standalone run does not advance an existing count",
          iv.STATE_FILE.read_text(), _before_solo)
finally:
    iv.read_overrides, iv.installed_labels = _saved_overrides, _saved_installed


# =============================================================================
# 10. WIRING -- the verifier is actually CALLED by the installed job
# =============================================================================
# The unit tests above all pass with the call-site deleted. This is the one that
# goes red if run_intent_check() is never reached. It asserts the call happens on
# an EMPTY problem list on purpose: run() returns early when nothing is failing,
# and a healthy fleet is exactly the state a job running against its own pause
# decision produces. Wired after that return, the whole feature would be dead.
_called = []
wd.run_intent_check = lambda dry: _called.append(dry)
wd.discover_problems = lambda: []
wd.STATE_FILE = _tmp / "never-written.json"
wd.run(dry_run=True)
check("run() calls the intent check even when no job is failing", _called, [True])

# And run_intent_check swallows a broken manifest instead of taking the watchdog
# down with it -- a watchdog that dies stops watching.
#
# The verifier is INJECTED, not reloaded. The first version of this test reloaded
# launchd-health-check.py and called the real function: the fresh copy built its
# own `iv` with the real INTENT_MANIFEST and LAUNCH_AGENTS, so it read the live
# machine and never parsed the malformed JSON at all. It passed, green, having
# tested nothing -- and it read a live data path to do it.
_wd2 = _load("launchd-health-check.py", "wd2")


class _ExplodingVerifier:
    @staticmethod
    def check(dry_run=False):
        raise iv.IntentError("launchd-intent.json is not valid JSON: line 1")


_wd2._INTENT = _ExplodingVerifier
_err = []
try:
    _wd2.run_intent_check(dry_run=True)
except Exception as exc:  # noqa: BLE001
    _err.append(repr(exc))
check("a malformed manifest does not raise out of the watchdog", _err, [])

# Negative self-test: prove that assertion can fail. Without the try/except in
# run_intent_check, the same input propagates and the check above goes red.
_leaked = []
try:
    _ExplodingVerifier.check()
except iv.IntentError:
    _leaked.append("raises")
check("the injected verifier really does raise", _leaked, ["raises"])


# =============================================================================
# 12. REPRODUCER: an installed-but-unloaded job was reported as RUNNING
# =============================================================================
# Codex review of PR #134, round 3. The verifier's only sources are the override
# database and the plists on disk; neither says whether a job is bootstrapped. The
# two drift kinds were nonetheless named `running_but_paused` /
# `paused_but_intended_running`, the page read "running but declared paused", and
# the PERMANENT Linear issue closed with "so it is running".
#
# The fixture is installed-but-unloaded BY CONSTRUCTION, not by assertion: a plist
# written into a fresh temp dir that launchd has never seen, so it cannot be
# bootstrapped. Probed against the shipped code, that job produced
# `running_but_paused`, a page reading "running but declared paused", and an issue
# body containing "so it is running" -- three runtime claims about a job that was
# not running.
#
# The fix is the rename plus the reworded page and body. Detection is unchanged: an
# enabled override on a job declared paused is real drift whether or not it is
# loaded, because launchd will run it at the next interval or the next bootstrap.
# What changed is that every claim now names the override record. These assertions
# go RED on the pre-fix code.
_unloaded_dir = Path(tempfile.mkdtemp()) / "LaunchAgents"
_unloaded_dir.mkdir()
UNLOADED = "com.kipi.never-bootstrapped"
(_unloaded_dir / (UNLOADED + ".plist")).write_text("<plist/>")

_saved_agents = iv.LAUNCH_AGENTS
iv.LAUNCH_AGENTS = _unloaded_dir
_unloaded_installed = iv.installed_labels()
iv.LAUNCH_AGENTS = _saved_agents

check("the fixture is installed", _unloaded_installed, {UNLOADED})

_unloaded_findings = iv.diff_intent(
    {UNLOADED: iv.DISABLED}, {UNLOADED: iv.ENABLED}, _unloaded_installed)
check("an installed-but-unloaded job is not called running",
      _unloaded_findings,
      [(UNLOADED, "enabled_but_declared_paused",
        "declared disabled, override record says enabled")])

_unloaded_due, _ = iv.ping_decision(_unloaded_findings, {})
_unloaded_page = iv.ping_message(_unloaded_due)
check("the page claims the override record, not behaviour",
      "override enabled, declared paused" in _unloaded_page, True)

# The consequence, not just the kind: the strings a human actually reads. Each of
# these was present pre-fix, so each can go red on its own.
_unloaded_issue = iv.linear_findings(
    _unloaded_findings, lambda detector, subject: detector + "/" + subject)[0]
_human_text = _unloaded_page + _unloaded_issue["title"] + _unloaded_issue["body"]
for _claim in ("so it is running", "running but declared paused", "is running"):
    check("nothing a human reads claims " + repr(_claim),
          _claim in _human_text, False)

# The permanent issue states what was measured, so a reader six months out does not
# have to open the script to learn that load state was never checked.
check("the issue names its source", "print-disabled" in _unloaded_issue["body"], True)
check("and names what it did not measure",
      "launchctl list" in _unloaded_issue["body"], True)

# The SAME defect on the other side of the same expression: a `disabled` override
# row is not evidence that a bootstrapped job has stopped, because disabling does
# not unload what is already running. Pre-fix that body ended "so it has silently
# stopped running".
_other = iv.diff_intent(
    {UNLOADED: iv.ENABLED}, {UNLOADED: iv.DISABLED}, _unloaded_installed)
check("the other direction is named for the record too",
      [k for _, k, _ in _other], ["disabled_but_declared_running"])
_other_body = iv.linear_findings(
    _other, lambda detector, subject: detector + "/" + subject)[0]["body"]
check("and it does not claim the job stopped",
      "has silently stopped running" in _other_body, False)

# Renaming the kinds re-pings every job still drifting under a pre-rename state
# row. Pinned here rather than discovered on the founder's phone: one duplicate
# page, never a missing one.
_legacy_state = {UNLOADED: {"kind": "running_but_paused", "runs": 7}}
_legacy_due, _ = iv.ping_decision(_unloaded_findings, _legacy_state)
check("a pre-rename state row re-pings once and resets the count",
      [(label, runs) for label, _, _, runs in _legacy_due], [(UNLOADED, 1)])


if failures:
    print("FAIL")
    for line in failures:
        print("  " + line)
    sys.exit(1)
print("PASS: launchd-intent-verify")
sys.exit(0)
