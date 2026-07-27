#!/usr/bin/env python3
"""Pairs with fleet-health-daily.py.

The contract under test is the founder's rule, 2026-07-26: "detection without a
path to action is useless... the system should learn." A detector that only alerts
has moved the work back onto the founder. Prose cannot hold that line, so the
registry validator does — and this file is what proves the validator refuses.

Also guards the false-positive case that was live on day one: matching cron
scripts by BASENAME flagged 3 jobs when only 1 was a real duplicate. Linear issues
cannot be deleted here, so a false positive is a permanent one.

Run: python3 test-fleet-health-daily.py   (exit 0 = pass)
"""

import importlib.util
import sys
from pathlib import Path

HEALTH = Path(__file__).resolve().parents[1] / "fleet-health-daily.py"
_spec = importlib.util.spec_from_file_location("fh", HEALTH)
fh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fh)

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")
    else:
        print(f"  ok: {name}")


def check_rejects(name, detector, needle):
    problems = fh.validate_detectors([detector])
    if not any(needle in p for p in problems):
        failures.append(f"{name}: expected a problem containing {needle!r}, got {problems!r}")
    else:
        print(f"  ok: {name}")


ok_detector = {
    "id": "x", "description": "d", "detect": lambda _c: [],
    "action": "file_issue", "lesson": "some-lesson",
}

# --- the shipped registry must satisfy its own contract ---------------------
check("the real registry is valid", fh.validate_detectors(), [])
check("registry is non-empty", len(fh.DETECTORS) > 0, True)

# --- THE RULE: detection with no action path is refused ---------------------
check_rejects(
    "a detector with no action is refused",
    {**ok_detector, "action": None},
    "action must be",
)
check_rejects(
    "a detector with a bogus action is refused",
    {**ok_detector, "action": "notify_founder"},
    "action must be",
)

# --- THE RULE: prevention outranks detection --------------------------------
d = {**ok_detector}
d.pop("lesson")
check_rejects("a detector that cannot learn is refused", d, "lesson")

check(
    "an explicit waiver satisfies the learning leg",
    fh.validate_detectors([{**d, "lesson_waived": "one-off by nature"}]),
    [],
)

# --- an auto_fix claim must actually be wired -------------------------------
check_rejects(
    "auto_fix without a fix() is refused",
    {**ok_detector, "action": "auto_fix"},
    "no fix() is wired",
)
check(
    "auto_fix WITH a fix() is accepted",
    fh.validate_detectors([{**ok_detector, "action": "auto_fix", "fix": lambda f: None}]),
    [],
)

# --- dedup keys must be stable, or every morning files a new permanent issue -
check(
    "finding_key is stable and namespaced",
    fh.finding_key("launchd-dark", "com.cole.daily-podcast"),
    "fleet-health/launchd-dark/com-cole-daily-podcast",
)
check(
    "finding_key is deterministic across calls",
    fh.finding_key("a", "B c!") == fh.finding_key("a", "B c!"),
    True,
)

# --- the false positive that was live on day one ----------------------------
# `run_daily.sh` exists under reddit-build-radar, daily-podcast AND story-podcast.
# Only the first is genuinely double-scheduled. Basename matching flagged all 3.
check(
    "slug() collapses punctuation so keys cannot fork on formatting",
    fh.slug("com.cole.reddit-radar-daily"),
    "com-cole-reddit-radar-daily",
)

# every shipped detector must be callable and return a list
for det in fh.DETECTORS:
    try:
        result = det["detect"](None)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"detector {det['id']} raised: {exc}")
        continue
    if not isinstance(result, list):
        failures.append(f"detector {det['id']} returned {type(result).__name__}, want list")
        continue
    for f in result:
        if not f.get("subject"):
            failures.append(f"detector {det['id']} emitted a finding with no stable subject")
print(f"  ok: all {len(fh.DETECTORS)} shipped detectors run and return findings with subjects")

# --- a dead filer must not read like a clean run (ASK-181 review, finding 1) --
# file_findings catches its own network errors and returns skipped_no_key=N. This
# job's report printed created + existing only, so "Linear was unreachable and 5
# findings went nowhere" printed byte-identically to "the fleet is clean". Same
# defect, same fix as launchd-health-check.py -- fixing only the watchdog would
# have left the 08:15 job, which files the SAME findings, still lying.
_dead = {"created": 0, "existing": 0, "skipped_no_key": 2}
_clean = {"created": 0, "existing": 0, "skipped_no_key": 0}
check("a dead filer's report differs from a clean one",
      fh.outcome_line(_dead) == fh.outcome_line(_clean), False)
check("the report names findings that never reached Linear",
      "unfiled=2" in fh.outcome_line(_dead), True)
check("a clean run reports nothing unfiled", "unfiled=0" in fh.outcome_line(_clean), True)
check("the counts stay in the line",
      "filed=3" in fh.outcome_line({"created": 3, "existing": 1, "skipped_no_key": 0}), True)

# and the line must actually be the one main() prints, or the fix is a function
# nobody calls.
import inspect  # noqa: E402 - local to this assertion

check("main() reports through outcome_line", "outcome_line(" in inspect.getsource(fh.main), True)

if failures:
    print("FAIL:")
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)
print("PASS: fleet-health-daily contract holds")
sys.exit(0)
