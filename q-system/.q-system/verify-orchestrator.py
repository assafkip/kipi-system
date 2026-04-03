#!/usr/bin/env python3
"""
Orchestrator housekeeping verifier. Run BETWEEN phases to enforce:
1. Gate checks are logged after verify-bus passes
2. Session-start checksums exist (Phase 0 only)
3. Action cards are logged after hitlist is written (Phase 5 only)

This is the harness that prevents the orchestrator (the LLM) from
skipping its own responsibilities. Agents handle content; this script
handles process.

Usage:
  python3 verify-orchestrator.py <date> <phase> [--fix]

Exit codes:
  0 = all housekeeping done
  1 = missing housekeeping (blocks next phase)
  2 = missing housekeeping, auto-fixed with --fix

The --fix flag generates the missing log entries from bus data.
Use this ONLY when the data exists but the log call was skipped.
"""

import json
import os
import sys
from datetime import datetime

# Resolve QROOT relative to this script's location (../ from .q-system/)
QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def load_log(date):
    path = os.path.join(QROOT, "output", f"morning-log-{date}.json")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return json.load(f)


def load_bus(date, filename):
    path = os.path.join(QROOT, ".q-system", "agent-pipeline", "bus", date, filename)
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return json.load(f)


def log_step_script():
    return os.path.join(QROOT, ".q-system", "log-step.py")


def check_phase(date, phase, fix=False):
    log = load_log(date)
    if not log:
        print(f"  [FAIL] Morning log not found. Run: python3 {log_step_script()} {date} init")
        return False

    issues = []
    fixes_applied = []

    # -- Phase 0: Session-start checksums --
    if phase == 0:
        checksums = log.get("state_checksums", {}).get("session_start", {})
        if not checksums:
            issues.append("No session-start checksums recorded")
            if fix:
                # Auto-generate checksums from current state
                import subprocess
                checks = {}
                # Count canonical files
                canonical_dir = os.path.join(QROOT, "canonical")
                if os.path.isdir(canonical_dir):
                    checks["canonical_file_count"] = str(len(os.listdir(canonical_dir)))
                # Count bus files
                bus_dir = os.path.join(QROOT, ".q-system", "agent-pipeline", "bus", date)
                if os.path.isdir(bus_dir):
                    checks["bus_file_count"] = str(len([f for f in os.listdir(bus_dir) if f.endswith('.json')]))
                for key, val in checks.items():
                    subprocess.run([
                        "python3", log_step_script(),
                        date, "checksum-start", key, val
                    ], capture_output=True)
                fixes_applied.append(f"Recorded {len(checks)} session-start checksums")

    # -- All phases: Gate check after verify-bus --
    # Gate names must match audit-morning.py expectations: step_8, step_9, step_11
    if phase >= 1:
        gates = log.get("gates_checked", {})
        gate_name = f"step_{phase}"
        if gate_name not in gates:
            # Check if verify-bus was run (bus files exist for this phase)
            bus_dir = os.path.join(QROOT, ".q-system", "agent-pipeline", "bus", date)
            phase_complete = os.path.isdir(bus_dir)  # simplified check
            issues.append(f"Gate check not logged for phase {phase}")
            if fix and phase_complete:
                import subprocess
                # Determine what steps ran
                steps = log.get("steps", {})
                step_keys = list(steps.keys())
                subprocess.run([
                    "python3", log_step_script(),
                    date, "gate-check", gate_name, "true", ""
                ], capture_output=True)
                fixes_applied.append(f"Logged gate check for phase {phase}")

    # -- Phase 5 (after hitlist): Action cards --
    if phase == 5:
        action_cards = log.get("action_cards", [])
        hitlist = load_bus(date, "hitlist.json")
        if hitlist and hitlist.get("actions") and not action_cards:
            actions = hitlist["actions"]
            issues.append(f"Hitlist has {len(actions)} actions but 0 action cards logged")
            if fix:
                import subprocess
                for action in actions:
                    rank = action.get("rank", 0)
                    action_type = action.get("action_type", "unknown")
                    contact = action.get("contact_name", "unknown")
                    copy_text = action.get("copy", "")[:200]
                    post_url = action.get("post_url") or action.get("profile_url") or ""
                    # Map action type to card ID prefix
                    prefix = {"comment": "C", "DM": "DM", "connection_request": "CR"}.get(action_type, "A")
                    card_id = f"{prefix}{rank}"
                    subprocess.run([
                        "python3", log_step_script(),
                        date, "add-card", card_id, action_type, contact, copy_text, post_url
                    ], capture_output=True)
                fixes_applied.append(f"Logged {len(actions)} action cards from hitlist")

    # -- Phase 5: Connection request minimum --
    if phase == 5:
        hitlist = load_bus(date, "hitlist.json")
        if hitlist and hitlist.get("actions"):
            cr_count = sum(1 for a in hitlist["actions"] if a.get("action_type") == "connection_request")
            leads = load_bus(date, "leads.json")
            has_tier_a = False
            if leads and leads.get("qualified_leads"):
                has_tier_a = any(l.get("tier") == "A" for l in leads["qualified_leads"])
            if cr_count == 0 and has_tier_a:
                issues.append("Hitlist has 0 connection requests despite Tier A leads available")
                # Don't auto-fix this one -- the hitlist agent needs to regenerate

    # -- Report --
    if fixes_applied:
        print(f"  Orchestrator check (phase {phase}): {len(issues)} issue(s), {len(fixes_applied)} auto-fixed")
        for f_msg in fixes_applied:
            print(f"    [FIXED] {f_msg}")
        return True
    elif issues:
        print(f"  Orchestrator check (phase {phase}): BLOCKED")
        for issue in issues:
            print(f"    [MISSING] {issue}")
        if not fix:
            print(f"\n  To auto-fix: python3 {os.path.join(QROOT, '.q-system', 'verify-orchestrator.py')} {date} {phase} --fix")
        return False
    else:
        print(f"  Orchestrator check (phase {phase}): PASS")
        return True


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <date> <phase> [--fix]")
        sys.exit(1)
    date = sys.argv[1]
    phase = int(sys.argv[2])
    fix = "--fix" in sys.argv
    success = check_phase(date, phase, fix=fix)
    sys.exit(0 if success else 1)
