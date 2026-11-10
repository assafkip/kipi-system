#!/usr/bin/env python3
"""The fleet's API-credit ledger and daily budget (ASK-4311).

WHY THIS EXISTS. Two Claude Ultra accounts each carry a $250/month Console API
credit, and that credit applies only to a run presenting an API key from the
linked Console org. Signed in with the plan, the same run draws on plan limits,
which is how the fleet ran until this file: 17 fleet scripts strip
`ANTHROPIC_API_KEY` on purpose. Founder, 2026-11-09, verbatim: "Im okay spending
the moeny I get from anthropic on the api. but I dont want to pay more myself".

So the ceiling is $500 a month and nothing here can ever buy credit. This module
owns two questions and nothing else:

  1. How much has each key spent this month, and what is left of its credit?
  2. What may the fleet spend today, and has it spent it?

WHY A BY-DAY SPREAD AND NOT A MONTHLY POOL. A monthly pool is spendable in a
day: the dispatcher tops up to its concurrency cap every 15 minutes, so an
unattended night can drain $500 and leave 29 days dark. The allowance is
therefore the credit that is actually LEFT divided by the days that are actually
LEFT, recomputed on every read. A quiet day raises tomorrow's allowance by
itself, and a heavy day lowers it, with no catch-up state to keep.

WHY THE BUDGET DAY STARTS AT 07:00 LOCAL. Same window the dispatcher's issue
counter already uses (`kipi-dispatch.sh`, RESET_HOUR, founder-set 2026-07-28), so
the two gates agree about which day a 03:00 run belongs to. A fresh allowance
arriving at local midnight hands the whole thing to an unattended overnight run.

WHY THE LEDGER IS APPEND-ONLY JSONL OUTSIDE EVERY REPO. A spend record that
lives in a checkout is a tracked file a scheduled job writes, which
`separate-worktrees.md` forbids, and a rewrite-in-place ledger loses rows when
two runs finish at once. One `O_APPEND` write of one line is atomic for our
line sizes, so concurrent runs interleave rows rather than clobbering them.

NOTHING HERE FAILS A RUN IT METERS. A ledger that cannot be read returns an
empty history and says so on stderr; a row that cannot be written is skipped.
The same contract `voiceloop/usage_ledger.py` states, for the same reason: a
meter that kills the job it meters is worse than no meter.

Usage:
  fleet_api_spend.py record --slot 1 --cost 0.42 [--actor worker] [--ok|--failed]
  fleet_api_spend.py budget [--json]      # today's allowance, spent, remaining
  fleet_api_spend.py credit [--json]      # per-key credit left this month
  fleet_api_spend.py event <kind> <text>  # pause / resume / failover, for the report
  fleet_api_spend.py events [--day D]     # read today's events back

Exit codes: 0 ok. 2 usage. 3 the day's budget is spent (`budget` only).

Env:
  KIPI_FLEET_SPEND_LEDGER   ledger path (default ~/.local/state/kipi/fleet-api-spend.jsonl)
  KIPI_FLEET_EVENTS         events path (default ~/.local/state/kipi/fleet-api-events.jsonl)
  KIPI_FLEET_MONTHLY_CREDIT per-key monthly credit in USD (default 250)
  KIPI_DISPATCH_RESET_HOUR  budget-day boundary, local hour (default 7)
  KIPI_FLEET_NOW            epoch seconds; the test clock
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import os
import sys

SCHEMA = 1
PRODUCER = "fleet_api_spend"

#: The two Ultra accounts. Slot order IS the failover order (see fleet_api_key.py).
SLOTS = (1, 2)

DEFAULT_LEDGER = os.path.join(
    os.path.expanduser("~"), ".local", "state", "kipi", "fleet-api-spend.jsonl")
DEFAULT_EVENTS = os.path.join(
    os.path.expanduser("~"), ".local", "state", "kipi", "fleet-api-events.jsonl")

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_BUDGET_SPENT = 3

_WARNED = set()


def _warn(msg):
    """Say a degradation once, never twice, and never on stdout."""
    if msg in _WARNED:
        return
    _WARNED.add(msg)
    sys.stderr.write("fleet_api_spend: %s\n" % msg)


def ledger_path():
    return os.environ.get("KIPI_FLEET_SPEND_LEDGER") or DEFAULT_LEDGER


def events_path():
    return os.environ.get("KIPI_FLEET_EVENTS") or DEFAULT_EVENTS


def monthly_credit_per_key():
    raw = os.environ.get("KIPI_FLEET_MONTHLY_CREDIT", "")
    try:
        return float(raw) if raw else 250.0
    except ValueError:
        _warn("KIPI_FLEET_MONTHLY_CREDIT=%r is not a number; using 250" % raw)
        return 250.0


def reset_hour():
    raw = os.environ.get("KIPI_DISPATCH_RESET_HOUR", "")
    try:
        return int(raw) if raw else 7
    except ValueError:
        return 7


def now():
    """Local-time `datetime`. KIPI_FLEET_NOW (epoch seconds) is the test clock."""
    raw = os.environ.get("KIPI_FLEET_NOW", "")
    if raw:
        try:
            return dt.datetime.fromtimestamp(float(raw))
        except (ValueError, OSError):
            _warn("KIPI_FLEET_NOW=%r is not epoch seconds; using the real clock" % raw)
    return dt.datetime.now()


def budget_day(at=None):
    """The label of the budget day `at` falls in: the clock shifted back RESET_HOUR.

    Same rule as kipi-dispatch.sh, so 03:00 Tuesday belongs to Monday's budget in
    BOTH gates. A disagreement here would pause one gate and not the other.
    """
    at = at or now()
    return (at - dt.timedelta(hours=reset_hour())).strftime("%Y-%m-%d")


def month_key(at=None):
    """Credit is granted per CALENDAR month, so this is not shifted by RESET_HOUR."""
    at = at or now()
    return at.strftime("%Y-%m")


def days_left_in_month(at=None):
    """Today included, so the last day of the month divides by 1, never by 0."""
    at = at or now()
    return calendar.monthrange(at.year, at.month)[1] - at.day + 1


def _read_rows(path):
    """Every well-formed row in `path`. A broken line is skipped, never fatal."""
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError as exc:
        _warn("cannot read %s (%s); treating the history as empty" % (path, exc))
        return []
    return rows


def _append(path, row):
    """One O_APPEND line. A write that fails is skipped, never raised."""
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(path, "a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        return True
    except OSError as exc:
        _warn("cannot append to %s (%s); the row is dropped" % (path, exc))
        return False


def _cost(row):
    try:
        value = float(row.get("cost_usd") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    # A negative or non-finite cost is a corrupt row, not a refund.
    return value if value > 0 and value == value and value != float("inf") else 0.0


def record(slot, cost_usd, actor=None, ok=True, note=None, at=None):
    """Append one spend row. Returns the row, written or not."""
    at = at or now()
    row = {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "ts": at.isoformat(timespec="seconds"),
        "day": budget_day(at),
        "month": month_key(at),
        "slot": int(slot),
        "cost_usd": round(float(cost_usd or 0.0), 6),
        "actor": actor or os.environ.get("KIPI_AGENT") or "unknown",
        "ok": bool(ok),
    }
    if note:
        row["note"] = note
    row["written"] = _append(ledger_path(), row)
    return row


def spent_month(slot=None, at=None):
    """USD charged this calendar month, for one slot or for both."""
    month = month_key(at)
    total = 0.0
    for row in _read_rows(ledger_path()):
        if row.get("month") != month:
            continue
        if slot is not None and row.get("slot") != int(slot):
            continue
        total += _cost(row)
    return round(total, 6)


def spent_today(at=None):
    """USD charged in the current budget day, across both slots."""
    day = budget_day(at)
    total = 0.0
    for row in _read_rows(ledger_path()):
        if row.get("day") == day:
            total += _cost(row)
    return round(total, 6)


def credit_left(slot, at=None):
    """What this key has left of its monthly credit. Never below zero."""
    return round(max(0.0, monthly_credit_per_key() - spent_month(slot, at)), 6)


def credit(at=None):
    """Per-key and total credit left this month."""
    per_key = dict((s, credit_left(s, at)) for s in SLOTS)
    return {
        "month": month_key(at),
        "per_key_usd": per_key,
        "per_key_monthly_credit_usd": monthly_credit_per_key(),
        "total_left_usd": round(sum(per_key.values()), 6),
    }


def budget(at=None):
    """Today's allowance, what it has spent, and whether it is spent out.

    allowance = total credit LEFT / days LEFT in the month (today included).
    Recomputed on every read, so a quiet day raises tomorrow by itself.
    """
    at = at or now()
    left = credit(at)["total_left_usd"]
    days = days_left_in_month(at)
    allowance = round(left / days, 6) if days > 0 else 0.0
    spent = spent_today(at)
    return {
        "day": budget_day(at),
        "allowance_usd": allowance,
        "spent_usd": spent,
        "remaining_usd": round(max(0.0, allowance - spent), 6),
        "total_credit_left_usd": left,
        "days_left_in_month": days,
        # True when the day's allowance is gone, OR the month's credit is: the
        # second is the hard ceiling Anthropic enforces and no day may cross it.
        "exhausted": spent >= allowance or left <= 0.0,
    }


def event(kind, text, at=None):
    """Record a pause, resume or failover for the daily chief report."""
    at = at or now()
    row = {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "ts": at.isoformat(timespec="seconds"),
        "day": budget_day(at),
        "kind": str(kind),
        "text": str(text),
    }
    row["written"] = _append(events_path(), row)
    return row


def events(day=None, at=None):
    """Events for one budget day (default: the current one)."""
    want = day or budget_day(at)
    return [r for r in _read_rows(events_path()) if r.get("day") == want]


def _main(argv):
    ap = argparse.ArgumentParser(prog="fleet_api_spend.py", description=__doc__)
    sub = ap.add_subparsers(dest="cmd")

    p_rec = sub.add_parser("record", help="append one spend row")
    p_rec.add_argument("--slot", type=int, required=True, choices=list(SLOTS))
    p_rec.add_argument("--cost", type=float, required=True)
    p_rec.add_argument("--actor")
    p_rec.add_argument("--note")
    p_rec.add_argument("--failed", action="store_true",
                       help="the run failed; the cost is still real and still charged")

    p_bud = sub.add_parser("budget", help="today's allowance, spent and remaining")
    p_bud.add_argument("--json", action="store_true")

    p_cre = sub.add_parser("credit", help="credit left per key this month")
    p_cre.add_argument("--json", action="store_true")

    p_ev = sub.add_parser("event", help="record a pause / resume / failover")
    p_ev.add_argument("kind")
    p_ev.add_argument("text")

    p_evs = sub.add_parser("events", help="read a budget day's events back")
    p_evs.add_argument("--day")

    args = ap.parse_args(argv)

    if args.cmd == "record":
        row = record(args.slot, args.cost, actor=args.actor,
                     ok=not args.failed, note=args.note)
        print(json.dumps(row, sort_keys=True))
        return EXIT_OK

    if args.cmd == "budget":
        state = budget()
        if args.json:
            print(json.dumps(state, sort_keys=True))
        else:
            print("day=%s allowance=$%.2f spent=$%.2f remaining=$%.2f "
                  "credit_left=$%.2f days_left=%d exhausted=%s"
                  % (state["day"], state["allowance_usd"], state["spent_usd"],
                     state["remaining_usd"], state["total_credit_left_usd"],
                     state["days_left_in_month"],
                     "yes" if state["exhausted"] else "no"))
        return EXIT_BUDGET_SPENT if state["exhausted"] else EXIT_OK

    if args.cmd == "credit":
        state = credit()
        if args.json:
            print(json.dumps(state, sort_keys=True))
        else:
            for slot in SLOTS:
                print("key %d: $%.2f left of $%.2f"
                      % (slot, state["per_key_usd"][slot],
                         state["per_key_monthly_credit_usd"]))
            print("total: $%.2f left this month" % state["total_left_usd"])
        return EXIT_OK

    if args.cmd == "event":
        print(json.dumps(event(args.kind, args.text), sort_keys=True))
        return EXIT_OK

    if args.cmd == "events":
        for row in events(day=args.day):
            print(json.dumps(row, sort_keys=True))
        return EXIT_OK

    ap.print_usage(sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
