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
pause), 4 stop (no reading). Prints one line either way, and appends it to the gate log.

UNDER A TEST THE LIVE PATH IS UNREACHABLE. "Am I under a test" has one answer in this
repo, fleet_door.in_test (KIPI_TEST=1, pytest running, or a temp-dir `claude`), and this
gate imports it. Under a test the endpoint, the token and the cache come ONLY from the
seams KIPI_PLAN_USAGE_URL / _TOKEN / _STATE (and the log from _LOG); without URL and
TOKEN the gate says "run" and reads nothing. Outside a test the seams are ignored, so no
fleet run can point the gauge at a stand-in. Scar: PR #885 rounds 2 and 3 answered the
question three ad-hoc ways (seams, per-test env, a temp-binary check); each covered the
suites in front of it, and the dispatcher suite still read the founder's Keychain and
overwrote ~/.local/state/kipi/plan-usage.json
(rca-pr885-plan-gate-test-isolation-2026-11-26).
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I drops it
from fleet_door import in_test  # noqa: E402  the one under-test rule (see docstring)

RULE = "RULE-2026-11-26-PLAN45"
STOP_PCT = 45.0  # the founder's line; no env override, so no run can raise it for itself
LIVE_URL = "https://api.anthropic.com/api/oauth/usage"
LIVE_STATE = os.path.expanduser("~/.local/state/kipi/plan-usage.json")
LIVE_LOG = os.path.expanduser("~/.local/state/kipi/plan-usage-gate.log")
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


def config(binary, env=None):
    """Where this call reads from: the live account, or a test's seams, never a mix."""
    env = os.environ if env is None else env
    if not in_test([binary] if binary else [], env):
        return {"test": False, "url": LIVE_URL, "token": None,
                "state": LIVE_STATE, "log": LIVE_LOG}
    return {"test": True, "url": env.get("KIPI_PLAN_USAGE_URL"),
            "token": env.get("KIPI_PLAN_USAGE_TOKEN"),
            "state": env.get("KIPI_PLAN_USAGE_STATE"), "log": env.get("KIPI_PLAN_USAGE_LOG")}


def token(cfg):
    if cfg["test"]:
        return cfg["token"]  # a test never reaches the Keychain
    svc = login()
    acct = os.environ.get("USER") or os.path.basename(os.path.expanduser("~"))
    raw = subprocess.run(["security", "find-generic-password", "-s", svc, "-a", acct, "-w"],
                         capture_output=True, text=True, timeout=10).stdout.strip()
    oauth = json.loads(raw).get("claudeAiOauth") or {}
    if not oauth.get("accessToken"):
        raise RuntimeError("no plan login token in Keychain item '%s'" % svc)
    return oauth["accessToken"]


def fetch(cfg):
    req = urllib.request.Request(cfg["url"], headers={"Authorization": "Bearer " + token(cfg),
                                                      "anthropic-beta": "oauth-2025-04-20"})
    body = json.loads(urllib.request.urlopen(req, timeout=15).read())
    week = body.get("seven_day") or {}
    pct = week.get("utilization")
    if not isinstance(pct, (int, float)):
        raise RuntimeError("usage reply has no seven_day.utilization")
    return {"pct": float(pct), "resets_at": week.get("resets_at"), "at": time.time(), "login": login()}


def cached(cfg):
    if not cfg["state"]:
        return None
    try:
        with open(cfg["state"]) as fh:
            row = json.load(fh)
        if (row.get("login") == login() and 0 <= time.time() - float(row["at"]) < CACHE_S
                and isinstance(row.get("pct"), (int, float))):
            return row
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def save(cfg, row):
    if not cfg["state"]:
        return
    try:
        os.makedirs(os.path.dirname(cfg["state"]), exist_ok=True)
        tmp = cfg["state"] + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(row, fh)
        os.replace(tmp, cfg["state"])
    except OSError:
        pass  # a lost cache costs one extra HTTP call, never a wrong verdict


def log(cfg, rc, line):
    """The gate's one log writer. fleet-claude.sh stays silent on a run, so the detail of
    every verdict lands here; under a test only a seam path is ever written."""
    if not cfg["log"]:
        return
    try:
        os.makedirs(os.path.dirname(cfg["log"]), exist_ok=True)
        with open(cfg["log"], "a") as fh:
            fh.write("%s rc=%d %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), rc, line))
    except OSError:
        pass


def verdict(cfg):
    if cfg["test"] and not (cfg["url"] and cfg["token"]):
        return 0, "plan-usage: run, under a test with no usage seam; the live account is never read"
    try:
        row = cached(cfg) or fetch(cfg)
    except (OSError, ValueError, RuntimeError, urllib.error.URLError, subprocess.SubprocessError) as e:
        return 4, "plan-usage: STOP, weekly usage unreadable (%s); fleet does not run (%s)" % (e, RULE)
    save(cfg, row)
    if row["pct"] >= STOP_PCT:
        return 3, ("plan-usage: STOP, weekly %.1f%% >= %.0f%% stop line, resets %s (%s)"
                   % (row["pct"], STOP_PCT, row.get("resets_at"), RULE))
    return 0, "plan-usage: run, weekly %.1f%% < %.0f%% stop line" % (row["pct"], STOP_PCT)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    binary = argv[argv.index("--binary") + 1] if "--binary" in argv[:-1] else ""
    cfg = config(binary)
    rc, line = verdict(cfg)
    log(cfg, rc, line)
    print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main())
