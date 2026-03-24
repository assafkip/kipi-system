#!/usr/bin/env python3
"""
Bus file verification harness. Run between pipeline phases to ensure
expected files exist and have valid structure.

Usage:
  python3 verify-bus.py <date> <phase>

Phases: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9

Exit codes:
  0 = all expected files present and valid
  1 = missing or invalid files (prints which ones)
"""

import json
import os
import sys
from datetime import datetime

def verify(date, phase):
    bus_dir = f"q-system/.q-system/agent-pipeline/bus/{date}"

    if not os.path.isdir(bus_dir):
        print(f"FAIL: Bus directory does not exist: {bus_dir}")
        return False

    # Define expected files per phase (cumulative)
    phase_files = {
        0: {
            "required": ["preflight.json", "energy.json"],
            "checks": {
                "preflight.json": lambda d: d.get("ready") == True,
                "energy.json": lambda d: d.get("level") in range(1, 6),
            }
        },
        1: {
            "required": ["calendar.json", "gmail.json", "notion.json"],
            "optional": ["vc-pipeline.json", "content-metrics.json", "copy-diffs.json"],
            "checks": {
                "calendar.json": lambda d: "today" in d or "this_week" in d,
                "gmail.json": lambda d: "emails" in d,
                "notion.json": lambda d: "contacts" in d and "actions" in d,
                "canonical-digest.json": lambda d: "talk_tracks" in d and "objections" in d and "decisions" in d,
            }
        },
        2: {
            "required": ["meeting-prep.json", "warm-intros.json"],
            "checks": {}
        },
        3: {
            "required": ["linkedin-posts.json", "linkedin-dms.json", "dp-pipeline.json"],
            "optional": ["behavioral-signals.json", "prospect-activity.json"],
            "checks": {
                "linkedin-posts.json": lambda d: "posts" in d,
                "linkedin-dms.json": lambda d: "dms" in d,
                "behavioral-signals.json": lambda d: "signals" in d,
            }
        },
        4: {
            "required": ["signals.json"],
            "optional": ["value-routing.json", "post-visuals.json", "kipi-promo.json"],
            "checks": {
                "signals.json": lambda d: "selected_signal" in d or "linkedin_draft" in d,
            }
        },
        5: {
            "required": ["temperature.json", "leads.json", "hitlist.json"],
            "optional": ["pipeline-followup.json", "loop-review.json"],
            "checks": {
                "hitlist.json": lambda d: "actions" in d and len(d["actions"]) > 0,
                "temperature.json": lambda d: "scores" in d or "prospects" in d,
            }
        },
        6: {
            "required": ["compliance.json", "positioning.json"],
            "checks": {
                "compliance.json": lambda d: "overall_pass" in d or "items_checked" in d,
            }
        },
        7: {
            "required": [],
            "optional": ["outreach-queue.json"],
            "checks": {
                "outreach-queue.json": lambda d: "queue" in d,
            }
        },
        9: {
            "required": [],
            "optional": ["notion-push.json", "daily-checklists.json"],
            "checks": {}
        },
    }

    if phase not in phase_files:
        print(f"Unknown phase: {phase}")
        return True

    spec = phase_files[phase]
    required = spec.get("required", [])
    optional = spec.get("optional", [])
    checks = spec.get("checks", {})

    all_pass = True
    results = []

    for f in required:
        path = os.path.join(bus_dir, f)
        if not os.path.isfile(path):
            results.append(f"  FAIL [required] {f}: MISSING")
            all_pass = False
            continue
        try:
            with open(path) as fh:
                data = json.load(fh)
            if "error" in data:
                results.append(f"  WARN [required] {f}: has error key ({data['error']})")
            elif f in checks and not checks[f](data):
                results.append(f"  FAIL [required] {f}: structure check failed")
                all_pass = False
            else:
                results.append(f"  OK   [required] {f}")
        except json.JSONDecodeError as e:
            results.append(f"  FAIL [required] {f}: invalid JSON ({e})")
            all_pass = False

    for f in optional:
        path = os.path.join(bus_dir, f)
        if not os.path.isfile(path):
            results.append(f"  SKIP [optional] {f}: not present")
            continue
        try:
            with open(path) as fh:
                data = json.load(fh)
            if "error" in data:
                results.append(f"  WARN [optional] {f}: has error key")
            elif f in checks and not checks[f](data):
                results.append(f"  WARN [optional] {f}: structure check failed")
            else:
                results.append(f"  OK   [optional] {f}")
        except json.JSONDecodeError:
            results.append(f"  WARN [optional] {f}: invalid JSON")

    print(f"Phase {phase} bus verification ({date}):")
    for r in results:
        print(r)
    print(f"Result: {'PASS' if all_pass else 'FAIL'}")
    return all_pass

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <date> <phase>")
        sys.exit(1)
    date = sys.argv[1]
    phase = int(sys.argv[2])
    success = verify(date, phase)
    sys.exit(0 if success else 1)
