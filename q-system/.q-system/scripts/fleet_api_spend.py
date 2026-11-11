#!/usr/bin/env python3
"""The fleet's API-credit ledger and daily budget (ASK-4311).

WHY THIS EXISTS. Each Claude account carries a monthly Console API credit, and
that credit applies only to a run presenting an API key from the linked Console
org. Signed in with the plan, the same run draws on plan limits, which is how the
fleet ran until this file: 17 fleet scripts strip `ANTHROPIC_API_KEY` on purpose.
Founder, 2026-11-09, verbatim: "Im okay spending the moeny I get from anthropic on
the api. but I dont want to pay more myself".

So the ceiling is the sum of the credits, and nothing here can ever buy credit.
This module owns two questions and nothing else:

  1. How much has each key spent this billing cycle, and what is left?
  2. What may the fleet spend today, and has it spent it?

WHERE THE CREDIT FACTS LIVE. `~/.config/kipi/fleet-api.json`, one row per key:
`monthly_credit_usd`, `current_cycle_expires_utc` and
`auto_reload_off_confirmed_at`, each with its source. No amount or date is
written in this file. The first build assumed $250 per key per calendar month;
both halves were wrong (Help Center article 17154008, read 2026-11-10): the
credit is $100 on Max and $200 on Ultra, and it refreshes per BILLING CYCLE and
expires unused at the cycle's end. The $250 was the Max subscription price on a
receipt. A number in code would have been wrong silently; a number in the facts
file is wrong in one place with its source beside it.

A KEY WITH AN UNKNOWN CREDIT OR CYCLE IS NOT USED. A null credit, a null or
past cycle expiry, or no auto-reload confirmation means that key is never run,
never failed over to, and adds $0 to the allowance. Guessing would
spend against a ceiling nobody measured, and with auto-reload unverified the
overflow could be the founder's own money. The daily report names the key and
the file to fix, every day, until it is set.

WHY A BY-DAY SPREAD AND NOT A CYCLE POOL. A pool is spendable in a day: the
dispatcher tops up to its concurrency cap every 15 minutes, so an unattended
night can drain it and leave weeks dark. Today's allowance is therefore, for
each key, the credit it had LEFT when today began divided by the days LEFT in
that key's own cycle, summed over the keys. A quiet day raises tomorrow's
allowance by itself and a heavy day lowers it, with no catch-up state to keep.

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
  fleet_api_spend.py credit [--json]      # per-key credit left this cycle
  fleet_api_spend.py event <kind> <text>  # pause / resume / failover, for the report
  fleet_api_spend.py events [--day D]     # read today's events back

Exit codes: 0 ok. 2 usage. 3 the day's budget is spent (`budget` only).

Env:
  KIPI_FLEET_SPEND_LEDGER   ledger path (default ~/.local/state/kipi/fleet-api-spend.jsonl)
  KIPI_FLEET_EVENTS         events path (default ~/.local/state/kipi/fleet-api-events.jsonl)
  KIPI_FLEET_API_FACTS      per-key credit, cycle expiry and auto-reload facts
                            (default ~/.config/kipi/fleet-api.json; under
                            KIPI_TEST=1 there is NO default, so a suite can
                            never read the live file)
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
DEFAULT_FACTS = os.path.join(
    os.path.expanduser("~"), ".config", "kipi", "fleet-api.json")

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


def facts_path():
    """Where the per-key credit facts live, or None.

    NO DEFAULT UNDER KIPI_TEST=1. A suite that forgot to point this at a fixture
    would otherwise read the founder's live file and pass or fail on whatever
    it says that day. With no path every key reads as unknown, which no budget
    case can mistake for a configured one.
    """
    env = os.environ.get("KIPI_FLEET_API_FACTS")
    if env:
        return env
    if os.environ.get("KIPI_TEST") == "1":
        return None
    return DEFAULT_FACTS


def _number(value):
    """A finite, non-negative real number, or None. A bool is not a number here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        return None
    return value


