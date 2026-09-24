#!/usr/bin/env python3
"""Probes every declared SURFACE of every research profile, and tells the right
person once when one changes state.

## What the first live morning taught, 2026-08-31

The v1 of this file shipped on 2026-08-30 and its first real run in production
printed:

    1 profiles, 0 dead, 0 sent      rc 0

Nothing was wrong with that line except that it was produced by a run which had
learned NOTHING. The founder's own sign-in window was open, a Chrome persistent
context is single-holder, so Playwright could not launch at all. The probe came
back `unknown`, and `unknown` rendered exactly like healthy.

That is the defect this file is now built around: **a state the instrument could
not determine must never render as a clean bill of health.** Every count on the
summary line, every state name, and the exit code follow from that.

## Six states, because four situations were being collapsed into two

    alive       loaded, and the signed-in marker was there
    dead        loaded, marker absent, and this marker HAS been seen true before
    unverified  loaded, marker absent, and the marker has NEVER been seen true.
                Indistinguishable from a wrong guess, so it must not alert.
    held        another Chrome holds the profile directory. Benign, expected,
                transient. Not healthy, not a fault.
    unknown     the probe could not look at all. Escalates if it persists.
    disabled    kill switch present.

`held` earns its own state rather than folding into `unknown` because the two
have opposite dispositions. A held profile is the NORMAL consequence of the
founder repairing a session by hand: the window he signs in with is the very
thing that blocks the next probe. Alerting on it would page him about the fix
he is performing. Escalating it would file a ticket about a healthy system.

## Alerting, founder-directed 2026-08-30 and unchanged

"Only give me one alert per instance, not continuously alerting forever if an
instance is down." The suppression is keyed per (profile, surface) and lives in
the receipt, so a launchd restart cannot resurrect an alert he has already had.

Two audiences, and the split is the point:

  FOUNDER, via slack_founder.deliver   a session died. Only a human with a
                                       password can repair it.
  SANA'S QUEUE, via slack-notify.sh    the probe itself is broken (N consecutive
                                       unknowns). He cannot fix a browser that
                                       will not launch, and paging him about it
                                       is how the channel gets muted.

## Why `unverified` exists at all

Declaring a surface means naming a string that appears only when signed in. Until
that string has been observed true ONCE, a wrong guess and a genuinely signed-out
session are the same observation. Without this state, adding a surface means
either a false death on day one or a silent blind spot. With it, an unproven
marker is visibly unproven and stays quiet.

The dangerous direction is the opposite one: a marker that is present while
signed OUT reports `alive` forever, and alive is silent. So a declared marker is
required to have been measured ABSENT on a signed-out load before it ships, and
that measurement belongs in the config's own notes.

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
import subprocess
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("KIPI_STATE_DIR", os.path.expanduser("~/.config/kipi")))
RECEIPT_PATH = STATE_DIR / "browser-session-health.json"
PROFILES_PATH = HERE / "browser_profiles.json"

REQUIRED_KEYS = ("name", "dir", "identity", "purpose", "kill_switch")

# Four consecutive unknowns is two hours of a probe that cannot look. One is a
# blip; two hours is a broken checker and somebody has to be told.
UNKNOWN_ESCALATION_AFTER = int(os.environ.get("KIPI_BROWSER_UNKNOWN_ESCALATION", "4"))

# DECISION 2026-08-31, recorded here because an unrecorded exception to canon is
# how canon dies.
#
# reddit_driver.py carries canon 2026-07-17: "Do NOT create a Playwright profile
# login for reddit: it is WAF-blocked and forbidden." browser_profiles.json's own
# notes said declaring-rather-than-scanning existed to keep Reddit out. On
# 2026-08-31 Reddit cookies were measured INSIDE the one declared profile, so
# the comment had stopped being true and nothing noticed.
#
# The canon stands. It was written against a headless driver and this capability
# is headful and read-only, which is a real difference, but it is an UNMEASURED
# one: nobody has established that headful changes the WAF outcome, and the cost
# of being wrong is the founder's Reddit account, which is not recoverable by
# retrying. An unmeasured difference is not a licence.
#
# So the refusal moves out of a JSON comment and into a load error. Reversing it
# is then a deliberate edit here with a measurement attached, in the open,
# instead of a surface quietly appearing in a config.
FORBIDDEN_PROBE_HOSTS = ("reddit.com",)

# Ad, analytics and CDN hosts. They are cookie noise, not identities, and left in
# they would drown the one signal undeclared_hosts exists to produce.
AD_HOSTS = {
    "doubleclick.net", "rubiconproject.com", "adnxs.com", "demdex.net",
    "dpm.demdex.net", "rlcdn.com", "33across.com", "3lift.com", "casalemedia.com",
    "pubmatic.com", "criteo.com", "protechts.net", "adsrvr.org", "bidswitch.net",
    "openx.net", "sharethrough.com", "taboola.com", "outbrain.com", "crwdcntrl.net",
    "scorecardresearch.com", "quantserve.com", "everesttech.net", "yahoo.com",
    "agkn.com", "tapad.com", "id5-sync.com", "smartadserver.com", "adform.net",
    # bing.com is here as an AD host, not a search engine: the cookies measured
    # in the jar on 2026-08-31 came from ad-sync redirects, not a sign-in.
    "bing.com", "teads.tv",
}


class ProfileConfigError(Exception):
    """A declared profile that cannot be probed. Refused at load, not at 3am."""


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _is_forbidden(url: str) -> bool:
    host = _host(url)
    return any(host == bad or host.endswith("." + bad) for bad in FORBIDDEN_PROBE_HOSTS)


def load_profiles(path=None) -> list:
    """Every profile, validated. Refused loudly rather than skipped at runtime.

    A profile with no surface to probe is a browser nobody can tell is dead,
    which is the exact defect this service exists to remove.
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

        probes = raw.get("liveness_probes") or []
        if not probes:
            raise ProfileConfigError(
                f"profile {raw['name']!r} declares no liveness_probes. A profile "
                "whose liveness cannot be checked is not a persistent session, "
                "it is a guess.")
        for probe_spec in probes:
            if not probe_spec.get("name") or not probe_spec.get("url") \
                    or not probe_spec.get("logged_in_marker"):
                raise ProfileConfigError(
                    f"profile {raw['name']!r} has a surface missing "
                    "name/url/logged_in_marker")
            if _is_forbidden(probe_spec["url"]):
                raise ProfileConfigError(
                    f"profile {raw['name']!r} declares a probe against "
                    f"{_host(probe_spec['url'])}, which is forbidden. A "
                    "Playwright-driven Reddit session is WAF-blocked (canon "
                    "2026-07-17, reddit_driver.py). Headful may or may not change "
                    "that; nobody has measured it, and the cost of being wrong is "
                    "an account that cannot be un-banned. Reverse this in "
                    "FORBIDDEN_PROBE_HOSTS with a measurement attached.")

        if not isinstance(raw.get("expected_cookie_hosts"), list) \
                or not raw["expected_cookie_hosts"]:
            raise ProfileConfigError(
                f"profile {raw['name']!r} declares no expected_cookie_hosts. "
                "One jar held four identities on 2026-08-31 and nothing noticed, "
                "because no profile ever had to say which identity it was.")

        entry = dict(raw)
        entry["dir"] = os.path.expanduser(entry["dir"])
        entry["kill_switch"] = os.path.expanduser(entry["kill_switch"])
        out.append(entry)
    return out


