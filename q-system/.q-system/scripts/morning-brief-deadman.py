#!/usr/bin/env python3
"""If the morning brief did not land, this says so. It is a DIFFERENT job.

## Why it cannot live inside morning-brief.py

The thing being watched is a job that did not run. A check inside the brief is
silent in exactly that case, so the watcher has to be a different process on a
different trigger. The whole defect being repaired here is a pipeline that died
on 2026-04-04 with nothing watching it; rebuilding the pipeline without a
deadman just resets the 148-day clock.

## Why StartInterval and not StartCalendarInterval

`com.kipi.morning-brief` is a StartCalendarInterval job. A watcher on the same
trigger class shares the suspect's failure mode -- a calendar job is SKIPPED
outright when the Mac is off at fire time and launchd does not catch up on wake,
so a powered-off morning would take the alarm down with the job. Same lesson
`com.cole.daily-social-deadman` records one job over, after the job it watches
went silent for sixteen days.

So this runs every 30 minutes and is silent until the deadline has passed. A
healthy day fires it ~48 times and says nothing.

## What it checks, and what it deliberately does not

It checks the RECEIPT: `~/.config/kipi/morning-brief-last.json`, written by the
brief only after Slack has answered. Not a log mtime, not a process listing --
those are liveness proxies, and a proxy is how you get a green watchdog over a
dead capability. The receipt records what Slack SAID, so "the job ran and
delivered nothing" alarms exactly like "the job never ran", which is correct:
both mean the founder has no brief.

It does NOT check whether the brief was any good. A brief with four COULD NOT
READ sections still delivered, and the founder can see that himself. This alarm
is for the case where he sees nothing at all.

## KNOWN LIMIT: this is off the JOB, not off the MACHINE

The lesson `a-freshness-deadman-must-live-off-the-machine-it-watches` is stricter
than what this satisfies. Both jobs run on the same Mac, so a machine that is
off, asleep or wedged silences the brief AND its alarm together.

The gap is narrower than it sounds, and the narrowing is why StartInterval was
chosen over StartCalendarInterval. A StartCalendarInterval job that misses its
fire time is skipped outright; launchd does not catch up on wake. A StartInterval
job with RunAtLoad DOES run on the next wake. So a Mac that was off at the brief's
fire time and opens hours later gets the alarm within thirty minutes of waking,
not never.

What remains uncovered is precisely: the machine stays off past the moment the
founder wanted to know. He is also not at his desk in that window, which is why
this is recorded as a bounded limit rather than treated as the same defect.

The real fix is an alarm keyed on the OUTPUT rather than the receipt -- something
off this machine asking Slack "did a message from colenotify with 'Morning brief'
land today?" That needs no local state, so unlike the brief itself it is not
blocked by the cloud sandbox's lack of access to ~/.config/kipi. It is captured,
not built here, because it is a different job with its own delivery proof.

## Who watches this watcher

`launchd-health-check.py` (com.kipi.launchd-health) auto-discovers every
`com.kipi.*` plist and reports a label that is failing or installed-but-unloaded.
It covers both this job and the one it watches. That is the honest boundary: it
catches a dead or crashing deadman, and it cannot catch a deadman that runs
happily against a stale threshold.

    python3 morning-brief-deadman.py            # check; alarm if overdue
    python3 morning-brief-deadman.py --dry-run  # print the verdict, send nothing
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
RECEIPT_PATH = STATE_DIR / "morning-brief-last.json"
ALARM_STATE = STATE_DIR / "morning-brief-deadman-state.json"

# The deadline is 09:00, founder-directed. This file deliberately does NOT name the
# hour the brief fires: it was a third copy of that number and it went stale the day
# the schedule moved to 07:40, so the alarm told the founder "the 07:00 job did not
# run" about a job that runs at 07:40 (Codex round 9). The plist is the record.
DEADLINE_HOUR = int(os.environ.get("KIPI_BRIEF_DEADLINE_HOUR", "9"))


def check(now: dt.datetime, receipt_path=None):
    """(ok, reason). `ok` means today's brief was delivered.

    A corrupt or absent receipt is NOT ok. Treating an unreadable receipt as
    healthy would make the alarm quietest exactly when the system is most broken.
    """
    path = Path(receipt_path) if receipt_path else RECEIPT_PATH
    today = now.strftime("%Y-%m-%d")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False, f"no morning-brief receipt at all ({path})"
    except (ValueError, OSError) as exc:
        return False, f"morning-brief receipt unreadable ({path}): {exc}"
    if not isinstance(data, dict):
        return False, f"morning-brief receipt is not an object ({path})"
    stamped = data.get("date")
    if stamped != today:
        return False, (f"last morning brief is stamped {stamped}, not {today} "
                       f"-- this morning's job did not run")
    if not data.get("delivered"):
        return False, (f"the {today} brief was built but NOT delivered: "
                       f"{data.get('reason') or 'no reason recorded'}")
    return True, None


def _before_deadline(now: dt.datetime) -> bool:
    return now.hour < DEADLINE_HOUR


def _already_alarmed(now: dt.datetime, state_path=None) -> bool:
    """One alarm per day. 48 firings a day would train the founder to mute the
    channel, and a muted alarm is the same as no alarm."""
    path = Path(state_path) if state_path else ALARM_STATE
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return False
    # A recorded-but-undelivered alarm does not count (PR #294 review, major):
    # it used to, so one refused Slack send at 09:00 silenced every later
    # retry that day. The record keeps `delivered` for exactly this reason.
    return state.get("date") == now.strftime("%Y-%m-%d") and bool(state.get("delivered"))


def _record_alarm(now: dt.datetime, result: dict, state_path=None) -> None:
    path = Path(state_path) if state_path else ALARM_STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"date": now.strftime("%Y-%m-%d"),
                               "delivered": bool(result.get("delivered")),
                               "at": now.isoformat(timespec="seconds")}), encoding="utf-8")
    tmp.replace(path)


def _sender():
    spec = importlib.util.spec_from_file_location("slack_founder", HERE / "slack_founder.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    now = dt.datetime.now().astimezone()
    ok, reason = check(now)
    if ok:
        print(f"[deadman] {now:%Y-%m-%d %H:%M} brief delivered; silent")
        return 0
    if _before_deadline(now):
        print(f"[deadman] {now:%H:%M} before the {DEADLINE_HOUR:02d}:00 deadline; "
              f"not overdue yet ({reason})")
        return 0
    message = (f":rotating_light: No morning brief today. {reason}\n"
               f"Checked {now:%Y-%m-%d %H:%M %Z} by com.kipi.morning-brief-deadman.")
    if args.dry_run:
        print(f"[deadman][dry-run] would send:\n{message}")
        return 1
    if _already_alarmed(now):
        print(f"[deadman] already alarmed today; staying quiet ({reason})")
        return 1
    result = _sender().deliver(message)
    print(f"[deadman] OVERDUE: {reason}")
    print(f"[deadman][send] {json.dumps(result)}")
    _record_alarm(now, result)
    # Non-zero either way: the watched job is overdue. launchd-health-check sees
    # this exit and files its own issue, so a deadman that cannot reach Slack is
    # still not a silent one.
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