def _utc_instant(value):
    """A timestamp WITH an offset, as a naive LOCAL datetime (the clock now()
    speaks), or None. A naive timestamp is refused rather than assumed UTC or
    local: the Console prints its expiry in UTC and a guessed zone moves the
    end of a cycle by up to a day."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        return None
    return dt.datetime.fromtimestamp(when.timestamp())


def key_facts():
    """{slot: {"credit_usd", "expires_at", "expires_utc", "confirmed_at"}}.
    Never raises.

    Anything unreadable (no file, bad JSON, a missing row, a null) leaves that
    key UNKNOWN, and an unknown key is never run (see the module docstring).
    """
    out = dict((s, {"credit_usd": None, "expires_at": None, "expires_utc": None,
                    "confirmed_at": None}) for s in SLOTS)
    path = facts_path()
    if not path:
        _warn("KIPI_TEST=1 and KIPI_FLEET_API_FACTS is unset: every key's credit "
              "is unknown")
        return out
    try:
        with open(path, "r") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        _warn("cannot read %s (%s): every key's credit is unknown" % (path, exc))
        return out
    keys = doc.get("keys") if isinstance(doc, dict) else None
    if not isinstance(keys, dict):
        _warn("%s has no `keys` object: every key's credit is unknown" % path)
        return out
    for slot in SLOTS:
        row = keys.get(str(slot))
        if not isinstance(row, dict):
            continue
        out[slot]["credit_usd"] = _number(row.get("monthly_credit_usd"))
        expires = _utc_instant(row.get("current_cycle_expires_utc"))
        if expires is not None:
            out[slot]["expires_at"] = expires
            out[slot]["expires_utc"] = row["current_cycle_expires_utc"].strip()
        confirmed = row.get("auto_reload_off_confirmed_at")
        if isinstance(confirmed, str) and confirmed.strip():
            out[slot]["confirmed_at"] = confirmed.strip()
    return out


def configured(slot, facts=None, at=None):
    """Does this key have a known credit AND a cycle that has not ended yet?

    A PAST expiry counts as unknown, not as "still the old cycle". The Console
    grants the next cycle's credit with a new expiry, and nothing here can read
    it; inferring "one month later" is a guess the founder's money would back.
    The key stops, the report says which field to update, and the fleet runs
    on whatever other key is known.
    """
    row = (facts or key_facts()).get(slot) or {}
    if row.get("credit_usd") is None or row.get("expires_at") is None:
        return False
    return (at or now()) < row["expires_at"]


def configured_slots(facts=None, at=None):
    """The keys with a known credit and a live cycle, in failover order."""
    facts = facts or key_facts()
    return tuple(s for s in SLOTS if configured(s, facts, at))


def billable(slot, facts=None, at=None):
    """May the fleet bill this key? Known credit AND auto-reload confirmed off.

    THE SPEND RULE HOLDS ONLY IF AUTO-RELOAD IS OFF (orchestrator, 2026-11-10,
    binding). "I dont want to pay more myself" is true only while Anthropic
    refuses at the credit. With auto-reload on, or with the credit not yet
    claimed, the first run past the credit charges the founder's card. Nothing
    here can read a Console billing setting, so the founder's confirmation is a
    field in the facts file, `auto_reload_off_confirmed_at`, written by the
    orchestrator one slot at a time. No timestamp, no run.
    """
    facts = facts or key_facts()
    return configured(slot, facts, at) and bool((facts.get(slot) or {}).get("confirmed_at"))


def billable_slots(facts=None, at=None):
    """The keys the fleet may actually bill, in failover order."""
    facts = facts or key_facts()
    return tuple(s for s in SLOTS if billable(s, facts, at))


def unconfirmed_slots(facts=None, at=None):
    """Keys with a known credit and cycle whose auto-reload is not confirmed off."""
    facts = facts or key_facts()
    return tuple(s for s in SLOTS
                 if configured(s, facts, at) and not billable(s, facts, at))


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


def budget_day_start(day=None, at=None):
    """The local-clock instant a budget day BEGINS: that day at RESET_HOUR.

    The inverse of `budget_day()`, and it exists because the label alone is not a
    timestamp. The report appended "T00:00:00Z" to it and asked Linear for
    everything completed since then, which in a UTC-8 zone is 15 hours before
    the day it claimed to measure -- it counted most of the previous afternoon
    and evening (PR #717 review round 1, finding 4). Wall-clock arithmetic on
    purpose, matching budget_day(): a day that crosses a DST boundary is 23 or 25
    hours long and still runs 07:00 to 07:00 by the clock on the wall.
    """
    label = day or budget_day(at)
    base = dt.datetime.strptime(label, "%Y-%m-%d")
    return base + dt.timedelta(hours=reset_hour())


def _utc_z(local_naive):
    """A naive LOCAL datetime as a UTC ISO-8601 `...Z` string."""
    return local_naive.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def budget_day_window_utc(day=None, at=None):
    """(start, end) of a budget day as UTC `...Z` strings, end exclusive.

    Both bounds, not just the start: a `--force` re-run, or a report built for a
    past day, would otherwise count everything since that day began.
    """
    start = budget_day_start(day, at)
    return _utc_z(start), _utc_z(start + dt.timedelta(days=1))


def _month_before(when):
    """The same wall-clock instant one calendar month earlier, day clamped."""
    year, month = (when.year - 1, 12) if when.month == 1 else (when.year, when.month - 1)
    day = min(when.day, calendar.monthrange(year, month)[1])
    return when.replace(year=year, month=month, day=day)


def cycle(slot, at=None, facts=None):
    """(start_label, end_label) of `slot`'s current cycle in budget-day labels,
    end exclusive, or None when the credit or the cycle is unknown or ended.

    THE END IS THE CONSOLE'S EXPIRY, not an inferred anchor. The first cut
    anchored key 1 on the 26th from Google Play renewals; the Console says its
    credit expires 2026-11-29 00:00 UTC (granted Nov 10), and the orchestrator
    ruled the Console the source. The end label is the budget day AFTER the one
    the expiry falls in, so that day's spend still counts against the cycle.

    WHY THIS RETIRES ROUND 3'S 1ST-OF-MONTH WINDOW (PR #717, minor 2). budget()
    divided a budget day's spend, which belonged to the old day until 07:00, by
    a calendar month that had already rolled at midnight. There is no calendar
    month left: a key's credit is paced against its own expiry, and a budget
    day's spend is compared with that same day's allowance.

    The START only selects ledger rows: one month before the expiry. A row from
    before a credit was granted cannot exist for a key the fleet had not used.
    """
    facts = facts or key_facts()
    if not configured(slot, facts, at):
        return None
    expires = facts[slot]["expires_at"]
    last = dt.datetime.strptime(budget_day(expires - dt.timedelta(seconds=1)), "%Y-%m-%d")
    end = (last + dt.timedelta(days=1)).strftime("%Y-%m-%d")
    return budget_day(_month_before(expires)), end


def cycle_id(slot, at=None, facts=None):
    """The label an exhausted mark carries: the cycle's expiry as written in the
    facts file, or None. A new expiry in the file is a new cycle, so every mark
    from the old one reads stale and the key comes back."""
    facts = facts or key_facts()
    if not configured(slot, facts, at):
        return None
    return facts[slot]["expires_utc"]


def days_left_in_cycle(slot, at=None, facts=None):
    """Budget days left in `slot`'s cycle, today included, so never 0. None if
    the key's credit or cycle is unknown or ended."""
    bounds = cycle(slot, at, facts)
    if not bounds:
        return None
    today = dt.datetime.strptime(budget_day(at), "%Y-%m-%d").date()
    end = dt.datetime.strptime(bounds[1], "%Y-%m-%d").date()
    return max(1, (end - today).days)


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


def record(slot, cost_usd, actor=None, ok=True, note=None, at=None,
           unmetered=False):
    """Append one spend row. Returns the row, written or not.

    `unmetered` MARKS A COST THAT WAS REALLY CHARGED AND NEVER READ (PR #717
    review round 2, finding 2). `linear-worker.sh` kills a hung run by process
    group at 1800s, and `claude -p` prints `total_cost_usd` only at the end, so a
    killed Opus turn's real cost is gone -- Anthropic charged it, and no reader
    here can recover the number. The honest move is not to invent one: the row
    carries cost 0 with this flag, `unmetered_today()` counts it, and the daily
    report says the day's spend is a FLOOR. A silent 0 would instead have the
    meter claim the run was free, and the allowance is divided out of that
    number.
    """
    at = at or now()
    row = {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "ts": at.isoformat(timespec="seconds"),
        "day": budget_day(at),
        "slot": int(slot),
        "cost_usd": round(float(cost_usd or 0.0), 6),
        "actor": actor or os.environ.get("KIPI_AGENT") or "unknown",
        "ok": bool(ok),
    }
    if unmetered:
        row["unmetered"] = True
    if note:
        row["note"] = note
    row["written"] = _append(ledger_path(), row)
    return row


def spent_cycle(slot, at=None, facts=None, before_today=False):
    """USD this key was charged in its current cycle. 0.0 for an unknown key.

    `before_today` stops at the start of the current budget day: the base the
    day's allowance is divided out of, so spending today does not shrink
    today's own allowance while it is being spent.
    """
    bounds = cycle(slot, at, facts)
    if not bounds:
        return 0.0
    start, end = bounds
    stop = budget_day(at) if before_today else end
    total = 0.0
    for row in _read_rows(ledger_path()):
        if row.get("slot") != int(slot):
            continue
        day = row.get("day")
        if not isinstance(day, str) or not (start <= day < end) or day >= stop:
            continue
        total += _cost(row)
    return round(total, 6)


def spent_today(at=None, slots=None):
    """USD charged in the current budget day, on every key or on `slots`."""
    day = budget_day(at)
    total = 0.0
    for row in _read_rows(ledger_path()):
        if row.get("day") == day and (slots is None or row.get("slot") in slots):
            total += _cost(row)
    return round(total, 6)


def unmetered_today(at=None):
    """How many runs in this budget day were charged and never read.

    The count the daily report turns into "today's spend is a floor, not a
    total". Deliberately a COUNT and not an estimate: there is no honest dollar
    figure to put here, and a guessed one would be spent against a real ceiling.
    """
    day = budget_day(at)
    return sum(1 for row in _read_rows(ledger_path())
               if row.get("day") == day and row.get("unmetered") is True)


def credit_left(slot, at=None, facts=None):
    """What this key has left of its cycle's credit, never below zero. None when
    the credit is unknown: an unknown is not a zero and not a number."""
    facts = facts or key_facts()
    if not configured(slot, facts, at):
        return None
    left = facts[slot]["credit_usd"] - spent_cycle(slot, at, facts)
    return round(max(0.0, left), 6)


def credit(at=None):
    """Per-key credit, cycle and what is left. Unknown keys are listed, not zeroed."""
    facts = key_facts()
    per_key, per_credit, per_cycle = {}, {}, {}
    for slot in SLOTS:
        per_key[slot] = credit_left(slot, at, facts)
        per_credit[slot] = facts[slot]["credit_usd"]
        bounds = cycle(slot, at, facts)
        per_cycle[slot] = None if not bounds else {
            "start": bounds[0], "end": bounds[1],
            "days_left": days_left_in_cycle(slot, at, facts)}
    return {
        "facts_path": facts_path(),
        "per_key_usd": per_key,
        "per_key_credit_usd": per_credit,
        "per_key_cycle": per_cycle,
        "unknown_keys": [s for s in SLOTS if not configured(s, facts, at)],
        "unconfirmed_keys": list(unconfirmed_slots(facts, at)),
        "per_key_expires_utc": dict((s, facts[s]["expires_utc"]) for s in SLOTS),
        "total_left_usd": round(sum(v for v in per_key.values() if v is not None), 6),
    }


def budget(at=None):
    """Today's allowance, what it has spent, and whether it is spent out.

    allowance = SUM over BILLABLE keys of
        (that key's credit left when today began) / (days left in its cycle)

    Each key on its own cycle: key 1 renews on the 26th, key 2 may renew on
    another day, and a credit that expires unused at its own cycle's end has to
    be paced against that end, not against the calendar month.
    """
    at = at or now()
    facts = key_facts()
    # Billable, not merely known: a key whose auto-reload is not confirmed off
    # runs nothing, so its credit is not today's to spend.
    known = billable_slots(facts, at)
    allowance = 0.0
    for slot in known:
        base = max(0.0, facts[slot]["credit_usd"]
                   - spent_cycle(slot, at, facts, before_today=True))
        allowance += base / days_left_in_cycle(slot, at, facts)
    allowance = round(allowance, 6)
    # The REPORT shows every dollar spent today; the VERDICT compares the
    # allowance with what the billable keys spent. On the day a key's cycle
    # ends, its morning spend belongs to a credit that is gone, and charging it
    # to the other key's share would stop that key early.
    spent = spent_today(at)
    spent_billable = spent_today(at, slots=known)
    left = round(sum(credit_left(s, at, facts) for s in known), 6)
    if not known:
        reason = ("no key is billable (each needs monthly_credit_usd, a future "
                  "current_cycle_expires_utc and auto_reload_off_confirmed_at) in %s"
                  % (facts_path() or "(no facts file)"))
    elif left <= 0.0:
        reason = "every known key's cycle credit is spent"
    elif spent_billable >= allowance:
        reason = "today's allowance is spent"
    else:
        reason = None
    return {
        "day": budget_day(at),
        "allowance_usd": allowance,
        "spent_usd": spent,
        "remaining_usd": round(max(0.0, allowance - spent_billable), 6),
        "total_credit_left_usd": left,
        "known_keys": list(known),
        # Exhausted when the day's allowance is gone, when every known credit
        # is (the hard ceiling Anthropic enforces), or when no key is known.
        "exhausted": reason is not None,
        "reason": reason,
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


def event_once(kind, text, at=None):
    """`event`, but at most one row of this KIND per budget day.

    FOR A CONDITION A READER NOTICES ON A TIMER (PR #717 review round 2, finding
    1). The dispatcher's gate probes every 15 minutes, so a condition that
    persists -- no key installed, say -- would file 96 identical rows a day, the
    report would render all of them, and an alert channel that cries 96 times
    gets muted. One row a day is the signal; the next budget day earns its own.

    The dedupe lives in the LEDGER rather than in a state file on purpose: it is
    then visible to anyone reading the events back, and it adds no field to the
    key state that a reader would have to write (`fleet_api_key.usable_slot`
    exists in two modes precisely because a reader writing state burned the
    paused fleet's one daily re-probe).
    """
    at = at or now()
    if any(r.get("kind") == str(kind) for r in events(at=at)):
        return {"kind": str(kind), "text": str(text), "day": budget_day(at),
                "deduped": True, "written": False}
    return event(kind, text, at=at)


def events(day=None, at=None):
    """Events for one budget day (default: the current one)."""
    want = day or budget_day(at)
    return [r for r in _read_rows(events_path()) if r.get("day") == want]


def describe_key(state, slot):
    """One line for one key, shared by `credit` and the daily report so the two
    cannot word the same fact two ways. An unused key says NOT USED, why, and
    which field of which file to set."""
    where = state.get("facts_path") or "the facts file"
    left = state["per_key_usd"].get(slot)
    if left is not None and slot in (state.get("unconfirmed_keys") or []):
        return ("key %d: NOT USED, auto-reload off is not confirmed, so a run past "
                "the credit could charge the card. Set auto_reload_off_confirmed_at "
                "for key %d in %s once it is (credit $%.2f this cycle)"
                % (slot, slot, where, state["per_key_credit_usd"][slot]))
    if left is None:
        if state["per_key_credit_usd"].get(slot) is None:
            return ("key %d: NOT USED, credit unknown. Set monthly_credit_usd for "
                    "key %d in %s" % (slot, slot, where))
        expires = (state.get("per_key_expires_utc") or {}).get(slot)
        if expires:
            return ("key %d: NOT USED, its billing cycle ended at %s. Read the new "
                    "expiry on the Console Billing page and set "
                    "current_cycle_expires_utc for key %d in %s"
                    % (slot, expires, slot, where))
        return ("key %d: NOT USED, billing cycle unknown. Set "
                "current_cycle_expires_utc for key %d in %s (the Console Billing "
                "page shows it)" % (slot, slot, where))
    cyc = state["per_key_cycle"][slot]
    return ("key %d: $%.2f left of $%.2f this cycle (ends %s, %d budget day%s left)"
            % (slot, left, state["per_key_credit_usd"][slot],
               state["per_key_expires_utc"][slot], cyc["days_left"],
               "" if cyc["days_left"] == 1 else "s"))


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

    p_cre = sub.add_parser("credit", help="credit left per key this cycle")
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
                  "credit_left=$%.2f exhausted=%s%s"
                  % (state["day"], state["allowance_usd"], state["spent_usd"],
                     state["remaining_usd"], state["total_credit_left_usd"],
                     "yes" if state["exhausted"] else "no",
                     " (%s)" % state["reason"] if state["reason"] else ""))
        return EXIT_BUDGET_SPENT if state["exhausted"] else EXIT_OK

    if args.cmd == "credit":
        state = credit()
        if args.json:
            print(json.dumps(state, sort_keys=True))
        else:
            for slot in SLOTS:
                print(describe_key(state, slot))
            print("total: $%.2f left across the known keys" % state["total_left_usd"])
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
