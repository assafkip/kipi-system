#!/usr/bin/env python3
"""Watchdog for the founder's launchd jobs -- surfaces silent job deaths.

Auto-discovers every ~/Library/LaunchAgents/<prefix>*.plist for the OS's base
job families (WATCHED_PREFIXES) plus any instance-local families listed in
EXTRA_PREFIXES_FILE, and Slack-pings (deduped) on TWO silent-death modes:
  1. loaded but its last run exited non-zero (LastExitStatus via `launchctl list`)
  2. installed on disk but NOT loaded into launchd -- so it silently never runs.
     Scar 2026-07-05: com.cole.daily-video was present + scheduled 07:00 but
     unloaded, so it produced no video AND no failure ping (an unloaded job
     cannot ping). Mode 1 alone -- the old com.kipi.*-only check -- was blind to
     both the non-kipi families and the entirely-unloaded case.

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

# Base launchd job families this OS's own automation uses. A prefix that matches
# nothing on a given machine is a harmless no-op. Instance- or client-specific
# families (client slack syncs, brand jobs) live in EXTRA_PREFIXES_FILE below, NOT
# here -- the skeleton propagates fleet-wide via kipi update and must carry no
# single instance's brand names.
WATCHED_PREFIXES = (
    "com.kipi.",
    "com.cole.",         # daily podcast/video GTM pipeline
    "com.claudedaddy.",  # social posters (Pinterest/X/YouTube/refill/repo)
    "com.ask.",          # ASK AI podcast
    "com.assaf.",        # competitive-analysis morning
)

# Instance-local additions, one prefix per line ('#' starts a comment). Lives in
# the founder's live env (~/.config/kipi/), outside the repo, so client/brand job
# families are watched without being baked into the propagated skeleton. Missing
# file = base set only (harmless no-op).
EXTRA_PREFIXES_FILE = Path.home() / ".config" / "kipi" / "launchd-watch-prefixes.txt"


def load_watched_prefixes():
    """Base families plus any instance-local additions from EXTRA_PREFIXES_FILE."""
    prefixes = list(WATCHED_PREFIXES)
    try:
        lines = EXTRA_PREFIXES_FILE.read_text().splitlines()
    except FileNotFoundError:
        return tuple(prefixes)
    for line in lines:
        entry = line.split("#", 1)[0].strip()
        if entry and entry not in prefixes:
            prefixes.append(entry)
    return tuple(prefixes)


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


def job_status(label):
    """Classify a launchd label:
      ('failing', code)     loaded, last run exited non-zero
      ('not_loaded', None)  plist on disk but not bootstrapped -> never runs
      ('ok', 0)             loaded, last run clean
      ('unknown', None)     launchctl unavailable -- do not alert
    `launchctl list <label>` exits non-zero when the label is not loaded, which
    is how a silently-unloaded job (present plist, absent from launchd) is caught."""
    try:
        result = subprocess.run(
            ["launchctl", "list", label],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return ("unknown", None)
    if result.returncode != 0:
        return ("not_loaded", None)
    match = re.search(r'"LastExitStatus"\s*=\s*(-?\d+)', result.stdout)
    code = normalize_exit(int(match.group(1))) if match else 0
    return ("failing", code) if code != 0 else ("ok", 0)


def discover_problems():
    """List (label, kind, detail) for every watched job that is failing or
    installed-but-unloaded. Watched = any watched-prefix plist, minus self."""
    problems = []
    seen = set()
    for prefix in load_watched_prefixes():
        for plist in sorted(LAUNCH_AGENTS.glob(f"{prefix}*.plist")):
            label = plist.stem
            if label == SELF_LABEL or label in seen:
                continue
            seen.add(label)
            kind, code = job_status(label)
            if kind == "failing":
                problems.append((label, "failing", f"exit {code}"))
            elif kind == "not_loaded":
                problems.append((label, "not_loaded", "installed but not running"))
    return problems


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


def problems_to_ping(problems, state, now):
    """Problems whose kind changed since the last ping, or whose last ping is
    older than the TTL (dedupe spam, but re-ping when failing -> not_loaded)."""
    due = []
    for label, kind, detail in problems:
        prev = state.get(label, {})
        kind_changed = prev.get("kind") != kind
        last_pinged = prev.get("pinged_at", 0)
        if kind_changed or now - last_pinged >= FAIL_PING_TTL_SECONDS:
            due.append((label, kind, detail))
    return due


def run(dry_run):
    problems = discover_problems()

    if not problems:
        if dry_run:
            print("all watched launchd jobs healthy (loaded, exit 0)")
        elif STATE_FILE.exists():
            write_state({})  # everything recovered; clear ping history
        return

    for label, kind, detail in problems:
        print(f"{kind.upper()}: {label} -- {detail}")

    state = load_state()
    now = int(time.time())
    due = problems_to_ping(problems, state, now)

    if dry_run:
        print(f"[dry] would ping {len(due)} job(s)")
        return

    if due:
        parts = [
            f"{label} (installed but NOT running)" if kind == "not_loaded"
            else f"{label} ({detail})"
            for label, kind, detail in due
        ]
        send_ping(f"launchd watchdog: {len(due)} job issue(s) -- " + ", ".join(parts))
        for label, kind, detail in due:
            state[label] = {"pinged_at": now, "kind": kind, "detail": detail}

    problem_labels = {label for label, _, _ in problems}
    for label in [k for k in state if k not in problem_labels]:
        state.pop(label)  # recovered since last run

    write_state(state)


if __name__ == "__main__":
    try:
        run("--dry" in sys.argv)
    finally:
        sys.exit(0)  # a watchdog must never report itself as the failing job
