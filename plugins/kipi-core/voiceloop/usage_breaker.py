"""The brake on top of the Step 2 usage ledger (ASK-2010, Step 4).

`usage_ledger.py` is the meter. This is the thing that acts on it. A cap needs a
meter first, and a meter with nothing reading it is a receipt for a fire.

WHAT IT DECIDES
---------------
For one named bot, against the rolling 7-day window of the ledger:

  run    exit 0 -- its spend is inside its share of the fleet's week.
  pause  exit 3 -- it is over its share, or the fleet floor is down on it.

Those two codes are the contract the DoR pinned (`control.py check`: 0 run,
3 paused), so a caller is a two-line `if` and never a parser.

SHARES ARE FRACTIONS, NOT DOLLARS
---------------------------------
The fleet runs on one flat-price subscription, so there is no dollar budget to
divide. A bot's share is its fraction of what the WHOLE fleet spent in the
window, which needs no ceiling to be meaningful and moves with the fleet. The
default is an equal split with 20% reserved on top for bots the founder marks
priority (the DoR's default). When nothing is marked priority the reserve is
split equally too: a reserve with no claimant would leave every bot judged
against 0.8/N and push an ordinary three-bot fleet over its own line on day one,
and a gate that is red on its own population gets switched off.

THE FLEET FLOOR
---------------
A `limit_text` row anywhere in the window means the subscription itself said no.
That is not one bot's fault and it is not fixed by waiting for one bot to cross a
share line, so low-priority bots pause at once, share or no share. Who is
low-priority is the founder's call and lives in the config file, not here.

IT FAILS OPEN, LOUDLY
---------------------
A ledger that cannot be read exits 0 with one line on stderr. The DoR asks that
the brake "fail in a way that is visible", and the visible failure of a brake is
not a dark fleet: a bug in this file would stop every chief bot and the worker at
once, which is the outage the brake exists to prevent. So: fail open, say so on
stderr every time, and let the absence of rows be the thing someone sees.

Off switch: `KIPI_USAGE_BREAKER=0`.
State:      `~/.config/kipi/usage-breaker.json` (`KIPI_USAGE_BREAKER_STATE`).
Config:     `~/.config/kipi/usage-shares.json`  (`KIPI_USAGE_SHARES`).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
from dataclasses import dataclass

try:  # imported as part of the package
    from . import usage_ledger
except ImportError:  # run as a script: `python3 usage_breaker.py check --bot x`
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from voiceloop import usage_ledger  # type: ignore[no-redef]

WINDOW_DAYS = 7
#: The DoR's founder default: 20% held back for priority bots, on top of an equal split.
RESERVE = 0.20
#: One trial run is granted this long after a pause, so a bot that stopped
#: spending is not held for a week by a share it no longer exceeds.
TRIAL_AFTER_SECONDS = 24 * 3600
STATE_ENV = "KIPI_USAGE_BREAKER_STATE"
CONFIG_ENV = "KIPI_USAGE_SHARES"
OFF_ENV = "KIPI_USAGE_BREAKER"
DEFAULT_STATE = os.path.join(os.path.expanduser("~"), ".config", "kipi", "usage-breaker.json")
DEFAULT_CONFIG = os.path.join(os.path.expanduser("~"), ".config", "kipi", "usage-shares.json")
#: Same sink and same seam `linear-worker.sh` already uses. Per
#: founder-notifications.md this files a Linear ticket for Sana; it pages nobody.
NOTIFY_ENV = "KIPI_NOTIFY"
_REPO_NOTIFY = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "..", "..", "q-system", ".q-system", "scripts", "slack-notify.sh")

DEFAULT_CFG = {"window_days": WINDOW_DAYS, "reserve": RESERVE, "priority": [], "low_priority": []}


@dataclass
class Decision:
    action: str          # "run" or "pause"
    reason: str          # "under-share" | "over-share" | "fleet-floor"
    share_used: float
    share_allowed: float
    bot: str
    end: str


def _date(value) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def window(rows, end, days: int = WINDOW_DAYS) -> list[dict]:
    """The rows whose `ts` falls in the `days`-long window ending on `end` (inclusive)."""
    last = _date(end)
    if last is None:
        return []
    first = last - _dt.timedelta(days=days - 1)
    return [r for r in rows if (d := _date(r.get("ts"))) is not None and first <= d <= last]


def spend_by_bot(rows) -> dict:
    """Dollars per bot. A row with no cost counts as 0: it happened, it cost nothing knowable.

    Failure rows are INCLUDED. A refusal still burns the request, and a breaker
    that only counted successes would let a bot in a retry storm spend freely.
    """
    out: dict = {}
    for r in rows:
        bot = r.get("bot")
        if not bot:
            continue
        cost = r.get("total_cost_usd")
        out[bot] = out.get(bot, 0.0) + (cost if isinstance(cost, (int, float)) else 0.0)
    return out


def shares(bots, priority=(), reserve: float = RESERVE) -> dict:
    """Each bot's allowed fraction of the window. Always sums to 1.0."""
    names = sorted(set(bots))
    if not names:
        return {}
    claimants = [b for b in names if b in set(priority)]
    if not claimants:
        reserve = 0.0  # nobody can spend it; see the module docstring
    base = (1.0 - reserve) / len(names)
    out = {b: base for b in names}
    for b in claimants:
        out[b] += reserve / len(claimants)
    return out


