#!/usr/bin/env python3
"""Probes every declared research profile and tells the founder ONCE when one dies.

This is the piece that makes the browsing capability "persistent" rather than
"a browser you have to babysit". `browser_session.py` can open a page; this job
is what notices, without anyone watching, that a session stopped being a
session.

## The alerting rule, founder-directed 2026-08-30

Restated by him verbatim: "Every thirty minutes is fine, but it has to only
give me one alert per instance, not continuously alerting forever if an
instance is down."

Two separate requirements live in that sentence and only one of them is
obvious:

  ONE PER DEATH    a profile down for three days produces one message on day
                   one and nothing after, until it recovers.
  PER INSTANCE     the suppression is keyed to the PROFILE. If a second profile
                   dies while the first is still down and still silent, the
                   second death is still delivered.

A module holding a single global "already alerted" flag satisfies the first and
silently fails the second, and it looks identical from the outside until the
day it matters. So the alerted state is stored per profile in the receipt, and
`test_c6_arm4_*` is the test that can tell the two designs apart.

## Why the state lives in the receipt and not in memory

The transition is derived from durable state, so a launchd restart, a reboot or
a crash cannot resurrect an alert the founder has already had. A process-local
flag resets to "never alerted" every time launchd reloads the job, which on a
30-minute StartInterval is a very effective way to send the same alarm forever.

## Three states, not two

`alive` / `dead` / `unknown`. `unknown` is a probe that could not look at all
(launch failure, navigation timeout). It NEVER alerts and it NEVER clears the
alerted state, it carries it forward. Folding `unknown` into `dead` would page
the founder about a session that is fine because his wifi dropped; folding it
into `alive` would clear the suppression and re-alert the next probe, turning
one outage into a message every hour.

## A dead session is reported, never repaired

Nothing here re-authenticates. Re-authenticating a profile the far side has
already flagged is the documented 2026-07-20 failure, and it converts a
recoverable session into a burned identity. Repair is a human opening a window
and typing a password; the alert says so and stops there. The check that holds
this asserts this file never even names the manual-login entry point.

## Why this alert goes to the founder and not to Sana's Linear queue

`.claude/rules/founder-notifications.md` routes engineering signals to
`slack-notify.sh`, which files a ticket for Sana. This is one of the few
genuine exceptions: a dead browser session can only be repaired by a human at
a keyboard with a password, so it goes to him via `slack_founder.deliver()`.
Filing it as a ticket would put a task in the queue of the one person who
cannot do it.

    browser_session_health.py            # probe, alert on transition, write receipt
    browser_session_health.py --dry-run  # probe and print; send nothing
    browser_session_health.py --status   # print the last receipt, probe nothing
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
PROFILES_PATH = HERE / "browser_profiles.json"

REQUIRED_KEYS = ("name", "dir", "identity", "purpose", "kill_switch")


class ProfileConfigError(Exception):
    """A declared profile that cannot be probed. Refused at load, not at 3am."""


def load_profiles(path=None) -> list:
    """Every profile, validated. A profile with no liveness probe is REFUSED.

    Declaring the probe is the whole reason continuity is checkable. A profile
    without one is a browser nobody can tell is dead, which is the exact defect
    this service exists to remove, so it is a load error rather than a profile
    that gets quietly skipped at runtime.
    """
    path = Path(path) if path else PROFILES_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileConfigError(f"no profile declaration at {path}") from exc
    except ValueError as exc:
        raise ProfileConfigError(f"{path} is not valid JSON: {exc}") from exc

    out = []
    for raw in data.get("profiles", []):
        missing = [k for k in REQUIRED_KEYS if not raw.get(k)]
        if missing:
            raise ProfileConfigError(
                f"profile {raw.get('name') or raw} is missing {missing}")
        probe_spec = raw.get("liveness_probe") or {}
        if not probe_spec.get("url") or not probe_spec.get("logged_in_marker"):
            raise ProfileConfigError(
                f"profile {raw['name']!r} declares no usable liveness_probe "
                "(needs url + logged_in_marker). A profile whose liveness "
                "cannot be checked is not a persistent session, it is a guess.")
        entry = dict(raw)
        entry["dir"] = os.path.expanduser(entry["dir"])
        entry["kill_switch"] = os.path.expanduser(entry["kill_switch"])
        out.append(entry)
    return out


def classify(result) -> str:
    """alive / dead / unknown from one probe result."""
    if not result.get("reachable"):
        return "unknown"
    return "alive" if result.get("logged_in") else "dead"


def read_receipt(path=None) -> dict:
    path = Path(path) if path else RECEIPT_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_receipt(payload: dict, path=None) -> Path:
    """Single writer. Atomic, because the deadman reads this while it writes."""
    path = Path(path) if path else RECEIPT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def _disabled(profile) -> bool:
    """The declared kill switch. A profile can be taken out of the rotation by
    touching one file, with no edit to committed config and no deploy."""
    return Path(profile["kill_switch"]).exists()


def _module(filename: str):
    """Load a sibling script by path.

    THE sys.modules REGISTRATION IS NOT OPTIONAL. Measured 2026-08-30: without
    it, Python 3.14's @dataclass decorator raises AttributeError while building
    ProbeResult, because dataclasses resolves the owning module out of
    sys.modules to check its annotations. The whole suite was green at the time
    -- every test injects its own prober, so nothing exercised this loader, and
    the live job died on import on every single run.
    """
    import sys
    name = filename[:-3]
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _live_prober(profile) -> dict:
    """The only path from here to a browser."""
    session = _module("browser_session.py")
    spec = profile["liveness_probe"]
    return session.probe(profile["name"], profile["dir"], spec["url"],
                         spec["logged_in_marker"]).as_dict()


def _founder_sender(message: str) -> dict:
    return _module("slack_founder.py").deliver(message)


def _message(profile, entry, state: str) -> str:
    """One line about ONE profile. Never a digest.

    It names only this profile on purpose: a combined message about several
    profiles makes "one alert per instance" undeliverable, and re-states an
    outage the founder was already told about every time a new one starts.
    """
    name = profile["name"]
    if state == "alive":
        return (f":white_check_mark: Browser session back: {name} "
                f"({profile['identity']}). Verified {entry.get('at')}.")
    why = entry.get("reason") or entry.get("error") or "no reason recorded"
    return (f":rotating_light: Browser session DEAD: {name} "
            f"({profile['identity']}) -- {why}\n"
            f"Purpose: {profile['purpose']}\n"
            f"Repair is a human step, nothing here will retry the sign-in: "
            f"python3 {HERE / 'browser_session.py'} login {name}\n"
            f"You get this once. Nothing further until it recovers.")


def run_once(profiles=None, prober=None, sender=None, receipt_path=None,
             now=None) -> dict:
    """Probe every profile, alert on per-profile transitions, write the receipt.

    Everything the transition arithmetic needs is injected, so the whole rule is
    testable without opening a browser or sending a message. The live wiring is
    the two defaults, and nothing else in this function knows the difference.
    """
    now = now or dt.datetime.now().astimezone()
    profiles = load_profiles() if profiles is None else profiles
    prober = prober or _live_prober
    sender = sender or _founder_sender
    prior_profiles = read_receipt(receipt_path).get("profiles", {})

    stamp = now.isoformat(timespec="seconds")
    out = {"at": stamp, "profiles": {}, "sends": []}

    for profile in profiles:
        name = profile["name"]
        prior = prior_profiles.get(name, {})
        # The alerted state is what the FOUNDER was last told, which is not the
        # same thing as the last observed state: two dead probes in a row have
        # the same state and only one of them is news.
        alerted = prior.get("alerted_state")

        if _disabled(profile):
            out["profiles"][name] = {
                "profile": name, "state": "disabled",
                "previous_state": prior.get("state"),
                "alerted_state": alerted,
                "last_verified": prior.get("last_verified"),
                "reason": f"kill switch present: {profile['kill_switch']}",
                "at": stamp,
            }
            continue

        result = dict(prober(profile))
        state = classify(result)
        entry = dict(result)
        entry["state"] = state
        entry["previous_state"] = prior.get("state")
        entry["last_verified"] = (
            stamp if state == "alive" else prior.get("last_verified"))
        entry["last_alert_at"] = prior.get("last_alert_at")

        if state in ("alive", "dead") and state != alerted:
            # A first-ever observation of a HEALTHY profile is not news. It
            # still records the alerted state, so the first death after it is.
            if not (state == "alive" and alerted is None):
                message = _message(profile, entry, state)
                verdict = sender(message)
                out["sends"].append({"profile": name, "state": state,
                                     "message": message, "result": verdict})
                entry["last_alert_at"] = stamp
            alerted = state

        entry["alerted_state"] = alerted
        out["profiles"][name] = entry

    write_receipt(out, receipt_path)
    return out


def main(argv=None, runner=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="probe and print; send nothing, write no receipt")
    ap.add_argument("--status", action="store_true",
                    help="print the last receipt and exit; probe nothing")
    args = ap.parse_args(argv)

    if args.status:
        print(json.dumps(read_receipt(), indent=2))
        return 0

    if args.dry_run:
        import tempfile
        captured = []
        # The receipt goes to a scratch path, never the live one: a dry run that
        # overwrote the real receipt would reset the per-profile alerted_state
        # and make the next real run re-announce an outage he already has.
        scratch = Path(tempfile.gettempdir()) / "browser-session-health.dryrun.json"
        result = run_once(sender=captured.append, receipt_path=scratch)
        print(json.dumps(result, indent=2))
        for message in captured:
            print(f"[dry-run] would send:\n{message}")
        return 0

    result = (runner or run_once)()
    for send in result["sends"]:
        print(f"[send] {send['profile']} -> {json.dumps(send['result'])}")
    dead = [n for n, e in result["profiles"].items() if e["state"] == "dead"]
    print(f"[health] {result['at']} "
          f"{len(result['profiles'])} profiles, {len(dead)} dead, "
          f"{len(result['sends'])} sent")
    # EXIT 0 FOR A COMPLETED CYCLE, EVEN WITH A DEAD PROFILE.
    #
    # Measured under launchd 2026-08-30: the first real run exited 1 because one
    # profile was signed out, and launchd records that as the job's status.
    # launchd-health-check.py auto-discovers every com.kipi.* label and reports a
    # failing one, so a profile that stays signed out for a week would have made
    # this job look broken every 30 minutes forever -- reintroducing the exact
    # "continuously alerting" the per-profile suppression exists to prevent, just
    # through a second channel the founder never agreed to.
    #
    # A dead session is a REPORTED state, not a job failure (constraint 4). The
    # report is the alert and the receipt. The exit code answers a different
    # question: did this checker run. Non-zero is reserved for the checker
    # itself failing, which argparse and an unhandled exception already cover.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
