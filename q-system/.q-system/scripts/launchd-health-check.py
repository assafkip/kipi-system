#!/usr/bin/env python3
"""Watchdog for kipi launchd jobs -- surfaces silent job deaths.

Auto-discovers every ~/Library/LaunchAgents/com.kipi.*.plist, reads each job's
LastExitStatus via `launchctl list`, and Slack-pings (deduped) when a job's last
run exited non-zero.

Scar: the fractional-cxo income scanners (opp-scan, bolt-on-discovery) exited 127
every day for 6 days (2026-06-24..2026-06-30) after a `kipi update` rsync --delete
wiped their scripts out from under the plists. Nothing surfaced it -- the jobs just
silently stopped hunting income. A prompt cannot watch launchd; this job can. It is
the deterministic backstop that turns a silent 127 into a phone ping within hours.

Single notification channel: slack-notify.sh (founder-notifications rule). Silent
no-op if no webhook is configured, so this watchdog never breaks anything.

The watchdog always exits 0 -- it must never become the failing job it reports.

Usage:
  launchd-health-check.py            # check; ping on newly/again-failing jobs
  launchd-health-check.py --dry      # print findings only; no ping, no state write
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

SELF_LABEL = "com.kipi.launchd-health"
FAIL_PING_TTL_SECONDS = 6 * 3600  # re-ping a still-failing job at most this often
HERE = Path(__file__).resolve().parent
NOTIFY_SCRIPT = HERE / "slack-notify.sh"
STATE_FILE = Path.home() / ".config" / "kipi" / "launchd-health-state.json"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"


def normalize_exit(raw):
    """launchctl reports LastExitStatus as a raw wait(2) status. Decode to the
    human exit code: exit 3 arrives as 3<<8 = 768; a signal kill as 128+signal.
    A small value (<256) is already a clean code, so pass it through."""
    if raw == 0 or 0 < raw < 256:
        return raw
    exit_code = (raw >> 8) & 0xFF
    if exit_code:
        return exit_code
    signal_num = raw & 0x7F
    return 128 + signal_num if signal_num else raw


def last_exit_status(label):
    """Return decoded LastExitStatus for a launchd label, or 0 if unknown/never-ran."""
    try:
        result = subprocess.run(
            ["launchctl", "list", label],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return 0
    match = re.search(r'"LastExitStatus"\s*=\s*(-?\d+)', result.stdout)
    return normalize_exit(int(match.group(1))) if match else 0


def discover_failing_jobs():
    """List (label, exit_code) for every com.kipi.* job whose last run failed."""
    failing = []
    for plist in sorted(LAUNCH_AGENTS.glob("com.kipi.*.plist")):
        label = plist.stem
        if label == SELF_LABEL:
            continue
        exit_code = last_exit_status(label)
        if exit_code != 0:
            failing.append((label, exit_code))
    return failing


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def write_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def send_ping(message):
    if not NOTIFY_SCRIPT.exists():
        return
    try:
        subprocess.run(["bash", str(NOTIFY_SCRIPT), message], timeout=20)
    except Exception:
        pass


def jobs_to_ping(failing, state, now):
    """Failing jobs whose last ping is older than the TTL (dedupe spam)."""
    due = []
    for label, exit_code in failing:
        last_pinged = state.get(label, {}).get("pinged_at", 0)
        if now - last_pinged >= FAIL_PING_TTL_SECONDS:
            due.append((label, exit_code))
    return due


def run(dry_run):
    failing = discover_failing_jobs()

    if not failing:
        if dry_run:
            print("all kipi launchd jobs healthy (exit 0)")
        elif STATE_FILE.exists():
            write_state({})  # everything recovered; clear ping history
        return

    for label, exit_code in failing:
        print(f"FAILING: {label} exit {exit_code}")

    state = load_state()
    now = int(time.time())
    due = jobs_to_ping(failing, state, now)

    if dry_run:
        print(f"[dry] would ping {len(due)} job(s)")
        return

    if due:
        summary = ", ".join(f"{label} (exit {code})" for label, code in due)
        send_ping(f"launchd watchdog: {len(due)} job(s) failing -- {summary}")
        for label, exit_code in due:
            state[label] = {"pinged_at": now, "exit": exit_code}

    failing_labels = {label for label, _ in failing}
    for label in [k for k in state if k not in failing_labels]:
        state.pop(label)  # recovered since last run

    write_state(state)


if __name__ == "__main__":
    try:
        run("--dry" in sys.argv)
    finally:
        sys.exit(0)  # a watchdog must never report itself as the failing job