def limit_warning(rows) -> bool:
    """True when the subscription itself refused a call somewhere in the window."""
    return any(r.get("limit_text") for r in rows)


def _cfg(overrides=None) -> dict:
    cfg = dict(DEFAULT_CFG)
    path = os.environ.get(CONFIG_ENV) or DEFAULT_CONFIG
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            cfg.update(loaded)
    except (OSError, ValueError):
        pass  # no config is the documented default, not an error
    if overrides:
        cfg.update(overrides)
    return cfg


def over_share(rows, end, cfg=None) -> list:
    """Every bot whose spend in the window ending `end` exceeds its share."""
    conf = _cfg(cfg)
    inside = window(rows, end, conf["window_days"])
    spend = spend_by_bot(inside)
    total = sum(spend.values())
    if total <= 0:
        return []
    allowed = shares(spend, conf["priority"], conf["reserve"])
    return sorted(b for b, v in spend.items() if v / total > allowed[b])


def decide(rows, bot: str, now: str, cfg=None) -> Decision:
    """Run or pause `bot`, judged on the window ending on `now`'s date."""
    conf = _cfg(cfg)
    end = str(now)[:10]
    inside = window(rows, end, conf["window_days"])
    spend = spend_by_bot(inside)
    total = sum(spend.values())
    # The bot being judged is always on the share line even when it spent
    # nothing this week: otherwise a quiet bot has no share to be measured
    # against and every caller has to special-case a KeyError.
    allowed = shares(set(spend) | {bot}, conf["priority"], conf["reserve"])
    used = (spend.get(bot, 0.0) / total) if total > 0 else 0.0
    if limit_warning(inside) and bot in set(conf["low_priority"]):
        return Decision("pause", "fleet-floor", used, allowed[bot], bot, end)
    if used > allowed[bot]:
        return Decision("pause", "over-share", used, allowed[bot], bot, end)
    return Decision("run", "under-share", used, allowed[bot], bot, end)


# --- state: one pause episode per bot, one alert, one trial run -------------

def state_path() -> str:
    return os.environ.get(STATE_ENV) or DEFAULT_STATE


def read_state() -> dict:
    try:
        with open(state_path(), encoding="utf-8") as fh:
            got = json.load(fh)
        return got if isinstance(got, dict) and isinstance(got.get("bots"), dict) else {"bots": {}}
    except (OSError, ValueError):
        return {"bots": {}}


def write_state(state: dict) -> bool:
    target = state_path()
    try:
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
        return True
    except (OSError, TypeError, ValueError) as exc:
        sys.stderr.write(f"usage_breaker: cannot write {target}: {exc}\n")
        return False


def _seconds_between(earlier: str, later: str) -> float:
    def parse(v):
        return _dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    try:
        return (parse(later) - parse(earlier)).total_seconds()
    except (TypeError, ValueError):
        return 0.0


