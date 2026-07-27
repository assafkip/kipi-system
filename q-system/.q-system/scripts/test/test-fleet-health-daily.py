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

# --- ASK-150: cron cannot authenticate `claude` (no keychain) ---------------
# Probed 2026-07-23: `keychain_read_rc=44`. The detector's job is to catch a
# crontab line that shells `claude` BEFORE it fails at 3am with an opaque auth
# error. The fixtures are fed in directly so the test never shells `crontab -l`
# (a test that reads live machine state passes or fails for the wrong reason).

CRON_WITH_CLAUDE = """\
# a comment line that mentions claude -p must NOT count
PATH=/usr/local/bin:/usr/bin:/bin
0 3 * * * cd ~/projects/kipi-system && timeout 1800 claude -p "sweep" </dev/null
"""

# The launchd-only machine: real cron lines, none of which invoke claude. Every
# line here is a decoy that a naive substring match would flag.
CRON_LAUNCHD_ONLY = """\
# claude -p "this is a comment, not a job"
CLAUDE_HOME=/Users/x/.claude
30 2 * * * bash ~/.claude/hooks/rotate-logs.sh
0 8 * * * cd ~/projects/claude && ./run_daily.sh
15 * * * * python3 ~/projects/kipi-system/q-system/.q-system/scripts/fleet-health-daily.py
"""

claude_findings = fh.detect_cron_shells_claude(None, cron_text=CRON_WITH_CLAUDE)
check("a crontab line shelling `claude -p` is detected", len(claude_findings), 1)
check(
    "the finding rolls up under ONE stable subject",
    claude_findings[0]["subject"] if claude_findings else None,
    "cron-shells-claude",
)
check(
    "a launchd-only crontab produces no finding",
    fh.detect_cron_shells_claude(None, cron_text=CRON_LAUNCHD_ONLY),
    [],
)
check("an empty crontab produces no finding", fh.detect_cron_shells_claude(None, cron_text=""), [])

# The false positives that would file a PERMANENT issue, asserted one by one.
check("`cd` into a dir named claude is not an invocation",
      fh._shells_claude("cd ~/projects/claude && ./run.sh"), False)
check("a script under ~/.claude/ is not an invocation",
      fh._shells_claude("bash ~/.claude/hooks/rotate-logs.sh"), False)
check("a claude-prefixed binary is not `claude`",
      fh._shells_claude("claude-code --version"), False)

# The true positives, including the wrapper shapes this fleet actually uses.
check("bare `claude -p` is an invocation", fh._shells_claude('claude -p "x"'), True)
check("`timeout 1800 claude` is an invocation",
      fh._shells_claude("timeout 1800 claude -p 'x' </dev/null"), True)
check("an absolute claude path is an invocation",
      fh._shells_claude("/Users/x/.claude/local/claude -p 'x'"), True)
check("claude inside `bash -lc` is an invocation",
      fh._shells_claude("bash -lc 'claude -p \"x\"'"), True)
check("claude after `&&` is an invocation",
      fh._shells_claude("cd ~/projects/x && claude -p 'x'"), True)

# The schedule fields must be stripped, and non-job lines must not be parsed.
check("a comment line yields no command", fh._cron_command("# 0 3 * * * claude -p 'x'"), "")
check("a crontab env assignment yields no command", fh._cron_command("MAILTO=me@example.com"), "")
check("a @daily line strips the special field",
      fh._cron_command("@daily claude -p 'x'"), "claude -p 'x'")

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

if failures:
    print("FAIL:")
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)
print("PASS: fleet-health-daily contract holds")
sys.exit(0)
