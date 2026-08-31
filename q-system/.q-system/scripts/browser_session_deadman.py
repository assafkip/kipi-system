#!/usr/bin/env python3
"""If the browser-session health check stopped running, this says so.

## Why it is a different job

The thing being watched is a checker that did not run, and a checker that did
not run is silent. Silence is also exactly what a fleet of healthy sessions
looks like, so from the outside "everything is fine" and "the watchman is dead"
are the same observation. That is the case this job exists for, and it cannot
live inside the job it watches.

Same shape as `morning-brief-deadman.py`, for the same measured reasons:
StartInterval plus RunAtLoad rather than a calendar trigger, because a calendar
job is SKIPPED outright when the Mac is off at fire time and launchd does not
catch up on wake, so a watcher on the same trigger class shares its suspect's
failure mode.

## It watches the RECEIPT, not a log

`~/.config/kipi/browser-session-health.json` is written by the health job after
every probe cycle. A log file's mtime is a liveness proxy and a proxy is how a
green watchdog ends up sitting over a dead capability.

## It fires on transition too

Founder-directed 2026-08-30, same rule as the health alerts: healthy to stale
tells him once, stale to stale is silent, and recovery gets one line. A
30-minute job that alarmed every run would send 48 messages a day about one
outage, and a muted channel is the same as no channel.

## Known limit, stated rather than papered over

This runs on the same Mac as the job it watches, so a machine that is off,
asleep or wedged silences both together. StartInterval + RunAtLoad narrows it
(the alarm fires within one interval of the next wake, where a calendar job
would have been skipped outright) but does not close it. The real fix is an
alarm off this machine, which is a different job with its own delivery proof.

    browser_session_deadman.py            # check; alarm if stale
    browser_session_deadman.py --dry-run  # print the verdict, send nothing
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("KIPI_STATE_DIR", os.path.expanduser("~/.config/kipi")))
RECEIPT_PATH = STATE_DIR / "browser-session-health.json"
ALARM_STATE = STATE_DIR / "browser-session-deadman-state.json"

# The health job runs every 30 minutes. Three missed cycles, so a single slow
# probe or a reboot does not alarm, and a job that actually died does.
STALE_AFTER_MIN = int(os.environ.get("KIPI_BROWSER_HEALTH_STALE_MIN", "95"))


def check(now: dt.datetime, receipt_path=None):
    """(ok, reason). `ok` means the health job wrote a receipt recently enough.

    An unreadable or absent receipt is NOT ok. Treating a corrupt receipt as
    healthy makes the alarm quietest exactly when the system is most broken.
    """
    path = Path(receipt_path) if receipt_path else RECEIPT_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False, f"no browser-session-health receipt at all ({path})"
    except (ValueError, OSError) as exc:
        return False, f"browser-session-health receipt unreadable ({path}): {exc}"
    if not isinstance(data, dict) or not data.get("at"):
        return False, f"browser-session-health receipt has no timestamp ({path})"
    try:
        stamped = dt.datetime.fromisoformat(data["at"])
    except ValueError as exc:
        return False, f"browser-session-health receipt timestamp unparseable: {exc}"

    # Compare naive-to-naive or aware-to-aware; a receipt written by the live
    # job carries a timezone and a fixture may not.
    reference = now
    if (stamped.tzinfo is None) != (reference.tzinfo is None):
        stamped = stamped.replace(tzinfo=None)
        reference = reference.replace(tzinfo=None)

    age_min = (reference - stamped).total_seconds() / 60
    if age_min > STALE_AFTER_MIN:
        return False, (f"the browser-session health check last wrote a receipt "
                       f"{age_min:.0f} minutes ago (stale after "
                       f"{STALE_AFTER_MIN}); nothing is watching the sessions")
    return True, None


def _read_state(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _founder_sender(message: str) -> dict:
    spec = importlib.util.spec_from_file_location(
        "slack_founder", HERE / "slack_founder.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.deliver(message)


def run(now: dt.datetime, receipt_path=None, state_path=None, sender=None) -> int:
    """One pass. Returns 0 when the health job is fresh, 1 when it is not.

    Non-zero either way once stale, including when the message could not be
    delivered: launchd-health-check reads the exit status and files its own
    issue, so a deadman that cannot reach Slack is still not a silent one.
    """
    sender = sender or _founder_sender
    state_path = Path(state_path) if state_path else ALARM_STATE
    ok, reason = check(now, receipt_path=receipt_path)
    state = _read_state(state_path)
    already = bool(state.get("alarmed"))
    stamp = now.isoformat(timespec="seconds")

    if ok:
        if already:
            sender(f":white_check_mark: The browser-session health check is "
                   f"running again. Verified {stamp}.")
            _write_state(state_path, {"alarmed": False, "at": stamp})
        return 0

    if already:
        return 1

    sender(f":rotating_light: Nothing is checking the research browser "
           f"sessions. {reason}\n"
           f"Checked {stamp} by com.kipi.browser-session-deadman.\n"
           f"You get this once. Nothing further until it recovers.")
    _write_state(state_path, {"alarmed": True, "at": stamp, "reason": reason})
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    now = dt.datetime.now().astimezone()

    if args.dry_run:
        ok, reason = check(now)
        print(f"[deadman][dry-run] ok={ok} reason={reason}")
        return 0 if ok else 1

    captured = []

    def sender(message: str) -> dict:
        captured.append(message)
        return _founder_sender(message)

    rc = run(now, sender=sender)
    for message in captured:
        print(f"[deadman][send] {message.splitlines()[0]}")
    if not captured:
        print(f"[deadman] {now:%Y-%m-%d %H:%M} rc={rc}; silent")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