def notify(line: str) -> None:
    """One line to the fleet alert sink. Never raises; a brake is not an alerter."""
    script = os.environ.get(NOTIFY_ENV) or _REPO_NOTIFY
    if not os.path.isfile(script):
        sys.stderr.write(f"usage_breaker: no alert sink at {script}; not paged: {line}\n")
        return
    try:
        subprocess.run(["bash", script, line], check=False, timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"usage_breaker: alert failed ({exc}); not paged: {line}\n")


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check(bot: str, now: str, cfg=None) -> int:
    """The CLI's whole decision. Returns the exit code: 0 run, 3 paused."""
    if os.environ.get(OFF_ENV) == "0":
        sys.stderr.write(f"usage_breaker: OFF ({OFF_ENV}=0); {bot} runs unbraked\n")
        return 0
    rows = usage_ledger.read()
    if not rows:
        # Fail OPEN and say so. See the module docstring: a brake that dark-starts
        # the fleet on its own bad day is worse than the spend it prevents.
        sys.stderr.write(f"usage_breaker: no usage rows at {usage_ledger.ledger_path()}; "
                         f"{bot} runs unbraked\n")
        return 0
    d = decide(rows, bot, now, cfg)
    state = read_state()
    entry = dict(state["bots"].get(bot) or {})

    if d.action == "run":
        if entry.get("paused_at"):
            state["bots"][bot] = {"paused_at": None, "trial_at": None, "cleared_at": now,
                                  "reason": None}
            write_state(state)
            print(f"usage_breaker: {bot} resumed ({d.share_used:.3f} of "
                  f"{d.share_allowed:.3f} share, window ending {d.end})")
        return 0

    if not entry.get("paused_at"):
        state["bots"][bot] = {"paused_at": now, "trial_at": None, "cleared_at": None,
                              "reason": d.reason}
        write_state(state)
        notify(f"usage-breaker: PAUSED {bot} ({d.reason}) -- used {d.share_used:.3f} of its "
               f"{d.share_allowed:.3f} share over the 7 days ending {d.end}. One trial run in 24h.")
        print(f"usage_breaker: {bot} PAUSED ({d.reason})")
        return 3

    # Already paused. One trial run, once, 24h in -- and never a second alert: the
    # worker ticks every 15 minutes, so a page per check is 96 tickets a day.
    if not entry.get("trial_at") and _seconds_between(entry["paused_at"], now) >= TRIAL_AFTER_SECONDS:
        entry["trial_at"] = now
        state["bots"][bot] = entry
        write_state(state)
        print(f"usage_breaker: {bot} trial run granted (paused {entry['paused_at']})")
        return 0
    print(f"usage_breaker: {bot} held ({d.reason}, paused {entry['paused_at']})")
    return 3


def report(now: str) -> int:
    rows = usage_ledger.read()
    if not rows:
        sys.stderr.write(f"usage_breaker: no usage rows at {usage_ledger.ledger_path()}\n")
        return 0
    conf = _cfg()
    end = str(now)[:10]
    inside = window(rows, end, conf["window_days"])
    spend = spend_by_bot(inside)
    total = sum(spend.values())
    allowed = shares(spend, conf["priority"], conf["reserve"])
    state = read_state()
    print(f"window {conf['window_days']}d ending {end}  total ${total:.4f}  "
          f"limit_warning={limit_warning(inside)}")
    for bot in sorted(spend, key=lambda b: -spend[b]):
        frac = spend[bot] / total if total else 0.0
        held = (state["bots"].get(bot) or {}).get("paused_at")
        print(f"  {bot:<10} ${spend[bot]:>9.4f}  {frac:.3f} of {allowed[bot]:.3f}"
              f"{'  PAUSED ' + held if held else ''}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="run or pause one bot (exit 0 run, 3 paused)")
    c.add_argument("--bot", required=True)
    c.add_argument("--now", default=None, help="ISO timestamp; defaults to now (UTC)")
    r = sub.add_parser("report", help="the window, per bot, with shares")
    r.add_argument("--now", default=None)
    args = ap.parse_args(argv)
    now = args.now or _now_iso()
    if args.cmd == "check":
        return check(args.bot, now)
    return report(now)


if __name__ == "__main__":
    sys.exit(main())
