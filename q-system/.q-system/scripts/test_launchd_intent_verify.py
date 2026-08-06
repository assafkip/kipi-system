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
import importlib.util
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
check("REPRODUCER half B: verifier reports running_but_paused",
      iv.diff_intent(_intent, {"com.kipi.zzz-should-be-paused": "enabled"},
                     {"com.kipi.zzz-should-be-paused"}),
      [("com.kipi.zzz-should-be-paused", "running_but_paused",
        "declared disabled, launchd says enabled")])

# Half B', the same job with NO override row at all. This is the common case: 65
# watched plists on disk, 32 override rows (measured 2026-08-06). If absence were
# read as 'unknown' instead of 'enabled', two thirds of the fleet would go
# unverified and this finding would vanish.
check("REPRODUCER half B': absent override still reports drift",
      iv.diff_intent(_intent, {}, {"com.kipi.zzz-should-be-paused"}),
      [("com.kipi.zzz-should-be-paused", "running_but_paused",
        "declared disabled, launchd says enabled")])


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


# =============================================================================
# 5. diff_intent -- all four kinds, and agreement producing silence
# =============================================================================
check("intent matching reality reports nothing",
      iv.diff_intent({"a": "enabled"}, {"a": "enabled"}, {"a"}), [])
check("declared enabled, launchd disabled",
      iv.diff_intent({"a": "enabled"}, {"a": "disabled"}, {"a"}),
      [("a", "paused_but_intended_running", "declared enabled, launchd says disabled")])
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
# `running_but_paused` for a job with no executable on disk. A stale override row
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
# row produced `running_but_paused`, which IS in PINGABLE_KINDS, so a job with no
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
DRIFT = [("a", "running_but_paused", "d")]

due, state = iv.ping_decision(DRIFT, {})
check("first sighting pings", due, [("a", "running_but_paused", "d", 1)])
check("and records one run", state, {"a": {"kind": "running_but_paused", "runs": 1, "detail": "d"}})

due, state = iv.ping_decision(DRIFT, state)
check("second consecutive run is silent", due, [])
check("but the count still advances", state["a"]["runs"], 2)

# Walk to the repeat threshold. The count is what re-fires, so this cannot be
# defeated by a schedule change the way a wall-clock TTL was (ASK-283).
s = {"a": {"kind": "running_but_paused", "runs": iv.REPEAT_EVERY_RUNS - 1}}
due, _ = iv.ping_decision(DRIFT, s)
check("re-pings at the consecutive-run threshold",
      due, [("a", "running_but_paused", "d", iv.REPEAT_EVERY_RUNS)])

# A different bad state is a new transition and pings immediately.
s = {"a": {"kind": "paused_but_intended_running", "runs": 9}}
due, _ = iv.ping_decision(DRIFT, s)
check("a changed kind re-pings and resets the count",
      due, [("a", "running_but_paused", "d", 1)])

# Coverage findings never reach the phone.
check("undeclared is never pingable",
      iv.ping_decision([("z", "undeclared", "no declared intent")], {})[0], [])
check("orphan is never pingable",
      iv.ping_decision([("z", "orphan", "x")], {})[0], [])

# One line for the whole run, not one ping per finding.
msg = iv.ping_message([("a", "running_but_paused", "d", 1),
                       ("b", "paused_but_intended_running", "d", 14)])
check("one message names both jobs", msg.count("--"), 1)
check("message says what drifted", "running but declared paused" in msg, True)
check("message carries the consecutive count", "14 runs" in msg, True)


# =============================================================================
# 8. linear_findings -- pingable kinds only, keyed through the shared keyer
# =============================================================================
lf = iv.linear_findings(
    [("a", "running_but_paused", "d"), ("z", "undeclared", "x")],
    lambda detector, subject: f"fleet-health/{detector}/{subject}")
check("only drift kinds are filed", [f["subject"] for f in lf], ["a"])
check("filed under the intent-drift detector", lf[0]["detector"], "launchd-intent-drift")
check("body names the label", "`a`" in lf[0]["body"], True)


# =============================================================================
# 9. check() -- the wiring, against a tmpdir, with injected launchd state
# =============================================================================
_home = Path(tempfile.mkdtemp())
iv.INTENT_MANIFEST = _home / "launchd-intent.json"
iv.STATE_FILE = _home / "state.json"
iv.LEGACY_PAUSED_FILES = (_home / "paused.txt",)
(_home / "paused.txt").write_text("com.kipi.paused-job\n")

findings, due, cov = iv.check(
    overrides={"com.kipi.paused-job": "enabled"},
    labels={"com.kipi.paused-job", "com.kipi.other"},
)
check("check() surfaces the drift",
      [(l, k) for l, k, _ in findings if k in iv.PINGABLE_KINDS],
      [("com.kipi.paused-job", "running_but_paused")])
check("check() pings the transition", [d[0] for d in due], ["com.kipi.paused-job"])
check("check() reports partial coverage", cov, (1, 2))
check("check() persisted the run count", json.loads(iv.STATE_FILE.read_text())
      ["com.kipi.paused-job"]["runs"], 1)

# dry mode must not advance the counter that decides future pings.
before = iv.STATE_FILE.read_text()
iv.check(dry_run=True, overrides={"com.kipi.paused-job": "enabled"},
         labels={"com.kipi.paused-job"})
check("dry run writes no state", iv.STATE_FILE.read_text(), before)


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

if failures:
    print("FAIL")
    for line in failures:
        print("  " + line)
    sys.exit(1)
print("PASS: launchd-intent-verify")
sys.exit(0)
