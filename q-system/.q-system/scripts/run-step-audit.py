#!/usr/bin/env python3
"""Generic step-completion auditor: expected - logged = silently skipped.

Extracted 2026-07-01 from audit-morning.py (its ~5-line kernel, lines 92-96 /
119-123) so jobs other than /q-morning can be audited. The gap this closes:
launchd-health only sees exit codes, so a job that exits 0 having silently
skipped half its steps is invisible (the class behind the 6-day silent
income-scanner death, 2026-06-30). audit-morning.py remains the
morning-specific wrapper; this is the reusable form.

Usage:
  run-step-audit.py --expected step1,step2 --log runlog.json [--job NAME]
  run-step-audit.py --manifest expected.json --log runlog.json [--job NAME]

Run-log schema (minimal, any job can emit it):
  {"job": "...", "steps": [{"id": "...", "status": "completed"}, ...]}
Statuses: completed|skipped = fine (skipped means INTENTIONALLY skipped and
said so). failed or anything else = problem. Expected id never logged at all =
silently skipped, the failure mode this tool exists for.

Exit codes: 0 = clean, 1 = findings (failed and/or silent steps), 2 = bad input.
"""

import argparse
import json
import sys

OK_STATUSES = {"completed", "skipped"}


def load_expected(args):
    if args.expected:
        return [s.strip() for s in args.expected.split(",") if s.strip()]
    with open(args.manifest) as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("manifest must be a JSON array of step ids")
    return [str(s) for s in data]


def audit(expected, logged_steps, job):
    logged = {}
    for step in logged_steps:
        logged[str(step.get("id"))] = str(step.get("status", "")).lower()

    silent = [s for s in expected if s not in logged]
    problems = [
        (sid, status) for sid, status in logged.items()
        if status not in OK_STATUSES
    ]

    label = f"[{job}] " if job else ""
    if not silent and not problems:
        print(f"{label}OK: all {len(expected)} expected steps accounted for")
        return 0
    if problems:
        print(f"{label}FAILED steps ({len(problems)}):")
        for sid, status in problems:
            print(f"  - {sid}: {status}")
    if silent:
        print(f"{label}SILENTLY SKIPPED - expected but never logged ({len(silent)}):")
        for sid in silent:
            print(f"  - {sid}")
    return 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--expected", help="comma-separated expected step ids")
    src.add_argument("--manifest", help="JSON file: array of expected step ids")
    p.add_argument("--log", required=True, help="run-log JSON path")
    p.add_argument("--job", default="", help="job name for output labeling")
    args = p.parse_args()

    try:
        expected = load_expected(args)
        with open(args.log) as f:
            run_log = json.load(f)
        steps = run_log.get("steps")
        if not isinstance(steps, list):
            raise ValueError('run-log needs a "steps" array')
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}")
        return 2

    return audit(expected, steps, args.job or run_log.get("job", ""))


if __name__ == "__main__":
    sys.exit(main())
