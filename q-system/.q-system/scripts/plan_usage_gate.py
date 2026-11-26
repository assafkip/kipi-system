#!/usr/bin/env python3
"""Stop the Sana ticket fleet at 45% of the Claude plan's weekly usage.

Founder, 2026-11-26, verbatim: "Move the fleet work to the claude account - Ensure it
stops when usage gets to 45% of the weekly usage". That moves fleet runs off the API
key and onto the founder's main login (~/.claude), and sets this stop line. The ruling
replaces RULE-2026-11-13-A ("we never have a cap") for plan usage only.

WHAT IT READS. The plan's own weekly number, the one the limit is enforced on: the
`seven_day.utilization` field of the OAuth usage endpoint, called with the login's own
token from the Keychain. Measured 2026-11-26: 17.0 for the main login, the same number
/usage shows. A ledger estimate cannot be the gate: usage-real.py's header records a
transcript estimate of 16.5% while /usage said 42%.

The login is the one a fleet `claude` run uses: CLAUDE_CONFIG_DIR when set, else
~/.claude. Claude Code keys its Keychain item by that dir: "Claude Code-credentials"
for ~/.claude, "Claude Code-credentials-<sha256(dir)[:8]>" for any other.

FAILS CLOSED. A reading that cannot be had (no token, an expired token, HTTP error,
a malformed body) is a stop, exit 4, never a run. The founder asked for a guaranteed
stop; a brake that opens when its gauge breaks is not one. The dispatcher pages Sana
once on 4 so the broken gauge gets fixed.

Exit 0 run, 3 stop (at or past the line; the same code usage_breaker.py uses for a
pause), 4 stop (no reading). Prints one line either way.
Test seams: KIPI_PLAN_USAGE_URL, KIPI_PLAN_USAGE_TOKEN, KIPI_PLAN_USAGE_STATE.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

RULE = "RULE-2026-11-26-PLAN45"
STOP_PCT = 45.0  # the founder's line; no env override, so no run can raise it for itself
URL = os.environ.get("KIPI_PLAN_USAGE_URL", "https://api.anthropic.com/api/oauth/usage")
STATE = os.environ.get("KIPI_PLAN_USAGE_STATE",
                       os.path.expanduser("~/.local/state/kipi/plan-usage.json"))
# A fleet call is minutes long; 2 minutes of staleness can overshoot the line by at most
# what the fleet spends in 2 minutes, and saves one HTTP call per `claude` launch.
CACHE_S = 120  # no env override: a widened window would let a day-old reading pass (PR #885 round 1)


def keychain_service(config_dir):
    home_default = os.path.join(os.path.expanduser("~"), ".claude")
    if not config_dir or os.path.normpath(config_dir) == home_default:
        return "Claude Code-credentials"
    return "Claude Code-credentials-" + hashlib.sha256(config_dir.encode()).hexdigest()[:8]


def login():
    """Which login this reading belongs to; a cached row from another login never counts."""
    return keychain_service(os.environ.get("CLAUDE_CONFIG_DIR", ""))


def token():
    if os.environ.get("KIPI_PLAN_USAGE_TOKEN"):
        return os.environ["KIPI_PLAN_USAGE_TOKEN"]
    svc = login()
    acct = os.environ.get("USER") or os.path.basename(os.path.expanduser("~"))
    raw = subprocess.run(["security", "find-generic-password", "-s", svc, "-a", acct, "-w"],
                         capture_output=True, text=True, timeout=10).stdout.strip()
    oauth = json.loads(raw).get("claudeAiOauth") or {}
    if not oauth.get("accessToken"):
        raise RuntimeError("no plan login token in Keychain item '%s'" % svc)
    return oauth["accessToken"]


def fetch():
    req = urllib.request.Request(URL, headers={"Authorization": "Bearer " + token(),
                                               "anthropic-beta": "oauth-2025-04-20"})
    body = json.loads(urllib.request.urlopen(req, timeout=15).read())
    week = body.get("seven_day") or {}
    pct = week.get("utilization")
    if not isinstance(pct, (int, float)):
        raise RuntimeError("usage reply has no seven_day.utilization")
    return {"pct": float(pct), "resets_at": week.get("resets_at"), "at": time.time(), "login": login()}


def cached():
    try:
        with open(STATE) as fh:
            row = json.load(fh)
        if (row.get("login") == login() and 0 <= time.time() - float(row["at"]) < CACHE_S
                and isinstance(row.get("pct"), (int, float))):
            return row
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def save(row):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(row, fh)
        os.replace(tmp, STATE)
    except OSError:
        pass  # a lost cache costs one extra HTTP call, never a wrong verdict


def main():
    try:
        row = cached() or fetch()
    except (OSError, ValueError, RuntimeError, urllib.error.URLError, subprocess.SubprocessError) as e:
        print("plan-usage: STOP, weekly usage unreadable (%s); fleet does not run (%s)" % (e, RULE))
        return 4
    save(row)
    if row["pct"] >= STOP_PCT:
        print("plan-usage: STOP, weekly %.1f%% >= %.0f%% stop line, resets %s (%s)"
              % (row["pct"], STOP_PCT, row.get("resets_at"), RULE))
        return 3
    print("plan-usage: run, weekly %.1f%% < %.0f%% stop line" % (row["pct"], STOP_PCT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