def classify(result) -> str:
    """alive / dead / held / unknown from ONE probe result.

    Deliberately pure and history-free. The promotion of `dead` to `unverified`
    needs the marker's history and belongs in run_once, so that this function
    stays a straight reading of what the probe saw.
    """
    if result.get("held"):
        return "held"
    if not result.get("reachable"):
        return "unknown"
    return "alive" if result.get("logged_in") else "dead"


def cookie_hosts(profile) -> list:
    """Every host in the profile's cookie jar, or [] if it cannot be read.

    Read-only, and against a COPY: the live jar is an sqlite file Chrome may
    hold open, and this must never be the thing that corrupts a session it
    exists to protect.
    """
    src = Path(profile["dir"]) / "Default" / "Cookies"
    if not src.exists():
        return []
    import shutil
    import sqlite3
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "cookies.db"
    try:
        shutil.copy2(src, tmp)
        conn = sqlite3.connect(str(tmp))
        try:
            return [r[0] for r in conn.execute("select distinct host_key from cookies")]
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return []
    finally:
        try:
            tmp.unlink()
            tmp.parent.rmdir()
        except OSError:
            pass


def undeclared_hosts(profile, hosts=None) -> list:
    """Cookie hosts this profile never said it would hold.

    DECISION 2026-08-31: the profile is the IDENTITY boundary and the surface is
    the probe boundary. One jar holding LinkedIn, Reddit, Google and YouTube is
    the shared-computer shape the Grok Bot research rejected, arriving from the
    other direction, and the plan's isolation constraint never covered it: it
    separated research from his real Chrome, never research profiles from each
    other.

    Splitting the existing jar needs his sign-ins and is captured, not done here.
    What IS done here is making the drift observable, so the next identity to
    appear in a jar is on the receipt the day it arrives rather than found by
    hand a month later.
    """
    hosts = cookie_hosts(profile) if hosts is None else hosts
    expected = [h.lower().lstrip(".") for h in profile.get("expected_cookie_hosts", [])]
    out = []
    for raw in hosts:
        bare = raw.lower().lstrip(".")
        if any(bare == ad or bare.endswith("." + ad) for ad in AD_HOSTS):
            continue
        if any(bare == e or bare.endswith("." + e) or e.endswith("." + bare)
               for e in expected):
            continue
        out.append(raw)
    return sorted(out)


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
    return Path(profile["kill_switch"]).exists()


def _module(filename: str):
    """Load a sibling script by path.

    THE sys.modules REGISTRATION IS NOT OPTIONAL. Measured 2026-08-30: without
    it, Python 3.14's @dataclass raises AttributeError while building
    ProbeResult, because dataclasses resolves the owning module out of
    sys.modules. The suite was green at the time; every test injects its own
    prober, so nothing exercised this loader and the live job died on import on
    every run.
    """
    import sys
    name = filename[:-3]
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _live_prober(profile, surface) -> dict:
    """The only path from here to a browser."""
    session = _module("browser_session.py")
    return session.probe(profile["name"], profile["dir"], surface["url"],
                         surface["logged_in_marker"],
                         surface=surface["name"]).as_dict()


def _founder_sender(message: str) -> dict:
    return _module("slack_founder.py").deliver(message)


def _ops_sender(message: str) -> dict:
    """Sana's Linear triage, via the fleet alert path.

    `.claude/rules/founder-notifications.md`: slack-notify.sh files a ticket for
    Sana and pages nobody. A probe that cannot launch a browser is hers.
    """
    script = HERE / "slack-notify.sh"
    try:
        done = subprocess.run(["bash", str(script), message],
                              capture_output=True, text=True, timeout=60)
        return {"delivered": done.returncode == 0, "transport": "slack-notify.sh",
                "rc": done.returncode, "out": (done.stdout or "")[:200]}
    except Exception as exc:  # noqa: BLE001
        return {"delivered": False, "transport": "slack-notify.sh",
                "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}


def _message(profile, surface, entry, state: str) -> str:
    """One line about ONE surface of ONE profile. Never a digest."""
    label = f"{profile['name']}/{surface['name']}"
    if state == "alive":
        return (f":white_check_mark: Browser session back: {label} "
                f"({profile['identity']}). Verified {entry.get('at')}.")
    why = entry.get("reason") or entry.get("error") or "no reason recorded"
    return (f":rotating_light: Browser session DEAD: {label} "
            f"({profile['identity']}) at {surface['url']} -- {why}\n"
            f"Repair is a human step, nothing here will retry the sign-in: "
            f"python3 {HERE / 'browser_session.py'} login {profile['name']}\n"
            f"You get this once. Nothing further until it recovers.")


def _ops_message(profile, surface, entry, count: int) -> str:
    return (f"browser-session probe cannot look: {profile['name']}/{surface['name']} "
            f"returned unknown {count} times in a row "
            f"({entry.get('error') or 'no error recorded'}). "
            f"The session may be fine; the CHECKER is not. "
            f"Nothing is watching {surface['url']} until this is fixed.")


def _surface_pass(profile, surface, prior, prober, sender, ops_sender, stamp, out):
    """One surface, one probe, one transition decision. Returns the new entry."""
    result = dict(prober(profile, surface))
    state = classify(result)
    marker_seen = bool(prior.get("marker_ever_seen"))
    alerted = prior.get("alerted_state")
    unknown_run = int(prior.get("consecutive_unknown") or 0)
    escalated = bool(prior.get("unknown_escalated"))
    first_verified = prior.get("first_verified_at")

    if state == "alive":
        marker_seen = True
        unknown_run = 0
        escalated = False
        # 72 hours of continuity means 72 UNBROKEN hours, so the clock is
        # stamped by the first true probe and never restamped while it holds.
        first_verified = first_verified or stamp
    elif state == "dead":
        unknown_run = 0
        escalated = False
        first_verified = None
        if not marker_seen:
            # A marker never once observed true is indistinguishable from a
            # wrong guess. Report it, never page on it.
            state = "unverified"
    elif state == "unknown":
        unknown_run += 1
    # `held` deliberately changes nothing: not the counter, not the alerted
    # state, not the clock. The window that blocks the probe is usually the
    # founder repairing the very session this would otherwise re-alert about.

    entry = dict(result)
    entry.update({
        "surface": surface["name"], "url": surface["url"], "state": state,
        "previous_state": prior.get("state"), "marker_ever_seen": marker_seen,
        "consecutive_unknown": unknown_run,
        "first_verified_at": first_verified,
        "last_verified": stamp if state == "alive" else prior.get("last_verified"),
        "last_alert_at": prior.get("last_alert_at"),
    })

    if state in ("alive", "dead") and state != alerted:
        # A first-ever observation of a HEALTHY surface is not news. It still
        # records the alerted state, so the first death after it is.
        if not (state == "alive" and alerted is None):
            message = _message(profile, surface, entry, state)
            result = sender(message) or {}
            out["sends"].append({"profile": profile["name"], "surface": surface["name"],
                                 "state": state, "message": message, "result": result})
            entry["last_alert_at"] = stamp
            # Suppress ONLY after the alert landed (PR #294 review, major): a
            # refused send left alerted_state stamped, so a Slack or Linear
            # outage silenced the incident until the browser state changed.
            if result.get("delivered"):
                alerted = state
        else:
            alerted = state

    if state == "unknown" and unknown_run >= UNKNOWN_ESCALATION_AFTER and not escalated:
        message = _ops_message(profile, surface, entry, unknown_run)
        result = ops_sender(message) or {}
        out["ops_sends"].append({"profile": profile["name"], "surface": surface["name"],
                                 "message": message, "result": result})
        escalated = bool(result.get("delivered"))  # same rule: an undelivered escalation retries

    entry["alerted_state"] = alerted
    entry["unknown_escalated"] = escalated
    return entry


def run_once(profiles=None, prober=None, sender=None, ops_sender=None,
             receipt_path=None, now=None) -> dict:
    """Probe every surface, alert on per-surface transitions, write the receipt."""
    now = now or dt.datetime.now().astimezone()
    profiles = load_profiles() if profiles is None else profiles
    prober = prober or _live_prober
    sender = sender or _founder_sender
    ops_sender = ops_sender or _ops_sender
    prior_profiles = read_receipt(receipt_path).get("profiles", {})

    stamp = now.isoformat(timespec="seconds")
    out = {"at": stamp, "profiles": {}, "sends": [], "ops_sends": []}

    for profile in profiles:
        name = profile["name"]
        prior = prior_profiles.get(name, {})
        prior_surfaces = prior.get("surfaces", {})

        if _disabled(profile):
            out["profiles"][name] = {
                "identity": profile["identity"], "state": "disabled",
                "reason": f"kill switch present: {profile['kill_switch']}",
                "surfaces": prior_surfaces, "at": stamp}
            continue

        surfaces = {}
        for surface in profile["liveness_probes"]:
            surfaces[surface["name"]] = _surface_pass(
                profile, surface, prior_surfaces.get(surface["name"], {}),
                prober, sender, ops_sender, stamp, out)

        out["profiles"][name] = {
            "identity": profile["identity"],
            "surfaces": surfaces,
            # Declared-but-unwatched surfaces stay ON the receipt. The blind
            # spot that started all of this was invisible, not accepted.
            "unmonitored_surfaces": profile.get("unmonitored_surfaces", []),
            "undeclared_cookie_hosts": undeclared_hosts(profile),
            "at": stamp,
        }

    write_receipt(out, receipt_path)
    return out


def _tally(result) -> dict:
    counts = {}
    for prof in result["profiles"].values():
        if prof.get("state") == "disabled":
            counts["disabled"] = counts.get("disabled", 0) + 1
        for surface in prof.get("surfaces", {}).values():
            state = surface.get("state", "?")
            counts[state] = counts.get(state, 0) + 1
    return counts


def main(argv=None, runner=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="probe and print; send nothing, write no live receipt")
    ap.add_argument("--status", action="store_true",
                    help="print the last receipt and exit; probe nothing")
    args = ap.parse_args(argv)

    if args.status:
        print(json.dumps(read_receipt(), indent=2))
        return 0

    if args.dry_run:
        import tempfile
        captured = []
        # Scratch receipt: a dry run that overwrote the live one would reset the
        # per-surface alerted_state and re-announce an outage he already has.
        scratch = Path(tempfile.gettempdir()) / "browser-session-health.dryrun.json"
        result = run_once(sender=captured.append, ops_sender=captured.append,
                          receipt_path=scratch)
        print(json.dumps(result, indent=2))
        for message in captured:
            print(f"[dry-run] would send:\n{message}")
        return 0

    result = (runner or run_once)()
    for send in result.get("sends", []):
        print(f"[send] {send['profile']}/{send['surface']} -> {json.dumps(send['result'])}")
    for send in result.get("ops_sends", []):
        print(f"[ops] {send['profile']}/{send['surface']} -> {json.dumps(send['result'])}")

    # EVERY state on one line, and never a bare "0 dead".
    #
    # `1 profiles, 0 dead, 0 sent` rc 0 is what a run that could not open Chrome
    # printed in production on day one. A summary that reports only the failures
    # it managed to observe is indistinguishable from one that observed nothing,
    # and that is the whole class of defect this file now exists to prevent.
    counts = _tally(result)
    summary = ", ".join(f"{n} {state}" for state, n in sorted(counts.items())) or "no surfaces"
    print(f"[health] {result['at']} {len(result['profiles'])} profiles: {summary}, "
          f"{len(result.get('sends', []))} sent, "
          f"{len(result.get('ops_sends', []))} escalated")

    for name, prof in result["profiles"].items():
        undeclared = prof.get("undeclared_cookie_hosts") or []
        if undeclared:
            print(f"[identity] {name} holds cookies it never declared: "
                  f"{', '.join(undeclared[:8])}")
        for un in prof.get("unmonitored_surfaces", []):
            print(f"[blind] {name}/{un.get('host')}: {un.get('reason')}")

    # A dead session is a REPORTED state, not a job failure. launchd-health-check
    # reports a non-zero label as failing, so exiting 1 on a signed-out profile
    # would reintroduce "continuously alerting" through a second channel.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
